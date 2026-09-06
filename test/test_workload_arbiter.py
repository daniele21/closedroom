from __future__ import annotations

import threading
import time
import unittest

from local_asr_server.runtime.resource_policy import ResourcePolicyBlocked
from local_asr_server.runtime.workload_arbiter import (
    CaptureReservationConflict,
    HeavyWorkloadArbiter,
    WorkloadAdmissionRejected,
    WorkloadQueueFull,
)
from local_asr_server.transcription_jobs import TranscriptionJobManager


class HeavyWorkloadArbiterTests(unittest.TestCase):
    def test_serializes_heavy_work_by_default(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        order: list[str] = []

        def first() -> None:
            order.append("first-start")
            first_started.set()
            release_first.wait(timeout=2.0)
            order.append("first-end")

        def second() -> None:
            order.append("second-start")
            second_started.set()

        try:
            arbiter.submit(task_id="one", workload_type="transcription", run=first)
            self.assertTrue(first_started.wait(timeout=1.0))
            arbiter.submit(task_id="two", workload_type="analysis", run=second)

            snapshot = arbiter.snapshot()
            self.assertEqual(snapshot["active_count"], 1)
            self.assertEqual(snapshot["queue_depth"], 1)
            self.assertFalse(second_started.wait(timeout=0.05))

            release_first.set()
            self.assertTrue(second_started.wait(timeout=1.0))
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and arbiter.snapshot()["completed"] < 2:
                time.sleep(0.01)

            self.assertEqual(order, ["first-start", "first-end", "second-start"])
            self.assertEqual(arbiter.snapshot()["completed"], 2)
        finally:
            release_first.set()
            arbiter.shutdown()

    def test_rejects_when_pending_capacity_is_full(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=1)
        first_started = threading.Event()
        release_first = threading.Event()

        def first() -> None:
            first_started.set()
            release_first.wait(timeout=2.0)

        try:
            arbiter.submit(task_id="one", workload_type="transcription", run=first)
            self.assertTrue(first_started.wait(timeout=1.0))
            arbiter.submit(task_id="two", workload_type="analysis", run=lambda: None)
            with self.assertRaises(WorkloadQueueFull):
                arbiter.submit(task_id="three", workload_type="vision", run=lambda: None)
            self.assertEqual(arbiter.snapshot()["rejected"], 1)
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)
        finally:
            release_first.set()
            arbiter.shutdown()

    def test_cancels_pending_work_without_running_it(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        first_started = threading.Event()
        release_first = threading.Event()
        cancelled = threading.Event()
        second_ran = threading.Event()

        def first() -> None:
            first_started.set()
            release_first.wait(timeout=2.0)

        try:
            arbiter.submit(task_id="one", workload_type="transcription", run=first)
            self.assertTrue(first_started.wait(timeout=1.0))
            arbiter.submit(
                task_id="two",
                workload_type="analysis",
                run=second_ran.set,
                on_cancel=lambda _reason: cancelled.set(),
            )
            self.assertTrue(arbiter.cancel_pending("two"))
            release_first.set()
            self.assertTrue(cancelled.wait(timeout=1.0))
            self.assertFalse(second_ran.is_set())
            self.assertEqual(arbiter.snapshot()["cancelled_pending"], 1)
        finally:
            release_first.set()
            arbiter.shutdown()

    def test_capture_reservation_waits_for_active_work_then_blocks_queued_work(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        def first() -> None:
            first_started.set()
            release_first.wait(timeout=2.0)

        try:
            arbiter.submit(task_id="one", workload_type="analysis", run=first)
            self.assertTrue(first_started.wait(timeout=1.0))
            reservation = arbiter.reserve_capture("capture-one")
            self.assertEqual(reservation["status"], "waiting")

            arbiter.submit(task_id="two", workload_type="transcription", run=second_started.set)
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)

            release_first.set()
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if arbiter.capture_reservation("capture-one")["status"] == "granted":
                    break
                time.sleep(0.01)

            self.assertEqual(arbiter.capture_reservation("capture-one")["status"], "granted")
            self.assertFalse(second_started.wait(timeout=0.05))
            self.assertTrue(arbiter.release_capture("capture-one"))
            self.assertTrue(second_started.wait(timeout=1.0))
        finally:
            release_first.set()
            arbiter.release_capture("capture-one")
            arbiter.shutdown()

    def test_work_submitted_during_reserved_capture_waits_instead_of_failing_admission(self) -> None:
        capture_active = False
        started = threading.Event()

        def guard(_workload_type: str) -> None:
            if capture_active:
                raise ResourcePolicyBlocked("capture_active")

        arbiter = HeavyWorkloadArbiter(
            max_concurrent=1,
            queue_capacity=2,
            admission_guard=guard,
        )
        try:
            self.assertEqual(arbiter.reserve_capture("capture-one")["status"], "granted")
            capture_active = True
            arbiter.submit(task_id="queued", workload_type="analysis", run=started.set)
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)
            self.assertFalse(started.wait(timeout=0.05))

            capture_active = False
            self.assertTrue(arbiter.release_capture("capture-one"))
            self.assertTrue(started.wait(timeout=1.0))
            self.assertEqual(arbiter.snapshot()["rejected"], 0)
        finally:
            arbiter.release_capture("capture-one")
            arbiter.shutdown()

    def test_pending_cancel_remains_effective_while_capture_is_reserved(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        cancelled = threading.Event()
        ran = threading.Event()
        try:
            self.assertEqual(arbiter.reserve_capture("capture-one")["status"], "granted")
            arbiter.submit(
                task_id="queued",
                workload_type="analysis",
                run=ran.set,
                on_cancel=lambda _reason: cancelled.set(),
            )
            self.assertTrue(arbiter.cancel_pending("queued"))
            self.assertTrue(cancelled.wait(timeout=1.0))
            self.assertFalse(ran.is_set())
            self.assertEqual(arbiter.snapshot()["cancelled_pending"], 1)
        finally:
            arbiter.release_capture("capture-one")
            arbiter.shutdown()

    def test_only_one_capture_reservation_can_be_active(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        try:
            first = arbiter.reserve_capture("capture-one")
            self.assertEqual(first["status"], "granted")
            with self.assertRaises(CaptureReservationConflict):
                arbiter.reserve_capture("capture-two")
            self.assertTrue(arbiter.release_capture("capture-one"))
            self.assertEqual(arbiter.reserve_capture("capture-two")["status"], "granted")
        finally:
            arbiter.release_capture("capture-two")
            arbiter.shutdown()

    def test_resource_policy_rejects_submission_while_capture_is_active(self) -> None:
        capture_active = True

        def guard(_workload_type: str) -> None:
            if capture_active:
                raise ResourcePolicyBlocked("capture_active")

        arbiter = HeavyWorkloadArbiter(
            max_concurrent=1,
            queue_capacity=2,
            admission_guard=guard,
        )
        try:
            with self.assertRaises(WorkloadAdmissionRejected) as ctx:
                arbiter.submit(task_id="blocked", workload_type="analysis", run=lambda: None)
            self.assertEqual(str(ctx.exception), "capture_active")
            self.assertEqual(arbiter.snapshot()["rejected"], 1)
            self.assertEqual(arbiter.snapshot()["queue_depth"], 0)
        finally:
            arbiter.shutdown()

    def test_capture_start_rejects_work_that_was_already_queued(self) -> None:
        capture_active = False
        first_started = threading.Event()
        release_first = threading.Event()
        rejected = threading.Event()
        second_ran = threading.Event()
        rejection_reason: list[str] = []

        def guard(_workload_type: str) -> None:
            if capture_active:
                raise ResourcePolicyBlocked("capture_active")

        def first() -> None:
            first_started.set()
            release_first.wait(timeout=2.0)

        arbiter = HeavyWorkloadArbiter(
            max_concurrent=1,
            queue_capacity=2,
            admission_guard=guard,
        )
        try:
            arbiter.submit(task_id="one", workload_type="analysis", run=first)
            self.assertTrue(first_started.wait(timeout=1.0))
            arbiter.submit(
                task_id="two",
                workload_type="transcription",
                run=second_ran.set,
                on_reject=lambda reason: (rejection_reason.append(reason), rejected.set()),
            )
            capture_active = True
            release_first.set()

            self.assertTrue(rejected.wait(timeout=1.0))
            self.assertFalse(second_ran.is_set())
            self.assertEqual(rejection_reason, ["capture_active"])
            self.assertEqual(arbiter.snapshot()["rejected"], 1)
        finally:
            release_first.set()
            arbiter.shutdown()

    def test_transcription_manager_uses_shared_arbiter(self) -> None:
        arbiter = HeavyWorkloadArbiter(max_concurrent=1, queue_capacity=2)
        manager = TranscriptionJobManager(arbiter=arbiter)
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        def first_runner(_job):
            first_started.set()
            release_first.wait(timeout=2.0)
            return {"outcome_status": "completed", "diagnostics": []}

        def second_runner(_job):
            second_started.set()
            return {"outcome_status": "completed", "diagnostics": []}

        try:
            first = manager.create("rec-1", first_runner)
            self.assertTrue(first_started.wait(timeout=1.0))
            second = manager.create("rec-2", second_runner)
            self.assertFalse(second_started.wait(timeout=0.05))
            self.assertEqual(arbiter.snapshot()["queue_depth"], 1)

            release_first.set()
            self.assertTrue(second_started.wait(timeout=1.0))
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if manager.get(second["id"])["status"] == "completed":
                    break
                time.sleep(0.01)

            self.assertEqual(manager.get(first["id"])["status"], "completed")
            self.assertEqual(manager.get(second["id"])["status"], "completed")
        finally:
            release_first.set()
            arbiter.shutdown()

    def test_transcription_manager_reports_policy_rejection_as_resource_admission_failure(self) -> None:
        def guard(_workload_type: str) -> None:
            raise ResourcePolicyBlocked("capture_active")

        arbiter = HeavyWorkloadArbiter(
            max_concurrent=1,
            queue_capacity=2,
            admission_guard=guard,
        )
        manager = TranscriptionJobManager(arbiter=arbiter)
        try:
            job = manager.create(
                "rec-1",
                lambda _job: {"outcome_status": "completed", "diagnostics": []},
            )
            stored = manager.get(job["id"])
            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["current_step"], "resource_admission")
            self.assertEqual(stored["error"], "capture_active")
        finally:
            arbiter.shutdown()


if __name__ == "__main__":
    unittest.main()
