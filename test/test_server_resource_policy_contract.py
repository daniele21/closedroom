from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVER = ROOT / "src" / "local_asr_server" / "server.py"


class ServerResourcePolicyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SERVER.read_text(encoding="utf-8")

    def test_managed_llm_is_not_speculatively_started_at_application_startup(self) -> None:
        self.assertNotIn("runtime_services.start_llm()", self.source)
        self.assertIn("managed on demand", self.source)
        self.assertIn("ensure_llm_ready() starts it on the first", self.source)

    def test_resource_policy_reads_canonical_recording_store_and_guards_shared_arbiter(self) -> None:
        self.assertIn(
            "recording_has_active_capture(recording_store.active_recording())",
            self.source,
        )
        self.assertIn(
            "admission_guard=resource_policy.assert_heavy_work_admissible",
            self.source,
        )
        self.assertEqual(self.source.count("HeavyWorkloadArbiter.from_env("), 1)


if __name__ == "__main__":
    unittest.main()
