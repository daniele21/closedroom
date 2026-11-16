from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from local_asr_server.transcription_diarization import TranscriptionDiarizationService


class _RecordingStore:
    def __init__(self) -> None:
        self.saved = None

    def transcribable_tracks(self, recording_id):
        return [
            ({"id": "mic", "source": "mic", "label": "Tu"}, Path("mic.wav")),
            ({"id": "system", "source": "system", "label": "Computer"}, Path("system.wav")),
        ]

    def save_speaker_diarization(self, recording_id, payload):
        self.saved = (recording_id, payload)


class _TranscriptionStore:
    def __init__(self) -> None:
        self.updated = None
        self.payload = {
            "id": "transcription-id",
            "recording_id": "recording-id",
            "language": "it",
            "text": "original text",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "io",
                    "track_id": "mic",
                    "source": "mic",
                    "provider_speaker": "mic:old",
                    "speaker_label": "Old mic",
                },
                {
                    "id": 1,
                    "start": 1.0,
                    "end": 2.0,
                    "text": "uno",
                    "track_id": "system",
                    "source": "system",
                    "provider_speaker": "system:old",
                    "speaker_label": "Old system",
                },
                {
                    "id": 2,
                    "start": 2.0,
                    "end": 3.0,
                    "text": "due",
                    "track_id": "system",
                    "source": "system",
                    "provider_speaker": "system:old",
                    "speaker_label": "Old system",
                },
            ],
            "source_tracks": [
                {"id": "mic", "source": "mic", "label": "Tu"},
                {"id": "system", "source": "system", "label": "Computer"},
            ],
            "speaker_attribution": {
                "mappings": [{
                    "speaker_cluster": "system:old",
                    "display_name": "Manual old name",
                    "status": "accepted",
                    "source": "manual",
                }],
            },
            "stats": {
                "recording_pipeline_cache_key": "stale",
                "speaker_attribution": {"mappings": []},
                "diagnostics": [],
            },
        }

    def get(self, transcription_id):
        return self.payload

    def replace_diarization(self, transcription_id, updated):
        self.updated = updated
        return updated


class _SpeechmaticsProvider:
    def __init__(self) -> None:
        self.requests = []

    def transcribe(self, request):
        self.requests.append(request)
        return {
            "segments": [
                {"start": 1.0, "end": 2.0, "text": "ignored", "provider_speaker": "S1"},
                {"start": 2.0, "end": 3.0, "text": "ignored", "provider_speaker": "S2"},
            ],
            "metadata": {"job_id": "cloud-job"},
        }


