from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable


class WorkloadQueueFull(RuntimeError):
    """Raised when the bounded heavy-workload queue cannot admit more work."""


class WorkloadArbiterClosed(RuntimeError):
    """Raised when work is submitted after shutdown has started."""


class WorkloadAdmissionRejected(RuntimeError):
    """Raised when resource policy forbids a heavy workload from starting."""


class CaptureReservationConflict(RuntimeError):
    """Raised when a second capture reservation is requested concurrently."""


class CaptureReservationNotFound(RuntimeError):
    """Raised when a capture reservation token is no longer active."""


@dataclass(frozen=True, slots=True)
class _WorkItem:
    task_id: str
    workload_type: str
    run: Callable[[], None]
    on_cancel: Callable[[str], None] | None = None
    on_reject: Callable[[str], None] | None = None


class HeavyWorkloadArbiter:
    """Bounded process-wide scheduler for memory-heavy ClosedRoom jobs.

    ClosedRoom owns cross-workload scheduling here. Model-level request admission,
    residency and eviction remain owned by local-llm-server. The default of one
    active heavy workload protects Apple unified memory until representative
    hardware evidence justifies a higher profile.

    Capture reservation is also coordinated here so starting a meeting and
    starting heavy AI cannot cross in a race. A reservation never force-kills
    active work: already-running work reaches its normal safe boundary, queued
    work remains pending, and the reservation becomes granted only when no heavy
    work is active. While the reservation is held, no queued work starts.

    The optional admission guard remains the fail-safe for capture that exists
    outside the reservation protocol. It is checked immediately before execution.
    """

    DEFAULT_MAX_CONCURRENT = 1
    DEFAULT_QUEUE_CAPACITY = 8

    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        queue_capacity: int = DEFAULT_QUEUE_CAPACITY,
        admission_guard: Callable[[str], None] | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be >= 1")
        self.max_concurrent = max_concurrent
        self.queue_capacity = queue_capacity
        self._admission_guard = admission_guard
        self._queue: queue.Queue[_WorkItem] = queue.Queue(maxsize=queue_capacity)
        self._lock = threading.RLock()
        self._state_changed = threading.Condition(self._lock)
        self._pending: dict[str, str] = {}
        self._active: dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._capture_reservation_id: str | None = None
        self._capture_reservation_state: str | None = None
        self._capture_requested_at: float | None = None
        self._closed = False
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._rejected = 0
        self._cancelled_pending = 0
        self._workers = [
            threading.Thread(
                target=self._worker,
                name=f"closedroom-heavy-{index + 1}",
                daemon=True,
            )
            for index in range(max_concurrent)
        ]
        for worker in self._workers:
            worker.start()

    @classmethod
    def from_env(
        cls,
        *,
        admission_guard: Callable[[str], None] | None = None,
    ) -> "HeavyWorkloadArbiter":
        return cls(
            max_concurrent=_positive_env_int(
                "CLOSEDROOM_HEAVY_WORKLOAD_CONCURRENCY",
                cls.DEFAULT_MAX_CONCURRENT,
            ),
            queue_capacity=_positive_env_int(
                "CLOSEDROOM_HEAVY_WORKLOAD_QUEUE_CAPACITY",
                cls.DEFAULT_QUEUE_CAPACITY,
            ),
            admission_guard=admission_guard,
        )

    def submit(
        self,
        *,
        task_id: str,
        workload_type: str,
        run: Callable[[], None],
        on_cancel: Callable[[str], None] | None = None,
        on_reject: Callable[[str], None] | None = None,
    ) -> None:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        if not workload_type.strip():
            raise ValueError("workload_type must be non-empty")

        # A reservation intentionally turns capture-active admission from a
        # failure into bounded waiting. Legacy/unreserved capture still uses the
        # guard and therefore fails safe as before.
        with self._lock:
            reservation_active = self._capture_reservation_id is not None
        if not reservation_active:
            self._assert_admitted(workload_type)

        item = _WorkItem(
            task_id=task_id,
            workload_type=workload_type,
            run=run,
            on_cancel=on_cancel,
            on_reject=on_reject,
        )
        with self._state_changed:
            if self._closed:
                raise WorkloadArbiterClosed("heavy-workload arbiter is shutting down")
            if task_id in self._pending or task_id in self._active:
                raise ValueError(f"task is already scheduled: {task_id}")
            try:
                self._queue.put_nowait(item)
            except queue.Full as exc:
                self._rejected += 1
                raise WorkloadQueueFull(
                    f"heavy-workload queue is full ({self.queue_capacity} pending); retry later"
                ) from exc
            self._pending[task_id] = workload_type
            self._submitted += 1
            self._state_changed.notify_all()

    def reserve_capture(self, reservation_id: str) -> dict[str, object]:
        """Reserve capture priority without interrupting already-running work."""
        if not reservation_id.strip():
            raise ValueError("reservation_id must be non-empty")
        with self._state_changed:
            if self._closed:
                raise WorkloadArbiterClosed("heavy-workload arbiter is shutting down")
            if self._capture_reservation_id not in {None, reservation_id}:
                raise CaptureReservationConflict("another capture reservation is already active")
            if self._capture_reservation_id is None:
                self._capture_reservation_id = reservation_id
                self._capture_requested_at = time.monotonic()
                self._capture_reservation_state = "waiting" if self._active else "granted"
            self._refresh_capture_reservation_locked()
            self._state_changed.notify_all()
            return self._capture_reservation_public_locked(reservation_id)

    def capture_reservation(self, reservation_id: str) -> dict[str, object]:
        with self._state_changed:
            if self._capture_reservation_id != reservation_id:
                raise CaptureReservationNotFound("capture reservation is not active")
            self._refresh_capture_reservation_locked()
            return self._capture_reservation_public_locked(reservation_id)

    def release_capture(self, reservation_id: str) -> bool:
        """Release capture priority and allow queued heavy work to resume."""
        with self._state_changed:
            if self._capture_reservation_id != reservation_id:
                return False
            self._capture_reservation_id = None
            self._capture_reservation_state = None
            self._capture_requested_at = None
            self._state_changed.notify_all()
            return True

    def cancel_pending(self, task_id: str) -> bool:
        """Mark queued work for cancellation without interrupting active execution."""
        with self._state_changed:
            if task_id not in self._pending:
                return False
            self._cancelled.add(task_id)
            self._state_changed.notify_all()
            return True

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._refresh_capture_reservation_locked()
            return {
                "max_concurrent": self.max_concurrent,
                "queue_capacity": self.queue_capacity,
                "queue_depth": len(self._pending),
                "active_count": len(self._active),
                "pending": dict(self._pending),
                "active": dict(self._active),
                "capture_reservation": {
                    "active": self._capture_reservation_id is not None,
                    "status": self._capture_reservation_state,
                },
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "rejected": self._rejected,
                "cancelled_pending": self._cancelled_pending,
                "closed": self._closed,
            }

    def shutdown(self, *, cancel_pending: bool = True, wait_timeout: float = 2.0) -> None:
        """Stop admission, optionally cancel queued work and wait boundedly for workers.

        Running work is not force-killed here because the owning runtime/process
        boundary is responsible for safe cancellation. Worker threads are daemon
        threads so process shutdown cannot be held indefinitely by a model job.
        """
        with self._state_changed:
            self._closed = True
            self._capture_reservation_id = None
            self._capture_reservation_state = None
            self._capture_requested_at = None
            if cancel_pending:
                self._cancelled.update(self._pending)
            self._state_changed.notify_all()
        deadline = time.monotonic() + max(0.0, wait_timeout)
        for worker in self._workers:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(timeout=remaining)

    def _assert_admitted(self, workload_type: str) -> None:
        if self._admission_guard is None:
            return
        try:
            self._admission_guard(workload_type)
        except Exception as exc:
            with self._lock:
                self._rejected += 1
            reason = str(exc) or exc.__class__.__name__
            raise WorkloadAdmissionRejected(reason) from exc

    def _refresh_capture_reservation_locked(self) -> None:
        if (
            self._capture_reservation_id is not None
            and self._capture_reservation_state == "waiting"
            and not self._active
        ):
            self._capture_reservation_state = "granted"

    def _capture_reservation_public_locked(self, reservation_id: str) -> dict[str, object]:
        if self._capture_reservation_id != reservation_id:
            raise CaptureReservationNotFound("capture reservation is not active")
        requested_at = self._capture_requested_at
        waited = max(0.0, time.monotonic() - requested_at) if requested_at is not None else 0.0
        return {
            "reservation_id": reservation_id,
            "status": self._capture_reservation_state or "waiting",
            "active_workloads": len(self._active),
            "queued_workloads": len(self._pending),
            "waited_seconds": round(waited, 3),
        }

    def _worker(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    if self._closed and not self._pending:
                        return
                continue

            cancelled = False
            rejection_reason: str | None = None

            while True:
                with self._state_changed:
                    while (
                        self._capture_reservation_id is not None
                        and item.task_id not in self._cancelled
                        and not self._closed
                    ):
                        self._refresh_capture_reservation_locked()
                        self._state_changed.wait(timeout=0.1)

                    cancelled = item.task_id in self._cancelled
                    if cancelled:
                        rejection_reason = None
                        break

                rejection_reason = None
                if self._admission_guard is not None:
                    try:
                        self._admission_guard(item.workload_type)
                    except Exception as exc:
                        rejection_reason = str(exc) or exc.__class__.__name__

                # A capture reservation may have arrived while the external
                # admission guard was running. Re-check under the scheduler lock
                # before converting pending work into active work.
                with self._state_changed:
                    if item.task_id in self._cancelled:
                        cancelled = True
                        rejection_reason = None
                        break
                    if self._capture_reservation_id is not None:
                        continue
                    break

            with self._state_changed:
                self._pending.pop(item.task_id, None)
                if item.task_id in self._cancelled:
                    self._cancelled.discard(item.task_id)
                    self._cancelled_pending += 1
                    cancelled = True
                    rejection_reason = None
                elif rejection_reason is not None:
                    self._rejected += 1
                else:
                    self._active[item.task_id] = item.workload_type
                self._refresh_capture_reservation_locked()
                self._state_changed.notify_all()

            try:
                if cancelled:
                    if item.on_cancel is not None:
                        item.on_cancel("cancelled_before_start")
                    continue
                if rejection_reason is not None:
                    if item.on_reject is not None:
                        item.on_reject(rejection_reason)
                    continue
                item.run()
            except Exception:
                with self._lock:
                    self._failed += 1
                # The job owner records user-visible failure. Do not kill the
                # scheduler worker because one workload failed.
            else:
                if not cancelled and rejection_reason is None:
                    with self._lock:
                        self._completed += 1
            finally:
                with self._state_changed:
                    self._active.pop(item.task_id, None)
                    self._refresh_capture_reservation_locked()
                    self._state_changed.notify_all()
                self._queue.task_done()


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value
