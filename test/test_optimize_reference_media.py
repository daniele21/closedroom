"""Deterministic tests for documentation media optimization (no app build)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, features

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import optimize_reference_media  # noqa: E402


@unittest.skipUnless(features.check("webp"), "Pillow lacks WebP")
class ReferenceMediaOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        self.media = self.root / "docs/assets"
        self.media.mkdir(parents=True)
        self.original = self.media / "screenshot.png"
        image = Image.new("RGBA", (280, 180), (10, 60, 100, 255))
        for x in range(0, 280, 5):
            for y in range(0, 180, 8):
                image.putpixel((x, y), (x % 256, y % 256, 80, 96))
        image.save(self.original, "PNG")
        self.readme = self.root / "README.md"
        self.readme.write_text("![UI](docs/assets/screenshot.png)\n", encoding="utf-8")
        self.docs = self.root / "docs" / "overview.md"
        self.docs.write_text("![UI](assets/screenshot.png)\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)

    def test_dry_run_preserves_files_and_reports_exact_candidate(self):
        result = optimize_reference_media.optimize(
            self.root, minimum_bytes=1, minimum_percent=0.0
        )
        self.assertGreater(result["total_saved_bytes"], 0)
        self.assertEqual(result["mode"], "dry_run")
        self.assertTrue(self.original.exists())
        self.assertFalse(self.media.joinpath("screenshot.webp").exists())
        self.assertIn("README.md", result["reference_files_changed"])

    def test_apply_rewrites_both_relative_reference_styles_without_pixel_changes(self):
        with Image.open(self.original) as image:
            expected = image.convert("RGBA").tobytes()
        result = optimize_reference_media.optimize(
            self.root, apply=True, minimum_bytes=1, minimum_percent=0.0
        )
        self.assertEqual(len(result["converted"]), 1)
        self.assertFalse(self.original.exists())
        target = self.media / "screenshot.webp"
        with Image.open(target) as image:
            self.assertEqual(image.convert("RGBA").tobytes(), expected)
        self.assertIn("docs/assets/screenshot.webp", self.readme.read_text())
        self.assertIn("assets/screenshot.webp", self.docs.read_text())

    def test_respects_savings_threshold(self):
        original = self.original.read_bytes()
        result = optimize_reference_media.optimize(
            self.root, apply=True, minimum_bytes=10_000_000
        )
        self.assertEqual(result["converted"], [])
        self.assertEqual(self.original.read_bytes(), original)
        self.assertFalse((self.media / "screenshot.webp").exists())


if __name__ == "__main__":
    unittest.main()
