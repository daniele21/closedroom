export interface HealthResponse {
  ok: boolean;
  server: string;
  backend: string;
  default_model: string;
  status: 'recording' | 'transcribing' | 'idle';
  endpoints: string[];
  recordings: boolean;
}

export type RecordingStatus =
  | 'recording'
  | 'finalizing'
  | 'recorded'
  | 'interrupted'
  | 'recoverable'
  | 'transcribing'
  | 'completed'
  | 'failed';

export interface Recording {
  id: string;
  title: string;
  project_name: string;
  archived_at?: string | null;
  status: RecordingStatus;
  error?: string | null;
  partial?: boolean;
  capture_backend?: 'browser' | 'native';
  capture_status?: string;
  quality_report?: any;
  warnings?: string[];
  mime_type: string;
  audio_file: string;
  capture_mode?: 'both' | 'mic_only' | 'pc_only' | 'legacy_mixed';
  primary_track_id?: string;
  audio_tracks?: RecordingTrack[];
  bytes_written: number;
  created_at: string;
  stopped_at?: string;
  duration_seconds?: number;
  duration?: number;
  metadata?: {
    duration_seconds?: number;
    duration?: number;
  };
}

export interface RecordingTrack {
  id: string;
  source: 'mixed' | 'mic' | 'system';
  label: string;
  mime_type: string;
  audio_file?: string | null;
  bytes_written: number;
  chunk_count: number;
  chunks?: RecordingChunk[];
  primary: boolean;
}

export interface RecordingChunk {
  sequence: number;
  sha256: string;
  size: number;
  received_at: string;
  client_started_at_ms?: number | null;
  client_chunk_start_ms?: number | null;
  client_chunk_end_ms?: number | null;
}

export interface ExpectedSequence {
  recording_id: string;
  track_id: string;
  status: RecordingStatus;
  expected_sequence: number;
  last_committed_sequence: number;
  bytes_written: number;
  part_file_exists: boolean;
  audio_file_exists: boolean;
}

export interface CapturePermissions {
  ok: boolean;
  microphone: 'authorized' | 'denied' | 'restricted' | 'notDetermined' | 'unknown';
  screen_capture: 'granted' | 'required';
  modes: {
    mic_only: { ok: boolean };
    pc_only: { ok: boolean };
    both: { ok: boolean };
  };
}

export type CaptureMode = 'both' | 'mic_only' | 'pc_only';

export interface CaptureEnsurePermissionsResult {
  ok: boolean;
  requested: boolean;
  permissions: CapturePermissions;
  diagnostics: CaptureDiagnostics;
  request_result?: any;
}

export interface CaptureCapabilities {
  default_backend: 'native' | 'browser';
  native: {
    available: boolean;
    backend: 'native';
    reason?: string;
    error?: string;
    modes?: Array<'both' | 'mic_only' | 'pc_only'>;
    minimum_macos?: string;
  };
  fallbacks: string[];
}

export interface CaptureWindow {
  id: number;
  title: string;
  application_name: string;
  bundle_identifier: string;
}

export interface CaptureDiagnostics {
  process_name?: string;
  executable_path?: string;
  bundle_identifier?: string;
  bundle_path?: string;
  screen_capture?: 'granted' | 'required' | string;
  microphone?: 'authorized' | 'denied' | 'restricted' | 'notDetermined' | 'unknown' | string;
  code_signature?: 'signed' | 'unsigned' | string;
  team_id?: string;
  identifier?: string;
  macos_version?: string;
}

export interface TranscriptionJob {
  id: string;
  type?: string;
  scope_type?: string | null;
  scope_id?: string | null;
  recording_id?: string | null;
  status: string;
  current_step: string;
  progress: number;
  progress_detail?: VisualProcessingProgress | ASRTrackProgress | Record<string, unknown> | null;
  error?: string | null;
  result?: any;
  created_at: number;
  updated_at: number;
}

export interface VisualProcessingProgress {
  schema_version: number;
  kind: 'visual_processing_progress';
  phase: string;
  unit: 'frames' | 'candidates';
  routing_mode: string;
  processed: number;
  total: number;
  remaining: number;
  captured_frames: number;
  selected_candidates: number;
  rejected_candidates: number;
  inferred: number;
  reused: number;
  skipped: number;
  failed: number;
  elapsed_seconds: number;
  eta_seconds?: number | null;
  sequence?: number | null;
  task?: string | null;
  trigger?: string | null;
  decision?: string | null;
}

export interface ASRTrackProgress {
  schema_version: number;
  kind: 'asr_track_progress';
  phase: string;
  track_id?: string | null;
  track_label?: string | null;
  track_index: number;
  track_count: number;
  processed_audio_seconds: number;
  audio_duration_seconds?: number | null;
  track_percent: number;
  elapsed_seconds: number;
  eta_seconds?: number | null;
}

