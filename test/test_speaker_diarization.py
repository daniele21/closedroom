from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_asr_server.speaker_diarization import LocalSpeakerDiarizationService, NEMOTRON3_ENGINE


class _Store:
    def __init__(self) -> None:
        self.saved = None

    def save_speaker_diarization(self, recording_id, payload):
        self.saved = (recording_id, payload)


class SpeakerDiarizationTests(unittest.TestCase):
    def test_assigns_local_clusters_and_preserves_provider_clusters(self) -> None:
        store = _Store()
        helper_result = {
            "engine": "fluidaudio-community-1",
            "tracks": {
                "system": {
                    "segments": [
                        {"speaker": "0", "start": 0.0, "end": 2.0},
                        {"speaker": "1", "start": 2.0, "end": 4.0},
                    ]
                }
            },
        }
        service = LocalSpeakerDiarizationService(runner=lambda _inputs: helper_result)
        track = {"id": "system"}
        result = {
            "segments": [
                {"start": 0.1, "end": 1.9, "text": "Uno"},
                {"start": 2.1, "end": 3.9, "text": "Due", "provider_speaker": "cloud-S2"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "local_asr_server.speaker_diarization.load_settings",
            return_value={"speaker_diarization_enabled": True, "speaker_diarization_minimum_overlap": 0.25},
        ):
            summary = service.process(
                store,
                "recording-id",
                [(track, Path(tmp) / "system.wav")],
                [{"track": track, "result": result}],
            )

        self.assertEqual(result["segments"][0]["provider_speaker"], "system:0")
        self.assertEqual(result["segments"][1]["provider_speaker"], "cloud-S2")
        self.assertEqual(summary["assigned_segments"], 1)
        self.assertEqual(summary["cluster_count"], 2)
        self.assertEqual(summary["clusters_by_track"]["system"], ["system:0", "system:1"])
        self.assertEqual(summary["unassigned_clusters_by_track"]["system"], ["system:1"])
        self.assertIn("fluidaudio-speaker-diarization", summary["model_path"])
        self.assertEqual(summary["details"]["model_path"], summary["model_path"])
        self.assertEqual(store.saved[0], "recording-id")

    def test_failure_is_persisted_without_raising(self) -> None:
        store = _Store()
        service = LocalSpeakerDiarizationService(runner=lambda _inputs: (_ for _ in ()).throw(RuntimeError("boom")))
        with patch(
            "local_asr_server.speaker_diarization.load_settings",
            return_value={"speaker_diarization_enabled": True},
        ):
            summary = service.process(store, "recording-id", [({"id": "mic"}, Path("mic.wav"))], [])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(store.saved[1]["error"], "boom")

    def test_force_runs_even_when_persisted_setting_is_disabled(self) -> None:
        store = _Store()
        service = LocalSpeakerDiarizationService(runner=lambda _inputs: {
            "engine": "fluidaudio-community-1",
            "tracks": {"system": {"segments": []}},
        })
        with patch(
            "local_asr_server.speaker_diarization.load_settings",
            return_value={"speaker_diarization_enabled": False},
        ):
            summary = service.process(
                store,
                "recording-id",
                [({"id": "system"}, Path("system.wav"))],
                [{"track": {"id": "system"}, "result": {"segments": []}}],
                force=True,
            )
        self.assertEqual(summary["status"], "completed")

    def test_nemotron_routes_selected_preset_to_native_helper(self) -> None:
        service = LocalSpeakerDiarizationService()
        inputs = {"system": Path("/tmp/speaker-fixture.wav")}
        settings = {
            "speaker_diarization_engine": NEMOTRON3_ENGINE,
            "speaker_diarization_nemotron_preset": "c128-split-w8a8",
        }
        with (
            patch("local_asr_server.speaker_diarization.load_settings", return_value=settings),
            patch.object(service, "_run_helper", return_value={"engine": NEMOTRON3_ENGINE, "tracks": {}}) as helper,
        ):
            result = service.diarize_paths(inputs)
        self.assertEqual(result["engine"], NEMOTRON3_ENGINE)
        helper.assert_called_once_with(inputs, engine=NEMOTRON3_ENGINE, preset="c128-split-w8a8")

    def test_invalid_engine_fails_closed_without_inference(self) -> None:
        service = LocalSpeakerDiarizationService()
        with (
            patch("local_asr_server.speaker_diarization.load_settings", return_value={}),
            patch.object(service, "_run_helper") as helper,
        ):
            with self.assertRaisesRegex(ValueError, "Unsupported diarization engine"):
                service.diarize_paths({"mic": Path("mic.wav")}, engine="cloud")
            helper.assert_not_called()

    def test_nemotron_assignment_uses_actual_engine_in_metadata(self) -> None:
        result = {"segments": [{"start": 0.0, "end": 1.0, "text": "Ciao"}]}
        assigned = LocalSpeakerDiarizationService.assign_segments(
            result, "mic", [{"speaker": "0", "start": 0.0, "end": 1.0}],
            0.25, engine=NEMOTRON3_ENGINE,
        )
        self.assertEqual(assigned, 1)
        self.assertEqual(result["metadata"]["speaker_diarization"]["engine"], NEMOTRON3_ENGINE)

    def test_selected_engine_failure_does_not_mutate_transcript(self) -> None:
        store = _Store()
        service = LocalSpeakerDiarizationService(runner=lambda _inputs: (_ for _ in ()).throw(RuntimeError("offline model unavailable")))
        result = {"segments": [{"start": 0, "end": 1, "text": "Contenuto originale"}]}
        with patch("local_asr_server.speaker_diarization.load_settings", return_value={
            "speaker_diarization_enabled": True,
            "speaker_diarization_engine": NEMOTRON3_ENGINE,
        }):
            summary = service.process(
                store, "r1", [({"id": "system"}, Path("system.wav"))],
                [{"track": {"id": "system"}, "result": result}],
            )
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["engine"], NEMOTRON3_ENGINE)
        self.assertNotIn("provider_speaker", result["segments"][0])


if __name__ == "__main__":
    unittest.main()
