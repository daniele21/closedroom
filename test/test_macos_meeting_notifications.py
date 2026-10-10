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

    def test_no_native_center_does_not_fake_delivery(self):
        center = MeetingNotificationCenter(lambda *_: None)
        self.assertFalse(center.available)
        self.assertFalse(center.notify("id"))
        self.assertEqual(CATEGORY_ID, "closedroom.meeting.suggestion")


if __name__ == "__main__":
    unittest.main()
