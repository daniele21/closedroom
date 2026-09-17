#!/usr/bin/env python3
"""Prove PRS-16 capture priority on the exact production app and target Mac.

This release-only runner deliberately composes real local managed ASR with the
packaged WKWebView and TCC-backed native capture path. It requires an observable
waiting state while managed AI is active, then verifies that capture starts only
after the active workload reaches its normal boundary and persists non-empty
microphone plus system-audio tracks. The physical contention transition is
retained as bounded ClosedRoom-window screenshots plus video evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import measured_release_target_mac as measured

WAITING_LABELS = ("Preparing recording", "Preparazione registrazione")
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--app", required=True)
    parser.add_argument("--seed-record-seconds", type=float, default=20.0)
    parser.add_argument("--capture-seconds", type=float, default=6.0)
    parser.add_argument("--active-timeout", type=float, default=120.0)
    parser.add_argument("--job-timeout", type=float, default=900.0)
    parser.add_argument("--sample-interval", type=float, default=0.75)
    parser.add_argument("--output")
    parser.add_argument("--keep-sandbox", action="store_true")
    return parser.parse_args()


def native_both_with_tracks(recording: Any) -> bool:
    if not isinstance(recording, dict):
        return False
    sources = set(recording.get("nonempty_track_sources") or [])
    if not sources:
        sources = measured.load_smoke_module(
            Path(__file__).parents[1]
        ).source_tracks_with_data(recording)
    return (
        recording.get("capture_backend") == "native"
        and recording.get("capture_mode") == "both"
        and {"mic", "system"}.issubset(sources)
    )


def capture_window(rect: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["screencapture", "-x", "-R", rect, str(destination)],
        check=True,
        timeout=15,
    )


def start_video(rect: str, destination: Path) -> subprocess.Popen[bytes]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            "screencapture",
            "-v",
            "-V",
            "900",
            "-R",
            rect,
            "-x",
            str(destination),
        ],
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


def file_nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def sample_state(
    api: Any,
    app_pid: int,
    job: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    runtime = measured.sanitize_runtime_resources(
        api.json("/v1/runtime/resources", timeout=10)
    )
    return {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "job_status": job.get("status"),
        "job_step": job.get("current_step"),
        "process_family": measured.process_family_sample(app_pid),
        "runtime": runtime,
        "thermal": measured.thermal_sample(),
    }


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    app = Path(args.app).expanduser().resolve()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit(
            "capture-contention evidence requires a target Apple-Silicon Mac"
        )
    if (
        args.seed_record_seconds < 10
        or args.capture_seconds <= 0
        or args.active_timeout <= 0
        or args.job_timeout <= 0
        or args.sample_interval <= 0
    ):
        raise SystemExit("invalid contention timing arguments")
    if not app.is_dir():
        raise SystemExit(f"app not found: {app}")

    checkout_revision, dirty_entries = measured.git_state(root)
    if dirty_entries:
        raise SystemExit(
            "capture-contention evidence requires a clean checkout: "
            + " | ".join(dirty_entries)
        )
    manifest_path, manifest = measured.production_manifest_for(app)
    source_revision = str((manifest.get("source") or {}).get("revision") or "")
    if not measured.revisions_match(checkout_revision, source_revision):
        raise SystemExit(
            "production artifact does not match checkout: "
            f"{source_revision or 'unknown'} != {checkout_revision}"
        )

    evidence_root = (
        root / "dist" / "evidence" / "measured-release" / source_revision
    )
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else evidence_root / "record-while-ai-busy-target-mac.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    seed_report = output.parent / "contention-seed-ui-report.json"
    media_root = output.parent / "ui-media" / "record-while-ai-busy"
    waiting_shot = media_root / "screenshots" / "01-ai-busy-waiting.png"
    recording_shot = media_root / "screenshots" / "02-recording-after-boundary.png"
    video_path = media_root / "video" / "contention-journey.mov"

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "fail",
        "journey_id": "record-while-ai-busy",
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "ui_evidence_mode": "full_media",
        "source_revision": source_revision,
        "checkout_revision": checkout_revision,
        "app": str(app),
        "build_manifest": str(manifest_path),
        "seed_ui_report": str(seed_report),
        "screenshots": [str(waiting_shot), str(recording_shot)],
        "video": str(video_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "resource_samples": [],
        "errors": [],
        "privacy_boundary": (
            "UI media is restricted to the ClosedRoom application window; "
            "resource evidence contains bounded process/runtime metrics and no transcript text."
        ),
        "residual_gaps": [
            "Source/browser tests remain the primary proof for bounded queue ordering and cancellation; this target-Mac run confirms the physical TCC/WKWebView/MLX contention boundary.",
            "No numeric thermal or performance threshold is inferred without a comparable baseline.",
        ],
    }

    def check(name: str, ok: bool, detail: Any = None) -> None:
        report["checks"].append(
            {"name": name, "status": "pass" if ok else "fail", "detail": detail}
        )
        if not ok:
            raise RuntimeError(f"check failed: {name}")

    smoke = measured.load_smoke_module(root)
    sandbox: Path | None = None
    app_process: subprocess.Popen[Any] | None = None
    video: subprocess.Popen[bytes] | None = None
    executable = ""
    port: int | None = None
    try:
        seed_command = [
            sys.executable,
            "scripts/real_environment_ui_evidence.py",
            "--root",
            str(root),
            "--app",
            str(app),
            "--record-seconds",
            str(args.seed_record_seconds),
            "--keep-sandbox",
            "--evidence",
            str(seed_report),
        ]
        seed_result = subprocess.run(
            seed_command, cwd=root, check=False, timeout=900
        )
        seed = (
            json.loads(seed_report.read_text(encoding="utf-8"))
            if seed_report.is_file()
            else {}
        )
        check(
            "seed_target_mac_recording_ui",
            seed_result.returncode == 0 and seed.get("status") == "pass",
            {"status": seed.get("status")},
        )
        created = (
            seed.get("created_recording")
            if isinstance(seed.get("created_recording"), dict)
            else {}
        )
        recording_id = str(created.get("id") or "")
        recordings_root = measured.existing_directory(
            seed.get("isolated_recordings_dir")
        )
        sandbox = measured.existing_directory(seed.get("isolated_home"))
        check("seed_native_both_capture", native_both_with_tracks(created), created)
        check(
            "seed_recording_available",
            bool(
                recording_id
                and recordings_root is not None
                and sandbox is not None
            ),
        )
        assert recordings_root is not None
        assert sandbox is not None

        info = smoke.bundle_info(app)
        executable = str(info["executable"])
        env = os.environ.copy()
        env["HOME"] = str(sandbox)
        app_process = subprocess.Popen(
            [executable],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        check(
            "contention_app_started",
            smoke.wait(lambda: app_process.poll() is None, 3),
            {"pid": app_process.pid},
        )
        port, _ = smoke.discover_server(
            app_process.pid, info["bundle_id"], info["version"], 90
        )
        api = smoke.Api(port)
        check(
            "packaged_window_accessible",
            smoke.wait(lambda: smoke.ui(app_process.pid, "window") == "true", 30),
        )
        check(
            "new_meeting_action_visible",
            smoke.wait(
                lambda: smoke.exists(app_process.pid, smoke.LABELS["new"]), 30
            ),
        )
        smoke.ui(app_process.pid, "press", smoke.LABELS["new"])
        check(
            "new_meeting_ready_before_contention",
            smoke.wait(
                lambda: smoke.exists(app_process.pid, smoke.LABELS["ready"]), 30
            ),
        )
        rect = smoke.UI_DRIVER.window_rect(app_process.pid)
        video = start_video(rect, video_path)

        before_ids = {
            str(item.get("id") or "")
            for item in api.recordings()
            if item.get("id")
        }
        job = api.json(
            f"/v1/recordings/{recording_id}/transcription-jobs",
            "POST",
            {
                "asr_provider": "local",
                "diarization_provider": "disabled",
                "visual_intelligence_enabled": False,
            },
            20,
        )
        job_id = str(job.get("id") or "")
        check("managed_ai_submitted", bool(job_id), {"job_id": job_id})

        started = time.monotonic()
        active_seen = False
        current: dict[str, Any] = {}
        active_deadline = time.monotonic() + args.active_timeout
        while time.monotonic() < active_deadline:
            current = api.json(f"/v1/jobs/{job_id}", timeout=10)
            sample = sample_state(api, app_process.pid, current, started)
            report["resource_samples"].append(sample)
            runtime = sample["runtime"]
            if (
                current.get("status") not in TERMINAL
                and int(runtime.get("heavy_active_count") or 0) > 0
            ):
                active_seen = True
                break
            if current.get("status") in TERMINAL:
                break
            time.sleep(args.sample_interval)
        check(
            "managed_ai_active_before_start",
            active_seen,
            measured.summarize_job(current),
        )

        smoke.ui(app_process.pid, "press", smoke.LABELS["start"])
        waiting_seen = smoke.wait(
            lambda: smoke.exists(app_process.pid, WAITING_LABELS),
            8,
            0.2,
        )
        check("truthful_waiting_state_observed", waiting_seen)
        waiting_job = api.json(f"/v1/jobs/{job_id}", timeout=10)
        waiting_sample = sample_state(
            api, app_process.pid, waiting_job, started
        )
        report["resource_samples"].append(waiting_sample)
        waiting_runtime = waiting_sample["runtime"]
        check(
            "managed_ai_still_active_while_waiting",
            waiting_job.get("status") not in TERMINAL
            and int(waiting_runtime.get("heavy_active_count") or 0) > 0,
            {
                "job": measured.summarize_job(waiting_job),
                "heavy_active_count": waiting_runtime.get("heavy_active_count"),
                "heavy_active_by_type": waiting_runtime.get("heavy_active_by_type")
                or {},
            },
        )
        check(
            "capture_not_active_while_ai_busy",
            not smoke.exists(app_process.pid, smoke.LABELS["stop"]),
        )
        capture_window(rect, waiting_shot)

        terminal: dict[str, Any] = {}
        deadline = time.monotonic() + args.job_timeout
        thermal_seen = False
        while time.monotonic() < deadline:
            current = api.json(f"/v1/jobs/{job_id}", timeout=10)
            sample = sample_state(api, app_process.pid, current, started)
            report["resource_samples"].append(sample)
            thermal_seen = (
                thermal_seen or sample["thermal"].get("status") == "available"
            )
            if current.get("status") in TERMINAL:
                terminal = current
                break
            time.sleep(args.sample_interval)

        summary = measured.summarize_job(terminal)
        report["managed_ai_job"] = summary
        check("managed_ai_completed", summary.get("status") == "completed", summary)
        backend = str(summary.get("backend") or "").lower()
        check(
            "managed_ai_is_local_mlx",
            str(summary.get("asr_provider") or "local").lower() == "local"
            and "mlx" in backend,
            {"backend": backend},
        )
        check("thermal_observation_available", thermal_seen)
        check(
            "capture_started_after_safe_boundary",
            smoke.wait(
                lambda: smoke.exists(app_process.pid, smoke.LABELS["stop"]), 90
            ),
        )
        capture_window(rect, recording_shot)
        finish_video(video)
        video = None
        check(
            "contention_full_media_complete",
            file_nonempty(waiting_shot)
            and file_nonempty(recording_shot)
            and file_nonempty(video_path),
            {
                "waiting_screenshot": str(waiting_shot),
                "recording_screenshot": str(recording_shot),
                "video": str(video_path),
            },
        )

        capture_started = time.monotonic()
        while time.monotonic() - capture_started < args.capture_seconds:
            pseudo_job = {
                "status": "capture_active",
                "current_step": "recording",
            }
            sample = sample_state(api, app_process.pid, pseudo_job, started)
            report["resource_samples"].append(sample)
            time.sleep(
                min(
                    args.sample_interval,
                    max(0.2, args.capture_seconds / 4),
                )
            )
        smoke.ui(app_process.pid, "press", smoke.LABELS["stop"])
        check(
            "contention_recording_persisted_ui",
            smoke.wait(
                lambda: smoke.exists(
                    app_process.pid, smoke.LABELS["transcribe"]
                ),
                60,
            ),
        )

        after = api.recordings()
        contention_recording = smoke.newest(before_ids, after)
        check("contention_recording_created", contention_recording is not None)
        assert contention_recording is not None
        sources = smoke.source_tracks_with_data(contention_recording)
        persisted = dict(contention_recording)
        persisted["nonempty_track_sources"] = sorted(sources)
        report["contention_recording"] = {
            "id": persisted.get("id"),
            "capture_backend": persisted.get("capture_backend"),
            "capture_mode": persisted.get("capture_mode"),
            "nonempty_track_sources": sorted(sources),
        }
        check(
            "contention_native_both_tracks",
            native_both_with_tracks(persisted),
            report["contention_recording"],
        )

        cleanup = smoke.quit_app(app_process.pid, executable, port)
        report["cleanup"] = cleanup
        check("contention_app_cleanup", bool(cleanup.get("process_gone")), cleanup)
        app_process = None
        report["status"] = "pass"
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        finish_video(video)
        if app_process is not None and executable:
            try:
                report["cleanup_after_failure"] = smoke.quit_app(
                    app_process.pid, executable, port
                )
            except Exception as exc:
                report["errors"].append(f"cleanup:{exc}")
        if sandbox is not None and sandbox.is_dir() and not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)
            report["sandbox_removed"] = not sandbox.exists()
            if report["status"] == "pass" and sandbox.exists():
                report["status"] = "fail"
                report["errors"].append("isolated HOME survived cleanup")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {"status": report["status"], "evidence": str(output)},
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
