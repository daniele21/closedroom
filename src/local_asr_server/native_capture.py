from __future__ import annotations

import json
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
        self.helper_path = helper_path or get_native_capture_helper_path()
        self._lock = threading.Lock()
        self._sessions: dict[str, CaptureSession] = {}

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
