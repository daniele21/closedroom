export interface VisualRoutingCandidate {
  schema_version: number;
  sequence: number;
  timestamp: number;
  task: 'meeting_ui' | 'meeting_state' | 'shared_content';
  trigger: string;
  selector_version: number;
  roi?: number[] | null;
  roi_source?: string | null;
  roi_confidence?: number | null;
  roi_fallback?: boolean;
  independent_inference: boolean;
}

export interface VisualTranscriptLink {
  link_id: string;
  target_id: string;
  target_type: 'meeting_state_event' | 'share_keyframe';
  timestamp: number;
  observation_id?: string | null;
  derivation: 'timestamp_overlap';
  transcript_evidence: Array<{ segment_id: string; start: number; end: number }>;
}

export interface VisualMeetingStateEvent {
  timestamp: number;
  type: string;
  observation_id?: string | null;
  layout?: string;
  previous_layout?: string;
  screen_share_active?: boolean;
  screen_share_presenter?: string | null;
  visible_participant_count?: number | null;
  participant_delta?: number;
  visible_activity?: string[];
}

export interface VisualShareKeyframe {
  timestamp: number;
  content_type: string;
  title?: string | null;
  visible_text: string[];
  key_information: unknown[];
  observation_id?: string | null;
}

export interface VisualShareSession {
  id: string;
  start: number;
  end: number;
  boundary_source: 'meeting_state' | 'shared_content_fallback';
  keyframes: VisualShareKeyframe[];
}

export interface VisualManualScreenshotGroup {
  group_id: string;
  screenshot_ids: string[];
  representative_screenshot_id: string;
  start: number;
  end: number;
  display_id?: number | null;
}

export interface VisualIntelligenceDocumentV2 {
  schema_version: 2;
  generation_id?: string;
  observations: Array<Record<string, unknown>>;
  manual_screenshot_groups?: VisualManualScreenshotGroup[];
  speaker_intervals: Array<Record<string, unknown>>;
  meeting_state_events: VisualMeetingStateEvent[];
  share_sessions: VisualShareSession[];
  unassigned_share_keyframes: VisualShareKeyframe[];
  semantic_links: VisualTranscriptLink[];
  routing_summary: Record<string, unknown>;
  model: string;
  prompt_version: number;
}

export interface VisualRoutingArtifact {
  schema_version: number;
  generation_id?: string;
  routing_mode: 'shadow' | 'v2';
  selector_version: number;
  captured_frames: number;
  candidate_count: number;
  candidates_by_task: Record<string, number>;
  candidates_by_trigger: Record<string, number>;
  rejected_task_evaluations: number;
  candidates: VisualRoutingCandidate[];
}

export interface VisualIntelligenceResponse {
  summary: Record<string, unknown>;
  observations: Array<Record<string, unknown>>;
  document?: Record<string, unknown>;
  routing?: VisualRoutingArtifact;
}

export interface VisualSourceValidity {
  status: 'current' | 'stale';
  manual_screenshot_count: number;
  missing_screenshot_ids: string[];
  unavailable_screenshot_ids: string[];
  changed_screenshot_ids: string[];
}

export interface VisualIntelligenceResponseV2 {
  schema_version: 2;
  summary: Record<string, unknown>;
  document: VisualIntelligenceDocumentV2;
  routing?: VisualRoutingArtifact;
  source_validity?: VisualSourceValidity;
}
