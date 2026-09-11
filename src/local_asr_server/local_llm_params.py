"""
local_llm_params.py — Manage parameter overrides for local-llm-server inference.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from local_asr_server.paths import get_local_llm_params_file

logger = logging.getLogger("uvicorn.error")

LOCAL_LLM_REGISTRY_PATHS_ENV = "LOCAL_LLM_REGISTRY_PATHS"

DEFAULT_LOCAL_LLM_PARAMS: dict[str, Any] = {
    "models": {
        "nemotron-nano-4b-q8": {
            "params": {
                "ctx_size": 36466,
                "n_gpu_layers": 42
            }
        },
        "qwen3-vl-4b": {
            "params": {
                "max_kv_size": 8192,
                "startup_timeout": 300
            }
        }
    },
    "chat_params": {
        "temperature": 0.0,
        "max_tokens": 512,
        "shared_content_max_tokens": 768
    }
}


def _default_params_copy() -> dict[str, Any]:
    return {
        "models": {
            key: {**value, "params": dict(value.get("params") or {})}
            for key, value in DEFAULT_LOCAL_LLM_PARAMS["models"].items()
        },
        "chat_params": dict(DEFAULT_LOCAL_LLM_PARAMS["chat_params"]),
    }


def load_local_llm_params() -> dict[str, Any]:
    """Load ClosedRoom-owned local LLM inference overrides.

    If the config file does not exist, write the default template to disk.
    """
    params_file = get_local_llm_params_file()
    if not params_file.exists():
        try:
            params_file.parent.mkdir(parents=True, exist_ok=True)
            with open(params_file, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_LOCAL_LLM_PARAMS, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write default local-llm-params config: %s", exc)
        return _default_params_copy()

    try:
        with open(params_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            merged = _default_params_copy()
            if "models" in data and isinstance(data["models"], dict):
                # The file is the user-facing source of truth for model overrides.
                merged["models"] = data["models"]
            if "chat_params" in data and isinstance(data["chat_params"], dict):
                merged["chat_params"].update(data["chat_params"])
            return merged
    except Exception as exc:
        logger.warning("Failed to load local-llm-params config file: %s. Using defaults.", exc)

    return _default_params_copy()


def _external_registry_paths_without(adapter_file: Path) -> list[str]:
    """Preserve caller-provided external registries while excluding our prior overlay."""
    raw = os.environ.get(LOCAL_LLM_REGISTRY_PATHS_ENV, "")
    if not raw.strip():
        return []
    adapter = adapter_file.expanduser().resolve()
    retained: list[str] = []
    for value in raw.split(os.pathsep):
        value = value.strip()
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if candidate == adapter:
            continue
        retained.append(str(candidate))
    return retained


def configure_local_llm_server_registry() -> Path:
    """Materialize ClosedRoom overrides through local-llm-server's public API.

    local-llm-server 0.4 exposes generic registry overlays through
    ``LOCAL_LLM_REGISTRY_PATHS``. ClosedRoom writes one private adapter file and
    appends it to that public environment contract instead of mutating upstream
    module globals. Any pre-existing external registry layers are preserved.

    The upstream user registry keeps the precedence defined by local-llm-server
    0.4. ClosedRoom does not rewrite or monkey-patch that upstream source.
    """
    import local_llm_server.registry as upstream_registry

    adapter_file = get_local_llm_params_file().with_name("local_llm_registry.yaml")
    external_paths = _external_registry_paths_without(adapter_file)

    # Build the adapter from genuine upstream inputs, excluding an older
    # ClosedRoom-generated overlay from a prior invocation in this process.
    previous_env = os.environ.get(LOCAL_LLM_REGISTRY_PATHS_ENV)
    try:
        if external_paths:
            os.environ[LOCAL_LLM_REGISTRY_PATHS_ENV] = os.pathsep.join(external_paths)
        else:
            os.environ.pop(LOCAL_LLM_REGISTRY_PATHS_ENV, None)
        registry = upstream_registry.load_registry()
    finally:
        if previous_env is None:
            os.environ.pop(LOCAL_LLM_REGISTRY_PATHS_ENV, None)
        else:
            os.environ[LOCAL_LLM_REGISTRY_PATHS_ENV] = previous_env

    models: dict[str, Any] = {}
    for key, entry in (registry.get("models") or {}).items():
        copied = dict(entry)
        copied["params"] = dict(entry.get("params") or {})
        models[key] = copied

    configured = load_local_llm_params().get("models") or {}
    startup_models: list[str] = []
    if isinstance(configured, dict):
        for key, override in configured.items():
            if key not in models:
                logger.warning(
                    "Ignoring ClosedRoom override for unknown local LLM model: %s",
                    key,
                )
                continue
            params = override.get("params") if isinstance(override, dict) else None
            if isinstance(params, dict):
                models[key]["params"].update(params)
            startup_models.append(key)

    overlay = {
        "models_dir": str(registry["models_dir"]),
        "defaults": dict(registry.get("defaults") or {}),
        "models": models,
        "default_model": registry.get("default_model"),
        "startup_models": startup_models or list(registry.get("startup_models") or []),
    }
    adapter_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = adapter_file.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(adapter_file)
    adapter_file.chmod(0o600)

    # The upstream CLI reads this public environment contract when it loads its
    # registry. Append our overlay exactly once and preserve existing layers.
    combined = [*external_paths, str(adapter_file.resolve())]
    os.environ[LOCAL_LLM_REGISTRY_PATHS_ENV] = os.pathsep.join(combined)
    return adapter_file
