from __future__ import annotations

from types import SimpleNamespace
import unittest
import sys
from unittest.mock import Mock, patch

if sys.platform == 'darwin':
    from local_asr_server.menubar import ClosedRoomApp


@unittest.skipUnless(sys.platform == 'darwin', 'requires the macOS app shell')
class MenuBarRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(ClosedRoomApp)
        self.old = Mock()
        self.replacement = Mock()
        self.bar = Mock()
        self.bar.statusItemWithLength_.return_value = self.replacement
        self.app._nsapp = SimpleNamespace(nsstatusitem=self.old)
        self.app._status_item_ready = True
        self.app._status_item_last_error = None
        self.app._status_item_repair_count = 0
        self.native = SimpleNamespace(
            NSStatusBar=SimpleNamespace(systemStatusBar=lambda: self.bar),
            NSSquareStatusItemLength=-2,
        )

    def configure(self):
        self.assertIs(self.app._nsapp.nsstatusitem, self.replacement)
        self.bar.removeStatusItem_.assert_not_called()
        self.app._status_item_ready = True
        self.app._status_item_last_error = None

    def test_recovery_replaces_item_and_preserves_menu_before_removing_old(self):
        self.app._ensure_status_item_visible = self.configure
        with patch.dict('sys.modules', AppKit=self.native):
            self.app._recreate_status_item()
        self.assertIs(self.app._nsapp.nsstatusitem, self.replacement)
        self.replacement.setMenu_.assert_called_once_with(self.old.menu())
        self.bar.removeStatusItem_.assert_called_once_with(self.old)
        self.assertTrue(self.app._status_item_ready)

    def test_failed_icon_configuration_preserves_old_item_and_removes_replacement(self):
        def fail():
            self.app._status_item_ready = False
            self.app._status_item_last_error = 'icon_load_failed'
        self.app._ensure_status_item_visible = fail
        with patch.dict('sys.modules', AppKit=self.native), self.assertLogs(level='ERROR'):
            self.app._recreate_status_item()
        self.assertIs(self.app._nsapp.nsstatusitem, self.old)
        self.bar.removeStatusItem_.assert_called_once_with(self.replacement)
        self.assertTrue(self.app._status_item_ready)
        self.assertIn('icon_load_failed', self.app._status_item_last_error)

    def test_allocation_failure_preserves_old_item(self):
        self.bar.statusItemWithLength_.return_value = None
        with patch.dict('sys.modules', AppKit=self.native), self.assertLogs(level='ERROR'):
            self.app._recreate_status_item()
        self.assertIs(self.app._nsapp.nsstatusitem, self.old)
        self.bar.removeStatusItem_.assert_not_called()
        self.assertIn('Unable to create', self.app._status_item_last_error)

    def test_repair_runs_replacement_and_counter_on_main_thread(self):
        self.app._recreate_status_item = Mock()
        self.app.menu_bar_status = Mock(return_value={'repair_count': 1})
        with patch('local_asr_server.window.run_on_main_thread',
                   side_effect=lambda callback, wait: callback()) as dispatch:
            result = self.app.repair_menu_bar()
        self.assertEqual(result['repair_count'], 1)
        self.assertEqual(self.app._status_item_repair_count, 1)
        dispatch.assert_called_once()
        self.assertTrue(dispatch.call_args.kwargs['wait'])
        self.app._recreate_status_item.assert_called_once()

    def test_detached_button_is_reported_without_display_claim(self):
        button = Mock()
        button.window.return_value = None
        self.assertEqual(self.app._status_item_window_status(button), {'attached': False})


if __name__ == '__main__':
    unittest.main()
