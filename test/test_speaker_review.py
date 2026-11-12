from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.catalog import CatalogStore
from local_asr_server.analysis_source_provenance import speaker_attribution_digest
from local_asr_server.server import create_app
from local_asr_server.speaker_labels import apply_speaker_labels
from local_asr_server.speaker_review import (
    project_speaker_action, project_verified_speaker_links, speaker_audio_samples,
)
from local_asr_server.transcription_diarization_review import fingerprint
from local_asr_server.transcriptions import TranscriptionStore
from support import deterministic_settings


def transcription():
    return {
        "recording_id": "meeting-1",
        "text": "Original human-authored source text.",
        "segments": [
            {"id": 0, "start": 0, "end": 4.5, "text": "Ciao", "track_id": "system",
             "provider_speaker": "system:S1", "words": [{"word": "Ciao", "start": 0, "end": 0.3}]},
            {"id": 1, "start": 6, "end": 10.2, "text": "Salve", "track_id": "system",
             "provider_speaker": "system:S2"},
            {"id": 2, "start": 12, "end": 16, "text": "A presto", "track_id": "system",
             "provider_speaker": "system:S1"},
        ],
        "stats": {"speaker_diarization": {
            "engine": "fluidaudio-community-1",
            "clusters_by_track": {"system": ["system:S1", "system:S2", "system:S3"]},
        }},
    }


