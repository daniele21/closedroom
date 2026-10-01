#!/usr/bin/env python3
"""Smoke the frozen ClosedRoom executable and prove zero-residue server lifecycle."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import plistlib
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", help="Path to a built .app; defaults to latest finalized build")
    parser.add_argument("--root", default=".")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--evidence", help="Optional evidence JSON path")
    return parser.parse_args()


def latest_finalized_app(root: Path) -> tuple[Path, Path | None]:
    manifests: list[tuple[str, Path, dict[str, Any]]] = []
    for path in (root / "dist" / "artifacts").glob("*/*/build-manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") != "successful":
            continue
        manifests.append((str(data.get("created_at") or ""), path, data))
    if manifests:
        _, manifest_path, data = max(manifests, key=lambda item: item[0])
        app_name = data.get("artifacts", {}).get("app", {}).get("path")
        if app_name:
            app_path = manifest_path.parent / app_name
            if app_path.is_dir():
                return app_path, manifest_path
    legacy = sorted((root / "dist").glob("ClosedRoom-*.app"), key=lambda path: path.stat().st_mtime, reverse=True)
    if legacy:
        return legacy[0], None
    raise FileNotFoundError("no finalized ClosedRoom .app found")


def bundle_executable(app_path: Path) -> Path:
    plist_path = app_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as handle:
        info = plistlib.load(handle)
    executable = info.get("CFBundleExecutable")
    if not executable:
        raise RuntimeError(f"CFBundleExecutable missing from {plist_path}")
    path = app_path / "Contents" / "MacOS" / str(executable)
    if not path.is_file():
        raise RuntimeError(f"bundle executable missing: {path}")
    return path


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def fetch_json(url: str, timeout: float = 2.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def fetch_text(url: str, timeout: float = 2.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def probe_archive_search(port: int, timeout: float = 5.0) -> dict[str, Any]:
    """Exercise the authenticated meeting-search path in the frozen Python runtime.

    A 200 proves that the bundled sqlite3 can create/query the FTS5 projection rather
    than relying on the host Python used to build the artifact.
    """
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = f"http://127.0.0.1:{port}"
    with opener.open(f"{base}/v1/session", timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"session bootstrap returned HTTP {response.status}")
    with opener.open(f"{base}/v1/meetings?q=packaged-fts5-probe&page=1&limit=1", timeout=timeout) as response:
        payload = json.loads(response.read())
        if response.status != 200:
            raise RuntimeError(f"archive search returned HTTP {response.status}")
    required = {"items", "total", "page", "limit", "has_more"}
    if not required.issubset(payload):
        raise RuntimeError(f"archive search response missing fields: {sorted(required - set(payload))}")
    return payload


def process_table() -> dict[int, tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    table: dict[int, tuple[int, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        command = parts[2] if len(parts) == 3 else ""
        table[pid] = (ppid, command)
    return table


def descendants(root_pid: int, table: dict[int, tuple[int, str]]) -> set[int]:
    found: set[int] = set()
    frontier = {root_pid}
    while frontier:
        parents = frontier
        frontier = {
            pid
            for pid, (ppid, _) in table.items()
            if ppid in parents and pid not in found
        }
        found.update(frontier)
    return found


def wait_until(predicate, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if args.app:
        app_path = Path(args.app).expanduser().resolve()
        manifest_path = app_path.parent / "build-manifest.json"
        if not manifest_path.is_file():
            manifest_path = None
    else:
        app_path, manifest_path = latest_finalized_app(root)
    executable = bundle_executable(app_path)
    port = reserve_port()
    started_at = datetime.now(timezone.utc).isoformat()

    default_evidence = app_path.parent / "packaged-app-smoke.json"
    evidence_path = Path(args.evidence).resolve() if args.evidence else default_evidence
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="closedroom-smoke-") as tmp:
        tmp_path = Path(tmp)
        home = tmp_path / "home"
        home.mkdir()
        stdout_path = tmp_path / "stdout.log"
        stderr_path = tmp_path / "stderr.log"
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CLOSEDROOM_BUILD_CHANNEL"] = env.get("CLOSEDROOM_BUILD_CHANNEL", "ci-smoke")

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                [str(executable), "serve", "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(root),
                env=env,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )

            health: dict[str, Any] = {}
            root_loaded = False

            def ready() -> bool:
                nonlocal health, root_loaded
                if process.poll() is not None:
                    return False
                try:
                    health = fetch_json(f"http://127.0.0.1:{port}/health")
                    page = fetch_text(f"http://127.0.0.1:{port}/")
                    root_loaded = "<html" in page.lower() or "<!doctype" in page.lower()
                    return bool(health.get("ok")) and root_loaded
                except Exception:
                    return False

            ready_ok = wait_until(ready, args.timeout)
            archive_search_payload: dict[str, Any] | None = None
            archive_search_error: str | None = None
            if ready_ok:
                try:
                    archive_search_payload = probe_archive_search(port)
                except Exception as exc:
                    archive_search_error = str(exc)

            table_before = process_table()
            child_pids = sorted(descendants(process.pid, table_before))

            graceful = True
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    graceful = False
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

        port_closed = wait_until(lambda: not port_open(port), 10.0)
        table_after = process_table()
        surviving_children = [pid for pid in child_pids if pid in table_after]
        executable_survivors = [
            pid for pid, (_, command) in table_after.items()
            if str(executable) in command and pid != os.getpid()
        ]

        errors: list[str] = []
        if not ready_ok:
            errors.append("packaged server/static root did not reach readiness")
        if archive_search_error:
            errors.append(f"packaged archive search/FTS5 probe failed: {archive_search_error}")
        if process.returncode not in (0, 130):
            errors.append(f"packaged process exited with {process.returncode}")
        if not graceful:
            errors.append("packaged process did not stop after SIGINT")
        if not port_closed:
            errors.append(f"loopback port {port} remained open after stop")
        if surviving_children:
            errors.append(f"child processes survived stop: {surviving_children}")
        if executable_survivors:
            errors.append(f"packaged executable processes survived stop: {executable_survivors}")

        evidence = {
            "schema_version": 1,
            "status": "pass" if not errors else "fail",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "app": str(app_path),
            "manifest": str(manifest_path) if manifest_path else None,
            "executable": str(executable),
            "port": port,
            "health_ok": bool(health.get("ok")),
            "static_root_loaded": root_loaded,
            "archive_search_fts5_ok": archive_search_payload is not None,
            "archive_search_probe": archive_search_payload,
            "graceful_sigint": graceful,
            "returncode": process.returncode,
            "port_closed": port_closed,
            "observed_child_pids": child_pids,
            "surviving_child_pids": surviving_children,
            "surviving_executable_pids": executable_survivors,
            "execution_environment": "github-hosted-macos-arm64" if os.getenv("GITHUB_ACTIONS") == "true" else "local-macos",
            "fidelity_class": "representative_virtual" if os.getenv("GITHUB_ACTIONS") == "true" else "target_environment",
            "residual_gaps": [
                "interactive WKWebView rendering is not asserted by this non-Cocoa smoke command",
                "TCC prompts and physical microphone/system-audio devices are not exercised",
                "production MLX/Metal model quality and performance are not exercised",
            ],
            "errors": errors,
        }
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if errors:
            print(json.dumps(evidence, indent=2), file=os.sys.stderr)
            print("\n--- packaged stdout ---", file=os.sys.stderr)
            print(stdout_path.read_text(encoding="utf-8", errors="replace"), file=os.sys.stderr)
            print("\n--- packaged stderr ---", file=os.sys.stderr)
            print(stderr_path.read_text(encoding="utf-8", errors="replace"), file=os.sys.stderr)
            return 1

        print(json.dumps(evidence, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
