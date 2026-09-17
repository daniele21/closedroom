from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from local_asr_server.settings import DEFAULT_VISUAL_FRAME_SIMILARITY_THRESHOLD

MAX_VISUAL_FRAME_BYTES = 5 * 1024 * 1024
MAX_VISUAL_VLM_CANDIDATES = 2048
VISUAL_OBSERVATIONS_FILE = "visual_observations.jsonl"
VISUAL_SUMMARY_FILE = "visual_summary.json"
VISUAL_ROUTING_FILE = "visual_routing.json"
VISUAL_DOCUMENT_FILE = "visual_intelligence.json"
VISUAL_PROCESSING_CHECKPOINT = "visual_processing_checkpoint.json"
VISUAL_GENERATION_STAGING_DIR = ".visual-generation-staging"
VISUAL_RECOVERY_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class VisualProcessingProgress:
    """Structured job/UI snapshot for visual filtering and inference progress."""

    phase: str
    unit: str
    routing_mode: str
    processed: int
    total: int
    captured_frames: int
    selected_candidates: int
    rejected_candidates: int
    inferred: int = 0
    reused: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    sequence: int | None = None
    task: str | None = None
    trigger: str | None = None
    decision: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "visual_processing_progress",
            **asdict(self),
            "remaining": max(0, self.total - self.processed),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "eta_seconds": round(self.eta_seconds, 1) if self.eta_seconds is not None else None,
        }


class VisualTask(str, Enum):
    MEETING_UI = "meeting_ui"
    MEETING_STATE = "meeting_state"
    SHARED_CONTENT = "shared_content"


class VisualTrigger(str, Enum):
    FIRST_FRAME = "first_frame"
    DIARIZATION_TURN_START = "diarization_turn_start"
    LOCAL_CHANGE = "local_change"
    STRUCTURAL_CHANGE = "structural_change"
    SHARED_ROI_CHANGE = "shared_roi_change"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True)
class VisualRoutingConfig:
    mode: str = "v1"
    dhash_distance: int = DEFAULT_VISUAL_FRAME_SIMILARITY_THRESHOLD
    max_candidates: int = MAX_VISUAL_VLM_CANDIDATES
    structural_dhash_distance: int = 12
    shared_roi_dhash_distance: int = 10
    speaker_delay_seconds: float = 0.5
    speaker_local_window_seconds: float = 2.5
    speaker_tile_dhash_distance: int = 4
    speaker_tile_color_distance: float = 0.08
    participant_grid_rows: int = 3
    participant_grid_columns: int = 3
    speaker_heartbeat_seconds: float = 10.0
    meeting_state_heartbeat_seconds: float = 30.0
    shared_content_heartbeat_seconds: float = 60.0
    shared_content_stabilization_seconds: float = 0.5
    shared_content_roi: tuple[float, float, float, float] = (0.05, 0.05, 0.95, 0.85)
    shared_content_roi_confidence: float = 0.55
    shared_content_cadence_seconds: tuple[tuple[str, float], ...] = (
        ("slide", 60.0),
        ("document", 90.0),
        ("spreadsheet", 60.0),
        ("code", 90.0),
        ("browser", 60.0),
        ("dashboard", 60.0),
        ("video", 120.0),
        ("unknown", 60.0),
    )


@dataclass(frozen=True)
class VisualTemporalConfig:
    meeting_state_debounce_seconds: float = 2.0


@dataclass(frozen=True)
class FrameCandidate:
    sequence: int
    timestamp: float
    task: VisualTask
    trigger: VisualTrigger
    selector_version: int = 1
    roi: tuple[float, float, float, float] | None = None
    roi_source: str | None = None
    roi_confidence: float | None = None
    roi_fallback: bool = False
    diarization_turn_id: str | None = None
    expected_cluster: str | None = None

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = 1
        payload["task"] = self.task.value
        payload["trigger"] = self.trigger.value
        payload["roi"] = list(self.roi) if self.roi else None
        payload["independent_inference"] = True
        return payload


@dataclass(frozen=True)
class VisualObservation:
    sequence: int
    timestamp: float
    platform: str
    layout: str
    participants: list[str]
    active_speakers: list[str]
    evidence: list[str]
    confidence: float
    model: str
    prompt_version: int
    task: str = VisualTask.MEETING_UI.value
    trigger: str = VisualTrigger.STRUCTURAL_CHANGE.value
    independent_inference: bool = True
    schema_version: int = 1
    diarization_turn_id: str | None = None
    expected_cluster: str | None = None

    def public(self) -> dict[str, Any]:
        return {**asdict(self), "status": "valid"}


@dataclass(frozen=True)
class PipelineRunConfig:
    recording_id: str
    job_id: str
    generation_id: str
    asr_provider: str
    asr_model: str
    diarization_enabled: bool
    diarization_model: str
    visual_enabled: bool
    visual_model: str
    visual_routing_mode: str
    visual_routing_config: dict[str, Any]
    prompt_versions: dict[str, int]
    llm_parameters: dict[str, Any]
    input_fingerprints: dict[str, str]

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    started_at: str
    completed_at: str
    duration_ms: int
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    memory: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)
