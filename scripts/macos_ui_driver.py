#!/usr/bin/env python3
"""Bounded macOS Accessibility driver used by ClosedRoom target-Mac evidence.

The driver compiles a tiny Swift helper into a stable ignored cache and then
talks directly to AXUIElement/CGEvent. It intentionally avoids System Events
tree enumeration, which can block indefinitely on large WKWebView accessibility
trees.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable


class UIAutomationError(RuntimeError):
    """Base error for target-Mac UI automation infrastructure."""


class AccessibilityPermissionRequired(UIAutomationError):
    """The stable macOS Accessibility helper is not trusted."""


class UIAutomationTimeout(UIAutomationError):
    """A bounded Accessibility action exceeded its allowed duration."""


class UIAutomationUnavailable(UIAutomationError):
    """Required target-Mac UI automation tooling is unavailable."""


TRANSIENT_WINDOW_ERROR = "closedroom_window_missing"
DIAGNOSTIC_KEYS = (
    "running_application_present",
    "running_application_terminated",
    "running_application_active",
    "running_application_hidden",
    "activation_policy",
    "ax_windows_result",
    "ax_windows_count",
    "ax_windows_positive_bounds_count",
    "ax_windows_minimized_count",
    "ax_main_window_result",
    "ax_main_window_present",
    "ax_focused_window_result",
    "ax_focused_window_present",
    "cg_window_count",
    "cg_onscreen_window_count",
    "cg_normal_window_count",
    "cg_onscreen_normal_window_count",
)


class MacOSUIDriver:
    def __init__(
        self,
        source: Path | None = None,
        *,
        cache_root: Path | None = None,
        action_timeout: float = 5.0,
        compile_timeout: float = 30.0,
    ) -> None:
        self.source = source or Path(__file__).with_name("macos_ax_helper.swift")
        self.cache_root = (
            cache_root
            or self.source.parent.parent / ".cache" / "closedroom" / "macos-ax-helper"
        )
        self.action_timeout = action_timeout
        self.compile_timeout = compile_timeout
        self._binary: Path | None = None

    def close(self) -> None:
        self._binary = None

    def helper_binary_path(self) -> Path:
        try:
            source_bytes = self.source.read_bytes()
        except OSError as exc:
            raise UIAutomationUnavailable(f"macos_ax_helper_missing:{self.source}") from exc
        fingerprint = hashlib.sha256(source_bytes).hexdigest()[:16]
        architecture = platform.machine() or "unknown"
        return self.cache_root / architecture / fingerprint / "closedroom-ax-helper"

    def _xcrun(self) -> str:
        if platform.system() != "Darwin":
            raise UIAutomationUnavailable("macos_accessibility_driver_requires_darwin")
        if not self.source.is_file():
            raise UIAutomationUnavailable(f"macos_ax_helper_missing:{self.source}")
        xcrun = shutil.which("xcrun")
        if not xcrun:
            raise UIAutomationUnavailable("xcrun_missing_for_macos_ax_helper")
        try:
            result = subprocess.run(
                [xcrun, "--sdk", "macosx", "--find", "swiftc"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise UIAutomationTimeout("swiftc_discovery_timeout") from exc
        except subprocess.CalledProcessError as exc:
            raise UIAutomationUnavailable((exc.stderr or exc.stdout or "swiftc_not_found").strip()) from exc
        if not result.stdout.strip():
            raise UIAutomationUnavailable("swiftc_not_found")
        return xcrun

    def _ensure_binary(self) -> Path:
        if self._binary is not None and self._binary.is_file():
            return self._binary

        binary = self.helper_binary_path()
        if binary.is_file() and os.access(binary, os.X_OK):
            self._binary = binary
            return binary

        xcrun = self._xcrun()
        binary.parent.mkdir(parents=True, exist_ok=True)
        temporary_binary = binary.with_name(f".{binary.name}.tmp-{os.getpid()}")
        command = [
            xcrun,
            "--sdk",
            "macosx",
            "swiftc",
            str(self.source),
            "-O",
            "-framework",
            "AppKit",
            "-framework",
            "ApplicationServices",
            "-o",
            str(temporary_binary),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.compile_timeout,
            )
            os.replace(temporary_binary, binary)
        except subprocess.TimeoutExpired as exc:
            temporary_binary.unlink(missing_ok=True)
            raise UIAutomationTimeout("macos_ax_helper_compile_timeout") from exc
        except subprocess.CalledProcessError as exc:
            temporary_binary.unlink(missing_ok=True)
            message = (exc.stderr or exc.stdout or "macos_ax_helper_compile_failed").strip()
            raise UIAutomationUnavailable(message) from exc
        except OSError as exc:
            temporary_binary.unlink(missing_ok=True)
            raise UIAutomationUnavailable(f"macos_ax_helper_cache_failed:{exc}") from exc

        self._binary = binary
        return binary

    def diagnostics(self, pid: int) -> dict[str, Any]:
        """Return bounded process/window metadata without labels, titles or meeting text."""
        binary = self._ensure_binary()
        try:
            result = subprocess.run(
                [str(binary), str(pid), "diagnose"],
                capture_output=True,
                text=True,
                timeout=min(max(self.action_timeout, 0.1), 2.0),
            )
        except subprocess.TimeoutExpired as exc:
            raise UIAutomationTimeout("ui_window_diagnostic_timeout") from exc

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode == 77 or "accessibility_permission_required" in error.lower():
            raise AccessibilityPermissionRequired("accessibility_helper_permission_required")
        if result.returncode:
            raise UIAutomationError("ui_window_diagnostic_unavailable")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise UIAutomationError("ui_window_diagnostic_invalid_json") from exc
        if not isinstance(payload, dict):
            raise UIAutomationError("ui_window_diagnostic_invalid_payload")
        return {key: payload.get(key) for key in DIAGNOSTIC_KEYS}

    def _window_missing_error(self, pid: int) -> UIAutomationError:
        try:
            snapshot = self.diagnostics(pid)
        except Exception:
            return UIAutomationError(f"{TRANSIENT_WINDOW_ERROR}|diagnostic=unavailable")
        fields = [TRANSIENT_WINDOW_ERROR]
        for key in DIAGNOSTIC_KEYS:
            value = snapshot.get(key)
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int):
                rendered = str(value)
            else:
                rendered = "unknown"
            fields.append(f"{key}={rendered}")
        return UIAutomationError("|".join(fields))

    def _invoke(self, pid: int, action: str, labels: Iterable[str] = ()) -> str:
        binary = self._ensure_binary()
        command = [str(binary), str(pid), action, *[str(label) for label in labels]]
        deadline = time.monotonic() + self.action_timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._window_missing_error(pid)
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=remaining,
                )
            except subprocess.TimeoutExpired as exc:
                raise UIAutomationTimeout(
                    f"ui_automation_timeout:{action}:{self.action_timeout:g}s"
                ) from exc

            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode == 77 or "accessibility_permission_required" in error.lower():
                raise AccessibilityPermissionRequired("accessibility_helper_permission_required")
            if result.returncode and error == TRANSIENT_WINDOW_ERROR:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self._window_missing_error(pid)
                time.sleep(min(0.1, remaining))
                continue
            if result.returncode:
                raise UIAutomationError(
                    error or output or f"ui_automation_failed:{action}:{result.returncode}"
                )
            return output

    def window_accessible(self, pid: int) -> bool:
        return self._invoke(pid, "window").lower() == "true"

    def window_rect(self, pid: int) -> str:
        raw = self._invoke(pid, "rect")
        parts = [int(float(item.strip())) for item in raw.split(",")]
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise UIAutomationError(f"invalid_closedroom_window_bounds:{raw}")
        return ",".join(str(item) for item in parts)

    def exists(self, pid: int, labels: Iterable[str]) -> bool:
        return self._invoke(pid, "exists", labels).lower() == "true"

    def press(self, pid: int, labels: Iterable[str]) -> None:
        if self._invoke(pid, "press", labels).lower() != "pressed":
            raise UIAutomationError("ax_press_did_not_complete")

    def focused(self, pid: int) -> str:
        return self._invoke(pid, "focused") or "unknown"

    def key(self, pid: int, name: str) -> None:
        if name not in {"cmd-k", "escape", "cmd-q"}:
            raise ValueError(f"unsupported key action: {name}")
        self._invoke(pid, name)


_DEFAULT_DRIVER = MacOSUIDriver()


def default_driver() -> MacOSUIDriver:
    return _DEFAULT_DRIVER
