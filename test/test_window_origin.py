from __future__ import annotations

import sys
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "darwin", "WKWebView/AppKit require macOS")
class NativeWindowRoutingTests(unittest.TestCase):
    def test_local_server_failure_replaces_loading_view_with_accessible_recovery(self):
        from local_asr_server.window import ClosedRoomWindowManager

        manager = ClosedRoomWindowManager("http://127.0.0.1:1236")
        manager.webview = Mock()
        manager.show_startup_error()
        manager.webview.loadHTMLString_baseURL_.assert_called_once()
        html = manager.webview.loadHTMLString_baseURL_.call_args.args[0]
        self.assertIn('role="alert"', html)
        self.assertIn("Impossibile avviare ClosedRoom", html)
        self.assertIn("chiudi ClosedRoom", html)
        self.assertNotIn("Avvio del server di trascrizione locale in corso", html)

    def test_notification_navigation_never_changes_overlay_origin(self):
        from local_asr_server.window import ClosedRoomWindowManager

        origin = "http://127.0.0.1:1236"
        manager = ClosedRoomWindowManager(origin)
        manager.webview = Mock()
        route = origin + "/#recording/auto/example-once-token"
        with patch("local_asr_server.window.NSURL") as url, patch("local_asr_server.window.NSURLRequest") as request:
            url.URLWithString_.return_value = Mock()
            request.requestWithURL_.return_value = Mock()
            manager.load_url(route)
            url.URLWithString_.assert_called_once_with(route)
            manager.webview.loadRequest_.assert_called_once_with(request.requestWithURL_.return_value)
        self.assertEqual(manager.url, origin)
        self.assertEqual(manager.url + "/#overlay", origin + "/#overlay")


if __name__ == "__main__":
    unittest.main()
