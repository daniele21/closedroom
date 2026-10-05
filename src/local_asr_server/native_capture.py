from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from local_asr_server.runtime.capture_events import (
    BoundedCaptureEventHistory,
    CoalescingCaptureEventQueue,
)

from local_asr_server.paths import (
    get_native_capture_helper_path,
    get_ffmpeg_path,
    get_ffprobe_path,
)


VALID_NATIVE_MODES = {"both", "mic_only", "pc_only"}

logger = logging.getLogger("local_asr_server.native_capture")


def _bounded_process_output(value: str | bytes | None, *, limit: int = 12_000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return "...[truncated]..." + text[-limit:]


def mode_permission_ok(payload: dict[str, Any], mode: str) -> bool:
    modes = payload.get("modes") or {}
    mode_info = modes.get(mode) or {}
    return bool(mode_info.get("ok"))


@dataclass
class CaptureSession:
    recording_id: str
    mode: str
    process: subprocess.Popen[str]
    output_dir: Path
    reader_thread: threading.Thread | None = None
    started_at: float = field(default_factory=time.time)
    events: CoalescingCaptureEventQueue = field(default_factory=CoalescingCaptureEventQueue)
    event_log: BoundedCaptureEventHistory = field(default_factory=BoundedCaptureEventHistory)
    ready_event: dict[str, Any] | None = None
    track_ready: dict[str, dict[str, Any]] = field(default_factory=dict)
    track_written: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_volume: dict[str, float] = field(default_factory=dict)
    warnings: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=128))
    stopped: bool = False
    screenshot_display_id: int | None = None
    screenshot_lock: threading.Lock = field(default_factory=threading.Lock)
    screenshot_condition: threading.Condition = field(default_factory=threading.Condition)
    screenshot_inflight: int = 0
    accept_screenshots: bool = True
    screenshot_worker_process: subprocess.Popen[str] | None = None
    screenshot_worker_reader_thread: threading.Thread | None = None
    screenshot_worker_ready: threading.Event = field(default_factory=threading.Event)
    screenshot_worker_displays: list[dict[str, Any]] = field(default_factory=list)
    screenshot_worker_pid: int | None = None
    screenshot_worker_restarts: int = 0
    screenshot_worker_lock: threading.Lock = field(default_factory=threading.Lock)
    screenshot_command_lock: threading.Lock = field(default_factory=threading.Lock)
    screenshot_pending: dict[str, queue.Queue[dict[str, Any]]] = field(default_factory=dict)