export interface AnalysisJobCreated {
  job_id: string;
  analysis_run_id: string;
  status: string;
}

export interface AnalysisPipelineCreated {
  pipeline_run_id: string;
  pipeline_id: string;
  status: string;
  jobs: AnalysisJobCreated[];
}

export interface AnalysisTemplate {
  id: string;
  analysis_type: string;
  label: string;
  description: string;
  version: string;
}

export interface AnalysisPipeline {
  id: string;
  label: string;
  description: string;
  template_ids: string[];
}

export interface AnalysisRun {
  id: string;
  job_id?: string | null;
  scope_type: string;
  scope_id: string;
  transcription_id?: string | null;
  recording_id?: string | null;
  analysis_type: string;
  template_id?: string | null;
  template_version?: string | null;
  pipeline_run_id?: string | null;
  provider: string;
  model?: string | null;
  temperature?: number | null;
  reasoning: string;
  effective_reasoning?: boolean | null;
  show_thinking: boolean;
  max_output_tokens?: number | null;
  json_mode: boolean;
  llm_options: Record<string, unknown>;
  prompt_version: string;
  input_hash: string;
  status: string;
  result?: any;
  result_markdown?: string | null;
  source_ids?: string[];
  period_start?: string | null;
  period_end?: string | null;
  error?: string | null;
  created_at: number;
  completed_at?: number | null;
}

export interface Meeting {
  id: string;
  recording: Recording;
  transcription?: Transcription | null;
  analysis_runs: AnalysisRun[];
  latest_analysis: Record<string, AnalysisRun>;
  jobs: TranscriptionJob[];
  status: 'recording' | 'recorded' | 'transcribed' | 'analyzing' | 'ready' | string;
  project_name: string;
  created_at: string;
  updated_at?: string;
}

export interface RuntimeService {
  name: string;
  status: string;
  mode?: 'auto' | 'external' | 'disabled';
  model?: string;
  managed?: boolean;
  host?: string | null;
  port?: number | null;
  url?: string | null;
  pid?: number | null;
  log_file?: string;
  model_path_configured?: boolean;
  error?: string | null;
}

export interface RuntimeStatus {
  services: Record<string, RuntimeService>;
}

export interface ProjectItem {
  recording: Recording;
  transcription: any;
  analysis: any;
  analysis_runs?: AnalysisRun[];
}

export interface Project {
  name: string;
  is_unassigned: boolean;
  items: ProjectItem[];
}

export interface TranscriptionSourceData {
  recordings: Recording[];
  recordings_count: number;
  projects: Project[];
  settings: Partial<Settings>;
}

export interface TranscriptionSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  track_id?: string;
  source?: 'mixed' | 'mic' | 'system';
  channel?: 'mixed' | 'mic' | 'system' | string;
  speaker_label?: string;
  speaker_name?: string;
  provider_speaker?: string;
  pause_before?: number;
  speech_rate_wpm?: number;
  energy?: 'low' | 'medium_low' | 'medium' | 'high' | string | null;
  overlap?: boolean;
  words?: Array<{ word: string; start: number; end: number }>;
}

export interface AudioIntelligenceEvent {
  start: number;
  end?: number;
  duration?: number;
  channels?: string[];
}

export interface AudioIntelligence {
  version: number;
  backend: string;
  mode: string;
  mock?: boolean;
  channels: Record<string, {
    track_id: string;
    label: string;
    available: boolean;
    error?: string | null;
    duration_seconds?: number;
    speech_threshold?: number;
  }>;
  speech_windows?: Array<AudioIntelligenceEvent & { channel: string; speech: boolean; pause_before?: number | null }>;
  conversation_metrics?: {
    duration_seconds?: number;
    speaking_time_seconds?: Record<string, number>;
    speaking_time_pct?: Record<string, number>;
    speech_rate_wpm?: Record<string, number>;
    long_pauses?: AudioIntelligenceEvent[];
    overlaps?: AudioIntelligenceEvent[];
    high_energy_moments?: AudioIntelligenceEvent[];
  };
  insight_candidates?: Array<{
    type: string;
    title?: string;
    start?: number;
    confidence?: string;
    evidence?: string[];
    mock?: boolean;
  }>;
  segments?: TranscriptionSegment[];
}

export interface RecordingVisualFrame {
  sequence: number;
  timestamp: number;
  url: string;
}

export interface CaptureDisplay {
  display_id: number;
  source_id: number;
  title: string;
  width: number;
  height: number;
  is_main?: boolean;
}

