from __future__ import annotations

import importlib.util
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from local_asr_server.paths import get_service_log_file
from local_asr_server.runtime.models import LOCAL_SERVICE_HOST


_DYNAMIC_RESIDENCY_MODELS = {
    "nemotron-nano-4b",
    "nemotron-nano-4b-q8",
    "qwen3-vl-4b",
}


class LocalLLMSidecarError(RuntimeError):
    """Raised when the managed local LLM service cannot become usable."""

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ResolvedReasoning:
    requested: str
    effective: str
    restart_required: bool = False


@dataclass(frozen=True)
class LocalLLMProcessConfig:
    model: str
    model_path: str = ""
    backend: str = ""
    mmproj_path: str = ""
    ctx_size: int | None = None
    startup_timeout: int | None = None
    llama_server_bin: str = ""
    dynamic_residency: bool = True


class LocalLLMSidecar:
    """Owns the process, port, readiness and logs for local-llm-server."""

    def __init__(self, log_file: Path | None = None) -> None:
        self.host = LOCAL_SERVICE_HOST
        self.log_file = log_file or get_service_log_file("llm-server", create_parent=False)
        self._process: subprocess.Popen[Any] | None = None
        self._port: int | None = None
        self._vision_port: int | None = None
        self._started_at: float | None = None
        self._last_error: str | None = None
        self._process_config: LocalLLMProcessConfig | None = None
        self._resident_configs: dict[str, LocalLLMProcessConfig] = {}

    @property
    def base_url(self) -> str | None:
        if self._port is None:
            return None
        return f"http://{self.host}:{self._port}"

    def _query_health(self) -> dict[str, Any] | None:
        if not self.base_url:
            return None
        import json
        try:
            with urlopen(f"{self.base_url}/health", timeout=1.0) as response:
                if 200 <= response.status < 300:
                    return json.loads(response.read().decode("utf-8"))
        except Exception:
            pass
        return None

    def status(self, model: str, mode: str, model_path: str = "") -> dict[str, Any]:
        process = self._process
        health_data = self._query_health()

        if mode == "disabled":
            status = "not_configured"
        elif model == "custom" and not model_path:
            status = "model_missing"
        elif process is None:
            status = "stopped"
        elif process.poll() is not None:
            status = "crashed"
        elif health_data is not None:
            status = "ready"
        else:
            status = "loading_model"

        loaded_model = None
        loaded_model_id = None
        loaded_model_path = None
        loaded_model_backend = None
        resident_models: list[str] = []
        if health_data:
            loaded_model = health_data.get("model_key") or health_data.get("model")
            loaded_model_id = health_data.get("model")
            loaded_model_path = health_data.get("model_path")
            loaded_model_backend = health_data.get("backend")
            values = health_data.get("loaded_models")
            if isinstance(values, list):
                resident_models = [str(value) for value in values]

        return {
            "name": "llm",
            "status": status,
            "mode": mode,
            "model": model,
            "loaded_model": loaded_model,
            "loaded_model_id": loaded_model_id,
            "loaded_model_path": loaded_model_path,
            "loaded_model_backend": loaded_model_backend,
            "resident_models": resident_models,
            "cold": bool(health_data is not None and not resident_models),
            "model_path_configured": bool(model_path),
            "managed": mode == "auto",
            "url": self.base_url,
            "host": self.host if self._port else None,
            "port": self._port,
            "pid": process.pid if process and process.poll() is None else None,
            "started_at": self._started_at,
            "log_file": str(self.log_file),
            "error": self._last_error,
        }

    def ensure_ready(
        self,
        *,
        model: str,
        model_path: str = "",
        backend: str = "",
        mmproj_path: str = "",
        ctx_size: int | None = None,
        startup_timeout: int | None = None,
        llama_server_bin: str = "",
        reasoning: str = "auto",
        capability: str = "text",
        timeout: float = 30.0,
        dynamic_residency: bool = True,
    ) -> dict[str, Any]:
        if model == "custom" and not model_path:
            raise LocalLLMSidecarError("local_llm_model_missing", "Percorso modello LLM locale non configurato.", 400)
        if not self._runtime_available():
            raise LocalLLMSidecarError(
                "local_llm_binary_missing",
                "local-llm-server non è installato o non è importabile.",
                503,
            )
        if capability == "image" and not self._vision_runtime_available():
            raise LocalLLMSidecarError(
                "local_llm_vision_dependency_missing",
                "Il backend visuale locale non è installato. Installa local-llm-server con l'extra vision.",
                503,
            )
        config = LocalLLMProcessConfig(
            model, model_path, backend, mmproj_path, ctx_size, startup_timeout,
            llama_server_bin, dynamic_residency,
        )
        if self._process is None or self._process.poll() is not None:
            self.start(**config.__dict__)
        elif self._supports_dynamic_residency(config):
            try:
                self._ensure_registered_model(config)
            except LocalLLMSidecarError:
                # The admin control plane is an optimization boundary. The
                # owned process remains the canonical reclamation boundary,
                # so recover by restarting with only the requested model.
                self.restart(**config.__dict__)
        elif self._process_config != config:
            self.restart(**config.__dict__)
        if not self.wait_until_ready(timeout=timeout):
            raise LocalLLMSidecarError("local_llm_not_ready", "Il servizio LLM locale è ancora in caricamento.", 503)
        resolved_reasoning = self.resolve_reasoning(reasoning, capability)
        return {
            "base_url": self.base_url,
            "model": model,
            "reasoning": resolved_reasoning.effective,
            "requested_reasoning": resolved_reasoning.requested,
            "restart_required": resolved_reasoning.restart_required,
        }

    def start(
        self,
        *,
        model: str,
        model_path: str = "",
        backend: str = "",
        mmproj_path: str = "",
        ctx_size: int | None = None,
        startup_timeout: int | None = None,
        llama_server_bin: str = "",
        dynamic_residency: bool = True,
    ) -> dict[str, Any]:
        config = LocalLLMProcessConfig(
            model, model_path, backend, mmproj_path, ctx_size, startup_timeout,
            llama_server_bin, dynamic_residency,
        )
        if self._process is not None and self._process.poll() is None:
            if self._supports_dynamic_residency(config):
                try:
                    self._ensure_registered_model(config)
                except LocalLLMSidecarError:
                    return self.restart(**config.__dict__)
                return {"base_url": self.base_url, "pid": self._process.pid}
            if self._process_config != config:
                return self.restart(**config.__dict__)
            return {"base_url": self.base_url, "pid": self._process.pid}

        if not self._runtime_available():
            raise LocalLLMSidecarError(
                "local_llm_binary_missing",
                "local-llm-server non è installato o non è importabile.",
                503,
            )
        self._terminate_stale_vision_workers()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._port = self._select_port()
        vision_port = self._select_port()
        cmd = self._build_command(port=self._port, vision_port=vision_port, **config.__dict__)
        try:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.info(f"Starting local LLM server on port {self._port} (model: {model})")
            log_handle = self.log_file.open("ab")
            self._process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._started_at = time.time()
            self._vision_port = vision_port
            self._last_error = None
            self._process_config = config
            self._resident_configs = {model: config}
        except Exception as exc:
            self._last_error = str(exc)
            raise LocalLLMSidecarError("local_llm_start_failed", f"Avvio local-llm-server non riuscito: {exc}") from exc
        return {"base_url": self.base_url, "pid": self._process.pid}

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        process = self._process
        if process is None:
            return {"stopped": True}
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()
                process.wait(timeout=timeout)
        self._process = None
        self._port = None
        self._vision_port = None
        self._started_at = None
        self._process_config = None
        self._resident_configs.clear()
        return {"stopped": True}

    def restart(self, **config: Any) -> dict[str, Any]:
        self.stop()
        return self.start(**config)

    def tail_logs(self, lines: int = 200) -> str:
        if not self.log_file.exists():
            return ""
        lines = max(1, min(lines, 2000))
        data = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])

    def wait_until_ready(self, timeout: float = 30.0, interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                self._last_error = f"local-llm-server exited with code {self._process.returncode}"
                return False
            if self.is_ready():
                return True
            time.sleep(interval)
        return False

    def is_ready(self) -> bool:
        if not self.base_url:
            return False
        try:
            with urlopen(f"{self.base_url}/health", timeout=1.0) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, ValueError):
            return False

    def resolve_reasoning(self, reasoning: str, capability: str = "text") -> ResolvedReasoning:
        if reasoning not in {"auto", "on", "off"}:
            reasoning = "auto"
        if reasoning == "auto":
            return ResolvedReasoning(requested="auto", effective="off" if capability == "audio" else "auto")
        return ResolvedReasoning(requested=reasoning, effective=reasoning)

    def _runtime_available(self) -> bool:
        return bool(shutil.which("local-llm-server")) or importlib.util.find_spec("local_llm_server") is not None

    @staticmethod
    def _terminate_stale_vision_workers() -> None:
        """Clean up orphaned mlx_vlm.server children left by an unclean sidecar stop."""
        try:
            found = subprocess.run(
                ["pgrep", "-f", "mlx_vlm.server"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return
        for value in found.stdout.split():
            try:
                pid = int(value)
            except ValueError:
                continue
            if pid == os.getpid():
                continue
            try:
                command = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                ).stdout
                if "-m mlx_vlm.server" not in command:
                    continue
                os.kill(pid, signal.SIGTERM)
            except (OSError, subprocess.SubprocessError):
                continue

    @staticmethod
    def _vision_runtime_available() -> bool:
        return importlib.util.find_spec("mlx_vlm") is not None

    @staticmethod
    def _supports_dynamic_residency(config: LocalLLMProcessConfig) -> bool:
        # These are the product-owned registry models whose upstream 0.4
        # entries resolve the same LM Studio/managed artifacts used by
        # ClosedRoom. Unknown/custom direct-path models retain the safer
        # process restart/stop lifecycle until model_path is an admin API.
        return config.dynamic_residency and config.model in _DYNAMIC_RESIDENCY_MODELS

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> dict[str, Any]:
        if not self.base_url:
            raise LocalLLMSidecarError("local_llm_not_running", "Il servizio LLM locale non è avviato.")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                detail = str(exc)
            raise LocalLLMSidecarError(
                "local_llm_admin_failed",
                f"local-llm-server admin {method} {path} failed ({exc.code}): {detail}",
                503,
            ) from exc
        except (OSError, URLError, ValueError) as exc:
            raise LocalLLMSidecarError(
                "local_llm_admin_unreachable",
                f"local-llm-server admin endpoint non raggiungibile: {exc}",
                503,
            ) from exc

    def _resident_model_keys(self) -> list[str]:
        payload = self._request_json("GET", "/v1/models", timeout=2.0)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        keys: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("key") or row.get("id")
            if value:
                keys.append(str(value))
        return keys

    def _activation_payload(
        self, config: LocalLLMProcessConfig, *, include_overrides: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": config.model}
        if not include_overrides:
            return payload
        for key in ("backend", "mmproj_path", "ctx_size", "startup_timeout", "llama_server_bin"):
            value = getattr(config, key)
            if value not in (None, ""):
                payload[key] = value
        if config.model == "qwen3-vl-4b" and self._vision_port is not None:
            payload["mlx_vlm_server_port"] = self._vision_port
        return payload

    def _ensure_registered_model(self, config: LocalLLMProcessConfig) -> None:
        resident = self._resident_model_keys()
        unknown = [
            key for key in resident
            if (self._resident_configs.get(key) is None
                or not self._supports_dynamic_residency(self._resident_configs[key]))
        ]
        if unknown:
            raise LocalLLMSidecarError(
                "local_llm_residency_conflict",
                "Il sidecar contiene un runtime non gestibile tramite la policy ClosedRoom.",
                503,
            )
        for key in resident:
            if key == config.model:
                continue
            self._request_json("DELETE", f"/api/v1/models/{quote(key, safe='')}")
            self._resident_configs.pop(key, None)
        target_resident = config.model in resident
        known_config = self._resident_configs.get(config.model)
        include_overrides = (not target_resident) or (known_config is not None and known_config != config)
        self._request_json(
            "POST",
            "/api/v1/models/activate",
            self._activation_payload(config, include_overrides=include_overrides),
            timeout=float(config.startup_timeout or 300),
        )
        self._resident_configs = {config.model: config}

    def release_resident_models(self) -> dict[str, Any]:
        """Return the managed sidecar to a cold state after a heavy phase.

        Registered product models use local-llm-server 0.4 zero-resident
        semantics. Unknown/custom runtimes fall back to process stop so a
        later phase can recreate the exact direct-path configuration.
        Cleanup is best-effort and never masks the workload result.
        """
        process = self._process
        if process is None or process.poll() is not None:
            self._resident_configs.clear()
            return {"released": True, "cold": True, "resident_models": []}
        try:
            resident = self._resident_model_keys()
            if any(
                self._resident_configs.get(key) is None
                or not self._supports_dynamic_residency(self._resident_configs[key])
                for key in resident
            ):
                self.stop()
                return {"released": True, "cold": True, "resident_models": [], "fallback": "process_stop"}
            released: list[str] = []
            for key in resident:
                self._request_json("DELETE", f"/api/v1/models/{quote(key, safe='')}")
                released.append(key)
            self._resident_configs.clear()
            return {"released": True, "cold": True, "resident_models": [], "unloaded_models": released}
        except Exception as exc:
            import logging
            logging.getLogger("uvicorn.error").warning(
                "Managed LLM residency cleanup failed; stopping owned sidecar: %s", exc
            )
            self._last_error = str(exc)
            self.stop()
            return {"released": True, "cold": True, "resident_models": [], "fallback": "process_stop"}

    def _build_command(
        self,
        *,
        model: str,
        model_path: str,
        backend: str,
        mmproj_path: str,
        ctx_size: int | None,
        startup_timeout: int | None,
        llama_server_bin: str,
        port: int,
        vision_port: int | None = None,
        dynamic_residency: bool = True,
    ) -> list[str]:
        cmd = [
            sys.executable,
            "-m",
            "local_asr_server.runtime.local_llm_entrypoint",
            "serve",
        ]
        cmd.extend(["--host", self.host, "--port", str(port), "--enable-admin-api"])
        if vision_port is not None:
            cmd.extend(["--mlx-vlm-server-port", str(vision_port)])
        # Start with exactly the model required by the current phase.
        # Additional registered models are activated through the 0.4 admin
        # API and the previous resident runtime is evicted first.
        cmd.extend(["--model", model])
        if model_path:
            cmd.extend(["--model-path", model_path])
        if backend:
            cmd.extend(["--backend", backend])
        if mmproj_path:
            cmd.extend(["--mmproj-path", mmproj_path])
        if ctx_size is not None:
            cmd.extend(["--ctx-size", str(ctx_size)])
        if startup_timeout is not None:
            cmd.extend(["--startup-timeout", str(startup_timeout)])
        if llama_server_bin:
            cmd.extend(["--llama-server-bin", llama_server_bin])
        return cmd

    def _select_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((self.host, 0))
            return int(sock.getsockname()[1])
