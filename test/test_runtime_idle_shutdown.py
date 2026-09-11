from __future__ import annotations

import unittest
from threading import Event, Thread
from unittest.mock import Mock, patch

from local_asr_server.runtime.service_manager import RuntimeServiceManager


AUTO_SETTINGS = {
    "mode": "auto",
    "model": "nemotron-nano-4b-q8",
    "model_path": None,
    "dynamic_residency": True,
    "url": "http://127.0.0.1:1235",
    "reasoning": "auto",
    "backend": "",
    "mmproj_path": "",
    "ctx_size": None,
    "startup_timeout": None,
    "llama_server_bin": "",
}


class FakeTimer:
    instances: list["FakeTimer"] = []

    def __init__(self, interval: float, callback) -> None:
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()

    def fire_stale(self) -> None:
        """Simulate a callback that already woke up before Timer.cancel()."""
        self.callback()


class RuntimeIdleShutdownTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTimer.instances.clear()

    def test_release_schedules_bounded_stop_after_residency_is_cold(self) -> None:
        sidecar = Mock()
        sidecar.release_resident_models.return_value = {"released": True, "cold": True}
        manager = RuntimeServiceManager(llm_sidecar=sidecar)

        with (
            patch.object(manager, "_llm_settings", return_value=AUTO_SETTINGS),
            patch("local_asr_server.runtime.service_manager.Timer", FakeTimer),
        ):
            result = manager.release_llm_residency()

            self.assertEqual(result, {"released": True, "cold": True})
            self.assertEqual(len(FakeTimer.instances), 1)
            timer = FakeTimer.instances[0]
            self.assertEqual(timer.interval, 90.0)
            self.assertTrue(timer.started)
            sidecar.stop.assert_not_called()

            timer.fire()
            sidecar.stop.assert_called_once_with()

    def test_new_managed_request_cancels_pending_idle_stop(self) -> None:
        sidecar = Mock()
        sidecar.release_resident_models.return_value = {"released": True, "cold": True}
        sidecar.ensure_ready.return_value = {"base_url": "http://127.0.0.1:1235"}
        manager = RuntimeServiceManager(llm_sidecar=sidecar)

        with (
            patch.object(manager, "_llm_settings", return_value=AUTO_SETTINGS),
            patch("local_asr_server.runtime.service_manager.Timer", FakeTimer),
        ):
            manager.release_llm_residency()
            timer = FakeTimer.instances[0]
            manager.ensure_llm_ready()

            self.assertTrue(timer.cancelled)
            sidecar.ensure_ready.assert_called_once()
            timer.fire_stale()
            sidecar.stop.assert_not_called()

    def test_reuse_cannot_interleave_between_release_and_idle_schedule(self) -> None:
        release_entered = Event()
        release_continue = Event()
        sidecar = Mock()

        def release_models():
            release_entered.set()
            self.assertTrue(release_continue.wait(timeout=2.0))
            return {"released": True, "cold": True}

        sidecar.release_resident_models.side_effect = release_models
        sidecar.ensure_ready.return_value = {"base_url": "http://127.0.0.1:1235"}
        manager = RuntimeServiceManager(llm_sidecar=sidecar)

        with (
            patch.object(manager, "_llm_settings", return_value=AUTO_SETTINGS),
            patch("local_asr_server.runtime.service_manager.Timer", FakeTimer),
        ):
            release_thread = Thread(target=manager.release_llm_residency)
            release_thread.start()
            self.assertTrue(release_entered.wait(timeout=2.0))

            ensure_thread = Thread(target=manager.ensure_llm_ready)
            ensure_thread.start()
            self.assertFalse(sidecar.ensure_ready.called)

            release_continue.set()
            release_thread.join(timeout=2.0)
            ensure_thread.join(timeout=2.0)
            self.assertFalse(release_thread.is_alive())
            self.assertFalse(ensure_thread.is_alive())

            self.assertEqual(len(FakeTimer.instances), 1)
            timer = FakeTimer.instances[0]
            self.assertTrue(timer.cancelled)
            sidecar.ensure_ready.assert_called_once()
            timer.fire_stale()
            sidecar.stop.assert_not_called()

    def test_new_release_invalidates_already_woken_old_timer(self) -> None:
        sidecar = Mock()
        sidecar.release_resident_models.return_value = {"released": True, "cold": True}
        manager = RuntimeServiceManager(llm_sidecar=sidecar)

        with (
            patch.object(manager, "_llm_settings", return_value=AUTO_SETTINGS),
            patch("local_asr_server.runtime.service_manager.Timer", FakeTimer),
        ):
            manager.release_llm_residency()
            first_timer = FakeTimer.instances[0]
            manager.release_llm_residency()
            second_timer = FakeTimer.instances[1]

            self.assertTrue(first_timer.cancelled)
            first_timer.fire_stale()
            sidecar.stop.assert_not_called()

            second_timer.fire()
            sidecar.stop.assert_called_once_with()

    def test_external_release_never_schedules_or_mutates_sidecar(self) -> None:
        sidecar = Mock()
        manager = RuntimeServiceManager(llm_sidecar=sidecar)
        external = {**AUTO_SETTINGS, "mode": "external"}

        with (
            patch.object(manager, "_llm_settings", return_value=external),
            patch("local_asr_server.runtime.service_manager.Timer", FakeTimer),
        ):
            result = manager.release_llm_residency()

        self.assertEqual(result, {"released": False, "reason": "not_managed"})
        self.assertEqual(FakeTimer.instances, [])
        sidecar.release_resident_models.assert_not_called()
        sidecar.stop.assert_not_called()

    def test_zero_idle_window_stops_managed_sidecar_immediately(self) -> None:
        sidecar = Mock()
        sidecar.release_resident_models.return_value = {"released": True, "cold": True}
        manager = RuntimeServiceManager(
            llm_sidecar=sidecar,
            managed_llm_idle_shutdown_seconds=0,
        )

        with patch.object(manager, "_llm_settings", return_value=AUTO_SETTINGS):
            manager.release_llm_residency()

        sidecar.release_resident_models.assert_called_once_with()
        sidecar.stop.assert_called_once_with()

    def test_negative_idle_window_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeServiceManager(
                llm_sidecar=Mock(),
                managed_llm_idle_shutdown_seconds=-1,
            )


if __name__ == "__main__":
    unittest.main()
