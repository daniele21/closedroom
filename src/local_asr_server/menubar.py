"""
menubar.py — ClosedRoom macOS Menu Bar App.

This module is the main entry point for the ClosedRoom.app bundle.
It runs the FastAPI server in a background thread and exposes a rumps
status-bar icon with quick actions.

Usage (dev):
    python -m local_asr_server.menubar
    local-asr app   ← via cli.py

Usage (bundle):
    Launched automatically by PyInstaller when the .app opens.
"""

from __future__ import annotations

import os
import sys
import logging
import json
import socket
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Optional

# ── PyInstaller bundle setup (must run before any MLX or certifi import) ──────
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]

    # 1. SSL certificates — required for Hugging Face model downloads.
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass

    # 2. PATH fix — mlx_whisper (via OpenAI Whisper's audio loader) calls
    #    ffmpeg as a subprocess.  The bundled ffmpeg lives in _MEIPASS
    #    (Contents/Resources/) which is not on the default PATH inside a
    #    sandboxed .app.  Prepend it so `shutil.which("ffmpeg")` and direct
    #    subprocess calls succeed.
    _existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{_meipass}:{_existing_path}"

    # MLX is intentionally not preloaded in the menu/API process. Frozen AI
    # workers preload their own MLX runtime through build_assets/hooks/pyi_rth_mlx.py.

from local_asr_server.window import ClosedRoomWindowManager
from local_asr_server.app_identity import get_app_identity
from local_asr_server.paths import get_brand_asset_path
from local_asr_server.runtime.models import (
    DEFAULT_API_PORT,
    DEFAULT_DEV_RELOAD_PORT,
    DEFAULT_LOCAL_LLM_PORT,
    LOCAL_SERVICE_HOST,
)
from local_asr_server.runtime.port_manager import (
    PortInUseError,
    clear_api_runtime,
    prepare_api_port,
    register_api_runtime,
)

logger = logging.getLogger(__name__)

# ── Lazy import of rumps so the module can still be imported on systems
#    where rumps is not installed (e.g. in CI or Linux dev environments).
try:
    import rumps
    _RUMPS_AVAILABLE = True
except ImportError:
    _RUMPS_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

MENU_BAR_ICON_ASSET = "closedroom-microphone-mark.png"
MENU_BAR_ICON_SOURCE = "design/assets/brand/closedroom-microphone-mark.png"

STATUS_ITEM_STATES = {
    "idle": "ClosedRoom — pronto",
    "recording": "ClosedRoom — registrazione in corso",
    "transcribing": "ClosedRoom — elaborazione in corso",
    "error": "ClosedRoom — non disponibile",
}


# ── Server thread ─────────────────────────────────────────────────────────────

class _ServerThread(threading.Thread):
    """
    Runs the FastAPI/uvicorn server in a daemon thread so it exits when
    the main menu bar process exits.
    """

    def __init__(self, app_instance: ClosedRoomApp, port: int) -> None:
        super().__init__(name="closedroom-server", daemon=True)
        self.app_instance = app_instance
        self.port = port
        self._server: Optional[object] = None
        self._app: Optional[object] = None
        self.ready = threading.Event()

    def run(self) -> None:
        import uvicorn
        from local_asr_server.server import create_app
        from local_asr_server.settings import load_settings
        from local_asr_server.paths import APP_NAME

        # If this exact app build is already serving the selected port, reuse it.
        status = _get_server_status(self.port)
        if _is_reusable_server(status):
            logger.info("A compatible server is already running on port %s. Reusing it.", self.port)
            self.ready.set()
            return

        app = create_app(
            recordings_dir=None,
        )
        self._app = app
        app.state.window_manager = self.app_instance.window_manager
        app.state.menubar_controller = self.app_instance
        app.state.capture_manager.set_screenshot_exclusion_provider(
            self.app_instance.window_manager.screenshot_exclusion_window_ids
        )

        uvicorn_log_level = os.environ.get("CLOSEDROOM_LOG_LEVEL", "info").lower()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level=uvicorn_log_level,
            loop="asyncio",
        )
        self._server = uvicorn.Server(config)

        # Signal that startup is complete so the menu bar can update its icon
        original_startup = self._server.startup

        async def _startup_with_signal(sockets=None):
            await original_startup(sockets=sockets)
            self.ready.set()

        self._server.startup = _startup_with_signal
        self._server.run()

    def stop(self) -> None:
        """Request graceful server shutdown."""
        runtime_services = getattr(getattr(self._app, "state", None), "runtime_services", None)
        if runtime_services is not None:
            try:
                runtime_services.shutdown()
            except Exception as exc:
                logger.warning("Failed to shut down managed runtime services: %s", exc)
        if self._server:
            self._server.should_exit = True


