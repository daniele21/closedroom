from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from local_asr_server.native_capture import CaptureSession, NativeCaptureManager
from local_asr_server.runtime.capture_events import (
    BoundedCaptureEventHistory,
    CoalescingCaptureEventQueue,
)


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class NativeCaptureEventRetentionTests(unittest.TestCase):
    def test_capture_session_defaults_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = CaptureSession(
                recording_id="rec-1",
                mode="both",
                process=_FakeProcess([]),  # type: ignore[arg-type]
                output_dir=Path(temporary),
            )

        self.assertIsInstance(session.events, CoalescingCaptureEventQueue)
        self.assertIsInstance(session.event_log, BoundedCaptureEventHistory)
        self.assertEqual(session.warnings.maxlen, 128)

    def test_reader_coalesces_volume_and_bounds_warning_retention(self) -> None:
        lines: list[str] = [json.dumps({"type": "ready"}) + "\n"]
        for index in range(1000):
            lines.append(json.dumps({"type": "volume", "source": "mic", "db": float(index)}) + "\n")
            lines.append(json.dumps({"type": "volume", "source": "system", "db": float(index + 1)}) + "\n")
        for index in range(140):
            lines.append(json.dumps({"type": "warning", "source": "backend", "message": f"warning-{index}"}) + "\n")
        lines.append(json.dumps({"type": "stopped"}) + "\n")

        process = _FakeProcess(lines)
        with tempfile.TemporaryDirectory() as temporary:
            session = CaptureSession(
                recording_id="rec-2",
                mode="both",
                process=process,  # type: ignore[arg-type]
                output_dir=Path(temporary),
            )
            manager = NativeCaptureManager(helper_path=Path("/nonexistent"))
            manager._read_events(session)

        self.assertTrue(process.stdout.closed)
        self.assertTrue(session.stopped)
        self.assertEqual(session.last_volume["mic"], 999.0)
        self.assertEqual(session.last_volume["system"], 1000.0)
        self.assertEqual(len(session.warnings), 128)
        self.assertEqual(session.warnings[0]["message"], "warning-12")

        queue_stats = session.events.stats()
        self.assertEqual(queue_stats["pending_volume_sources"], 2)
        self.assertEqual(queue_stats["coalesced_volume_events"], 1998)
        self.assertLessEqual(queue_stats["pending_discrete_events"], queue_stats["capacity"])

        history_stats = session.event_log.stats()
        self.assertEqual(history_stats["ignored_volume_events"], 2000)
        self.assertLessEqual(history_stats["retained_events"], history_stats["capacity"])


if __name__ == "__main__":
    unittest.main()
