from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

from local_asr_server.asr_provider import VAD_GUIDED_DEFAULT, VAD_POST_FILTER_DEFAULT

ANALYSIS_SETTING_OVERRIDE_FIELDS = (
    "llm_provider",
    "gemini_model",
    "local_llm_mode",
    "local_llm_url",
    "local_llm_model",
    "local_llm_quality_preset",
    "local_llm_temperature",
    "local_llm_reasoning",
    "local_llm_max_output_tokens",
    "local_llm_json_mode",
    "local_llm_model_path",
    "local_llm_backend",
    "local_llm_mmproj_path",
    "local_llm_ctx_size",
    "local_llm_startup_timeout",
    "local_llm_llama_server_bin",
)
ANALYSIS_LLM_REQUEST_FIELDS = ("gemini_api_key", *ANALYSIS_SETTING_OVERRIDE_FIELDS)

class AnalysisRequest(BaseModel):
    transcription_id: Optional[str] = None
    recording_id: Optional[str] = None
    text: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    llm_provider: Optional[str] = None
    local_llm_mode: Optional[str] = None
    local_llm_url: Optional[str] = None
    local_llm_model: Optional[str] = None
    local_llm_quality_preset: Optional[str] = None
    local_llm_temperature: Optional[float] = None
    local_llm_reasoning: Optional[str] = None
    local_llm_max_output_tokens: Optional[int] = None
    local_llm_json_mode: Optional[bool] = None
    local_llm_model_path: Optional[str] = None
    local_llm_backend: Optional[str] = None
    local_llm_mmproj_path: Optional[str] = None
    local_llm_ctx_size: Optional[int] = None
    local_llm_startup_timeout: Optional[int] = None
    local_llm_llama_server_bin: Optional[str] = None
    audio_task: Optional[str] = "analysis"
    question: Optional[str] = None
    prompt: Optional[str] = None
    analysis_type: Optional[str] = None
    template_id: Optional[str] = None
    template_version: Optional[str] = None
    pipeline_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    source_ids: Optional[list[str]] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class AnalysisPipelineRequest(BaseModel):
    transcription_id: Optional[str] = None
    recording_id: Optional[str] = None
    text: Optional[str] = None
    llm_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    local_llm_mode: Optional[str] = None
    local_llm_url: Optional[str] = None
    local_llm_model: Optional[str] = None
    local_llm_quality_preset: Optional[str] = None
    local_llm_temperature: Optional[float] = None
    local_llm_reasoning: Optional[str] = None
    local_llm_max_output_tokens: Optional[int] = None
    local_llm_json_mode: Optional[bool] = None
    local_llm_model_path: Optional[str] = None
    local_llm_backend: Optional[str] = None
    local_llm_mmproj_path: Optional[str] = None
    local_llm_ctx_size: Optional[int] = None
    local_llm_startup_timeout: Optional[int] = None
    local_llm_llama_server_bin: Optional[str] = None
    pipeline_id: Optional[str] = None
    analysis_types: Optional[list[str]] = None
    source_ids: Optional[list[str]] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class StructuredNoteEditRequest(BaseModel):
    base_generated_hash: str
    fields: dict[str, Optional[str]]


class TranscribePathRequest(BaseModel):
    file: str
    model: Optional[str] = None
    language: Optional[str] = "it"
    task: str = "transcribe"
    response_format: str = "json"
    word_timestamps: bool = False
    initial_prompt: Optional[str] = None
    temperature: Optional[float] = None
    condition_on_previous_text: bool = False
    verbose: Optional[bool] = None
    vad_guided: bool = VAD_GUIDED_DEFAULT
    vad_post_filter: bool = VAD_POST_FILTER_DEFAULT
    asr_provider: Optional[str] = None
    speechmatics_region: Optional[str] = None
    speechmatics_model: Optional[str] = None
    speechmatics_diarization: Optional[str] = None
    diarization_provider: Optional[str] = None

class CreateRecordingRequest(BaseModel):
    title: Optional[str] = None
    project_name: Optional[str] = ""
    mime_type: str = "audio/webm;codecs=opus"
    model: Optional[str] = None
    language: Optional[str] = "it"
    capture_mode: Optional[str] = "legacy_mixed"
    capture_backend: Optional[str] = "browser"

