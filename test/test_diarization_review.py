from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_asr_server.catalog import CatalogStore
from local_asr_server.transcriptions import TranscriptionStore
from local_asr_server.transcription_diarization_review import (
    REVIEW_JOB_TYPE, fingerprint, project_review,
)


def _payload(recording_id="recording-id"):
    return {
        "recording_id": recording_id,
        "text": "The original transcript. It must stay exactly as written.",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Hello team",
             "track_id": "mic", "source": "mic", "provider_speaker": "mic:old", "speaker_label": "Old mic", "words": [{"word": "Hello", "start": 0.0, "end": 0.6}]},
            {"id": 1, "start": 2.0, "end": 4.0, "text": "Next topic",
             "track_id": "system", "source": "system", "provider_speaker": "system:old", "speaker_label": "Old remote", "words": [{"word": "Next", "start": 2.0, "end": 2.6}]},
            {"id": 2, "start": 4.0, "end": 6.0, "text": "I agree",
             "track_id": "system", "source": "system", "provider_speaker": "system:old", "speaker_label": "Old remote"},
        ],
        "source_tracks": [
            {"id": "mic", "label": "Local mic", "source": "mic"},
            {"id": "system", "label": "Computer", "source": "system"},
        ],
        "stats": {"time_total_seconds": 6},
    }


def _job(transcription):
    return {
        "type": REVIEW_JOB_TYPE,
        "status": "completed",
        "result": {
            "scope": "full",
            "track_id": "system",
            "transcription_fingerprint": fingerprint(transcription),
            "runs": [{
                "key": "community-1", "status": "completed",
                "timeline": [
                    {"speaker": "S1", "start": 2, "end": 4},
                    {"speaker": "S2", "start": 4, "end": 6},
                ],
            }],
        },
    }


class CommunityReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mock_settings = patch(
            "local_asr_server.transcriptions.load_settings",
            return_value={"transcriptions_dir": str(self.root / "transcripts")},
        )
        self.mock_review = patch(
            "local_asr_server.transcription_diarization_review.load_settings",
            return_value={"speaker_diarization_minimum_overlap": 0.25},
        )
        self.mock_settings.start()
        self.mock_review.start()
        self.db = self.root / "catalog.db"
        self.store = TranscriptionStore(CatalogStore(self.db))
        self.saved = self.store.save(_payload(), recording_id="recording-id")
        self.transcription_id = self.saved["id"]

    def tearDown(self):
        self.mock_review.stop()
        self.mock_settings.stop()
        self.tmp.cleanup()

    def test_preview_is_pure_and_text_time_words_remain_unchanged_after_apply_and_undo(self):
        original = self.store.get(self.transcription_id)
        old = copy.deepcopy(original)
        job = _job(original)
        review = project_review(original, job)
        self.assertEqual(self.store.get(self.transcription_id), old)
        self.assertEqual(review["candidate"]["text"], old["text"])
        self.assertEqual(review["assigned_segments"], 2)
        self.assertEqual(review["cluster_count"], 3)  # two remote speakers plus mic
        self.assertEqual(review["changed_segments"], 3)
        self.assertEqual(review["candidate"]["segments"][0]["provider_speaker"], "mic:S1")
        self.assertEqual([seg["provider_speaker"] for seg in review["candidate"]["segments"][1:]],
                         ["system:S1", "system:S2"])

        committed = self.store.apply_reviewed_diarization(
            self.transcription_id,
            candidate=review["candidate"],
            expected_fingerprint=fingerprint(original),
        )
        self.assertEqual(committed["transcription"]["text"], old["text"])
        self.assertEqual(self.store.get(self.transcription_id)["text"], old["text"])
        self.assertEqual(
            [(s["start"], s["end"], s["text"], s.get("words")) for s in self.store.get(self.transcription_id)["segments"]],
            [(s["start"], s["end"], s["text"], s.get("words")) for s in old["segments"]],
        )
        reloaded = TranscriptionStore(CatalogStore(self.db))
        token = reloaded.reviewed_diarization_undo(self.transcription_id)
        self.assertEqual(token, {"revision_id": committed["revision_id"]})
        restored = reloaded.undo_reviewed_diarization(self.transcription_id, committed["revision_id"])
        self.assertEqual(restored["text"], old["text"])
        self.assertEqual(reloaded.get(self.transcription_id)["text"], old["text"])
        self.assertIsNone(reloaded.reviewed_diarization_undo(self.transcription_id))
        self.assertEqual(
            [s.get("provider_speaker") for s in restored["segments"]],
            [s.get("provider_speaker") for s in self.saved["segments"]],
        )

    def test_stale_preview_and_stale_undo_never_overwrite_newer_user_edits(self):
        original = self.store.get(self.transcription_id)
        review = project_review(original, _job(original))
        self.store.update_speaker_names(self.transcription_id, {"mic:old": "My name"})
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.apply_reviewed_diarization(
                self.transcription_id,
                candidate=review["candidate"],
                expected_fingerprint=fingerprint(original),
            )
        fresh = self.store.get(self.transcription_id)
        preview = project_review(fresh, _job(fresh))
        result = self.store.apply_reviewed_diarization(
            self.transcription_id, candidate=preview["candidate"],
            expected_fingerprint=fingerprint(fresh),
        )
        self.store.update_speaker_names(self.transcription_id, {"system:S1": "Colleague"})
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.undo_reviewed_diarization(self.transcription_id, result["revision_id"])
        self.assertIsNone(self.store.reviewed_diarization_undo(self.transcription_id))

    def test_full_length_and_unchanged_transcription_are_required(self):
        original = self.store.get(self.transcription_id)
        job = _job(original)
        job["result"]["scope"] = "sample"
        with self.assertRaisesRegex(ValueError, "complete"):
            project_review(original, job)
        job["result"]["scope"] = "full"
        job["result"]["runs"][0]["timeline"] = []
        with self.assertRaisesRegex(ValueError, "no speaker"):
            project_review(original, job)
        stale = copy.deepcopy(original)
        stale["segments"][1]["text"] = "changed while processing"
        with self.assertRaisesRegex(ValueError, "changed"):
            project_review(stale, _job(original))


if __name__ == "__main__":
    unittest.main()
