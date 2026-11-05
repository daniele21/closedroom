"""Read-only speaker timeline coverage and correction consistency."""
from __future__ import annotations

import copy
import math
import unittest
from pathlib import Path

from local_asr_server.speaker_labels import apply_speaker_labels
from local_asr_server.speaker_review import project_speaker_action, speaker_timeline_window


def transcript():
    return apply_speaker_labels({
        "id": "transcription-1", "recording_id": "recording-1",
        "text": "Do not modify the original text.",
        "segments": [
            {"id": 0, "track_id": "system", "start": 1, "end": 7,
             "text": "Hello", "provider_speaker": "system:S1",
             "words": [{"word": "Hello", "start": 1, "end": 2}]},
            {"id": 1, "track_id": "system", "start": 10, "end": 12,
             "text": "Hi", "provider_speaker": "system:S2"},
        ],
        "stats": {"speaker_diarization": {
            "status": "completed", "engine": "fluidaudio-community-1",
            "clusters_by_track": {"system": ["system:S1", "system:S2", "system:S3"]},
        }},
    })


class RecordingFixture:
    def __init__(self, *, audio=True, raw_engine="fluidaudio-community-1"):
        self.audio = audio
        self.raw_engine = raw_engine

    def get(self, recording_id, include_result=False):
        assert recording_id == "recording-1" and not include_result
        return {"audio_tracks": [
            {"id": "system", "audio_file": "system.wav" if self.audio else None},
        ]}

    def track_audio_path(self, recording_id, track_id):
        if not self.audio:
            raise ValueError("Audio was moved to remote storage")
        return Path("/private") / track_id

    def read_speaker_diarization(self, recording_id):
        return {"engine": self.raw_engine, "tracks": {"system": {"segments": [
            {"speaker": "S1", "start": 1.0, "end": 8.0},
            {"speaker": "S2", "start": 6.5, "end": 12.5},
            {"speaker": "S3", "start": 18.0, "end": 21.0},
        ]}}}


