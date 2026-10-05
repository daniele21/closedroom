"""
paths.py — Centralized path resolution for ClosedRoom.

Handles the difference between:
  - Dev mode: running directly with `uv run local-asr` from the project root.
  - Bundle mode: running inside the macOS .app bundle (PyInstaller frozen binary).

All path helpers are pure functions with no side effects. Directories are
created on demand only where explicitly noted.
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

# ── App identity ──────────────────────────────────────────────────────────────

APP_NAME = "ClosedRoom"
APP_BUNDLE_ID = "com.closedroom.app"
NATIVE_CAPTURE_HELPER_APP_NAME = "ClosedRoomNativeCapture.app"
NATIVE_CAPTURE_HELPER_EXECUTABLE = "ClosedRoomNativeCapture"
SPEAKER_DIARIZATION_HELPER_EXECUTABLE = "speaker-diarization-helper"


# ── Bundle detection ──────────────────────────────────────────────────────────

def is_bundled() -> bool:
    """Return True when running inside a PyInstaller .app bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_bundle_dir() -> Path:
    """
    Return the directory that contains bundled resources.

    In bundle mode this is ``sys._MEIPASS`` (the PyInstaller temp dir that
    holds everything from ``Contents/Resources``).  In dev mode it falls back
    to the package root so the same relative paths work.
    """
    if is_bundled():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # Dev mode: two levels up from this file → project root/src/local_asr_server
    return Path(__file__).parent


def get_app_contents_dir() -> Path | None:
    """Return the app bundle ``Contents`` directory when running bundled."""
    if not is_bundled():
        return None

    executable = Path(sys.executable).resolve()
    if executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
        return executable.parent.parent

    meipass = Path(sys._MEIPASS).resolve()  # type: ignore[attr-defined]
    for candidate in [meipass, *meipass.parents]:
        if candidate.name == "Contents":
            return candidate

    return None


# ── macOS standard directories ─────────────────────────────────────────────────

def get_app_support_dir() -> Path:
    """
    Return ``~/Library/Application Support/ClosedRoom/``, creating it if needed.

    This is the canonical location for user data on macOS (settings, models,
    cache).  We create the directory on first access.
    """
    base = Path.home() / "Library" / "Application Support" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_cache_dir() -> Path:
    """
    Return the cache directory, creating it if needed.

    - **Bundle mode**: ``~/Library/Caches/ClosedRoom/`` (macOS convention).
    - **Dev mode**: ``.cache/`` at the project root (preserves existing behavior).
    """
    if is_bundled():
        cache = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        # Keep existing dev-mode location: <project-root>/.cache/
        cache = Path(__file__).parent.parent.parent / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def get_models_dir() -> Path:
    """
    Return ``~/Library/Application Support/ClosedRoom/models/``.

    Whisper models are downloaded here on first use and persist across
    app updates.
    """
    models = get_app_support_dir() / "models"
    models.mkdir(parents=True, exist_ok=True)
    return models


def get_settings_file() -> Path:
    """Return the path to ``settings.json`` (not created here)."""
    return get_app_support_dir() / "settings.json"


def get_prompts_file() -> Path:
    """Return the path to ``prompts.json`` (not created here)."""
    return get_app_support_dir() / "prompts.json"


def get_local_llm_params_file() -> Path:
    """Return the path to ``local_llm_params.json`` (not created here)."""
    return get_app_support_dir() / "local_llm_params.json"




def get_runtime_state_file() -> Path:
    """Return the local runtime state file path."""
    return get_app_support_dir() / "runtime-state.json"


def get_logs_dir(create: bool = True) -> Path:
    """Return ``~/Library/Logs/ClosedRoom/``, creating it by default."""
    logs = Path.home() / "Library" / "Logs" / APP_NAME
    if create:
        logs.mkdir(parents=True, exist_ok=True)
    return logs


def get_service_log_file(service_name: str, create_parent: bool = True) -> Path:
    """Return the log file path for a managed local service."""
    safe_name = service_name.replace("/", "-").replace("..", "-")
    return get_logs_dir(create=create_parent) / f"{safe_name}.log"


# ── Resource path helpers ─────────────────────────────────────────────────────

