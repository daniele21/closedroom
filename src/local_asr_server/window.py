"""
window.py — Native macOS WKWebView Window Wrapper for ClosedRoom.

This module provides a native NSWindow hosting a WKWebView using PyObjC
to render the ClosedRoom web interface. It runs within the main Cocoa event
loop managed by the status-bar menu app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import objc
from AppKit import (
    NSApplication,
    NSApplicationDidBecomeActiveNotification,
    NSBackingStoreBuffered,
    NSNotificationCenter,
    NSObject,
    NSScreen,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSPanel,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSFloatingWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSColor,
    NSView,
    NSViewMinYMargin,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
)
from Foundation import NSURL, NSURLRequest

logger = logging.getLogger(__name__)

# Load WebKit framework dynamically via PyObjC
try:
    objc.loadBundle(
        "WebKit",
        globals(),
        bundle_path="/System/Library/Frameworks/WebKit.framework",
    )
    WKWebView = objc.lookUpClass("WKWebView")
    _WEBKIT_AVAILABLE = True
except Exception as exc:
    logger.error("Failed to load WebKit framework: %s", exc)
    _WEBKIT_AVAILABLE = False
    WKWebView = None


class ClosedRoomWindowDelegate(NSObject):
    """Delegate for the ClosedRoom window to handle window lifecycle events."""

    def initWithWindowManager_(self, manager: ClosedRoomWindowManager) -> ClosedRoomWindowDelegate:
        self = objc.super(ClosedRoomWindowDelegate, self).init()
        if self:
            self._manager = manager
        return self

    def windowShouldClose_(self, sender: objc.objc_object) -> bool:
        """Intercept the window close button and hide the window instead."""
        logger.info("Window close intercepted. Hiding window.")
        if self._manager.window:
            self._manager.window.orderOut_(None)
        return False  # Return False to prevent actual window destruction


class ClosedRoomActivationObserver(NSObject):
    """Observer for app activation notifications (e.g. clicking the Dock icon)."""

    def initWithCallback_(self, callback: Callable[[], None]) -> ClosedRoomActivationObserver:
        self = objc.super(ClosedRoomActivationObserver, self).init()
        if self:
            self._callback = callback
        return self

    def appDidBecomeActive_(self, notification: objc.objc_object) -> None:
        """Callback triggered when the application becomes active."""
        logger.info("App became active. Re-opening window.")
        self._callback()


class DragHandleView(NSView):
    """A transparent custom NSView subclass overlaying the WKWebView to enable window dragging."""

    def mouseDownCanMoveWindow(self) -> bool:
        return True

    def acceptsFirstMouse_(self, event) -> bool:
        return True


class ClosedRoomWindowManager:
    """Manages the lifecycle and state of the native WKWebView application window."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.window: Optional[NSWindow] = None
        self.webview: Optional[objc.objc_object] = None
        self.overlay_window: Optional[NSPanel] = None
        self.overlay_webview: Optional[objc.objc_object] = None
        self._delegate: Optional[ClosedRoomWindowDelegate] = None
        self._observer: Optional[ClosedRoomActivationObserver] = None
        self._key_event_monitor: Optional[objc.objc_object] = None

    def show(self) -> None:
        """Show the native window, creating it if it doesn't exist yet."""
        if not _WEBKIT_AVAILABLE or WKWebView is None:
            logger.error("Cannot show window: WebKit is not available.")
            return

        if not self.window:
            self._create_window()

        if self.window:
            self.window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def load_url(self, url: str) -> None:
        """Load a new URL into the webview."""
        self.url = url
        if self.webview:
            ns_url = NSURL.URLWithString_(url)
            request = NSURLRequest.requestWithURL_(ns_url)
            self.webview.loadRequest_(request)
            logger.info("WebView loading URL: %s", url)

    def evaluate_js(self, js_code: str) -> None:
        """Evaluate JavaScript in the webview on the main thread."""
        if not self.webview:
            return
        
        def _eval():
            if self.webview:
                self.webview.evaluateJavaScript_completionHandler_(js_code, None)
        
        run_on_main_thread(_eval)

    def _dispatch_keyboard_event_to_webview(self, *, key: str, code: str, meta_key: bool = False) -> None:
        """Bridge an AppKit key event into the focused DOM path of the main WKWebView.

        ClosedRoom owns app-level keyboard commands at the native window boundary.
        The bridge intentionally targets the current DOM focus so existing React
        and dialog keyboard handlers remain the canonical behavior owners.
        """
        meta_value = "true" if meta_key else "false"
        js = (
            "(() => {"
            "const target = document.activeElement || document.body || document;"
            "target.dispatchEvent(new KeyboardEvent('keydown', {"
            f"key: {key!r}, code: {code!r}, metaKey: {meta_value}, "
            "bubbles: true, cancelable: true"
            "}));"
            "})();"
        )
        self.evaluate_js(js)

    def _handle_local_key_event(self, event):
        """Route app-local shortcuts through AppKit before WKWebView delivery."""
        if not self.window or not self.window.isKeyWindow():
            return event

        modifiers = int(event.modifierFlags())
        characters = str(event.charactersIgnoringModifiers() or "").lower()
        key_code = int(event.keyCode())

        if modifiers & NSEventModifierFlagCommand and characters == "k":
            self._dispatch_keyboard_event_to_webview(key="k", code="KeyK", meta_key=True)
        elif key_code == 53:  # Escape
            self._dispatch_keyboard_event_to_webview(key="Escape", code="Escape")

        # Preserve the normal AppKit/WebKit path for real keyboard events. The
        # bridge is additive and idempotent for the existing open/close handlers.
        return event

    def _install_local_key_monitor(self) -> None:
        """Install one bounded app-local key monitor for the main window."""
        if self._key_event_monitor is not None:
            return
        self._key_event_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown,
            self._handle_local_key_event,
        )

    def show_loading(self) -> None:
        """Display a premium loading screen inside the webview."""
        if not self.webview:
            return

        loading_html = """
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>ClosedRoom</title>
          <style>
            body {
              background: radial-gradient(circle at center, #1e1e24 0%, #121214 100%);
              color: #f3f4f6;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
              display: flex;
              flex-direction: column;
              align-items: center;
              justify-content: center;
              height: 100vh;
              margin: 0;
              overflow: hidden;
            }
            .container {
              text-align: center;
              animation: fadeIn 0.8s ease-out;
            }
            .spinner {
              width: 50px;
              height: 50px;
              border: 3.5px solid rgba(255, 255, 255, 0.08);
              border-radius: 50%;
              border-top-color: #3b82f6;
              animation: spin 1.2s cubic-bezier(0.5, 0.1, 0.5, 0.9) infinite;
              margin: 0 auto 24px;
              box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);
            }
            .title {
              font-size: 20px;
              font-weight: 600;
              letter-spacing: -0.025em;
              margin-bottom: 8px;
              background: linear-gradient(135deg, #ffffff 0%, #a1a1aa 100%);
              -webkit-background-clip: text;
              -webkit-text-fill-color: transparent;
            }
            .subtitle {
              font-size: 13px;
              color: #71717a;
              font-weight: 400;
            }
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
            @keyframes fadeIn {
              from { opacity: 0; transform: translateY(10px); }
              to { opacity: 1; transform: translateY(0); }
            }
          </style>
        </head>
        <body>
          <div class="container">
            <div class="spinner"></div>
            <div class="title">ClosedRoom</div>
            <div class="subtitle">Avvio del server di trascrizione locale in corso...</div>
          </div>
        </body>
        </html>
        """
        self.webview.loadHTMLString_baseURL_(loading_html, None)
        logger.info("WebView showing loading screen")

    def _create_window(self) -> None:
        """Initialize the NSWindow and add WKWebView."""
        logger.info("Creating native application window...")

        # Styles: Title bar, close, minimize, resize
        style_mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )

        # Default frame dimensions
        rect = ((100, 100), (1024, 768))

        # Create window
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("ClosedRoom")
        self.window.center()

        # Create WKWebView
        content_rect = self.window.contentView().frame()
        self.webview = WKWebView.alloc().initWithFrame_(content_rect)
        self.webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.window.setContentView_(self.webview)
        self._install_local_key_monitor()

        # Display initial loading screen
        self.show_loading()

        # Set Window Delegate (to handle close intercepts)
        self._delegate = ClosedRoomWindowDelegate.alloc().initWithWindowManager_(self)
        self.window.setDelegate_(self._delegate)

        # Register observer for Dock icon reactivations
        self._register_activation_observer()

    def _register_activation_observer(self) -> None:
        """Observe application activation notifications to reopen window on Dock clicks."""
        self._observer = ClosedRoomActivationObserver.alloc().initWithCallback_(self.show)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._observer,
            "appDidBecomeActive:",
            NSApplicationDidBecomeActiveNotification,
            None,
        )

    def show_overlay(self) -> None:
        """Create and show the floating recording overlay panel."""
        if not _WEBKIT_AVAILABLE or WKWebView is None:
            logger.error("Cannot show overlay: WebKit is not available.")
            return

        if not self.overlay_window:
            self._create_overlay_window()

        if self.overlay_window:
            self.overlay_window.makeKeyAndOrderFront_(None)
            logger.info("Showing overlay window.")

    def hide_overlay(self) -> None:
        """Hide the floating recording overlay panel."""
        if self.overlay_window:
            self._save_overlay_position()
            self.overlay_window.orderOut_(None)
            logger.info("Hiding overlay window.")

    def _save_overlay_position(self) -> None:
        if self.overlay_window:
            frame = self.overlay_window.frame()
            x = frame.origin.x
            y = frame.origin.y
            try:
                from local_asr_server.settings import load_settings, save_settings
                settings = load_settings()
                settings["overlay_position"] = {"x": float(x), "y": float(y)}
                save_settings(settings)
                logger.info("Saved overlay position: x=%s, y=%s", x, y)
            except Exception as e:
                logger.warning("Failed to save overlay position: %s", e)

    def set_overlay_size(self, width: int, height: int) -> None:
        """Resize the overlay window panel, keeping top-left corner fixed and animating the transition."""
        if self.overlay_window:
            frame = self.overlay_window.frame()
            old_h = frame.size.height
            new_y = frame.origin.y + old_h - height
            new_frame = ((frame.origin.x, new_y), (width, height))
            self.overlay_window.setFrame_display_animate_(new_frame, True, True)
            logger.info("Resized overlay window to %dx%d", width, height)

    def _create_overlay_window(self) -> None:
        """Initialize the floating NSPanel for recording status monitoring."""
        logger.info("Creating native recording overlay window...")

        # Non-activating panel, borderless, always on top
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        # Place the panel on the active screen visible frame (respecting menu bar and Dock)
        screen = NSScreen.mainScreen()
        screen_frame = screen.visibleFrame()
        screen_w = screen_frame.size.width
        screen_h = screen_frame.size.height
        screen_x = screen_frame.origin.x
        screen_y = screen_frame.origin.y

        # Default compact dimensions
        width = 300
        height = 130

        # Load saved position if available
        saved_pos = None
        try:
            from local_asr_server.settings import load_settings
            settings = load_settings()
            saved_pos = settings.get("overlay_position")
        except Exception:
            pass

        if saved_pos and "x" in saved_pos and "y" in saved_pos:
            x = saved_pos["x"]
            y = saved_pos["y"]
            # Clamp to screen visible frame to avoid being out of bounds
            x = max(screen_x, min(x, screen_x + screen_w - width))
            y = max(screen_y, min(y, screen_y + screen_h - height))
            rect = ((x, y), (width, height))
        else:
            # Position: 40px from right of visible frame, 40px below top of visible frame
            rect = ((screen_x + screen_w - width - 40, screen_y + screen_h - height - 40), (width, height))

        # Create overlay window (NSPanel)
        self.overlay_window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        
        # Configure floating panel behavior
        self.overlay_window.setLevel_(NSFloatingWindowLevel)
        
        # Include FullScreenAuxiliary behaviour (allows panel on full-screen Spaces and Stage Manager)
        try:
            from AppKit import NSWindowCollectionBehaviorFullScreenAuxiliary
            behavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        except ImportError:
            behavior = NSWindowCollectionBehaviorCanJoinAllSpaces | 256  # 256 is FullScreenAuxiliary
            
        self.overlay_window.setCollectionBehavior_(behavior)
        self.overlay_window.setHidesOnDeactivate_(False)
        self.overlay_window.setMovableByWindowBackground_(True) # Allow dragging from anywhere
        self.overlay_window.setHasShadow_(True)
        
        # Make the panel background transparent to support CSS glassmorphism and rounded corners
        self.overlay_window.setOpaque_(False)
        self.overlay_window.setBackgroundColor_(NSColor.clearColor())

        # Create WKWebView
        content_rect = self.overlay_window.contentView().frame()
        self.overlay_webview = WKWebView.alloc().initWithFrame_(content_rect)
        self.overlay_webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        
        # Set transparent webview background (works for WebKit)
        self.overlay_webview.setValue_forKey_(False, "drawsBackground")

        # Set corner radius and masksToBounds for overlay window contentView and webview
        corner_radius = 22.0
        content = self.overlay_window.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(corner_radius)
        content.layer().setMasksToBounds_(True)

        self.overlay_webview.setWantsLayer_(True)
        self.overlay_webview.layer().setCornerRadius_(corner_radius)
        self.overlay_webview.layer().setMasksToBounds_(True)

        self.overlay_window.setContentView_(self.overlay_webview)

        # Add native transparent drag handle above the WKWebView on the top-left area
        drag_handle = DragHandleView.alloc().initWithFrame_(
            ((12, height - 42), (190, 34))
        )
        drag_handle.setAutoresizingMask_(NSViewMinYMargin)
        self.overlay_window.contentView().addSubview_positioned_relativeTo_(
            drag_handle,
            1,  # NSWindowAbove
            None
        )
        self.overlay_drag_handle = drag_handle

        # Load overlay hash route
        ns_url = NSURL.URLWithString_(f"{self.url}/#overlay")
        request = NSURLRequest.requestWithURL_(ns_url)
        self.overlay_webview.loadRequest_(request)
        logger.info("Overlay WebView loading URL: %s/#overlay", self.url)

    def close(self) -> None:
        """Deallocate windows and clean up observers."""
        if self._observer:
            NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
            self._observer = None
        if self._key_event_monitor is not None:
            NSEvent.removeMonitor_(self._key_event_monitor)
            self._key_event_monitor = None
        if self.window:
            self.window.setDelegate_(None)
            self.window.close()
            self.window = None
        if self.overlay_window:
            self._save_overlay_position()
            self.overlay_window.close()
            self.overlay_window = None
        self._delegate = None
        self.webview = None
        self.overlay_webview = None


class MainThreadHelper(NSObject):
    """Helper class to run Python callables on the main macOS thread."""

    def runCallback_(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            logger.exception("Error executing callback on main thread: %s", exc)


_main_thread_helper = MainThreadHelper.alloc().init()


def run_on_main_thread(callback: Callable[[], None], wait: bool = False) -> None:
    """Run a Python callback on the macOS main thread using PyObjC."""
    _main_thread_helper.performSelectorOnMainThread_withObject_waitUntilDone_(
        b"runCallback:",
        callback,
        wait,
    )