class TranscriptionDiarizationTests(unittest.TestCase):
    def test_uploaded_audio_uses_speechmatics_only_for_speaker_timeline(self) -> None:
        provider = _SpeechmaticsProvider()
        service = TranscriptionDiarizationService(speechmatics_provider=provider)
        payload = {
            "text": "testo Whisper originale",
            "language": "it",
            "segments": [
                {"id": 0, "start": 1.0, "end": 2.0, "text": "uno"},
                {"id": 1, "start": 2.0, "end": 3.0, "text": "due"},
            ],
            "stats": {"time_total_seconds": 1.0},
        }

        with patch(
            "local_asr_server.transcription_diarization.load_settings",
            return_value={
                "speechmatics_api_key": "secret",
                "speechmatics_region": "eu",
                "speechmatics_model": "standard",
                "speaker_diarization_minimum_overlap": 0.25,
            },
        ):
            result = service.process_audio_payload(
                Path("upload.wav"),
                payload,
                provider="speechmatics",
            )

        self.assertIn("Speaker 1: uno", result["text"])
        self.assertIn("Speaker 2: due", result["text"])
        self.assertEqual([item["text"] for item in result["segments"]], ["uno", "due"])
        self.assertEqual(
            [item["provider_speaker"] for item in result["segments"]],
            ["system:S1", "system:S2"],
        )
        self.assertEqual(result["stats"]["speaker_diarization"]["cluster_count"], 2)
        self.assertEqual(len(provider.requests), 1)

    def test_speechmatics_asr_speaker_timeline_is_reused_without_second_cloud_job(self) -> None:
        provider = _SpeechmaticsProvider()
        service = TranscriptionDiarizationService(speechmatics_provider=provider)
        result = service.process_audio_payload(
            Path("upload.wav"),
            {
                "text": "Uno due",
                "language": "it",
                "segments": [
                    {
                        "id": 0,
                        "start": 1.0,
                        "end": 2.0,
                        "text": "Uno",
                        "provider_speaker": "S1",
                    },
                    {
                        "id": 1,
                        "start": 2.0,
                        "end": 3.0,
                        "text": "due",
                        "provider_speaker": "S2",
                    },
                ],
                "stats": {},
            },
            provider="speechmatics",
        )

        self.assertEqual(
            [item["provider_speaker"] for item in result["segments"]],
            ["system:S1", "system:S2"],
        )
        self.assertEqual(provider.requests, [])

    def test_cloud_cluster_without_whisper_overlap_is_preserved(self) -> None:
        provider = _SpeechmaticsProvider()
        provider.transcribe = lambda _request: {
            "segments": [
                {"start": 1.0, "end": 2.0, "provider_speaker": "S1"},
                {"start": 10.0, "end": 11.0, "provider_speaker": "S3"},
            ],
            "metadata": {"job_id": "cloud-job"},
        }
        service = TranscriptionDiarizationService(speechmatics_provider=provider)
        payload = {
            "text": "testo locale",
            "language": "it",
            "segments": [{"id": 0, "start": 1.0, "end": 2.0, "text": "uno"}],
            "stats": {},
        }

        with patch(
            "local_asr_server.transcription_diarization.load_settings",
            return_value={
                "speechmatics_api_key": "secret",
                "speechmatics_region": "eu",
                "speechmatics_model": "standard",
                "speaker_diarization_minimum_overlap": 0.25,
            },
        ):
            result = service.process_audio_payload(
                Path("upload.wav"), payload, provider="speechmatics",
            )

        diarization = result["stats"]["speaker_diarization"]
        self.assertEqual(diarization["clusters_by_track"]["system"], ["system:S1", "system:S3"])
        self.assertEqual(diarization["cluster_count"], 2)
        self.assertEqual(diarization["assigned_cluster_count"], 1)
        self.assertEqual(diarization["unassigned_clusters_by_track"]["system"], ["system:S3"])
        mappings = result["speaker_attribution"]["mappings"]
        self.assertEqual([item["speaker_cluster"] for item in mappings], ["system:S1", "system:S3"])
        self.assertEqual(mappings[1]["transcript_segment_count"], 0)

    def test_speechmatics_replaces_only_speaker_data_and_skips_mic_upload(self) -> None:
        recordings = _RecordingStore()
        transcriptions = _TranscriptionStore()
        provider = _SpeechmaticsProvider()
        service = TranscriptionDiarizationService(speechmatics_provider=provider)

        with patch(
            "local_asr_server.transcription_diarization.load_settings",
            return_value={
                "speechmatics_api_key": "secret",
                "speechmatics_region": "eu",
                "speechmatics_model": "standard",
                "speaker_diarization_minimum_overlap": 0.25,
            },
        ):
            result = service.run(
                recordings,
                transcriptions,
                "transcription-id",
                provider="speechmatics",
            )

        self.assertEqual(
            [segment.get("provider_speaker") for segment in result["segments"]],
            ["mic:S1", "system:S1", "system:S2"],
        )
        self.assertEqual(
            [segment["text"] for segment in result["segments"]],
            ["io", "uno", "due"],
        )
        self.assertNotIn("recording_pipeline_cache_key", result["stats"])
        self.assertEqual(result["stats"]["speaker_diarization"]["cluster_count"], 3)
        self.assertEqual(
            result["stats"]["speaker_diarization"]["clusters_by_track"]["system"],
            ["system:S1", "system:S2"],
        )
        self.assertNotIn("Manual old name", result["text"])
        mic = next(row for row in result["speaker_attribution"]["mappings"]
                   if row["speaker_cluster"] == "mic:S1")
        self.assertEqual((mic["display_name"], mic["status"], mic["source"]),
                         ("Tu", "accepted", "microphone_track"))
        self.assertEqual(result["segments"][0]["speaker_name"], "Tu")
        system = next(row for row in result["speaker_attribution"]["mappings"]
                      if row["speaker_cluster"] == "system:S1")
        self.assertEqual(system["status"], "unassigned")
        self.assertEqual(recordings.saved[0], "recording-id")
        self.assertEqual([Path(request.audio_path).name for request in provider.requests], ["system.wav"])
        self.assertEqual(
            sorted(recordings.saved[1]["tracks"]),
            ["mic", "system"],
        )

    def test_missing_cloud_clusters_fails_without_replacing_transcript(self) -> None:
        recordings = _RecordingStore()
        transcriptions = _TranscriptionStore()
        provider = _SpeechmaticsProvider()
        provider.transcribe = lambda _request: {"segments": [], "metadata": {}}
        service = TranscriptionDiarizationService(speechmatics_provider=provider)

        with patch(
            "local_asr_server.transcription_diarization.load_settings",
            return_value={
                "speechmatics_api_key": "secret",
                "speechmatics_region": "eu",
                "speechmatics_model": "standard",
                "speaker_diarization_minimum_overlap": 0.25,
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "No speaker clusters"):
                service.run(
                    recordings,
                    transcriptions,
                    "transcription-id",
                    provider="speechmatics",
                )

        self.assertIsNone(transcriptions.updated)
        self.assertEqual(recordings.saved[1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
