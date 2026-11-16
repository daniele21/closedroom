from __future__ import annotations

import unittest
import copy

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

    def test_verified_microphone_track_is_tu_without_manual_confirmation(self) -> None:
        payload = {
            "text": "Original recording words.",
            "source_tracks": [
                {"id": "mic", "source": "mic", "label": "Tu"},
                {"id": "system", "source": "system", "label": "Computer"},
            ],
            "segments": [
                {"id": 0, "track_id": "mic", "start": 4.0, "end": 5.0,
                 "text": "Ciao", "provider_speaker": "mic:S1",
                 "speaker_label": "Tu", "words": [{"word": "Ciao", "start": 4.0}]},
                {"id": 1, "track_id": "system", "start": 6.0, "end": 7.0,
                 "text": "Buongiorno", "provider_speaker": "system:S1",
                 "speaker_label": "Computer"},
            ],
            "stats": {
                "speaker_diarization": {
                    "status": "completed",
                    "clusters_by_track": {
                        "mic": ["mic:S1"], "system": ["system:S1"],
                    },
                },
                "speaker_attribution": {"mappings": [
                    {"speaker_cluster": "mic:S1", "display_name": "Tu",
                     "status": "unassigned", "source": "diarization"},
                    {"speaker_cluster": "system:S1", "display_name": "Computer",
                     "status": "unassigned"},
                ]},
            },
        }
        original = copy.deepcopy(payload)
        result = apply_speaker_labels(payload)
        by_id = {m["speaker_cluster"]: m for m in result["stats"]["speaker_attribution"]["mappings"]}
        self.assertEqual((by_id["mic:S1"]["display_name"], by_id["mic:S1"]["status"]),
                         ("Tu", "accepted"))
        self.assertEqual(by_id["system:S1"]["status"], "unassigned")
        self.assertEqual(result["segments"][0]["speaker_name"], "Tu")
        self.assertEqual(result["segments"][0]["provider_speaker"], "mic:S1")
        self.assertEqual(result["segments"][0]["words"], original["segments"][0]["words"])
        # Reprojection must be stable across reopening, without persisting
        # a synthetic user "confirm" action.
        repeat = apply_speaker_labels(result)
        self.assertEqual(
            next(m["status"] for m in repeat["stats"]["speaker_attribution"]["mappings"]
                 if m["speaker_cluster"] == "mic:S1"), "accepted",
        )
        self.assertFalse(result["stats"].get("speaker_review"))

    def test_no_mic_provenance_never_inferrs_a_person(self) -> None:
        common = {
            "source_tracks": [{"id": "system", "source": "system", "label": "Computer"}],
            "segments": [
                {"id": 1, "start": 4, "end": 5, "text": "Uno",
                 "track_id": "system", "provider_speaker": "mic:S1",
                 "speaker_label": "Tu"},
            ],
        }
        label_only = apply_speaker_labels(__import__("copy").deepcopy(common))
        self.assertEqual(label_only["stats"]["speaker_attribution"]["mappings"][0]["status"],
                         "unassigned")
        common["source_tracks"].append({"id": "mic", "source": "mic", "label": "Tu"})
        wrong_track = apply_speaker_labels(__import__("copy").deepcopy(common))
        self.assertEqual(wrong_track["stats"]["speaker_attribution"]["mappings"][0]["status"],
                         "unassigned")
        common["segments"][0]["provider_speaker"] = "mic:S2"
        common["segments"][0]["track_id"] = "mic"
        other_cluster = apply_speaker_labels(__import__("copy").deepcopy(common))
        self.assertEqual(other_cluster["stats"]["speaker_attribution"]["mappings"][0]["status"],
                         "unassigned")
        common["segments"][0]["provider_speaker"] = "mic:S1"
        common["source_tracks"][1]["source"] = "system"
        invalid_source = apply_speaker_labels(__import__("copy").deepcopy(common))
        self.assertEqual(invalid_source["stats"]["speaker_attribution"]["mappings"][0]["status"],
                         "unassigned")

    def test_mic_default_preserves_explicit_rename_exclusion_and_merge(self) -> None:
        payload = {
            "source_tracks": [{"id": "mic", "source": "mic", "label": "Tu"}],
            "text": "Immutable original",
            "segments": [
                {"id": 0, "start": 0, "end": 1, "text": "One",
                 "provider_speaker": "mic:S1", "track_id": "mic"},
                {"id": 1, "start": 2, "end": 3, "text": "Two",
                 "provider_speaker": "system:S1", "track_id": "system"},
            ],
            "stats": {
                "speaker_diarization": {
                    "clusters_by_track": {"mic": ["mic:S1"], "system": ["system:S1"]}},
                "speaker_review": {
                    "names": {"mic:S1": "Daniele"},
                    "excluded": [],
                    "merged_into": {},
                    "segment_assignments": {},
                },
                "review_preserve_canonical_text": True,
            },
        }
        renamed = apply_speaker_labels(__import__("copy").deepcopy(payload))
        mic = next(m for m in renamed["stats"]["speaker_attribution"]["mappings"]
                   if m["speaker_cluster"] == "mic:S1")
        self.assertEqual((mic["display_name"], mic["status"]), ("Daniele", "accepted"))
        self.assertEqual(renamed["text"], "Immutable original")
        excluded = __import__("copy").deepcopy(payload)
        excluded["stats"]["speaker_review"]["excluded"] = ["mic:S1"]
        hidden = apply_speaker_labels(excluded)
        mic = next(m for m in hidden["stats"]["speaker_attribution"]["mappings"]
                   if m["speaker_cluster"] == "mic:S1")
        self.assertEqual(mic["status"], "excluded")
        self.assertEqual(mic["display_name"], "Non identificato")
        merged = __import__("copy").deepcopy(payload)
        merged["stats"]["speaker_review"]["names"] = {}
        merged["stats"]["speaker_review"]["merged_into"] = {"mic:S1": "system:S1"}
        linked = apply_speaker_labels(merged)
        mic = next(m for m in linked["stats"]["speaker_attribution"]["mappings"]
                   if m["speaker_cluster"] == "mic:S1")
        self.assertEqual(mic["status"], "merged")
        self.assertEqual(linked["segments"][0]["speaker_group"], "system:S1")

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
