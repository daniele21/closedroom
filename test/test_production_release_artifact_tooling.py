from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1]


def load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


production = load("production_release_artifact_tooling", "scripts/build_production_artifact.py")


class ProductionNotaryKeychainTests(unittest.TestCase):
    @patch.object(production, "run")
    def test_notary_submit_uses_explicit_file_keychain(self, run: Mock) -> None:
        run.return_value = Mock(
            stdout=json.dumps({"id": "submission", "status": "Accepted"})
        )

        result = production.notary_submit(
            Path("ClosedRoom.dmg"),
            "closedroom-production",
            cwd=ROOT,
            keychain="/tmp/closedroom-release.keychain-db",
        )

        command = run.call_args.args[0]
        self.assertEqual(result["status"], "Accepted")
        self.assertEqual(
            command,
            [
                "xcrun",
                "notarytool",
                "submit",
                "ClosedRoom.dmg",
                "--keychain-profile",
                "closedroom-production",
                "--keychain",
                "/tmp/closedroom-release.keychain-db",
                "--wait",
                "--output-format",
                "json",
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 1800)

    @patch.object(production, "run")
    def test_notary_submit_keeps_existing_profile_behavior_without_keychain(
        self, run: Mock
    ) -> None:
        run.return_value = Mock(stdout=json.dumps({"status": "Accepted"}))

        production.notary_submit(
            Path("ClosedRoom.zip"),
            "closedroom-production",
            cwd=ROOT,
        )

        command = run.call_args.args[0]
        self.assertNotIn("--keychain", command)
        self.assertEqual(
            command,
            [
                "xcrun",
                "notarytool",
                "submit",
                "ClosedRoom.zip",
                "--keychain-profile",
                "closedroom-production",
                "--wait",
                "--output-format",
                "json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
