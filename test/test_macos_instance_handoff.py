"""No second writer or unapproved process termination during macOS app handoff."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from local_asr_server import macos_instance_handoff as handoff


class FakeRunningApp:
    def __init__(self, bundle: str, path: str, pid: int = 42, terminated: bool = False):
        self._bundle = bundle
        self._path = path
        self._pid = pid
        self._terminated = terminated
        self.activateWithOptions_ = Mock(return_value=True)

    def bundleIdentifier(self):
        return self._bundle

    def processIdentifier(self):
        return self._pid

    def isTerminated(self):
        return self._terminated

    def bundleURL(self):
        return SimpleNamespace(path=lambda: self._path)


class InstanceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.running = []
        self.alert = Mock()
        self.alert.runModal.return_value = 1000
        self.native = SimpleNamespace(
            NSWorkspace=SimpleNamespace(
                sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: self.running),
            ),
            NSAlert=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: self.alert)),
            NSAlertStyleInformational=1,
            NSRunningApplicationActivateIgnoringOtherApps=2,
        )
        self.patches = [
            patch.dict(sys.modules, {"AppKit": self.native}),
            patch.object(handoff.sys, "platform", "darwin"),
            patch.object(handoff.sys, "executable", "/Apps/New/ClosedRoom.app/Contents/MacOS/ClosedRoom"),
            patch.object(handoff.os, "getpid", return_value=999),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_same_build_activates_without_dialog_or_new_server(self):
        peer = FakeRunningApp("com.closedroom.app", "/Apps/New/ClosedRoom.app")
        self.running.append(peer)
        self.assertEqual(handoff.handle_existing_instance(), "focused")
        peer.activateWithOptions_.assert_called_once_with(2)
        self.alert.runModal.assert_not_called()

    def test_other_build_does_not_terminate_peer_and_requires_user_choice(self):
        peer = FakeRunningApp("com.closedroom.app", "/Applications/ClosedRoom.app")
        self.running.append(peer)
        self.alert.runModal.return_value = 1001
        self.assertEqual(handoff.handle_existing_instance(), "explained")
        peer.activateWithOptions_.assert_not_called()
        self.alert.setMessageText_.assert_called_with("ClosedRoom è già aperto")
        self.assertIn("Un'altra versione", self.alert.setInformativeText_.call_args.args[0])

    def test_other_build_may_be_activated_after_explicit_choice(self):
        peer = FakeRunningApp("com.closedroom.app", "/Applications/ClosedRoom.app")
        self.running.append(peer)
        self.assertEqual(handoff.handle_existing_instance(), "focused")
        peer.activateWithOptions_.assert_called_once_with(2)

    def test_ambiguous_peers_are_not_activated(self):
        first = FakeRunningApp("com.closedroom.app", "/Applications/ClosedRoom.app", pid=42)
        second = FakeRunningApp("com.closedroom.app", "/Apps/Other/ClosedRoom.app", pid=43)
        self.running.extend([first, second])
        self.assertEqual(handoff.handle_existing_instance(), "explained")
        first.activateWithOptions_.assert_not_called()
        second.activateWithOptions_.assert_not_called()
        self.alert.addButtonWithTitle_.assert_any_call("OK")

    def test_unrelated_and_self_processes_are_not_assumed_lock_owners(self):
        self.running.extend([
            FakeRunningApp("com.example.other", "/Applications/Other.app"),
            FakeRunningApp("com.closedroom.app", "/Apps/New/ClosedRoom.app", pid=999),
            FakeRunningApp("com.closedroom.app", "/Apps/New/ClosedRoom.app", pid=31, terminated=True),
        ])
        self.assertEqual(handoff.handle_existing_instance(), "explained")
        self.alert.addButtonWithTitle_.assert_any_call("OK")

    def test_non_macos_does_not_attempt_native_handoff(self):
        with patch.object(handoff.sys, "platform", "linux"):
            self.assertEqual(handoff.handle_existing_instance(), "unavailable")
        self.alert.runModal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
