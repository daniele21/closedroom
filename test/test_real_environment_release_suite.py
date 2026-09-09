from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


def load_suite():
    path = ROOT / "scripts" / "run_real_environment_release_suite.py"
    spec = importlib.util.spec_from_file_location(
        "run_real_environment_release_suite", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suite = load_suite()


def arguments(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "record_seconds": 8.0,
        "seed_record_seconds": 20.0,
        "capture_seconds": 6.0,
        "sample_interval": 0.75,
        "job_timeout": 900.0,
        "active_timeout": 120.0,
        "benchmark_repeats": 3,
        "keep_sandbox": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class RealEnvironmentReleaseSuiteTests(unittest.TestCase):
    def test_commands_use_same_exact_app_and_explicit_child_outputs(self) -> None:
        root = Path("/repo")
        app = Path("/release/ClosedRoom.app")
        measured_output = Path("/evidence/measured.json")
        contention_output = Path("/evidence/contention.json")
        commands = suite.build_commands(
            root,
            app,
            measured_output,
            contention_output,
            arguments(keep_sandbox=True),
        )

        self.assertEqual(
            [item[0] for item in commands],
            ["measured_release", "record_while_ai_busy"],
        )
        for _, command, _, _ in commands:
            self.assertIn(str(app), command)
            self.assertIn(str(root), command)
            self.assertIn("--keep-sandbox", command)
        self.assertIn(str(measured_output), commands[0][1])
        self.assertIn(str(contention_output), commands[1][1])

    def test_child_summary_never_copies_check_details_or_error_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "child.json"
            evidence.write_text(
                json.dumps(
                    {
                        "status": "fail",
                        "checks": [
                            {
                                "name": "mic_system_persisted",
                                "status": "fail",
                                "detail": {"transcript": "private meeting text"},
                            }
                        ],
                        "errors": ["private meeting text in child error"],
                    }
                ),
                encoding="utf-8",
            )
            summary = suite.child_summary(evidence, 1)

        self.assertEqual(summary["failed_checks"], ["mic_system_persisted"])
        self.assertEqual(summary["error_count"], 1)
        self.assertNotIn("private meeting text", json.dumps(summary))
        self.assertFalse(suite.child_passed(summary))

    def test_child_pass_requires_zero_exit_and_pass_report(self) -> None:
        self.assertTrue(suite.child_passed({"returncode": 0, "status": "pass"}))
        self.assertFalse(suite.child_passed({"returncode": 1, "status": "pass"}))
        self.assertFalse(suite.child_passed({"returncode": 0, "status": "fail"}))

    def _run_main(
        self, second_status: str = "pass"
    ) -> tuple[int, dict[str, object]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        app = root / "artifact" / "ClosedRoom.app"
        app.mkdir(parents=True)
        aggregate = root / "aggregate.json"

        call_index = 0

        def fake_run(
            command: list[str], **_: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal call_index
            call_index += 1
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            status = "pass" if call_index == 1 else second_status
            checks = []
            errors = []
            if status != "pass":
                checks = [
                    {
                        "name": "contention_native_both_tracks",
                        "status": "fail",
                        "detail": {"transcript": "private meeting text"},
                    }
                ]
                errors = ["private meeting text in child error"]
            output.write_text(
                json.dumps(
                    {
                        "status": status,
                        "checks": checks,
                        "errors": errors,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command, 0 if status == "pass" else 1
            )

        argv = [
            "run_real_environment_release_suite.py",
            "--root",
            str(root),
            "--app",
            str(app),
            "--output",
            str(aggregate),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(suite.platform, "system", return_value="Darwin"),
            patch.object(suite.platform, "machine", return_value="arm64"),
            patch.object(
                suite.measured,
                "git_state",
                return_value=("abc123", []),
            ),
            patch.object(
                suite.measured,
                "production_manifest_for",
                return_value=(
                    root / "artifact" / "build-manifest.json",
                    {"source": {"revision": "abc123"}},
                ),
            ),
            patch.object(suite.subprocess, "run", side_effect=fake_run),
        ):
            result = suite.main()

        return result, json.loads(aggregate.read_text(encoding="utf-8"))

    def test_main_passes_only_when_both_real_environment_runners_pass(self) -> None:
        result, report = self._run_main()
        self.assertEqual(result, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["source_revision"], "abc123")
        self.assertEqual(
            report["tests"]["measured_release"]["status"],
            "pass",
        )
        self.assertEqual(
            report["tests"]["record_while_ai_busy"]["status"],
            "pass",
        )
        self.assertEqual(
            report["non_automated_evidence"][0]["id"],
            "voiceover_subjective_usability",
        )

    def test_main_fails_and_surfaces_failed_child_check_without_payload(self) -> None:
        result, report = self._run_main(second_status="fail")
        self.assertEqual(result, 1)
        self.assertEqual(report["status"], "fail")
        contention = report["tests"]["record_while_ai_busy"]
        self.assertEqual(
            contention["failed_checks"],
            ["contention_native_both_tracks"],
        )
        self.assertEqual(contention["error_count"], 1)
        self.assertNotIn("private meeting text", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
