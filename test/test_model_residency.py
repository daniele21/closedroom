from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from local_asr_server.runtime.service_manager import RuntimeServiceManager
from local_asr_server.schemas import AnalysisRequest
from local_asr_server.services.analysis_service import AnalysisService


class ModelResidencyTests(unittest.TestCase):
    def test_runtime_release_only_mutates_managed_auto_sidecar(self) -> None:
        sidecar = Mock()
        sidecar.release_resident_models.return_value = {"released": True, "cold": True}
        manager = RuntimeServiceManager(llm_sidecar=sidecar)
        with patch("local_asr_server.runtime.service_manager.load_settings", return_value={
            "local_llm_mode": "auto",
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_model_path": "",
        }):
            result = manager.release_llm_residency()
        self.assertTrue(result["released"])
        sidecar.release_resident_models.assert_called_once_with()

        sidecar.reset_mock()
        with patch("local_asr_server.runtime.service_manager.load_settings", return_value={
            "local_llm_mode": "auto",
            "local_llm_model": "nemotron-nano-4b-q8",
        }):
            result = manager.release_llm_residency(overrides={
                "local_llm_mode": "external",
                "local_llm_model": "nemotron-nano-4b-q8",
                "local_llm_url": "http://127.0.0.1:5555",
            })
        self.assertEqual(result["reason"], "not_managed")
        sidecar.release_resident_models.assert_not_called()

    def test_local_analysis_releases_residency_after_success(self) -> None:
        services = Mock()
        services.runtime.ensure_llm_ready.return_value = {
            "base_url": "http://127.0.0.1:1235",
            "model": "nemotron-nano-4b-q8",
        }
        provider = Mock()
        provider.analyze.return_value = {
            "title": "Title", "summary": "Summary", "key_points": [], "action_items": []
        }
        services.catalog.get_analysis_cache.return_value = None
        settings = {
            "llm_provider": "nemotron_local",
            "local_llm_mode": "auto",
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_reasoning": "off",
            "local_llm_quality_preset": "balanced",
            "local_llm_json_mode": True,
        }
        with (
            patch("local_asr_server.services.analysis_service.load_settings", return_value=settings),
            patch("local_asr_server.services.analysis_service.LLMService.get_provider", return_value=provider),
        ):
            result = AnalysisService(services).analyze(
                AnalysisRequest(text="meeting text", llm_provider="nemotron_local")
            )
        self.assertEqual(result["title"], "Title")
        services.runtime.release_llm_residency.assert_called_once_with(overrides=settings)

    def test_local_analysis_releases_residency_after_failure(self) -> None:
        services = Mock()
        services.runtime.ensure_llm_ready.return_value = {
            "base_url": "http://127.0.0.1:1235",
            "model": "nemotron-nano-4b-q8",
        }
        provider = Mock()
        provider.analyze.side_effect = RuntimeError("inference failed")
        services.catalog.get_analysis_cache.return_value = None
        settings = {
            "llm_provider": "nemotron_local",
            "local_llm_mode": "auto",
            "local_llm_model": "nemotron-nano-4b-q8",
            "local_llm_reasoning": "off",
            "local_llm_quality_preset": "balanced",
            "local_llm_json_mode": True,
        }
        with (
            patch("local_asr_server.services.analysis_service.load_settings", return_value=settings),
            patch("local_asr_server.services.analysis_service.LLMService.get_provider", return_value=provider),
            self.assertRaises(HTTPException),
        ):
            AnalysisService(services).analyze(
                AnalysisRequest(text="meeting text", llm_provider="nemotron_local")
            )
        services.runtime.release_llm_residency.assert_called_once_with(overrides=settings)


if __name__ == "__main__":
    unittest.main()
