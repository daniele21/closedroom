"""
launchd.py — macOS LaunchAgent management for ClosedRoom.

Creates and removes a launchd plist so the ClosedRoom app launches automatically
when the user logs in.

The plist is installed at::

    ~/Library/LaunchAgents/com.closedroom.app.plist

Usage::

    from local_asr_server.launchd import install_launch_agent, uninstall_launch_agent
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from local_asr_server.paths import get_logs_dir

# ── Constants ─────────────────────────────────────────────────────────────────

_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def _get_plist_path() -> Path:
    """Return the LaunchAgent plist Path, dynamically resolved from the current app identity."""
    from local_asr_server.app_identity import get_app_identity
    return _LAUNCH_AGENTS_DIR / f"{get_app_identity().bundle_identifier}.plist"


# App bundle candidates (resolved at install time).
_APP_ROOTS = [
    Path("/Applications"),
    Path.home() / "Applications",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_app_binary() -> Path | None:
    """Locate the ClosedRoom binary in the current or installed app bundle."""
    if getattr(sys, "frozen", False):
        current_binary = Path(sys.executable).resolve()
        if current_binary.exists():
            return current_binary

    # Non-bundled CLI selection must not accidentally pick the Test app.
    for root in _APP_ROOTS:
        app = root / "ClosedRoom.app"
        binary = app / "Contents" / "MacOS" / "ClosedRoom"
        if binary.exists():
            return binary
    return None


def _generate_plist(binary_path: Path) -> str:
    """Generate the launchd plist XML content."""
    from local_asr_server.app_identity import get_app_identity
    bundle_id = get_app_identity().bundle_identifier
    logs = get_logs_dir()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{bundle_id}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{logs}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{logs}/stderr.log</string>
</dict>
</plist>
"""


def _ensure_log_dir() -> None:
    """Create the log directory used by the LaunchAgent."""
    get_logs_dir(create=True)


# ── Public API ────────────────────────────────────────────────────────────────

def is_launch_agent_installed() -> bool:
    """Return True if the LaunchAgent plist exists on disk."""
    return _get_plist_path().exists()


def install_launch_agent(app_binary: Path | None = None) -> Path:
    """
    Install the LaunchAgent plist so ClosedRoom starts at login.

    Args:
        app_binary: Path to the ClosedRoom binary inside the .app bundle.
            Auto-detected if None.

    Returns:
        The path to the installed plist file.

    Raises:
        FileNotFoundError: If the .app bundle cannot be found automatically.
        RuntimeError: If not on macOS.
    """
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent is only supported on macOS.")

    binary = app_binary or _find_app_binary()
    if binary is None:
        checked = [str(root / "ClosedRoom*.app") for root in _APP_ROOTS]
        raise FileNotFoundError(
            "ClosedRoom app not found in standard locations:\n"
            + "\n".join(f"  {p}" for p in checked)
            + "\nMove the app to /Applications/ first."
        )

    _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_log_dir()

    plist_content = _generate_plist(binary)
    plist_path = _get_plist_path()
    plist_path.write_text(plist_content, encoding="utf-8")

    # Load the agent immediately so the user doesn't need to log out
    try:
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Non-fatal: the plist is installed and will activate on next login
        pass

    return plist_path


def uninstall_launch_agent() -> None:
    """
    Remove the LaunchAgent plist and unload it from launchd.

    No-op if the plist does not exist.
    """
    plist_path = _get_plist_path()
    if not plist_path.exists():
        return

    # Unload the agent first so it stops immediately
    try:
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass  # Already unloaded or never loaded — safe to continue

    plist_path.unlink(missing_ok=True)
