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

    # 3. MLX metallib fix — MLX resolves mlx.metallib relative to the loaded
    #    .so via dladdr/NSBundle.  In a PyInstaller bundle this path resolution
    #    can fail because the bundle layout differs from a normal wheel install.
    #    We pre-load libmlx.dylib from the known location so that dladdr returns
    #    the correct path and MLX can find mlx.metallib alongside it.
    _mlx_lib_dir = _meipass / "mlx" / "lib"
    if _mlx_lib_dir.exists():
        # Prepend to DYLD_LIBRARY_PATH so the dynamic linker finds libmlx.dylib
        # and libjaccl.dylib from our bundled copies before any system path.
        _existing_dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
        _new_dyld = str(_mlx_lib_dir)
        if _existing_dyld:
            _new_dyld = f"{_new_dyld}:{_existing_dyld}"
        os.environ["DYLD_LIBRARY_PATH"] = _new_dyld

        # Pre-load libmlx so that subsequent dladdr calls return paths inside
        # _meipass/mlx/lib/, which lets MLX calculate the metallib path correctly.
        import ctypes
        _libmlx_path = _mlx_lib_dir / "libmlx.dylib"
        if _libmlx_path.exists():
            try:
                ctypes.CDLL(str(_libmlx_path))
            except OSError as _e:
                # Non-fatal: log and continue; MLX will try its own resolution.
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Could not pre-load libmlx.dylib from %s: %s", _libmlx_path, _e
                )

from local_asr_server.window import ClosedRoomWindowManager
from local_asr_server.app_identity import get_app_identity
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

