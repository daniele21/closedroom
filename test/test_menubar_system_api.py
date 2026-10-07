from __future__ import annotations

from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from local_asr_server.routers import system


class _FakeMenuBarController:
    def __init__(self) -> None:
        self.repair_calls = 0
        self.settings_calls = 0

    def menu_bar_status(self) -> dict:
        return {
            "available": True,
            "visible": True,
            "icon_loaded": True,
            "state": "idle",
            "icon_asset": "design/assets/brand/closedroom-microphone-mark.png",
            "repair_count": self.repair_calls,
            "last_error": None,
        }

    def repair_menu_bar(self) -> dict:
        self.repair_calls += 1
        return self.menu_bar_status()

    def open_menu_bar_settings(self) -> dict:
        self.settings_calls += 1
        return {
            "opened": True,
            "url": "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension",
        }


def _request(controller=None):
    state = SimpleNamespace()
    if controller is not None:
        state.menubar_controller = controller
    return SimpleNamespace(app=SimpleNamespace(state=state))


class MenuBarSystemApiTests(unittest.TestCase):
    def test_status_projects_native_controller_state(self) -> None:
        controller = _FakeMenuBarController()

        payload = system.system_menubar_status(_request(controller))

        self.assertTrue(payload["available"])
        self.assertTrue(payload["visible"])
        self.assertTrue(payload["icon_loaded"])
        self.assertEqual(
            payload["icon_asset"],
            "design/assets/brand/closedroom-microphone-mark.png",
        )

    def test_status_is_truthful_when_native_controller_is_absent(self) -> None:
        payload = system.system_menubar_status(_request())

        self.assertFalse(payload["available"])
        self.assertFalse(payload["visible"])
        self.assertEqual(payload["last_error"], "menubar_controller_unavailable")

    def test_refresh_delegates_to_native_controller(self) -> None:
        controller = _FakeMenuBarController()

        payload = system.refresh_system_menubar(_request(controller))

        self.assertEqual(controller.repair_calls, 1)
        self.assertEqual(payload["repair_count"], 1)
        self.assertTrue(payload["visible"])

    def test_open_settings_delegates_to_native_controller(self) -> None:
        controller = _FakeMenuBarController()

        payload = system.open_system_menubar_settings(_request(controller))

        self.assertEqual(controller.settings_calls, 1)
        self.assertTrue(payload["opened"])
        self.assertIn("ControlCenter-Settings.extension", payload["url"])

    def test_refresh_rejects_non_menubar_runtime(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            system.refresh_system_menubar(_request())

        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