def get_resource_path(relative: str) -> Path:
    """
    Resolve a path relative to the bundle's Resources directory.

    Example::

        get_resource_path("static/index.html")

    In dev mode the path is resolved from the ``static/`` directory that
    lives next to this module (i.e. ``src/local_asr_server/static/``).
    """
    return get_bundle_dir() / relative


def get_static_dir() -> Path:
    """Return the directory that serves the web UI static files."""
    if is_bundled():
        return get_bundle_dir() / "static"
    dev_static_dir = os.environ.get("CLOSEDROOM_DEV_STATIC_DIR")
    if dev_static_dir:
        return Path(dev_static_dir).expanduser().resolve()
    # Direct create_app() callers and tests keep the committed static fallback.
    return Path(__file__).parent / "static"


# ── External binary helpers ───────────────────────────────────────────────────

def get_ffmpeg_path() -> str:
    """
    Return the path to the ffmpeg binary.

    Priority:
      1. Bundled binary inside the .app (``Resources/ffmpeg``).
      2. System ffmpeg found via ``shutil.which``.

    Raises ``FileNotFoundError`` if ffmpeg cannot be located.
    """
    if is_bundled():
        bundled = get_bundle_dir() / "ffmpeg"
        if bundled.exists():
            return str(bundled)

    system = shutil.which("ffmpeg")
    if system:
        return system

    raise FileNotFoundError(
        "ffmpeg not found. Install it with: brew install ffmpeg"
    )


def get_ffprobe_path() -> str:
    """
    Return the path to the ffprobe binary.

    Priority:
      1. Bundled binary inside the .app (``Resources/ffprobe``).
      2. System ffprobe found via ``shutil.which``.

    Raises ``FileNotFoundError`` if ffprobe cannot be located.
    """
    if is_bundled():
        bundled = get_bundle_dir() / "ffprobe"
        if bundled.exists():
            return str(bundled)

    system = shutil.which("ffprobe")
    if system:
        return system

    raise FileNotFoundError(
        "ffprobe not found. Install it with: brew install ffmpeg"
    )



def get_audio_helper_path() -> Path:
    """
    Return the path to the pre-compiled Swift audio helper binary.

    In bundle mode the pre-compiled binary is included in Resources.
    In dev mode we rely on the runtime compilation path managed by
    ``macos_audio_helper.compile``.
    """
    if is_bundled():
        return get_bundle_dir() / "audio-helper"

    # Dev mode: use the compile-time cache location
    from local_asr_server.macos_audio_helper.compile import _BINARY_PATH  # type: ignore
    return _BINARY_PATH


def get_native_capture_helper_path() -> Path:
    """
    Return the path to the native ScreenCaptureKit capture helper.

    Bundle mode prefers the embedded helper app so macOS/TCC sees a stable
    bundle identifier and usage-description Info.plist. Dev mode uses the cache
    managed by ``native_capture_helper.compile``.
    """
    if is_bundled():
        contents_dir = get_app_contents_dir()
        helper_relative = (
            Path(NATIVE_CAPTURE_HELPER_APP_NAME)
            / Path("Contents")
            / "MacOS"
            / NATIVE_CAPTURE_HELPER_EXECUTABLE
        )
        candidates: list[Path] = []
        if contents_dir is not None:
            candidates.extend([
                contents_dir / "Helpers" / helper_relative,
                contents_dir / "Frameworks" / "native-capture-helper",
                contents_dir / "Resources" / "native-capture-helper",
            ])
        candidates.append(get_bundle_dir() / "native-capture-helper")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    from local_asr_server.native_capture_helper.compile import _BINARY_PATH  # type: ignore
    return _BINARY_PATH


def get_speaker_diarization_helper_path() -> Path:
    """Return the FluidAudio batch diarization helper in dev or bundle mode."""
    if is_bundled():
        contents_dir = get_app_contents_dir()
        candidates = []
        if contents_dir is not None:
            candidates.extend([
                contents_dir / "Frameworks" / SPEAKER_DIARIZATION_HELPER_EXECUTABLE,
                contents_dir / "Resources" / SPEAKER_DIARIZATION_HELPER_EXECUTABLE,
            ])
        candidates.append(get_bundle_dir() / SPEAKER_DIARIZATION_HELPER_EXECUTABLE)
        return next((path for path in candidates if path.exists()), candidates[0])

    from local_asr_server.speaker_diarization_helper.compile import _BINARY_PATH  # type: ignore
    return _BINARY_PATH