class SpeakerTimelineProjectionTests(unittest.TestCase):
    def test_long_meeting_audio_only_speaker_appears_in_full_overview(self):
        # Screenshot regression: an audio example at 25:15, no attributed
        # phrases, but a full 30-minute saved recording.
        case = {
            "id": "transcription-1", "recording_id": "recording-1",
            "segments": [], "text": "",
            "stats": {"speaker_diarization": {
                "status": "completed", "engine": "fluidaudio-community-1",
                "clusters_by_track": {
                    "system": [f"system:S{i}" for i in range(1, 6)],
                },
            }},
        }
        class LongRecording(RecordingFixture):
            def get(self, recording_id, include_result=False):
                return {**super().get(recording_id, include_result=include_result),
                        "created_at": "2026-11-04T13:00:00+00:00",
                        "stopped_at": "2026-11-04T13:30:00+00:00"}
            def read_speaker_diarization(self, recording_id):
                return {"engine": self.raw_engine, "tracks": {"system": {
                    "segments": [
                        {"speaker": "S1", "start": 0, "end": 10},
                        {"speaker": "S2", "start": 120, "end": 130},
                        {"speaker": "S3", "start": 1515, "end": 1521},
                        {"speaker": "S4", "start": 1640, "end": 1650},
                        {"speaker": "S5", "start": 1780, "end": 1790},
                    ],
                }}}
        recording = LongRecording()
        first_second = speaker_timeline_window(
            case, recording, start_seconds=0, end_seconds=1,
        )
        self.assertEqual(first_second["duration_seconds"], 1800)
        self.assertEqual(first_second["duration_source"], "recording_clock")
        self.assertEqual(first_second["coverage"], "diarization")
        self.assertEqual(first_second["window_coverage"], "diarization")
        self.assertEqual(first_second["total_interval_count"], 5)
        self.assertEqual(first_second["intervals"][0]["end"], 1)
        self.assertEqual(first_second["overview_bucket_count"], 120)
        giulia = next(item for item in first_second["overview"] if item["cluster"] == "system:S3")
        self.assertEqual(giulia["interval_count"], 1)
        self.assertGreater(giulia["first_start"], 1500)
        self.assertTrue(giulia["bins"])
        self.assertLessEqual(len(giulia["bins"]), 120)
        off_window = speaker_timeline_window(
            case, recording, start_seconds=60, end_seconds=80,
        )
        self.assertEqual(off_window["intervals"], [])
        self.assertEqual(off_window["window_coverage"], "none")
        self.assertEqual(off_window["coverage"], "diarization")
        self.assertEqual(off_window["total_interval_count"], 5)
        late = speaker_timeline_window(
            case, recording, start_seconds=1500, end_seconds=1540,
        )
        self.assertEqual([r["cluster"] for r in late["intervals"]], ["system:S3"])

    def test_unknown_duration_remains_explicit_until_evidence_exists(self):
        case = transcript()
        case["segments"] = []
        case["stats"]["speaker_diarization"]["clusters_by_track"] = {}
        no_data = speaker_timeline_window(
            case, RecordingFixture(raw_engine="wrong"), start_seconds=0, end_seconds=60,
        )
        self.assertIsNone(no_data["duration_seconds"])
        self.assertEqual(no_data["duration_source"], "unknown")
        self.assertEqual(no_data["coverage"], "none")
        self.assertEqual(no_data["overview_bucket_count"], 120)
        self.assertTrue(all(not entry["bins"] for entry in no_data["overview"]))

    def test_recording_metadata_duration_is_used_without_lying_about_audio(self):
        case = transcript()
        class ExplicitDuration(RecordingFixture):
            def get(self, recording_id, include_result=False):
                return {**super().get(recording_id, include_result=include_result),
                        "duration_seconds": 3600, "created_at": "bad"}
        result = speaker_timeline_window(
            case, ExplicitDuration(), start_seconds=1000, end_seconds=1100,
        )
        self.assertEqual(result["duration_seconds"], 3600)
        self.assertEqual(result["duration_source"], "recording")
        self.assertEqual(result["coverage"], "diarization")
        self.assertEqual(result["window_coverage"], "none")
        self.assertEqual(result["total_interval_count"], 3)

    def test_full_native_timeline_includes_cluster_missing_from_asr(self):
        result = speaker_timeline_window(
            transcript(), RecordingFixture(), start_seconds=0, end_seconds=30)
        self.assertEqual(result["coverage"], "diarization")
        self.assertFalse(result["truncated"])
        self.assertEqual([row["cluster"] for row in result["intervals"]],
                         ["system:S1", "system:S2", "system:S3"])
        self.assertTrue(all(row["origin"] == "diarization" for row in result["intervals"]))
        self.assertTrue(all(row["playable"] for row in result["intervals"]))

    def test_edits_reproject_without_changing_raw_timing_and_undo(self):
        original = transcript()
        unchanged = copy.deepcopy(original)
        renamed = project_speaker_action(original, action="rename", cluster="system:S1", name="Giulia")
        merged = project_speaker_action(renamed, action="merge", cluster="system:S2", target="system:S1")
        data = speaker_timeline_window(merged, RecordingFixture(), start_seconds=0, end_seconds=30)
        self.assertEqual([row["cluster"] for row in data["intervals"]],
                         ["system:S1", "system:S2", "system:S3"])
        self.assertEqual(merged["segments"][1]["speaker_group"], "system:S1")
        self.assertEqual(merged["text"], unchanged["text"])
        self.assertEqual([s.get("words") for s in merged["segments"]],
                         [s.get("words") for s in unchanged["segments"]])
        excluded = project_speaker_action(merged, action="exclude", cluster="system:S1")
        self.assertEqual(excluded["stats"]["speaker_attribution"]["mappings"][0]["status"], "excluded")
        restored = project_speaker_action(excluded, action="restore", cluster="system:S1")
        self.assertEqual(restored["stats"]["speaker_attribution"]["mappings"][0]["status"], "accepted")
        self.assertEqual(speaker_timeline_window(
            restored, RecordingFixture(), start_seconds=0, end_seconds=30)["intervals"], data["intervals"])

    def test_reviewed_meeting_does_not_use_unrelated_raw_diarization(self):
        candidate = transcript()
        candidate["stats"]["speaker_diarization"]["source"] = "reviewed_meeting"
        result = speaker_timeline_window(
            candidate, RecordingFixture(), start_seconds=0, end_seconds=30)
        self.assertEqual(result["coverage"], "transcript")
        self.assertEqual([row["cluster"] for row in result["intervals"]],
                         ["system:S1", "system:S2"])
        self.assertTrue(all(row["origin"] == "transcript" for row in result["intervals"]))

    def test_applied_community_one_uses_exact_job_timeline_without_duplication(self):
        case = transcript()
        case["stats"]["speaker_diarization"].update({
            "source": "reviewed_meeting", "applied_review_job_id": "job-applied",
        })
        job = {
            "id": "job-applied", "type": "diarization_review",
            "status": "completed", "scope_id": case["id"], "recording_id": case["recording_id"],
            "result": {"scope": "full", "track_id": "system", "runs": [{
                "key": "community-1", "status": "completed",
                "timeline": [
                    {"speaker": "S1", "start": 0, "end": 8},
                    {"speaker": "S2", "start": 9, "end": 14},
                    {"speaker": "S3", "start": 20, "end": 29},
                ],
            }]},
        }
        full = speaker_timeline_window(
            case, RecordingFixture(raw_engine="different"), start_seconds=0, end_seconds=30,
            review_job=job)
        self.assertEqual(full["coverage"], "diarization")
        self.assertEqual([item["cluster"] for item in full["intervals"]],
                         ["system:S1", "system:S2", "system:S3"])
        self.assertEqual(full["intervals"][0]["start"], 0)
        self.assertTrue(all(item["origin"] == "diarization" for item in full["intervals"]))
        # Missing or mismatched job links must not reuse an unrelated saved run.
        for update in (
            {"id": "some-other-job"},
            {"scope_id": "other-transcription"},
            {"recording_id": "other-meeting"},
            {"status": "failed"},
        ):
            stale = {**job, **update}
            fallback = speaker_timeline_window(
                case, RecordingFixture(), start_seconds=0, end_seconds=30, review_job=stale)
            self.assertEqual(fallback["coverage"], "transcript")
            self.assertEqual(len(fallback["intervals"]), 2)
        missing = speaker_timeline_window(
            case, RecordingFixture(), start_seconds=0, end_seconds=30)
        self.assertEqual(missing["coverage"], "transcript")

    def test_review_job_rejects_mismatched_native_cluster_set(self):
        case = transcript()
        case["stats"]["speaker_diarization"].update({
            "source": "reviewed_meeting", "applied_review_job_id": "job-applied",
        })
        job = {
            "id": "job-applied", "type": "diarization_review",
            "status": "completed", "scope_id": case["id"], "recording_id": case["recording_id"],
            "result": {"scope": "full", "track_id": "system", "runs": [{
                "key": "community-1", "status": "completed",
                "timeline": [{"speaker": "S1", "start": 0, "end": 8}],
            }]},
        }
        result = speaker_timeline_window(
            case, RecordingFixture(), start_seconds=0, end_seconds=30, review_job=job)
        self.assertEqual(result["coverage"], "transcript")
        self.assertEqual(len(result["intervals"]), 2)

    def test_mismatched_raw_engine_falls_back_to_transcript(self):
        result = speaker_timeline_window(
            transcript(), RecordingFixture(raw_engine="other"), start_seconds=0, end_seconds=30)
        self.assertEqual(result["coverage"], "transcript")
        self.assertEqual(len(result["intervals"]), 2)

    def test_deleted_audio_keeps_visible_intervals_but_no_playback(self):
        result = speaker_timeline_window(
            transcript(), RecordingFixture(audio=False), start_seconds=0, end_seconds=30)
        self.assertFalse(result["has_audio"])
        self.assertEqual(len(result["intervals"]), 3)
        self.assertTrue(all(not row["playable"] for row in result["intervals"]))

    def test_ranges_are_clipped_and_very_long_or_invalid_rejected(self):
        result = speaker_timeline_window(
            transcript(), RecordingFixture(), start_seconds=6.0, end_seconds=7.0)
        self.assertEqual([(row["start"], row["end"]) for row in result["intervals"]],
                         [(6.0, 7.0), (6.5, 7.0)])
        for start, end in [(0, 0), (-1, 2), (2, 1), (0, 28801),
                           (math.nan, 3), (0, math.inf)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                speaker_timeline_window(
                    transcript(), RecordingFixture(), start_seconds=start, end_seconds=end)

    def test_truncation_is_explicit_and_bounded(self):
        case = transcript()
        raw = RecordingFixture()
        native = raw.read_speaker_diarization("recording-1")
        native["tracks"]["system"]["segments"] = [
            {"speaker": "S1", "start": float(i), "end": float(i) + 0.25}
            for i in range(5050)
        ]
        # A changed cluster set invalidates raw evidence rather than fabricating identity.
        case["stats"]["speaker_diarization"]["clusters_by_track"]["system"] = ["system:S1"]
        raw.read_speaker_diarization = lambda _: native
        result = speaker_timeline_window(case, raw, start_seconds=0, end_seconds=6000)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["intervals"]), 5000)


if __name__ == "__main__":
    unittest.main()
