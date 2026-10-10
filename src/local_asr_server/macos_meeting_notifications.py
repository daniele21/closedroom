"""App-owned, actionable macOS meeting prompts. No media or cloud calls.

The notification center delegate must be strongly retained for the lifetime of
the menu-bar process. Action callbacks are routed back to the shell; this
adapter never starts, stops or persists a recording.
"""
from __future__ import annotations

import sys
from typing import Callable

CATEGORY_ID = "closedroom.meeting.suggestion"
RECORD_ACTION = "closedroom.meeting.record"
IGNORE_ACTION = "closedroom.meeting.ignore"
NOTIFICATION_PREFIX = "closedroom.meeting."
ACTION_NAMES = {RECORD_ACTION: "record", IGNORE_ACTION: "ignore",
                "com.apple.UNNotificationDefaultActionIdentifier": "body_open",
                "com.apple.UNNotificationDismissActionIdentifier": "dismiss"}


def decode_notification_action(identifier: str, action_identifier: str) -> tuple[str, str] | None:
    if not identifier.startswith(NOTIFICATION_PREFIX) or not identifier[len(NOTIFICATION_PREFIX):]:
        return None
    action = ACTION_NAMES.get(action_identifier)
    if action is None:
        return None
    return identifier[len(NOTIFICATION_PREFIX):], action


class MeetingNotificationCenter:
    """UNUserNotificationCenter owner with a mockable platform boundary."""

    def __init__(self, callback: Callable[[str, str], None], *, native=None):
        self._callback = callback
        self._native = native
        self._center = None
        self._delegate = None
        self._authorization = "unknown"

    @property
    def authorization(self) -> str:
        return self._authorization

    @property
    def available(self) -> bool:
        return self._center is not None

    def start(self) -> bool:
        if self._center is not None:
            return True
        if sys.platform != "darwin" and self._native is None:
            self._authorization = "unsupported"
            return False
        try:
            native = self._native
            if native is None:
                import UserNotifications as native
            from Foundation import NSObject
            from local_asr_server.window import run_on_main_thread

            class MeetingNotificationDelegate(NSObject):
                def initWithHandler_(self, handler):
                    self = self.init()
                    if self is not None:
                        self._handle = handler
                    return self

                def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
                    self, center, response, completionHandler
                ):
                    try:
                        request = response.notification().request()
                        decoded = decode_notification_action(
                            str(request.identifier()), str(response.actionIdentifier())
                        )
                        if decoded:
                            self._handle(*decoded)
                    finally:
                        completionHandler()

                def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                    self, center, notification, completionHandler
                ):
                    completionHandler(int(getattr(native, "UNNotificationPresentationOptionBanner", 2)))

            def configure():
                center = native.UNUserNotificationCenter.currentNotificationCenter()
                delegate = MeetingNotificationDelegate.alloc().initWithHandler_(self._callback)
                actions = [
                    native.UNNotificationAction.actionWithIdentifier_title_options_(
                        RECORD_ACTION, "Registra", 0
                    ),
                    native.UNNotificationAction.actionWithIdentifier_title_options_(
                        IGNORE_ACTION, "Non ora", 0
                    ),
                ]
                category = native.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                    CATEGORY_ID, actions, [], int(getattr(native, "UNNotificationCategoryOptionCustomDismissAction", 1))
                )
                center.setNotificationCategories_({category})
                center.setDelegate_(delegate)
                self._center = center
                self._delegate = delegate  # keep alive
                center.getNotificationSettingsWithCompletionHandler_(
                    lambda s: self._set_authorization(int(s.authorizationStatus()))
                )

            run_on_main_thread(configure, wait=True)
            return self._center is not None
        except (ImportError, AttributeError, RuntimeError, OSError):
            self._authorization = "unsupported"
            return False

    def _set_authorization(self, status: int) -> None:
        # UNAuthorizationStatus: notDetermined 0, denied 1, authorized 2, provisional 3.
        self._authorization = {0: "not_determined", 1: "denied",
                               2: "authorized", 3: "authorized", 4: "authorized"}.get(status, "unknown")

    def request_authorization(self) -> bool:
        """Only call as the direct result of a deliberate user opt-in."""
        if not self.start():
            return False
        from local_asr_server.window import run_on_main_thread

        def request():
            native = self._native
            if native is None:
                import UserNotifications as native
            options = int(native.UNAuthorizationOptionAlert) | int(native.UNAuthorizationOptionSound)
            def completed(granted, error):
                self._authorization = "authorized" if granted else "denied"
            self._center.requestAuthorizationWithOptions_completionHandler_(options, completed)
        run_on_main_thread(request)
        return True

    def notify(self, candidate_id: str, *, app_label: str | None = None) -> bool:
        if not self._center or self._authorization != "authorized":
            return False
        from local_asr_server.window import run_on_main_thread

        def deliver():
            native = self._native
            if native is None:
                import UserNotifications as native
            content = native.UNMutableNotificationContent.alloc().init()
            content.setTitle_("Una chiamata in corso?")
            content.setBody_(f"{app_label} sta utilizzando il microfono. Vuoi registrare?"
                             if app_label else "Vuoi registrare il meeting con ClosedRoom?")
            content.setCategoryIdentifier_(CATEGORY_ID)
            request = native.UNNotificationRequest.requestWithIdentifier_content_trigger_(
                NOTIFICATION_PREFIX + candidate_id, content, None
            )
            self._center.addNotificationRequest_withCompletionHandler_(
                request, lambda error: None
            )
        run_on_main_thread(deliver)
        return True

    def dismiss(self, candidate_id: str) -> None:
        if self._center:
            self._center.removeDeliveredNotificationsWithIdentifiers_(
                [NOTIFICATION_PREFIX + candidate_id]
            )
            self._center.removePendingNotificationRequestsWithIdentifiers_(
                [NOTIFICATION_PREFIX + candidate_id]
            )

    def stop(self) -> None:
        if self._center is None:
            return
        from local_asr_server.window import run_on_main_thread
        def close():
            if self._center and self._delegate:
                self._center.setDelegate_(None)
            self._delegate = None
            self._center = None
        run_on_main_thread(close, wait=True)