# ── Health check ──────────────────────────────────────────────────────────────

def _build_app_url(port: int) -> str:
    return f"http://{LOCAL_SERVICE_HOST}:{port}"


def _check_server_health(port: int) -> bool:
    """Return True if the local server is responding."""
    return bool(_get_server_status(port).get("ok"))


def _get_server_status(port: int) -> dict:
    """Return the parsed /health JSON or an empty dict on failure."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{_build_app_url(port)}/health", timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def _request_api_json(
    port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 2.0,
    bearer_token: str | None = None,
) -> dict:
    """Call ClosedRoom's authenticated-loopback-equivalent local API from the app shell."""
    import urllib.request
    data = None
    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{_build_app_url(port)}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((LOCAL_SERVICE_HOST, port)) == 0


def _is_reusable_server(status: dict) -> bool:
    """Return True only for a healthy server that matches this app identity."""
    if not status.get("ok"):
        return False

    current = get_app_identity()
    if not current.bundled:
        return True

    return (
        status.get("bundle_identifier") == current.bundle_identifier
        and status.get("bundle_display_name") == current.display_name
        and status.get("app_version") == current.version
    )


def _select_app_port() -> int:
    """
    Prefer the standard app port, but do not silently reuse a stale bundle server.

    This lets a versioned build run even while an older ``ClosedRoom.app`` still
    owns the default port.
    """
    candidate_ports = [DEFAULT_API_PORT]
    candidate_ports.extend(
        port
        for port in range(DEFAULT_API_PORT + 2, DEFAULT_API_PORT + 32)
        if port not in {DEFAULT_DEV_RELOAD_PORT, DEFAULT_LOCAL_LLM_PORT}
    )

    for port in candidate_ports:
        try:
            prepare_api_port(port)
            register_api_runtime(port)
            return port
        except PortInUseError as exc:
            logger.warning("%s Trying another port.", exc)

    raise RuntimeError("No available local port found for ClosedRoom.")


# ── LaunchAgent helpers (forward to launchd module) ───────────────────────────

def _toggle_launch_agent(menu_item) -> None:
    """Install or uninstall the LaunchAgent depending on current state."""
    try:
        from local_asr_server.launchd import (
            is_launch_agent_installed,
            install_launch_agent,
            uninstall_launch_agent,
        )
        if is_launch_agent_installed():
            uninstall_launch_agent()
            menu_item.title = "Avvia al login"
            rumps.notification("ClosedRoom", "", "Auto-start disabilitato.")
        else:
            install_launch_agent()
            menu_item.title = "✓ Avvia al login"
            rumps.notification("ClosedRoom", "", "ClosedRoom si avvierà al login.")
    except Exception as exc:
        logger.error("Failed to toggle launch agent: %s", exc)
        rumps.alert("Errore", f"Impossibile modificare l'auto-start:\n{exc}")


# ── Main App ──────────────────────────────────────────────────────────────────

