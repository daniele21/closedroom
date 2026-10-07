from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


logger = logging.getLogger("local_asr_server.macos_hotkeys")


def fourcc(value: str) -> int:
    if len(value) != 4:
        raise ValueError("FourCC values must contain exactly four characters")
    return int.from_bytes(value.encode("mac_roman"), byteorder="big", signed=False)


# Carbon Events constants. Keep the raw values local to this narrowly scoped
# registration owner so the rest of ClosedRoom does not depend on Carbon.
K_EVENT_CLASS_KEYBOARD = fourcc("keyb")
K_EVENT_HOT_KEY_PRESSED = 5
K_EVENT_PARAM_DIRECT_OBJECT = fourcc("----")
TYPE_EVENT_HOT_KEY_ID = fourcc("hkid")

CMD_KEY = 1 << 8
SHIFT_KEY = 1 << 9

# Physical ANSI key codes from HIToolbox/Events.h.
KEY_R = 15
KEY_9 = 25
KEY_N = 45

_EVENT_HANDLER_RESULT = ctypes.c_int32
_OSSTATUS = ctypes.c_int32
_UINT32 = ctypes.c_uint32
_EVENT_HANDLER_PROC = ctypes.CFUNCTYPE(
    _EVENT_HANDLER_RESULT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
)


class EventTypeSpec(ctypes.Structure):
    _fields_ = [
        ("eventClass", _UINT32),
        ("eventKind", _UINT32),
    ]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [
        ("signature", _UINT32),
        ("id", _UINT32),
    ]


@dataclass(frozen=True, slots=True)
class HotKeySpec:
    identifier: int
    key_code: int
    modifiers: int
    label: str
    callback: Callable[[], None]


class CarbonHotKeyManager:
    """Register narrowly scoped global macOS hotkeys through Carbon.

    RegisterEventHotKey is used only for discrete modifier+key commands. It
    does not install a keyboard event tap, synthesize input, or require
    Accessibility permission for these meeting actions.
    """

    SIGNATURE = fourcc("CLRM")

    def __init__(self, specs: list[HotKeySpec], *, carbon=None) -> None:
        self._specs = list(specs)
        self._callbacks = {int(spec.identifier): spec.callback for spec in specs}
        self._carbon = carbon
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_refs: list[ctypes.c_void_p] = []
        self._handler_proc = None
        self._registered = False

    @staticmethod
    def supported() -> bool:
        return sys.platform == "darwin"

    @staticmethod
    def _framework_path() -> str:
        return "/System/Library/Frameworks/Carbon.framework/Carbon"

    def _load_carbon(self):
        if self._carbon is not None:
            return self._carbon
        if not self.supported():
            raise RuntimeError("macOS is required for native global hotkeys")
        framework = Path(self._framework_path())
        if not framework.exists():
            raise RuntimeError("Carbon framework is unavailable")
        self._carbon = ctypes.CDLL(str(framework))
        return self._carbon

    def _configure_functions(self, carbon) -> None:
        carbon.GetApplicationEventTarget.argtypes = []
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p,
            _EVENT_HANDLER_PROC,
            _UINT32,
            ctypes.POINTER(EventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.InstallEventHandler.restype = _OSSTATUS

        carbon.RegisterEventHotKey.argtypes = [
            _UINT32,
            _UINT32,
            EventHotKeyID,
            ctypes.c_void_p,
            _UINT32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = _OSSTATUS

        carbon.GetEventParameter.argtypes = [
            ctypes.c_void_p,
            _UINT32,
            _UINT32,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
        ]
        carbon.GetEventParameter.restype = _OSSTATUS

        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        carbon.UnregisterEventHotKey.restype = _OSSTATUS

        carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        carbon.RemoveEventHandler.restype = _OSSTATUS

    def start(self) -> list[str]:
        if self._registered:
            return []

        carbon = self._load_carbon()
        self._configure_functions(carbon)
        target = carbon.GetApplicationEventTarget()
        if not target:
            raise RuntimeError("Unable to resolve the macOS application event target")

        def handle_event(_next_handler, event_ref, _user_data):
            hot_key = EventHotKeyID()
            actual_size = ctypes.c_size_t()
            status = carbon.GetEventParameter(
                event_ref,
                K_EVENT_PARAM_DIRECT_OBJECT,
                TYPE_EVENT_HOT_KEY_ID,
                None,
                ctypes.sizeof(EventHotKeyID),
                ctypes.byref(actual_size),
                ctypes.byref(hot_key),
            )
            if status != 0:
                return status
            if hot_key.signature != self.SIGNATURE:
                return 0
            callback = self._callbacks.get(int(hot_key.id))
            if callback is None:
                return 0
            try:
                callback()
            except Exception:
                logger.exception("Native hotkey callback failed: id=%s", hot_key.id)
            return 0

        self._handler_proc = _EVENT_HANDLER_PROC(handle_event)
        event_spec = EventTypeSpec(
            eventClass=K_EVENT_CLASS_KEYBOARD,
            eventKind=K_EVENT_HOT_KEY_PRESSED,
        )
        status = carbon.InstallEventHandler(
            target,
            self._handler_proc,
            1,
            ctypes.byref(event_spec),
            None,
            ctypes.byref(self._handler_ref),
        )
        if status != 0:
            self._handler_proc = None
            raise RuntimeError(f"InstallEventHandler failed with OSStatus {status}")

        failures: list[str] = []
        for spec in self._specs:
            hot_key_ref = ctypes.c_void_p()
            hot_key_id = EventHotKeyID(
                signature=self.SIGNATURE,
                id=int(spec.identifier),
            )
            status = carbon.RegisterEventHotKey(
                int(spec.key_code),
                int(spec.modifiers),
                hot_key_id,
                target,
                0,
                ctypes.byref(hot_key_ref),
            )
            if status != 0 or not hot_key_ref.value:
                failures.append(spec.label)
                logger.warning(
                    "Native hotkey registration failed: label=%s status=%s",
                    spec.label,
                    status,
                )
                continue
            self._hotkey_refs.append(hot_key_ref)

        self._registered = bool(self._hotkey_refs)
        if not self._registered:
            self.stop()
            raise RuntimeError("No native meeting hotkeys could be registered")
        return failures

    def stop(self) -> None:
        carbon = self._carbon
        if carbon is not None:
            for ref in self._hotkey_refs:
                try:
                    carbon.UnregisterEventHotKey(ref)
                except Exception:
                    logger.exception("Failed to unregister native hotkey")
            if self._handler_ref.value:
                try:
                    carbon.RemoveEventHandler(self._handler_ref)
                except Exception:
                    logger.exception("Failed to remove native hotkey handler")
        self._hotkey_refs.clear()
        self._handler_ref = ctypes.c_void_p()
        self._handler_proc = None
        self._registered = False


DEFAULT_MEETING_HOTKEYS = {
    "toggle_recording": (KEY_R, CMD_KEY | SHIFT_KEY, "⌘⇧R"),
    "add_note": (KEY_N, CMD_KEY | SHIFT_KEY, "⌘⇧N"),
    "screenshot": (KEY_9, CMD_KEY | SHIFT_KEY, "⌘⇧9"),
}
