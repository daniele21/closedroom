from __future__ import annotations

import copy
import unittest

from local_asr_server.analysis_source_provenance import (
    project_speaker_source_validity,
    speaker_attribution_digest,
)
from local_asr_server.speaker_labels import apply_speaker_labels


def source():
    return {
        "id": "trans-1",
        "segments": [
            {"id": 0, "start": 0, "end": 2, "provider_speaker": "system:S1",
             "speaker_group": "system:S1", "speaker_label": "Speaker 1", "speaker_name": "Speaker 1",
             "text": "Private meeting words."},
            {"id": 1, "start": 2, "end": 4, "provider_speaker": "system:S2",
             "speaker_group": "system:S2", "speaker_label": "Speaker 2", "speaker_name": "Speaker 2",
             "text": "Some private response."},
        ],
        "stats": {},
    }


def run(transcription, *, result=None, transcription_id="trans-1", status="completed"):
    return {
        "id": "analysis-1",
        "transcription_id": transcription_id,
        "status": status,
        "result": result if result is not None else {
            "source_snapshot": {
                "transcription_id": transcription["id"],
                "speaker_attribution_sha256": speaker_attribution_digest(transcription),
            },
            "generated": {"summary": "Do not change user-generated notes."},
        },
    }


class SpeakerAnalysisProvenanceTests(unittest.TestCase):
    def test_identity_tracks_rename_and_group_without_copying_raw_text(self):
        original = source()
        digest = speaker_attribution_digest(original)
        changed = copy.deepcopy(original)
        changed["stats"]["speaker_review"] = {"segment_assignments": {"0": "system:S2"}}
        self.assertNotEqual(speaker_attribution_digest(changed), digest)
        changed = copy.deepcopy(original)
        changed["stats"]["speaker_review"] = {"names": {"system:S1": "Giulia"}}
        self.assertNotEqual(speaker_attribution_digest(changed), digest)
        changed = copy.deepcopy(original)
        changed["segments"][0]["text"] = "A harmless text edit."
        self.assertEqual(speaker_attribution_digest(changed), digest)

    def test_raw_catalog_and_decorated_get_share_speaker_identity(self):
        original = source()
        untouched = copy.deepcopy(original)
        decorated = apply_speaker_labels(copy.deepcopy(original))
        self.assertEqual(speaker_attribution_digest(original), speaker_attribution_digest(decorated))
        self.assertEqual(original, untouched, "provenance must never mutate source")
        original["stats"]["speaker_review"] = {"names": {"system:S1": "Giulia"}}
        decorated = apply_speaker_labels(copy.deepcopy(original))
        self.assertEqual(speaker_attribution_digest(original), speaker_attribution_digest(decorated))

    def test_current_stale_undo_does_not_mutate_persisted_result(self):
        original = source()
        stored = run(original)
        untouched = copy.deepcopy(stored)
        self.assertEqual(project_speaker_source_validity([stored], original)[0]
                         ["speaker_source_validity"]["status"], "current")
        corrected = copy.deepcopy(original)
        corrected["stats"]["speaker_review"] = {"segment_assignments": {"0": "system:S2"}}
        stale = project_speaker_source_validity([stored], corrected)[0]
        self.assertEqual(stale["speaker_source_validity"],
                         {"status": "stale", "reason": "speaker_attribution_changed"})
        self.assertEqual(stale["result"], stored["result"])
        self.assertEqual(stored, untouched)
        self.assertEqual(project_speaker_source_validity([stored], original)[0]
                         ["speaker_source_validity"]["status"], "current")

    def test_legacy_review_is_unverifiable_instead_of_false_current(self):
        original = source()
        stored = run(original, result={"generated": {"summary": "Legacy notes"}})
        original["stats"]["speaker_review"] = {"segment_assignments": {"0": "system:S2"}}
        self.assertEqual(project_speaker_source_validity([stored], original)[0]
                         ["speaker_source_validity"]["status"], "unverifiable")
        original["stats"] = {}
        self.assertNotIn("speaker_source_validity",
                         project_speaker_source_validity([stored], original)[0])

    def test_invalid_or_unrelated_provenance_does_not_claim_current(self):
        original = source()
        unrelated = run(original, transcription_id="other")
        self.assertNotIn("speaker_source_validity",
                         project_speaker_source_validity([unrelated], original)[0])
        running = run(original, status="running")
        self.assertNotIn("speaker_source_validity",
                         project_speaker_source_validity([running], original)[0])
        original["stats"]["speaker_review"] = {"names": {"system:S1": "Paolo"}}
        for snapshot in [
            {"transcription_id": "trans-1", "speaker_attribution_sha256": "x" * 64},
            {"transcription_id": "other", "speaker_attribution_sha256": speaker_attribution_digest(original)},
        ]:
            broken = run(original, result={"source_snapshot": snapshot})
            self.assertEqual(project_speaker_source_validity([broken], original)[0]
                             ["speaker_source_validity"]["status"], "unverifiable")


if __name__ == "__main__":
    unittest.main()
