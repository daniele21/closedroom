from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr_server.runtime.resource_metrics import ResourceMetricsCollector


class ResourceMetricsCollectorTests(unittest.TestCase):
    def test_current_rss_uses_ps_kib_and_converts_to_bytes(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="1234\n")
        with patch("local_asr_server.runtime.resource_metrics.subprocess.run", return_value=completed) as run:
            value = ResourceMetricsCollector._current_rss_bytes(42)

        self.assertEqual(value, 1234 * 1024)
        run.assert_called_once()

    def test_current_rss_is_unknown_when_process_measurement_fails(self) -> None:
        with patch(
            "local_asr_server.runtime.resource_metrics.subprocess.run",
            side_effect=OSError("ps unavailable"),
        ):
            self.assertIsNone(ResourceMetricsCollector._current_rss_bytes(42))

    def test_peak_rss_normalizes_darwin_bytes_without_multiplying(self) -> None:
        usage = SimpleNamespace(ru_maxrss=987654)
        with patch("local_asr_server.runtime.resource_metrics.resource.getrusage", return_value=usage), patch(
            "local_asr_server.runtime.resource_metrics.platform.system", return_value="Darwin"
        ):
            self.assertEqual(ResourceMetricsCollector._self_peak_rss_bytes(), 987654)

    def test_snapshot_never_represents_missing_sidecar_as_zero(self) -> None:
        collector = ResourceMetricsCollector()
        with patch.object(collector, "process_memory") as process_memory, patch.object(
            collector, "machine_memory", return_value={"status": "unknown", "physical_memory_bytes": None}
        ):
            process_memory.return_value.public.return_value = {
                "status": "unknown",
                "pid": os.getpid(),
                "current_rss_bytes": None,
                "peak_rss_bytes": None,
            }
            snapshot = collector.snapshot(sidecar_pid=None, workload_arbiter=None)

        self.assertEqual(snapshot["llm_sidecar"]["status"], "not_running")
        self.assertIsNone(snapshot["llm_sidecar"]["current_rss_bytes"])
        self.assertIsNone(snapshot["heavy_workloads"]["queue_depth"])
        self.assertNotEqual(snapshot["llm_sidecar"]["current_rss_bytes"], 0)

    def test_snapshot_aggregates_arbiter_state_without_job_identifiers(self) -> None:
        collector = ResourceMetricsCollector()
        arbiter = Mock()
        arbiter.snapshot.return_value = {
            "max_concurrent": 1,
            "queue_capacity": 8,
            "queue_depth": 3,
            "active_count": 1,
            "pending": {"job-2": "analysis", "job-3": "analysis", "job-4": "diarization"},
            "active": {"job-1": "transcription"},
            "submitted": 4,
            "completed": 0,
            "failed": 0,
            "rejected": 0,
            "cancelled_pending": 0,
            "closed": False,
        }
        with patch.object(collector, "process_memory") as process_memory, patch.object(
            collector, "machine_memory", return_value={"status": "available", "physical_memory_bytes": 16}
        ):
            process_memory.return_value.public.return_value = {
                "status": "available",
                "pid": 123,
                "current_rss_bytes": 1024,
                "peak_rss_bytes": None,
            }
            snapshot = collector.snapshot(sidecar_pid=123, workload_arbiter=arbiter)

        workloads = snapshot["heavy_workloads"]
        self.assertEqual(workloads["queue_depth"], 3)
        self.assertEqual(workloads["active_count"], 1)
        self.assertEqual(workloads["pending_by_type"], {"analysis": 2, "diarization": 1})
        self.assertEqual(workloads["active_by_type"], {"transcription": 1})
        self.assertNotIn("pending", workloads)
        self.assertNotIn("active", workloads)
        self.assertNotIn("job-1", str(workloads))
        self.assertEqual(snapshot["llm_sidecar"]["current_rss_bytes"], 1024)
        arbiter.snapshot.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
