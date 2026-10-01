from __future__ import annotations

import re
import unittest

from local_asr_server.structured_notes import (
    AGGREGATION_PROMPT,
    StructuredNotesError,
    generate_structured_notes,
)


def two_chunk_transcript():
    filler = " context" * 70
    return {
        "id": "trans-boundary",
        "text": "source boundary fixture",
        "segments": [
            {"id": 0, "start": 0.0, "end": 5.0, "text": f"First supported fact.{filler}"},
            {"id": 1, "start": 5.0, "end": 10.0, "text": f"Second supported fact.{filler}"},
        ],
    }


class CrossChunkCitationProvider:
    def analyze(self, text, prompt=None, temperature=None):
        return {
            "generated": {
                "summary": {
                    "text": "Citation from a segment not supplied to this chunk",
                    "source_refs": [{"segment_id": 1}],
                },
                "actions": [],
                "decisions": [],
                "risks": [],
            }
        }


class AggregationCitationProvider:
    def analyze(self, text, prompt=None, temperature=None):
        if prompt == AGGREGATION_PROMPT:
            return {
                "generated": {
                    "summary": {
                        "text": "Aggregation attempted to introduce a previously unused ref",
                        "source_refs": [{"segment_id": 1}],
                    },
                    "actions": [],
                    "decisions": [],
                    "risks": [],
                }
            }
        ids = [int(value) for value in re.findall(r"\[S(\d+)", text)]
        if 0 in ids:
            return {
                "generated": {
                    "summary": {"text": "First fact", "source_refs": [{"segment_id": 0}]},
                    "actions": [],
                    "decisions": [],
                    "risks": [],
                }
            }
        return {
            "generated": {
                "summary": {"text": "", "source_refs": []},
                "actions": [],
                "decisions": [],
                "risks": [],
            }
        }


class StructuredNotesSourceBoundaryTests(unittest.TestCase):
    def test_extraction_cannot_reference_segment_outside_current_chunk(self) -> None:
        with self.assertRaises(StructuredNotesError):
            generate_structured_notes(
                CrossChunkCitationProvider(),
                two_chunk_transcript(),
                source_char_budget=700,
                max_source_chunks=4,
            )

    def test_aggregation_cannot_introduce_reference_absent_from_partials(self) -> None:
        with self.assertRaises(StructuredNotesError):
            generate_structured_notes(
                AggregationCitationProvider(),
                two_chunk_transcript(),
                source_char_budget=700,
                max_source_chunks=4,
            )


if __name__ == "__main__":
    unittest.main()
