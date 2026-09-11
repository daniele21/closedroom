from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "real_environment_ui_evidence.py"
SCRIPTS_DIR = SCRIPT.parent


def load_module():
    spec = importlib.util.spec_from_file_location("real_environment_ui_evidence", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load real_environment_ui_evidence.py")
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


class RealEnvironmentUIEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_module()

    def _write_artifact(
        self,
        root: Path,
        build_id: str,
        *,
        revision: str,
        dirty: bool = False,
        created_at: str = "2026-09-04T13:00:00+00:00",
    ) -> tuple[Path, Path]:
        directory = root / "dist" / "artifacts" / "macos-arm64-local-app" / build_id
        app = directory / f"ClosedRoom-0.1.0-{build_id}-{revision}.app"
        app.mkdir(parents=True)
        manifest = directory / "build-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "status": "successful",
                    "created_at": created_at,
                    "source": {"revision": revision, "dirty": dirty},
                    "artifacts": {"app": {"path": app.name}},
                }
            ),
            encoding="utf-8",
        )
        return app, manifest

    def test_exact_artifact_uses_nested_manifest_source_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected_app, expected_manifest = self._write_artifact(
                root,
                "exact-old",
                revision="7b95d718a35e",
                created_at="2026-09-04T13:00:00+00:00",
            )
            self._write_artifact(
                root,
                "wrong-newer",
                revision="ffffffffffff",
                created_at="2026-09-04T14:00:00+00:00",
            )
            self._write_artifact(
                root,
                "dirty-newest",
                revision="7b95d718a35e",
                dirty=True,
                created_at="2026-09-04T15:00:00+00:00",
            )
            self.assertEqual(
                self.runner.exact_finalized_app(root, "7b95d718a35e"),
                (expected_app, expected_manifest),
            )

    def test_prepare_reuses_exact_artifact_without_rebuilding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected_app, expected_manifest = self._write_artifact(
                root,
                "exact",
                revision="7b95d718a35e",
            )
            with mock.patch.object(self.runner.subprocess, "run") as run_mock:
                app, manifest, selection = self.runner.prepare_exact_app(root, "7b95d718a35e")
            self.assertEqual((app, manifest), (expected_app, expected_manifest))
            self.assertEqual(selection, "reused_exact")
            run_mock.assert_not_called()

    def test_build_path_restores_only_generated_frontend_and_rechecks_cleanliness(self) -> None:
        root = Path("/tmp/closedroom-repo")
        app = root / "dist" / "artifacts" / "lineage" / "build" / "ClosedRoom.app"
        manifest = app.parent / "build-manifest.json"
        with (
            mock.patch.object(
                self.runner,
                "exact_finalized_app",
                side_effect=[None, (app, manifest)],
            ),
            mock.patch.object(
                self.runner,
                "git_state",
                side_effect=[("7b95d718a35e", []), ("7b95d718a35e", [])],
            ),
            mock.patch.object(self.runner.subprocess, "run") as run_mock,
        ):
            selected_app, selected_manifest, selection = self.runner.prepare_exact_app(
                root,
                "7b95d718a35e",
            )

        self.assertEqual((selected_app, selected_manifest, selection), (app, manifest, "built_exact"))
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(commands[0], ["bash", "scripts/build_artifact.sh", "--no-dmg"])
        self.assertEqual(
            commands[1],
            [
                "git",
                "restore",
                "--source=HEAD",
                "--staged",
                "--worktree",
                "--",
                "src/local_asr_server/static",
            ],
        )
        self.assertEqual(
            commands[2],
            ["git", "clean", "-fd", "--", "src/local_asr_server/static"],
        )

    def test_find_closedroom_pid_prefers_exact_new_smoke_process(self) -> None:
        expected = "/tmp/build/ClosedRoom.app/Contents/MacOS/ClosedRoom"
        snapshot = [
            (100, "/old/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
            (200, f"{expected}"),
            (300, "/other/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
        ]
        with mock.patch.object(self.runner, "process_snapshot", return_value=snapshot):
            self.assertEqual(
                self.runner.find_closedroom_pid(expected_executable=expected, excluded={100}),
                200,
            )

    def test_find_closedroom_pid_excludes_processes_present_before_smoke(self) -> None:
        snapshot = [
            (100, "/old/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
            (250, "/new/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
        ]
        with mock.patch.object(self.runner, "process_snapshot", return_value=snapshot):
            self.assertEqual(self.runner.find_closedroom_pid(excluded={100}), 250)
            self.assertIsNone(self.runner.find_closedroom_pid(excluded={100, 250}))


if __name__ == "__main__":
    unittest.main()
