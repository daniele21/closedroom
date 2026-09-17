from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.visual_intelligence.contracts import (
    FrameCandidate,
    VisualRoutingConfig,
    VisualTask,
    VisualTrigger,
)
from local_asr_server.visual_intelligence.router import TaskAwareFrameRouter
from visual_intelligence_support import jpeg


class VisualRouterTests(unittest.TestCase):
    def test_first_frame_emits_all_task_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.jpg"
            path.write_bytes(jpeg())
            candidates, summary = TaskAwareFrameRouter(VisualRoutingConfig(mode="v2")).route(
                [{"sequence": 0, "timestamp": 0.0, "path": path}], [],
            )
            self.assertEqual(
                {candidate.task.value for candidate in candidates},
                {"meeting_ui", "meeting_state", "shared_content"},
            )
            self.assertFalse(summary["candidate_budget_applied"])
            self.assertEqual(summary["uncapped_candidate_count"], 3)

    def test_candidate_budget_is_deterministic_and_preserves_full_timeline(self):
        candidates = [
            FrameCandidate(
                sequence=index,
                timestamp=float(index),
                task=VisualTask.MEETING_STATE,
                trigger=VisualTrigger.HEARTBEAT,
            )
            for index in range(10)
        ]

        bounded = TaskAwareFrameRouter._apply_candidate_budget(candidates, 4)

        self.assertEqual([item.sequence for item in bounded], [0, 3, 6, 9])

    def test_candidate_budget_rejects_invalid_zero_budget(self):
        candidate = FrameCandidate(
            sequence=0,
            timestamp=0.0,
            task=VisualTask.MEETING_STATE,
            trigger=VisualTrigger.FIRST_FRAME,
        )
        with self.assertRaises(ValueError):
            TaskAwareFrameRouter._apply_candidate_budget([candidate], 0)


if __name__ == "__main__":
    unittest.main()
