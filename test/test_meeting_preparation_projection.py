from __future__ import annotations

import unittest

from local_asr_server.routers.helpers import _exclude_incomplete_preparation_runs


class MeetingPreparationProjectionTests(unittest.TestCase):
    def test_incomplete_preparation_pipeline_is_not_promoted_as_ready_notes(self) -> None:
        runs = [
            {"id": "partial", "pipeline_run_id": "pipeline-failed", "status": "completed"},
            {"id": "older", "pipeline_run_id": "pipeline-complete", "status": "completed"},
            {"id": "manual", "pipeline_run_id": None, "status": "completed"},
        ]
        jobs = [
            {
                "id": "parent-failed",
                "type": "meeting_preparation",
                "status": "failed",
                "result": {"pipeline_run_id": "pipeline-failed"},
            },
            {
                "id": "parent-complete",
                "type": "meeting_preparation",
                "status": "completed",
                "result": {"pipeline_run_id": "pipeline-complete"},
            },
        ]

        visible = _exclude_incomplete_preparation_runs(runs, jobs)

        self.assertEqual([run["id"] for run in visible], ["older", "manual"])

    def test_cancelled_and_interrupted_preparation_output_are_non_canonical(self) -> None:
        for status in ("cancelled", "interrupted"):
            with self.subTest(status=status):
                visible = _exclude_incomplete_preparation_runs(
                    [
                        {
                            "id": "partial",
                            "pipeline_run_id": "pipeline-incomplete",
                            "status": "completed",
                        }
                    ],
                    [
                        {
                            "id": "parent",
                            "type": "meeting_preparation",
                            "status": status,
                            "result": {"pipeline_run_id": "pipeline-incomplete"},
                        }
                    ],
                )
                self.assertEqual(visible, [])


if __name__ == "__main__":
    unittest.main()
