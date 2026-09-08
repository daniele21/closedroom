#!/usr/bin/env python3
"""Collect PRS-18 target-Mac release evidence from one exact production app.

The runner composes the existing packaged WKWebView/TCC journey, then executes
one real local transcription job while sampling privacy-safe process/resource
and thermal state. Finally it runs the existing read-only PRS-9 dual-vs-mixed
audio benchmark on the recording produced by the UI journey.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--app", required=True, help="Exact Developer-ID/notarized .app to validate")
    parser.add_argument("--record-seconds", type=float, default=8.0)
    parser.add_argument("--sample-interval", type=float, default=0.75)
    parser.add_argument("--job-timeout", type=float, default=900.0)
    parser.add_argument("--benchmark-repeats", type=int, default=3)
    parser.add_argument("--output")
    parser.add_argument("--keep-sandbox", action="store_true")
    return parser.parse_args()


def load_smoke_module(root: Path):
    scripts_dir = str(root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    path = root / "scripts" / "real_environment_smoke.py"
    spec = importlib.util.spec_from_file_location("closedroom_real_environment_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load real_environment_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def production_manifest_for(app: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = app.parent / "build-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("production app is missing build-manifest.json")
    manifest = read_json(manifest_path)
    signing = str((manifest.get("configuration") or {}).get("signing") or "")
    if signing != "developer-id-notarized":
        raise RuntimeError(f"production app signing is not release-ready: {signing or 'unknown'}")
    evidence_path = app.parent / "production-release-evidence.json"
    if not evidence_path.is_file() or read_json(evidence_path).get("status") != "pass":
        raise RuntimeError("production-release-evidence.json is missing or not PASS")
    return manifest_path, manifest


def process_table() -> dict[int, tuple[int, float, int]]:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,%cpu=,rss="],
        capture_output=True,
        text=True,
        check=True,
    )
    table: dict[int, tuple[int, float, int]] = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), float(parts[2]), int(parts[3]) * 1024)
        except ValueError:
            continue
    return table


def family_pids(root_pid: int, table: dict[int, tuple[int, float, int]]) -> set[int]:
    found = {root_pid}
    frontier = {root_pid}
    while frontier:
        children = {pid for pid, (ppid, _, _) in table.items() if ppid in frontier and pid not in found}
        found.update(children)
        frontier = children
    return found


def process_family_sample(root_pid: int) -> dict[str, Any]:
    table = process_table()
    pids = family_pids(root_pid, table)
    values = [table[pid] for pid in pids if pid in table]
    return {
        "process_count": len(values),
        "cpu_percent_sum": round(sum(value[1] for value in values), 2),
        "rss_bytes_sum": sum(value[2] for value in values),
    }


def thermal_sample() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["pmset", "-g", "thermlog"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    except (OSError, subprocess.SubprocessError):
        return {"status": "unknown", "source": "pmset-thermlog", "metrics": {}}
    metrics: dict[str, int] = {}
    for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_ ]{1,48})\s*=\s*(\d+)", text):
        normalized = re.sub(r"\s+", "_", key.strip().lower())
        metrics[normalized] = int(value)
    return {
        "status": "available" if metrics else "unknown",
        "source": "pmset-thermlog",
        "metrics": metrics,
    }


def sanitize_runtime_resources(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "unknown"}
    app = payload.get("app_process") if isinstance(payload.get("app_process"), dict) else {}
    llm = payload.get("llm_sidecar") if isinstance(payload.get("llm_sidecar"), dict) else {}
    workloads = payload.get("heavy_workloads") if isinstance(payload.get("heavy_workloads"), dict) else {}
    machine = payload.get("machine") if isinstance(payload.get("machine"), dict) else {}
    return {
        "app_current_rss_bytes": app.get("current_rss_bytes"),
        "app_peak_rss_bytes": app.get("peak_rss_bytes"),
        "llm_status": llm.get("status"),
        "llm_current_rss_bytes": llm.get("current_rss_bytes"),
        "heavy_status": workloads.get("status"),
        "heavy_active_count": workloads.get("active_count"),
        "heavy_queue_depth": workloads.get("queue_depth"),
        "heavy_active_by_type": workloads.get("active_by_type") or {},
        "physical_memory_bytes": machine.get("physical_memory_bytes"),
    }


def locate_session(recordings_root: Path, recording_id: str) -> Path:
    direct = recordings_root / recording_id
    if direct.is_dir():
        return direct
    matches = [path for path in recordings_root.rglob(recording_id) if path.is_dir() and path.name == recording_id]
    if len(matches) != 1:
        raise RuntimeError(f"could not uniquely locate recording session {recording_id}")
    return matches[0]


def summarize_job(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "current_step": job.get("current_step"),
        "progress": job.get("progress"),
        "backend": result.get("backend") or stats.get("backend"),
        "asr_provider": result.get("asr_provider") or stats.get("asr_provider"),
        "model": result.get("model"),
        "time_total_seconds": stats.get("time_total_seconds"),
        "error": str(job.get("error") or "")[:300] or None,
    }


def run_audio_benchmark(root: Path, session: Path, model: str, language: str, repeats: int, output: Path) -> dict[str, Any]:
    command = [
        "uv", "run", "--frozen", "--python", "3.12", "python",
        "scripts/benchmark_audio_strategy.py", str(session),
        "--model", model,
        "--language", language,
        "--repeats", str(repeats),
        "--output", str(output),
    ]
    subprocess.run(command, cwd=root, check=True, timeout=3600)
    return read_json(output)


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    app = Path(args.app).expanduser().resolve()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("measured release evidence requires a target Apple-Silicon Mac")
    if args.sample_interval <= 0 or args.job_timeout <= 0 or not 1 <= args.benchmark_repeats <= 9:
        raise SystemExit("invalid sampling/timeout/repeat arguments")
    if shutil.which("uv") is None:
        raise SystemExit("uv is required for the representative audio benchmark")
    if not app.is_dir():
        raise SystemExit(f"app not found: {app}")

    manifest_path, manifest = production_manifest_for(app)
    source_revision = str((manifest.get("source") or {}).get("revision") or "")
    evidence_root = root / "dist" / "evidence" / "measured-release" / source_revision
    output = Path(args.output).expanduser().resolve() if args.output else evidence_root / "measured-release-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    ui_report = output.parent / "ui-target-mac-report.json"
    benchmark_path = output.parent / "audio-strategy-benchmark.json"

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "fail",
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "source_revision": source_revision,
        "app": str(app),
        "build_manifest": str(manifest_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "resource_samples": [],
        "errors": [],
        "residual_gaps": [
            "VoiceOver spoken-output quality and subjective usability remain human judgement.",
            "No numeric performance budget is inferred without a comparable baseline; this run records observations and workload completion truthfully.",
        ],
    }

    def check(name: str, ok: bool, detail: Any = None) -> None:
        report["checks"].append({"name": name, "status": "pass" if ok else "fail", "detail": detail})
        if not ok:
            raise RuntimeError(f"check failed: {name}")

    sandbox: Path | None = None
    app_process: subprocess.Popen[Any] | None = None
    smoke = load_smoke_module(root)
    port: int | None = None
    executable = ""
    try:
        ui_command = [
            sys.executable, "scripts/real_environment_ui_evidence.py",
            "--root", str(root), "--app", str(app),
            "--record-seconds", str(args.record_seconds),
            "--keep-sandbox", "--evidence", str(ui_report),
        ]
        ui_result = subprocess.run(ui_command, cwd=root, check=False, timeout=600)
        ui = read_json(ui_report) if ui_report.is_file() else {}
        check("target_mac_recording_ui", ui_result.returncode == 0 and ui.get("status") == "pass", {"status": ui.get("status")})
        created = ui.get("created_recording") if isinstance(ui.get("created_recording"), dict) else {}
        recording_id = str(created.get("id") or "")
        recordings_root = Path(str(ui.get("isolated_recordings_dir") or ""))
        sandbox = Path(str(ui.get("isolated_home") or ""))
        check("native_both_capture", created.get("capture_backend") == "native" and created.get("capture_mode") == "both", created)
        check("mic_system_persisted", {"mic", "system"}.issubset(set(created.get("nonempty_track_sources") or [])), created.get("nonempty_track_sources"))
        check("isolated_recording_available", bool(recording_id and recordings_root.is_dir() and sandbox.is_dir()))
        session = locate_session(recordings_root, recording_id)

        info = smoke.bundle_info(app)
        executable = str(info["executable"])
        env = os.environ.copy()
        env["HOME"] = str(sandbox)
        app_process = subprocess.Popen([executable], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        check("resource_probe_app_started", smoke.wait(lambda: app_process.poll() is None, 3), {"pid": app_process.pid})
        port, _ = smoke.discover_server(app_process.pid, info["bundle_id"], info["version"], 90)
        api = smoke.Api(port)
        settings = api.json("/v1/settings")
        model = str(settings.get("default_model") or api.health().get("default_model") or "")
        language = str(settings.get("default_language") or "it")
        check("local_asr_model_resolved", bool(model), {"model": model})

        job = api.json(
            f"/v1/recordings/{recording_id}/transcription-jobs",
            "POST",
            {"asr_provider": "local", "diarization_provider": "disabled", "visual_intelligence_enabled": False},
            20,
        )
        job_id = str(job.get("id") or "")
        check("managed_transcription_submitted", bool(job_id), {"job_id": job_id})
        started = time.monotonic()
        active_seen = False
        thermal_seen = False
        terminal: dict[str, Any] = {}
        while time.monotonic() - started < args.job_timeout:
            current = api.json(f"/v1/jobs/{job_id}", timeout=10)
            runtime = sanitize_runtime_resources(api.json("/v1/runtime/resources", timeout=10))
            family = process_family_sample(app_process.pid)
            thermal = thermal_sample()
            active_seen = active_seen or int(runtime.get("heavy_active_count") or 0) > 0
            thermal_seen = thermal_seen or thermal.get("status") == "available"
            report["resource_samples"].append({
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "job_status": current.get("status"),
                "job_step": current.get("current_step"),
                "process_family": family,
                "runtime": runtime,
                "thermal": thermal,
            })
            if current.get("status") in TERMINAL:
                terminal = current
                break
            time.sleep(args.sample_interval)

        summary = summarize_job(terminal)
        report["managed_ai_job"] = summary
        check("managed_transcription_completed", summary.get("status") == "completed", summary)
        check("arbiter_active_observed", active_seen)
        check("resource_samples_recorded", len(report["resource_samples"]) >= 2, {"samples": len(report["resource_samples"])})
        check("thermal_observation_available", thermal_seen)
        backend = str(summary.get("backend") or "").lower()
        check("local_mlx_backend", str(summary.get("asr_provider") or "local").lower() == "local" and "mlx" in backend, {"backend": backend})

        cleanup = smoke.quit_app(app_process.pid, executable, port)
        report["managed_ai_cleanup"] = cleanup
        check("managed_ai_app_cleanup", bool(cleanup.get("process_gone")), cleanup)
        app_process = None

        benchmark = run_audio_benchmark(root, session, model, language, args.benchmark_repeats, benchmark_path)
        report["audio_strategy_benchmark"] = benchmark
        check("audio_strategy_benchmark_completed", benchmark.get("status") in {"pass", "completed", "ok"} or bool(benchmark.get("strategies") or benchmark.get("results")), {"output": str(benchmark_path)})

        report["status"] = "pass"
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        if app_process is not None and executable:
            try:
                report["cleanup_after_failure"] = smoke.quit_app(app_process.pid, executable, port)
            except Exception as exc:
                report["errors"].append(f"cleanup:{exc}")
        if sandbox is not None and sandbox.is_dir() and not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)
            report["sandbox_removed"] = not sandbox.exists()
            if report["status"] == "pass" and sandbox.exists():
                report["status"] = "fail"
                report["errors"].append("isolated HOME survived cleanup")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "evidence": str(output)}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
