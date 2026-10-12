"""Experimental ClosedRoom -> Korgis SDK attach path and behavior boundaries."""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from local_asr_server.llm import NemotronLocalProvider
from local_asr_server.runtime.local_ai import (
    KorgisTextAdapter,
    LocalLLMServerAdapter,
)
from local_asr_server.services.analysis_service import AnalysisService
from local_asr_server.settings import DEFAULT_SETTINGS


class _FakeConnection:
    def __init__(self, calls: list, content: str = "local response") -> None:
        self.calls = calls
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def role(self, name):
        self.calls.append(("role", name))
        return self

    def chat(self, messages, **kwargs):
        self.calls.append(("chat", messages, kwargs))
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeKorgis:
    calls: list = []
    response = "local response"

    @classmethod
    def connect(cls, profile, *, base_url):
        cls.calls.append(("connect", profile, base_url))
        return _FakeConnection(cls.calls, cls.response)


class KorgisConsumerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeKorgis.calls = []
        _FakeKorgis.response = "local response"
        self.module = types.ModuleType("korgis_sdk")
        self.module.Korgis = _FakeKorgis
        self.patch_sdk = patch.dict(sys.modules, {"korgis_sdk": self.module})
        self.patch_sdk.start()

    def tearDown(self) -> None:
        self.patch_sdk.stop()

    def test_default_transport_and_provider_ownership_are_unchanged(self):
        self.assertEqual(DEFAULT_SETTINGS["local_llm_client_transport"], "legacy")
        self.assertIsNone(AnalysisService._text_transport_for_provider(
            {"local_llm_client_transport": "legacy"}, "nemotron_local"
        ))
        self.assertIsNone(AnalysisService._text_transport_for_provider(
            {"local_llm_client_transport": "korgis_sdk"}, "gemini"
        ))
        self.assertIsInstance(LocalLLMServerAdapter(), LocalLLMServerAdapter)

    def test_opt_in_text_binding_uses_exact_model_and_attaches_only(self):
        adapter = AnalysisService._text_transport_for_provider(
            {"local_llm_client_transport": "korgis_sdk"}, "nemotron_local"
        )
        self.assertIsInstance(adapter, KorgisTextAdapter)
        client = adapter.create_client(
            base_url="http://127.0.0.1:57931", model="nemotron-nano-4b-q8"
        )
        self.assertTrue(client.is_ready())
        self.assertEqual(
            client.chat([{"role": "user", "content": "Private meeting"}], temperature=0),
            "local response",
        )
        connections = [c for c in _FakeKorgis.calls if c[0] == "connect"]
        self.assertEqual(len(connections), 2)
        self.assertEqual(connections[0][2], "http://127.0.0.1:57931")
        self.assertEqual(connections[0][1], {
            "schema_version": "korgis-client-bindings-v1",
            "app": "closedroom",
            "roles": {"analysis": {"model": "nemotron-nano-4b-q8", "task": "chat"}},
        })
        self.assertEqual(
            [v for v in _FakeKorgis.calls if v[0] == "role"],
            [("role", "analysis")],
        )
        self.assertEqual(
            [v for v in _FakeKorgis.calls if v[0] == "chat"][0][1],
            [{"role": "user", "content": "Private meeting"}],
        )

    def test_nemotron_provider_preserves_existing_explicit_prompt(self):
        provider = NemotronLocalProvider(
            base_url="http://127.0.0.1:1235", model="text-model",
            local_ai=KorgisTextAdapter(),
        )
        self.assertEqual(
            provider.analyze("Meeting transcript", language="en",
                             prompt="Produce action items", temperature=0.2),
            "local response",
        )
        request = [c for c in _FakeKorgis.calls if c[0] == "chat"][0]
        self.assertIn("Produce action items\n\nLingua: en\nTrascrizione:\nMeeting transcript",
                      request[1][0]["content"])
        self.assertEqual(request[2], {"temperature": 0.2})

    def test_nemotron_default_prompt_returns_same_dict_contract(self):
        _FakeKorgis.response = json.dumps({
            "title": "Sync", "summary": "Local", "key_points": [], "action_items": []
        })
        provider = NemotronLocalProvider(model="text-model", local_ai=KorgisTextAdapter())
        parsed = provider.analyze("Presenta i risultati", language="it")
        self.assertEqual(parsed["title"], "Sync")
        call = [c for c in _FakeKorgis.calls if c[0] == "chat"][0]
        self.assertIn("Trascrizione:\nPresenta i risultati", call[1][0]["content"])
        self.assertEqual(call[2], {
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        })

    def test_malformed_json_is_explicit_and_never_echoes_sensitive_text(self):
        _FakeKorgis.response = "secret customer transcript - not JSON"
        provider = NemotronLocalProvider(model="text-model", local_ai=KorgisTextAdapter())
        with self.assertRaisesRegex(ValueError, "JSON object") as caught:
            provider.analyze("Very private transcript")
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("customer", str(caught.exception))

    def test_unreachable_sdk_server_has_no_legacy_or_cloud_fallback(self):
        class OfflineKorgis:
            @staticmethod
            def connect(*_args, **_kwargs):
                raise RuntimeError("server not available")

        self.module.Korgis = OfflineKorgis
        client = KorgisTextAdapter().create_client(base_url="http://127.0.0.1:1235",
                                                    model="text-model")
        self.assertFalse(client.is_ready())
        with self.assertRaises(RuntimeError):
            client.chat([{"role": "user", "content": "private"}])

    def test_missing_sdk_and_unsupported_models_fail_closed(self):
        with patch.dict(sys.modules, {"korgis_sdk": None}):
            with self.assertRaisesRegex(RuntimeError, "korgis_client_sdk_not_installed"):
                KorgisTextAdapter().create_client(base_url="http://127.0.0.1:1235",
                                                   model="model")
        with self.assertRaisesRegex(RuntimeError, "explicit_model"):
            KorgisTextAdapter().create_client(base_url="http://127.0.0.1:1235",
                                               model=None)
        with self.assertRaisesRegex(RuntimeError, "does_not_support_audio"):
            KorgisTextAdapter().create_client(base_url="http://127.0.0.1:1235",
                                               model="model").analyze_audio(
                audio_path=Path("meeting.wav")
            )
        with self.assertRaisesRegex(RuntimeError, "does_not_support_vision"):
            KorgisTextAdapter().prepare_image_message(Path("frame.png"), "describe")

    def test_voxtral_is_not_silently_routed_to_legacy_or_sdk(self):
        for provider, expected in (
            ("voxtral_local", "korgis_sdk_text_only"),
            ("nemotron_local", None),
        ):
            if expected:
                with self.assertRaises(HTTPException) as caught:
                    AnalysisService._text_transport_for_provider(
                        {"local_llm_client_transport": "korgis_sdk"}, provider
                    )
                self.assertEqual(caught.exception.status_code, 422)
                self.assertEqual(caught.exception.detail["code"], expected)
        with self.assertRaises(HTTPException) as caught:
            AnalysisService._text_transport_for_provider(
                {"local_llm_client_transport": "nonexistent"}, "nemotron_local"
            )
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