class SpeakerReviewProjectionTests(unittest.TestCase):
    def test_merge_exclude_restore_preserve_raw_ids_words_and_text(self):
        base = transcription()
        base_copy = copy.deepcopy(base)
        renamed = project_speaker_action(base, action="rename", cluster="system:S1", name="Paolo")
        merged = project_speaker_action(renamed, action="merge", cluster="system:S2", target="system:S1")
        self.assertEqual(merged["text"], base["text"])
        self.assertEqual([x["provider_speaker"] for x in merged["segments"]],
                         [x["provider_speaker"] for x in base_copy["segments"]])
        self.assertEqual([x.get("words") for x in merged["segments"]],
                         [x.get("words") for x in base_copy["segments"]])
        self.assertEqual([x["speaker_name"] for x in merged["segments"]],
                         ["Paolo", "Paolo", "Paolo"])
        self.assertEqual(merged["segments"][1]["speaker_group"], "system:S1")
        hidden = project_speaker_action(merged, action="exclude", cluster="system:S1")
        self.assertEqual([s["speaker_name"] for s in hidden["segments"]],
                         ["Non identificato"] * 3)
        self.assertEqual(hidden["text"], base["text"])
        restored = project_speaker_action(hidden, action="restore", cluster="system:S1")
        self.assertEqual(restored["segments"][1]["speaker_name"], "Paolo")
        unmerged = project_speaker_action(restored, action="restore", cluster="system:S2")
        self.assertEqual(unmerged["segments"][1]["speaker_group"], "system:S2")
        self.assertNotEqual(unmerged["segments"][1]["speaker_name"], "Paolo")
        self.assertEqual(base, base_copy)

    def test_confirm_name_without_rename_preserves_identity_and_raw_content(self):
        original = transcription()
        base = apply_speaker_labels(copy.deepcopy(original))
        for mapping in base["stats"]["speaker_attribution"]["mappings"]:
            if mapping["speaker_cluster"] == "system:S1":
                mapping["display_name"] = "Tu"
                mapping["status"] = "unassigned"
        preserved = copy.deepcopy(base)
        confirmed = project_speaker_action(base, action="confirm", cluster="system:S1")
        by_cluster = {m["speaker_cluster"]: m for m in confirmed["stats"]["speaker_attribution"]["mappings"]}
        self.assertEqual(by_cluster["system:S1"]["display_name"], "Tu")
        self.assertEqual(by_cluster["system:S1"]["status"], "accepted")
        self.assertEqual(by_cluster["system:S2"]["status"], "unassigned")
        self.assertEqual(confirmed["stats"]["speaker_review"]["confirmed"], ["system:S1"])
        self.assertEqual(confirmed["stats"]["speaker_review"]["names"], {})
        self.assertEqual([x["speaker_name"] for x in confirmed["segments"] if
                          x["provider_speaker"] == "system:S1"], ["Tu", "Tu"])
        self.assertEqual(confirmed["text"], preserved["text"],
                         "explicit confirmation must not rewrite the existing read text")
        self.assertEqual(
            [(s["id"], s["text"], s["start"], s["end"], s.get("words"), s["provider_speaker"])
             for s in confirmed["segments"]],
            [(s["id"], s["text"], s["start"], s["end"], s.get("words"), s["provider_speaker"])
             for s in preserved["segments"]],
        )
        reloaded = apply_speaker_labels(copy.deepcopy(confirmed))
        mapping = next(m for m in reloaded["stats"]["speaker_attribution"]["mappings"]
                       if m["speaker_cluster"] == "system:S1")
        self.assertEqual((mapping["display_name"], mapping["status"]), ("Tu", "accepted"))
        self.assertEqual(base, preserved)

    def test_confirm_rejects_placeholder_already_confirmed_or_unavailable_identity(self):
        base = apply_speaker_labels(copy.deepcopy(transcription()))
        with self.assertRaisesRegex(ValueError, "name"):
            project_speaker_action(base, action="confirm", cluster="system:S1")
        for mapping in base["stats"]["speaker_attribution"]["mappings"]:
            if mapping["speaker_cluster"] == "system:S1":
                mapping["display_name"] = "Tu"
        confirmed = project_speaker_action(base, action="confirm", cluster="system:S1")
        with self.assertRaisesRegex(ValueError, "already confirmed"):
            project_speaker_action(confirmed, action="confirm", cluster="system:S1")
        merged = project_speaker_action(base, action="merge", cluster="system:S1",
                                        target="system:S2")
        with self.assertRaisesRegex(ValueError, "unmerged"):
            project_speaker_action(merged, action="confirm", cluster="system:S1")
        excluded = project_speaker_action(base, action="exclude", cluster="system:S1")
        with self.assertRaisesRegex(ValueError, "excluded"):
            project_speaker_action(excluded, action="confirm", cluster="system:S1")

    def test_confirm_can_apply_to_named_voice_without_transcript_turns(self):
        base = apply_speaker_labels(copy.deepcopy(transcription()))
        base["segments"] = []
        for mapping in base["stats"]["speaker_attribution"]["mappings"]:
            if mapping["speaker_cluster"] == "system:S3":
                mapping["display_name"] = "Tu"
        result = project_speaker_action(base, action="confirm", cluster="system:S3")
        mapping = next(m for m in result["stats"]["speaker_attribution"]["mappings"]
                       if m["speaker_cluster"] == "system:S3")
        self.assertEqual((mapping["display_name"], mapping["status"]), ("Tu", "accepted"))
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["text"], base["text"])

    def test_reassign_one_turn_without_mutating_source_or_other_turns(self):
        base = transcription()
        untouched = copy.deepcopy(base)
        moved = project_speaker_action(
            base, action="reassign_turn", cluster="system:S1", target="system:S2", segment_id=0,
        )
        self.assertEqual(moved["segments"][0]["speaker_group"], "system:S2")
        self.assertEqual(moved["segments"][1]["speaker_group"], "system:S2")
        self.assertEqual(moved["segments"][2]["speaker_group"], "system:S1")
        self.assertEqual(moved["segments"][0]["provider_speaker"], "system:S1")
        self.assertEqual(moved["text"], base["text"])
        self.assertEqual(
            [(row["text"], row["start"], row["end"], row.get("words")) for row in moved["segments"]],
            [(row["text"], row["start"], row["end"], row.get("words")) for row in base["segments"]],
        )
        self.assertEqual(moved["stats"]["speaker_review"]["segment_assignments"], {"0": "system:S2"})
        restored = project_speaker_action(
            moved, action="reassign_turn", cluster="system:S1", target=None, segment_id=0,
        )
        self.assertEqual(restored["segments"][0]["speaker_group"], "system:S1")
        self.assertEqual(restored["stats"]["speaker_review"]["segment_assignments"], {})
        self.assertEqual(base, untouched)

    def test_turn_assignment_rejects_duplicate_segment_ids(self):
        base = transcription()
        base["segments"][2]["id"] = 0
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            project_speaker_action(base, action="reassign_turn", cluster="system:S1",
                                   target="system:S2", segment_id=0)

    def test_turn_assignment_rejects_invalid_scope_and_target(self):
        base = transcription()
        for segment_id in (None, -1, 99):
            with self.assertRaises(ValueError):
                project_speaker_action(base, action="reassign_turn", cluster="system:S1",
                                       target="system:S2", segment_id=segment_id)
        with self.assertRaisesRegex(ValueError, "changed speaker"):
            project_speaker_action(base, action="reassign_turn", cluster="system:S2",
                                   target="system:S1", segment_id=0)
        with self.assertRaisesRegex(ValueError, "detected"):
            project_speaker_action(base, action="reassign_turn", cluster="system:S1",
                                   target="system:absent", segment_id=0)
        with self.assertRaisesRegex(ValueError, "original speaker"):
            project_speaker_action(base, action="reassign_turn", cluster="system:S1",
                                   target=None, segment_id=0)
        excluded = project_speaker_action(base, action="exclude", cluster="system:S3")
        with self.assertRaisesRegex(ValueError, "excluded person"):
            project_speaker_action(excluded, action="reassign_turn", cluster="system:S1",
                                   target="system:S3", segment_id=0)

    def test_invalid_target_self_merge_cycle_and_duplicate_exclusion(self):
        base = transcription()
        with self.assertRaisesRegex(ValueError, "Unknown"):
            project_speaker_action(base, action="exclude", cluster="system:unknown")
        with self.assertRaisesRegex(ValueError, "Cannot merge"):
            project_speaker_action(base, action="merge", cluster="system:S1", target="system:S1")
        with self.assertRaisesRegex(ValueError, "Choose a speaker"):
            project_speaker_action(base, action="merge", cluster="system:S1", target="system:absent")
        merged = project_speaker_action(base, action="merge", cluster="system:S1", target="system:S2")
        with self.assertRaisesRegex(ValueError, "non-excluded"):
            project_speaker_action(merged, action="merge", cluster="system:S1", target="system:S3")
        excluded = project_speaker_action(base, action="exclude", cluster="system:S3")
        with self.assertRaisesRegex(ValueError, "already"):
            project_speaker_action(excluded, action="exclude", cluster="system:S3")


