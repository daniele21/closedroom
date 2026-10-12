from __future__ import annotations

import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from local_asr_server.meeting_detection import (
    ActivityObservation, AudioPropertyAddress, CoreAudioInputObserver,
    _PROCESS_BUNDLE, _PROCESS_INPUT, _PROCESS_LIST, _PROCESS_PID,
)


class SimulatedCoreAudio:
    """CoreAudio signatures and ownership, without opening a real microphone."""

    def __init__(self, processes):
        self.processes = processes
        self.AudioObjectGetPropertyData = Mock(side_effect=self.get)
        self.AudioObjectGetPropertyDataSize = Mock(side_effect=self.size)

    @staticmethod
    def ptr(address):
        return ctypes.cast(address, ctypes.POINTER(ctypes.c_uint32))

    @staticmethod
    def selector(address):
        return ctypes.cast(address, ctypes.POINTER(AudioPropertyAddress)).contents.selector

    def size(self, object_id, address, qualifier_size, qualifier, out_size):
        if object_id != 1 or self.selector(address) != _PROCESS_LIST:
            return -1
        self.ptr(out_size).contents.value = 4 * len(self.processes)
        return 0

    def get(self, object_id, address, qualifier_size, qualifier, size, out):
        selector = self.selector(address)
        if selector == _PROCESS_LIST:
            ids = (ctypes.c_uint32 * len(self.processes))(*sorted(self.processes))
            ctypes.memmove(out, ids, ctypes.sizeof(ids))
            self.ptr(size).contents.value = ctypes.sizeof(ids)
            return 0
        data = self.processes.get(object_id)
        if data is None:
            return -1
        if selector == _PROCESS_INPUT:
            self.ptr(size).contents.value = 4
            self.ptr(out).contents.value = int(data["input"])
            return 0
        if selector == _PROCESS_PID:
            self.ptr(size).contents.value = 4
            self.ptr(out).contents.value = data["pid"]
            return 0
        if selector == _PROCESS_BUNDLE:
            self.ptr(size).contents.value = ctypes.sizeof(ctypes.c_void_p)
            ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p)).contents.value = data.get("cfptr")
            return 0 if data.get("cfptr") else -1
        return -1


class CoreAudioBundleIdentityTests(unittest.TestCase):
    def test_running_input_uses_coreaudio_bundle_id_even_if_ns_application_unavailable(self):
        audio = SimulatedCoreAudio({
            12: {"input": True, "pid": 1200, "cfptr": 12000},
            14: {"input": False, "pid": 1400, "cfptr": 14000},
            16: {"input": True, "pid": 1600, "cfptr": 16000},
        })
        name_by_ptr = {12000: b"com.microsoft.teams2", 14000: b"us.zoom.xos", 16000: b"com.google.Chrome"}
        releases = []
        def convert(ptr, buf, nbytes, encoding):
            data = name_by_ptr.get(ptr.value, b"")
            ctypes.memmove(buf, data + b"\\x00", len(data) + 1)
            return True
        cf = SimpleNamespace(CFStringGetCString=Mock(side_effect=convert),
                             CFRelease=Mock(side_effect=lambda ptr: releases.append(ptr.value)))
        pid_lookup = Mock(return_value=None)
        with patch("local_asr_server.meeting_detection.ctypes.CDLL", return_value=cf):
            result = CoreAudioInputObserver(audio=audio, app_lookup=pid_lookup).scan()
        self.assertEqual(result.capability, "supported")
        self.assertEqual(result.active_bundle_ids, frozenset({"com.microsoft.teams2"}))
        self.assertEqual(result.active_input_processes, 2)
        self.assertEqual(result.unattributed_input_processes, 0)
        self.assertEqual(releases, [12000, 16000])
        pid_lookup.assert_not_called()

    def test_no_bundle_metadata_uses_pid_only_as_fallback_and_never_guesses(self):
        audio = SimulatedCoreAudio({11: {"input": True, "pid": 777},
                                    12: {"input": True, "pid": 778}})
        lookup = Mock(side_effect=lambda pid: "com.microsoft.teams2" if pid == 777 else None)
        result = CoreAudioInputObserver(audio=audio, app_lookup=lookup).scan()
        self.assertEqual(result.capability, "supported")
        self.assertEqual(result.active_bundle_ids, frozenset({"com.microsoft.teams2"}))
        self.assertEqual(result.active_input_processes, 2)
        self.assertEqual(result.unattributed_input_processes, 1)
        self.assertEqual(lookup.call_count, 2)

    def test_unsupported_backend_does_not_synthesize_meeting(self):
        observer = CoreAudioInputObserver(audio=SimulatedCoreAudio({
            12: {"input": False, "pid": 777, "cfptr": 12000}
        }), app_lookup=Mock(return_value="com.microsoft.teams2"))
        result = observer.scan()
        self.assertEqual(result, ActivityObservation("supported"))


if __name__ == "__main__":
    unittest.main()
