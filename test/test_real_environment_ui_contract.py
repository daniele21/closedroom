from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SMOKE_SCRIPT = SCRIPTS / "real_environment_smoke.py"
UI_EVIDENCE_SCRIPT = SCRIPTS / "real_environment_ui_evidence.py"
MEETING_PAGE = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
EXPECTED_WORKSPACE_LABELS = (
    "Prepare notes",
    "Prepara note",
    "Transcript only",
    "Solo trascrizione",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(SCRIPTS))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


class RealEnvironmentUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = load_module("real_environment_smoke_contract", SMOKE_SCRIPT)
        cls.ui_evidence = load_module(
            "real_environment_ui_evidence_contract", UI_EVIDENCE_SCRIPT
        )
        cls.meeting_source = MEETING_PAGE.read_text(encoding="utf-8")

    def test_post_stop_workspace_labels_exist_in_product_ui(self) -> None:
        self.assertEqual(
            self.smoke.LABELS["meeting_workspace"], EXPECTED_WORKSPACE_LABELS
        )
        self.assertNotIn("transcribe", self.smoke.LABELS)
        for label in EXPECTED_WORKSPACE_LABELS:
            with self.subTest(label=label):
                self.assertIn(label, self.meeting_source)

    def test_full_media_checkpoint_uses_same_workspace_labels(self) -> None:
        checkpoints = dict(self.ui_evidence.CHECKPOINTS)
        self.assertEqual(
            checkpoints["03-meeting-persisted"], EXPECTED_WORKSPACE_LABELS
        )
        self.assertEqual(
            checkpoints["03-meeting-persisted"],
            self.smoke.LABELS["meeting_workspace"],
        )


if __name__ == "__main__":
    unittest.main()