class VerifiedAutomaticLinkTests(unittest.TestCase):
    @staticmethod
    def source():
        return {
            "recording_id": "meeting-1",
            "text": "Exact original transcript.",
            "segments": [
                {"id": 1, "start": 0.0, "end": 2.0, "text": "Hello",
                 "track_id": "system", "provider_speaker": "Computer",
                 "speaker_label": "Computer",
                 "words": [{"word": "Hello", "start": 0.0, "end": 0.3}]},
                {"id": 2, "start": 3.0, "end": 5.0, "text": "World",
                 "track_id": "system", "provider_speaker": "Computer",
                 "speaker_label": "Computer"},
            ],
            "source_tracks": [{"id": "system", "label": "Computer"}],
            "stats": {
                "speaker_diarization": {
                    "status": "completed", "engine": "fluidaudio-community-1",
                    "clusters_by_track": {"system": ["system:S1", "system:S2"]},
                },
                "speaker_attribution": {"mappings": [
                    {"speaker_cluster": "system:S1", "display_name": "Tu", "status": "accepted"},
                    {"speaker_cluster": "system:S2", "display_name": "Ismet", "status": "accepted"},
                    {"speaker_cluster": "Computer", "display_name": "Computer", "status": "unassigned"},
                ]},
            },
        }

    @staticmethod
    def timeline():
        return {"truncated": False, "intervals": [
            {"origin": "diarization", "cluster": "system:S1", "track_id": "system",
             "start": 0, "end": 2},
            {"origin": "diarization", "cluster": "system:S2", "track_id": "system",
             "start": 3, "end": 5},
        ]}

    def test_only_verified_native_intervals_link_text_and_keep_all_source_bytes(self):
        source = self.source()
        untouched = copy.deepcopy(source)
        candidate, status, n = project_verified_speaker_links(source, self.timeline())
        self.assertEqual((status, n), ("linked", 2))
        self.assertEqual([x["provider_speaker"] for x in candidate["segments"]],
                         ["system:S1", "system:S2"])
        self.assertEqual([x["speaker_name"] for x in candidate["segments"]], ["Tu", "Ismet"])
        self.assertEqual(candidate["text"], untouched["text"])
        for old, new in zip(source["segments"], candidate["segments"]):
            for field in ("id", "start", "end", "text", "words", "track_id"):
                self.assertEqual(new.get(field), old.get(field))
        self.assertEqual(source, untouched)
        self.assertEqual(candidate["stats"]["speaker_review"]["auto_link_revision"], 1)

    def test_transcript_derived_intervals_are_not_new_diarization_evidence(self):
        timeline = self.timeline()
        for item in timeline["intervals"]:
            item["origin"] = "transcript"
        candidate, status, count = project_verified_speaker_links(self.source(), timeline)
        self.assertIsNone(candidate)
        self.assertEqual((status, count), ("no_verified_diarization", 0))

    def test_missing_timed_text_cannot_be_silently_mapped(self):
        source = self.source()
        for segment in source["segments"]:
            segment["text"] = ""
        candidate, status, count = project_verified_speaker_links(source, self.timeline())
        self.assertIsNone(candidate)
        self.assertEqual((status, count), ("no_timed_text", 0))

    def test_ambiguous_or_partial_speech_never_auto_assigns(self):
        timeline = self.timeline()
        timeline["intervals"][1].update(start=0, end=2)
        source = self.source()
        source["segments"] = source["segments"][:1]
        candidate, status, count = project_verified_speaker_links(source, timeline)
        self.assertIsNone(candidate)
        self.assertEqual((status, count), ("no_safe_matches", 0))
        timeline["truncated"] = True
        self.assertEqual(project_verified_speaker_links(source, timeline)[1],
                         "no_verified_diarization")

    def test_user_confirmed_or_corrected_segments_are_not_replaced(self):
        source = self.source()
        source["segments"][0]["provider_speaker"] = "system:S1"
        source["segments"][0]["speaker_label"] = "Tu"
        source["stats"]["speaker_review"] = {"segment_assignments": {"2": "system:S1"}}
        candidate, status, count = project_verified_speaker_links(source, self.timeline())
        self.assertIsNone(candidate)
        self.assertEqual((status, count), ("no_safe_matches", 0))
        source["stats"]["speaker_review"] = {"auto_link_suppressed": True}
        self.assertEqual(project_verified_speaker_links(source, self.timeline())[1],
                         "suppressed")


