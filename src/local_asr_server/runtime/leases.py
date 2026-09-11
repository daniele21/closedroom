from __future__ import annotations

import logging
from threading import Lock
from typing import Any

logger = logging.getLogger("uvicorn.error")


class ModelRuntimeLeaseManager:
    """Coordinates model phase transitions; it is not a workload scheduler.

    Global admission, queue bounds and mutual exclusion belong to
    ``HeavyWorkloadArbiter``. This compatibility hook only records the current
    model phase and asks the runtime service manager to release the LLM/VLM
    sidecar before ASR/diarization phases when appropriate.
    """

    _lock = Lock()
    _active_lease: str | None = None
    _service_manager: Any = None

    @classmethod
    def set_service_manager(cls, manager: Any) -> None:
        cls._service_manager = manager

    @classmethod
    def acquire_lease(cls, lease_type: str) -> None:
        """Activate a model phase hook (asr, diarization, vision, llm)."""
        with cls._lock:
            logger.info("[Model Phase] Activating: %s (current: %s)", lease_type, cls._active_lease)

            if lease_type in ("asr", "diarization"):
                if cls._service_manager:
                    status = cls._service_manager.llm_status()
                    if status.get("status") in ("ready", "running"):
                        logger.info(
                            "[Model Phase] Stopping VLM/LLM sidecar to free unified memory for %s",
                            lease_type,
                        )
                        try:
                            cls._service_manager.stop_llm()
                        except Exception as e:
                            logger.warning("[Model Phase] Failed to stop LLM sidecar: %s", e)

            cls._active_lease = lease_type

    @classmethod
    def release_lease(cls, lease_type: str) -> None:
        """Clear the phase marker when it still belongs to the caller."""
        with cls._lock:
            if cls._active_lease == lease_type:
                logger.info("[Model Phase] Released: %s", lease_type)
                cls._active_lease = None
