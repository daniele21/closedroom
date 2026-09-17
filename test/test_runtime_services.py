from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from local_asr_server.runtime.models import DEFAULT_LOCAL_LLM_URL
from local_asr_server.runtime.service_manager import RuntimeServiceManager
from local_asr_server.runtime.models import resolve_local_llm_model_path


class RuntimeServiceManagerTests(unittest.TestCase):
    def test_model_specific_path_precedes_legacy_global_path(self) -> None:
        settings = {
            "local_llm_model": "selected",
            "local_llm_model_path": "/models/legacy.gguf",
            "local_llm_model_paths": {"selected": "/models/selected.gguf"},
        }

        self.assertEqual(
            resolve_local_llm_model_path(settings),
            "/models/selected.gguf",
        )

    def test_model_path_explicit_provenance_distinguishes_config_from_discovery(self) -> None:
        from local_asr_server.runtime.models import is_local_llm_model_path_explicit

        self.assertTrue(is_local_llm_model_path_explicit({
            "local_llm_model": "selected",
            "local_llm_model_paths": {"selected": "/models/selected.gguf"},
            "local_llm_model_path": "",
        }))
        self.assertFalse(is_local_llm_model_path_explicit({
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_model_paths": {},
            "local_llm_model_path": "",
        }))

    def test_model_path_falls_back_to_legacy_global_path(self) -> None:
        settings = {
            "local_llm_model": "selected",
            "local_llm_model_path": "/models/legacy.gguf",
            "local_llm_model_paths": {},
        }

        self.assertEqual(
            resolve_local_llm_model_path(settings),
            "/models/legacy.gguf",
        )

    @patch("local_asr_server.runtime.models.Path")
    @patch.dict("os.environ", {"CLOSEDROOM_TEST_RESOLVE": "1"})
    def test_resolve_local_llm_model_path_scans_lm_studio(self, mock_path_class: Mock) -> None:
        mock_lm_studio_dir = Mock()
        mock_lm_studio_dir.exists.return_value = True
        
        mock_model_file = Mock()
        mock_model_file.is_file.return_value = True
        mock_model_file.is_dir.return_value = False
        mock_model_file.suffix = ".gguf"
        mock_model_file.relative_to.return_value = "lmstudio-community/NVIDIA-Nemotron-3-Nano-4B-GGUF/NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf"
        mock_model_file.resolve.return_value = "/mock/home/.lmstudio/models/lmstudio-community/NVIDIA-Nemotron-3-Nano-4B-GGUF/NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf"
        
        mock_lm_studio_dir.rglob.return_value = [mock_model_file]
        
        def path_side_effect(arg):
            if arg == "~/.lmstudio/models":
                p = Mock()
                p.expanduser.return_value = mock_lm_studio_dir
                return p
            else:
                p = Mock()
                p.expanduser.return_value = p
                p.exists.return_value = False
                return p
        mock_path_class.side_effect = path_side_effect
        
        settings = {
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_model_path": "",
            "local_llm_model_paths": {},
        }
        
        resolved_path = resolve_local_llm_model_path(settings)
        self.assertEqual(
            resolved_path,
            "/mock/home/.lmstudio/models/lmstudio-community/NVIDIA-Nemotron-3-Nano-4B-GGUF/NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf"
        )

    def test_llm_status_defaults_to_managed_stopped(self) -> None:
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "auto",
                "local_llm_model": "nemotron-nano-4b",
                "local_llm_model_path": "",
                "local_llm_url": DEFAULT_LOCAL_LLM_URL,
            }

            status = RuntimeServiceManager().llm_status()

        self.assertEqual(status["name"], "llm")
        self.assertEqual(status["status"], "stopped")
        self.assertEqual(status["mode"], "auto")
        self.assertTrue(status["managed"])
        self.assertIsNone(status["url"])

    def test_llm_status_reports_disabled_as_not_configured(self) -> None:
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "disabled",
                "local_llm_model": "nemotron-nano-4b",
            }

            status = RuntimeServiceManager().llm_status()

        self.assertEqual(status["status"], "not_configured")
        self.assertFalse(status["managed"])

    def test_llm_status_reports_missing_custom_model_path(self) -> None:
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "auto",
                "local_llm_model": "custom",
                "local_llm_model_path": "",
            }

            status = RuntimeServiceManager().llm_status()

        self.assertEqual(status["status"], "model_missing")

    def test_external_mode_exposes_configured_url(self) -> None:
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "external",
                "local_llm_model": "nemotron-nano-4b",
                "local_llm_url": "http://127.0.0.1:5555",
            }

            status = RuntimeServiceManager().llm_status()

        self.assertEqual(status["status"], "stopped")
        self.assertFalse(status["managed"])
        self.assertEqual(status["url"], "http://127.0.0.1:5555")

    def test_auto_mode_ensures_managed_sidecar_ready(self) -> None:
        sidecar = Mock()
        sidecar.ensure_ready.return_value = {
            "base_url": "http://127.0.0.1:49001",
            "reasoning": "auto",
            "requested_reasoning": "auto",
            "restart_required": False,
        }
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "auto",
                "local_llm_model": "nemotron-nano-4b",
                "local_llm_model_path": "",
                "local_llm_reasoning": "auto",
            }

            result = RuntimeServiceManager(llm_sidecar=sidecar).ensure_llm_ready(capability="text")

        self.assertEqual(result["base_url"], "http://127.0.0.1:49001")
        sidecar.ensure_ready.assert_called_once_with(
            model="nemotron-nano-4b",
            model_path="",
            backend="",
            mmproj_path="",
            ctx_size=None,
            startup_timeout=None,
            llama_server_bin="",
            reasoning="auto",
            capability="text",
            dynamic_residency=True,
        )

    @patch("local_asr_server.runtime.service_manager._query_external_health")
    def test_external_mode_returns_configured_llm_url_without_sidecar(self, mock_health) -> None:
        mock_health.return_value = {"status": "ok"}
        sidecar = Mock()
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "external",
                "local_llm_model": "nemotron-nano-4b",
                "local_llm_url": "http://127.0.0.1:5555",
                "local_llm_reasoning": "off",
            }

            result = RuntimeServiceManager(llm_sidecar=sidecar).ensure_llm_ready(capability="text")

        self.assertEqual(result["base_url"], "http://127.0.0.1:5555")
        self.assertEqual(result["model"], "nemotron-nano-4b")
        self.assertEqual(result["reasoning"], "off")
        sidecar.ensure_ready.assert_not_called()
        mock_health.assert_called_once_with("http://127.0.0.1:5555")

    @patch("local_asr_server.runtime.service_manager._query_external_health")
    def test_external_mode_raises_when_not_reachable(self, mock_health) -> None:
        mock_health.return_value = None
        sidecar = Mock()
        with patch("local_asr_server.runtime.service_manager.load_settings") as load:
            load.return_value = {
                "local_llm_mode": "external",
                "local_llm_model": "nemotron-nano-4b",
                "local_llm_url": "http://127.0.0.1:5555",
                "local_llm_reasoning": "off",
            }

            with self.assertRaises(RuntimeError) as ctx:
                RuntimeServiceManager(llm_sidecar=sidecar).ensure_llm_ready(capability="text")

        self.assertIn("external_llm_server_not_reachable", str(ctx.exception))
        sidecar.ensure_ready.assert_not_called()
        mock_health.assert_called_once_with("http://127.0.0.1:5555")


if __name__ == "__main__":
    unittest.main()
