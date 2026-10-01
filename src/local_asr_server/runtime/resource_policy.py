from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


class ResourcePolicyBlocked(RuntimeError):
    """Raised when current product resource policy forbids heavy work."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def recording_has_active_capture(recording: Mapping[str, object] | None) -> bool:
    """Distinguish an actual capture from a merely prepared recording.

    ``RecordingStore.active_recording()`` intentionally powers UI/recovery and
    therefore returns a recording as soon as its durable state is ``recording``.
    Resource admission needs the narrower signal: native capture marks
    ``capture_status=recording`` and browser capture proves activity once audio
    chunks arrive. Older persisted metadata without ``capture_status`` remains
    fail-safe and is treated as active while its recording state is active.
    """
    if recording is None:
        return False

    capture_status = recording.get("capture_status")
    if capture_status == "recording":
        return True

    chunk_count = recording.get("chunk_count")
    if isinstance(chunk_count, int) and chunk_count > 0:
        return True

    tracks = recording.get("audio_tracks")
    if isinstance(tracks, list):
        for track in tracks:
            if not isinstance(track, Mapping):
                continue
            track_chunks = track.get("chunk_count")
            if isinstance(track_chunks, int) and track_chunks > 0:
                return True

    if capture_status is None:
        return recording.get("status") == "recording"
    return False


@dataclass(frozen=True, slots=True)
class ResourcePolicySnapshot:
    profile: str
    capture_active: bool

    def public(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "capture_active": self.capture_active,
        }


class ResourcePolicy:
    """Outcome-level admission policy layered above the heavy-work scheduler.

    This class does not own queues, workers, recording state, model residency or
    cancellation. ``RecordingStore`` remains the canonical capture-state owner,
    ``HeavyWorkloadArbiter`` remains the sole ClosedRoom heavy-work scheduler,
    and runtime/service owners remain responsible for model lifecycle. The
    policy only answers whether starting a heavy phase is currently allowed.
    """

    DEFAULT_PROFILE = "balanced"
    VALID_PROFILES = {"efficient", "balanced", "maximum"}

    def __init__(
        self,
        *,
        capture_active: Callable[[], bool],
        profile: str = DEFAULT_PROFILE,
    ) -> None:
        if profile not in self.VALID_PROFILES:
            raise ValueError(f"unsupported resource profile: {profile}")
        self._capture_active = capture_active
        self.profile = profile

    def assert_heavy_work_admissible(self, workload_type: str) -> None:
        if not workload_type.strip():
            raise ValueError("workload_type must be non-empty")
        if self._capture_active():
            raise ResourcePolicyBlocked("capture_active")

    def snapshot(self) -> dict[str, object]:
        return ResourcePolicySnapshot(
            profile=self.profile,
            capture_active=self._capture_active(),
        ).public()
