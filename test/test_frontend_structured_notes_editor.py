from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
EDITOR = ROOT / "frontend" / "src" / "components" / "meeting" / "StructuredNotesEditor.tsx"
API = ROOT / "frontend" / "src" / "api" / "structuredNotes.ts"


class FrontendStructuredNotesEditorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.editor = EDITOR.read_text(encoding="utf-8")
        self.api = API.read_text(encoding="utf-8")

    def test_removed_regeneration_conflicts_remain_visible_and_recoverable(self) -> None:
        self.assertIn("conflict.reason === 'item_missing'", self.editor)
        self.assertIn('data-note-conflict="item-missing"', self.editor)
        self.assertIn("Voce rimossa dalla rigenerazione", self.editor)
        self.assertIn("Item removed by regeneration", self.editor)
        self.assertIn("resolveConflict(conflict, false)", self.editor)
        self.assertIn("Scarta la correzione", self.editor)
        self.assertIn("Discard edit", self.editor)

    def test_removed_conflict_keeps_verifiable_source_snapshot(self) -> None:
        self.assertIn("base_generated?: StructuredNoteItem | null", self.api)
        self.assertIn("conflict.retained_edit.base_generated", self.editor)
        self.assertIn("<EvidenceRefs refs={sourceItem?.source_refs}", self.editor)
        self.assertIn("Previous generated", self.editor)
        self.assertIn("Versione precedente", self.editor)

    def test_editing_still_uses_generated_hash_optimistic_concurrency(self) -> None:
        self.assertIn("base_generated_hash: sourceItem.generated_hash", self.editor)
        self.assertIn("err?.status === 409", self.editor)
        self.assertIn("structuredSourceRunId(run)", self.editor)


if __name__ == "__main__":
    unittest.main()
