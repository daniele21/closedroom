from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1]


def load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


production = load("build_production_artifact", "scripts/build_production_artifact.py")
measured = load("measured_release_target_mac", "scripts/measured_release_target_mac.py")


class ProductionArtifactContractTests(unittest.TestCase):
    def test_only_developer_id_application_is_release_identity(self) -> None:
        self.assertTrue(production.developer_id_identity("Developer ID Application: Example (TEAMID)"))
        self.assertFalse(production.developer_id_identity("Apple Development: Example (TEAMID)"))
        self.assertFalse(production.developer_id_identity("-"))

    def test_release_codesign_requires_developer_id_and_secure_timestamp(self) -> None:
        ready = "Authority=Developer ID Application: Example (TEAMID)\nTimestamp=Sep 8, 2026 at 10:00:00\n"
        self.assertTrue(production.codesign_is_release_ready(ready))
        self.assertFalse(production.codesign_is_release_ready("Authority=Developer ID Application: Example (TEAMID)\n"))
        self.assertFalse(production.codesign_is_release_ready("Authority=Apple Development: Example\nTimestamp=now\n"))

    def test_codesign_wrapper_replaces_only_timestamp_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = production.write_codesign_wrapper(Path(tmp))
            text = wrapper.read_text(encoding="utf-8")
        self.assertIn('[[ "$arg" == "--timestamp=none" ]]', text)
        self.assertIn('args+=("--timestamp")', text)
        self.assertIn('exec /usr/bin/codesign', text)

    @patch.object(production, "run")
    def test_notary_submit_fails_closed_when_not_accepted(self, run: Mock) -> None:
        run.return_value = Mock(stdout=json.dumps({"id": "submission", "status": "Invalid"}))
        with self.assertRaisesRegex(RuntimeError, "notarization was not accepted"):
            production.notary_submit(Path("ClosedRoom.dmg"), "profile", cwd=ROOT)


class MeasuredReleaseContractTests(unittest.TestCase):
    def test_production_manifest_rejects_non_notarized_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            app = directory / "ClosedRoom.app"
            app.mkdir()
            (directory / "build-manifest.json").write_text(
                json.dumps({"configuration": {"signing": "identified"}}),
                encoding="utf-8",
            )
            (directory / "production-release-evidence.json").write_text(
                json.dumps({"status": "pass"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "signing is not release-ready"):
                measured.production_manifest_for(app)

    def test_production_manifest_requires_release_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            app = directory / "ClosedRoom.app"
            app.mkdir()
            manifest = directory / "build-manifest.json"
            manifest.write_text(
                json.dumps({"configuration": {"signing": "developer-id-notarized"}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "production-release-evidence"):
                measured.production_manifest_for(app)
            (directory / "production-release-evidence.json").write_text(
                json.dumps({"status": "pass"}),
                encoding="utf-8",
            )
            path, payload = measured.production_manifest_for(app)
            self.assertEqual(path, manifest)
            self.assertEqual(payload["configuration"]["signing"], "developer-id-notarized")

    def test_process_family_includes_descendants_only(self) -> None:
        table = {
            10: (1, 2.0, 100),
            11: (10, 3.0, 200),
            12: (11, 4.0, 300),
            20: (1, 9.0, 900),
        }
        self.assertEqual(measured.family_pids(10, table), {10, 11, 12})

    def test_resource_sanitizer_keeps_only_bounded_metrics(self) -> None:
        payload = {
            "app_process": {"current_rss_bytes": 100, "peak_rss_bytes": 200, "secret": "no"},
            "llm_sidecar": {"status": "ready", "current_rss_bytes": 300},
            "heavy_workloads": {"status": "available", "active_count": 1, "queue_depth": 0, "active_by_type": {"transcription": 1}, "pending": {"id": "private"}},
            "machine": {"physical_memory_bytes": 1000},
        }
        result = measured.sanitize_runtime_resources(payload)
        self.assertEqual(result["heavy_active_by_type"], {"transcription": 1})
        self.assertEqual(result["physical_memory_bytes"], 1000)
        self.assertNotIn("secret", result)
        self.assertNotIn("pending", result)

    @patch.object(measured.subprocess, "run")
    def test_thermal_sample_is_unknown_when_metrics_are_unavailable(self, run: Mock) -> None:
        run.return_value = Mock(stdout="", stderr="", returncode=0)
        self.assertEqual(measured.thermal_sample()["status"], "unknown")

    @patch.object(measured.subprocess, "run")
    def test_thermal_sample_parses_numeric_limits(self, run: Mock) -> None:
        run.return_value = Mock(stdout="CPU_Scheduler_Limit = 100\nCPU_Speed_Limit = 95\n", stderr="", returncode=0)
        sample = measured.thermal_sample()
        self.assertEqual(sample["status"], "available")
        self.assertEqual(sample["metrics"]["cpu_scheduler_limit"], 100)
        self.assertEqual(sample["metrics"]["cpu_speed_limit"], 95)


if __name__ == "__main__":
    unittest.main()
