from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from local_asr_server.routers.system import (
    MeetingStartIntentRequest, MeetingStartFeedbackRequest,
    authorize_meeting_detection, claim_meeting_start_intent, meeting_start_feedback,
)


class FakeController:
    def __init__(self):
        self.used = set()
        self.feedback = []

    def authorize_meeting_detection(self):
        return True

    def claim_meeting_start_intent(self, token):
        if token in self.used:
            return False
        self.used.add(token)
        return True

    def meeting_start_feedback(self, token, phase):
        self.feedback.append((token, phase))
        return token in self.used


class MeetingDetectionApiTests(unittest.TestCase):
    def test_authenticated_shell_adapter_delegates_one_time_claim(self):
        controller = FakeController()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(menubar_controller=controller)))
        token = "a" * 24
        self.assertEqual(authorize_meeting_detection(request), {"requested": True})
        body = MeetingStartIntentRequest(token=token)
        self.assertEqual(claim_meeting_start_intent(request, body), {"accepted": True})
        self.assertEqual(claim_meeting_start_intent(request, body), {"accepted": False})
        feedback = MeetingStartFeedbackRequest(token=token, phase="preparing")
        self.assertEqual(meeting_start_feedback(request, feedback), {"accepted": True})
        self.assertEqual(controller.feedback, [(token, "preparing")])

    def test_non_native_runtime_fails_closed(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(menubar_controller=None)))
        with self.assertRaises(HTTPException) as ctx:
            authorize_meeting_detection(request)
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
