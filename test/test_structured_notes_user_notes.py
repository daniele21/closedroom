from __future__ import annotations

import unittest

from local_asr_server.structured_notes import generate_structured_notes


class UserNoteProvider:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def analyze(self, text, prompt=None, temperature=None):
        self.inputs.append(text)
        return {
            "generated": {
                "summary": {
                    "text": "Remember to ask Marco for the updated numbers.",
                    "source_refs": [{"source_type": "user_note", "note_id": "note-1"}],
                },
                "actions": [],
                "decisions": [],
                "risks": [],
            }
        }


class StructuredUserNoteProvenanceTests(unittest.TestCase):
    def test_user_note_is_a_distinct_timestamped_source(self) -> None:
        provider = UserNoteProvider()
        result = generate_structured_notes(
            provider,
            {
                "id": "trans-1",
                "text": "Marco discussed the launch.",
                "segments": [
                    {"id": 0, "start": 0.0, "end": 20.0, "text": "Marco discussed the launch."},
                ],
                "user_note_sources": [
                    {
                        "note_id": "note-1",
                        "timestamp": 12.5,
                        "text": "Ask Marco for updated numbers",
                        "revision": 2,
                    }
                ],
            },
        )

        self.assertTrue(any("[Nnote-1 t=12.50" in value for value in provider.inputs))
        summary = result["generated"]["summary"]
        self.assertEqual(summary["evidence_basis"], "user_note")
        self.assertEqual(summary["source_refs"][0]["source_type"], "user_note")
        self.assertEqual(summary["source_refs"][0]["source_id"], "user_note:note-1")
        self.assertEqual(summary["source_refs"][0]["timestamp"], 12.5)
        self.assertTrue(summary["source_refs"][0]["user_authored"])
        self.assertTrue(summary["source_refs"][0]["user_marked"])


if __name__ == "__main__":
    unittest.main()
