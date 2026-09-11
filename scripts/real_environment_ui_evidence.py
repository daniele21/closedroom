#!/usr/bin/env python3
"""Run the ClosedRoom target-environment smoke while retaining privacy-safe UI media evidence."""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from macos_ui_driver import UIAutomationError, default_driver

UI_DRIVER = default_driver()
GENERATED_FRONTEND = Path("src/local_asr_server/static")
CHECKPOINTS = [
    ("01-ready-to-record", ("Ready to record", "Pronto per registrare")),
    ("02-recording", ("Stop and Save", "Termina e salva")),
    (
        "03-meeting-persisted",
        ("Prepare notes", "Prepara note", "Transcript only", "Solo trascrizione"),
    ),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ClosedRoom target-environment UI media evidence")
    p.add_argument("--root", default=".")
    p.add_argument("--app")
    p.add_argument(
        "--build",
        action="store_true",
        help="Ensure an exact-checkout finalized app exists; reuse it across reruns instead of rebuilding TCC identity",
    )
    p.add_argument("--record-seconds", type=float, default=8.0)
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--keep-sandbox", action="store_true")
    p.add_argument("--evidence", help="Path to the underlying real-environment report.json")
    return p.parse_args()


def run_text(cmd: list[str], *, cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def git_state(root: Path) -> tuple[str, list[str]]:
    revision = run_text(["git", "rev-parse", "--short=12", "HEAD"], cwd=root)
    status = run_text(["git", "status", "--porcelain"], cwd=root)
    return revision, [line for line in status.splitlines() if line.strip()]


def manifest_source_revision(data: dict[str, Any]) -> str:
    source = data.get("source")
    if isinstance(source, dict):
        value = source.get("revision")
        if value:
            return str(value)
    return str(data.get("source_revision") or "")


def manifest_source_dirty(data: dict[str, Any]) -> bool:
    source = data.get("source")
    if isinstance(source, dict) and "dirty" in source:
        return bool(source.get("dirty"))
    return bool(data.get("dirty", False))


def revisions_match(left: str, right: str) -> bool:
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def exact_finalized_app(root: Path, revision: str) -> tuple[Path, Path] | None:
    matches: list[tuple[str, Path, Path]] = []
    for manifest_path in (root / "dist" / "artifacts").glob("*/*/build-manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") != "successful" or manifest_source_dirty(data):
            continue
        if not revisions_match(revision, manifest_source_revision(data)):
            continue
        app_name = data.get("artifacts", {}).get("app", {}).get("path")
        if not app_name:
            continue
        app_path = manifest_path.parent / str(app_name)
        if app_path.is_dir():
            matches.append((str(data.get("created_at") or ""), app_path, manifest_path))
    if not matches:
        return None
    _, app_path, manifest_path = max(matches, key=lambda item: item[0])
    return app_path, manifest_path


def restore_generated_frontend(root: Path) -> None:
    """Restore only Vite's committed output after a build that began clean."""
    target = GENERATED_FRONTEND.as_posix()
    subprocess.run(
        ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", target],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "clean", "-fd", "--", target], cwd=root, check=True)


def prepare_exact_app(root: Path, revision: str) -> tuple[Path, Path, str]:
    """Reuse an exact finalized app, or build it once and restore generated source output."""
    existing = exact_finalized_app(root, revision)
    if existing is not None:
        app_path, manifest_path = existing
        return app_path, manifest_path, "reused_exact"

    current_revision, dirty_entries = git_state(root)
    if not revisions_match(revision, current_revision):
        raise RuntimeError(f"source_revision_moved:{revision}->{current_revision}")
    if dirty_entries:
        raise RuntimeError("checkout_dirty_before_build:" + " | ".join(dirty_entries))

    subprocess.run(["bash", "scripts/build_artifact.sh", "--no-dmg"], cwd=root, check=True)
    restore_generated_frontend(root)

    after_revision, after_dirty = git_state(root)
    if not revisions_match(revision, after_revision):
        raise RuntimeError(f"source_revision_moved_during_build:{revision}->{after_revision}")
    if after_dirty:
        raise RuntimeError("build_left_checkout_dirty:" + " | ".join(after_dirty))

    built = exact_finalized_app(root, revision)
    if built is None:
        raise RuntimeError(f"exact_finalized_artifact_missing_after_build:{revision}")
    app_path, manifest_path = built
    return app_path, manifest_path, "built_exact"


def process_snapshot() -> list[tuple[int, str]]:
    result = subprocess.run(["ps", "-axo", "pid=,command="], check=True, capture_output=True, text=True)
    found: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            found.append((int(parts[0]), parts[1]))
        except ValueError:
            pass
    return found


def closedroom_pids(snapshot: list[tuple[int, str]]) -> set[int]:
    return {
        pid
        for pid, command in snapshot
        if "/Contents/MacOS/" in command and "ClosedRoom" in command
    }


def find_closedroom_pid(expected_executable: str | None = None, excluded: set[int] | None = None) -> int | None:
    excluded = excluded or set()
    exact: list[int] = []
    generic: list[int] = []
    for pid, command in process_snapshot():
        if pid in excluded or "/Contents/MacOS/" not in command or "ClosedRoom" not in command:
            continue
        generic.append(pid)
        if expected_executable and expected_executable in command:
            exact.append(pid)
    candidates = exact or generic
    return max(candidates) if candidates else None


def window_rect(pid: int) -> str:
    return UI_DRIVER.window_rect(pid)


def has_label(pid: int, labels: tuple[str, ...]) -> bool:
    return UI_DRIVER.exists(pid, labels)


def capture_window(rect: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["screencapture", "-x", "-R", rect, str(destination)], check=True, timeout=15)


def start_video(rect: str, destination: Path) -> subprocess.Popen[bytes]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["screencapture", "-v", "-V", "180", "-R", rect, "-x", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def finish_video(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def evidence_report_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = root / "dist" / "evidence" / "real-environment" / stamp / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    report_path = evidence_report_path(root, args.evidence)
    media_root = report_path.parent / "ui-media" / "meeting-recording-ui"
    screenshot_root = media_root / "screenshots"
    video_path = media_root / "video" / "journey.mov"
    manifest_path = media_root / "manifest.json"
    media_root.mkdir(parents=True, exist_ok=True)

    selected_app: Path | None = Path(args.app).expanduser().resolve() if args.app else None
    artifact_selection = "explicit" if selected_app is not None else "smoke_default"
    selected_manifest: Path | None = None

    if args.build and selected_app is None:
        revision, dirty_entries = git_state(root)
        if dirty_entries:
            # Let the functional smoke own/report checkout_clean rather than
            # rebuilding or silently discarding local source changes.
            artifact_selection = "checkout_dirty"
        else:
            selected_app, selected_manifest, artifact_selection = prepare_exact_app(root, revision)
            verb = "Reusing" if artifact_selection == "reused_exact" else "Built"
            print(f"{verb} exact target-Mac artifact: {selected_app}")

    command = [
        sys.executable,
        str(root / "scripts" / "real_environment_smoke.py"),
        "--root",
        str(root),
        "--evidence",
        str(report_path),
        "--record-seconds",
        str(args.record_seconds),
        "--timeout",
        str(args.timeout),
    ]
    if selected_app is not None:
        command += ["--app", str(selected_app)]
    if args.keep_sandbox:
        command.append("--keep-sandbox")

    existing_closedroom = closedroom_pids(process_snapshot())
    expected_executable = str(selected_app / "Contents" / "MacOS" / "ClosedRoom") if selected_app is not None else None
    smoke = subprocess.Popen(command, cwd=root)
    app_pid: int | None = None
    rect: str | None = None
    video: subprocess.Popen[bytes] | None = None
    captured: set[str] = set()
    media_errors: list[str] = []
    deadline = time.monotonic() + max(args.timeout + args.record_seconds + 90, 180)

    def media_error(message: str) -> None:
        if message not in media_errors:
            media_errors.append(message)

    try:
        while smoke.poll() is None and time.monotonic() < deadline:
            if app_pid is None:
                app_pid = find_closedroom_pid(expected_executable, existing_closedroom)
            if app_pid is not None and rect is None:
                try:
                    rect = window_rect(app_pid)
                    video = start_video(rect, video_path)
                except UIAutomationError as exc:
                    if str(exc) != "closedroom_window_missing":
                        media_error(f"media_start_ui: {exc}")
                    rect = None
                except Exception as exc:
                    media_error(f"media_start: {exc}")
                    rect = None
            if app_pid is not None and rect is not None:
                for name, labels in CHECKPOINTS:
                    if name in captured:
                        continue
                    try:
                        visible = has_label(app_pid, labels)
                    except UIAutomationError as exc:
                        media_error(f"{name}_ui: {exc}")
                        continue
                    if not visible:
                        continue
                    try:
                        capture_window(rect, screenshot_root / f"{name}.png")
                        captured.add(name)
                    except Exception as exc:
                        media_error(f"{name}: {exc}")
            time.sleep(0.4)

        if smoke.poll() is None:
            smoke.terminate()
            try:
                smoke.wait(timeout=10)
            except subprocess.TimeoutExpired:
                smoke.kill()
                smoke.wait(timeout=5)
            media_error("real_environment_smoke exceeded UI evidence wrapper deadline")
    finally:
        finish_video(video)

    smoke_status = smoke.returncode if smoke.returncode is not None else 1
    report: dict = {}
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            media_error(f"report_parse: {exc}")

    screenshot_paths = [screenshot_root / f"{name}.png" for name, _ in CHECKPOINTS]
    screenshots_ok = all(path.is_file() and path.stat().st_size > 0 for path in screenshot_paths)
    video_ok = video_path.is_file() and video_path.stat().st_size > 0
    successful_smoke = smoke_status == 0 and report.get("status") == "pass"
    media_complete = screenshots_ok and video_ok

    manifest = {
        "schema_version": 1,
        "journey_id": "meeting-recording-ui",
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "ui_driver": report.get("ui_driver", "AXUIElement/CGEvent via bounded Swift helper"),
        "source_revision": report.get("source_revision"),
        "artifact_selection": artifact_selection,
        "app": str(selected_app) if selected_app is not None else report.get("app"),
        "build_manifest": str(selected_manifest) if selected_manifest is not None else report.get("manifest"),
        "result": "PASS"
        if successful_smoke and media_complete
        else "E2E_EVIDENCE_INCOMPLETE"
        if successful_smoke
        else report.get("status", "fail"),
        "screenshots": [str(path.relative_to(report_path.parent)) for path in screenshot_paths if path.is_file()],
        "video": str(video_path.relative_to(report_path.parent)) if video_path.is_file() else None,
        "media_errors": media_errors,
        "privacy_boundary": "Capture is restricted to the ClosedRoom application window rectangle; synthetic test content only.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if successful_smoke and not media_complete:
        print(
            "E2E_EVIDENCE_INCOMPLETE: ClosedRoom target UI smoke passed but screenshot/video evidence is incomplete",
            file=sys.stderr,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 1

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return smoke_status


if __name__ == "__main__":
    raise SystemExit(main())
