from __future__ import annotations

import signal
import sys
import unittest
from unittest.mock import Mock, patch

from local_asr_server.runtime.llm_sidecar import (
    LocalLLMSidecar,
    LocalLLMSidecarError,
    LocalLLMProcessConfig,
)


class LocalLLMSidecarTests(unittest.TestCase):
    def test_stale_vision_cleanup_only_terminates_matching_worker(self) -> None:
        with (
            patch("local_asr_server.runtime.llm_sidecar.subprocess.run") as run,
            patch("local_asr_server.runtime.llm_sidecar.os.kill") as kill,
        ):
            run.side_effect = [
                Mock(stdout="123\n456\n"),
                Mock(stdout="python -m mlx_vlm.server --port 8092\n"),
                Mock(stdout="python unrelated.py\n"),
            ]

            LocalLLMSidecar._terminate_stale_vision_workers()

        kill.assert_called_once_with(123, signal.SIGTERM)

    def test_build_command_keeps_registry_model_when_overriding_model_path(self) -> None:
        sidecar = LocalLLMSidecar()
        with (
            patch("local_asr_server.settings.load_settings", return_value={"visual_llm_model": "qwen3-vl-4b"}),
            patch("local_asr_server.local_llm_params.load_local_llm_params", return_value={}),
        ):
            command = sidecar._build_command(
                model="voxtral-mini-3b",
                model_path="/models/voxtral.gguf",
                backend="llama_server",
                mmproj_path="/models/mmproj.gguf",
                ctx_size=32768,
                startup_timeout=120,
                llama_server_bin="/opt/bin/llama-server",
                port=45678,
                vision_port=45679,
            )

        self.assertEqual(
            command,
            [
                sys.executable, "-m", "local_asr_server.runtime.local_llm_entrypoint", "serve",
                "--host", "127.0.0.1", "--port", "45678",
                "--enable-admin-api", "--mlx-vlm-server-port", "45679",
                "--model", "voxtral-mini-3b", "--model-path", "/models/voxtral.gguf",
                "--backend", "llama_server", "--mmproj-path", "/models/mmproj.gguf",
                "--ctx-size", "32768", "--startup-timeout", "120",
                "--llama-server-bin", "/opt/bin/llama-server",
            ],
        )

    def test_ensure_ready_restarts_when_process_configuration_changes(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        sidecar._process = process
        sidecar._process_config = LocalLLMProcessConfig(model="nemotron-nano-4b")

        with (
            patch.object(sidecar, "_runtime_available", return_value=True),
            patch.object(sidecar, "restart") as restart,
            patch.object(sidecar, "wait_until_ready", return_value=True),
        ):
            sidecar.ensure_ready(model="voxtral-mini-3b", model_path="/models/voxtral.gguf")

        restart.assert_called_once_with(
            model="voxtral-mini-3b",
            model_path="/models/voxtral.gguf",
            backend="",
            mmproj_path="",
            ctx_size=None,
            startup_timeout=None,
            llama_server_bin="",
            dynamic_residency=True,
        )

    def test_ensure_ready_reports_missing_vision_extra_before_starting(self) -> None:
        sidecar = LocalLLMSidecar()
        with (
            patch.object(sidecar, "_runtime_available", return_value=True),
            patch.object(sidecar, "_vision_runtime_available", return_value=False),
            patch.object(sidecar, "start") as start,
            self.assertRaises(LocalLLMSidecarError) as raised,
        ):
            sidecar.ensure_ready(model="qwen3-vl-4b", capability="image")

        self.assertEqual(raised.exception.code, "local_llm_vision_dependency_missing")
        self.assertEqual(raised.exception.status, 503)
        start.assert_not_called()


    def test_registered_model_switch_evicts_previous_before_activation(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        sidecar._process = process
        previous = LocalLLMProcessConfig(model="nemotron-nano-4b-q8")
        sidecar._process_config = previous
        sidecar._resident_configs = {previous.model: previous}

        with (
            patch.object(sidecar, "_runtime_available", return_value=True),
            patch.object(sidecar, "_vision_runtime_available", return_value=True),
            patch.object(sidecar, "_resident_model_keys", return_value=[previous.model]),
            patch.object(sidecar, "_request_json", return_value={"ok": True}) as request_json,
            patch.object(sidecar, "restart") as restart,
            patch.object(sidecar, "wait_until_ready", return_value=True),
        ):
            ready = sidecar.ensure_ready(model="qwen3-vl-4b", capability="image")

        self.assertEqual(ready["model"], "qwen3-vl-4b")
        restart.assert_not_called()
        self.assertEqual(request_json.call_args_list[0].args[:2], ("DELETE", "/api/v1/models/nemotron-nano-4b-q8"))
        self.assertEqual(request_json.call_args_list[1].args[:2], ("POST", "/api/v1/models/activate"))
        self.assertEqual(request_json.call_args_list[1].args[2]["model"], "qwen3-vl-4b")
        self.assertEqual(list(sidecar._resident_configs), ["qwen3-vl-4b"])

    def test_start_reactivates_registered_model_when_sidecar_is_cold(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        process.pid = 123
        sidecar._process = process
        config = LocalLLMProcessConfig(model="nemotron-nano-4b-q8")
        sidecar._process_config = config
        sidecar._resident_configs = {}
        with (
            patch.object(sidecar, "_ensure_registered_model") as ensure_model,
            patch.object(sidecar, "_runtime_available", return_value=True),
        ):
            result = sidecar.start(**config.__dict__)
        ensure_model.assert_called_once_with(config)
        self.assertEqual(result["pid"], 123)

    def test_qwen_activation_reuses_private_vlm_port(self) -> None:
        sidecar = LocalLLMSidecar()
        sidecar._vision_port = 45679
        payload = sidecar._activation_payload(
            LocalLLMProcessConfig(model="qwen3-vl-4b"), include_overrides=True
        )
        self.assertEqual(payload["mlx_vlm_server_port"], 45679)

    def test_release_registered_models_keeps_sidecar_alive_and_cold(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        sidecar._process = process
        sidecar._port = 45678
        config = LocalLLMProcessConfig(model="qwen3-vl-4b")
        sidecar._resident_configs = {config.model: config}

        with (
            patch.object(sidecar, "_resident_model_keys", return_value=[config.model]),
            patch.object(sidecar, "_request_json", return_value={"ok": True}) as request_json,
            patch.object(sidecar, "stop") as stop,
        ):
            result = sidecar.release_resident_models()

        self.assertTrue(result["released"])
        self.assertTrue(result["cold"])
        self.assertEqual(result["unloaded_models"], ["qwen3-vl-4b"])
        request_json.assert_called_once_with("DELETE", "/api/v1/models/qwen3-vl-4b")
        stop.assert_not_called()
        self.assertEqual(sidecar._resident_configs, {})

    def test_explicit_path_registered_model_uses_process_stop_reclamation(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        sidecar._process = process
        config = LocalLLMProcessConfig(
            model="nemotron-nano-4b-q8",
            model_path="/custom/nemotron.gguf",
            dynamic_residency=False,
        )
        sidecar._resident_configs = {config.model: config}
        with (
            patch.object(sidecar, "_resident_model_keys", return_value=[config.model]),
            patch.object(sidecar, "stop", return_value={"stopped": True}) as stop,
        ):
            result = sidecar.release_resident_models()
        self.assertEqual(result["fallback"], "process_stop")
        stop.assert_called_once_with()

    def test_release_unknown_model_falls_back_to_owned_process_stop(self) -> None:
        sidecar = LocalLLMSidecar()
        process = Mock()
        process.poll.return_value = None
        sidecar._process = process
        with (
            patch.object(sidecar, "_resident_model_keys", return_value=["custom-runtime"]),
            patch.object(sidecar, "stop", return_value={"stopped": True}) as stop,
        ):
            result = sidecar.release_resident_models()

        self.assertEqual(result["fallback"], "process_stop")
        stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
