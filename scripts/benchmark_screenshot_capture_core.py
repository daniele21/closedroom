#!/usr/bin/env python3
"""Benchmark the persistent screenshot worker on a target Mac.

This runner is intentionally local-only. It captures real screen pixels into a temporary
folder and deletes them immediately after each sample. The JSON report contains only
technical latency/process metadata, never image content.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def read_json_event(process: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("worker stdout unavailable")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                raise RuntimeError(f"worker exited with code {process.returncode}")
            time.sleep(0.01)
            continue
        line = line.strip()
        if not line or line.startswith("CR_SCREENSHOT_DIAG "):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise TimeoutError("worker event timeout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--helper")
    parser.add_argument("--shots", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--display-id", type=int)
    parser.add_argument("--output")
    parser.add_argument("--enforce-slo", action="store_true")
    parser.add_argument("--max-p95-ms", type=float, default=700.0)
    args = parser.parse_args()

    if platform.system() != "Darwin":
        raise SystemExit("REAL screenshot benchmark requires macOS")

    if args.helper:
        helper = Path(args.helper).expanduser().resolve()
    else:
        from local_asr_server.native_capture_helper import get_helper_binary

        helper = Path(get_helper_binary()).resolve()
    if not helper.is_file():
        raise SystemExit(f"native helper not found: {helper}")

    recording_id = f"benchmark-{uuid.uuid4()}"
    process = subprocess.Popen(
        [str(helper), "screenshot-worker", "--recording-id", recording_id],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "fail",
        "recording_id": recording_id,
        "helper": str(helper),
        "shots_requested": args.shots,
        "interval_seconds": args.interval,
        "samples": [],
        "privacy": "technical metrics only; captured images are temporary and deleted",
    }

    try:
        ready = read_json_event(process, timeout=5.0)
        if ready.get("type") != "screenshot_worker_ready":
            raise RuntimeError(f"worker did not become ready: {ready}")
        displays = [item for item in ready.get("displays") or [] if isinstance(item, dict)]
        if not displays:
            raise RuntimeError("worker reported no displays")
        selected = args.display_id
        if selected is None:
            main_display = next((item for item in displays if item.get("is_main")), displays[0])
            selected = int(main_display["display_id"])
        worker_pid = int(ready.get("worker_pid") or process.pid)

        with tempfile.TemporaryDirectory(prefix="closedroom-shot-benchmark-") as temp_name:
            temp_dir = Path(temp_name)
            for index in range(args.shots):
                request_id = f"benchmark-{index:03d}-{uuid.uuid4().hex[:8]}"
                original = temp_dir / f"{request_id}.jpg"
                thumbnail = temp_dir / f"{request_id}-thumb.jpg"
                command = {
                    "type": "capture_screenshot",
                    "request_id": request_id,
                    "trace_id": request_id,
                    "display_id": selected,
                    "recording_ready_uptime": 0.001,
                    "original_file": str(original),
                    "thumbnail_file": str(thumbnail),
                }
                started = time.monotonic()
                if process.stdin is None:
                    raise RuntimeError("worker stdin unavailable")
                process.stdin.write(json.dumps(command, separators=(",", ":")) + "\n")
                process.stdin.flush()

                event = read_json_event(process, timeout=2.0)
                elapsed_ms = (time.monotonic() - started) * 1000.0
                success = event.get("type") == "screenshot_completed"
                report["samples"].append({
                    "index": index,
                    "success": success,
                    "reason": event.get("reason"),
                    "roundtrip_ms": round(elapsed_ms, 2),
                    "capture_ms": event.get("capture_ms"),
                    "encode_ms": event.get("encode_ms"),
                    "write_ms": event.get("write_ms"),
                    "worker_pid": worker_pid,
                })
                original.unlink(missing_ok=True)
                thumbnail.unlink(missing_ok=True)
                if args.interval > 0 and index + 1 < args.shots:
                    time.sleep(args.interval)

        latencies = [
            float(item["roundtrip_ms"])
            for item in report["samples"]
            if item["success"]
        ]
        successes = sum(1 for item in report["samples"] if item["success"])
        report["successes"] = successes
        report["failures"] = args.shots - successes
        report["success_rate"] = successes / max(args.shots, 1)
        report["p50_ms"] = round(percentile(latencies, 0.50) or 0.0, 2)
        report["p95_ms"] = round(percentile(latencies, 0.95) or 0.0, 2)
        report["mean_ms"] = round(statistics.mean(latencies), 2) if latencies else None
        report["worker_pid"] = worker_pid
        report["single_worker_pid"] = all(
            item["worker_pid"] == worker_pid for item in report["samples"]
        )
        slo_ok = (
            successes == args.shots
            and report["single_worker_pid"]
            and report["p95_ms"] <= args.max_p95_ms
        )
        report["slo"] = {
            "max_p95_ms": args.max_p95_ms,
            "all_shots_successful": successes == args.shots,
            "single_worker_pid": report["single_worker_pid"],
            "passed": slo_ok,
        }
        report["status"] = "pass" if (slo_ok or not args.enforce_slo) else "fail"
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
                    process.stdin.flush()
                process.wait(timeout=1.0)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
        report["worker_exit_code"] = process.returncode

    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
        print(output)
    else:
        print(encoded)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
