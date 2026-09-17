from __future__ import annotations

import os
import platform
import resource
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol


class WorkloadSnapshotProvider(Protocol):
    def snapshot(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class ProcessMemorySnapshot:
    pid: int
    current_rss_bytes: int | None
    peak_rss_bytes: int | None

    def public(self) -> dict[str, Any]:
        available = self.current_rss_bytes is not None or self.peak_rss_bytes is not None
        return {
            "status": "available" if available else "unknown",
            "pid": self.pid,
            "current_rss_bytes": self.current_rss_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
        }


class ResourceMetricsCollector:
    """Collect privacy-safe resource state on demand without background polling.

    Resource telemetry is deliberately best-effort. Unsupported or unavailable
    measurements are returned as ``None``/``unknown`` rather than being
    represented as zero, which would make pressure diagnostics misleading.
    """

    def snapshot(
        self,
        *,
        sidecar_pid: int | None = None,
        workload_arbiter: WorkloadSnapshotProvider | None = None,
    ) -> dict[str, Any]:
        app_pid = os.getpid()
        return {
            "captured_at": time.time(),
            "app_process": self.process_memory(app_pid, include_peak=True).public(),
            "llm_sidecar": (
                self.process_memory(sidecar_pid, include_peak=False).public()
                if sidecar_pid is not None
                else {
                    "status": "not_running",
                    "pid": None,
                    "current_rss_bytes": None,
                    "peak_rss_bytes": None,
                }
            ),
            "heavy_workloads": self._workload_snapshot(workload_arbiter),
            "machine": self.machine_memory(),
        }

    def process_memory(self, pid: int, *, include_peak: bool) -> ProcessMemorySnapshot:
        current = self._current_rss_bytes(pid)
        peak = self._self_peak_rss_bytes() if include_peak and pid == os.getpid() else None
        return ProcessMemorySnapshot(pid=pid, current_rss_bytes=current, peak_rss_bytes=peak)

    @staticmethod
    def _workload_snapshot(workload_arbiter: WorkloadSnapshotProvider | None) -> dict[str, Any]:
        if workload_arbiter is None:
            return {
                "status": "unknown",
                "max_concurrent": None,
                "queue_capacity": None,
                "queue_depth": None,
                "active_count": None,
                "pending_by_type": {},
                "active_by_type": {},
            }
        raw = workload_arbiter.snapshot()
        pending = raw.get("pending") if isinstance(raw.get("pending"), dict) else {}
        active = raw.get("active") if isinstance(raw.get("active"), dict) else {}
        return {
            "status": "available",
            "max_concurrent": raw.get("max_concurrent"),
            "queue_capacity": raw.get("queue_capacity"),
            "queue_depth": raw.get("queue_depth"),
            "active_count": raw.get("active_count"),
            "pending_by_type": dict(Counter(str(value) for value in pending.values())),
            "active_by_type": dict(Counter(str(value) for value in active.values())),
            "submitted": raw.get("submitted"),
            "completed": raw.get("completed"),
            "failed": raw.get("failed"),
            "rejected": raw.get("rejected"),
            "cancelled_pending": raw.get("cancelled_pending"),
            "closed": raw.get("closed"),
        }

    @staticmethod
    def _current_rss_bytes(pid: int) -> int | None:
        try:
            completed = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        try:
            rss_kib = int(completed.stdout.strip())
        except (TypeError, ValueError):
            return None
        return rss_kib * 1024 if rss_kib >= 0 else None

    @staticmethod
    def _self_peak_rss_bytes() -> int | None:
        try:
            raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if raw < 0:
            return None
        # Darwin reports bytes; Linux and most BSD CI environments report KiB.
        return raw if platform.system() == "Darwin" else raw * 1024

    @staticmethod
    def machine_memory() -> dict[str, Any]:
        total_bytes: int | None = None
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            if page_size > 0 and page_count > 0:
                total_bytes = page_size * page_count
        except (AttributeError, OSError, TypeError, ValueError):
            total_bytes = None

        return {
            "status": "available" if total_bytes is not None else "unknown",
            "system": platform.system() or None,
            "machine": platform.machine() or None,
            "physical_memory_bytes": total_bytes,
        }
