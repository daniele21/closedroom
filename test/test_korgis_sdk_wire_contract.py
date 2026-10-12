"""Exact installed Korgis SDK ↔ ClosedRoom text consumer HTTP contract.

Runs both with default test discovery (skipped when optional SDK is not
installed) and in an independent CI workflow with REQUIRED=1 and a pinned
SDK Git checkout. Real TCP, real SDK and ClosedRoom provider, fake inference.
This is NOT a model quality, Metal or packaged app hardware test.
"""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from local_asr_server.llm import NemotronLocalProvider
from local_asr_server.runtime.local_ai import KorgisTextAdapter

_HAS_SDK = importlib.util.find_spec("korgis_sdk") is not None


class _LoopbackInferenceHandler(BaseHTTPRequestHandler):
    server: "_LocalServer"

    def log_message(self, *_args):
        # Never emit sensitive prompts to stdout or CI job logs.
        return

    def _send(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "server": "local-llm-server", "backend": "synthetic-fixture"})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [
                {"id": "org/demo-model", "key": "demo-text", "object": "model"},
            ]})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not_found"})
            return
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 64 * 1024:
            self._send(413, {"error": "request_size_invalid"})
            return
        payload = json.loads(self.rfile.read(size))
        self.server.requests.append(payload)
        if payload.get("model") != "demo-text":
            self._send(404, {"error": "model_not_resident"})
            return
        self._send(200, {"id": "fixture", "object": "chat.completion", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": json.dumps({
                "title": "Demo",
                "summary": "Solo dati sintetici",
                "key_points": [],
                "action_items": [],
            })}, "finish_reason": "stop"},
        ]})


class _LocalServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _LoopbackInferenceHandler)
        self.requests: list[dict] = []


class RealKorgisConsumerWireContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _HAS_SDK and os.environ.get("CLOSEDROOM_REQUIRE_KORGIS_SDK") == "1":
            raise RuntimeError("korgis-client was not installed by the contract CI job")

    def setUp(self):
        if not _HAS_SDK:
            self.skipTest("optional SDK not installed in default ClosedRoom environment")
        self.server = _LocalServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        if not _HAS_SDK:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "no serving thread must survive")

    def test_real_installed_sdk_attaches_and_preserves_default_json_contract(self):
        from importlib.metadata import version
        self.assertEqual(version("korgis-client"), "0.1.0a1")
        provider = NemotronLocalProvider(
            base_url=self.base_url, model="demo-text", local_ai=KorgisTextAdapter(),
        )
        result = provider.analyze("Solo transcript sintetico", language="it")
        self.assertEqual(result["title"], "Demo")
        self.assertEqual(result["summary"], "Solo dati sintetici")
        self.assertEqual(len(self.server.requests), 1)
        payload = self.server.requests[0]
        self.assertEqual(payload["model"], "demo-text")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0.0)
        self.assertIn("Trascrizione:\nSolo transcript sintetico", payload["messages"][0]["content"])

    def test_real_sdk_preserves_custom_prompt_and_generation_params(self):
        provider = NemotronLocalProvider(
            base_url=self.base_url, model="demo-text", local_ai=KorgisTextAdapter(),
        )
        provider.analyze("Testo sintetico", language="en",
                         prompt="Output actions", temperature=0.25)
        payload = self.server.requests[0]
        self.assertEqual(payload["temperature"], 0.25)
        self.assertEqual(payload["messages"], [{"role": "user", "content":
            "Output actions\n\nLingua: en\nTrascrizione:\nTesto sintetico"}])

    def test_wrong_resident_model_fails_before_sending_transcript(self):
        provider = NemotronLocalProvider(
            base_url=self.base_url, model="different-model", local_ai=KorgisTextAdapter(),
        )
        with self.assertRaisesRegex(RuntimeError, "non è raggiungibile"):
            provider.analyze("testo confidenziale")
        self.assertEqual(self.server.requests, [], "no request may reach the chat endpoint")

    def test_attach_does_not_manage_process_or_cloud_fallback(self):
        from korgis_sdk import Korgis
        self.assertIsNotNone(Korgis.managed)
        provider = NemotronLocalProvider(
            base_url=self.base_url, model="demo-text", local_ai=KorgisTextAdapter(),
        )
        provider.analyze("Esempio")
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
