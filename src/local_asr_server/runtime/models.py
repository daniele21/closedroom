from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Literal


LOCAL_SERVICE_HOST = "127.0.0.1"
DEFAULT_API_PORT = 1236
DEFAULT_DEV_RELOAD_PORT = 1237
DEFAULT_LOCAL_LLM_PORT = 1235
DEFAULT_LOCAL_LLM_URL = f"http://{LOCAL_SERVICE_HOST}:{DEFAULT_LOCAL_LLM_PORT}"

SERVICE_STATUSES = {
    "not_configured",
    "binary_missing",
    "model_missing",
    "stopped",
    "starting",
    "loading_model",
    "ready",
    "busy",
    "failed",
    "crashed",
    "stopping",
    "unknown",
}

LocalLLMMode = Literal["auto", "external", "disabled"]
LLMQualityPreset = Literal["precise", "balanced", "creative"]
LLMReasoningPolicy = Literal["auto", "on", "off"]

LOCAL_LLM_MODES = frozenset({"auto", "external", "disabled"})
LLM_QUALITY_PRESETS = frozenset({"precise", "balanced", "creative"})
LLM_REASONING_POLICIES = frozenset({"auto", "on", "off"})


DEFAULT_LLM_QUALITY_PRESET: LLMQualityPreset = "balanced"
DEFAULT_LLM_REASONING: LLMReasoningPolicy = "auto"


@dataclass(frozen=True)
class AnalysisQualityDefaults:
    precise: float = 0.1
    balanced: float = 0.2
    creative: float = 0.5


ANALYSIS_QUALITY_DEFAULTS = AnalysisQualityDefaults()


def is_local_llm_model_path_explicit(
    settings: dict[str, Any], model: str | None = None,
) -> bool:
    """Return whether the selected model path is explicitly user/config supplied.

    Automatic LM Studio discovery is deliberately excluded: registered product
    models may be re-resolved by local-llm-server 0.4 after a zero-resident
    transition, while explicit paths must preserve their exact artifact through
    an owned process restart boundary.
    """
    selected_model = model or settings.get("local_llm_model") or ""
    model_paths = settings.get("local_llm_model_paths") or {}
    if not isinstance(model_paths, dict):
        model_paths = {}
    if model_paths.get(selected_model) or settings.get("local_llm_model_path"):
        return True
    if selected_model:
        return Path(selected_model).expanduser().exists()
    return False


def resolve_local_llm_model_path(settings: dict[str, Any], model: str | None = None) -> str:
    """Resolve model-specific paths before the legacy global model path."""

    selected_model = model or settings.get("local_llm_model") or ""
    model_paths = settings.get("local_llm_model_paths") or {}
    if not isinstance(model_paths, dict):
        model_paths = {}
    
    path = model_paths.get(selected_model) or settings.get("local_llm_model_path") or ""
    if path:
        return path

    if selected_model:
        # Check if the selected_model is already a path that exists
        model_path_obj = Path(selected_model).expanduser()
        if model_path_obj.exists():
            return str(model_path_obj.resolve())

        # Scan LM Studio models directory (skip in unit tests to ensure test hermeticity)
        import sys
        import os
        lm_studio_dir = Path("~/.lmstudio/models").expanduser()
        if ("unittest" not in sys.modules or os.environ.get("CLOSEDROOM_TEST_RESOLVE")) and lm_studio_dir.exists():
            query_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', selected_model) if t]
            if query_tokens:
                best_match = None
                best_match_score = 0
                best_match_len = 999999
                
                for p in lm_studio_dir.rglob("*"):
                    is_gguf_file = p.is_file() and p.suffix.lower() == ".gguf"
                    is_mlx_dir = p.is_dir() and (p / "config.json").exists()
                    
                    if not (is_gguf_file or is_mlx_dir):
                        continue
                        
                    path_str = str(p.relative_to(lm_studio_dir)).lower()
                    
                    # Exclude mmproj files unless explicitly requested
                    if "mmproj" in path_str and "mmproj" not in selected_model.lower():
                        continue
                        
                    matched_tokens = sum(1 for token in query_tokens if token in path_str)
                    
                    if matched_tokens > best_match_score:
                        best_match_score = matched_tokens
                        best_match = p
                        best_match_len = len(path_str)
                    elif matched_tokens == best_match_score and best_match_score > 0:
                        if len(path_str) < best_match_len:
                            best_match = p
                            best_match_len = len(path_str)
                            
                if best_match and best_match_score >= max(1, len(query_tokens) // 2):
                    return str(best_match.resolve())

    return ""
