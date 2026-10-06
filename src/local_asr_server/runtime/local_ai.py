from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


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
