import json
import re
import unittest

from local_asr_server.structured_notes import (
    AGGREGATION_PROMPT,
    StructuredNotesError,
    StructuredNotesInputTooLarge,
    build_source_chunks,
    generate_structured_notes,
    legacy_projection_results,
    normalize_structured_notes,
)
from local_asr_server.structured_notes_evaluation import (
    evaluate_structured_notes,
    passes_default_gate,
)


class FixtureProvider:
    def __init__(self) -> None:
        self.calls = []

    def analyze(self, text, prompt=None, temperature=None):
        self.calls.append({"text": text, "prompt": prompt, "temperature": temperature})
        if prompt == AGGREGATION_PROMPT:
            payload = json.loads(text)
            partials = payload["partials"]
            summaries = [part["summary"] for part in partials if part.get("summary", {}).get("text")]
            actions = [item for part in partials for item in part.get("actions", [])]
            decisions = [item for part in partials for item in part.get("decisions", [])]
            risks = [item for part in partials for item in part.get("risks", [])]
            refs = [ref for summary in summaries for ref in summary.get("source_refs", [])]
            return {
                "generated": {
                    "summary": {"text": "Combined meeting summary", "source_refs": refs[:3]},
                    "actions": actions,
                    "decisions": decisions,
                    "risks": risks,
                }
            }

        segment_ids = [int(value) for value in re.findall(r"\[S(\d+)", text)]
        first = segment_ids[0]
        last = segment_ids[-1]
        action = []
        decision = []
        risk = []
        if 1 in segment_ids:
            action.append({
                "text": "Alex validates the release by Friday",
                "owner": "Alex",
                "due": "Friday",
                "status": None,
                "source_refs": [{"segment_id": 1}],
            })
        if 2 in segment_ids:
            decision.append({
                "text": "The team will ship only after validation",
                "rationale": "Reduce release risk",
                "impact": None,
                "source_refs": [{"segment_id": 2}],
            })
        if 3 in segment_ids:
            risk.append({
                "text": "Validation is still blocking the release",
                "severity": None,
                "impact": "Release may slip",
                "next_step": "Complete validation",
                "source_refs": [{"segment_id": 3}],
            })
        return {
            "generated": {
                "summary": {
                    "text": "The release depends on validation.",
                    "source_refs": [{"segment_id": first}, {"segment_id": last}],
                },
                "actions": action,
                "decisions": decision,
                "risks": risk,
            }
        }


def meeting_transcription(*, pad: int = 0):
    suffix = (" detail" * pad).strip()
    return {
        "id": "transcript-1",
        "text": "Release validation meeting",
        "segments": [
            {"id": 0, "start": 0.0, "end": 5.0, "speaker_label": "Sam", "text": f"We are reviewing the release. {suffix}"},
            {"id": 1, "start": 5.0, "end": 12.0, "speaker_label": "Alex", "text": f"I will validate the release by Friday. {suffix}"},
            {"id": 2, "start": 12.0, "end": 20.0, "speaker_label": "Sam", "text": f"Decision: we ship only after validation. {suffix}"},
            {"id": 3, "start": 20.0, "end": 27.0, "speaker_label": "Lee", "text": f"Validation is still blocking the release. {suffix}"},
        ],
    }


class StructuredNotesTests(unittest.TestCase):
    def test_short_meeting_uses_one_inference_and_passes_default_rubric(self) -> None:
        provider = FixtureProvider()
        result = generate_structured_notes(provider, meeting_transcription())

        self.assertEqual(result["schema"]["version"], 2)
        self.assertEqual(result["metrics"]["inference_count"], 1)
        self.assertEqual(result["metrics"]["source_chunk_count"], 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["generated"]["actions"][0]["source_refs"][0]["segment_id"], 1)

        expected = {
            "actions": [{"contains": ["validate", "Friday"], "segment_ids": [1]}],
            "decisions": [{"contains": ["ship", "validation"], "segment_ids": [2]}],
            "risks": [{"contains": ["blocking", "release"], "segment_ids": [3]}],
        }
        baseline_tokens = result["metrics"]["estimated_input_tokens"] * 4
        report = evaluate_structured_notes(
            result,
            expected,
            baseline_metrics={
                "inference_count": 4,
                "estimated_input_tokens": baseline_tokens,
                "peak_rss_bytes": None,
            },
        )
        self.assertEqual(report["factual_support"], 1.0)
        self.assertEqual(report["action_recall"], 1.0)
        self.assertEqual(report["decision_recall"], 1.0)
        self.assertEqual(report["attribution"], 1.0)
        self.assertTrue(report["inference_count_improved"])
        self.assertEqual(report["peak_memory_assessment"], "unknown")
        self.assertTrue(passes_default_gate(report))

    def test_long_meeting_chunks_by_source_and_aggregates_without_dropping_refs(self) -> None:
        provider = FixtureProvider()
        result = generate_structured_notes(
            provider,
            meeting_transcription(pad=45),
            source_char_budget=500,
            max_source_chunks=8,
        )

        self.assertGreater(result["metrics"]["source_chunk_count"], 1)
        self.assertGreater(result["metrics"]["inference_count"], result["metrics"]["source_chunk_count"])
        decision_refs = result["generated"]["decisions"][0]["source_refs"]
        self.assertEqual(decision_refs[0]["segment_id"], 2)
        self.assertTrue(any(call["prompt"] == AGGREGATION_PROMPT for call in provider.calls))

    def test_oversized_input_fails_explicitly_instead_of_truncating(self) -> None:
        with self.assertRaises(StructuredNotesInputTooLarge) as ctx:
            build_source_chunks(
                meeting_transcription(pad=80),
                char_budget=500,
                max_chunks=1,
            )
        self.assertIn("refuses to silently truncate", str(ctx.exception))

    def test_missing_source_reference_is_rejected(self) -> None:
        _chunks, refs = build_source_chunks(meeting_transcription())
        with self.assertRaises(StructuredNotesError):
            normalize_structured_notes(
                {
                    "generated": {
                        "summary": {"text": "Unsupported summary", "source_refs": []},
                        "actions": [],
                        "decisions": [],
                        "risks": [],
                    }
                },
                refs,
            )

    def test_legacy_projections_preserve_four_default_views(self) -> None:
        result = generate_structured_notes(FixtureProvider(), meeting_transcription())
        projections = legacy_projection_results(result)
        self.assertEqual(
            set(projections),
            {"meeting_brief", "action_items", "decisions", "risks_blockers"},
        )
        self.assertIn("Alex validates the release", projections["action_items"]["markdown"])
        self.assertIn("ship only after validation", projections["decisions"]["markdown"])
        self.assertIn("blocking the release", projections["risks_blockers"]["markdown"])


if __name__ == "__main__":
    unittest.main()
