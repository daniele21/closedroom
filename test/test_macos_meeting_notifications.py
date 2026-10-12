from __future__ import annotations

import unittest

from local_asr_server.macos_meeting_notifications import (
    CATEGORY_ID, IGNORE_ACTION, RECORD_ACTION, MeetingNotificationCenter,
    decode_notification_action,
)


class ActionableMeetingNotificationContractTests(unittest.TestCase):
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
        self.assertIsNone(center.last_error)

    def test_no_native_center_does_not_fake_delivery(self):
        center = MeetingNotificationCenter(lambda *_: None)
        self.assertFalse(center.available)
        self.assertFalse(center.notify("id"))
        self.assertEqual(CATEGORY_ID, "closedroom.meeting.suggestion")


if __name__ == "__main__":
    unittest.main()
