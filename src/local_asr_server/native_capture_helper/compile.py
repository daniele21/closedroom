from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

_MODULE_DIR = Path(__file__).parent
_SWIFT_SOURCE = _MODULE_DIR / "native_capture_helper.swift"
_PROJECT_ROOT = _MODULE_DIR.parents[2]
_CACHE_DIR = _PROJECT_ROOT / ".cache" / "native-capture-helper"
_BINARY_PATH = _CACHE_DIR / "native-capture-helper"
_HASH_PATH = _CACHE_DIR / "source.sha256"


def _swift_source_hash() -> str:
    return hashlib.sha256(_SWIFT_SOURCE.read_bytes()).hexdigest()


def _is_binary_up_to_date() -> bool:
    return (
        _BINARY_PATH.exists()
        and _HASH_PATH.exists()
        and _HASH_PATH.read_text().strip() == _swift_source_hash()
    )


def _find_swiftc() -> str | None:
    import shutil
    return shutil.which("swiftc") or ("/usr/bin/swiftc" if Path("/usr/bin/swiftc").exists() else None)


def compile_helper(force: bool = False) -> str:
    if sys.platform != "darwin":
        raise RuntimeError("The native capture helper is only available on macOS.")
    if not _SWIFT_SOURCE.exists():
        raise RuntimeError(f"Swift source not found: {_SWIFT_SOURCE}")
    if not force and _is_binary_up_to_date():
        return str(_BINARY_PATH)
    swiftc = _find_swiftc()
    if swiftc is None:
        raise RuntimeError("Swift compiler (swiftc) not found. Install Xcode Command Line Tools.")
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        swiftc,
        "-O",
        "-o",
        str(_BINARY_PATH),
        str(_SWIFT_SOURCE),
        "-framework",
        "Foundation",
        "-framework",
        "AVFoundation",
        "-framework",
        "ScreenCaptureKit",
        "-framework",
        "AppKit",
    ]
    module_cache = _CACHE_DIR / "clang-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "CLANG_MODULE_CACHE_PATH": str(module_cache)},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Native capture helper compilation failed:\n{result.stderr}")
    _HASH_PATH.write_text(_swift_source_hash())
    logger.info("Native capture helper compiled successfully: %s", _BINARY_PATH)
    return str(_BINARY_PATH)


def get_helper_binary() -> str:
    from local_asr_server.paths import get_native_capture_helper_path, is_bundled

    if is_bundled():
        bundled = get_native_capture_helper_path()
        if bundled.exists():
            return str(bundled)
        raise RuntimeError(f"Bundled native capture helper not found at: {bundled}")
    return compile_helper(force=False)