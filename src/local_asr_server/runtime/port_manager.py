from __future__ import annotations

import json
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager
import fcntl
from urllib.request import urlopen

from local_asr_server.app_identity import get_app_identity
from local_asr_server.paths import get_runtime_state_file
from local_asr_server.runtime.models import LOCAL_SERVICE_HOST

RUNTIME_STATE_SCHEMA_VERSION = 1
class PortInUseError(RuntimeError):
    """Raised when a requested port belongs to an unrelated process."""


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def query_closedroom_health(host: str, port: int) -> dict[str, Any]:
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=1.0) as response:
            payload = json.loads(response.read())
    except Exception:
        return {}
    if payload.get("ok") and payload.get("server") == "local-asr-server":
        return payload
    return {}


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _api_key(host: str, port: int) -> str:
    return f"{host}:{port}"


def _api_entries(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = state.get("apis")
    if isinstance(entries, dict):
        return {
            str(key): value
            for key, value in entries.items()
            if isinstance(value, dict)
        }
    legacy = state.get("api")
    if isinstance(legacy, dict) and legacy.get("port"):
        host = str(legacy.get("host") or LOCAL_SERVICE_HOST)
        return {_api_key(host, int(legacy["port"])): legacy}
    return {}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def runtime_instance_lock(*, lock_path: Path | None = None) -> Iterator[None]:
    """One local profile writer per process, without signalling other processes.

    The OS-managed advisory lock lives for the entire server/app lifetime.
    Dev and bundled app use different profile paths. Closing or crashing the
    owner releases the lock automatically; no stale PID may terminate a peer.
    """
    path = lock_path or get_runtime_state_file().with_name("instance.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise PortInUseError(
                "Another ClosedRoom instance is already using this data profile. "
                "Keep the existing instance open or close it normally before retrying."
            ) from exc
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def prepare_api_port(
    port: int,
    *,
    host: str = LOCAL_SERVICE_HOST,
    state_path: Path | None = None,
) -> None:
    """Reject occupied ports without touching any running process or state.

    A caller must hold runtime_instance_lock for the active profile before
    creating writable services. A free port is not permission to take over
    another profile's data and an HTTP health response is never kill authority.
    """
    if not (1 <= port <= 65535):
        raise ValueError("API port must be between 1 and 65535")
    if not is_port_open(host, port):
        return
    health = query_closedroom_health(host, port)
    if health:
        raise PortInUseError(
            f"ClosedRoom is already listening on {host}:{port}. "
            "The existing app was left running; choose a different --port."
        )
    raise PortInUseError(
        f"Port {host}:{port} is occupied. The owning process was not stopped; "
        "choose a different --port."
    )


def register_api_runtime(
    port: int,
    *,
    host: str = LOCAL_SERVICE_HOST,
    state_path: Path | None = None,
) -> None:
    path = state_path or get_runtime_state_file()
    identity = get_app_identity()
    entry = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "command": " ".join([str(item) for item in [os.path.basename(os.sys.executable), *os.sys.argv]]),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "bundle_identifier": identity.bundle_identifier,
        "app_version": identity.version,
        "bundled": identity.bundled,
    }
    _write_state(path, {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
        "apis": {_api_key(host, port): entry},
    })


def clear_api_runtime(
    port: int,
    *,
    host: str = LOCAL_SERVICE_HOST,
    state_path: Path | None = None,
    pid: int | None = None,
) -> None:
    path = state_path or get_runtime_state_file()
    state = _read_state(path)
    entries = _api_entries(state)
    key = _api_key(host, port)
    api_state = entries.get(key, {})
    expected_pid = os.getpid() if pid is None else pid
    if int(api_state.get("pid") or 0) == expected_pid:
        entries.pop(key, None)
        if entries:
            _write_state(path, {
                "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
                "apis": entries,
            })
        else:
            path.unlink(missing_ok=True)
