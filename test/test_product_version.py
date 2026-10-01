from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "product_version.py"
spec = importlib.util.spec_from_file_location("product_version", SCRIPT)
assert spec and spec.loader
product_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(product_version)


class ProductVersionTests(unittest.TestCase):
    def test_repository_version_is_valid_semver(self) -> None:
        version = product_version.read_product_version(ROOT)
        self.assertEqual(product_version.validate_version(version), version)

    def test_product_build_paths_use_canonical_version_owner(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        spec_source = (ROOT / "ClosedRoom.spec").read_text(encoding="utf-8")
        artifact = (ROOT / "scripts" / "build_artifact.sh").read_text(encoding="utf-8")
        production = (ROOT / "scripts" / "build_production_artifact.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('scripts/product_version.py', build)
        self.assertIn('from product_version import read_product_version', spec_source)
        self.assertIn('scripts/product_version.py', artifact)
        self.assertIn('from product_version import read_product_version', production)

        for source in (build, spec_source, artifact, production):
            self.assertNotIn('["project"]["version"]', source)
            self.assertNotIn("['project']['version']", source)

    def test_tag_round_trip_uses_repository_version(self) -> None:
        version = product_version.read_product_version(ROOT)
        tag = product_version.tag_for_version(version)
        self.assertEqual(product_version.version_from_tag(tag), version)

    def test_invalid_or_ambiguous_versions_fail(self) -> None:
        for value in ("0.2", "v0.2.0", "0.02.0", "0.2.0-beta.1", "1.0.0+build"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    product_version.validate_version(value)

    def test_release_tag_must_match_canonical_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("9.8.7\n", encoding="utf-8")
            self.assertEqual(
                product_version.assert_tag_matches_product(root, "v9.8.7"),
                "9.8.7",
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                product_version.assert_tag_matches_product(root, "v9.8.8")

    def test_missing_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "canonical product version missing"):
                product_version.read_product_version(Path(tmp))


if __name__ == "__main__":
    unittest.main()
