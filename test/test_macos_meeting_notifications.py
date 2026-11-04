from __future__ import annotations

import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from local_asr_server.macos_meeting_notifications import (
    CATEGORY_ID, IGNORE_ACTION, RECORD_ACTION, MeetingNotificationCenter,
    decode_notification_action, needs_initial_notification_consent,
    _native_framework,
)


class ActionableMeetingNotificationContractTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS app bridge")
    def test_native_bridge_has_completion_handler_signatures(self):
        # Exercise actual PyObjC metadata: class-only loading passes mock tests
        # but fails on the Mac with 'a block, but no signature available'.
        native = _native_framework()
        for selector, index, argument_types in (
            ("requestAuthorizationWithOptions_completionHandler_", 3, (b"Z", b"@")),
            ("getNotificationSettingsWithCompletionHandler_", 2, (b"@",)),
            ("addNotificationRequest_withCompletionHandler_", 3, (b"@",)),
        ):
            with self.subTest(selector=selector):
                block = getattr(native.UNUserNotificationCenter, selector).__metadata__()["arguments"][index]
                self.assertEqual(block["type"], b"@?")
                self.assertEqual(block["callable"]["retval"]["type"], b"v")
                self.assertEqual(
                    tuple(arg["type"] for arg in block["callable"]["arguments"][1:]),
                    argument_types,
                )

    def test_first_run_notification_consent_is_explicit_once_and_respects_off(self):
        should_ask = needs_initial_notification_consent
        self.assertTrue(should_ask(enabled=True, authorization="not_determined",
                                   requested_this_launch=False))
        for enabled, authorization, requested in (
            (False, "not_determined", False),
            (True, "authorized", False),
            (True, "denied", False),
            (True, "unknown", False),
            (True, "not_determined", True),
        ):
            with self.subTest(enabled=enabled, authorization=authorization, requested=requested):
                self.assertFalse(should_ask(enabled=enabled, authorization=authorization,
                                            requested_this_launch=requested))

    def test_record_and_ignore_are_scoped_to_closedroom_candidate(self):
        self.assertEqual(
            decode_notification_action("closedroom.meeting.test-session", RECORD_ACTION),
            ("test-session", "record"),
        )
        self.assertEqual(
            decode_notification_action("closedroom.meeting.test-session", IGNORE_ACTION),
            ("test-session", "ignore"),
        )
        self.assertEqual(
            decode_notification_action("closedroom.meeting.test-session",
                                       "com.apple.UNNotificationDefaultActionIdentifier"),
            ("test-session", "body_open"),
        )
        self.assertEqual(
            decode_notification_action("closedroom.meeting.test-session",
                                       "com.apple.UNNotificationDismissActionIdentifier"),
            ("test-session", "dismiss"),
        )
        self.assertIsNone(decode_notification_action("unrelated-notification", RECORD_ACTION))
        self.assertIsNone(decode_notification_action("closedroom.meeting.", RECORD_ACTION))
        self.assertIsNone(decode_notification_action("closedroom.meeting.x", "unknown"))

    def test_permission_state_and_delivery_failures_are_not_silent(self):
        center = MeetingNotificationCenter(lambda *_: None)
        center._set_authorization(0)
        self.assertEqual(center.authorization, "not_determined")
        center._set_authorization(2)
        self.assertEqual(center.authorization, "authorized")
        center._record_delivery_error(RuntimeError("synthetic"))
        self.assertEqual(center.last_error, "notification_delivery_failed")
        center._set_authorization(1)
        self.assertEqual(center.authorization, "denied")
        self.assertEqual(center.last_error, "notification_delivery_failed")
        center._record_delivery_error(None)
        self.assertIsNone(center.last_error)

    def test_os_submission_acknowledgement_is_async_and_failure_is_visible(self):
        class FakeContent:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                return self

            def setTitle_(self, title):
                self.title = title

            def setBody_(self, body):
                self.body = body

            def setCategoryIdentifier_(self, category):
                self.category = category

        class FakeRequest:
            @staticmethod
            def requestWithIdentifier_content_trigger_(identifier, content, trigger):
                return (identifier, content)

        class FakeCenter:
            def __init__(self):
                self.complete = None
                self.requests = []

            def addNotificationRequest_withCompletionHandler_(self, request, completion):
                self.requests.append(request)
                self.complete = completion

        fake = FakeCenter()
        native = SimpleNamespace(
            UNMutableNotificationContent=FakeContent, UNNotificationRequest=FakeRequest
        )
        center = MeetingNotificationCenter(lambda *_: None, native=native)
        center._center = fake
        center._authorization = "authorized"
        results = []
        with patch.dict(sys.modules, {
            "local_asr_server.window": SimpleNamespace(run_on_main_thread=lambda fn: fn())
        }):
            self.assertTrue(center.notify("candidate-1", app_label="Zoom", on_result=results.append))
        self.assertEqual(results, [])  # scheduling is NOT delivery acknowledgement
        self.assertEqual(fake.requests[0][0], "closedroom.meeting.candidate-1")
        fake.complete(RuntimeError("submission failed"))
        self.assertEqual(results, [False])
        self.assertEqual(center.last_error, "notification_delivery_failed")

        with patch.dict(sys.modules, {
            "local_asr_server.window": SimpleNamespace(run_on_main_thread=lambda fn: fn())
        }):
            self.assertTrue(center.notify("candidate-2", on_result=results.append))
        fake.complete(None)
        self.assertEqual(results, [False, True])
        self.assertIsNone(center.last_error)

    def test_unavailable_native_callbacks_fail_closed_without_crashing_shell(self):
        def raise_native(*_args):
            raise RuntimeError("native bridge unavailable")

        center = MeetingNotificationCenter(lambda *_: None)
        center._center = SimpleNamespace(
            getNotificationSettingsWithCompletionHandler_=raise_native,
            removeDeliveredNotificationsWithIdentifiers_=raise_native,
        )
        center._authorization = "checking"
        with patch.dict(sys.modules, {
            "local_asr_server.window": SimpleNamespace(run_on_main_thread=lambda fn: fn())
        }):
            center.refresh_authorization()
            self.assertEqual(center.authorization, "unknown")
            self.assertEqual(center.last_error, "notification_settings_query_failed")
            center.dismiss("candidate")
            self.assertEqual(center.last_error, "notification_dismiss_failed")

        with patch.dict(sys.modules, {
            "local_asr_server.window": SimpleNamespace(run_on_main_thread=raise_native)
        }):
            self.assertFalse(center.request_authorization())
            self.assertEqual(center.last_error, "notification_permission_request_failed")

    def test_denied_permission_does_not_fake_submission(self):
        center = MeetingNotificationCenter(lambda *_: None)
        center._center = object()
        center._authorization = "denied"
        results = []
        self.assertFalse(center.notify("candidate", on_result=results.append))
        self.assertEqual(results, [])

    def test_no_native_center_does_not_fake_delivery(self):
        center = MeetingNotificationCenter(lambda *_: None)
        self.assertFalse(center.available)
        self.assertFalse(center.notify("id"))
        self.assertEqual(CATEGORY_ID, "closedroom.meeting.suggestion")


if __name__ == "__main__":
    unittest.main()
