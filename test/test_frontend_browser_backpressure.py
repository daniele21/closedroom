from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HOOK = ROOT / "frontend" / "src" / "hooks" / "useRecorder.ts"
BACKLOG = ROOT / "frontend" / "src" / "utils" / "browserUploadBacklog.ts"


class BrowserRecordingBackpressureContractTests(unittest.TestCase):
    def test_backlog_has_explicit_byte_and_chunk_budgets(self) -> None:
        source = BACKLOG.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_BROWSER_UPLOAD_MAX_PENDING_BYTES", source)
        self.assertIn("DEFAULT_BROWSER_UPLOAD_MAX_PENDING_CHUNKS", source)
        self.assertIn("64 * 1024 * 1024", source)
        self.assertIn("= 24", source)
        self.assertIn("highWaterBytes", source)
        self.assertIn("highWaterChunks", source)

    def test_recorder_fails_closed_without_pausing_or_dropping_chunks(self) -> None:
        source = HOOK.read_text(encoding="utf-8")
        self.assertIn("BrowserUploadBacklog", source)
        self.assertIn("browserUploadBacklogRef", source)
        self.assertIn("browserBackpressureTriggeredRef", source)
        self.assertIn("backlogSnapshot.saturated", source)
        self.assertIn(".finally(() =>", source)
        self.assertIn("browserUploadBacklogRef.current.release", source)
        self.assertIn("t('recording.uploadBackpressure')", source)
        self.assertNotIn("browser upload backlog limit reached", source)
        self.assertNotIn("recorder.pause()", source)
        self.assertNotIn("event.data.size >", source)


if __name__ == "__main__":
    unittest.main()
