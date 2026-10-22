from __future__ import annotations

import importlib.util
import json
import plistlib
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "finalize_build_artifact.py"
spec = importlib.util.spec_from_file_location("finalize_build_artifact", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class BuildArtifactMetadataTests(unittest.TestCase):
    def test_bundle_build_and_product_versions_are_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            contents = Path(temp) / "ClosedRoom Test.app" / "Contents"
            contents.mkdir(parents=True)
            data = {
                "CFBundleIdentifier": "com.closedroom.app.test",
                "CFBundleShortVersionString": "0.2.0",
                "CFBundleVersion": "42",
            }
            with (contents / "Info.plist").open("wb") as stream:
                plistlib.dump(data, stream)
            self.assertEqual(mod.read_bundle_identity(contents.parent, "0.2.0", "com.closedroom.app.test"), 42)
            with self.assertRaisesRegex(ValueError, "product version"):
                mod.read_bundle_identity(contents.parent, "0.3.0", "com.closedroom.app.test")
            with self.assertRaisesRegex(ValueError, "bundle identifier"):
                mod.read_bundle_identity(contents.parent, "0.2.0", "com.closedroom.app")
            data["CFBundleVersion"] = "0.2.0"
            with (contents / "Info.plist").open("wb") as stream:
                plistlib.dump(data, stream)
            with self.assertRaisesRegex(ValueError, "positive numeric"):
                mod.read_bundle_identity(contents.parent, "0.2.0", "com.closedroom.app.test")

    def test_tree_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            first = mod.fingerprint_tree(root)
            (root / "a.txt").write_text("two", encoding="utf-8")
            second = mod.fingerprint_tree(root)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["file_count"], 1)

    def test_previous_successful_build_uses_latest_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            lineage = Path(tmp)
            for build_id, created_at in (("old", "2026-01-01T00:00:00+00:00"), ("new", "2026-02-01T00:00:00+00:00")):
                directory = lineage / build_id
                directory.mkdir()
                (directory / mod.MANIFEST_NAME).write_text(
                    json.dumps({"status": "successful", "build_id": build_id, "created_at": created_at}),
                    encoding="utf-8",
                )
            current = lineage / "current"
            current.mkdir()
            previous = mod.load_previous(lineage, current)
            self.assertEqual(previous["build_id"], "new")

    def test_retention_keeps_newest_successful_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            lineage = Path(tmp)
            dirs = []
            for index in range(3):
                directory = lineage / f"b{index}"
                directory.mkdir()
                dirs.append(directory)
                (directory / mod.MANIFEST_NAME).write_text(
                    json.dumps({
                        "status": "successful",
                        "build_id": f"b{index}",
                        "created_at": f"2026-01-0{index + 1}T00:00:00+00:00",
                    }),
                    encoding="utf-8",
                )
            removed = mod.enforce_retention(lineage, dirs[-1], 2)
            self.assertEqual(removed, ["b0"])
            self.assertFalse(dirs[0].exists())
            self.assertTrue(dirs[1].exists())
            self.assertTrue(dirs[2].exists())


if __name__ == "__main__":
    unittest.main()