class SampleReferenceTests(unittest.TestCase):
    class Store:
        def get(self, rid, include_result=False):
            assert rid == "meeting-1"
            return {"audio_tracks": [
                {"id": "system", "audio_file": "sound.wav"},
                {"id": "mic", "audio_file": "mic.wav"},
            ]}
        def track_audio_path(self, rid, track):
            return Path("/recording") / (track + ".wav")
        def read_speaker_diarization(self, rid):
            return {
                "engine": "fluidaudio-community-1",
                "tracks": {"system": {"segments": [
                    {"speaker": "S1", "start": 0, "end": 5},
                    {"speaker": "S3", "start": 20, "end": 26},
                    {"speaker": "S3", "start": 40, "end": 48},
                    {"speaker": "S2", "start": 6, "end": 11},
                ]}},
            }

    def test_samples_are_bounded_and_raw_fallback_requires_matching_provenance(self):
        base = transcription()
        response = speaker_audio_samples(base, self.Store())
        by_id = {x["speaker_cluster"]: x["samples"] for x in response["speakers"]}
        self.assertTrue(by_id["system:S1"])
        self.assertEqual(by_id["system:S1"][0]["kind"], "transcript")
        self.assertEqual(len(by_id["system:S3"]), 2)
        self.assertEqual(by_id["system:S3"][0]["track_id"], "system")
        self.assertTrue(all(0 < s["end"] - s["start"] <= 8 for x in by_id.values() for s in x))
        base["stats"]["speaker_diarization"]["source"] = "reviewed_meeting"
        response2 = speaker_audio_samples(base, self.Store())
        by_id2 = {x["speaker_cluster"]: x["samples"] for x in response2["speakers"]}
        self.assertEqual(by_id2["system:S3"], [])


class SpeakerReviewPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings_patch = patch("local_asr_server.transcriptions.load_settings",
                                    return_value={"transcriptions_dir": str(root / "transcriptions")})
        self.settings_patch.start()
        self.db = root / "catalog.db"
        self.store = TranscriptionStore(CatalogStore(self.db))
        self.original = self.store.save(transcription(), recording_id="meeting-1")

    def tearDown(self):
        self.settings_patch.stop()
        self.tmp.cleanup()

    def test_commit_reload_and_undo_and_stale_request(self):
        before = self.store.get(self.original["id"])
        candidate = project_speaker_action(before, action="merge", cluster="system:S2",
                                          target="system:S1")
        committed = self.store.apply_reviewed_diarization(
            self.original["id"], candidate=candidate,
            expected_fingerprint=fingerprint(before), preserve_raw_text=True)
        again = TranscriptionStore(CatalogStore(self.db))
        current = again.get(self.original["id"])
        self.assertEqual(current["segments"][1]["speaker_group"], "system:S1")
        self.assertEqual(current["text"], self.original["text"])
        raw_json = again.root / again._file_name_for(self.original["id"])
        self.assertEqual(json.loads(raw_json.read_text())["text"], self.original["text"])
        self.assertEqual(again.reviewed_diarization_undo(self.original["id"]),
                         {"revision_id": committed["revision_id"]})
        with self.assertRaisesRegex(ValueError, "changed"):
            again.apply_reviewed_diarization(
                self.original["id"], candidate=candidate, expected_fingerprint=fingerprint(before))
        undone = again.undo_reviewed_diarization(self.original["id"], committed["revision_id"])
        self.assertEqual(undone["segments"][1]["speaker_group"], "system:S2")


def wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 16_000)
    return buf.getvalue()


class SpeakerReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        settings = deterministic_settings(root, recordings_dir=str(root))
        self.setting_patch = patch("local_asr_server.transcriptions.load_settings",
                                   return_value=settings)
        self.setting_patch.start()
        self.app = create_app(default_model="test-model", recordings_dir=root, enable_auth=False)
        from local_asr_server.app_services import get_services
        service = get_services(self.app)
        recording = service.recordings.create(
            title="Private meeting", mime_type="audio/wav", model="test-model",
            language="it", capture_mode="pc_only")
        self.recording_id = recording["id"]
        service.recordings.append_track_chunk(self.recording_id, "system", 0, wav_bytes())
        service.recordings.finalize(self.recording_id)
        payload = transcription()
        payload["recording_id"] = self.recording_id
        self.id = service.transcriptions.save(payload, recording_id=self.recording_id)["id"]
        self.client = TestClient(self.app)
        self.url = f"/v1/transcriptions/{self.id}/speaker-review"

    def tearDown(self):
        self.client.close()
        self.setting_patch.stop()
        self.tmp.cleanup()

    def test_auto_link_from_verified_local_timeline_persists_and_undo_opts_out(self):
        from local_asr_server.app_services import get_services
        services = get_services(self.app)
        payload = VerifiedAutomaticLinkTests.source()
        payload["recording_id"] = self.recording_id
        payload["segments"][0]["id"] = 0
        payload["segments"][1]["id"] = 1
        saved = services.transcriptions.save(payload, recording_id=self.recording_id)
        transcription_id = saved["id"]
        url = f"/v1/transcriptions/{transcription_id}/speaker-review"
        services.recordings.save_speaker_diarization(self.recording_id, {
            "status": "completed", "engine": "fluidaudio-community-1",
            "tracks": {"system": {"segments": [
                {"speaker": "S1", "start": 0, "end": 2},
                {"speaker": "S2", "start": 3, "end": 5},
            ]}},
        })
        raw_export = services.transcriptions.root / services.transcriptions._file_name_for(transcription_id)
        original_text = json.loads(raw_export.read_text())["text"]
        first = self.client.post(url + "/auto-link")
        self.assertEqual(first.status_code, 200, first.text)
        result = first.json()
        self.assertEqual((result["status"], result["linked_segments"]), ("linked", 2))
        self.assertEqual([s["provider_speaker"] for s in result["transcription"]["segments"]],
                         ["system:S1", "system:S2"])
        self.assertEqual(json.loads(raw_export.read_text())["text"], original_text)
        self.assertEqual(self.client.post(url + "/auto-link").json()["status"],
                         "undo_pending")
        reverted = self.client.post(url + "/undo", json={"revision_id": result["revision_id"]})
        self.assertEqual(reverted.status_code, 200, reverted.text)
        self.assertEqual(reverted.json()["transcription"]["segments"][0]["provider_speaker"],
                         "Computer")
        self.assertEqual(json.loads(raw_export.read_text())["text"], original_text)
        self.assertTrue(services.transcriptions.get(transcription_id)["stats"]["speaker_review"]
                        ["auto_link_suppressed"])
        self.assertEqual(self.client.post(url + "/auto-link").json()["status"],
                         "suppressed")

    def test_read_only_speaker_timeline_without_asr_segments(self):
        from local_asr_server.app_services import get_services
        service = get_services(self.app)
        payload = transcription()
        payload["segments"] = []
        payload["text"] = ""
        saved = service.transcriptions.save(payload, recording_id=self.recording_id)
        url = f"/v1/transcriptions/{saved['id']}/speaker-review"
        timeline = self.client.get(url + "/timeline?start=0&end=1")
        self.assertEqual(timeline.status_code, 200, timeline.text)
        body = timeline.json()
        self.assertEqual(body["coverage"], "none")
        self.assertEqual(body["total_interval_count"], 0)
        self.assertIn("duration_seconds", body)
        self.assertEqual(len(body["overview"]), 3)
        samples = self.client.get(url + "/samples")
        self.assertEqual(samples.status_code, 200, samples.text)
        # A person may be identified even when the transcription has no
        # attributed ASR text. The revision still preserves text/words/timing.
        review = self.client.get(url)
        self.assertEqual(review.status_code, 200, review.text)
        revision = review.json()["fingerprint"]
        renamed = self.client.post(url, json={
            "action": "rename", "cluster": "system:S3", "name": "Giulia",
            "expected_fingerprint": revision,
        })
        self.assertEqual(renamed.status_code, 200, renamed.text)
        changed = renamed.json()["transcription"]
        mapping = next(entry for entry in changed["stats"]["speaker_attribution"]["mappings"]
                       if entry["speaker_cluster"] == "system:S3")
        self.assertEqual(mapping["display_name"], "Giulia")
        self.assertEqual(mapping["status"], "accepted")
        self.assertEqual(changed["text"], "")
        self.assertEqual(changed["segments"], [])
        self.assertEqual(self.client.post(url, json={
            "action": "exclude", "cluster": "system:S3",
            "expected_fingerprint": revision,
        }).status_code, 409)
        undone = self.client.post(url + "/undo", json={
            "revision_id": renamed.json()["revision_id"],
        })
        self.assertEqual(undone.status_code, 200, undone.text)
        restored = undone.json()["transcription"]
        self.assertEqual(restored["segments"], [])
        self.assertEqual(restored["text"], "")
        self.assertNotEqual(
            next(entry["display_name"] for entry in restored["stats"]["speaker_attribution"]["mappings"]
                 if entry["speaker_cluster"] == "system:S3"),
            "Giulia",
        )

    def test_confirm_existing_tu_name_api_with_exact_revision_and_undo(self):
        from local_asr_server.app_services import get_services
        services = get_services(self.app)
        payload = transcription()
        payload["segments"][0]["speaker_label"] = "Tu"
        payload["source_tracks"] = [{"id": "system", "label": "Computer"}]
        saved = services.transcriptions.save(payload, recording_id=self.recording_id)
        url = f"/v1/transcriptions/{saved['id']}/speaker-review"
        raw_path = services.transcriptions.root / services.transcriptions._file_name_for(saved["id"])
        canonical_text = json.loads(raw_path.read_text(encoding="utf-8"))["text"]
        original = self.client.get(f"/v1/transcriptions/{saved['id']}").json()
        before = next(m for m in original["stats"]["speaker_attribution"]["mappings"]
                      if m["speaker_cluster"] == "system:S1")
        self.assertEqual((before["display_name"], before["status"]), ("Tu", "unassigned"))
        revision = self.client.get(url).json()["fingerprint"]
        response = self.client.post(url, json={
            "action": "confirm", "cluster": "system:S1",
            "expected_fingerprint": revision,
        })
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()["transcription"]
        mapping = next(m for m in changed["stats"]["speaker_attribution"]["mappings"]
                       if m["speaker_cluster"] == "system:S1")
        self.assertEqual((mapping["display_name"], mapping["status"]), ("Tu", "accepted"))
        self.assertEqual(changed["segments"][0]["speaker_name"], "Tu")
        self.assertEqual(changed["text"], canonical_text)
        self.assertEqual(json.loads(raw_path.read_text(encoding="utf-8"))["text"],
                         canonical_text, "persisted source text must remain identical")
        self.assertEqual(
            [(s["id"], s["start"], s["end"], s.get("words"), s["provider_speaker"])
             for s in changed["segments"]],
            [(s["id"], s["start"], s["end"], s.get("words"), s["provider_speaker"])
             for s in original["segments"]],
        )
        self.assertEqual(self.client.post(url, json={
            "action": "confirm", "cluster": "system:S1",
            "expected_fingerprint": revision,
        }).status_code, 409)
        reloaded = self.client.get(f"/v1/transcriptions/{saved['id']}").json()
        self.assertEqual(next(m["status"] for m in
            reloaded["stats"]["speaker_attribution"]["mappings"] if
            m["speaker_cluster"] == "system:S1"), "accepted")
        undone = self.client.post(url + "/undo", json={
            "revision_id": response.json()["revision_id"],
        })
        self.assertEqual(undone.status_code, 200, undone.text)
        reverted = undone.json()["transcription"]
        restored_mapping = next(m for m in
            reverted["stats"]["speaker_attribution"]["mappings"] if
            m["speaker_cluster"] == "system:S1")
        self.assertEqual((restored_mapping["display_name"], restored_mapping["status"]),
                         ("Tu", "unassigned"))
        self.assertEqual(reverted["text"], canonical_text)
        self.assertEqual(json.loads(raw_path.read_text(encoding="utf-8"))["text"],
                         canonical_text)

    def test_single_turn_api_revision_and_undo(self):
        info = self.client.get(self.url).json()
        before = self.client.get(f"/v1/transcriptions/{self.id}").json()
        response = self.client.post(self.url, json={
            "action": "reassign_turn", "cluster": "system:S1", "target": "system:S2",
            "segment_id": 0, "expected_fingerprint": info["fingerprint"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["transcription"]
        self.assertEqual(result["segments"][0]["speaker_group"], "system:S2")
        self.assertEqual(result["segments"][2]["speaker_group"], "system:S1")
        self.assertEqual(result["segments"][0]["provider_speaker"], "system:S1")
        self.assertEqual(result["segments"][0]["words"], before["segments"][0]["words"])
        # GET may decorate the transcript for reading. The original exported
        # source text, not that read projection, is the preservation invariant.
        self.assertEqual(result["text"], "Original human-authored source text.")
        from local_asr_server.app_services import get_services
        store = get_services(self.app).transcriptions
        raw_path = store.root / store._file_name_for(self.id)
        self.assertEqual(json.loads(raw_path.read_text())["text"],
                         "Original human-authored source text.")
        conflict = self.client.post(self.url, json={
            "action": "reassign_turn", "cluster": "system:S1",
            "target": "system:S3", "segment_id": 0,
            "expected_fingerprint": info["fingerprint"],
        })
        self.assertEqual(conflict.status_code, 409)
        undone = self.client.post(self.url + "/undo", json={"revision_id": response.json()["revision_id"]})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["transcription"]["segments"][0]["speaker_group"], "system:S1")

    def test_meeting_exposes_stale_analysis_after_speaker_correction_and_undo(self):
        from local_asr_server.app_services import get_services
        services = get_services(self.app)
        current = services.transcriptions.get(self.id)
        original_result = {
            "markdown": "Original analysis rendered as-is.",
            "source_snapshot": {
                "transcription_id": self.id,
                "speaker_attribution_sha256": speaker_attribution_digest(current),
            },
            "user_edits": [{"id": "preserve-this-edit"}],
        }
        services.catalog.create_analysis_run({
            "id": "source-fingerprint-run", "scope_type": "transcription", "scope_id": self.id,
            "recording_id": self.recording_id, "transcription_id": self.id,
            "analysis_type": "meeting_brief", "provider": "mock", "input_hash": "a" * 64,
            "status": "completed", "created_at": 1.0, "result": original_result,
        })
        url = f"/v1/meetings/{self.recording_id}"
        before = self.client.get(url)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["latest_analysis"]["meeting_brief"]
                         ["speaker_source_validity"]["status"], "current")
        revision = self.client.get(self.url).json()["fingerprint"]
        changed = self.client.post(self.url, json={
            "action": "reassign_turn", "cluster": "system:S1", "target": "system:S2",
            "segment_id": 0, "expected_fingerprint": revision,
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        after = self.client.get(url)
        self.assertEqual(after.status_code, 200, after.text)
        run = after.json()["latest_analysis"]["meeting_brief"]
        self.assertEqual(run["speaker_source_validity"]["status"], "stale")
        self.assertEqual(run["result"]["user_edits"], [{"id": "preserve-this-edit"}])
        self.assertEqual(after.json()["analysis_runs"][0]["speaker_source_validity"]["status"], "stale")
        self.assertEqual(services.catalog.get_analysis_run("source-fingerprint-run")["result"],
                         original_result, "read projection must not mutate saved user edits")
        undone = self.client.post(self.url + "/undo",
                                  json={"revision_id": changed.json()["revision_id"]})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(self.client.get(url).json()["latest_analysis"]
                         ["meeting_brief"]["speaker_source_validity"]["status"], "current")

    def test_revision_conflict_merge_and_undo(self):
        info = self.client.get(self.url)
        self.assertEqual(info.status_code, 200, info.text)
        rev = info.json()["fingerprint"]
        saved = self.client.post(self.url, json={
            "action": "merge", "cluster": "system:S2", "target": "system:S1",
            "expected_fingerprint": rev})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["transcription"]["text"],
                         "Original human-authored source text.")
        from local_asr_server.app_services import get_services
        store = get_services(self.app).transcriptions
        raw_path = store.root / store._file_name_for(self.id)
        self.assertEqual(json.loads(raw_path.read_text())["text"],
                         "Original human-authored source text.")
        self.assertEqual(self.client.post(self.url, json={
            "action": "exclude", "cluster": "system:S3",
            "expected_fingerprint": rev}).status_code, 409)
        self.assertEqual(self.client.get(self.url).json()["undo"]["revision_id"],
                         saved.json()["revision_id"])
        restored = self.client.post(self.url + "/undo",
                                    json={"revision_id": saved.json()["revision_id"]})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["transcription"]["segments"][1]["speaker_group"],
                         "system:S2")
        samples = self.client.get(self.url + "/samples")
        self.assertEqual(samples.status_code, 200, samples.text)
        self.assertEqual(samples.json()["recording_id"], self.recording_id)
        timeline = self.client.get(self.url + "/timeline?start=0&end=30")
        self.assertEqual(timeline.status_code, 200, timeline.text)
        self.assertEqual(timeline.json()["coverage"], "transcript")
        self.assertEqual(timeline.json()["recording_id"], self.recording_id)
        self.assertEqual([row["cluster"] for row in timeline.json()["intervals"]],
                         ["system:S1", "system:S2", "system:S1"])
        self.assertTrue(all("text" not in row for row in timeline.json()["intervals"]))
        self.assertEqual(
            self.client.get(self.url + "/timeline?start=30&end=10").status_code, 409)



if __name__ == "__main__":
    unittest.main()
