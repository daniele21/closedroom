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

    def test_media_is_isolated_per_child_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            measured = self.runner.media_directory(parent / "ui-target-mac-report.json")
            contention = self.runner.media_directory(parent / "contention-seed-ui-report.json")
            self.assertNotEqual(measured, contention)
            self.assertEqual(measured.name, "meeting-recording-ui")
            self.assertEqual(contention.name, "meeting-recording-ui")
            self.assertEqual(measured.parent.name, "ui-target-mac-report")
            self.assertEqual(contention.parent.name, "contention-seed-ui-report")

    def test_known_executable_never_falls_back_to_another_closedroom(self) -> None:
        wanted = "/Applications/ClosedRoom Test-id.app/Contents/MacOS/ClosedRoom"
        running = [
            (101, "/Applications/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
            (102, "/Applications/ClosedRoom Test-other.app/Contents/MacOS/ClosedRoom"),
            (103, wanted + "-spurious"),
        ]
        with mock.patch.object(self.runner, "process_snapshot", return_value=running):
            self.assertIsNone(self.runner.find_closedroom_pid(expected_executable=wanted))
        running.append((104, wanted))
        with mock.patch.object(self.runner, "process_snapshot", return_value=running):
            self.assertEqual(self.runner.find_closedroom_pid(expected_executable=wanted), 104)

    def test_video_duration_is_bounded_and_covers_normal_smoke(self) -> None:
        self.assertEqual(self.runner.video_duration(8), 90)
        self.assertEqual(self.runner.video_duration(20), 90)
        self.assertEqual(self.runner.video_duration(150), 180)

    def test_screencapture_uses_natural_duration_not_sigint_for_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            movie = Path(tmp) / "journey.mov"
            with mock.patch.object(self.runner.subprocess, "Popen") as popen:
                self.runner.start_video("0,0,640,480", movie, 90)
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[:5], ["screencapture", "-v", "-V", "90", "-R"])
            self.assertEqual(cmd[-1], str(movie))
            self.assertIn("0,0,640,480", cmd)

    def test_video_requires_natural_success_and_full_journey(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            movie = Path(tmp) / "journey.mov"
            self.assertFalse(self.runner.video_passes(0, movie, True))
            movie.write_bytes(b"sample")
            self.assertFalse(self.runner.video_passes(-2, movie, True))
            self.assertFalse(self.runner.video_passes(0, movie, False))
            self.assertTrue(self.runner.video_passes(0, movie, True))

    def test_video_cleanup_does_not_interrupt_completed_recorder(self) -> None:
        finished = mock.Mock()
        finished.poll.return_value = 0
        self.assertFalse(self.runner.abort_unfinished_video(finished))
        finished.terminate.assert_not_called()
        finished.send_signal.assert_not_called()

        ongoing = mock.Mock()
        ongoing.poll.return_value = None
        self.assertTrue(self.runner.abort_unfinished_video(ongoing))
        ongoing.terminate.assert_called_once()
        ongoing.send_signal.assert_not_called()

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
