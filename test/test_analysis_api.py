import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import os

from local_asr_server.server import create_app
from local_asr_server.llm import LLMService, MockProvider, NemotronLocalProvider, VoxtralLocalProvider
from support import deterministic_settings

class AnalysisApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.transcriptions_dir = Path(self.temp_dir.name) / "transcriptions"
        self.transcriptions_dir.mkdir(parents=True, exist_ok=True)
        self.settings_patcher = patch("local_asr_server.transcriptions.load_settings")
        self.mock_load_settings = self.settings_patcher.start()
        self.mock_load_settings.return_value = deterministic_settings(Path(self.temp_dir.name))
        self.runtime_settings_patcher = patch(
            "local_asr_server.runtime.service_manager.load_settings",
            return_value=self.mock_load_settings.return_value,
        )
        self.analysis_settings_patcher = patch(
            "local_asr_server.services.analysis_service.load_settings",
            return_value=self.mock_load_settings.return_value,
        )
        self.runtime_settings_patcher.start()
        self.analysis_settings_patcher.start()
        self.app = create_app(
            default_model="test-model",
            recordings_dir=Path(self.temp_dir.name),
            enable_auth=False,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.analysis_settings_patcher.stop()
        self.runtime_settings_patcher.stop()
        self.settings_patcher.stop()
        self.client.close()
        self.temp_dir.cleanup()

    def test_mock_analysis_endpoint(self) -> None:
        response = self.client.post(
            "/v1/analysis",
            json={
                "text": "Hello world",
                "llm_provider": "mock"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("key_points", data)
        self.assertIn("action_items", data)


    @patch("local_asr_server.services.analysis_service.LLMService.get_provider")
    def test_source_scoped_recording_analysis_uses_explicit_bounded_text(self, mock_provider_factory) -> None:
        provider = MagicMock()
        provider.analyze.return_value = {"markdown": "bounded answer"}
        mock_provider_factory.return_value = provider

        response = self.client.post(
            "/v1/analysis",
            json={
                "recording_id": "recording-key-moment",
                "text": "[VISUAL INFERENCE] roadmap\n[SPOKEN] ship after validation",
                "source_ids": ["screenshot:shot-1"],
                "prompt": "Answer only from the supplied key moment evidence.",
                "llm_provider": "mock",
            },
        )

        self.assertEqual(response.status_code, 200)
        provider.analyze.assert_called_once()
        analyzed_text = provider.analyze.call_args.args[0]
        self.assertIn("[VISUAL INFERENCE] roadmap", analyzed_text)
        self.assertIn("[SPOKEN] ship after validation", analyzed_text)

    @patch("local_asr_server.services.settings_service.load_settings")
    def test_settings_does_not_return_gemini_secret(self, mock_load) -> None:
        mock_load.return_value = {
            "gemini_api_key": "secret-value",
            "speechmatics_api_key": "speech-secret",
            "llm_provider": "gemini",
        }
        response = self.client.get("/v1/settings")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("gemini_api_key", response.json())
        self.assertNotIn("speechmatics_api_key", response.json())
        self.assertTrue(response.json()["gemini_api_key_configured"])
        self.assertTrue(response.json()["speechmatics_api_key_configured"])

    @patch("local_asr_server.services.settings_service.load_settings")
    def test_settings_detects_speechmatics_key_from_env_case_insensitive(self, mock_load) -> None:
        mock_load.return_value = {"gemini_api_key": "", "speechmatics_api_key": "", "llm_provider": "mock"}
        with patch.dict(os.environ, {"SPeeCHMATICS_API_KEY": "from-env"}, clear=False):
            response = self.client.get("/v1/settings")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["speechmatics_api_key_configured"])
        self.assertNotIn("speechmatics_api_key", data)

    @patch("local_asr_server.routers.system.load_settings")
    @patch("local_asr_server.llm.urllib.request.urlopen")
    def test_gemini_analysis_endpoint(self, mock_urlopen, mock_load) -> None:
        mock_load.return_value = {
            "gemini_api_key": "test_key",
            "llm_provider": "gemini"
        }
        
        # Mock Gemini response
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "{\\"title\\": \\"Gemini Title\\", \\"summary\\": \\"Gemini Summary\\", \\"key_points\\": [\\"point 1\\"], \\"action_items\\": [\\"action 1\\"]}"}]}}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        
        response = self.client.post(
            "/v1/analysis",
            json={
                "text": "Hello Gemini",
                "llm_provider": "gemini",
                "gemini_api_key": "test_key",
                "gemini_model": "gemini-3.5-flash",
            }
        )
        self.assertEqual(response.status_code, 200)
        requested_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("/gemini-3.5-flash:generateContent", requested_url)
        data = response.json()
        self.assertEqual(data["title"], "Gemini Title")

    @patch("local_asr_server.analysis_jobs.AnalysisJobManager._run", return_value=None)
    @patch("local_asr_server.analysis_jobs.load_settings")
    def test_analysis_job_records_local_llm_overrides(self, mock_load, _mock_run) -> None:
        mock_load.return_value = {
            "llm_provider": "mock",
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_quality_preset": "balanced",
            "local_llm_temperature": 0.6,
            "local_llm_reasoning": "auto",
            "local_llm_json_mode": True,
        }

        response = self.client.post(
            "/v1/analysis-jobs",
            json={
                "text": "Run with explicit local setup",
                "llm_provider": "nemotron_local",
                "local_llm_model": "voxtral-mini-3b",
                "local_llm_model_path": "/tmp/voxtral-mini-3b.gguf",
                "local_llm_quality_preset": "precise",
                "local_llm_temperature": 0.2,
                "local_llm_reasoning": "off",
                "local_llm_max_output_tokens": 4096,
                "local_llm_json_mode": False,
            },
        )

        self.assertEqual(response.status_code, 202)
        run = self.client.get(f"/v1/analysis-runs/{response.json()['analysis_run_id']}").json()
        self.assertEqual(run["provider"], "nemotron_local")
        self.assertEqual(run["model"], "voxtral-mini-3b")
        self.assertEqual(run["temperature"], 0.2)
        self.assertEqual(run["reasoning"], "off")
        self.assertEqual(run["max_output_tokens"], 4096)
        self.assertFalse(run["json_mode"])
        self.assertEqual(run["llm_options"]["quality_preset"], "precise")
        self.assertEqual(run["llm_options"]["model_path"], "/tmp/voxtral-mini-3b.gguf")

    @patch("local_asr_server.analysis_jobs.AnalysisJobManager._run", return_value=None)
    @patch("local_asr_server.analysis_jobs.load_settings")
    def test_analysis_pipeline_carries_local_llm_overrides_to_jobs(self, mock_load, _mock_run) -> None:
        mock_load.return_value = {
            "llm_provider": "mock",
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_quality_preset": "balanced",
            "local_llm_temperature": 0.6,
            "local_llm_reasoning": "auto",
            "local_llm_json_mode": True,
        }

        response = self.client.post(
            "/v1/analysis-pipelines",
            json={
                "text": "Pipeline with explicit local setup",
                "pipeline_id": "meeting_default",
                "llm_provider": "nemotron_local",
                "local_llm_model": "voxtral-mini-3b",
                "local_llm_quality_preset": "creative",
                "local_llm_temperature": None,
                "local_llm_reasoning": "on",
                "local_llm_max_output_tokens": 2048,
                "local_llm_json_mode": False,
            },
        )

        self.assertEqual(response.status_code, 202)
        first_job = response.json()["jobs"][0]
        run = self.client.get(f"/v1/analysis-runs/{first_job['analysis_run_id']}").json()
        self.assertEqual(run["provider"], "nemotron_local")
        self.assertEqual(run["model"], "voxtral-mini-3b")
        self.assertIsNone(run["temperature"])
        self.assertEqual(run["reasoning"], "on")
        self.assertEqual(run["llm_options"]["quality_preset"], "creative")
        self.assertEqual(run["llm_options"]["max_output_tokens"], 2048)
        self.assertFalse(run["llm_options"]["json_mode"])

    @patch("local_llm_server.client.LocalLLMClient")
    def test_nemotron_local_provider_called(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client.is_ready.return_value = True
        mock_client.analyze_text.return_value = {
            "title": "Nemotron Title",
            "summary": "Nemotron Summary",
            "key_points": ["point n"],
            "action_items": []
        }
        mock_client_cls.return_value = mock_client

        provider = LLMService.get_provider("nemotron_local", local_llm_url="http://127.0.0.1:1235", local_llm_model="nemotron-nano-4b")
        self.assertIsInstance(provider, NemotronLocalProvider)
        
        result = provider.analyze("Test Nemotron Text")
        mock_client_cls.assert_called_once_with(base_url="http://127.0.0.1:1235", model="nemotron-nano-4b")
        mock_client.analyze_text.assert_called_once_with("Test Nemotron Text", language="it")
        self.assertEqual(result["title"], "Nemotron Title")

    @patch("local_llm_server.client.LocalLLMClient")
    def test_voxtral_local_provider_audio(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client.is_ready.return_value = True
        mock_client.analyze_audio.return_value = {
            "title": "Voxtral Title",
            "summary": "Voxtral Summary",
            "key_points": ["point v"],
            "action_items": []
        }
        mock_client_cls.return_value = mock_client

        provider = LLMService.get_provider("voxtral_local", local_llm_url="http://127.0.0.1:1235", local_llm_model="voxtral-mini-3b")
        self.assertIsInstance(provider, VoxtralLocalProvider)
        
        result = provider.analyze_audio("test.wav", task="insights", question="what?")
        mock_client_cls.assert_called_once_with(base_url="http://127.0.0.1:1235", model="voxtral-mini-3b")
        mock_client.analyze_audio.assert_called_once_with(
            audio_path="test.wav",
            task="insights",
            question="what?",
            language="it"
        )
        self.assertEqual(result["title"], "Voxtral Title")

    @patch("local_asr_server.runtime.service_manager._query_external_health")
    @patch("local_llm_server.client.LocalLLMClient")
    @patch("local_asr_server.routers.system.load_settings")
    def test_voxtral_audio_analysis_via_endpoint(self, mock_load, mock_client_cls, mock_health) -> None:
        mock_health.return_value = {"status": "ok"}
        mock_load.return_value = {
            "local_llm_url": "http://127.0.0.1:1235",
            "llm_provider": "voxtral_local"
        }
        mock_client = MagicMock()
        mock_client.is_ready.return_value = True
        mock_client.analyze_audio.return_value = {
            "title": "Voxtral Endpoint Title",
            "summary": "Voxtral Endpoint Summary",
            "key_points": ["point v_end"],
            "action_items": []
        }
        mock_client_cls.return_value = mock_client

        # Create a mock recording
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Voxtral Test Audio",
                "mime_type": "audio/webm;codecs=opus",
                "language": "it",
            },
        )
        self.assertEqual(created.status_code, 201)
        recording_id = created.json()["id"]

        # Append mock chunk and stop to finalize paths
        self.client.post(
            f"/v1/recordings/{recording_id}/chunks",
            data={"sequence": "0"},
            files={"file": ("chunk.webm", b"audio", "audio/webm")},
        )
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        # Now test analysis endpoint with recording_id
        response = self.client.post(
            "/v1/analysis",
            json={
                "recording_id": recording_id,
                "llm_provider": "voxtral_local",
                "audio_task": "insights",
                "question": "test-question"
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "Voxtral Endpoint Title")

    def test_prompts_endpoints(self) -> None:
        # Test GET /v1/prompts
        response = self.client.get("/v1/prompts")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data)
        self.assertIn("default_instruction", data)
        
        # Test POST /v1/prompts
        custom_prompts = {
            "summary": {
                "it": "Custom summary prompt",
                "en": "Custom summary prompt en"
            },
            "default_instruction": {
                "it": "Custom instruction",
                "en": "Custom instruction en"
            }
        }
        post_response = self.client.post("/v1/prompts", json=custom_prompts)
        self.assertEqual(post_response.status_code, 200)
        
        # Re-fetch and check
        get_response = self.client.get("/v1/prompts")
        self.assertEqual(get_response.status_code, 200)
        updated_data = get_response.json()
        self.assertEqual(updated_data["summary"]["it"], "Custom summary prompt")
        self.assertEqual(updated_data["default_instruction"]["it"], "Custom instruction")


if __name__ == "__main__":
    unittest.main()