export interface RecordingScreenshot {
  screenshot_id: string;
  recording_id: string;
  request_id: string;
  sequence: number;
  capture_kind: 'manual' | 'automatic' | string;
  timestamp: number;
  captured_wall_time?: number | null;
  display_id: number;
  display_title?: string | null;
  width: number;
  height: number;
  thumbnail_width?: number;
  thumbnail_height?: number;
  sha256: string;
  available: boolean;
  thumbnail_available: boolean;
  original_url: string;
  thumbnail_url: string;
}

export interface RecordingNote {
  note_id: string;
  recording_id: string;
  request_id: string;
  sequence: number;
  timestamp: number;
  created_at?: string | null;
  updated_at?: string | null;
  text: string;
  revision: number;
  source_kind: 'user_note';
}

export interface MergedSource {
  id: string;
  audio_filename: string;
  recording_id?: string;
}

/* Visual-intelligence contracts live in their domain module. */
export type {
  VisualRoutingCandidate, VisualTranscriptLink, VisualMeetingStateEvent,
  VisualShareKeyframe, VisualShareSession, VisualIntelligenceDocumentV2,
  VisualIntelligenceResponse, VisualIntelligenceResponseV2,
} from './visualIntelligence';
import type { VisualIntelligenceResponse, VisualIntelligenceResponseV2 } from './visualIntelligence';


export interface Transcription {
  id: string;
  timestamp: string;
  model: string;
  language: string;
  audio_filename: string;
  text: string;
  segments?: TranscriptionSegment[];
  stats?: {
    outcome_status?: 'completed' | 'completed_with_warnings' | string;
    diagnostics?: EnrichmentDiagnostic[];
    time_total_seconds?: number;
    asr_provider?: string;
    backend?: string;
    model?: string;
    provider_options?: Record<string, unknown>;
    speaker_diarization?: {
      status: string;
      engine?: string;
      provider?: string;
      assigned_segments?: number;
      assigned_segments_by_track?: Record<string, number>;
      cluster_count?: number;
      clusters_by_track?: Record<string, string[]>;
      assigned_cluster_count?: number;
      unassigned_clusters_by_track?: Record<string, string[]>;
      text_preserved?: boolean;
      rerun?: boolean;
      error?: string;
    };
    visual_intelligence?: {
      version?: number;
      status: string;
      model?: string;
      routing_mode?: 'v1' | 'shadow' | 'v2';
      requested_routing_mode?: 'v1' | 'shadow' | 'v2';
      observation_count?: number;
      independent_observation_count?: number;
      parse_errors?: number;
      routing_summary?: {
        captured_frames?: number;
        candidate_count?: number;
        candidates_by_task?: Record<string, number>;
        candidates_by_trigger?: Record<string, number>;
      };
      error?: string;
    };
    speaker_attribution?: {
      source?: string;
      mappings?: Array<{
        speaker_cluster: string;
        display_name?: string | null;
        status: string;
        source?: string;
        observation_count?: number;
        distinct_turn_count?: number;
        temporal_support_seconds?: number;
        margin?: number;
        transcript_segment_count?: number;
      }>;
    };
    [key: string]: unknown;
  };
  analysis?: any;
  saved_id?: string;
  recording_id?: string;
  merged_sources?: MergedSource[];
  source_tracks?: RecordingTrack[];
  asr_provider?: 'local' | 'speechmatics' | string;
  backend?: string;
  provider_options?: Record<string, unknown>;
}

export interface EnrichmentDiagnostic {
  component: string;
  status: 'completed' | 'completed_with_warnings' | 'degraded' | 'failed' | 'disabled' | 'skipped' | string;
  requested_backend?: string | null;
  actual_backend?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  error?: string | null;
  counts?: Record<string, number>;
  duration_seconds?: number | null;
  details?: Record<string, unknown>;
}

export interface MeetingDiagnostics {
  recording_id: string;
  outcome_status: string;
  diagnostics: EnrichmentDiagnostic[];
  jobs: TranscriptionJob[];
  events: Array<Record<string, unknown>>;
  artifacts: Record<string, boolean>;
  log_file?: string | null;
  log_lines: string[];
}

export interface AccessibilityStatus {
  available: boolean;
  trusted: boolean;
  required_for: string[];
  reason?: string | null;
  error?: string | null;
}

export interface MenuBarStatus {
  available: boolean;
  visible: boolean;
  icon_loaded: boolean;
  state: 'idle' | 'recording' | 'transcribing' | 'error' | 'unavailable' | string;
  icon_asset: string;
  repair_count: number;
  last_error?: string | null;
}

