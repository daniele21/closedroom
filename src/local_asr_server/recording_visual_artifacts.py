from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from local_asr_server.visual_intelligence.contracts import (
    VISUAL_OBSERVATIONS_FILE,
    VISUAL_PROCESSING_CHECKPOINT,
    VISUAL_ROUTING_FILE,
)


class VisualArtifactStore:
    """Own low-level visual artifact topology inside a recording session.

    RecordingStore keeps recording lifecycle, admission, locking, and catalog
    projection. This collaborator owns only visual frame/JSONL artifact mechanics.
    """

    @staticmethod
    def staging_directory(session_dir: Path) -> Path:
        return session_dir / ".visual-staging"

    def frame_manifest_path(self, session_dir: Path) -> Path:
        return self.staging_directory(session_dir) / "manifest.jsonl"

    @staticmethod
    def observations_path(session_dir: Path) -> Path:
        return session_dir / VISUAL_OBSERVATIONS_FILE

    @staticmethod
    def routing_path(session_dir: Path) -> Path:
        return session_dir / VISUAL_ROUTING_FILE

    @staticmethod
    def checkpoint_path(session_dir: Path) -> Path:
        return session_dir / VISUAL_PROCESSING_CHECKPOINT

    def stage_frame(
        self,
        session_dir: Path,
        *,
        sequence: int,
        timestamp: float,
        content: bytes,
        write_bytes_atomic: Callable[[Path, bytes], None],
        conflict_error: Callable[[str], Exception],
    ) -> dict[str, Any]:
        staging = self.staging_directory(session_dir)
        staging.mkdir(mode=0o700, parents=True, exist_ok=True)
        manifest = self.frame_manifest_path(session_dir)
        if manifest.exists():
            lines = manifest.read_text(encoding="utf-8").splitlines()
            if lines:
                previous = json.loads(lines[-1])
                if sequence <= int(previous["sequence"]) or timestamp < float(previous["timestamp"]):
                    raise conflict_error("Visual frame sequence and timestamp must be monotonic")

        path = staging / f"frame-{sequence:08d}.jpg"
        if path.exists():
            raise conflict_error(f"Visual frame sequence already exists: {sequence}")
        write_bytes_atomic(path, content)
        with manifest.open("a", encoding="utf-8") as output:
            output.write(json.dumps({
                "sequence": sequence,
                "timestamp": timestamp,
                "file": path.name,
            }) + "\n")
            output.flush()
            os.fsync(output.fileno())
        return {"sequence": sequence, "timestamp": timestamp, "bytes": len(content)}

    def list_frames(self, session_dir: Path) -> list[dict[str, Any]]:
        staging = self.staging_directory(session_dir)
        manifest = self.frame_manifest_path(session_dir)
        if not manifest.exists():
            return []
        frames: list[dict[str, Any]] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            path = (staging / str(item.get("file") or "")).resolve()
            if path.parent == staging.resolve() and path.is_file():
                frames.append({**item, "path": path})
        return sorted(frames, key=lambda item: int(item["sequence"]))

    def reset_observations(self, session_dir: Path) -> None:
        self.observations_path(session_dir).unlink(missing_ok=True)

    def append_observation(self, session_dir: Path, observation: dict[str, Any]) -> None:
        with self.observations_path(session_dir).open("a", encoding="utf-8") as output:
            output.write(json.dumps(observation, ensure_ascii=False) + "\n")

    def reset_routing(self, session_dir: Path) -> None:
        self.routing_path(session_dir).unlink(missing_ok=True)

    @staticmethod
    def read_valid_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                items.append(item)
        return items
