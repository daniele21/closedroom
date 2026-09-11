from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "SettingsPage.tsx"


class SettingsSimplicityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PAGE.read_text(encoding="utf-8")

    def test_provider_and_runtime_controls_are_progressively_disclosed(self) -> None:
        self.assertIn("showAdvancedProcessing", self.source)
        self.assertIn('aria-controls="settings-advanced-processing"', self.source)
        self.assertIn("showDiagnostics", self.source)
        self.assertIn('aria-controls="settings-developer-diagnostics"', self.source)
        self.assertIn("Providers, models and quality overrides", self.source)
        self.assertIn("Runtime, endpoints, model paths", self.source)

    def test_normal_surface_leads_with_outcome_preferences(self) -> None:
        advanced_start = self.source.index('id="settings-advanced-processing"')
        provider_asr = self.source.index('label="Provider ASR"')
        provider_llm = self.source.index("label={t('settings.providerLabel')}")
        self.assertGreater(provider_asr, advanced_start)
        self.assertGreater(provider_llm, advanced_start)
        self.assertIn("Preferences that change the outcome", self.source)
        self.assertIn("Privacy & processing", self.source)

    def test_runtime_lifecycle_controls_live_under_diagnostics(self) -> None:
        diagnostics_start = self.source.index('id="settings-developer-diagnostics"')
        start_runtime = self.source.index("runLlmAction('start')")
        model_path = self.source.index('id="settings-local-model-path"')
        self.assertGreater(start_runtime, diagnostics_start)
        self.assertGreater(model_path, diagnostics_start)


if __name__ == "__main__":
    unittest.main()