export interface Settings {
  transcriptions_dir: string;
  recordings_dir: string;
  asr_provider?: 'local' | 'speechmatics' | string;
  speechmatics_api_key?: string;
  speechmatics_api_key_configured?: boolean;
  speechmatics_region?: string;
  speechmatics_model?: string;
  speechmatics_diarization?: string;
  speechmatics_timeout_seconds?: number | null;
  speechmatics_poll_interval_seconds?: number | null;
  gemini_api_key?: string;
  gemini_api_key_configured?: boolean;
  gemini_model?: string;
  llm_provider: string;
  local_llm_mode?: 'auto' | 'external' | 'disabled';
  local_llm_url?: string;
  local_llm_model?: string;
  local_llm_quality_preset?: 'precise' | 'balanced' | 'creative';
  local_llm_temperature?: number | null;
  local_llm_reasoning?: 'auto' | 'on' | 'off';
  local_llm_max_output_tokens?: number | null;
  local_llm_json_mode?: boolean;
  local_llm_model_path?: string;
  /** Mappa model-key → percorso assoluto al file .gguf locale */
  local_llm_model_paths?: Record<string, string>;
  local_llm_backend?: string;
  local_llm_mmproj_path?: string;
  local_llm_ctx_size?: number | null;
  local_llm_startup_timeout?: number | null;
  local_llm_llama_server_bin?: string;
  meeting_auto_analysis?: boolean;
  meeting_default_pipeline?: string;
  speaker_diarization_enabled?: boolean;
  speaker_diarization_minimum_overlap?: number;
  visual_intelligence_enabled?: boolean;
  visual_llm_model?: string;
  visual_routing_mode?: 'v1' | 'shadow' | 'v2';
  visual_frame_similarity_threshold?: number;
  visual_minimum_observations?: number;
  visual_minimum_margin?: number;
  visual_minimum_distinct_turns?: number;
  visual_minimum_temporal_support_seconds?: number;
  default_model: string;
  default_language: string;
  default_task: string;
  default_temperature?: number | null;
  default_word_timestamps: boolean;
  default_condition_on_previous: boolean;
}

export interface AnalysisSetupPayload {
  gemini_api_key?: string;
  gemini_model?: string;
  llm_provider?: string;
  local_llm_mode?: 'auto' | 'external' | 'disabled' | string;
  local_llm_url?: string;
  local_llm_model?: string;
  local_llm_quality_preset?: 'precise' | 'balanced' | 'creative' | string;
  local_llm_temperature?: number | null;
  local_llm_reasoning?: 'auto' | 'on' | 'off' | string;
  local_llm_max_output_tokens?: number | null;
  local_llm_json_mode?: boolean;
  local_llm_model_path?: string;
  local_llm_backend?: string;
  local_llm_mmproj_path?: string;
  local_llm_ctx_size?: number | null;
  local_llm_startup_timeout?: number | null;
  local_llm_llama_server_bin?: string;
}

let sessionPromise: Promise<void> | null = null;

function isPublicRequest(url: string): boolean {
  return url === '/health' || url === '/v1/session';
}

async function sha256Blob(file: Blob): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null;
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function ensureSession(): Promise<void> {
  if (!sessionPromise) {
    sessionPromise = fetch('/v1/session', { credentials: 'same-origin' }).then((response) => {
      if (!response.ok) {
        throw new Error(`Session bootstrap failed: HTTP ${response.status}`);
      }
    });
  }
  return sessionPromise;
}

async function request(url: string, options: RequestInit = {}, retrying = false): Promise<Response> {
  if (!isPublicRequest(url)) {
    await ensureSession();
  }
  const response = await fetch(url, { ...options, credentials: options.credentials ?? 'same-origin' });
  if (response.ok) return response;
  if (response.status === 401 && !isPublicRequest(url) && !retrying) {
    sessionPromise = null;
    await ensureSession();
    return request(url, options, true);
  }

  let detail = `HTTP ${response.status}`;
  const bodyText = await response.text();
  if (bodyText) {
    try {
      const payload = JSON.parse(bodyText);
      detail = payload.detail || detail;
    } catch {
      detail = bodyText;
    }
  }
  throw new Error(detail);
}

