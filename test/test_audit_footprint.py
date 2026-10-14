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


if __name__ == "__main__":
    unittest.main()
