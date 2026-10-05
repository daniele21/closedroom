from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HOOK = ROOT / "frontend" / "src" / "hooks" / "useRecorder.ts"
STATE = ROOT / "frontend" / "src" / "hooks" / "recorderLifecycle.ts"


class RecorderLifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = HOOK.read_text(encoding="utf-8")
        self.state = STATE.read_text(encoding="utf-8")

    def test_recorder_lifecycle_is_explicit_and_bounded(self) -> None:
        for phase in ("idle", "preparing", "waiting_for_ai", "recording", "stopping"):
            self.assertIn(f"'{phase}'", self.state)
        self.assertIn("recorderLifecycleReducer", self.state)
        self.assertIn("recorderLifecycleFlags", self.state)

    def test_hook_derives_mutually_exclusive_public_flags_from_lifecycle(self) -> None:
        self.assertIn("useReducer(recorderLifecycleReducer", self.hook)
        self.assertIn("recorderLifecycleFlags(recorderLifecycle)", self.hook)
        self.assertNotIn("const [isRecording, setIsRecording] = useState", self.hook)
        self.assertNotIn("const [isPreparingRecording, setIsPreparingRecording] = useState", self.hook)
        self.assertNotIn("const [isWaitingForAi, setIsWaitingForAi] = useState", self.hook)

    def test_major_transitions_are_dispatched_by_recording_flow(self) -> None:
        for action in (
            "prepare",
            "wait_for_ai",
            "resume_preparation",
            "recording_started",
            "stop_requested",
            "reset",
        ):
            self.assertIn(f"type: '{action}'", self.hook)


if __name__ == "__main__":
    unittest.main()
