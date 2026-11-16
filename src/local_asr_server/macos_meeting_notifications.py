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



def _native_framework():
    """Load the wrapper with block signatures and delegate protocol metadata.

    Loading Objective-C classes alone loses completion-handler signatures,
    breaking both authorization queries and permission requests in frozen apps.
    The app extra and bundle spec must include this native bridge.
    """
    import UserNotifications
    return UserNotifications

def needs_initial_notification_consent(*, enabled: bool, authorization: str,
                                       requested_this_launch: bool) -> bool:
    """Ask macOS once for user consent when default-on detection first starts.

    macOS remains the authorization owner: no notification is sent without
    granted permission, and an explicit saved Off is never overridden.
    """
    return enabled and authorization == "not_determined" and not requested_this_launch


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
        self._last_error: str | None = None

    @property
    def authorization(self) -> str:
        return self._authorization

    @property
    def available(self) -> bool:
        return self._center is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def refresh_authorization(self) -> None:
        """Refresh the OS notification permission state, never infer success."""
        if not self._center:
            return
        from local_asr_server.window import run_on_main_thread
        def query():
            try:
                self._center.getNotificationSettingsWithCompletionHandler_(
                    lambda state: self._set_authorization(int(state.authorizationStatus()))
                )
            except Exception:
                self._last_error = "notification_settings_query_failed"
                self._authorization = "unknown"
        try:
            run_on_main_thread(query)
        except Exception:
            self._last_error = "notification_settings_query_failed"
            self._authorization = "unknown"


    def start(self) -> bool:
        if self._center is not None:
            return True
        if sys.platform != "darwin" and self._native is None:
            self._authorization = "unsupported"
            return False
        try:
            native = self._native or _native_framework()
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
                self._authorization = "checking"
                self.refresh_authorization()

            run_on_main_thread(configure, wait=True)
            return self._center is not None
        except Exception as exc:
            # Missing framework/bridge must never crash the menu-bar app.
            self._last_error = f"notification_center_setup_failed:{type(exc).__name__}"
            self._authorization = "unsupported"
            return False

    def _set_authorization(self, status: int) -> None:
        # UNAuthorizationStatus: notDetermined 0, denied 1, authorized 2, provisional 3.
        self._authorization = {0: "not_determined", 1: "denied",
                               2: "authorized", 3: "authorized", 4: "authorized"}.get(status, "unknown")
        if self._authorization != "unknown" and self._last_error == "notification_settings_query_failed":
            self._last_error = None

    def request_authorization(self) -> bool:
        """Request explicit macOS authorization, never infer permission from defaults."""
        if not self.start():
            return False
        from local_asr_server.window import run_on_main_thread

        def request():
            try:
                native = self._native or _native_framework()
                options = int(native.UNAuthorizationOptionAlert) | int(native.UNAuthorizationOptionSound)
                def completed(granted, error):
                    if error is not None:
                        self._authorization = "unknown"
                        self._last_error = "notification_permission_request_failed"
                    else:
                        self._authorization = "authorized" if granted else "denied"
                        self._last_error = None
                self._center.requestAuthorizationWithOptions_completionHandler_(options, completed)
            except Exception:
                self._authorization = "unknown"
                self._last_error = "notification_permission_request_failed"
        try:
            run_on_main_thread(request)
        except Exception:
            self._authorization = "unknown"
            self._last_error = "notification_permission_request_failed"
            return False
        return True

    def notify(self, candidate_id: str, *, app_label: str | None = None,
               on_result: Callable[[bool], None] | None = None) -> bool:
        """Queue an OS notification and asynchronously acknowledge its submission.

        True means only that dispatch was scheduled, not that macOS displayed a
        banner. The callback receives the OS submission result; Focus mode and
        user presentation preferences can still suppress the visible banner.
        """
        if not self._center or self._authorization != "authorized":
            return False
        from local_asr_server.window import run_on_main_thread

        def complete(error) -> None:
            self._record_delivery_error(error)
            if on_result is not None:
                on_result(error is None)

        def deliver() -> None:
            try:
                native = self._native or _native_framework()
                content = native.UNMutableNotificationContent.alloc().init()
                content.setTitle_("Una chiamata in corso?")
                content.setBody_(f"{app_label} sta utilizzando il microfono. Vuoi registrare?"
                                 if app_label else "Vuoi registrare il meeting con ClosedRoom?")
                content.setCategoryIdentifier_(CATEGORY_ID)
                request = native.UNNotificationRequest.requestWithIdentifier_content_trigger_(
                    NOTIFICATION_PREFIX + candidate_id, content, None
                )
                self._center.addNotificationRequest_withCompletionHandler_(request, complete)
            except Exception:
                self._record_delivery_error(RuntimeError("native_submit_failed"))
                if on_result is not None:
                    on_result(False)

        try:
            run_on_main_thread(deliver)
        except Exception:
            self._record_delivery_error(RuntimeError("dispatch_failed"))
            return False
        return True

    def _record_delivery_error(self, error) -> None:
        if error is not None:
            self._last_error = "notification_delivery_failed"
        elif self._last_error == "notification_delivery_failed":
            self._last_error = None

    def dismiss(self, candidate_id: str) -> None:
        if not self._center:
            return
        try:
            from local_asr_server.window import run_on_main_thread

            def remove() -> None:
                self._center.removeDeliveredNotificationsWithIdentifiers_(
                    [NOTIFICATION_PREFIX + candidate_id]
                )
                self._center.removePendingNotificationRequestsWithIdentifiers_(
                    [NOTIFICATION_PREFIX + candidate_id]
                )
            run_on_main_thread(remove)
        except Exception:
            self._last_error = "notification_dismiss_failed"

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