class ClosedRoomApp(rumps.App):
    """
    macOS application for ClosedRoom.

    Provides a status-bar icon with quick actions and launches a native NSWindow
    hosting a WKWebView. The FastAPI server is run in a background thread.
    """

    def __init__(self) -> None:
        # rumps owns the NSStatusItem lifecycle. Use the canonical transparent
        # ClosedRoom microphone mark directly rather than a synthetic SF Symbol.
        self._menu_bar_icon_path = get_brand_asset_path(MENU_BAR_ICON_ASSET)
        self._status_icon_state = "idle"
        self._status_item_ready = False
        self._status_item_last_error: str | None = None
        self._status_item_repair_count = 0
        icon_path = str(self._menu_bar_icon_path) if self._menu_bar_icon_path.is_file() else None
        super().__init__(
            name="ClosedRoom",
            title=None if icon_path else "CR",
            icon=icon_path,
            template=bool(icon_path),
            quit_button=None,  # we provide our own Esci item
        )
        self._ensure_status_item_visible()

        # Build the menu
        self._build_menu()

        self.app_port = _select_app_port()
        self.app_url = _build_app_url(self.app_port)

        # Initialize the window manager
        self.window_manager = ClosedRoomWindowManager(self.app_url)

        # Start the server
        self._server_thread = _ServerThread(self, self.app_port)
        self._server_thread.start()

        # Poll until server is ready, then update icon
        threading.Thread(target=self._wait_for_server, daemon=True).start()

        # Delay the window show slightly to run after Cocoa event loop is active
        self._show_timer = rumps.Timer(self._initial_show, 0.1)
        self._show_timer.start()

        # Start global shortcuts listener
        self._start_shortcuts_listener()

    def _initial_show(self, timer: rumps.Timer) -> None:
        """One-shot timer to show the window once the Cocoa run loop is active."""
        timer.stop()
        # Do not runtime-subclass NSStatusBarButton here. That old file-drop
        # hook mutated the same native control that must remain visible.
        self._ensure_status_item_visible()
        self.window_manager.show()

    def _ensure_status_item_visible(self) -> None:
        """Re-assert the canonical menu-bar item on the Cocoa main thread."""
        try:
            import AppKit

            status_item = self._nsapp.nsstatusitem
            button = status_item.button()
            if status_item is None or button is None:
                raise RuntimeError("NSStatusItem is unavailable")
            if not self._menu_bar_icon_path.is_file():
                raise FileNotFoundError(f"menu-bar icon missing: {self._menu_bar_icon_path}")

            image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(self._menu_bar_icon_path))
            if image is None:
                raise RuntimeError(f"unable to load menu-bar icon: {self._menu_bar_icon_path}")

            # The source asset has transparent background. Template rendering is
            # the macOS-native treatment that keeps it legible in light/dark menu bars.
            image.setTemplate_(True)
            image.setSize_((18.0, 18.0))
            self._status_item_image = image  # retain the NSImage for the item lifetime

            if hasattr(status_item, "setAutosaveName_"):
                status_item.setAutosaveName_("ClosedRoomMenuBarItem")
            if hasattr(status_item, "setVisible_"):
                status_item.setVisible_(True)
            status_item.setLength_(AppKit.NSSquareStatusItemLength)
            button.setImage_(image)
            button.setImagePosition_(AppKit.NSImageOnly)
            button.setTitle_("")
            button.setToolTip_(STATUS_ITEM_STATES.get(self._status_icon_state, STATUS_ITEM_STATES["idle"]))

            self._status_item_ready = True
            self._status_item_last_error = None
        except Exception as exc:
            self._status_item_ready = False
            self._status_item_last_error = str(exc)
            logger.exception("Failed to render ClosedRoom menu-bar item: %s", exc)
            try:
                status_item = self._nsapp.nsstatusitem
                if hasattr(status_item, "setVisible_"):
                    status_item.setVisible_(True)
                status_item.setLength_(34.0)
                button = status_item.button()
                button.setImage_(None)
                button.setTitle_("CR")
                button.setToolTip_(STATUS_ITEM_STATES.get(self._status_icon_state, "ClosedRoom"))
            except Exception:
                logger.exception("Failed to render text fallback for menu-bar item")

    def _set_status_icon(self, state: str) -> None:
        """Keep the brand mark stable while updating its accessible state label."""
        self._status_icon_state = state if state in STATUS_ITEM_STATES else "idle"
        if not self._status_item_ready:
            self._ensure_status_item_visible()
            return
        try:
            self._nsapp.nsstatusitem.button().setToolTip_(STATUS_ITEM_STATES[self._status_icon_state])
        except Exception as exc:
            self._status_item_ready = False
            self._status_item_last_error = str(exc)
            self._ensure_status_item_visible()

    def menu_bar_status(self) -> dict:
        """Return a truthful native-shell snapshot for Settings diagnostics."""
        from local_asr_server.window import run_on_main_thread

        snapshot: dict = {}

        def capture() -> None:
            try:
                status_item = self._nsapp.nsstatusitem
                button = status_item.button()
                visible = bool(status_item.isVisible()) if hasattr(status_item, "isVisible") else self._status_item_ready
                snapshot.update({
                    "available": True,
                    "visible": visible,
                    "icon_loaded": bool(button.image()),
                    "state": self._status_icon_state,
                    "icon_asset": MENU_BAR_ICON_SOURCE,
                    "repair_count": self._status_item_repair_count,
                    "last_error": self._status_item_last_error,
                })
            except Exception as exc:
                snapshot.update({
                    "available": False,
                    "visible": False,
                    "icon_loaded": False,
                    "state": self._status_icon_state,
                    "icon_asset": MENU_BAR_ICON_SOURCE,
                    "repair_count": self._status_item_repair_count,
                    "last_error": str(exc),
                })

        run_on_main_thread(capture, wait=True)
        return snapshot

    def repair_menu_bar(self) -> dict:
        """Re-assert visibility and the canonical icon, then report the result."""
        from local_asr_server.window import run_on_main_thread

        self._status_item_repair_count += 1
        run_on_main_thread(self._ensure_status_item_visible, wait=True)
        return self.menu_bar_status()

    # ── Menu construction ──────────────────────────────────────────────────

    def _build_menu(self) -> None:
        """Construct a meeting-aware menu instead of exposing server internals."""
        from local_asr_server.launchd import is_launch_agent_installed

        launch_agent_title = (
            "✓ Avvia al login"
            if is_launch_agent_installed()
            else "Avvia al login"
        )

        self._meeting_status_item = rumps.MenuItem("Avvio…")
        self._start_item = rumps.MenuItem("＋ Nuovo meeting", callback=self._start_recording)
        self._recent_item = rumps.MenuItem("Recenti")
        self._recent_signature: tuple[tuple[str, str], ...] = ()
        empty_recent = rumps.MenuItem("Nessun meeting recente")
        empty_recent.set_callback(None)
        self._recent_item.add(empty_recent)
        self._add_note_item = rumps.MenuItem("✎ Aggiungi nota", callback=self._add_quick_note)
        self._screenshot_item = rumps.MenuItem("▣ Screenshot", callback=self._take_screenshot)
        self._open_controls_item = rumps.MenuItem("Apri controlli registrazione", callback=self._open_recording_controls)
        self._stop_item = rumps.MenuItem("■ Ferma registrazione", callback=self._stop_recording)
        self._copy_transcript_item = rumps.MenuItem("Copia ultima trascrizione", callback=self._copy_last_transcription)

        self.menu = [
            rumps.MenuItem("Apri ClosedRoom", callback=self._open_window),
            self._meeting_status_item,
            rumps.separator,
            self._start_item,
            self._recent_item,
            self._add_note_item,
            self._screenshot_item,
            self._open_controls_item,
            self._stop_item,
            rumps.separator,
            self._copy_transcript_item,
            rumps.separator,
            rumps.MenuItem("Preferenze…", callback=self._open_preferences),
            rumps.MenuItem(launch_agent_title, callback=_toggle_launch_agent),
            rumps.separator,
            rumps.MenuItem("Esci", callback=self._quit),
        ]

        self._set_recording_actions(recording=False, available=False)

    def _refresh_api_session(self) -> None:
        session = _request_api_json(self.app_port, "/v1/session")
        self._api_bearer_token = session.get("token")

    def _api_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        timeout: float = 2.0,
    ) -> dict:
        import urllib.error

        if not hasattr(self, "_api_bearer_token"):
            self._refresh_api_session()
        try:
            return _request_api_json(
                self.app_port,
                path,
                method=method,
                payload=payload,
                timeout=timeout,
                bearer_token=self._api_bearer_token,
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
            self._refresh_api_session()
            return _request_api_json(
                self.app_port,
                path,
                method=method,
                payload=payload,
                timeout=timeout,
                bearer_token=self._api_bearer_token,
            )

    def _refresh_recent_meetings(self) -> None:
        try:
            payload = self._api_json("/v1/recordings?limit=3")
        except Exception:
            return
        items = [
            item
            for item in (payload.get("items") or [])
            if isinstance(item, dict) and item.get("id")
        ][:3]
        signature = tuple(
            (str(item["id"]), str(item.get("title") or "Meeting"))
            for item in items
        )
        if signature == self._recent_signature:
            return

        self._recent_signature = signature
        self._recent_item.clear()
        if not items:
            empty = rumps.MenuItem("Nessun meeting recente")
            empty.set_callback(None)
            self._recent_item.add(empty)
            return

        for item in items:
            recording_id = str(item["id"])
            title = str(item.get("title") or "Meeting").strip() or "Meeting"
            menu_item = rumps.MenuItem(title[:64])

            def open_recent(_, rid=recording_id):
                self.window_manager.show()
                self.window_manager.load_url(f"{self.app_url}/#meeting/{rid}")

            menu_item.set_callback(open_recent)
            self._recent_item.add(menu_item)

    def _set_recording_actions(self, *, recording: bool, available: bool = True) -> None:
        self._start_item.set_callback(self._start_recording if available and not recording else None)
        self._add_note_item.set_callback(self._add_quick_note if available and recording else None)
        self._screenshot_item.set_callback(self._take_screenshot if available and recording else None)
        self._open_controls_item.set_callback(self._open_recording_controls if available and recording else None)
        self._stop_item.set_callback(self._stop_recording if available and recording else None)
        self._copy_transcript_item.set_callback(self._copy_last_transcription if available else None)

    # ── Server lifecycle ───────────────────────────────────────────────────

    def _wait_for_server(self) -> None:
        """Wait for local services, then expose user-facing ready state."""
        self._server_thread.ready.wait(timeout=60)
        import time
        for _ in range(20):
            if _check_server_health(self.app_port):
                break
            time.sleep(0.5)

        from local_asr_server.window import run_on_main_thread

        def update_ui():
            self._update_status_item("Pronto")
            self._set_recording_actions(recording=False, available=True)
            self.window_manager.load_url(self.app_url)

        run_on_main_thread(update_ui)

    @rumps.timer(5)
    def _refresh_status(self, _) -> None:
        """Project canonical recording/job state into the menu bar."""
        status = _get_server_status(self.app_port)
        if not status:
            self._set_status_icon("error")
            self._update_status_item("ClosedRoom non disponibile")
            self._set_recording_actions(recording=False, available=False)
            return

        server_status = status.get("status", "idle")
        self._refresh_recent_meetings()

        if server_status == "recording":
            self._set_status_icon("recording")
            try:
                active = self._api_json("/v1/recordings/active")
            except Exception:
                active = {}
            title = str(active.get("title") or "Meeting").strip()
            self._update_status_item(f"● {title}")
            self._set_recording_actions(recording=True, available=True)
        elif server_status == "transcribing":
            self._set_status_icon("transcribing")
            self._update_status_item("Preparazione in corso…")
            self._set_recording_actions(recording=False, available=False)
            self._copy_transcript_item.set_callback(self._copy_last_transcription)
        else:
            self._set_status_icon("idle")
            self._update_status_item("Pronto")
            self._set_recording_actions(recording=False, available=True)

    def _update_status_item(self, text: str) -> None:
        self._meeting_status_item.title = text

    # ── Drag and drop support ──────────────────────────────────────────────

    def _setup_drag_and_drop(self) -> None:
        """Configure drag and drop support on the status bar button."""
        try:
            import objc
            import AppKit

            button = self._nsapp.nsstatusitem.button()

            global DragStatusButton
            class DragStatusButton(objc.lookUpClass("NSStatusBarButton")):
                def draggingEntered_(self, sender):
                    pb = sender.draggingPasteboard()
                    types = pb.types()
                    if AppKit.NSFilenamesPboardType in types:
                        return AppKit.NSDragOperationCopy
                    return AppKit.NSDragOperationNone

                def performDragOperation_(self, sender):
                    pb = sender.draggingPasteboard()
                    filenames = pb.propertyListForType_(AppKit.NSFilenamesPboardType)
                    if filenames:
                        file_path = filenames[0]
                        import threading
                        threading.Thread(
                            target=self.app_instance.transcribe_dropped_file,
                            args=(file_path,),
                            daemon=True
                        ).start()
                        return True
                    return False

            DragStatusButton.app_instance = self
            button.__class__ = DragStatusButton
            button.registerForDraggedTypes_([AppKit.NSFilenamesPboardType])
            logger.info("Drag and drop configured successfully.")
        except Exception as exc:
            logger.error("Failed to setup drag and drop: %s", exc)

    def transcribe_dropped_file(self, file_path: str) -> None:
        """Transcribe a dropped audio file in the background."""
        import urllib.request
        import urllib.parse
        import json
        from AppKit import NSPasteboard, NSStringPboardType

        from local_asr_server.window import run_on_main_thread

        def set_status_transcribing():
            self._set_status_icon("transcribing")
            self._update_status_item("Trascrizione da drop… ⏳")
            self._start_item.set_callback(None)
            self._stop_item.set_callback(None)

        run_on_main_thread(set_status_transcribing)

        try:
            url = f"{self.app_url}/v1/audio/transcriptions/path"
            req_data = json.dumps({"file": file_path}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            # 10 minutes timeout for transcriptions
            with urllib.request.urlopen(req, timeout=600) as resp:
                res_data = json.loads(resp.read())
                text = res_data.get("text", "")

                if text.strip():
                    pb = NSPasteboard.generalPasteboard()
                    pb.clearContents()
                    pb.declareTypes_owner_([NSStringPboardType], None)
                    pb.setString_forType_(text, NSStringPboardType)

                    rumps.notification(
                        "ClosedRoom",
                        "Trascrizione completata 🎉",
                        f"Il testo di {Path(file_path).name} è stato copiato negli appunti."
                    )
                else:
                    rumps.notification(
                        "ClosedRoom",
                        "Trascrizione completata",
                        "La trascrizione del file è vuota."
                    )
        except Exception as exc:
            logger.error("Failed to transcribe dropped file: %s", exc)
            rumps.notification(
                "ClosedRoom",
                "Errore Trascrizione ❌",
                f"Impossibile trascrivere {Path(file_path).name}: {exc}"
            )
        finally:
            def refresh():
                self._refresh_status(None)
            run_on_main_thread(refresh)

    # ── Global keyboard shortcuts ──────────────────────────────────────────

    def _start_shortcuts_listener(self) -> None:
        """Register core meeting hotkeys natively, then optional legacy shortcuts."""
        self._native_hotkeys = None
        try:
            from local_asr_server.macos_hotkeys import (
                CarbonHotKeyManager,
                DEFAULT_MEETING_HOTKEYS,
                HotKeySpec,
            )

            toggle_key, toggle_mods, toggle_label = DEFAULT_MEETING_HOTKEYS["toggle_recording"]
            note_key, note_mods, note_label = DEFAULT_MEETING_HOTKEYS["add_note"]
            shot_key, shot_mods, shot_label = DEFAULT_MEETING_HOTKEYS["screenshot"]
            manager = CarbonHotKeyManager([
                HotKeySpec(1, toggle_key, toggle_mods, toggle_label, self._shortcut_toggle_recording),
                HotKeySpec(2, note_key, note_mods, note_label, self._shortcut_add_note),
                HotKeySpec(3, shot_key, shot_mods, shot_label, self._shortcut_take_screenshot),
            ])
            failures = manager.start()
            self._native_hotkeys = manager
            if failures:
                unavailable = ", ".join(failures)
                logger.warning("Some native meeting shortcuts are unavailable: %s", unavailable)
                rumps.notification(
                    "ClosedRoom",
                    "Shortcut non disponibile",
                    f"{unavailable}. Le azioni restano disponibili dalla menu bar.",
                )
        except Exception as exc:
            logger.warning("Native meeting shortcuts unavailable: %s", exc)
            rumps.notification(
                "ClosedRoom",
                "Shortcut globali non disponibili",
                "Puoi continuare a usare le azioni dalla menu bar.",
            )

        # Clipboard transcription/paste are separate power tools. Paste still
        # synthesizes keyboard input, so only these legacy actions retain the
        # Accessibility-gated pynput path.
        from local_asr_server.macos_permissions import accessibility_status

        permission = accessibility_status()
        if not permission.get("trusted"):
            logger.info(
                "Legacy clipboard shortcuts disabled because Accessibility permission is not granted; "
                "core meeting shortcuts use native registration instead."
            )
            return

        def run_listener():
            try:
                from pynput import keyboard

                shortcuts = {
                    "<cmd>+<shift>+t": self._shortcut_transcribe_clipboard,
                    "<cmd>+<shift>+v": self._shortcut_paste_last_transcription,
                }

                logger.info("Starting Accessibility-gated legacy clipboard shortcuts...")
                with keyboard.GlobalHotKeys(shortcuts) as listener:
                    listener.join()
            except Exception as exc:
                logger.error("Legacy clipboard shortcut listener failed: %s", exc)

        threading.Thread(target=run_listener, daemon=True).start()

    def _shortcut_toggle_recording(self) -> None:
        """Toggle recording through the canonical recording controller."""
        status = _get_server_status(self.app_port)
        server_status = status.get("status", "idle")
        if server_status == "recording":
            self.window_manager.evaluate_js("RecordingController.stop()")
            rumps.notification("ClosedRoom", "Registrazione", "Salvataggio del meeting in corso…")
        elif server_status == "idle":
            self.window_manager.evaluate_js("RecordingController.start()")
            rumps.notification("ClosedRoom", "Registrazione", "Avvio meeting…")
        else:
            rumps.notification("ClosedRoom", "Meeting non disponibile", "ClosedRoom sta preparando il meeting.")

    def _shortcut_add_note(self) -> None:
        """Open the same timestamped quick-note flow exposed by the menu bar."""
        self._add_quick_note(None)

    def _shortcut_take_screenshot(self) -> None:
        """Use the same selected-display screenshot action as the menu bar."""
        self._take_screenshot(None)

    def _shortcut_transcribe_clipboard(self) -> None:
        """Transcribe an audio file copied to the clipboard."""
        try:
            from AppKit import NSPasteboard, NSFilenamesPboardType
            pb = NSPasteboard.generalPasteboard()
            filenames = pb.propertyListForType_(NSFilenamesPboardType)
            if filenames:
                file_path = filenames[0]
                ext = Path(file_path).suffix.lower()
                if ext in {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".flac", ".aac"}:
                    import threading
                    threading.Thread(
                        target=self.transcribe_dropped_file,
                        args=(file_path,),
                        daemon=True
                    ).start()
                    rumps.notification(
                        "ClosedRoom",
                        "Trascrizione ⏳",
                        f"Avvio trascrizione di {Path(file_path).name} dagli appunti…"
                    )
                else:
                    rumps.notification(
                        "ClosedRoom",
                        "Errore Trascrizione ⚠️",
                        f"Il file negli appunti non è un formato audio supportato ({ext})."
                    )
            else:
                rumps.notification(
                    "ClosedRoom",
                    "Errore Trascrizione ⚠️",
                    "Nessun file trovato negli appunti. Copia un file audio in Finder e riprova."
                )
        except Exception as exc:
            logger.error("Shortcut transcribe clipboard failed: %s", exc)

    def _shortcut_paste_last_transcription(self) -> None:
        """Fetch last transcription, copy to clipboard, and simulate paste."""
        try:
            import urllib.request
            import json
            from AppKit import NSPasteboard, NSStringPboardType
            from pynput.keyboard import Controller, Key
            import time

            with urllib.request.urlopen(f"{self.app_url}/v1/transcriptions?limit=1", timeout=2) as resp:
                data = json.loads(resp.read())
                items = data.get("items", [])
                if items:
                    text = items[0].get("text", "")
                    if text.strip():
                        pb = NSPasteboard.generalPasteboard()
                        pb.clearContents()
                        pb.declareTypes_owner_([NSStringPboardType], None)
                        pb.setString_forType_(text, NSStringPboardType)

                        # Small delay to ensure clipboard is populated
                        time.sleep(0.1)

                        # Simulate cmd+v paste
                        keyboard_controller = Controller()
                        keyboard_controller.press(Key.cmd)
                        keyboard_controller.press('v')
                        keyboard_controller.release('v')
                        keyboard_controller.release(Key.cmd)
                    else:
                        rumps.notification("ClosedRoom", "Incolla Fallito", "L'ultima trascrizione è vuota.")
                else:
                    rumps.notification("ClosedRoom", "Incolla Fallito", "Nessuna trascrizione in archivio.")
        except Exception as exc:
            logger.error("Shortcut paste last transcription failed: %s", exc)

    # ── Menu callbacks ─────────────────────────────────────────────────────

    def _open_window(self, _) -> None:
        """Show and focus the native application window."""
        self.window_manager.show()

    def _start_recording(self, _) -> None:
        """Trigger recording start in WKWebView."""
        if not _check_server_health(self.app_port):
            self._update_status_item("ClosedRoom non disponibile")
            return
        self.window_manager.evaluate_js("RecordingController.start()")

    def _stop_recording(self, _) -> None:
        """Trigger recording stop in WKWebView."""
        if not _check_server_health(self.app_port):
            self._update_status_item("ClosedRoom non disponibile")
            return
        self.window_manager.evaluate_js("RecordingController.stop()")

    def _active_recording_payload(self) -> dict:
        try:
            payload = self._api_json("/v1/recordings/active")
        except Exception as exc:
            logger.warning("Unable to resolve active recording for menu action: %s", exc)
            return {}
        return payload if payload.get("active") else {}

    def _open_recording_controls(self, _) -> None:
        if not self._active_recording_payload():
            rumps.notification("ClosedRoom", "", "Nessun meeting in registrazione.")
            return
        self.window_manager.show_overlay()

    def _add_quick_note(self, _) -> None:
        active = self._active_recording_payload()
        recording_id = active.get("recording_id")
        if not recording_id:
            rumps.notification("ClosedRoom", "", "Nessun meeting in registrazione.")
            return
        try:
            anchor = self._api_json(
                f"/v1/recordings/{recording_id}/notes/anchor",
                method="POST",
            )
        except Exception as exc:
            logger.warning("Unable to anchor menu-bar note: %s", exc)
            rumps.notification("ClosedRoom", "", "Impossibile iniziare la nota in questo momento.")
            return

        timestamp = float(anchor.get("timestamp") or 0.0)
        minute = int(timestamp // 60)
        second = int(timestamp % 60)
        title = str(active.get("title") or "Meeting")
        response = rumps.Window(
            message=f"{title} · {minute}:{second:02d}",
            title="Aggiungi nota",
            default_text="",
            ok="Salva",
            cancel="Annulla",
            dimensions=(360, 72),
        ).run()
        if not response.clicked:
            return
        note_text = str(response.text or "").strip()
        if not note_text:
            return
        try:
            self._api_json(
                f"/v1/recordings/{recording_id}/notes",
                method="POST",
                payload={
                    "request_id": f"menubar-note-{recording_id}-{uuid.uuid4()}",
                    "timestamp": timestamp,
                    "text": note_text,
                },
            )
            rumps.notification("ClosedRoom", f"Nota salvata · {minute}:{second:02d}", "")
        except Exception as exc:
            logger.warning("Unable to save menu-bar note: %s", exc)
            rumps.alert(
                "Nota non salvata",
                "ClosedRoom non è riuscito a salvare la nota. Il meeting continua normalmente.",
            )

    def _take_screenshot(self, _) -> None:
        active = self._active_recording_payload()
        recording_id = active.get("recording_id")
        if not recording_id:
            rumps.notification("ClosedRoom", "", "Nessun meeting in registrazione.")
            return
        if active.get("capture_backend") != "native":
            rumps.notification("ClosedRoom", "", "Gli screenshot richiedono la registrazione nativa.")
            return
        display_id = active.get("screenshot_display_id")
        if display_id is None:
            self.window_manager.show_overlay()
            rumps.notification("ClosedRoom", "", "Scegli lo schermo nei controlli di registrazione.")
            return
        try:
            self._api_json(
                f"/v1/recordings/{recording_id}/screenshots",
                method="POST",
                payload={
                    "request_id": f"menubar-shot-{recording_id}-{uuid.uuid4()}",
                    "display_id": int(display_id),
                },
                timeout=8.0,
            )
            rumps.notification("ClosedRoom", "Screenshot salvato", "")
        except Exception as exc:
            logger.warning("Unable to capture menu-bar screenshot: %s", exc)
            rumps.notification("ClosedRoom", "Screenshot non salvato", "Apri i controlli per riprovare.")

    def _copy_last_transcription(self, _) -> None:
        """Copy the latest transcription text to clipboard."""
        import urllib.request
        import json
        from AppKit import NSPasteboard, NSStringPboardType

        try:
            with urllib.request.urlopen(f"{self.app_url}/v1/transcriptions?limit=1", timeout=2) as resp:
                data = json.loads(resp.read())
                items = data.get("items", [])
                if items:
                    text = items[0].get("text", "")
                    if text.strip():
                        pb = NSPasteboard.generalPasteboard()
                        pb.clearContents()
                        pb.declareTypes_owner_([NSStringPboardType], None)
                        pb.setString_forType_(text, NSStringPboardType)
                        rumps.notification(
                            "ClosedRoom",
                            "Copiato 📋",
                            "Trascrizione copiata negli appunti con successo."
                        )
                    else:
                        rumps.notification("ClosedRoom", "Copia Fallita", "L'ultima trascrizione è vuota.")
                else:
                    rumps.notification("ClosedRoom", "Copia Fallita", "Nessuna trascrizione in archivio.")
        except Exception as exc:
            logger.error("Failed to copy last transcription: %s", exc)
            rumps.alert("Errore", f"Impossibile copiare l'ultima trascrizione:\n{exc}")

    def _open_preferences(self, _) -> None:
        """Show window and navigate to the settings tab."""
        self.window_manager.show()
        self.window_manager.load_url(f"{self.app_url}/#settings")

    def _quit(self, _) -> None:
        """Gracefully stop the server, close the window, and quit."""
        self._status_timer.stop()
        native_hotkeys = getattr(self, "_native_hotkeys", None)
        if native_hotkeys is not None:
            native_hotkeys.stop()
        self.window_manager.close()
        self._server_thread.stop()
        clear_api_runtime(self.app_port)
        rumps.quit_application()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Run the ClosedRoom menu bar application."""
    from local_asr_server.bundled_module_dispatch import dispatch_bundled_module

    if dispatch_bundled_module():
        return
    if not _RUMPS_AVAILABLE:
        raise SystemExit(
            "rumps is not installed. Install it with:\n"
            "  pip install rumps\n"
            "or:\n"
            "  uv pip install rumps"
        )

    log_level_name = os.environ.get("CLOSEDROOM_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    ClosedRoomApp().run()


if __name__ == "__main__":
    main()
