from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from local_asr_server.jobs import JobStore
from local_asr_server.jobs.models import TERMINAL_JOB_STATUSES
from local_asr_server.runtime.workload_arbiter import (
    HeavyWorkloadArbiter,
    WorkloadAdmissionRejected,
    WorkloadArbiterClosed,
    WorkloadQueueFull,
)

TRANSCRIPTION_JOB_TYPE = "transcription"
DIARIZATION_JOB_TYPE = "diarization"
VISUAL_INTELLIGENCE_JOB_TYPE = "visual_intelligence"

logger = logging.getLogger("uvicorn.error")
JobTerminalCallback = Callable[[dict[str, Any]], None]


@dataclass
class TranscriptionJob:
    id: str
    recording_id: str | None
    job_type: str = TRANSCRIPTION_JOB_TYPE
    scope_type: str = "recording"
    scope_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    current_step: str = "queued"
    progress: int = 0
    progress_detail: dict[str, Any] | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_requested: bool = False
    events: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.job_type,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id or self.recording_id,
            "recording_id": self.recording_id,
            "status": self.status,
            "current_step": self.current_step,
            "progress": self.progress,
            "progress_detail": self.progress_detail,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TranscriptionJobManager:
    def __init__(
        self,
        store: JobStore | None = None,
        *,
        arbiter: HeavyWorkloadArbiter | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, TranscriptionJob] = {}
        self._store = store
        self._arbiter = arbiter

    def create(
        self,
        recording_id: str | None,
        runner: Callable[[TranscriptionJob], dict[str, Any]],
        *,
        job_type: str = TRANSCRIPTION_JOB_TYPE,
        scope_type: str = "recording",
        scope_id: str | None = None,
        payload: dict[str, Any] | None = None,
        on_terminal: JobTerminalCallback | None = None,
    ) -> dict[str, Any]:
        job = TranscriptionJob(
            id=str(uuid.uuid4()),
            recording_id=recording_id,
            job_type=job_type,
            scope_type=scope_type,
            scope_id=scope_id or recording_id,
            payload=payload or {},
        )
        with self._lock:
            self._jobs[job.id] = job
        if self._store is not None:
            self._store.create(
                job_id=job.id,
                job_type=job.job_type,
                scope_type=job.scope_type,
                scope_id=job.scope_id,
                payload=job.payload or {"recording_id": recording_id},
            )
        else:
            self._emit(job, "queued", 0)

        if self._arbiter is None:
            threading.Thread(
                target=self._run,
                args=(job, runner, on_terminal),
                daemon=True,
            ).start()
            return job.public()

        try:
            self._arbiter.submit(
                task_id=job.id,
                workload_type=job.job_type,
                run=lambda: self._run(job, runner, on_terminal),
                on_cancel=lambda reason: self._cancel_before_start(job, reason, on_terminal),
                on_reject=lambda reason: self._reject_before_start(job, reason, on_terminal),
            )
        except (WorkloadQueueFull, WorkloadArbiterClosed, WorkloadAdmissionRejected) as exc:
            self._reject_before_start(job, str(exc), on_terminal)
        return job.public()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return job.public()
        if self._store is None:
            return None
        stored = self._store.get(job_id)
        return self._stored_public(stored) if stored else None

    def list(
        self,
        *,
        job_type: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._store is None:
            with self._lock:
                jobs = list(self._jobs.values())
            return [
                job.public()
                for job in sorted(jobs, key=lambda item: item.created_at, reverse=True)
                if (job_type is None or job_type == job.job_type)
                and (scope_type is None or scope_type == job.scope_type)
                and (scope_id is None or scope_id == (job.scope_id or job.recording_id))
            ][:limit]
        return [
            self._stored_public(job)
            for job in self._store.list_jobs(
                job_type=job_type,
                scope_type=scope_type,
                scope_id=scope_id,
                limit=limit,
            )
        ]

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            if self._store is None:
                return None
            stored = self._store.request_cancel(job_id)
            return self._stored_public(stored) if stored else None
        if job.status in TERMINAL_JOB_STATUSES:
            return job.public()
        job.cancel_requested = True
        if self._store is not None:
            self._store.request_cancel(job.id)
        if self._arbiter is not None:
            self._arbiter.cancel_pending(job.id)
        if job.status not in TERMINAL_JOB_STATUSES:
            self._emit(job, "cancelling", job.progress, "cancelling")
        return job.public()

    def update_progress(
        self,
        job_id: str,
        status: str,
        progress: int,
        step: str | None = None,
        *,
        message: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            self._emit(job, status, progress, step, message=message, event_payload=event_payload)

    def drain_events(self, job_id: str) -> list[dict[str, Any]] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        events = []
        while True:
            try:
                events.append(job.events.get_nowait())
            except queue.Empty:
                return events

    def events_after(self, job_id: str, sequence: int = 0) -> list[dict[str, Any]] | None:
        if self._store is not None:
            events = self._store.events_after(job_id, sequence)
            if events is None:
                return None
            return [self._event_public(event) for event in events]
        events = self.drain_events(job_id)
        return events

    def _cancel_before_start(
        self,
        job: TranscriptionJob,
        reason: str,
        on_terminal: JobTerminalCallback | None = None,
    ) -> None:
        if job.status in TERMINAL_JOB_STATUSES:
            return
        job.cancel_requested = True
        if self._store is not None:
            self._store.request_cancel(job.id)
        self._emit(
            job,
            "cancelled",
            job.progress,
            "cancelled",
            message=reason,
            event_payload={"reason": reason},
        )
        self._notify_terminal(job, on_terminal)

    def _reject_before_start(
        self,
        job: TranscriptionJob,
        reason: str,
        on_terminal: JobTerminalCallback | None = None,
    ) -> None:
        if job.status in TERMINAL_JOB_STATUSES:
            return
        job.error = reason[:2000]
        self._emit(
            job,
            "failed",
            job.progress,
            "resource_admission",
            message="heavy_workload_not_admitted",
            event_payload={"reason": job.error},
        )
        self._notify_terminal(job, on_terminal)

    def _run(
        self,
        job: TranscriptionJob,
        runner: Callable[[TranscriptionJob], dict[str, Any]],
        on_terminal: JobTerminalCallback | None = None,
    ) -> None:
        try:
            if job.cancel_requested:
                self._emit(job, "cancelled", job.progress)
                return
            result = runner(job)
            if job.cancel_requested:
                self._emit(job, "cancelled", job.progress)
                return
            job.result = result
            self._emit(
                job,
                "completed",
                100,
                message=result.get("outcome_status"),
                event_payload={
                    "outcome_status": result.get("outcome_status", "completed"),
                    "diagnostics": result.get("diagnostics", []),
                },
            )
        except Exception as exc:
            if job.cancel_requested:
                self._emit(job, "cancelled", job.progress)
                return
            job.error = str(exc)[:2000]
            self._emit(job, "failed", job.progress)
        finally:
            if job.status in TERMINAL_JOB_STATUSES:
                self._notify_terminal(job, on_terminal)

    def _notify_terminal(
        self,
        job: TranscriptionJob,
        callback: JobTerminalCallback | None,
    ) -> None:
        if callback is None:
            return
        try:
            snapshot = self.get(job.id) or job.public()
            callback(snapshot)
        except Exception:
            logger.exception("Transcription terminal callback failed for job %s", job.id)

    def _emit(
        self,
        job: TranscriptionJob,
        status: str,
        progress: int,
        step: str | None = None,
        *,
        message: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        job.status = status
        job.current_step = step or status
        job.progress = progress
        job.progress_detail = event_payload
        job.updated_at = time.time()
        if self._store is None:
            job.events.put(job.public())
        else:
            self._store.update(
                job.id,
                status=status,
                current_step=job.current_step,
                progress=progress,
                result=job.result,
                error=job.error,
                cancel_requested=job.cancel_requested,
                message=message,
                event_payload=event_payload,
                progress_detail=event_payload,
            )

    def _stored_public(self, stored: dict[str, Any] | None) -> dict[str, Any]:
        if stored is None:
            return {}
        return {
            "id": stored["id"],
            "type": stored["type"],
            "scope_type": stored["scope_type"],
            "scope_id": stored["scope_id"],
            "recording_id": (
                (stored.get("payload") or {}).get("recording_id")
                or (stored["scope_id"] if stored["scope_type"] == "recording" else None)
            ),
            "status": stored["status"],
            "current_step": stored["current_step"],
            "progress": stored["progress"],
            "progress_detail": stored.get("progress_detail"),
            "error": stored["error"],
            "result": stored["result"],
            "created_at": stored["created_at"],
            "updated_at": stored["updated_at"],
            "started_at": stored["started_at"],
            "completed_at": stored["completed_at"],
            "cancel_requested": stored["cancel_requested"],
        }

    def _event_public(self, event: dict[str, Any]) -> dict[str, Any]:
        job = self.get(event["job_id"]) or {}
        return {
            **job,
            "event_id": event["id"],
            "sequence": event["sequence"],
            "status": event["status"],
            "current_step": event["current_step"],
            "progress": event["progress"],
            "message": event["message"],
            "event_payload": event["payload"],
            "event_created_at": event["created_at"],
        }
