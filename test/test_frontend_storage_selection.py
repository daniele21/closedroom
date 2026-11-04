from __future__ import annotations

import unittest
from pathlib import Path


PAGE = Path(__file__).parents[1] / "frontend/src/pages/SettingsPage.tsx"
CLIENT = Path(__file__).parents[1] / "frontend/src/api/apiClient.ts"


class StorageSelectionFrontendContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = PAGE.read_text(encoding="utf-8")
        self.client = CLIENT.read_text(encoding="utf-8")

    def test_accessible_mutually_exclusive_choices_with_local_default(self) -> None:
        self.assertIn("data-storage-target-selection", self.page)
        self.assertIn("storagePreference] = useState<'local' | 'gcs'>('local')", self.page)
        self.assertIn('id="settings-storage-local"', self.page)
        self.assertIn('id="settings-storage-gcs"', self.page)
        self.assertEqual(self.page.count('name="storage-target"'), 2)
        self.assertIn("checked={storagePreference === 'local'}", self.page)
        self.assertIn("checked={storagePreference === 'gcs'}", self.page)
        self.assertIn('aria-describedby="storage-target-help"', self.page)

    def test_effective_mode_never_derived_from_preference(self) -> None:
        self.assertIn("settings.storage_effective_mode === 'gcs'", self.page)
        self.assertIn('data-storage-effective-mode={storageEffectiveMode}', self.page)
        self.assertIn("storage_effective_mode?: 'local' | 'gcs'", self.client)
        self.assertIn("storage_capability?: 'preparation_only'", self.client)

    def test_cloud_fields_are_only_preparation_and_no_upload_action_exists(self) -> None:
        for field in ("storage_preference:", "gcs_project_id:", "gcs_bucket_name:", "gcs_region:"):
            self.assertIn(field, self.page)
        self.assertIn('data-storage-gcs-preparation="true"', self.page)
        self.assertIn("Nessun nuovo audio sarà caricato automaticamente", self.page)
        self.assertNotIn("ApiClient.uploadGcs", self.page)
        self.assertNotIn("audio_auto_cleanup_enabled: true", self.page)


if __name__ == "__main__":
    unittest.main()
