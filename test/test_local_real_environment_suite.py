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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load_module(
    "local_real_environment_policy_test",
    ROOT / "scripts" / "local_real_environment_policy.py",
)
suite = load_module(
    "run_local_real_environment_suite_test",
    ROOT / "scripts" / "run_local_real_environment_suite.py",
)


def write_manifest(
    artifact_dir: Path,
    app: Path,
    *,
    revision: str = "abc123",
    dirty: bool = False,
    signing: str = "ad-hoc",
    created_at: str = "2026-09-09T10:00:00+00:00",
) -> Path:
    manifest = {
        "status": "successful",
        "created_at": created_at,
        "source": {"revision": revision, "dirty": dirty},
        "lineage": {"platform": "macos", "architecture": "arm64"},
        "configuration": {"signing": signing},
        "validation": {"build": "pass", "codesign": "pass"},
        "artifacts": {"app": {"path": app.name}},
    }
    path = artifact_dir / "build-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


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


class LocalRealEnvironmentPolicyTests(unittest.TestCase):
    def test_accepts_finalized_clean_ad_hoc_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            app = artifact_dir / "ClosedRoom.app"
            app.mkdir(parents=True)
            manifest_path = write_manifest(artifact_dir, app)

            actual_path, manifest = policy.local_manifest_for(app)

        self.assertEqual(actual_path, manifest_path)
        self.assertEqual(manifest["configuration"]["signing"], "ad-hoc")

    def test_rejects_dirty_or_non_ad_hoc_artifacts(self) -> None:
        for dirty, signing in ((True, "ad-hoc"), (False, "identified")):
            with self.subTest(dirty=dirty, signing=signing):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    app = artifact_dir / "ClosedRoom.app"
                    app.mkdir(parents=True)
                    write_manifest(
                        artifact_dir,
                        app,
                        dirty=dirty,
                        signing=signing,
                    )
                    with self.assertRaises(RuntimeError):
                        policy.local_manifest_for(app)

    def test_finds_newest_exact_local_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "dist" / "artifacts" / "lineage" / "first"
            second_dir = root / "dist" / "artifacts" / "lineage" / "second"
            first_app = first_dir / "ClosedRoom-first.app"
            second_app = second_dir / "ClosedRoom-second.app"
            first_app.mkdir(parents=True)
            second_app.mkdir(parents=True)
            write_manifest(
                first_dir,
                first_app,
                revision="abc123",
                created_at="2026-09-09T10:00:00+00:00",
            )
            second_manifest = write_manifest(
                second_dir,
                second_app,
                revision="abc123",
                created_at="2026-09-09T11:00:00+00:00",
            )

            found = policy.find_exact_local_app(root, "abc123456")

        assert found is not None
        self.assertEqual(found[0], second_app)
        self.assertEqual(found[1], second_manifest)


class LocalRealEnvironmentSuiteTests(unittest.TestCase):
    def test_commands_use_local_adapter_and_same_exact_app(self) -> None:
        root = Path("/repo")
        app = Path("/artifact/ClosedRoom.app")
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
            self.assertIn("scripts/local_real_environment_child.py", command)
            self.assertIn(str(app), command)
            self.assertIn(str(root), command)
            self.assertIn("--keep-sandbox", command)
        self.assertIn("measured_release", commands[0][1])
        self.assertIn("record_while_ai_busy", commands[1][1])

    def test_main_can_pass_local_evidence_while_distribution_remains_blocked(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        artifact_dir = root / "artifact"
        app = artifact_dir / "ClosedRoom.app"
        app.mkdir(parents=True)
        manifest_path = write_manifest(artifact_dir, app, revision="abc123")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = root / "local-report.json"

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            child_output = Path(command[command.index("--output") + 1])
            child_output.parent.mkdir(parents=True, exist_ok=True)
            child_output.write_text(
                json.dumps({"status": "pass", "checks": [], "errors": []}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        argv = [
            "run_local_real_environment_suite.py",
            "--root",
            str(root),
            "--output",
            str(output),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(suite.platform, "system", return_value="Darwin"),
            patch.object(suite.platform, "machine", return_value="arm64"),
            patch.object(suite, "required_tools_missing", return_value=[]),
            patch.object(suite.measured, "git_state", return_value=("abc123", [])),
            patch.object(
                suite,
                "select_local_artifact",
                return_value=(app, manifest_path, manifest, "reused_exact"),
            ),
            patch.object(suite.subprocess, "run", side_effect=fake_run),
        ):
            result = suite.main()

        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["qualification_scope"], "local_real_environment")
        self.assertEqual(report["distribution_authority"]["status"], "blocked")
        self.assertEqual(report["release_qualification"], "not_established")
        self.assertEqual(report["tests"]["measured_release"]["status"], "pass")
        self.assertEqual(report["tests"]["record_while_ai_busy"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
