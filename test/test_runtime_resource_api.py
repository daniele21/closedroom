from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr_server.routers import system


class RuntimeResourceApiTests(unittest.TestCase):
    def test_resource_snapshot_uses_managed_sidecar_pid_and_process_arbiter(self) -> None:
        runtime = Mock()
        runtime.llm_status.return_value = {"name": "llm", "pid": 4321}
        arbiter = Mock()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(heavy_workload_arbiter=arbiter)))
        services = SimpleNamespace(runtime=runtime)

        with patch.object(system, "get_services", return_value=services), patch.object(
            system.ResourceMetricsCollector,
            "snapshot",
            return_value={"app_process": {"status": "available"}},
        ) as snapshot:
            result = system.runtime_resources(request)

        self.assertEqual(result["app_process"]["status"], "available")
        snapshot.assert_called_once_with(sidecar_pid=4321, workload_arbiter=arbiter)

    def test_runtime_status_adds_resources_without_replacing_service_status(self) -> None:
        runtime = Mock()
        runtime.status.return_value = {"services": {"llm": {"status": "ready"}}}
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(heavy_workload_arbiter=None)))
        services = SimpleNamespace(runtime=runtime)

        with patch.object(system, "get_services", return_value=services), patch.object(
            system,
            "runtime_resources",
            return_value={"app_process": {"status": "unknown"}},
        ):
            result = system.runtime_status(request)

        self.assertEqual(result["services"]["llm"]["status"], "ready")
        self.assertEqual(result["resources"]["app_process"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