def validate_audio_file(file_path: Path) -> dict[str, Any]:
    """Validate audio file using ffprobe and return info/warnings."""
    if not file_path.exists():
        return {"valid": False, "error": "file_not_found"}
    if file_path.stat().st_size == 0:
        return {"valid": False, "error": "file_empty"}
        
    try:
        ffprobe_path = get_ffprobe_path()
        
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration:stream=sample_rate,channels",
            "-of", "json",
            str(file_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
        data = json.loads(res.stdout or "{}")
        
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        
        duration = float(fmt.get("duration", 0.0))
        channels = int(streams[0].get("channels", 0)) if streams else 0
        sample_rate = int(streams[0].get("sample_rate", 0)) if streams else 0
        
        if duration <= 0:
            return {"valid": False, "error": "zero_duration", "size": file_path.stat().st_size}
            
        return {
            "valid": True,
            "duration": duration,
            "channels": channels,
            "sample_rate": sample_rate,
            "size": file_path.stat().st_size
        }
    except Exception as e:
        return {"valid": False, "error": "ffprobe_failed", "details": str(e)}


class NativeCaptureManager:
    def __init__(self, helper_path: Path | None = None) -> None:
        self._helper_path_overridden = helper_path is not None
        self.helper_path = helper_path or get_native_capture_helper_path()
        self._lock = threading.Lock()
        self._sessions: dict[str, CaptureSession] = {}

    def _refresh_dev_helper(self) -> None:
        """Compile the native helper when its Swift source changed in dev mode."""
        if self._helper_path_overridden or sys.platform != "darwin":
            return
        from local_asr_server.native_capture_helper import get_helper_binary

        self.helper_path = Path(get_helper_binary())

    def get_session(self, recording_id: str) -> CaptureSession | None:
        """Return the active capture session without exposing mutable storage."""

        with self._lock:
            return self._sessions.get(recording_id)

    def capabilities(self) -> dict[str, Any]:
        if sys.platform != "darwin":
            return {
                "available": False,
                "backend": "native",
                "reason": "macos_required",
                "modes": [],
            }
        if not self.helper_path.exists():
            try:
                from local_asr_server.native_capture_helper import get_helper_binary
                self.helper_path = Path(get_helper_binary())
            except Exception as exc:
                return {
                    "available": False,
                    "backend": "native",
                    "reason": "helper_missing",
                    "helper_path": str(self.helper_path),
                    "error": str(exc),
                    "modes": [],
                }
        return self._run_json(["capabilities"], fallback_reason="capabilities_failed")

    def permissions(self) -> dict[str, Any]:
        if not self.helper_path.exists():
            return {"ok": False, "reason": "helper_missing"}
        return self._run_json(["permissions"], fallback_reason="permissions_failed")

    def request_permissions(self) -> dict[str, Any]:
        if not self.helper_path.exists():
            return {"ok": False, "reason": "helper_missing"}
        return self._run_json(["request-permissions"], fallback_reason="request_permissions_failed")

    def diagnostics(self) -> dict[str, Any]:
        if not self.helper_path.exists():
            return {"ok": False, "reason": "helper_missing"}
        return self._run_json(["diagnostics"], fallback_reason="diagnostics_failed")

    def windows(self) -> dict[str, Any]:
        if not self.helper_path.exists():
            return {"windows": [], "reason": "helper_missing"}
        return self._run_json(["windows"], fallback_reason="window_listing_failed")

    def displays(self) -> dict[str, Any]:
        with self._lock:
            active = next(
                (session for session in self._sessions.values() if not session.stopped),
                None,
            )
        if active is not None:
            try:
                self._ensure_screenshot_worker(active)
            except Exception as exc:
                logger.warning(
                    "Screenshot worker unavailable while listing displays for recording %s: %s",
                    active.recording_id,
                    exc,
                )
            active.screenshot_worker_ready.wait(timeout=0.25)
            with active.screenshot_worker_lock:
                cached = [dict(item) for item in active.screenshot_worker_displays]
                worker = active.screenshot_worker_process
                worker_alive = worker is not None and worker.poll() is None
            if cached:
                return {"displays": cached, "reason": None, "source": "worker_cache"}
            return {
                "displays": [],
                "reason": "screenshot_worker_starting" if worker_alive else "screenshot_worker_unavailable",
                "source": "worker_cache",
            }

        payload = self.windows()
        displays: list[dict[str, Any]] = []
        for item in payload.get("windows") or []:
            if item.get("kind") != "display" and item.get("bundle_identifier") != "com.apple.displays":
                continue
            source_id = int(item.get("id") or 0)
            display_id = int(item.get("display_id") or abs(source_id))
            if display_id <= 0:
                continue
            displays.append({
                "display_id": display_id,
                "source_id": source_id,
                "title": item.get("title") or f"Display {display_id}",
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
                "is_main": bool(item.get("is_main", False)),
            })
        return {"displays": displays, "reason": payload.get("reason"), "source": "legacy_discovery"}

    def begin_screenshot(self, recording_id: str) -> None:
        with self._lock:
            session = self._sessions.get(recording_id)
        if session is None or session.stopped:
            raise RuntimeError("Native capture session is not active")
        with session.screenshot_condition:
            if not session.accept_screenshots or session.stopped:
                raise RuntimeError("Screenshot capture is closing")
            session.screenshot_inflight += 1

    def finish_screenshot(self, recording_id: str) -> None:
        with self._lock:
            session = self._sessions.get(recording_id)
        if session is None:
            return
        with session.screenshot_condition:
            if session.screenshot_inflight > 0:
                session.screenshot_inflight -= 1
            session.screenshot_condition.notify_all()

    def capture_screenshot(
        self,
        recording_id: str,
        *,
        request_id: str,
        display_id: int | None = None,
        admission_held: bool = False,
        original_path: Path | None = None,
        thumbnail_path: Path | None = None,
    ) -> dict[str, Any]:
        request_id = request_id.strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain between 1 and 128 characters")

        if not admission_held:
            self.begin_screenshot(recording_id)
        try:
            return self._capture_screenshot_admitted(
                recording_id,
                request_id=request_id,
                display_id=display_id,
                original_path=original_path,
                thumbnail_path=thumbnail_path,
            )
        finally:
            if not admission_held:
                self.finish_screenshot(recording_id)

    def _capture_screenshot_admitted(
        self,
        recording_id: str,
        *,
        request_id: str,
        display_id: int | None,
        original_path: Path | None,
        thumbnail_path: Path | None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(recording_id)
        if session is None or session.stopped:
            raise RuntimeError("Native capture session is not active")

        self._ensure_screenshot_worker(session)
        if not session.screenshot_worker_ready.wait(timeout=1.0):
            raise RuntimeError("screenshot_worker_not_ready")

        with session.screenshot_worker_lock:
            displays = [dict(item) for item in session.screenshot_worker_displays]
        by_id = {int(item["display_id"]): item for item in displays}
        selected = display_id if display_id is not None else session.screenshot_display_id
        if selected is None:
            if displays:
                main = next((item for item in displays if item.get("is_main")), displays[0])
                selected = int(main["display_id"])
                logger.info(
                    "No display explicitly selected for recording %s; defaulting to display_id=%s",
                    recording_id,
                    selected,
                )
            else:
                raise RuntimeError("no_display_available")
        selected = int(selected)
        if selected not in by_id:
            raise RuntimeError("selected_display_unavailable")

        ready = session.ready_event or {}
        ready_uptime = ready.get("recording_ready_uptime")
        if ready_uptime is None:
            raise RuntimeError("capture_not_ready")

        with session.screenshot_lock:
            if session.stopped or not session.accept_screenshots:
                raise RuntimeError("Screenshot capture is closing")
            session.screenshot_display_id = selected
            owns_output_paths = original_path is None and thumbnail_path is None
            if (original_path is None) != (thumbnail_path is None):
                raise ValueError("original_path and thumbnail_path must be provided together")
            temp_dir: Path | None = None
            token = uuid.uuid4().hex
            trace_id = f"shot-{token[:12]}"
            if owns_output_paths:
                temp_dir = session.output_dir / ".screenshot-capture-temp"
                temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                original_path = temp_dir / f"{token}.jpg"
                thumbnail_path = temp_dir / f"{token}-thumb.jpg"
            else:
                original_path = Path(original_path)
                thumbnail_path = Path(thumbnail_path)
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            with session.screenshot_worker_lock:
                session.screenshot_pending[request_id] = waiter
                worker_pid = session.screenshot_worker_pid
                restart_count = session.screenshot_worker_restarts

            command = {
                "type": "capture_screenshot",
                "recording_id": recording_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "display_id": selected,
                "recording_ready_uptime": float(ready_uptime),
                "original_file": str(original_path),
                "thumbnail_file": str(thumbnail_path),
            }
            roundtrip_start = time.monotonic()
            try:
                logger.info(
                    "Screenshot dispatch: trace_id=%s recording=%s display=%s worker_pid=%s restart_count=%s",
                    trace_id,
                    recording_id,
                    selected,
                    worker_pid,
                    restart_count,
                )
                self._send_screenshot_worker_command(session, command)
                try:
                    event = waiter.get(timeout=1.6)
                except queue.Empty as exc:
                    logger.error(
                        "Screenshot worker response timeout: trace_id=%s recording=%s display=%s worker_pid=%s",
                        trace_id,
                        recording_id,
                        selected,
                        worker_pid,
                    )
                    self._restart_screenshot_worker(session, reason="request_timeout")
                    raise RuntimeError(f"screenshot_capture_timeout:{trace_id}") from exc

                event_type = str(event.get("type") or "")
                if event_type != "screenshot_completed":
                    reason = str(event.get("reason") or "screenshot_capture_failed")
                    message = str(event.get("message") or reason)
                    if reason == "screenshot_capture_timeout":
                        self._restart_screenshot_worker(session, reason=reason)
                    raise RuntimeError(f"{reason}: {message}")

                if not original_path.is_file() or not thumbnail_path.is_file():
                    raise RuntimeError("screenshot_capture_missing_output")

                captured_uptime = float(event.get("captured_uptime"))
                roundtrip_ms = int((time.monotonic() - roundtrip_start) * 1000.0)
                logger.info(
                    "Screenshot completed: trace_id=%s worker_pid=%s display=%s roundtrip_ms=%s "
                    "capture_ms=%s encode_ms=%s write_ms=%s",
                    trace_id,
                    worker_pid,
                    selected,
                    roundtrip_ms,
                    event.get("capture_ms"),
                    event.get("encode_ms"),
                    event.get("write_ms"),
                )
                result = {
                    **event,
                    "request_id": request_id,
                    "recording_id": recording_id,
                    "display_id": selected,
                    "display_title": by_id[selected].get("title"),
                    "captured_uptime": captured_uptime,
                    "recording_ready_uptime": float(ready_uptime),
                    "timestamp": max(0.0, captured_uptime - float(ready_uptime)),
                    "roundtrip_ms": roundtrip_ms,
                    "worker_pid": worker_pid,
                    "worker_restart_count": restart_count,
                    "original_path": str(original_path),
                    "thumbnail_path": str(thumbnail_path),
                }
                if owns_output_paths:
                    result["original_bytes"] = original_path.read_bytes()
                    result["thumbnail_bytes"] = thumbnail_path.read_bytes()
                return result
            finally:
                with session.screenshot_worker_lock:
                    session.screenshot_pending.pop(request_id, None)
                if owns_output_paths:
                    original_path.unlink(missing_ok=True)
                    thumbnail_path.unlink(missing_ok=True)
                    if temp_dir is not None:
                        try:
                            temp_dir.rmdir()
                        except OSError:
                            pass

    def _ensure_screenshot_worker(self, session: CaptureSession) -> None:
        with session.screenshot_worker_lock:
            worker = session.screenshot_worker_process
            alive = worker is not None and worker.poll() is None
        if alive:
            return
        self._start_screenshot_worker(session)

    def _start_screenshot_worker(self, session: CaptureSession) -> None:
        command = [
            str(self.helper_path),
            "screenshot-worker",
            "--recording-id",
            session.recording_id,
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        with session.screenshot_worker_lock:
            session.screenshot_worker_process = process
            session.screenshot_worker_pid = process.pid
            session.screenshot_worker_ready.clear()
            session.screenshot_worker_displays = []
        thread = threading.Thread(
            target=self._read_screenshot_worker_events,
            args=(session, process),
            daemon=True,
        )
        session.screenshot_worker_reader_thread = thread
        thread.start()
        logger.info(
            "Screenshot worker started: recording=%s pid=%s restart_count=%s",
            session.recording_id,
            process.pid,
            session.screenshot_worker_restarts,
        )

    def _read_screenshot_worker_events(
        self,
        session: CaptureSession,
        process: subprocess.Popen[str],
    ) -> None:
        if process.stdout is None:
            return
        try:
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("CR_SCREENSHOT_DIAG "):
                    logger.info("Screenshot worker diagnostic: %s", _bounded_process_output(line))
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Screenshot worker emitted non-JSON output for recording %s: %s",
                        session.recording_id,
                        _bounded_process_output(line),
                    )
                    continue
                event_type = str(event.get("type") or "")
                if event_type == "screenshot_worker_ready":
                    displays = event.get("displays") if isinstance(event.get("displays"), list) else []
                    with session.screenshot_worker_lock:
                        if session.screenshot_worker_process is process:
                            session.screenshot_worker_pid = int(event.get("worker_pid") or process.pid)
                            session.screenshot_worker_displays = [
                                dict(item) for item in displays if isinstance(item, dict)
                            ]
                            session.screenshot_worker_ready.set()
                    logger.info(
                        "Screenshot worker ready: recording=%s pid=%s displays=%s backend=%s",
                        session.recording_id,
                        event.get("worker_pid"),
                        len(displays),
                        event.get("capture_backend"),
                    )
                elif event_type == "displays_changed":
                    displays = event.get("displays") if isinstance(event.get("displays"), list) else []
                    with session.screenshot_worker_lock:
                        if session.screenshot_worker_process is process:
                            session.screenshot_worker_displays = [
                                dict(item) for item in displays if isinstance(item, dict)
                            ]
                elif event_type in {"screenshot_completed", "screenshot_failed"}:
                    request_id = str(event.get("request_id") or "")
                    with session.screenshot_worker_lock:
                        waiter = session.screenshot_pending.get(request_id)
                    if waiter is not None:
                        try:
                            waiter.put_nowait(event)
                        except queue.Full:
                            pass
                elif event_type in {"screenshot_worker_warning", "screenshot_worker_error"}:
                    logger.warning(
                        "Screenshot worker event: recording=%s type=%s reason=%s message=%s",
                        session.recording_id,
                        event_type,
                        event.get("reason"),
                        event.get("message"),
                    )
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass
            with session.screenshot_worker_lock:
                is_current = session.screenshot_worker_process is process
                if is_current:
                    session.screenshot_worker_ready.clear()
                    pending = list(session.screenshot_pending.values())
                else:
                    pending = []
            for waiter in pending:
                try:
                    waiter.put_nowait({
                        "type": "screenshot_failed",
                        "reason": "screenshot_worker_stopped",
                        "message": "Screenshot worker stopped before completing the request",
                        "recoverable": True,
                    })
                except queue.Full:
                    pass

    def _send_screenshot_worker_command(
        self,
        session: CaptureSession,
        payload: dict[str, Any],
    ) -> None:
        with session.screenshot_command_lock:
            with session.screenshot_worker_lock:
                worker = session.screenshot_worker_process
            if worker is None or worker.poll() is not None or worker.stdin is None:
                raise RuntimeError("screenshot_worker_unavailable")
            try:
                worker.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
                worker.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError("screenshot_worker_unavailable") from exc

    def _stop_screenshot_worker(self, session: CaptureSession, *, graceful: bool) -> None:
        with session.screenshot_worker_lock:
            worker = session.screenshot_worker_process
            thread = session.screenshot_worker_reader_thread
        if worker is None:
            return
        if worker.poll() is None and graceful:
            try:
                self._send_screenshot_worker_command(session, {"type": "shutdown"})
                worker.wait(timeout=1.0)
            except Exception:
                pass
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=1.0)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with session.screenshot_worker_lock:
            if session.screenshot_worker_process is worker:
                session.screenshot_worker_process = None
                session.screenshot_worker_reader_thread = None
                session.screenshot_worker_pid = None
                session.screenshot_worker_ready.clear()
                session.screenshot_worker_displays = []

    def _restart_screenshot_worker(self, session: CaptureSession, *, reason: str) -> None:
        logger.warning(
            "Restarting screenshot worker: recording=%s reason=%s previous_pid=%s",
            session.recording_id,
            reason,
            session.screenshot_worker_pid,
        )
        self._stop_screenshot_worker(session, graceful=False)
        with session.screenshot_worker_lock:
            session.screenshot_worker_restarts += 1
        if not session.stopped and session.accept_screenshots:
            self._start_screenshot_worker(session)

    def ensure_permissions(self, mode: str) -> dict[str, Any]:
        if mode not in VALID_NATIVE_MODES:
            raise ValueError(f"Invalid native capture mode: {mode}")

        permissions = self.permissions()
        if mode_permission_ok(permissions, mode):
            return {
                "ok": True,
                "permissions": permissions,
                "diagnostics": self.diagnostics(),
                "requested": False,
            }

        microphone = permissions.get("microphone")
        screen_capture = permissions.get("screen_capture")
        should_request = False

        if mode in {"both", "mic_only"} and microphone == "notDetermined":
            should_request = True
        if mode in {"both", "pc_only"} and screen_capture == "required":
            should_request = True

        if should_request:
            request_result = self.request_permissions()
            permissions = self.permissions()
            return {
                "ok": mode_permission_ok(permissions, mode),
                "permissions": permissions,
                "diagnostics": self.diagnostics(),
                "requested": True,
                "request_result": request_result,
            }

        return {
            "ok": False,
            "permissions": permissions,
            "diagnostics": self.diagnostics(),
            "requested": False,
        }

    def start(
        self, recording_id: str, output_dir: Path, mode: str, *,
        visual_window_id: int | None = None, visual_fps: float = 0.5,
    ) -> dict[str, Any]:
        if mode not in VALID_NATIVE_MODES:
            raise ValueError(f"Invalid native capture mode: {mode}")
        self._refresh_dev_helper()
        if not self.capabilities().get("available"):
            raise RuntimeError("Native capture helper is not available")
        with self._lock:
            if recording_id in self._sessions:
                raise RuntimeError("Native capture session already active")
            command = [
                    str(self.helper_path),
                    "start",
                    "--recording-id",
                    recording_id,
                    "--output-dir",
                    str(output_dir),
                    "--mode",
                    mode,
                ]
            if visual_window_id is not None:
                command.extend(["--visual-window-id", str(visual_window_id), "--visual-fps", str(visual_fps)])
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            session = CaptureSession(
                recording_id=recording_id,
                mode=mode,
                process=process,
                output_dir=output_dir,
            )
            self._sessions[recording_id] = session
            thread = threading.Thread(target=self._read_events, args=(session,), daemon=True)
            session.reader_thread = thread
            thread.start()
            try:
                self._start_screenshot_worker(session)
            except Exception as exc:
                logger.warning(
                    "Screenshot worker failed to start for recording %s; audio capture continues: %s",
                    recording_id,
                    exc,
                )
            return {
                "recording_id": recording_id,
                "capture_session_id": str(uuid.uuid4()),
                "backend": "native",
                "mode": mode,
                "status": "starting",
            }

    def stop(self, recording_id: str) -> dict[str, Any]:
        return self._terminate(recording_id, cancel=False)

    def cancel(self, recording_id: str) -> dict[str, Any]:
        return self._terminate(recording_id, cancel=True)

    def drain_events(self, recording_id: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(recording_id)
        if session is None:
            return []
        events = []
        while True:
            try:
                events.append(session.events.get_nowait())
            except queue.Empty:
                return events

    def _run_json(self, args: list[str], *, fallback_reason: str) -> dict[str, Any]:
        try:
            self._refresh_dev_helper()
            completed = subprocess.run(
                [str(self.helper_path), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            
            parsed = None
            if stdout:
                try:
                    parsed = json.loads(stdout.splitlines()[-1])
                except (json.JSONDecodeError, IndexError):
                    parsed = None
                    
            if completed.returncode != 0:
                return {
                    "available": False,
                    "backend": "native",
                    "reason": parsed.get("reason", fallback_reason) if (parsed and isinstance(parsed, dict)) else fallback_reason,
                    "error": parsed or stderr or stdout,
                }
            return parsed if (parsed and isinstance(parsed, dict)) else {}
        except Exception as exc:
            return {"available": False, "backend": "native", "reason": fallback_reason, "error": str(exc)}

    def _read_events(self, session: CaptureSession) -> None:
        if session.process.stdout is None:
            return
        try:
            for line in session.process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "warning", "message": line}
                
                session.event_log.append(event)
                if event.get("type") == "ready":
                    session.ready_event = event
                elif event.get("type") == "track_first_sample":
                    session.track_ready[event["source"]] = event
                elif event.get("type") == "track_first_written_sample":
                    session.track_written[event["source"]] = event
                elif event.get("type") == "volume":
                    session.last_volume[event["source"]] = event.get("db", -120.0)
                elif event.get("type") in {"warning", "error"}:
                    session.warnings.append(event)
                    if event.get("type") == "error":
                        session.stopped = True

                session.events.put(event)
                if event.get("type") in {"stopped", "error"}:
                    session.stopped = True
            session.process.wait()
        finally:
            session.process.stdout.close()
            session.stopped = True

    def _terminate(self, recording_id: str, *, cancel: bool) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(recording_id)
        if session is None:
            return {"recording_id": recording_id, "backend": "native", "status": "not_active"}

        with session.screenshot_condition:
            session.accept_screenshots = False
            deadline = time.monotonic() + 10.0
            while session.screenshot_inflight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                session.screenshot_condition.wait(timeout=remaining)

        self._stop_screenshot_worker(session, graceful=True)

        was_killed = False
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                session.process.kill()
                was_killed = True
                
        events = []
        if session.reader_thread:
            session.reader_thread.join(timeout=2)
            if session.reader_thread.is_alive():
                events.append({
                    "type": "warning",
                    "source": "backend",
                    "message": "Native helper stdout reader did not finish before post-processing."
                })
        while True:
            try:
                events.append(session.events.get_nowait())
            except queue.Empty:
                break
                
        if was_killed:
            events.append({
                "type": "error",
                "source": "backend",
                "message": "Native helper did not stop cleanly and was killed. Audio files may be incomplete or corrupted."
            })
            
        # Post-process mixing and validation
        if not cancel and not was_killed:
            output_dir = session.output_dir
            mode = session.mode
            mic_path = output_dir / "mic.wav"
            system_path = output_dir / "system.wav"
            recording_path = output_dir / "recording.wav"
            
            # Post-processing mixing
            if mode == "both":
                mic_exists = mic_path.exists() and mic_path.stat().st_size > 0
                system_exists = system_path.exists() and system_path.stat().st_size > 0
                
                if mic_exists and system_exists:
                    try:
                        # Get durations to calculate dynamic timeout
                        mic_duration = 0.0
                        system_duration = 0.0
                        
                        mic_report = validate_audio_file(mic_path)
                        if mic_report["valid"]:
                            mic_duration = mic_report["duration"]
                        
                        system_report = validate_audio_file(system_path)
                        if system_report["valid"]:
                            system_duration = system_report["duration"]
                            
                        max_duration = max(mic_duration, system_duration)
                        ffmpeg_timeout = max(120.0, min(3600.0, max_duration * 0.5))
                        
                        ffmpeg_path = get_ffmpeg_path()
                        cmd = [
                            ffmpeg_path,
                            "-y",
                            "-i", str(mic_path),
                            "-i", str(system_path),
                            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0",
                            "-ar", "16000",
                            "-ac", "1",
                            str(recording_path)
                        ]
                        subprocess.run(cmd, capture_output=True, text=True, timeout=ffmpeg_timeout, check=True)
                    except Exception as e:
                        error_msg = f"Failed to mix audio tracks with ffmpeg: {e}"
                        events.append({"type": "error", "source": "backend", "message": error_msg})
                elif mic_exists:
                    try:
                        shutil.copy2(mic_path, recording_path)
                    except Exception as e:
                        events.append({"type": "error", "source": "backend", "message": f"Failed to copy mic.wav to recording.wav: {e}"})
                elif system_exists:
                    try:
                        shutil.copy2(system_path, recording_path)
                    except Exception as e:
                        events.append({"type": "error", "source": "backend", "message": f"Failed to copy system.wav to recording.wav: {e}"})
                else:
                    events.append({"type": "warning", "message": "Neither mic.wav nor system.wav contains valid audio data."})
            
            # Build and save timeline.json
            timeline_data = {
                "recording_ready_at": None,
                "recording_ready_uptime": None,
                "tracks": {}
            }
            
            if session.ready_event:
                timeline_data["recording_ready_at"] = session.ready_event.get("recording_ready_at")
                timeline_data["recording_ready_uptime"] = session.ready_event.get("recording_ready_uptime")
                
            for src in ["mic", "system"]:
                track_info = {}
                
                # Track observed time
                if src in session.track_ready:
                    evt = session.track_ready[src]
                    track_info["first_observed_wall_time"] = evt.get("observed_wall_time")
                    track_info["first_observed_uptime"] = evt.get("observed_uptime")
                    track_info["first_observed_pts"] = evt.get("pts")
                    
                # Track written time
                if src in session.track_written:
                    evt = session.track_written[src]
                    track_info["first_written_wall_time"] = evt.get("written_wall_time")
                    track_info["first_written_uptime"] = evt.get("written_uptime")
                    track_info["first_written_pts"] = evt.get("pts")
                    
                if track_info:
                    # Compute offset using uptime
                    ready_uptime = timeline_data.get("recording_ready_uptime")
                    written_uptime = track_info.get("first_written_uptime")
                    if ready_uptime is not None and written_uptime is not None:
                        offset_ms = int((written_uptime - ready_uptime) * 1000)
                        track_info["offset_ms"] = offset_ms
                    timeline_data["tracks"][src] = track_info
            
            timeline_path = output_dir / "timeline.json"
            try:
                with open(timeline_path, "w", encoding="utf-8") as f:
                    json.dump(timeline_data, f, indent=2)
            except Exception as e:
                events.append({"type": "warning", "message": f"Failed to write timeline.json: {e}"})

            # Run ffprobe validation
            paths_to_validate = {}
            if mode == "both":
                paths_to_validate = {"mic": mic_path, "system": system_path, "mixed": recording_path}
            elif mode == "mic_only":
                paths_to_validate = {"mic": mic_path}
            else:
                paths_to_validate = {"system": system_path}
                
            for source, path in paths_to_validate.items():
                report = validate_audio_file(path)
                if not report["valid"]:
                    events.append({
                        "type": "warning",
                        "message": f"Validation failed for track {source}: {report.get('error')} ({report.get('details', '')})"
                    })
                elif report.get("duration", 0.0) < 1.0:
                    events.append({
                        "type": "warning",
                        "message": f"Track {source} is extremely short (duration: {report['duration']}s)"
                    })

        with self._lock:
            self._sessions.pop(recording_id, None)
            
        return {
            "recording_id": recording_id,
            "backend": "native",
            "status": "cancelled" if cancel else ("interrupted" if was_killed else "stopped"),
            "events": events,
            "event_buffer": {
                "queue": session.events.stats(),
                "history": session.event_log.stats(),
                "retained_warnings": len(session.warnings),
                "warning_capacity": session.warnings.maxlen,
            },
        }