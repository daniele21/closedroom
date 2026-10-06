from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from local_asr_server.bundled_module_dispatch import dispatch_bundled_module


class BundledModuleDispatchTests(unittest.TestCase):
    def test_ignores_regular_closedroom_arguments(self) -> None:
        self.assertFalse(dispatch_bundled_module(["ClosedRoom", "--other"]))

    def test_dispatches_bundle_runtime_smoke(self) -> None:
        with patch(
            "local_asr_server.bundled_module_dispatch._run_bundle_runtime_smoke"
        ) as smoke:
            self.assertTrue(dispatch_bundled_module(["ClosedRoom", "bundle-runtime-smoke"]))
        smoke.assert_called_once_with()

    def test_dispatches_local_llm_server_cli(self) -> None:
        with patch("local_llm_server.cli.main") as main, patch.object(sys, "argv", ["ClosedRoom"]):
            self.assertTrue(dispatch_bundled_module(["ClosedRoom", "-m", "local_llm_server", "serve", "--port", "1235"]))
            main.assert_called_once_with()
            self.assertEqual(sys.argv, ["local_llm_server", "serve", "--port", "1235"])

    def test_dispatches_closedroom_local_llm_entrypoint(self) -> None:
        with patch(
            "local_asr_server.runtime.local_llm_entrypoint.run_local_llm_server_cli"
        ) as run_local_llm, patch.object(sys, "argv", ["ClosedRoom"]):
            self.assertTrue(
                dispatch_bundled_module([
                    "ClosedRoom", "-m",
                    "local_asr_server.runtime.local_llm_entrypoint",
                    "serve", "--port", "1235",
                ])
            )
            run_local_llm.assert_called_once_with()
            self.assertEqual(
                sys.argv,
                [
                    "local_asr_server.runtime.local_llm_entrypoint",
                    "serve",
                    "--port",
                    "1235",
                ],
            )

    def test_dispatches_mlx_vlm_server_module(self) -> None:
        with patch("local_asr_server.bundled_module_dispatch.runpy.run_module") as run_module, patch.object(sys, "argv", ["ClosedRoom"]):
            self.assertTrue(dispatch_bundled_module(["ClosedRoom", "-m", "mlx_vlm.server", "--port", "8092"]))
            run_module.assert_called_once_with("mlx_vlm.server", run_name="__main__")
            self.assertEqual(sys.argv, ["mlx_vlm.server", "--port", "8092"])

    def test_dispatches_inspect_meeting_to_bundled_cli(self) -> None:
        with patch("local_asr_server.cli.main") as main, patch.object(sys, "argv", ["ClosedRoom"]):
            self.assertTrue(
                dispatch_bundled_module(
                    ["ClosedRoom", "inspect-meeting", "recording-123", "--json"]
                )
            )
            main.assert_called_once_with()
            self.assertEqual(
                sys.argv,
                ["local-asr", "inspect-meeting", "recording-123", "--json"],
            )


if __name__ == "__main__":
    unittest.main()
