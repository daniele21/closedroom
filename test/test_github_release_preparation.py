from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "prepare_github_release.py"
spec = importlib.util.spec_from_file_location("prepare_github_release", SCRIPT)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


NOTES = """## Highlights

- Local-first meeting intelligence.

## Compatibility

- Apple Silicon Mac running macOS 14 or later.

## Installation

- Open the DMG and install ClosedRoom.

## Privacy

- Meeting data stays on-device by default.

## Known limitations

- ClosedRoom remains pre-1.0 software.
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GitHubReleasePreparationTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, str, bytes]:
        version = "1.2.3"
        tag = f"v{version}"
        revision = "a" * 40
        build_id = "release-fixture"
        bundle_id = "com.closedroom.app"
        dmg_bytes = b"qualified-dmg-bytes"
        dmg_name = f"ClosedRoom-{version}-{build_id}-{revision[:12]}.dmg"
        dmg_sha = sha256(dmg_bytes)

        (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        notes = root / "notes.md"
        notes.write_text(NOTES, encoding="utf-8")
        artifact = root / "artifact"
        artifact.mkdir()
        (artifact / dmg_name).write_bytes(dmg_bytes)
        (artifact / release.BUILD_CHANGELOG_NAME).write_text(
            "# Build changelog\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "status": "successful",
            "product": "ClosedRoom",
            "product_version": version,
            "build_id": build_id,
            "lineage": {
                "platform": "macos",
                "architecture": "arm64",
                "channel": "release",
                "variant": "package",
            },
            "source": {"revision": revision, "dirty": False},
            "configuration": {
                "bundle_id": bundle_id,
                "signing": "developer-id-notarized",
            },
            "artifacts": {
                "dmg": {
                    "path": dmg_name,
                    "sha256": dmg_sha,
                    "bytes": len(dmg_bytes),
                }
            },
        }
        (artifact / release.MANIFEST_NAME).write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        evidence = {
            "schema_version": 1,
            "status": "pass",
            "source_revision": revision,
            "build_id": build_id,
            "bundle_id": bundle_id,
            "signing": "developer-id",
            "secure_timestamp": True,
            "app_notarization": "accepted",
            "app_stapler_validation": "pass",
            "app_gatekeeper_assessment": "pass",
            "dmg_notarization": "accepted",
            "dmg_stapler_validation": "pass",
            "dmg_gatekeeper_assessment": "pass",
            "notary_profile_configured": True,
        }
        (artifact / release.PRODUCTION_EVIDENCE_NAME).write_text(
            json.dumps(evidence), encoding="utf-8"
        )
        (artifact / release.INPUT_CHECKSUMS_NAME).write_text(
            f"{dmg_sha}  {dmg_name}\n", encoding="utf-8"
        )
        return artifact, notes, revision, dmg_bytes

    def test_stages_same_dmg_bytes_and_public_release_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, dmg_bytes = self.make_fixture(root)
            output = root / "staged"
            plan = release.stage_release(
                root=root,
                artifact_dir=artifact,
                tag="v1.2.3",
                source_revision=revision,
                notes_source=notes,
                release_state="prerelease",
                output_dir=output,
            )

            public_dmg = output / "assets" / "ClosedRoom-v1.2.3-macos-arm64.dmg"
            self.assertEqual(public_dmg.read_bytes(), dmg_bytes)
            self.assertEqual(plan["tag"], "v1.2.3")
            self.assertEqual(plan["title"], "ClosedRoom v1.2.3")
            self.assertTrue(plan["draft"])
            self.assertTrue(plan["prerelease"])
            self.assertFalse(plan["make_latest"])
            self.assertEqual(
                [asset["name"] for asset in plan["assets"]],
                [
                    "ClosedRoom-v1.2.3-macos-arm64.dmg",
                    "SHA256SUMS",
                    "build-manifest.json",
                    "BUILD_CHANGELOG.md",
                ],
            )
            checksum_text = (output / "assets" / "SHA256SUMS").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                f"{sha256(dmg_bytes)}  ClosedRoom-v1.2.3-macos-arm64.dmg",
                checksum_text,
            )
            self.assertIn("# ClosedRoom v1.2.3", (output / "RELEASE_NOTES.md").read_text(encoding="utf-8"))

    def test_stable_state_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            plan = release.stage_release(
                root=root,
                artifact_dir=artifact,
                tag="v1.2.3",
                source_revision=revision,
                notes_source=notes,
                release_state="stable",
                output_dir=root / "staged",
            )
            self.assertFalse(plan["prerelease"])
            self.assertTrue(plan["make_latest"])

    def test_rejects_tag_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            with self.assertRaisesRegex(ValueError, "does not match"):
                release.stage_release(
                    root=root,
                    artifact_dir=artifact,
                    tag="v1.2.4",
                    source_revision=revision,
                    notes_source=notes,
                    release_state="prerelease",
                    output_dir=root / "staged",
                )

    def test_rejects_unqualified_signing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            manifest_path = artifact / release.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["configuration"]["signing"] = "ad-hoc"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "manifest signing mismatch"):
                release.stage_release(
                    root=root,
                    artifact_dir=artifact,
                    tag="v1.2.3",
                    source_revision=revision,
                    notes_source=notes,
                    release_state="prerelease",
                    output_dir=root / "staged",
                )

    def test_rejects_modified_dmg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            manifest = json.loads(
                (artifact / release.MANIFEST_NAME).read_text(encoding="utf-8")
            )
            dmg = artifact / manifest["artifacts"]["dmg"]["path"]
            dmg.write_bytes(b"modified-after-qualification")
            with self.assertRaisesRegex(RuntimeError, "DMG SHA-256 mismatch"):
                release.stage_release(
                    root=root,
                    artifact_dir=artifact,
                    tag="v1.2.3",
                    source_revision=revision,
                    notes_source=notes,
                    release_state="prerelease",
                    output_dir=root / "staged",
                )

    def test_rejects_incomplete_production_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            evidence_path = artifact / release.PRODUCTION_EVIDENCE_NAME
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["dmg_notarization"] = "invalid"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaisesRegex(
                RuntimeError, "production evidence dmg_notarization mismatch"
            ):
                release.stage_release(
                    root=root,
                    artifact_dir=artifact,
                    tag="v1.2.3",
                    source_revision=revision,
                    notes_source=notes,
                    release_state="prerelease",
                    output_dir=root / "staged",
                )

    def test_requires_complete_user_facing_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, notes, revision, _ = self.make_fixture(root)
            notes.write_text("## Highlights\n\nOnly one section.\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "missing required sections"):
                release.stage_release(
                    root=root,
                    artifact_dir=artifact,
                    tag="v1.2.3",
                    source_revision=revision,
                    notes_source=notes,
                    release_state="prerelease",
                    output_dir=root / "staged",
                )


if __name__ == "__main__":
    unittest.main()
