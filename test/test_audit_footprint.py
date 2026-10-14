"""Focused deterministic footprint audit tests. No macOS, dependencies or private data."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_footprint  # noqa: E402


class FootprintAuditTests(unittest.TestCase):
    def test_repository_audit_uses_commit_snapshot_and_reports_identical_blobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@invalid.local"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            for name in ("frontend/public/logo-light.png", "src/local_asr_server/static/logo-dark.png"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"same-logo")
            media = root / "docs/assets/demo.mov"
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"video-media")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
            (root / "docs/assets/demo.mov").write_bytes(b"changed working tree not counted")
            report = audit_footprint.repository_audit(root)
            self.assertEqual(report["count"], 3)
            self.assertEqual(report["total_bytes"], 2 * len(b"same-logo") + len(b"video-media"))
            self.assertEqual(report["groups"]["documentation_media"]["bytes"], len(b"video-media"))
            self.assertEqual(report["duplicate_blob_groups"][0]["redundant_bytes"], len(b"same-logo"))
            self.assertEqual(len(report["source_revision"]), 40)

    def test_bundle_counts_real_files_and_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "ClosedRoom.app"
            resource = app / "Contents/Resources"
            framework = app / "Contents/Frameworks"
            resource.mkdir(parents=True)
            framework.mkdir(parents=True)
            (resource / "ui.js").write_bytes(b"abc")
            (framework / "lib.dylib").write_bytes(b"12345")
            (resource / "link.js").symlink_to(resource / "ui.js")
            report = audit_footprint.bundle_audit(app)
            self.assertEqual(report["total_bytes"], 8)
            self.assertEqual(report["count"], 2)
            self.assertEqual(report["symlinks_not_followed"], 1)
            self.assertEqual(report["groups"]["Contents/Resources"]["bytes"], 3)
            self.assertNotIn(str(Path(temporary)), json.dumps(report))

    def test_cli_reports_incompatible_comparison_as_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "ClosedRoom.app"
            (app / "Contents").mkdir(parents=True)
            prev = root / "baseline.json"
            prev.write_text(json.dumps({"schema_version": 1, "kind": "repository_tree", "count": 1, "total_bytes": 2}))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(audit_footprint.main(["bundle", "--app", str(app), "--compare", str(prev)]), 2)
                self.assertEqual(audit_footprint.main(["bundle", "--app", str(app)]), 0)

    def test_bundle_breaks_down_real_component_directories_without_guessing_python_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "ClosedRoom.app"
            resources = app / "Contents/Resources"
            frameworks = app / "Contents/Frameworks"
            for folder in (resources / "static/assets", frameworks / "mlx/lib", frameworks / "mlx_whisper"):
                folder.mkdir(parents=True)
            (resources / "static/assets/app.js").write_bytes(b"js" * 10)
            (frameworks / "mlx/lib/libmlx.dylib").write_bytes(b"a" * 40)
            (frameworks / "mlx_whisper/preprocessor.so").write_bytes(b"b" * 25)
            (resources / "base_library.zip").write_bytes(b"z" * 18)
            (app / "Contents/MacOS").mkdir()
            (app / "Contents/MacOS/ClosedRoom").write_bytes(b"embedded-pyz-data")
            # A user meeting artifact outside the .app must never be enumerated.
            (root / "private-meeting-transcript.txt").write_text("a user's local meeting content")
            report = audit_footprint.bundle_audit(app)
            self.assertEqual(report["count"], 5)
            self.assertEqual(report["total_bytes"], 20 + 40 + 25 + 18 + len(b"embedded-pyz-data"))
            self.assertEqual(report["component_groups"]["Contents/Frameworks/mlx"]["bytes"], 40)
            self.assertEqual(report["component_groups"]["Contents/Frameworks/mlx_whisper"]["bytes"], 25)
            self.assertEqual(report["file_roles"]["bundled_web_ui"]["bytes"], 20)
            self.assertEqual(report["file_roles"]["opaque_archives"]["bytes"], 18)
            self.assertEqual(report["unattributed_opaque_archive_bytes"], 18)
            self.assertEqual(sum(v["bytes"] for v in report["file_roles"].values()), report["total_bytes"])
            self.assertNotIn(str(root), json.dumps(report))
            self.assertNotIn("a user's local meeting content", json.dumps(report))
            self.assertEqual(report["artifact_identity"]["status"], "absent")

    def test_finalized_selection_identity_and_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lineage = root / "dist/artifacts/macos-arm64-local"
            def create(build_id, created_at, body):
                folder = lineage / build_id
                app = folder / f"ClosedRoom-{build_id}.app"
                (app / "Contents/Resources").mkdir(parents=True)
                (app / "Contents/Resources/asset.bin").write_bytes(body)
                manifest = {
                    "status": "successful", "created_at": created_at, "build_id": build_id,
                    "product_version": "0.2.0", "source": {"revision": "a" * 40, "dirty": False},
                    "lineage": {"channel": "local"}, "configuration": {"signing": "identified"},
                    "artifacts": {"app": {"path": app.name, "bytes": len(body), "file_count": 1},
                                  "dmg": {"bytes": 15}},
                }
                (folder / "build-manifest.json").write_text(json.dumps(manifest))
                return app, manifest, folder
            older, _, _ = create("one", "2026-10-01T10:00:00+00:00", b"one")
            latest, identity, manifest_dir = create("two", "2026-10-14T10:00:00+00:00", b"newer")
            self.assertEqual(audit_footprint.latest_finalized_app(root), latest)
            report = audit_footprint.bundle_audit(latest)
            self.assertEqual(report["artifact_identity"]["source_revision"], "a" * 40)
            self.assertEqual(report["artifact_identity"]["status"], "size_and_count_match_not_checksum_verified")
            self.assertEqual(report["artifact_identity"]["dmg_bytes_if_present"], 15)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(audit_footprint.main(["bundle", "--latest-finalized", "--root", str(root)]), 0)
            self.assertEqual(json.loads(out.getvalue())["total_bytes"], 5)
            compare = root / "previous.json"
            compare.write_text(json.dumps(audit_footprint.bundle_audit(older)))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(audit_footprint.main([
                    "bundle", "--app", str(latest), "--compare", str(compare)
                ]), 0)
            delta = json.loads(out.getvalue())["comparison"]
            self.assertEqual(delta["delta_bytes"], 2)
            self.assertEqual(delta["component_groups_delta_bytes"]["Contents/Resources/_root_files"], 2)
            self.assertEqual(delta["file_roles_delta_bytes"]["unclassified_bundle_files"], 2)
            identity["artifacts"]["app"]["bytes"] = 2000
            (manifest_dir / "build-manifest.json").write_text(json.dumps(identity))
            with self.assertRaisesRegex(ValueError, "does not match"):
                audit_footprint.bundle_audit(latest)

    def test_finalized_selection_avoids_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "dist/artifacts/mac/bad"
            folder.mkdir(parents=True)
            (folder / "build-manifest.json").write_text(json.dumps({
                "status": "successful", "artifacts": {"app": {"path": "../../Some.app"}}
            }))
            with self.assertRaisesRegex(ValueError, "No finalized"):
                audit_footprint.latest_finalized_app(root)




if __name__ == "__main__":
    unittest.main()
