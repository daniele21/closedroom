from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class BundleDietContractTests(unittest.TestCase):
    def test_runtime_brand_assets_have_one_canonical_frontend_source(self) -> None:
        frontend_public = ROOT / "frontend" / "public"
        static = ROOT / "src" / "local_asr_server" / "static"

        self.assertTrue((frontend_public / "logo-dark.png").is_file())
        self.assertTrue((frontend_public / "logo-light.png").is_file())
        self.assertTrue((static / "logo-dark.png").is_file())
        self.assertTrue((static / "logo-light.png").is_file())

        for obsolete in ("favicon.svg", "logo.svg", "logo-dark.svg", "logo-light.svg"):
            self.assertFalse((frontend_public / obsolete).exists())
            self.assertFalse((static / obsolete).exists())
        self.assertFalse((ROOT / "public").exists())

    def test_frontend_and_icon_build_use_png_assets(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        build = (ROOT / "build.sh").read_text(encoding="utf-8")

        self.assertIn('src="/logo-dark.png"', app)
        self.assertIn('src="/logo-light.png"', app)
        self.assertIn('type="image/png" href="/logo-light.png"', html)
        self.assertIn('PNG_SOURCE="$SCRIPT_DIR/frontend/public/logo-dark.png"', build)
        self.assertNotIn("rsvg-convert", build)

    def test_mlx_vlm_hidden_imports_match_closedroom_product_surface(self) -> None:
        spec = (ROOT / "ClosedRoom.spec").read_text(encoding="utf-8")

        self.assertNotIn('collect_submodules("mlx_vlm")', spec)
        self.assertIn('collect_submodules("mlx_vlm.server")', spec)
        self.assertIn('collect_submodules("mlx_vlm.models.qwen3_vl")', spec)
        self.assertIn('collect_submodules("local_llm_server")', spec)


if __name__ == "__main__":
    unittest.main()
