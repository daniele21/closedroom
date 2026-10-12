"""Probe is exercised using the actual installed SDK but a declared fake endpoint.

Only a separate target-Mac run with a resident model may supply a live device
observation. These tests never claim backend/weights/TCC or Metal evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from test_korgis_sdk_wire_contract import _LocalServer

_PROBE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_korgis_live_inference.py"
_spec = importlib.util.spec_from_file_location("closedroom_live_korgis_probe", _PROBE_PATH)
assert _spec is not None and _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

_HAS_SDK = importlib.util.find_spec("korgis_sdk") is not None


class KorgisLiveInferenceProbeContract(unittest.TestCase):
    def setUp(self):
        self.server = _LocalServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "no fake server thread survives")

    def test_endpoint_rejects_non_loopback_and_credential_smuggling_before_network(self):
        values = (
            "https://127.0.0.1:1235", "http://127.0.0.2:1235",
            "http://example.com:1235", "http://localhost:1235",
            "http://127.0.0.1:1235/path",
            "http://user:password@127.0.0.1:1235",
            "http://127.0.0.1:1235?q=1",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(probe.ProbeFailure):
                probe.run_probe(endpoint=value, model="demo-text")
        self.assertEqual(self.server.requests, [])

    def test_missing_model_fails_before_sensitive_request(self):
        with self.assertRaisesRegex(probe.ProbeFailure, "requested_model_not_resident"):
            probe.run_probe(endpoint=self.endpoint, model="not-installed")
        self.assertEqual(self.server.requests, [])

    def test_bad_model_name_fails_before_server_access(self):
        for model in ("/private/transcript", "model?token=x", "bad space", ""):
            with self.subTest(model=model), self.assertRaises(probe.ProbeFailure):
                probe.run_probe(endpoint=self.endpoint, model=model)
        self.assertEqual(self.server.requests, [])

    @unittest.skipUnless(_HAS_SDK, "optional consumer wheel absent in this environment")
    def test_real_sdk_and_closedroom_provider_complete_loopback_probe(self):
        status = probe.run_probe(endpoint=self.endpoint, model="demo-text")
        self.assertEqual(status["status"], "pass")
        self.assertEqual(status["checks"]["closedroom_note_shape"], "pass")
        self.assertGreaterEqual(status["latency_seconds"], 0)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0]["model"], "demo-text")

    @unittest.skipUnless(_HAS_SDK, "optional consumer wheel absent in this environment")
    def test_probe_evidence_is_bounded_without_prompt_or_model_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "probe.json"
            code = probe.main([
                "--endpoint", self.endpoint, "--model", "demo-text",
                "--output", str(output),
            ])
            self.assertEqual(code, 0)
            body = output.read_text(encoding="utf-8")
            data = json.loads(body)
            self.assertEqual(data["status"], "pass")
            self.assertEqual(data["weights_identity"], "unverified")
            self.assertEqual(data["native_capture"], "not_tested")
            self.assertEqual(data["output_quality"], "shape_only_not_semantically_judged")
            self.assertFalse(data["sensitive_content_saved"])
            for forbidden in ("Atlas", "Laura", "Marco", "Solo dati sintetici",
                              "Riunione del progetto", str(output)):
                self.assertNotIn(forbidden, body)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
