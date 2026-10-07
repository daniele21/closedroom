from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class MacOSShellContractTests(unittest.TestCase):
    def test_menu_bar_uses_native_square_template_icon(self) -> None:
        source = (ROOT / "src" / "local_asr_server" / "menubar.py").read_text(encoding="utf-8")

        self.assertIn("STATUS_ITEM_STATES", source)
        self.assertIn("imageWithSystemSymbolName_accessibilityDescription_", source)
        self.assertIn("image.setTemplate_(True)", source)
        self.assertIn("status_item.setLength_(AppKit.NSSquareStatusItemLength)", source)
        self.assertIn("button.setImage_(image)", source)
        self.assertIn('button.setTitle_("")', source)
        self.assertIn('self._set_status_icon("recording")', source)
        self.assertIn('self._set_status_icon("idle")', source)

    def test_overlay_drag_is_owned_by_native_view_above_webview(self) -> None:
        source = (ROOT / "src" / "local_asr_server" / "window.py").read_text(encoding="utf-8")

        self.assertIn("class DragHandleView(NSView):", source)
        self.assertIn("def mouseDragged_(self, event) -> None:", source)
        self.assertIn("NSEvent.mouseLocation()", source)
        self.assertIn("window.setFrameOrigin_", source)
        self.assertIn("manager._save_overlay_position()", source)
        self.assertIn("self.overlay_container = NSView.alloc().initWithFrame_", source)
        self.assertIn("self.overlay_window.setContentView_(self.overlay_container)", source)
        self.assertIn("self.overlay_container.addSubview_(self.overlay_webview)", source)
        self.assertIn("self.overlay_container.addSubview_(drag_handle)", source)
        self.assertIn("self.overlay_window.setMovableByWindowBackground_(False)", source)

    def test_overlay_exposes_a_visible_drag_affordance(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "RecordingOverlayPage.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn("GripHorizontal", source)
        self.assertIn('data-overlay-drag-region="true"', source)
        self.assertIn('title="Drag to move"', source)

    def test_brand_has_asset_and_render_fallback_contract(self) -> None:
        app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
        smoke = (ROOT / "scripts" / "smoke_packaged_app.py").read_text(encoding="utf-8")

        self.assertIn('src="/logo-dark.png"', app)
        self.assertIn('src="/logo-light.png"', app)
        self.assertIn("onError={() => setBrandLogoFailed(true)}", app)
        self.assertIn('data-brand-logo-fallback="true"', app)
        self.assertIn(".brand-logo-fallback", css)
        self.assertIn("probe_image_asset", smoke)
        self.assertIn('"brand_asset_loaded": brand_asset_loaded', smoke)


if __name__ == "__main__":
    unittest.main()
