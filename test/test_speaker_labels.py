from __future__ import annotations

import unittest

from local_asr_server.speaker_labels import apply_speaker_labels


class SpeakerLabelsTests(unittest.TestCase):
    def test_diarized_clusters_receive_stable_fallback_labels(self) -> None:
        payload = {
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "Uno", "provider_speaker": "system:S2"},
                {"id": 1, "start": 1, "end": 2, "text": "Due", "provider_speaker": "system:S1"},
                {"id": 2, "start": 2, "end": 3, "text": "Tre", "provider_speaker": "system:S2"},
            ],
        }

        result = apply_speaker_labels(payload)

        self.assertEqual(result["segments"][0]["speaker_label"], "Speaker 1")
        self.assertEqual(result["segments"][1]["speaker_label"], "Speaker 2")
        self.assertIn("[00:00] Speaker 1: Uno", result["text"])
        self.assertEqual(
            [item["speaker_cluster"] for item in result["stats"]["speaker_attribution"]["mappings"]],
            ["system:S2", "system:S1"],
        )

    def test_manual_name_overrides_fallback_and_rebuilds_text(self) -> None:
        payload = {
            "segments": [
                {"id": 0, "start": 4, "end": 5, "text": "Ciao", "provider_speaker": "system:S1"},
            ],
        }

        result = apply_speaker_labels(payload, {"system:S1": "Paolo"})

        self.assertEqual(result["segments"][0]["speaker_label"], "Paolo")
        self.assertEqual(result["text"], "[00:04] Paolo: Ciao")
        mapping = result["speaker_attribution"]["mappings"][0]
        self.assertEqual(mapping["source"], "manual")
        self.assertEqual(mapping["status"], "accepted")

    def test_text_only_transcription_preserves_canonical_text(self) -> None:
        payload = {
            "text": "Imported transcript without timestamped segments",
            "segments": [],
        }

        result = apply_speaker_labels(payload)

        self.assertEqual(
            result["text"],
            "Imported transcript without timestamped segments",
        )
        self.assertEqual(result["speaker_attribution"]["mappings"], [])

    def test_accepted_visual_name_has_priority_over_fallback(self) -> None:
        payload = {
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "Ciao", "provider_speaker": "system:S1"},
            ],
            "speaker_attribution": {
                "source": "visual_evidence_plus_provider_diarization",
                "mappings": [{
                    "speaker_cluster": "system:S1",
                    "display_name": "Salvatore",
                    "status": "accepted",
                }],
            },
        }

        result = apply_speaker_labels(payload)

        self.assertEqual(result["segments"][0]["speaker_label"], "Salvatore")
        self.assertEqual(result["speaker_attribution"]["mappings"][0]["source"], "visual")

    def test_detected_cluster_without_transcript_overlap_remains_visible(self) -> None:
        payload = {
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "Ciao", "provider_speaker": "system:S1"},
            ],
            "stats": {
                "speaker_diarization": {
                    "clusters_by_track": {"system": ["system:S1", "system:S2"]},
                },
            },
        }

        result = apply_speaker_labels(payload)

        mappings = result["speaker_attribution"]["mappings"]
        self.assertEqual([item["speaker_cluster"] for item in mappings], ["system:S1", "system:S2"])
        self.assertEqual(mappings[0]["transcript_segment_count"], 1)
        self.assertEqual(mappings[1]["transcript_segment_count"], 0)

    def test_no_provider_speaker_repeated_apply(self) -> None:
        payload = {
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "Uno", "speaker_label": "Computer"},
                {"id": 1, "start": 1, "end": 2, "text": "Due", "speaker_label": "Tu"},
            ],
        }

        # First run (no manual names yet)
        result1 = apply_speaker_labels(payload)
        
        # Check that mappings were created and segments got stable display names
        self.assertEqual(result1["segments"][0]["speaker_label"], "Computer")
        self.assertEqual(result1["segments"][1]["speaker_label"], "Tu")

        # Simulate user updating the name of Speaker 1 (original cluster was "Computer")
        # The frontend sends the manual name mapped to the original cluster ID "Computer"
        result2 = apply_speaker_labels(result1, {"Computer": "Walter"})
        
        # Segment speaker_label should update to "Walter"
        self.assertEqual(result2["segments"][0]["speaker_label"], "Walter")

        # Now, simulate a subsequent load/fetch of the transcription (manual_names=None)
        result3 = apply_speaker_labels(result2)
        
        # It should preserve "Walter" (the display name), not revert it
        self.assertEqual(result3["segments"][0]["speaker_label"], "Walter")


    def test_single_turn_override_is_idempotent_and_preserves_raw_attribution(self):
        payload = {
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "Ciao", "provider_speaker": "system:S1"},
                {"id": 1, "start": 1, "end": 2, "text": "Salve", "provider_speaker": "system:S1"},
            ],
            "stats": {
                "speaker_diarization": {"clusters_by_track": {"system": ["system:S1", "system:S2"]}},
                "speaker_review": {"segment_assignments": {"0": "system:S2"}},
                "review_preserve_canonical_text": True,
            },
            "text": "Immutable human transcript.",
        }
        result = apply_speaker_labels(payload)
        self.assertEqual(result["segments"][0]["speaker_group"], "system:S2")
        self.assertEqual(result["segments"][1]["speaker_group"], "system:S1")
        self.assertEqual(result["segments"][0]["provider_speaker"], "system:S1")
        self.assertEqual(result["text"], "Immutable human transcript.")
        again = apply_speaker_labels(result)
        self.assertEqual(again["segments"][0]["speaker_group"], "system:S2")
        self.assertEqual(again["segments"][0]["provider_speaker"], "system:S1")
        mappings = {entry["speaker_cluster"]: entry["display_name"]
                    for entry in again["stats"]["speaker_attribution"]["mappings"]}
        self.assertNotEqual(mappings["system:S1"], mappings["system:S2"],
                            "turn override must not rename the whole original cluster")


if __name__ == "__main__":
    unittest.main()
