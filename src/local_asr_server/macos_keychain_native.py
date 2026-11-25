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
# Isolated experimental backend. Never stores user vault keys.
VAULT_PROBE_SERVICE = "com.closedroom.app.secure-sync-vault-probe.v1"
LOCAL_VAULT_PROBE_SERVICE = "com.closedroom.app.secure-sync-local-development-probe.v1"
MAX_PROBE_PASSWORD_BYTES = 4096
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

    def __init__(self, *, service: str = SERVICE) -> None:
        if service not in (SERVICE, VAULT_PROBE_SERVICE, LOCAL_VAULT_PROBE_SERVICE):
            raise NativeKeychainError("Unapproved Keychain service")
        self.service = service
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
        sec.SecItemUpdate.argtypes = (ptr, ptr)
        sec.SecItemUpdate.restype = ctypes.c_int32
        self.cf, self.sec = cf, sec
        self._const = {
            k: ptr.in_dll(sec, k).value
            for k in ("kSecClass", "kSecClassGenericPassword", "kSecAttrService",
                      "kSecAttrAccount", "kSecValueData", "kSecReturnData",
                      "kSecMatchLimit", "kSecMatchLimitOne",
                      "kSecAttrAccessible", "kSecAttrAccessibleWhenUnlockedThisDeviceOnly",
                      "kSecUseDataProtectionKeychain")
        }
        self._true = ptr.in_dll(cf, "kCFBooleanTrue").value
        if service == LOCAL_VAULT_PROBE_SERVICE:
            # Diagnostic-only process: never let an ACL denial become an
            # interactive approval or silently broaden the trusted-app list.
            sec.SecKeychainSetUserInteractionAllowed.argtypes = (ctypes.c_ubyte,)
            sec.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32
            status = sec.SecKeychainSetUserInteractionAllowed(0)
            if status != SUCCESS:
                raise NativeKeychainError(f"Keychain interaction policy failed (OSStatus {status})")

    def _configure_query(self, query: int) -> None:
        """Select macOS Data Protection Keychain for every vault probe CRUD.

        kSecAttrAccessible* is defined for macOS only with
        kSecUseDataProtectionKeychain=true (not iCloud sync). The SAME
        qualifier is required for add, copy, update and delete. Never
        retry against the legacy login Keychain if access is denied.
        """
        if self.service == VAULT_PROBE_SERVICE:
            self.cf.CFDictionarySetValue(
                query, self._const["kSecUseDataProtectionKeychain"], self._true,
            )

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
            service = cf.CFStringCreateWithCString(None, self.service.encode("utf-8"), _UTF8)
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
            self._configure_query(q)
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
            # Per-device, unlocked-login-only data. No sync or backup migration.
            if self.service == VAULT_PROBE_SERVICE:
                self.cf.CFDictionarySetValue(
                    query, self._const["kSecAttrAccessible"],
                    self._const["kSecAttrAccessibleWhenUnlockedThisDeviceOnly"],
                )
            status = self.sec.SecItemAdd(query, None)
        if status != SUCCESS:
            raise NativeKeychainError(f"Keychain creation failed (OSStatus {status})")

    def update(self, account: str, secret: bytes) -> None:
        """Update only an existing Keychain item; never silently create."""
        with self._query(account) as query:
            # SecItemUpdate accepts only attributes to change.
            attrs = self.cf.CFDictionaryCreateMutable(None, 0, None, None)
            if not attrs:
                raise NativeKeychainError("Unable to allocate Keychain update")
            try:
                source = ctypes.create_string_buffer(secret)
                blob = self.cf.CFDataCreate(None, source, len(secret))
                if not blob:
                    raise NativeKeychainError("Unable to encode Keychain update")
                try:
                    self.cf.CFDictionarySetValue(attrs, self._const["kSecValueData"], blob)
                    status = self.sec.SecItemUpdate(query, attrs)
                finally:
                    self.cf.CFRelease(blob)
            finally:
                self.cf.CFRelease(attrs)
        if status != SUCCESS:
            raise NativeKeychainError(f"Keychain update failed (OSStatus {status})")

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


def _vault_probe_account(account: str) -> bool:
    """Allow only explicit synthetic hex IDs and a bounded known field suffix."""
    if not isinstance(account, str) or ":" not in account:
        return False
    vault_id, suffix = account.split(":", 1)
    if not _account_ok(vault_id):
        return False
    if suffix in ("master", "owner-signing", "owner-pin", "checkpoint",
                  "ledger-anchor", "ledger-prepare"):
        return True
    if suffix.startswith("epoch:"):
        value = suffix[6:]
        return bool(1 <= len(value) <= 6 and value.isascii() and value.isdecimal()
                    and str(int(value)) == value and 2 <= int(value) <= 999999)
    return False


class NativeVaultProbeBackend:
    """Test-only Keychain provider matching the isolated vault backend protocol.

    This does NOT authorize a vault, store real user keys or initialize sync.
    Only the explicitly selected synthetic service is accessible; no fallback.
    """

    def __init__(self, *, local_development: bool = False, _test_api: object | None = None) -> None:
        # Explicit selection only. File-based Keychain uses the OS default
        # creator-app ACL, not DPK entitlements. No fallback and no production
        # claims about ThisDeviceOnly, backup migration or rollback.
        self.service = LOCAL_VAULT_PROBE_SERVICE if local_development else VAULT_PROBE_SERVICE
        self._api = _SecurityAPI(service=self.service) if _test_api is None else _test_api

    def _check(self, service: str, account: str) -> None:
        if service != self.service or not _vault_probe_account(account):
            raise NativeKeychainError("Unapproved native vault probe account")

    def get_password(self, service: str, account: str) -> str | None:
        self._check(service, account)
        raw = self._api.get(account)
        if raw is None:
            return None
        if not isinstance(raw, bytes) or len(raw) > MAX_PROBE_PASSWORD_BYTES:
            raise NativeKeychainError("Invalid Keychain probe data")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NativeKeychainError("Invalid Keychain probe encoding") from exc

    def set_password(self, service: str, account: str, password: str) -> None:
        self._check(service, account)
        if not isinstance(password, str):
            raise NativeKeychainError("Invalid probe input")
        raw = password.encode("utf-8")
        if len(raw) > MAX_PROBE_PASSWORD_BYTES:
            raise NativeKeychainError("Probe input too long")
        # The Keychain update is atomic per record, not a cross-record CAS.
        # No claim is made about multi-record vault state consistency.
        old = self._api.get(account)
        if old is None:
            self._api.add(account, raw)
        else:
            self._api.update(account, raw)
        if self._api.get(account) != raw:
            raise NativeKeychainError("Keychain probe readback failed")

    def delete_password(self, service: str, account: str) -> None:
        self._check(service, account)
        self._api.delete(account)
        if self._api.get(account) is not None:
            raise NativeKeychainError("Keychain probe deletion unverified")
