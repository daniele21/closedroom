from __future__ import annotations

import time
import unittest

from local_asr_server.runtime.workload_arbiter import HeavyWorkloadArbiter, WorkloadQueueFull


class CaptureReservationCapacityTests(unittest.TestCase):
    def test_worker_held_pending_item_still_consumes_capacity(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=1)
        ran = False
        try:
            self.assertEqual(arbiter.reserve_capture("capture-one")["status"], "granted")
            arbiter.submit(
                task_id="held",
                workload_type="analysis",
                run=lambda: None,
            )

            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if arbiter.snapshot()["queue_depth"] == 1:
                    break
                time.sleep(0.01)
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)

            with self.assertRaises(WorkloadQueueFull):
                arbiter.submit(
                    task_id="must-not-fit",
                    workload_type="transcription",
                    run=lambda: None,
                )
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)
            self.assertEqual(arbiter.snapshot()["rejected"], 1)
        finally:
            arbiter.release_capture("capture-one")
            arbiter.shutdown()


if __name__ == "__main__":
    unittest.main()
