from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
import json
import re


class LocalAIClient(Protocol):
    def is_ready(self) -> bool:
        ...

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        ...

    def analyze_text(self, text: str, *, language: str = "it") -> Any:
        ...

    def analyze_audio(self, *, audio_path: str | Path, **kwargs: Any) -> Any:
        ...


class LocalAIRuntimePort(Protocol):
    """Client-side port for the local AI runtime already owned by ClosedRoom."""

    def create_client(self, *, base_url: str, model: str | None) -> LocalAIClient:
        ...

    def prepare_image_message(self, path: Path, prompt: str) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class LocalLLMServerAdapter:
    """Adapter for the bundled/installed local-llm-server client package.

    Runtime lifecycle and readiness remain owned by RuntimeServiceManager. This
    adapter only translates application inference calls to the concrete local
    runtime client and never performs remote fallback.
    """

    def create_client(self, *, base_url: str, model: str | None) -> LocalAIClient:
        try:
            from local_llm_server.client import LocalLLMClient
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "local-llm-server non è installato. "
                "Installa il wheel local_llm_server dalla directory dist del repository collegato."
            ) from exc
        return LocalLLMClient(base_url=base_url, model=model)

    def prepare_image_message(self, path: Path, prompt: str) -> list[dict[str, Any]]:
        try:
            from local_llm_server.vision import prepare_image_message
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "local-llm-server non è installato. "
                "Il runtime visuale locale richiede il package local_llm_server."
            ) from exc
        return prepare_image_message(path, prompt)



# Experimental, text-only attach transport. ClosedRoom always retains control
# over sidecar lifecycle, residency, application prompts and output validation.
_CLOSEDROOM_TEXT_ANALYSIS_PROMPT = """Analizza la seguente trascrizione e restituisci solo JSON valido:
{{
  "title": "...",
  "summary": "...",
  "key_points": ["...", "..."],
  "action_items": ["...", "..."]
}}

Lingua: {language}
Trascrizione:
{text}
"""


class KorgisTextClient:
    """Adapt the role-bound Korgis consumer to ClosedRoom's existing text port.

    The SDK is strictly opt-in and only an HTTP consumer: never Korgis.managed().
    Audio/VLM remain on their established separate runtime paths.
    """

    def __init__(self, *, base_url: str, model: str, korgis: Any) -> None:
        self.base_url = base_url
        self.model = model
        self._korgis = korgis
        self._bindings = {
            "schema_version": "korgis-client-bindings-v1",
            "app": "closedroom",
            "roles": {"analysis": {"model": model, "task": "chat"}},
        }

    def _connect(self) -> Any:
        return self._korgis.connect(self._bindings, base_url=self.base_url)

    def is_ready(self) -> bool:
        try:
            with self._connect():
                return True
        except Exception:
            # Same boolean contract as the existing client.is_ready(); errors
            # are never logged or expanded to include the meeting transcript.
            return False

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        with self._connect() as connection:
            response = connection.role("analysis").chat(messages, **kwargs)
        if not isinstance(response, dict):
            raise ValueError("Invalid local LLM response shape")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("Missing local LLM response choices")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("Missing local LLM response text")
        return message["content"]

    def analyze_text(self, text: str, *, language: str = "it") -> dict[str, Any]:
        prompt = _CLOSEDROOM_TEXT_ANALYSIS_PROMPT.format(language=language, text=text)
        raw = self.chat(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Legacy LocalLLMClient accepts an object wrapped in model prose.
            # Retain that narrow behavior for an opt-in consumer comparison.
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if match is None:
                raise ValueError("Local LLM response did not contain a JSON object") from None
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                raise ValueError("Invalid local LLM JSON object") from None
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object from local LLM")
        return parsed

    def analyze_audio(self, *, audio_path: str | Path, **kwargs: Any) -> Any:
        raise RuntimeError("korgis_text_transport_does_not_support_audio")


@dataclass(frozen=True, slots=True)
class KorgisTextAdapter:
    """Opt-in attach-only adapter for Nemotron analysis, not runtime management."""

    def create_client(self, *, base_url: str, model: str | None) -> LocalAIClient:
        if not model:
            raise RuntimeError("korgis_sdk_requires_explicit_model")
        try:
            from korgis_sdk import Korgis
        except ImportError as exc:
            raise RuntimeError("korgis_client_sdk_not_installed") from exc
        return KorgisTextClient(base_url=base_url, model=model, korgis=Korgis)

    def prepare_image_message(self, path: Path, prompt: str) -> list[dict[str, Any]]:
        raise RuntimeError("korgis_text_transport_does_not_support_vision")
