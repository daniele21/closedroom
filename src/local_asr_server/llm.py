"""
llm.py — LLM provider abstraction for ClosedRoom analysis.

Providers:
  - MockProvider         — simulated response, no dependencies
  - GeminiProvider       — Google Gemini cloud API
  - NemotronLocalProvider — local Nemotron 4B via local-llm-server (text)
  - VoxtralLocalProvider  — local Voxtral 3B via local-llm-server (audio + text)
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from local_asr_server.runtime.models import DEFAULT_LOCAL_LLM_URL
from local_asr_server.prompts import load_prompts

logger = logging.getLogger("uvicorn.error")

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "custom",
)


# ── Base class ────────────────────────────────────────────────────────────────

class BaseLLMProvider:
    """Base interface for all LLM analysis providers."""

    def analyze(self, text: str, prompt: Optional[str] = None, temperature: Optional[float] = None) -> dict:
        """Analyze a transcript text and return a structured result dict."""
        raise NotImplementedError("Subclasses must implement analyze()")


# ── Mock provider ─────────────────────────────────────────────────────────────

class MockProvider(BaseLLMProvider):
    """Simulated provider for development and testing (no external calls)."""

    @staticmethod
    def _shared_notes_response(text: str, prompt: str) -> dict:
        if "Merge the supplied partial structured meeting notes" in prompt:
            try:
                payload = json.loads(text)
                partials = payload.get("partials") or []
            except Exception:
                partials = []
            summaries = [
                partial.get("summary")
                for partial in partials
                if isinstance(partial, dict) and isinstance(partial.get("summary"), dict)
            ]
            refs = [
                ref
                for summary in summaries
                for ref in summary.get("source_refs") or []
                if isinstance(ref, dict)
            ]
            generated = {
                "summary": {
                    "text": "Riepilogo simulato aggregato del meeting.",
                    "source_refs": refs[:3],
                },
                "actions": [
                    item
                    for partial in partials
                    if isinstance(partial, dict)
                    for item in partial.get("actions") or []
                    if isinstance(item, dict)
                ],
                "decisions": [
                    item
                    for partial in partials
                    if isinstance(partial, dict)
                    for item in partial.get("decisions") or []
                    if isinstance(item, dict)
                ],
                "risks": [
                    item
                    for partial in partials
                    if isinstance(partial, dict)
                    for item in partial.get("risks") or []
                    if isinstance(item, dict)
                ],
            }
            if not generated["summary"]["source_refs"]:
                generated["summary"]["text"] = ""
            return {"generated": generated}

        segment_ids = []
        for raw in re.findall(r"\[S([^\s\]]+)", text):
            value = int(raw) if raw.isdigit() else raw
            if value not in segment_ids:
                segment_ids.append(value)
        source_refs = [{"segment_id": segment_id} for segment_id in segment_ids[:3]]
        return {
            "generated": {
                "summary": {
                    "text": "Riepilogo simulato basato sulla trascrizione." if source_refs else "",
                    "source_refs": source_refs,
                },
                "actions": [],
                "decisions": [],
                "risks": [],
            }
        }

    def analyze(self, text: str, prompt: Optional[str] = None, temperature: Optional[float] = None) -> dict:
        time.sleep(1.5)  # Simulate API latency
        if prompt and "CLOSEDROOM_MEETING_NOTES_V2" in prompt:
            return self._shared_notes_response(text, prompt)

        words = text.split()
        word_count = len(words)
        preview = " ".join(words[:5]) + "..." if word_count > 5 else text

        return {
            "title": f"Analisi di: {preview}",
            "summary": (
                f"Questo è un riepilogo simulato della trascrizione che contiene {word_count} parole. "
                "Il testo analizza i temi principali introdotti nel discorso, evidenziando i passaggi chiave."
            ),
            "key_points": [
                "Punto chiave 1: Introduzione e contesto iniziale della registrazione.",
                f"Punto chiave 2: Analisi quantitativa dei dati (rilevate {word_count} parole nel testo).",
                "Punto chiave 3: Conclusioni e considerazioni finali emerse durante la sessione.",
            ],
            "action_items": [
                "Verificare la correttezza della trascrizione importata.",
                "Configurare un provider LLM reale per ottenere analisi effettive.",
                "Condividere i punti chiave del riepilogo con il team.",
            ],
        }


# ── Gemini cloud provider ─────────────────────────────────────────────────────

class GeminiProvider(BaseLLMProvider):
    """Google Gemini cloud API provider."""

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_GEMINI_MODEL

    def analyze(self, text: str, prompt: Optional[str] = None, temperature: Optional[float] = None) -> dict:
        if not self.api_key:
            raise ValueError("Chiave API Gemini mancante o non configurata.")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        if not prompt:
            prompts = load_prompts()
            prompt_instruction = prompts.get("default_instruction", {}).get("it", "Analizza la seguente trascrizione audio.")
        else:
            prompt_instruction = prompt
        prompt_str = (
            f"{prompt_instruction}\n\n"
            "La trascrizione è la seguente:\n\n"
            f"{text}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt_str}]}]
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if not candidates:
                    raise ValueError("Nessuna risposta generata da Gemini.")
                content_text = candidates[0]["content"]["parts"][0]["text"]
                return content_text

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            logger.error("Gemini HTTP Error: %s - %s", e.code, err_body)
            raise Exception(f"Errore Gemini API: {e.code} - {err_body}")
        except Exception as e:
            logger.error("Errore durante la chiamata a Gemini: %s", e)
            raise Exception(f"Errore durante l'analisi con Gemini: {e}")


# ── Local providers (via local-llm-server) ────────────────────────────────────

class NemotronLocalProvider(BaseLLMProvider):
    """
    Local text analysis via Nemotron 4B GGUF running in local-llm-server.

    Expects a running local-llm-server instance at `base_url` (default port 1235).
    Does NOT auto-start the server — the user must run local-llm-server separately.
    """

    def __init__(self, base_url: str = DEFAULT_LOCAL_LLM_URL, model: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def analyze(
        self,
        text: str,
        language: str = "it",
        prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        try:
            from local_llm_server.client import LocalLLMClient  # lazy import
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "local-llm-server non è installato. "
                "Installa il wheel local_llm_server dalla directory dist del repository collegato."
            ) from exc

        client = LocalLLMClient(base_url=self.base_url, model=self.model)
        if not client.is_ready():
            raise RuntimeError(
                f"Il server LLM locale non è raggiungibile su {self.base_url}. "
                "Avvia local-llm-server prima di usare questo provider."
            )
        if prompt:
            full_prompt = (
                f"{prompt}\n\n"
                f"Lingua: {language}\n"
                f"Trascrizione:\n{text}"
            )
            content = client.chat(
                [{"role": "user", "content": full_prompt}],
                temperature=temperature if temperature is not None else 0.0,
            )
            return content
        return client.analyze_text(text, language=language)


class VoxtralLocalProvider(BaseLLMProvider):
    """
    Local analysis via Voxtral Mini 3B running in local-llm-server (llama-server subprocess).

    Supports:
      - analyze(text)         — text fallback (uses Voxtral in text-only mode)
      - analyze_audio(path)   — direct audio analysis (multimodal, requires soundfile+numpy)
    """

    def __init__(self, base_url: str = DEFAULT_LOCAL_LLM_URL, model: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _get_client(self):
        """Return a ready LocalLLMClient or raise a descriptive error."""
        try:
            from local_llm_server.client import LocalLLMClient  # lazy import
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "local-llm-server non è installato. "
                "Installa il wheel local_llm_server dalla directory dist del repository collegato."
            ) from exc

        client = LocalLLMClient(base_url=self.base_url, model=self.model)
        if not client.is_ready():
            raise RuntimeError(
                f"Il server LLM locale non è raggiungibile su {self.base_url}. "
                "Avvia local-llm-server con il modello Voxtral prima di usare questo provider."
            )
        return client

    def analyze(
        self,
        text: str,
        language: str = "it",
        prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        """Text-only analysis fallback (uses Voxtral in chat mode)."""
        client = self._get_client()
        if prompt:
            full_prompt = (
                f"{prompt}\n\n"
                f"Lingua: {language}\n"
                f"Trascrizione:\n{text}"
            )
            content = client.chat(
                [{"role": "user", "content": full_prompt}],
                temperature=temperature if temperature is not None else 0.0,
            )
            return content
        return client.analyze_text(text, language=language)

    def analyze_audio(
        self,
        audio_path: str | Path,
        task: str = "analysis",
        question: Optional[str] = None,
        language: str = "it",
    ) -> dict:
        """
        Direct audio analysis via Voxtral multimodal.

        Parameters
        ----------
        audio_path:  Path to the audio file (any format; converted internally to 16kHz WAV).
        task:        One of: transcribe, summary, analysis, insights, qa.
        question:    Required when task='qa'.
        language:    Response language hint (default: 'it').
        """
        client = self._get_client()
        result = client.analyze_audio(
            audio_path=audio_path,
            task=task,
            question=question,
            language=language,
        )
        # Ensure the result always has the standard analysis schema keys
        if isinstance(result, str):
            return {
                "title": "Analisi audio",
                "summary": result,
                "key_points": [],
                "action_items": [],
            }
        return result


# ── Service factory ───────────────────────────────────────────────────────────

LLM_PROVIDER_NAMES = frozenset({"mock", "gemini", "nemotron_local", "voxtral_local"})

class LLMService:
    """Factory that instantiates the correct provider from a name string."""

    @staticmethod
    def get_provider(
        provider_name: str,
        api_key: Optional[str] = None,
        local_llm_url: Optional[str] = None,
        local_llm_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
    ) -> BaseLLMProvider:
        """
        Return an LLM provider instance.

        Parameters
        ----------
        provider_name:  One of: mock, gemini, nemotron_local, voxtral_local.
        api_key:        Gemini API key (only used with provider_name='gemini').
        local_llm_url:  Base URL of the running local-llm-server instance
                        (used by nemotron_local and voxtral_local; defaults to
                        DEFAULT_LOCAL_LLM_URL if not provided).
        """
        url = (local_llm_url or DEFAULT_LOCAL_LLM_URL).rstrip("/")

        if provider_name == "gemini":
            return GeminiProvider(api_key or "", gemini_model or DEFAULT_GEMINI_MODEL)
        if provider_name == "nemotron_local":
            return NemotronLocalProvider(base_url=url, model=local_llm_model)
        if provider_name == "voxtral_local":
            return VoxtralLocalProvider(base_url=url, model=local_llm_model)
        return MockProvider()
