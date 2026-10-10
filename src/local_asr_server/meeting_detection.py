"""Content-free, opt-in microphone activity suggestions for supported macOS apps.

CoreAudio is queried for input-running processes. No audio stream is opened,
and browser processes are deliberately excluded: Chrome using a microphone
does not establish that its active tab is a meeting.
"""
from __future__ import annotations

import ctypes
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Callable


SUPPORTED_APPS = {
    "us.zoom.xos": "Zoom",
    "com.microsoft.teams2": "Microsoft Teams",
    "com.microsoft.teams": "Microsoft Teams",
}
_GLOBAL_SCOPE = int.from_bytes(b"glob", "big")
_SYSTEM_OBJECT = 1
_PROCESS_LIST = int.from_bytes(b"prs#", "big")
_PROCESS_PID = int.from_bytes(b"ppid", "big")
_PROCESS_INPUT = int.from_bytes(b"piri", "big")


class AudioPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class ActivityObservation:
    capability: str  # supported | unsupported | unknown
    active_bundle_ids: frozenset[str] = frozenset()
    reason: str = ""


class CoreAudioInputObserver:
    """Fail closed: never infer an inactive meeting from unsupported CoreAudio."""

    def __init__(self, *, audio=None, app_lookup: Callable[[int], str | None] | None = None):
        self._audio = audio
        self._app_lookup = app_lookup

    @staticmethod
    def _available() -> bool:
        if sys.platform != "darwin":
            return False
        version = platform.mac_ver()[0]
        try:
            return tuple(int(x) for x in version.split(".")[:2]) >= (14, 2)
        except (ValueError, TypeError):
            return False

    def scan(self) -> ActivityObservation:
        if self._audio is None and not self._available():
            return ActivityObservation("unsupported", reason="macos_14_2_required")
        try:
            audio = self._audio or ctypes.CDLL(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
            )
            lookup = self._app_lookup or self._bundle_for_pid
            active = self._active_process_ids(audio)
            recognized = {bundle for pid in active
                          if (bundle := lookup(pid)) in SUPPORTED_APPS}
            return ActivityObservation("supported", frozenset(recognized))
        except (OSError, AttributeError, ValueError, RuntimeError):
            return ActivityObservation("unknown", reason="coreaudio_unavailable")

    @staticmethod
    def _bundle_for_pid(pid: int) -> str | None:
        try:
            from AppKit import NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            return str(app.bundleIdentifier()) if app and app.bundleIdentifier() else None
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _active_process_ids(audio) -> list[int]:
        audio.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(AudioPropertyAddress),
            ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
        ]
        audio.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        audio.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(AudioPropertyAddress),
            ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        audio.AudioObjectGetPropertyData.restype = ctypes.c_int32

        def read(object_id: int, selector: int, ctype):
            address = AudioPropertyAddress(selector, _GLOBAL_SCOPE, 0)
            data = ctype()
            size = ctypes.c_uint32(ctypes.sizeof(data))
            status = audio.AudioObjectGetPropertyData(
                object_id, ctypes.byref(address), 0, None,
                ctypes.byref(size), ctypes.byref(data),
            )
            if status != 0 or size.value != ctypes.sizeof(data):
                raise RuntimeError("CoreAudio process property unavailable")
            return data.value

        address = AudioPropertyAddress(_PROCESS_LIST, _GLOBAL_SCOPE, 0)
        size = ctypes.c_uint32(0)
        if audio.AudioObjectGetPropertyDataSize(
            _SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size)
        ) != 0:
            raise RuntimeError("CoreAudio process list unavailable")
        if size.value % ctypes.sizeof(ctypes.c_uint32) or size.value > 262144:
            raise RuntimeError("Invalid CoreAudio process list size")
        if not size.value:
            return []
        entries = (ctypes.c_uint32 * (size.value // 4))()
        if audio.AudioObjectGetPropertyData(
            _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
            ctypes.byref(size), ctypes.byref(entries),
        ) != 0:
            raise RuntimeError("CoreAudio process list changed")
        result: list[int] = []
        for obj_id in entries[: size.value // 4]:
            try:
                if read(obj_id, _PROCESS_INPUT, ctypes.c_uint32):
                    pid = read(obj_id, _PROCESS_PID, ctypes.c_int32)
                    if pid > 0:
                        result.append(pid)
            except RuntimeError:
                # A process can exit while the CoreAudio list is being read.
                continue
        return result


@dataclass
class MeetingCandidate:
    candidate_id: str
    bundle_id: str
    first_seen: float
    last_seen: float
    prompted: bool = False
    dismissed: bool = False


class MeetingSuggestionPolicy:
    """Volatile per-call policy; no transcript, application inventory or storage."""

    def __init__(self, *, activation_seconds: float = 4,
                 end_grace_seconds: float = 25):
        self.activation_seconds = activation_seconds
        self.end_grace_seconds = end_grace_seconds
        self._sessions: dict[str, MeetingCandidate] = {}

    def reset(self) -> None:
        self._sessions.clear()

    def active_candidate(self, candidate_id: str, *, now: float | None = None) -> MeetingCandidate | None:
        now = time.monotonic() if now is None else now
        for candidate in self._sessions.values():
            if candidate.candidate_id == candidate_id and now - candidate.last_seen < self.end_grace_seconds:
                return candidate
        return None

    def resolve_action(self, candidate_id: str, action: str, *, now: float | None = None) -> bool:
        candidate = self.active_candidate(candidate_id, now=now)
        if candidate is None or candidate.dismissed or action not in {"record", "ignore", "dismiss"}:
            return False
        candidate.dismissed = True
        return action == "record"

    def observe(self, observation: ActivityObservation, *, enabled: bool,
                busy: bool, now: float | None = None) -> list[MeetingCandidate]:
        now = time.monotonic() if now is None else now
        if not enabled:
            self.reset()
            return []
        if observation.capability != "supported":
            return []
        for bundle_id, candidate in list(self._sessions.items()):
            if bundle_id not in observation.active_bundle_ids and now - candidate.last_seen >= self.end_grace_seconds:
                del self._sessions[bundle_id]
        for bundle_id in observation.active_bundle_ids:
            if bundle_id not in SUPPORTED_APPS:
                continue
            if bundle_id in self._sessions:
                self._sessions[bundle_id].last_seen = now
            else:
                self._sessions[bundle_id] = MeetingCandidate(
                    candidate_id=str(uuid.uuid4()), bundle_id=bundle_id,
                    first_seen=now, last_seen=now,
                )
        if busy:
            return []
        to_notify: list[MeetingCandidate] = []
        for candidate in self._sessions.values():
            if not candidate.prompted and not candidate.dismissed and now - candidate.first_seen >= self.activation_seconds:
                candidate.prompted = True
                to_notify.append(candidate)
        return to_notify