# Status icons shown in the menu bar (using SF Symbols via text fallbacks)
ICON_IDLE = "🎙️"
ICON_RECORDING = "🔴"
ICON_TRANSCRIBING = "⏳"
ICON_ERROR = "⚠️"


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
        # Use a plain text title while we load; we'll update after server starts
        super().__init__(
            name="ClosedRoom",
            title=ICON_IDLE,
            quit_button=None,  # we provide our own Esci item
        )

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

        # Periodic status refresh (every 5 s)
        self._status_timer = rumps.Timer(self._refresh_status, 5)
        self._status_timer.start()

        # Start global shortcuts listener
        self._start_shortcuts_listener()

    def _initial_show(self, timer: rumps.Timer) -> None:
        """One-shot timer to show the window once the Cocoa run loop is active."""
        timer.stop()
        self._setup_drag_and_drop()
        self.window_manager.show()

    # ── Menu construction ──────────────────────────────────────────────────

    def _build_menu(self) -> None:
        """Construct the drop-down menu items."""
        from local_asr_server.launchd import is_launch_agent_installed

        launch_agent_title = (
            "✓ Avvia al login"
            if is_launch_agent_installed()
            else "Avvia al login"
        )

        self.menu = [
            rumps.MenuItem("Apri ClosedRoom", callback=self._open_window),
            rumps.separator,
            rumps.MenuItem("Stato: in avvio…"),
            rumps.separator,
            rumps.MenuItem("⏺ Avvia registrazione", callback=self._start_recording),
            rumps.MenuItem("⏹ Ferma registrazione", callback=self._stop_recording),
            rumps.MenuItem("📋 Copia ultima trascrizione", callback=self._copy_last_transcription),
            rumps.separator,
            rumps.MenuItem("Preferenze…", callback=self._open_preferences),
            rumps.MenuItem(launch_agent_title, callback=_toggle_launch_agent),
            rumps.separator,
            rumps.MenuItem("Esci", callback=self._quit),
        ]

        # Disable recording controls until server is ready
        self.menu["⏺ Avvia registrazione"].set_callback(None)
        self.menu["⏹ Ferma registrazione"].set_callback(None)
        self.menu["📋 Copia ultima trascrizione"].set_callback(None)

    # ── Server lifecycle ───────────────────────────────────────────────────

    def _wait_for_server(self) -> None:
        """Block until the server reports healthy, then update the UI and load WebView."""
        self._server_thread.ready.wait(timeout=60)
        # Extra wait for uvicorn to bind the port
        import time
        for _ in range(20):
            if _check_server_health(self.app_port):
                break
            time.sleep(0.5)

        from local_asr_server.window import run_on_main_thread

        def update_ui():
            # Update status item and re-enable recording controls
            self._update_status_item("Server attivo ✅")
            self.menu["⏺ Avvia registrazione"].set_callback(self._start_recording)
            self.menu["⏹ Ferma registrazione"].set_callback(None)
            self.menu["📋 Copia ultima trascrizione"].set_callback(self._copy_last_transcription)

            # Replace loading screen with the real application URL
            self.window_manager.load_url(self.app_url)

        run_on_main_thread(update_ui)


    # ── Periodic status refresh ────────────────────────────────────────────

    @rumps.timer(5)
    def _refresh_status(self, _) -> None:
        """Update the status menu item and icon every 5 seconds."""
        status = _get_server_status(self.app_port)
        if not status:
            self._update_status_item("Server non raggiungibile ⚠️")
            self.title = ICON_ERROR
            # Disable recording callbacks when server is down
            self.menu["⏺ Avvia registrazione"].set_callback(None)
            self.menu["⏹ Ferma registrazione"].set_callback(None)
            self.menu["📋 Copia ultima trascrizione"].set_callback(None)
            return

        server_status = status.get("status", "idle")
        if server_status == "recording":
            self.title = ICON_RECORDING
            self._update_status_item("Registrazione in corso… 🔴")
            self.menu["⏺ Avvia registrazione"].set_callback(None)
            self.menu["⏹ Ferma registrazione"].set_callback(self._stop_recording)
        elif server_status == "transcribing":
            self.title = ICON_TRANSCRIBING
            self._update_status_item("Trascrizione in corso… ⏳")
            self.menu["⏺ Avvia registrazione"].set_callback(None)
            self.menu["⏹ Ferma registrazione"].set_callback(None)
        else:
            self.title = ICON_IDLE
            self._update_status_item("Server attivo ✅")
            self.menu["⏺ Avvia registrazione"].set_callback(self._start_recording)
            self.menu["⏹ Ferma registrazione"].set_callback(None)
        
        self.menu["📋 Copia ultima trascrizione"].set_callback(self._copy_last_transcription)

    def _update_status_item(self, text: str) -> None:
        self.menu["Stato: in avvio…"].title = f"Stato: {text}"

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
            self.title = ICON_TRANSCRIBING
            self._update_status_item("Trascrizione da drop… ⏳")
            self.menu["⏺ Avvia registrazione"].set_callback(None)
            self.menu["⏹ Ferma registrazione"].set_callback(None)

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
        """Start the global keyboard shortcuts listener using pynput."""
        from local_asr_server.macos_permissions import accessibility_status

        permission = accessibility_status()
        if not permission.get("trusted"):
            logger.warning(
                "Global shortcuts disabled: macOS Accessibility permission is required "
                "(System Settings > Privacy & Security > Accessibility)."
            )
            return

        def run_listener():
            try:
                from pynput import keyboard

                shortcuts = {
                    "<cmd>+<shift>+r": self._shortcut_toggle_recording,
                    "<cmd>+<shift>+t": self._shortcut_transcribe_clipboard,
                    "<cmd>+<shift>+v": self._shortcut_paste_last_transcription,
                }

                logger.info("Starting global keyboard shortcut listener...")
                with keyboard.GlobalHotKeys(shortcuts) as listener:
                    listener.join()
            except Exception as exc:
                logger.error("Global shortcuts listener failed: %s", exc)

        import threading
        threading.Thread(target=run_listener, daemon=True).start()

    def _shortcut_toggle_recording(self) -> None:
        """Toggle recording via global keyboard shortcut."""
        status = _get_server_status(self.app_port)
        server_status = status.get("status", "idle")
        if server_status == "recording":
            self.window_manager.evaluate_js("RecordingController.stop()")
            rumps.notification("ClosedRoom", "Registrazione ⏹", "Salvataggio registrazione in corso…")
        elif server_status == "idle":
            self.window_manager.evaluate_js("RecordingController.start()")
            rumps.notification("ClosedRoom", "Registrazione ⏺", "Avvio registrazione…")
        else:
            rumps.notification("ClosedRoom", "Registrazione", "Il server è occupato con una trascrizione.")

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
            self._update_status_item("Server non raggiungibile ⚠️")
            return
        self.window_manager.evaluate_js("RecordingController.start()")

    def _stop_recording(self, _) -> None:
        """Trigger recording stop in WKWebView."""
        if not _check_server_health(self.app_port):
            self._update_status_item("Server non raggiungibile ⚠️")
            return
        self.window_manager.evaluate_js("RecordingController.stop()")

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
