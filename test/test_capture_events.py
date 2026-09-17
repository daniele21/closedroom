from __future__ import annotations

import queue
import unittest

from local_asr_server.runtime.capture_events import (
    BoundedCaptureEventHistory,
    CoalescingCaptureEventQueue,
)


class CaptureEventBufferTests(unittest.TestCase):
    def test_volume_events_are_coalesced_per_source(self) -> None:
        events = CoalescingCaptureEventQueue(capacity=4)
        for index in range(1000):
            events.put({"type": "volume", "source": "mic", "db": -60.0 + index})
            events.put({"type": "volume", "source": "system", "db": -50.0 + index})

        self.assertEqual(events.qsize(), 2)
        stats = events.stats()
        self.assertEqual(stats["pending_volume_sources"], 2)
        self.assertEqual(stats["coalesced_volume_events"], 1998)

        drained = [events.get_nowait(), events.get_nowait()]
        by_source = {event["source"]: event for event in drained}
        self.assertEqual(by_source["mic"]["db"], 939.0)
        self.assertEqual(by_source["system"]["db"], 949.0)
        with self.assertRaises(queue.Empty):
            events.get_nowait()

    def test_discrete_events_are_bounded_and_drop_oldest(self) -> None:
        events = CoalescingCaptureEventQueue(capacity=3)
        for index in range(5):
            events.put({"type": "warning", "message": f"warning-{index}"})

        self.assertEqual(events.qsize(), 3)
        self.assertEqual(events.stats()["dropped_events"], 2)
        self.assertEqual(
            [events.get_nowait()["message"] for _ in range(3)],
            ["warning-2", "warning-3", "warning-4"],
        )

    def test_discrete_events_are_drained_before_latest_volume(self) -> None:
        events = CoalescingCaptureEventQueue(capacity=3)
        events.put({"type": "volume", "source": "mic", "db": -20.0})
        events.put({"type": "ready"})

        self.assertEqual(events.get_nowait()["type"], "ready")
        self.assertEqual(events.get_nowait()["type"], "volume")

    def test_history_ignores_volume_and_has_fixed_capacity(self) -> None:
        history = BoundedCaptureEventHistory(capacity=2)
        for index in range(1000):
            history.append({"type": "volume", "source": "mic", "db": float(index)})
        history.append({"type": "ready", "sequence": 1})
        history.append({"type": "warning", "sequence": 2})
        history.append({"type": "stopped", "sequence": 3})

        self.assertEqual(len(history), 2)
        self.assertEqual([event["type"] for event in history], ["warning", "stopped"])
        stats = history.stats()
        self.assertEqual(stats["ignored_volume_events"], 1000)
        self.assertEqual(stats["dropped_events"], 1)

    def test_capacity_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            CoalescingCaptureEventQueue(capacity=0)
        with self.assertRaises(ValueError):
            BoundedCaptureEventHistory(capacity=0)


if __name__ == "__main__":
    unittest.main()
