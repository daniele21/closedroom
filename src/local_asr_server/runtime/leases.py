from __future__ import annotations

import logging
from threading import Lock
from typing import Any

logger = logging.getLogger("uvicorn.error")


class ModelRuntimeLeaseManager:
    """Coordinate model phase transitions for one app runtime.

    Global admission, queue bounds and mutual exclusion belong to
    HeavyWorkloadArbiter. This app-owned collaborator only records the
    current model phase and asks its owning runtime service manager to release
    the LLM/VLM sidecar before ASR/diarization phases when appropriate.
    """

    def __init__(self, service_manager: Any | None = None) -> None:
        self._lock = Lock()
        self._active_lease: str | None = None
        self._service_manager = service_manager

    @property
    def active_lease(self) -> str | None:
        with self._lock:
            return self._active_lease

    def acquire_lease(self, lease_type: str) -> None:
        """Activate a model phase hook (asr, diarization, vision, llm)."""
        with self._lock:
            logger.info(
                "[Model Phase] Activating: %s (current: %s)",
                lease_type,
                self._active_lease,
            )

            if lease_type in ("asr", "diarization") and self._service_manager:
                status = self._service_manager.llm_status()
                if status.get("status") in ("ready", "running"):
                    logger.info(
                        "[Model Phase] Stopping VLM/LLM sidecar to free unified memory for %s",
                        lease_type,
                    )
                    try:
                        self._service_manager.stop_llm()
                    except Exception as exc:
                        logger.warning(
                            "[Model Phase] Failed to stop LLM sidecar: %s",
                            exc,
                        )

            self._active_lease = lease_type

    def release_lease(self, lease_type: str) -> None:
        """Clear the phase marker when it still belongs to the caller."""
        with self._lock:
            if self._active_lease == lease_type:
                logger.info("[Model Phase] Released: %s", lease_type)
                self._active_lease = None