class UpdateRecordingRequest(BaseModel):
    title: Optional[str] = None
    project_name: Optional[str] = None

class SettingsRequest(BaseModel):
    # All fields are optional to support partial updates (e.g. only updating
    # the LLM provider without touching directory settings).
    transcriptions_dir: Optional[str] = None
    recordings_dir: Optional[str] = None
    asr_provider: Optional[str] = None
    speechmatics_api_key: Optional[str] = None
    speechmatics_region: Optional[str] = None
    speechmatics_model: Optional[str] = None
    speechmatics_diarization: Optional[str] = None
    speechmatics_timeout_seconds: Optional[int] = None
    speechmatics_poll_interval_seconds: Optional[int] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    llm_provider: Optional[str] = None
    local_llm_mode: Optional[str] = None
    local_llm_url: Optional[str] = None
    default_model: Optional[str] = None
    default_language: Optional[str] = None
    default_task: Optional[str] = None
    default_temperature: Optional[float] = None
    default_word_timestamps: Optional[bool] = None
    default_condition_on_previous: Optional[bool] = None
    local_llm_model: Optional[str] = None
    local_llm_quality_preset: Optional[str] = None
    local_llm_temperature: Optional[float] = None
    local_llm_reasoning: Optional[str] = None
    local_llm_max_output_tokens: Optional[int] = None
    local_llm_json_mode: Optional[bool] = None
    local_llm_model_path: Optional[str] = None
    local_llm_model_paths: Optional[dict[str, str]] = None
    local_llm_backend: Optional[str] = None
    local_llm_mmproj_path: Optional[str] = None
    local_llm_ctx_size: Optional[int] = None
    local_llm_startup_timeout: Optional[int] = None
    local_llm_llama_server_bin: Optional[str] = None
    meeting_auto_analysis: Optional[bool] = None
    meeting_default_pipeline: Optional[str] = None
    speaker_diarization_enabled: Optional[bool] = None
    speaker_diarization_minimum_overlap: Optional[float] = None
    visual_intelligence_enabled: Optional[bool] = None
    visual_llm_model: Optional[str] = None
    visual_routing_mode: Optional[str] = None
    visual_frame_similarity_threshold: Optional[int] = None
    visual_minimum_observations: Optional[int] = None
    visual_minimum_margin: Optional[float] = None
    visual_minimum_distinct_turns: Optional[int] = None
    visual_minimum_temporal_support_seconds: Optional[float] = None

class MergeTranscriptionsRequest(BaseModel):
    transcription_ids: list[str]
    title: Optional[str] = None

class TranscribeRecordingRequest(BaseModel):
    model: Optional[str] = None
    language: Optional[str] = "it"
    task: str = "transcribe"
    response_format: str = "verbose_json"
    word_timestamps: bool = False
    initial_prompt: Optional[str] = None
    temperature: Optional[float] = None
    condition_on_previous_text: bool = False
    verbose: Optional[bool] = None
    vad_guided: bool = VAD_GUIDED_DEFAULT
    vad_post_filter: bool = VAD_POST_FILTER_DEFAULT
    asr_provider: Optional[str] = None
    speechmatics_region: Optional[str] = None
    speechmatics_model: Optional[str] = None
    speechmatics_diarization: Optional[str] = None
    diarization_provider: Optional[str] = None
    visual_intelligence_enabled: Optional[bool] = None

class OverlayRequest(BaseModel):
    show: bool

class OverlayResizeRequest(BaseModel):
    width: int
    height: int


class CaptureStartRequest(BaseModel):
    mode: str = "both"
    visual_window_id: Optional[int] = None
    visual_fps: float = 0.5


class CaptureEnsurePermissionsRequest(BaseModel):
    mode: str = "both"

class TranscriptionJobRequest(TranscribeRecordingRequest):
    pass


class DiarizationJobRequest(BaseModel):
    provider: str = "local"
    speechmatics_region: Optional[str] = None
    speechmatics_model: Optional[str] = None


class MockDataRequest(BaseModel):
    lang: str = "it"
