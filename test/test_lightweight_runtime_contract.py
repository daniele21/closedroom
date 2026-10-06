from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class LightweightRuntimeContractTests(unittest.TestCase):
    def test_frontend_does_not_fetch_remote_fonts(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "src" / "index.css").read_text(encoding="utf-8")

        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)
        self.assertNotIn("Outfit", css)
        self.assertNotIn("JetBrains Mono", css)
        self.assertIn("-apple-system", css)
        self.assertIn("SFMono-Regular", css)

    def test_heavy_frontend_pages_are_loaded_on_demand(self) -> None:
        source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("lazy(() => import('./pages/MeetingDetailPage'))", source)
        self.assertIn("lazy(() => import('./pages/RecordingPage'))", source)
        self.assertIn("lazy(() => import('./pages/TranscriptionPage'))", source)
        self.assertIn("lazy(() => import('./pages/ProjectsPage'))", source)
        self.assertIn("lazy(() => import('./pages/AnalysisPage'))", source)
        self.assertIn("lazy(() => import('./pages/SettingsPage'))", source)
        self.assertIn("<Suspense", source)

    def test_health_polling_is_slow_but_refreshes_on_user_return(self) -> None:
        config = (ROOT / "frontend" / "src" / "api" / "config.ts").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("HEALTH_CHECK_INTERVAL_MS = 60000", config)
        self.assertIn("window.addEventListener('focus', refreshWhenVisible)", source)
        self.assertIn("document.addEventListener('visibilitychange', refreshWhenVisible)", source)

    def test_menu_bar_uses_only_the_decorated_status_timer(self) -> None:
        source = (ROOT / "src" / "local_asr_server" / "menubar.py").read_text(encoding="utf-8")

        self.assertIn("@rumps.timer(5)", source)
        self.assertNotIn("self._status_timer = rumps.Timer", source)

    def test_frozen_main_process_does_not_preload_mlx(self) -> None:
        hook = (ROOT / "build_assets" / "hooks" / "pyi_rth_mlx.py").read_text(encoding="utf-8")
        menubar = (ROOT / "src" / "local_asr_server" / "menubar.py").read_text(encoding="utf-8")

        self.assertIn("def _needs_mlx_preload", hook)
        self.assertIn('args[0] == "transcribe"', hook)
        self.assertIn('"local_asr_server.runtime.local_llm_entrypoint"', hook)
        self.assertIn("_needs_mlx_preload(sys.argv)", hook)
        self.assertNotIn('ctypes.CDLL(str(_libmlx_path))', menubar)

    def test_obsolete_static_backups_are_not_tracked(self) -> None:
        self.assertFalse((ROOT / "src" / "local_asr_server" / "static_vanilla_backup").exists())
        self.assertFalse((ROOT / "frontend" / "public" / "logo-dark.old.svg").exists())
        self.assertFalse((ROOT / "frontend" / "public" / "logo-light.old.svg").exists())


if __name__ == "__main__":
    unittest.main()
