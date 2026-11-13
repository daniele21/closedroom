from __future__ import annotations

import argparse
import importlib.util
import json
import plistlib
import shutil
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

    def test_installs_verified_copy_without_overwriting_other_apps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifact"
            source_app = artifact_dir / "ClosedRoom-source.app"
            (source_app / "Contents" / "MacOS").mkdir(parents=True)
            (source_app / "Contents" / "MacOS" / "ClosedRoom").write_bytes(b"app")
            manifest_path = write_manifest(artifact_dir, source_app)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["build_id"] = "local-verified"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source_app))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            applications = root / "Applications"
            applications.mkdir()
            normal_app = applications / "ClosedRoom.app"
            normal_app.mkdir()
            (normal_app / "keep.txt").write_text("untouched", encoding="utf-8")

            original_run = subprocess.run
            def simulate_install(command: list[str], **kwargs: object):
                if command[0] == "ditto":
                    shutil.copytree(command[1], command[2], symlinks=True)
                    return subprocess.CompletedProcess(command, 0)
                if command[0] == "codesign":
                    return subprocess.CompletedProcess(command, 0)
                return original_run(command, **kwargs)

            with patch.object(policy.subprocess, "run", side_effect=simulate_install):
                installed, status = policy.install_test_app(
                    source_app, manifest, applications_dir=applications
                )
                reused, reused_status = policy.install_test_app(
                    source_app, manifest, applications_dir=applications
                )

            self.assertEqual(status, "installed_verified")
            self.assertEqual(reused_status, "reused_verified")
            self.assertEqual(installed, reused)
            self.assertTrue(installed.name.startswith("ClosedRoom Test-"))
            self.assertEqual((normal_app / "keep.txt").read_text(), "untouched")
            self.assertEqual(
                (installed / "Contents" / "MacOS" / "ClosedRoom").read_bytes(), b"app"
            )
            self.assertEqual(
                (source_app / "Contents" / "MacOS" / "ClosedRoom").read_bytes(), b"app"
            )

            (installed / "Contents" / "MacOS" / "ClosedRoom").write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "differs"):
                policy.install_test_app(source_app, manifest, applications_dir=applications)
            self.assertEqual((normal_app / "keep.txt").read_text(), "untouched")

    def test_installed_override_requires_exact_verified_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_app = root / "artifact" / "ClosedRoom-source.app"
            source_app.mkdir(parents=True)
            (source_app / "data").write_text("original", encoding="utf-8")
            manifest_path = write_manifest(source_app.parent, source_app)
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source_app))
            manifest_path.write_text(json.dumps(manifest))
            installed_app = root / "Applications" / "ClosedRoom Test.app"
            shutil.copytree(source_app, installed_app)
            env = {
                policy.INSTALLED_APP_ENV: str(installed_app),
                policy.SOURCE_APP_ENV: str(source_app),
            }
            with patch.dict(policy.os.environ, env):
                actual_manifest, _ = policy.local_manifest_for(installed_app)
                self.assertEqual(actual_manifest, manifest_path)
                (installed_app / "data").write_text("modified", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    policy.local_manifest_for(installed_app)

    def test_install_main_app_requires_identified_artifact_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "artifact"
            source_app = folder / "ClosedRoom-source.app"
            (source_app / "Contents").mkdir(parents=True)
            with (source_app / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, stream)
            (source_app / "Contents" / "payload").write_bytes(b"original")
            manifest_path = write_manifest(folder, source_app, signing="identified")
            manifest = json.loads(manifest_path.read_text())
            manifest["configuration"]["bundle_id"] = "com.closedroom.app"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source_app))
            manifest_path.write_text(json.dumps(manifest))
            apps = root / "Applications"
            apps.mkdir()

            original_run = subprocess.run
            def simulate_install(command: list[str], **kwargs: object):
                if command[0] == "ditto":
                    shutil.copytree(command[1], command[2], symlinks=True)
                elif command[0] != "codesign":
                    return original_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(policy.subprocess, "run", side_effect=simulate_install):
                installed = policy.install_main_app(source_app, manifest, applications_dir=apps)
                self.assertEqual(installed, apps / "ClosedRoom.app")
                self.assertEqual((installed / "Contents" / "payload").read_bytes(), b"original")
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    policy.install_main_app(source_app, manifest, applications_dir=apps)
                self.assertEqual((installed / "Contents" / "payload").read_bytes(), b"original")

                installed.rename(apps / "moved.app")
                (apps / "ClosedRoom.app").symlink_to(apps / "moved.app")
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    policy.install_main_app(source_app, manifest, applications_dir=apps)

            (apps / "ClosedRoom.app").unlink()
            with self.assertRaisesRegex(RuntimeError, "identified"):
                wrong = dict(manifest, configuration={"signing": "ad-hoc", "bundle_id": "com.closedroom.app"})
                policy.install_main_app(source_app, wrong, applications_dir=apps)
            self.assertFalse((apps / "ClosedRoom.app").exists())

    def test_upgrade_main_app_preserves_backup_and_current_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_app = root / "Applications" / "ClosedRoom.app"
            (original_app / "Contents").mkdir(parents=True)
            with (original_app / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, stream)
            (original_app / "Contents" / "payload").write_bytes(b"old-version")
            source = root / "artifact" / "ClosedRoom-new.app"
            shutil.copytree(original_app, source)
            (source / "Contents" / "payload").write_bytes(b"new-version")
            manifest_path = write_manifest(source.parent, source, signing="identified")
            manifest = json.loads(manifest_path.read_text())
            manifest["configuration"]["bundle_id"] = "com.closedroom.app"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source))
            manifest_path.write_text(json.dumps(manifest))
            real_run = subprocess.run

            def run_copy(command: list[str], **kwargs: object):
                if command[0] == "ditto":
                    shutil.copytree(command[1], command[2], symlinks=True)
                elif command[0] == "codesign" and "-dv" in command:
                    return subprocess.CompletedProcess(
                        command, 0, "", "Authority=ClosedRoom Local Development\\nTeamIdentifier=not set\\n"
                    )
                elif command[0] not in ("codesign", "ps"):
                    return real_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(policy.subprocess, "run", side_effect=run_copy),
                patch.object(policy, "main_app_running", return_value=False),
            ):
                installed, backup = policy.upgrade_main_app(
                    source, manifest, applications_dir=root / "Applications"
                )
            self.assertEqual(installed, original_app)
            self.assertEqual((installed / "Contents" / "payload").read_bytes(), b"new-version")
            self.assertEqual((backup / "Contents" / "payload").read_bytes(), b"old-version")
            self.assertTrue(backup.name.startswith(".ClosedRoom-backup-"))
            self.assertEqual((source / "Contents" / "payload").read_bytes(), b"new-version")

    def test_upgrade_main_app_restores_original_if_publish_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_app = root / "Applications" / "ClosedRoom.app"
            (original_app / "Contents").mkdir(parents=True)
            with (original_app / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, stream)
            (original_app / "Contents" / "payload").write_bytes(b"old-version")
            source = root / "artifact" / "ClosedRoom-new.app"
            shutil.copytree(original_app, source)
            (source / "Contents" / "payload").write_bytes(b"new-version")
            manifest_path = write_manifest(source.parent, source, signing="identified")
            manifest = json.loads(manifest_path.read_text())
            manifest["configuration"]["bundle_id"] = "com.closedroom.app"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source))
            manifest_path.write_text(json.dumps(manifest))
            real_run = subprocess.run
            real_rename = Path.rename

            def run_copy(command: list[str], **kwargs: object):
                if command[0] == "ditto":
                    shutil.copytree(command[1], command[2], symlinks=True)
                elif command[0] == "codesign" and "-dv" in command:
                    return subprocess.CompletedProcess(command, 0, "", "Authority=ClosedRoom Local Development\\n")
                elif command[0] not in ("codesign", "ps"):
                    return real_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            def fail_publishing(path: Path, destination: Path):
                if str(path).endswith("/.ClosedRoom-upgrade-staging") or (
                    path.parent.name.startswith(".ClosedRoom-upgrade-staging-")
                    and destination == original_app
                ):
                    raise OSError("injected app publish failure")
                return real_rename(path, destination)

            with (
                patch.object(policy.subprocess, "run", side_effect=run_copy),
                patch.object(policy, "main_app_running", return_value=False),
                patch.object(Path, "rename", fail_publishing),
            ):
                with self.assertRaisesRegex(OSError, "injected app publish failure"):
                    policy.upgrade_main_app(source, manifest, applications_dir=root / "Applications")

            self.assertEqual((original_app / "Contents" / "payload").read_bytes(), b"old-version")
            self.assertFalse(list((root / "Applications").glob(".ClosedRoom-backup-*.app")))

    def test_upgrade_main_app_fails_closed_on_certificate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "Applications" / "ClosedRoom.app"
            (old / "Contents").mkdir(parents=True)
            with (old / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, stream)
            (old / "Contents" / "payload").write_bytes(b"old")
            source = root / "artifact" / "ClosedRoom-new.app"
            shutil.copytree(old, source)
            (source / "Contents" / "payload").write_bytes(b"new")
            mp = write_manifest(source.parent, source, signing="identified")
            manifest = json.loads(mp.read_text())
            manifest["configuration"]["bundle_id"] = "com.closedroom.app"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source))
            mp.write_text(json.dumps(manifest))
            authorities = iter([("Old Signer",), ("New Signer",)])
            real_run = subprocess.run

            def run_copy(command: list[str], **kwargs: object):
                if command[0] == "ditto":
                    shutil.copytree(command[1], command[2], symlinks=True)
                elif command[0] not in ("codesign", "ps"):
                    return real_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(policy.subprocess, "run", side_effect=run_copy),
                patch.object(policy, "main_app_running", return_value=False),
                patch.object(policy, "signing_authorities", side_effect=lambda _: next(authorities)),
            ):
                with self.assertRaisesRegex(RuntimeError, "signing authority differs"):
                    policy.upgrade_main_app(source, manifest, applications_dir=root / "Applications")
            self.assertEqual((old / "Contents" / "payload").read_bytes(), b"old")
            self.assertFalse(list((root / "Applications").glob(".ClosedRoom-backup-*.app")))

    def test_main_installed_matching_artifact_is_read_only_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "dist" / "artifacts" / "lineage" / "build"
            source = folder / "ClosedRoom-build.app"
            (source / "Contents").mkdir(parents=True)
            with (source / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, stream)
            (source / "Contents" / "binary").write_bytes(b"original")
            manifest_path = write_manifest(folder, source, revision="abc123", signing="identified")
            manifest = json.loads(manifest_path.read_text())
            manifest["configuration"]["bundle_id"] = "com.closedroom.app"
            manifest["artifacts"]["app"].update(policy.fingerprint_tree(source))
            manifest_path.write_text(json.dumps(manifest))
            installed = root / "Applications" / "ClosedRoom.app"
            shutil.copytree(source, installed)
            with patch.object(policy.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                found, artifact, reference, verified = policy.installed_main_artifact(
                    root, "abc123", installed_app=installed
                )
                self.assertEqual((found, artifact, reference), (installed, source, manifest_path))
                self.assertEqual(verified["configuration"]["signing"], "identified")
                (installed / "Contents" / "binary").write_bytes(b"tampered")
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    policy.installed_main_artifact(root, "abc123", installed_app=installed)
            self.assertEqual((source / "Contents" / "binary").read_bytes(), b"original")

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

    def test_install_main_mode_bootstraps_missing_app_then_waits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "artifact" / "ClosedRoom-build.app"
            source.mkdir(parents=True)
            manifest_path = write_manifest(source.parent, source, revision="abc123", signing="identified")
            manifest = json.loads(manifest_path.read_text())
            installed = Path("/Applications/ClosedRoom.app")
            report_path = root / "summary.json"
            commands = []
            def fake_run(cmd: list[str], **kwargs: object):
                commands.append(cmd)
                child_path = Path(cmd[cmd.index("--output") + 1])
                child_path.parent.mkdir(parents=True, exist_ok=True)
                child_path.write_text(json.dumps({"status": "pass", "checks": [], "errors": []}))
                return subprocess.CompletedProcess(cmd, 0)

            original_exists = Path.exists
            def fake_exists(path):
                if str(path) == str(installed):
                    return False
                return original_exists(path)

            with (
                patch.object(sys, "argv", ["suite", "--root", str(root), "--output", str(report_path), "--install-main-app"]),
                patch.object(suite.platform, "system", return_value="Darwin"),
                patch.object(suite.platform, "machine", return_value="arm64"),
                patch.object(suite.sys.stdin, "isatty", return_value=True),
                patch.object(suite, "required_tools_missing", return_value=[]),
                patch.object(suite.measured, "git_state", return_value=("abc123", [])),
                patch.object(suite, "build_identified_main_artifact", return_value=source) as build,
                patch.object(suite.local_policy, "local_manifest_for", return_value=(manifest_path, manifest)),
                patch.object(suite.local_policy, "install_main_app", return_value=installed) as install,
                patch.object(suite.local_policy, "installed_main_artifact", return_value=(installed, source, manifest_path, manifest)),
                patch.object(suite.local_policy, "verify_installed_copy"),
                patch.object(suite, "permission_checkpoint") as checkpoint,
                patch.object(suite.subprocess, "run", side_effect=fake_run),
                patch.object(Path, "exists", fake_exists),
            ):
                status = suite.main()
            self.assertEqual(status, 0)
            build.assert_called_once()
            install.assert_called_once()
            checkpoint.assert_called_once_with(installed)
            self.assertEqual(len(commands), 2)
            payload = json.loads(report_path.read_text())
            self.assertEqual(payload["installation_status"], "installed_new_main")

    def test_upgrade_main_mode_builds_verified_candidate_then_checks_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "artifact" / "ClosedRoom-new.app"
            source.mkdir(parents=True)
            manifest_path = write_manifest(source.parent, source, revision="abc123", signing="identified")
            manifest = json.loads(manifest_path.read_text())
            installed = Path("/Applications/ClosedRoom.app")
            backup = Path("/Applications/.ClosedRoom-backup-fake.app")
            report_path = root / "summary.json"
            commands = []

            def fake_run(cmd: list[str], **kwargs: object):
                commands.append(cmd)
                child = Path(cmd[cmd.index("--output") + 1])
                child.parent.mkdir(parents=True, exist_ok=True)
                child.write_text(json.dumps({"status": "pass", "checks": [], "errors": []}))
                return subprocess.CompletedProcess(cmd, 0)

            with (
                patch.object(sys, "argv", ["suite", "--root", str(root), "--output", str(report_path), "--upgrade-main-app"]),
                patch.object(suite.platform, "system", return_value="Darwin"),
                patch.object(suite.platform, "machine", return_value="arm64"),
                patch.object(suite.sys.stdin, "isatty", return_value=True),
                patch.object(suite, "required_tools_missing", return_value=[]),
                patch.object(suite.measured, "git_state", return_value=("abc123", [])),
                patch.object(suite, "build_identified_main_artifact", return_value=source) as build,
                patch.object(suite.local_policy, "local_manifest_for", return_value=(manifest_path, manifest)),
                patch.object(suite.local_policy, "upgrade_main_app", return_value=(installed, backup)) as upgrade,
                patch.object(suite.local_policy, "installed_main_artifact", return_value=(installed, source, manifest_path, manifest)),
                patch.object(suite.local_policy, "verify_installed_copy"),
                patch.object(suite, "permission_checkpoint") as checkpoint,
                patch.object(suite.subprocess, "run", side_effect=fake_run),
                patch.object(Path, "is_dir", lambda path: str(path) == str(installed) or path == root or (path.exists() and not path.is_symlink())),
            ):
                result = suite.main()
            self.assertEqual(result, 0)
            self.assertEqual(len(commands), 2)
            build.assert_called_once()
            upgrade.assert_called_once()
            checkpoint.assert_called_once_with(installed)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["installation_status"], "upgraded_main_verified")
            self.assertEqual(report["previous_app_backup"], str(backup))

    def test_install_main_mode_requires_stable_signing_identity(self) -> None:
        with patch.dict(suite.os.environ, {"CLOSEDROOM_SIGN_IDENTITY": ""}):
            with self.assertRaisesRegex(RuntimeError, "CLOSEDROOM_SIGN_IDENTITY"):
                suite.build_identified_main_artifact(Path("/repo"), "abc123")

    def test_main_app_suite_waits_and_uses_existing_exact_installed_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "artifact" / "ClosedRoom-build.app"
            source.mkdir(parents=True)
            manifest_path = write_manifest(source.parent, source, revision="abc123", signing="identified")
            manifest = json.loads(manifest_path.read_text())
            installed = root / "Applications" / "ClosedRoom.app"
            output = root / "summary.json"
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **kwargs: object):
                report_path = Path(cmd[cmd.index("--output") + 1])
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps({"status": "pass", "checks": [], "errors": []}))
                env = kwargs["env"]
                self.assertEqual(env[policy.MAIN_APP_ENV], "1")
                self.assertEqual(env[policy.SOURCE_APP_ENV], str(source))
                self.assertEqual(env[policy.INSTALLED_APP_ENV], str(installed))
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)

            with (
                patch.object(sys, "argv", ["suite", "--root", str(root), "--output", str(output), "--use-installed-app"]),
                patch.object(suite.platform, "system", return_value="Darwin"),
                patch.object(suite.platform, "machine", return_value="arm64"),
                patch.object(suite.sys.stdin, "isatty", return_value=True),
                patch.object(suite, "required_tools_missing", return_value=[]),
                patch.object(suite.measured, "git_state", return_value=("abc123", [])),
                patch.object(suite.local_policy, "installed_main_artifact", return_value=(installed, source, manifest_path, manifest)),
                patch.object(suite.local_policy, "verify_installed_copy"),
                patch.object(suite, "select_local_artifact", side_effect=AssertionError("must not build")),
                patch.object(suite, "permission_checkpoint") as checkpoint,
                patch.object(suite.subprocess, "run", side_effect=fake_run),
            ):
                result = suite.main()
            self.assertEqual(result, 0)
            checkpoint.assert_called_once_with(installed)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(str(installed) in cmd for cmd in calls))
            report = json.loads(output.read_text())
            self.assertEqual(report["installation_status"], "existing_main_verified")
            self.assertEqual(report["permission_checkpoint"], "acknowledged")

    def test_permission_checkpoint_requires_terminal(self) -> None:
        with patch.object(suite.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "interactive Terminal"):
                suite.permission_checkpoint(Path("/Applications/ClosedRoom.app"))

    def test_installed_suite_passes_same_app_and_original_manifest_to_both_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "artifact" / "ClosedRoom-original.app"
            source.mkdir(parents=True)
            manifest_path = write_manifest(source.parent, source, revision="abc123")
            manifest = json.loads(manifest_path.read_text())
            installed = root / "Applications" / "ClosedRoom Test.app"
            output = root / "local-report.json"
            recorded: list[tuple[list[str], dict[str, str]]] = []

            def fake_run(command: list[str], **kwargs: object):
                child_output = Path(command[command.index("--output") + 1])
                child_output.parent.mkdir(parents=True, exist_ok=True)
                child_output.write_text(json.dumps({"status": "pass", "checks": [], "errors": []}))
                recorded.append((command, kwargs["env"]))
                return subprocess.CompletedProcess(command, 0)

            with (
                patch.object(sys, "argv", ["suite", "--root", str(root), "--output", str(output), "--install-to-applications"]),
                patch.object(suite.platform, "system", return_value="Darwin"),
                patch.object(suite.platform, "machine", return_value="arm64"),
                patch.object(suite, "required_tools_missing", return_value=[]),
                patch.object(suite.measured, "git_state", return_value=("abc123", [])),
                patch.object(suite, "select_local_artifact", return_value=(source, manifest_path, manifest, "reused_exact")),
                patch.object(suite.local_policy, "install_test_app", return_value=(installed, "installed_verified")),
                patch.object(suite.subprocess, "run", side_effect=fake_run),
            ):
                code = suite.main()

            self.assertEqual(code, 0)
            self.assertEqual(len(recorded), 2)
            for command, env in recorded:
                self.assertIn(str(installed), command)
                self.assertEqual(env[policy.SOURCE_APP_ENV], str(source))
                self.assertEqual(env[policy.INSTALLED_APP_ENV], str(installed))
            result = json.loads(output.read_text())
            self.assertEqual(result["app"], str(installed))
            self.assertEqual(result["build_manifest"], str(manifest_path))
            self.assertEqual(result["installation_status"], "installed_verified")

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
