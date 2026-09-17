from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


def load_suite():
    path = ROOT / "scripts" / "run_real_environment_release_suite.py"
    spec = importlib.util.spec_from_file_location(
        "run_real_environment_release_suite_nested_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suite = load_suite()


class NestedUIDiagnosticPropagationTests(unittest.TestCase):
    def _write_parent(
        self,
        directory: Path,
        report_field: str,
        nested_path: Path,
    ) -> Path:
        parent = directory / "parent.json"
        parent.write_text(
            json.dumps(
                {
                    "status": "fail",
                    "checks": [
                        {"name": "target_mac_recording_ui", "status": "fail"}
                    ],
                    "errors": ["check failed: target_mac_recording_ui"],
                    report_field: str(nested_path),
                }
            ),
            encoding="utf-8",
        )
        return parent

    def test_measured_parent_surfaces_bounded_diagnostic_from_ui_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            nested = directory / "ui-target-mac-report.json"
            nested.write_text(
                json.dumps(
                    {
                        "errors": [
                            "closedroom_window_missing|running_application_present=true|"
                            "ax_windows_count=0|cg_onscreen_normal_window_count=1|"
                            "window_title=private meeting title"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            parent = self._write_parent(directory, "ui_evidence_report", nested)
            summary = suite.child_summary(parent, 1)

        self.assertEqual(
            summary["ui_failure_diagnostic"],
            {
                "code": "closedroom_window_missing",
                "running_application_present": True,
                "ax_windows_count": 0,
                "cg_onscreen_normal_window_count": 1,
            },
        )
        self.assertNotIn("private meeting title", json.dumps(summary))
        self.assertEqual(summary["error_count"], 1)

    def test_contention_parent_surfaces_bounded_diagnostic_from_seed_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            nested = directory / "contention-seed-ui-report.json"
            nested.write_text(
                json.dumps(
                    {
                        "errors": [
                            "closedroom_window_missing|running_application_active=false|"
                            "running_application_hidden=true|cg_window_count=0"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            parent = self._write_parent(directory, "seed_ui_report", nested)
            summary = suite.child_summary(parent, 1)

        self.assertEqual(
            summary["ui_failure_diagnostic"],
            {
                "code": "closedroom_window_missing",
                "running_application_active": False,
                "running_application_hidden": True,
                "cg_window_count": 0,
            },
        )

    def test_nested_report_outside_parent_evidence_directory_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            outside = root / "outside.json"
            outside.write_text(
                json.dumps(
                    {
                        "errors": [
                            "closedroom_window_missing|running_application_present=true"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            parent = self._write_parent(
                evidence_dir, "ui_evidence_report", outside
            )
            summary = suite.child_summary(parent, 1)

        self.assertNotIn("ui_failure_diagnostic", summary)

    def test_nested_arbitrary_errors_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            nested = directory / "ui-target-mac-report.json"
            nested.write_text(
                json.dumps({"errors": ["private meeting text"]}),
                encoding="utf-8",
            )
            parent = self._write_parent(directory, "ui_evidence_report", nested)
            summary = suite.child_summary(parent, 1)

        self.assertNotIn("ui_failure_diagnostic", summary)
        self.assertNotIn("private meeting text", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
