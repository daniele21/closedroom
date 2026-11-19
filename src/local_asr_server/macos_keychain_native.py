"""ClosedRoom macOS Security.framework Keychain adapter, currently diagnostic-only.

Uses the native signed process identity, not an external "security" CLI.
No cloud, filesystem fallback, password prompts, user vaults or app settings.
The app does NOT enroll any sync identity through this module yet.
"""
from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from typing import Iterator

SERVICE = "com.closedroom.app.secure-sync-probe.v1"
ITEM_NOT_FOUND = -25300
DUPLICATE_ITEM = -25299
SUCCESS = 0
_UTF8 = 0x08000100


class NativeKeychainError(RuntimeError):
    """Security.framework could not securely perform the requested operation."""


def _account_ok(account: str) -> bool:
    return (
        isinstance(account, str)
        and len(account) == 32
        and all(c in "0123456789abcdef" for c in account)
    )


class _SecurityAPI:
    """Low-level macOS Keychain bindings. All created CoreFoundation refs released."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise NativeKeychainError("macOS Security.framework is required")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        ptr = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = (ptr, ctypes.c_char_p, ctypes.c_uint32)
        cf.CFStringCreateWithCString.restype = ptr
        cf.CFDataCreate.argtypes = (ptr, ctypes.c_void_p, ctypes.c_long)
        cf.CFDataCreate.restype = ptr
        cf.CFDictionaryCreateMutable.argtypes = (ptr, ctypes.c_long, ptr, ptr)
        cf.CFDictionaryCreateMutable.restype = ptr
        cf.CFDictionarySetValue.argtypes = (ptr, ptr, ptr)
        cf.CFDictionarySetValue.restype = None
        cf.CFRelease.argtypes = (ptr,)
        cf.CFRelease.restype = None
        cf.CFGetTypeID.argtypes = (ptr,)
        cf.CFGetTypeID.restype = ctypes.c_ulong
        cf.CFDataGetTypeID.restype = ctypes.c_ulong
        cf.CFDataGetLength.argtypes = (ptr,)
        cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = (ptr,)
        cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        sec.SecItemAdd.argtypes = (ptr, ctypes.POINTER(ptr))
        sec.SecItemAdd.restype = ctypes.c_int32
        sec.SecItemCopyMatching.argtypes = (ptr, ctypes.POINTER(ptr))
        sec.SecItemCopyMatching.restype = ctypes.c_int32
        sec.SecItemDelete.argtypes = (ptr,)
        sec.SecItemDelete.restype = ctypes.c_int32
        self.cf, self.sec = cf, sec
        self._const = {
            k: ptr.in_dll(sec, k).value
            for k in ("kSecClass", "kSecClassGenericPassword", "kSecAttrService",
                      "kSecAttrAccount", "kSecValueData", "kSecReturnData",
                      "kSecMatchLimit", "kSecMatchLimitOne")
        }
        self._true = ptr.in_dll(cf, "kCFBooleanTrue").value

    @contextmanager
    def _query(self, account: str, data: bytes | None = None, *,
               read: bool = False) -> Iterator[int]:
        created: list[int] = []
        cf = self.cf
        try:
            q = cf.CFDictionaryCreateMutable(None, 0, None, None)
            if not q:
                raise NativeKeychainError("Could not create Keychain query")
            created.append(q)
            service = cf.CFStringCreateWithCString(None, SERVICE.encode("utf-8"), _UTF8)
            acct = cf.CFStringCreateWithCString(None, account.encode("ascii"), _UTF8)
            if not service or not acct:
                if service:
                    created.append(service)
                if acct:
                    created.append(acct)
                raise NativeKeychainError("Could not encode Keychain account")
            created.extend([service, acct])
            for key, value in (
                ("kSecClass", self._const["kSecClassGenericPassword"]),
                ("kSecAttrService", service),
                ("kSecAttrAccount", acct),
            ):
                cf.CFDictionarySetValue(q, self._const[key], value)
            if data is not None:
                # CFDataCreate copies bytes; the transient C buffer is never logged.
                source = ctypes.create_string_buffer(data)
                blob = cf.CFDataCreate(None, source, len(data))
                if not blob:
                    raise NativeKeychainError("Could not create Keychain value")
                created.append(blob)
                cf.CFDictionarySetValue(q, self._const["kSecValueData"], blob)
            if read:
                cf.CFDictionarySetValue(q, self._const["kSecReturnData"], self._true)
                cf.CFDictionarySetValue(
                    q, self._const["kSecMatchLimit"], self._const["kSecMatchLimitOne"],
                )
            yield q
        finally:
            for ref in reversed(created):
                cf.CFRelease(ref)

    def get(self, account: str) -> bytes | None:
        with self._query(account, read=True) as query:
            value = ctypes.c_void_p()
            status = self.sec.SecItemCopyMatching(query, ctypes.byref(value))
        if status == ITEM_NOT_FOUND:
            return None
        if status != SUCCESS:
            if value.value:
                self.cf.CFRelease(value)
            raise NativeKeychainError(f"Keychain read failed (OSStatus {status})")
        if not value.value:
            raise NativeKeychainError("Keychain returned no value")
        try:
            if self.cf.CFGetTypeID(value) != self.cf.CFDataGetTypeID():
                raise NativeKeychainError("Unexpected Keychain result type")
            length = self.cf.CFDataGetLength(value)
            if not 0 <= length <= 8192:
                raise NativeKeychainError("Invalid Keychain value length")
            return ctypes.string_at(self.cf.CFDataGetBytePtr(value), length)
        finally:
            self.cf.CFRelease(value)

    def add(self, account: str, secret: bytes) -> None:
        with self._query(account, data=secret) as query:
            status = self.sec.SecItemAdd(query, None)
        if status != SUCCESS:
            raise NativeKeychainError(f"Keychain creation failed (OSStatus {status})")

    def delete(self, account: str) -> None:
        with self._query(account) as query:
            status = self.sec.SecItemDelete(query)
        if status not in (SUCCESS, ITEM_NOT_FOUND):
            raise NativeKeychainError(f"Keychain cleanup failed (OSStatus {status})")


class MacKeychain:
    """Minimal fail-closed native adapter; diagnostic service only."""

    def __init__(self, *, _test_api: object | None = None) -> None:
        self._api = _SecurityAPI() if _test_api is None else _test_api

    def load(self, account: str) -> bytes | None:
        if not _account_ok(account):
            raise NativeKeychainError("Invalid Keychain account")
        value = self._api.get(account)
        if value is not None and (not isinstance(value, bytes) or len(value) != 32):
            raise NativeKeychainError("Invalid stored Keychain secret")
        return value

    def create(self, account: str, secret: bytes) -> None:
        if not _account_ok(account) or not isinstance(secret, bytes) or len(secret) != 32:
            raise NativeKeychainError("Invalid Keychain input")
        # SecItemAdd is atomic with respect to duplicate account and fails closed.
        self._api.add(account, secret)

    def delete(self, account: str) -> None:
        if not _account_ok(account):
            raise NativeKeychainError("Invalid Keychain account")
        self._api.delete(account)