export const ApiClient = {
  async health(): Promise<HealthResponse> {
    return (await request('/health')).json();
  },

  async captureCapabilities(): Promise<CaptureCapabilities> {
    return (await request('/v1/capture/capabilities')).json();
  },

  async accessibilityStatus(): Promise<AccessibilityStatus> {
    return (await request('/v1/system/accessibility')).json();
  },

  async menuBarStatus(): Promise<MenuBarStatus> {
    return (await request('/v1/system/menubar')).json();
  },

  async refreshMenuBar(): Promise<MenuBarStatus> {
    return (await request('/v1/system/menubar/refresh', { method: 'POST' })).json();
  },

  async captureWindows(): Promise<{ windows: CaptureWindow[] }> {
    return (await request('/v1/capture/windows')).json();
  },

  async capturePermissions(): Promise<CapturePermissions> {
    return (await request('/v1/capture/permissions')).json();
  },

  async requestCapturePermissions(): Promise<any> {
    return (await request('/v1/capture/request-permissions', { method: 'POST' })).json();
  },

  async ensureCapturePermissions(mode: CaptureMode): Promise<CaptureEnsurePermissionsResult> {
    return (await request('/v1/capture/ensure-permissions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })).json();
  },

  async listRecordings(): Promise<{ items: Recording[] }> {
    return (await request('/v1/recordings')).json();
  },

  async getRecording(recordingId: string): Promise<Recording> {
    return (await request(`/v1/recordings/${recordingId}`)).json();
  },

  async listProjects(): Promise<{ items: Project[] }> {
    return (await request('/v1/projects')).json();
  },

  async recordingAudio(recordingId: string): Promise<Blob> {
    return (await request(`/v1/recordings/${recordingId}/audio`)).blob();
  },

  async recordingProject(recordingId: string): Promise<ProjectItem> {
    return (await request(`/v1/recordings/${recordingId}/project`)).json();
  },

  async recordingIntelligence(recordingId: string): Promise<AudioIntelligence> {
    return (await request(`/v1/recordings/${recordingId}/intelligence`)).json();
  },

  async transcriptionSourceData(limit = 100): Promise<TranscriptionSourceData> {
    return (await request(`/v1/transcription/source-data?limit=${limit}`)).json();
  },

  async asrProviders(): Promise<any> {
    return (await request('/v1/asr/providers')).json();
  },

  transcribe(formData: FormData, signal?: AbortSignal): Promise<Response> {
    return request('/v1/audio/transcriptions', { method: 'POST', body: formData, signal });
  },

  async createRecording(payload: { title?: string; project_name?: string; mime_type?: string; model?: string; language?: string; capture_mode?: 'both' | 'mic_only' | 'pc_only' | 'legacy_mixed'; capture_backend?: 'browser' | 'native' }): Promise<Recording> {
    return (await request('/v1/recordings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })).json();
  },

  async stopRecording(recordingId: string): Promise<Recording> {
    return (await request(`/v1/recordings/${recordingId}/stop`, { method: 'POST' })).json();
  },

  async startNativeCapture(recordingId: string, mode: 'both' | 'mic_only' | 'pc_only', visualWindowId?: number, visualFps = 0.5): Promise<any> {
    return (await request(`/v1/recordings/${recordingId}/capture/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, visual_window_id: visualWindowId, visual_fps: visualFps }),
    })).json();
  },

  async stopNativeCapture(recordingId: string): Promise<{ capture: any; recording: Recording }> {
    return (await request(`/v1/recordings/${recordingId}/capture/stop`, { method: 'POST' })).json();
  },

  async cancelNativeCapture(recordingId: string): Promise<any> {
    return (await request(`/v1/recordings/${recordingId}/capture/cancel`, { method: 'POST' })).json();
  },

  async recoverRecording(recordingId: string): Promise<Recording> {
    return (await request(`/v1/recordings/${recordingId}/recover`, { method: 'POST' })).json();
  },

  async discardRecording(recordingId: string): Promise<void> {
    await request(`/v1/recordings/${recordingId}/discard`, { method: 'POST' });
  },

  async appendRecordingChunk(recordingId: string, sequence: number, file: Blob): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('sequence', String(sequence));
    formData.append('size', String(file.size));
    const sha256 = await sha256Blob(file);
    if (sha256) formData.append('sha256', sha256);
    return (await request(`/v1/recordings/${recordingId}/chunks`, {
      method: 'POST',
      body: formData
    })).json();
  },

  async appendVisualFrame(recordingId: string, sequence: number, timestamp: number, file: Blob): Promise<any> {
    const formData = new FormData();
    formData.append('file', file, `frame-${sequence}.jpg`);
    formData.append('sequence', String(sequence));
    formData.append('timestamp', String(timestamp));
    return (await request(`/v1/recordings/${recordingId}/visual-frames`, {
      method: 'POST', body: formData,
    })).json();
  },

  async visualIntelligence(recordingId: string): Promise<VisualIntelligenceResponse> {
    return (await request(`/v1/recordings/${recordingId}/visual-intelligence`)).json();
  },

  async visualIntelligenceV2(recordingId: string, signal?: AbortSignal): Promise<VisualIntelligenceResponseV2> {
    return (await request(`/v2/recordings/${recordingId}/visual-intelligence`, { signal })).json();
  },

  async visualDebug(recordingId: string, page = 1, limit = 50, task?: string, signal?: AbortSignal): Promise<any> {
    const url = `/v2/recordings/${recordingId}/visual-debug?page=${page}&limit=${limit}${task ? `&task=${task}` : ''}`;
    return (await request(url, { signal })).json();
  },

  async appendRecordingTrackChunk(recordingId: string, trackId: string, sequence: number, file: Blob): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('sequence', String(sequence));
    formData.append('size', String(file.size));
    const sha256 = await sha256Blob(file);
    if (sha256) formData.append('sha256', sha256);
    return (await request(`/v1/recordings/${recordingId}/tracks/${trackId}/chunks`, {
      method: 'POST',
      body: formData
    })).json();
  },

  async expectedRecordingTrackSequence(recordingId: string, trackId: string): Promise<ExpectedSequence> {
    return (await request(`/v1/recordings/${recordingId}/tracks/${trackId}/expected-sequence`)).json();
  },

  async recordingTrackAudio(recordingId: string, trackId: string): Promise<Blob> {
    return (await request(`/v1/recordings/${recordingId}/tracks/${trackId}/audio`)).blob();
  },

  transcribeRecording(recordingId: string, payload: {
    model?: string;
    language?: string;
    task?: string;
    response_format?: string;
    word_timestamps?: boolean;
    initial_prompt?: string;
    temperature?: number | null;
    condition_on_previous_text?: boolean;
    vad_guided?: boolean;
    vad_post_filter?: boolean;
    asr_provider?: string;
    speechmatics_region?: string;
    speechmatics_model?: string;
    speechmatics_diarization?: string;
    diarization_provider?: string;
    visual_intelligence_enabled?: boolean;
  }): Promise<Transcription> {
    return request(`/v1/recordings/${recordingId}/transcriptions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then((res) => res.json());
  },

  async createTranscriptionJob(recordingId: string, payload: {
    model?: string;
    language?: string;
    task?: string;
    response_format?: string;
    word_timestamps?: boolean;
    initial_prompt?: string;
    temperature?: number | null;
    condition_on_previous_text?: boolean;
    vad_guided?: boolean;
    vad_post_filter?: boolean;
    asr_provider?: string;
    speechmatics_region?: string;
    speechmatics_model?: string;
    speechmatics_diarization?: string;
    diarization_provider?: string;
    visual_intelligence_enabled?: boolean;
  }): Promise<TranscriptionJob> {
    return (await request(`/v1/recordings/${recordingId}/transcription-jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async createDiarizationJob(transcriptionId: string, payload: {
    provider: 'local' | 'speechmatics' | string;
    speechmatics_region?: string;
    speechmatics_model?: string;
  }): Promise<TranscriptionJob> {
    return (await request(`/v1/transcriptions/${transcriptionId}/diarization-jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async getJob(jobId: string): Promise<TranscriptionJob> {
    return (await request(`/v1/jobs/${jobId}`)).json();
  },

  async cancelJob(jobId: string): Promise<TranscriptionJob> {
    return (await request(`/v1/jobs/${jobId}/cancel`, { method: 'POST' })).json();
  },

  async updateRecording(recordingId: string, payload: { title?: string; project_name?: string }): Promise<Recording> {
    return (await request(`/v1/recordings/${recordingId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async getSettings(): Promise<Settings> {
    return (await request('/v1/settings')).json();
  },

  async getPrompts(): Promise<Record<string, Record<string, string>>> {
    return (await request('/v1/prompts')).json();
  },

  async checkModelCache(modelName: string): Promise<{ model: string; cached: boolean }> {
    return (await request(`/v1/models/check-cache?model=${encodeURIComponent(modelName)}`)).json();
  },

  async updateSettings(settings: Partial<Settings>): Promise<Settings> {
    return (await request('/v1/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    })).json();
  },

  async savePrompts(prompts: Record<string, Record<string, string>>): Promise<{ status: string }> {
    return (await request('/v1/prompts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prompts),
    })).json();
  },

  async stats(): Promise<any> {
    return (await request('/v1/stats')).json();
  },

  async runtimeStatus(): Promise<RuntimeStatus> {
    return (await request('/v1/runtime/status')).json();
  },

  async listRuntimeServices(): Promise<RuntimeStatus> {
    return this.runtimeStatus();
  },

  async getLlmService(): Promise<RuntimeService> {
    return (await request('/v1/runtime/services/llm')).json();
  },

  async startLlmService(): Promise<RuntimeService> {
    return (await request('/v1/runtime/services/llm/start', { method: 'POST' })).json();
  },

  async stopLlmService(): Promise<RuntimeService> {
    return (await request('/v1/runtime/services/llm/stop', { method: 'POST' })).json();
  },

  async restartLlmService(): Promise<RuntimeService> {
    return (await request('/v1/runtime/services/llm/restart', { method: 'POST' })).json();
  },

  async getLlmLogs(tail = 200): Promise<{ service: string; tail: number; text: string }> {
    return (await request(`/v1/runtime/services/llm/logs?tail=${tail}`)).json();
  },

  async analyze(payload: AnalysisSetupPayload & { transcription_id?: string; recording_id?: string; text?: string; audio_task?: string; question?: string }): Promise<any> {
    return (await request('/v1/analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async createAnalysisJob(payload: AnalysisSetupPayload & { transcription_id?: string; recording_id?: string; text?: string; audio_task?: string; question?: string; prompt?: string; analysis_type?: string; template_id?: string; pipeline_id?: string; pipeline_run_id?: string; source_ids?: string[] }): Promise<AnalysisJobCreated> {
    return (await request('/v1/analysis-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async createAnalysisPipeline(payload: AnalysisSetupPayload & { transcription_id?: string; recording_id?: string; text?: string; pipeline_id?: string; analysis_types?: string[] }): Promise<AnalysisPipelineCreated> {
    return (await request('/v1/analysis-pipelines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async listAnalysisTemplates(): Promise<{ items: AnalysisTemplate[] }> {
    return (await request('/v1/analysis/templates')).json();
  },

  async listAnalysisPipelines(): Promise<{ items: AnalysisPipeline[] }> {
    return (await request('/v1/analysis/pipelines')).json();
  },

  async getAnalysisRun(analysisRunId: string): Promise<AnalysisRun> {
    return (await request(`/v1/analysis-runs/${analysisRunId}`)).json();
  },

  async listAnalysisRuns(params: { scope_type?: string; scope_id?: string; transcription_id?: string; recording_id?: string; analysis_type?: string; pipeline_run_id?: string; limit?: number } = {}): Promise<{ items: AnalysisRun[] }> {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
    });
    const query = search.toString();
    return (await request(`/v1/analysis-runs${query ? `?${query}` : ''}`)).json();
  },

  async listMeetings(limit = 50): Promise<{ items: Meeting[] }> {
    return (await request(`/v1/meetings?limit=${limit}`)).json();
  },

  async listArchivedMeetings(page = 1): Promise<{ items: Meeting[]; total: number; has_more: boolean }> {
    return (await request(`/v1/meetings?q=&archived=true&limit=50&page=${page}`)).json();
  },

  async archiveMeeting(recordingId: string): Promise<Recording> {
    return (await request(`/v1/meetings/${encodeURIComponent(recordingId)}/archive`, { method: 'POST' })).json();
  },

  async restoreMeeting(recordingId: string): Promise<Recording> {
    return (await request(`/v1/meetings/${encodeURIComponent(recordingId)}/restore`, { method: 'POST' })).json();
  },

  async getMeeting(recordingId: string): Promise<Meeting> {
    return (await request(`/v1/meetings/${recordingId}`)).json();
  },

  async getMeetingDiagnostics(recordingId: string): Promise<MeetingDiagnostics> {
    return (await request(`/v1/meetings/${recordingId}/diagnostics`)).json();
  },

  async selectDirectory(): Promise<{ path: string | null; error?: string }> {
    return (await request('/v1/system/select-directory', { method: 'POST' })).json();
  },

  async selectFile(): Promise<{ path: string | null; error?: string }> {
    return (await request('/v1/system/select-file', { method: 'POST' })).json();
  },

  async listTranscriptions(page = 1, limit = 10): Promise<{ items: Transcription[]; total: number; page: number; limit: number }> {
    return (await request(`/v1/transcriptions?page=${page}&limit=${limit}`)).json();
  },

  async getTranscription(id: string): Promise<Transcription> {
    return (await request(`/v1/transcriptions/${id}`)).json();
  },

  async deleteTranscription(id: string): Promise<{ ok: boolean }> {
    return (await request(`/v1/transcriptions/${id}`, { method: 'DELETE' })).json();
  },

  async mergeTranscriptions(transcriptionIds: string[], title?: string): Promise<Transcription> {
    return (await request('/v1/transcriptions/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcription_ids: transcriptionIds, title })
    })).json();
  },

  async splitTranscription(id: string): Promise<{ ok: boolean; restored_ids: string[] }> {
    return (await request(`/v1/transcriptions/${id}/split`, { method: 'POST' })).json();
  },

  async recordingVisualFrames(recordingId: string): Promise<{ items: RecordingVisualFrame[]; total: number }> {
    return (await request(`/v1/recordings/${recordingId}/visual-frames`)).json();
  },

  async captureDisplays(): Promise<{ displays: CaptureDisplay[]; reason?: string | null }> {
    return (await request('/v1/capture/displays')).json();
  },

  async recordingScreenshots(recordingId: string): Promise<{ items: RecordingScreenshot[]; total: number }> {
    return (await request(`/v1/recordings/${recordingId}/screenshots`)).json();
  },

  async recordingNotes(recordingId: string): Promise<{ items: RecordingNote[]; total: number }> {
    return (await request(`/v1/recordings/${recordingId}/notes`)).json();
  },

  async recordingNoteAnchor(recordingId: string): Promise<{
    recording_id: string;
    timestamp: number;
    clock_source: 'native_recording_uptime' | 'recording_created_at_fallback' | string;
  }> {
    return (await request(`/v1/recordings/${recordingId}/notes/anchor`, { method: 'POST' })).json();
  },

  async createRecordingNote(
    recordingId: string,
    payload: { request_id: string; timestamp: number; text: string },
  ): Promise<RecordingNote> {
    return (await request(`/v1/recordings/${recordingId}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async updateRecordingNote(
    recordingId: string,
    noteId: string,
    payload: { text: string; revision: number },
  ): Promise<RecordingNote> {
    return (await request(`/v1/recordings/${recordingId}/notes/${noteId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },

  async deleteRecordingNote(recordingId: string, noteId: string): Promise<void> {
    await request(`/v1/recordings/${recordingId}/notes/${noteId}`, { method: 'DELETE' });
  },

  async selectScreenshotDisplay(
    recordingId: string,
    displayId: number,
  ): Promise<{ recording_id: string; display_id: number; display: CaptureDisplay }> {
    return (await request(`/v1/recordings/${recordingId}/screenshot-display`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_id: displayId }),
    })).json();
  },

  async captureScreenshot(recordingId: string, requestId: string, displayId?: number): Promise<RecordingScreenshot> {
    return (await request(`/v1/recordings/${recordingId}/screenshots`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        ...(displayId !== undefined ? { display_id: displayId } : {}),
      }),
    })).json();
  },

  async deleteScreenshot(recordingId: string, screenshotId: string): Promise<void> {
    await request(`/v1/recordings/${recordingId}/screenshots/${screenshotId}`, { method: 'DELETE' });
  },

  async updateTranscriptionSpeakers(id: string, names: Record<string, string>): Promise<Transcription> {
    return (await request(`/v1/transcriptions/${id}/speakers`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ names }),
    })).json();
  },

  async testAudioRoute(): Promise<any> {
    return (await request('/v1/system/audio/activate', { method: 'POST' })).json();
  },

  async testAudioRestore(): Promise<any> {
    return (await request('/v1/system/audio/restore', { method: 'POST' })).json();
  },
  
  async getAudioRouteStatus(): Promise<any> {
    return (await request('/v1/system/audio/status')).json();
  },

  async getActiveRecording(): Promise<{
    active: boolean;
    recording_id?: string;
    title?: string;
    capture_backend?: 'browser' | 'native';
    capture_mode?: 'both' | 'mic_only' | 'pc_only';
    started_at?: number | string;
    bytes_written?: number;
    mic_db?: number;
    system_db?: number;
    warnings?: string[];
    screenshot_count?: number;
    note_count?: number;
    screenshot_display_id?: number | null;
  }> {
    return (await request('/v1/recordings/active')).json();
  },

  async stopRecordingControl(recordingId: string): Promise<any> {
    return (await request(`/v1/recordings/${recordingId}/control/stop`, { method: 'POST' })).json();
  },

  async openMeetingWindow(recordingId: string): Promise<{ success: boolean; error?: string }> {
    return (await request(`/v1/system/window/main/meeting/${recordingId}`, { method: 'POST' })).json();
  },

  async resizeOverlay(width: number, height: number): Promise<{ success: boolean; error?: string }> {
    try {
      return (await request('/v1/system/window/overlay/resize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ width, height })
      })).json();
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  },

  async toggleOverlay(show: boolean): Promise<{
    success: boolean;
    error?: string;
    fallback?: 'browser' | null;
    fallback_expected?: boolean;
  }> {
    try {
      return (await request('/v1/system/window/overlay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ show })
      })).json();
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  },

  async getCaptureDiagnostics(): Promise<CaptureDiagnostics> {
    return (await request('/v1/capture/diagnostics')).json();
  },

  async populateMockData(lang: string = 'it'): Promise<{ success: boolean }> {
    return (await request('/v1/system/mock-data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang })
    })).json();
  },

  async clearMockData(): Promise<{ success: boolean }> {
    return (await request('/v1/system/clear-mock-data', {
      method: 'POST'
    })).json();
  },

  async logClientEvent(level: 'info' | 'warn' | 'error', source: string, message: string, data?: any): Promise<void> {
    try {
      await request('/v1/system/client-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level, source, message, data }),
      });
    } catch {
      // Best-effort client logging
    }
  }
};