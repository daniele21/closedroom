from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_asr_server.catalog import CatalogStore
from local_asr_server.settings import load_settings
from local_asr_server.speaker_labels import apply_speaker_labels


class TranscriptionStore:
    def __init__(self, catalog: CatalogStore | None = None):
        self.catalog = catalog or CatalogStore(self.root / "closedroom.db")
        self.catalog.import_transcriptions_dir(self.root)

    @property
    def root(self) -> Path:
        settings = load_settings()
        path = Path(settings["transcriptions_dir"]).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sync(self) -> None:
        self.catalog.import_transcriptions_dir(self.root)

    def _file_name_for(self, transcription_id: str) -> str | None:
        with self.catalog.connection() as conn:
            row = conn.execute(
                "SELECT file_name FROM transcriptions WHERE id = ?",
                (transcription_id,),
            ).fetchone()
        return row["file_name"] if row else None

    def _write_export_files(self, filename_base: str, meta: dict[str, Any]) -> str:
        json_path = self.root / f"{filename_base}.json"
        txt_path = self.root / f"{filename_base}.txt"
        json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        txt_path.write_text(meta.get("text", ""), encoding="utf-8")
        return json_path.name

    def save(self, payload: dict[str, Any], audio_filename: str = "", recording_id: str | None = None) -> dict[str, Any]:
        transcription_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"transcript_{formatted_time}_{transcription_id[:8]}"

        meta = {
            "id": transcription_id,
            "timestamp": timestamp,
            "audio_filename": audio_filename or "uploaded_audio",
            "recording_id": recording_id or payload.get("recording_id") or "",
            "model": payload.get("model", "default"),
            "language": payload.get("language", "it"),
            "text": payload.get("text", ""),
            "segments": payload.get("segments", []),
            "stats": payload.get("stats", {}),
            "asr_provider": payload.get("asr_provider") or payload.get("stats", {}).get("asr_provider"),
            "backend": payload.get("backend") or payload.get("stats", {}).get("backend"),
            "provider_options": payload.get("provider_options") or payload.get("stats", {}).get("provider_options") or {},
            "analysis": payload.get("analysis"),
            "merged_sources": payload.get("merged_sources"),
            "source_tracks": payload.get("source_tracks"),
            "speaker_diarization": payload.get("speaker_diarization"),
            "speaker_attribution": payload.get("speaker_attribution"),
            "insight_candidates": payload.get("insight_candidates"),
            "diagnostics": payload.get("diagnostics"),
            "outcome_status": payload.get("outcome_status"),
        }

        file_name = self._write_export_files(filename_base, meta)
        self.catalog.upsert_transcription(meta, file_name=file_name)
        return meta

    def latest_for_recording(self, recording_id: str) -> dict[str, Any] | None:
        """Return the latest persisted transcription for a recording, if any."""
        item = self.catalog.find_transcription_for_recording(recording_id)
        if item is None:
            return None
        file_name = self._file_name_for(item["id"])
        if not file_name:
            return None
        try:
            return apply_speaker_labels(
                json.loads((self.root / file_name).read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError):
            return None

    def merge(self, transcription_ids: list[str], title: str | None = None) -> dict[str, Any]:
        if not transcription_ids or len(transcription_ids) < 2:
            raise ValueError("Devi selezionare almeno due trascrizioni da unire.")

        transcriptions_to_merge = []
        for t_id in transcription_ids:
            try:
                transcriptions_to_merge.append(self.get(t_id))
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"Trascrizione con ID {t_id} non trovata.") from exc

        if not title or not title.strip():
            title = f"Trascrizione Unita - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        merged_text_parts = []
        merged_segments = []
        merged_sources = []
        current_offset = 0.0
        segment_id_counter = 0
        total_time = 0.0
        languages: list[str] = []
        models: list[str] = []

        for tr in transcriptions_to_merge:
            audio_filename = tr.get("audio_filename") or "Sorgente"
            merged_sources.append({
                "id": tr["id"],
                "audio_filename": audio_filename,
                "recording_id": tr.get("recording_id") or "",
            })

            if tr.get("text"):
                merged_text_parts.append(f"--- {audio_filename} ---\n{tr['text']}")

            max_end = 0.0
            for seg in tr.get("segments", []):
                shifted_seg = seg.copy()
                shifted_seg["id"] = segment_id_counter
                segment_id_counter += 1
                shifted_seg["start"] = seg["start"] + current_offset
                shifted_seg["end"] = seg["end"] + current_offset
                max_end = max(max_end, shifted_seg["end"])
                merged_segments.append(shifted_seg)

            current_offset += max_end
            total_time += tr.get("stats", {}).get("time_total_seconds", 0.0)
            if tr.get("language") and tr["language"] not in languages:
                languages.append(tr["language"])
            if tr.get("model") and tr["model"] not in models:
                models.append(tr["model"])

        merged_meta = self.save(
            {
                "text": "\n\n".join(merged_text_parts),
                "segments": merged_segments,
                "merged_sources": merged_sources,
                "language": ", ".join(languages) if languages else "it",
                "model": ", ".join([m.split("/")[-1] for m in models]) if models else "default",
                "stats": {"time_total_seconds": total_time},
            },
            audio_filename=title,
        )

        for t_id in transcription_ids:
            self._update_export_flags(t_id, hidden=True, merged_into=merged_meta["id"])
            self.catalog.update_transcription_flags(t_id, hidden=True, merged_into=merged_meta["id"])

        return merged_meta

    def split(self, transcription_id: str) -> list[str]:
        merged_data = self.get(transcription_id)
        restored_ids = []
        for src in merged_data.get("merged_sources", []) or []:
            src_id = src.get("id")
            if not src_id:
                continue
            self._update_export_flags(src_id, hidden=False, merged_into=None)
            self.catalog.update_transcription_flags(src_id, hidden=False, merged_into=None)
            restored_ids.append(src_id)

        self.delete(transcription_id)
        return restored_ids

    def _update_export_flags(self, transcription_id: str, *, hidden: bool, merged_into: str | None) -> None:
        file_name = self._file_name_for(transcription_id)
        if not file_name:
            return
        path = self.root / file_name
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if hidden:
                data["hidden"] = True
                data["merged_into"] = merged_into
            else:
                data.pop("hidden", None)
                data.pop("merged_into", None)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            return

    def list(self, page: int = 1, limit: int = 10) -> tuple[list[dict[str, Any]], int]:
        return self.catalog.list_transcriptions(page=page, limit=limit)

    def get(self, transcription_id: str) -> dict[str, Any]:
        item = self.catalog.get_transcription(transcription_id)
        if not item:
            raise FileNotFoundError("Transcription not found")
        return apply_speaker_labels(item)

    def find_for_recording(self, recording_id: str, audio_filename: str = "") -> dict[str, Any] | None:
        return self.catalog.find_transcription_for_recording(recording_id, audio_filename)

    def save_analysis(self, transcription_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
        data = self.get(transcription_id)
        file_name = self._file_name_for(transcription_id)
        analysis_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": analysis,
        }
        data["analysis"] = analysis_payload

        if file_name:
            json_path = self.root / file_name
            if json_path.exists():
                try:
                    export_data = json.loads(json_path.read_text(encoding="utf-8"))
                    export_data["analysis"] = analysis_payload
                    json_path.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass

        self.catalog.update_analysis(transcription_id, analysis_payload)
        return data

    def update_speaker_names(self, transcription_id: str, names: dict[str, str]) -> dict[str, Any]:
        file_name = self._file_name_for(transcription_id)
        if not file_name:
            raise FileNotFoundError("Transcription not found")
        json_path = self.root / file_name
        if not json_path.exists():
            raise FileNotFoundError("Transcription export not found")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        updated = apply_speaker_labels(data, names)
        self._write_export_files(json_path.stem, updated)
        self.catalog.upsert_transcription(updated, file_name=file_name)
        return updated

    def replace_diarization(
        self,
        transcription_id: str,
        updated: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a speaker-only transcript revision without creating a new ASR result."""
        file_name = self._file_name_for(transcription_id)
        if not file_name:
            raise FileNotFoundError("Transcription not found")
        json_path = self.root / file_name
        if not json_path.exists():
            raise FileNotFoundError("Transcription export not found")
        if str(updated.get("id") or "") != transcription_id:
            raise ValueError("Diarization update does not match the target transcription")

        self._write_export_files(json_path.stem, updated)
        self.catalog.upsert_transcription(updated, file_name=file_name)
        return updated

    def replace_visual_intelligence(
        self,
        transcription_id: str,
        updated: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist visual enrichment in place without creating a new ASR result."""
        file_name = self._file_name_for(transcription_id)
        if not file_name:
            raise FileNotFoundError("Transcription not found")
        json_path = self.root / file_name
        if not json_path.exists():
            raise FileNotFoundError("Transcription export not found")
        if str(updated.get("id") or "") != transcription_id:
            raise ValueError("Visual update does not match the target transcription")

        self._write_export_files(json_path.stem, updated)
        self.catalog.upsert_transcription(updated, file_name=file_name)
        return updated

    def delete(self, transcription_id: str) -> bool:
        file_name = self._file_name_for(transcription_id)
        if not file_name:
            return False

        json_path = self.root / file_name
        if json_path.exists():
            json_path.unlink()
        txt_path = json_path.with_suffix(".txt")
        if txt_path.exists():
            txt_path.unlink()

        self.catalog.delete_transcription(transcription_id)
        return True
