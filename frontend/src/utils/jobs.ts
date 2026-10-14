import type { ASRTrackProgress, TranscriptionJob, VisualProcessingProgress } from '../api/apiClient';

export const ACTIVE_JOB_STATUSES = new Set([
  'queued', 'running', 'waiting_for_service', 'retrying', 'cancel_requested', 'cancelling',
  'validating_audio', 'downloading', 'loading_model', 'transcribing', 'transcribing_mic',
  'transcribing_system', 'preparing_diarization', 'diarizing_system', 'diarizing', 'merging',
  'visual_processing', 'audio_intelligence', 'saving', 'saving_diarization',
]);

type Translate = (key: string, replacements?: Record<string, string | number>) => string;

export type TranscriptionFinalizationStepStatus = 'completed' | 'active' | 'pending';

export interface TranscriptionFinalizationStep {
  id: 'visual_processing' | 'audio_intelligence' | 'saving';
  label: string;
  description: string;
  status: TranscriptionFinalizationStepStatus;
}

const LOCALIZED_JOB_STEPS = new Set([
  'queued',
  'validating_audio',
  'transcribing_mic',
  'transcribing_system',
  'preparing_diarization',
  'diarizing_system',
  'diarizing',
  'merging',
  'visual_processing',
  'audio_intelligence',
  'saving',
  'saving_diarization',
  'completed',
  'failed',
  'cancelled',
  'interrupted',
]);

export function localizeJobStep(step: string, translate: Translate): string {
  return LOCALIZED_JOB_STEPS.has(step) ? translate(`jobSteps.${step}`) : step;
}

export function formatJobProgress(job: TranscriptionJob, translate: (key: string) => string): string {
  const step = job.current_step || job.status;
  return `${localizeJobStep(step, translate)} · ${job.progress || 0}%`;
}

const FINALIZATION_STEP_IDS: TranscriptionFinalizationStep['id'][] = [
  'visual_processing',
  'audio_intelligence',
  'saving',
];

export function getTranscriptionActiveStep(currentStep: string, progress: number): number {
  if (currentStep === 'queued' || currentStep === 'validating_audio' || currentStep === 'downloading') return 0;
  if (currentStep === 'transcribing_mic' || currentStep === 'transcribing_system' || currentStep === 'transcribing') {
    return progress < 45 ? 1 : 2;
  }
  if (currentStep === 'diarizing' || currentStep === 'merging') return 3;
  if (FINALIZATION_STEP_IDS.includes(currentStep as TranscriptionFinalizationStep['id'])) return 4;
  return Math.min(4, Math.max(0, Math.floor(progress / 22)));
}

export function getTranscriptionFinalizationSteps(
  currentStep: string,
  translate: Translate,
): TranscriptionFinalizationStep[] {
  const activeIndex = FINALIZATION_STEP_IDS.indexOf(currentStep as TranscriptionFinalizationStep['id']);
  if (activeIndex < 0) return [];

  return FINALIZATION_STEP_IDS.map((id, index) => ({
    id,
    label: translate(`transcription.finalization_${id}Label`),
    description: translate(`transcription.finalization_${id}Desc`),
    status: index < activeIndex ? 'completed' : index === activeIndex ? 'active' : 'pending',
  }));
}

export function isVisualProcessingProgress(
  detail: TranscriptionJob['progress_detail'],
): detail is VisualProcessingProgress {
  return Boolean(detail && detail.kind === 'visual_processing_progress');
}

export function isASRTrackProgress(
  detail: TranscriptionJob['progress_detail'],
): detail is ASRTrackProgress {
  return Boolean(detail && detail.kind === 'asr_track_progress');
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

export function formatASRTrackProgressStatus(detail: ASRTrackProgress, translate: Translate): string {
  return translate('transcription.asrTrackProgress', {
    track: detail.track_label || detail.track_id || detail.track_index,
    current: detail.track_index,
    total: detail.track_count,
    processed: formatDuration(detail.processed_audio_seconds),
    duration: formatDuration(detail.audio_duration_seconds),
    percent: detail.track_percent,
    eta: formatVisualEta(detail.eta_seconds, translate),
  });
}

export function formatASRTrackProgressLog(detail: ASRTrackProgress, translate: Translate): string {
  return translate('transcription.asrTrackLog', {
    track: detail.track_label || detail.track_id || detail.track_index,
    processed: formatDuration(detail.processed_audio_seconds),
    duration: formatDuration(detail.audio_duration_seconds),
    elapsed: formatDuration(detail.elapsed_seconds),
    eta: formatVisualEta(detail.eta_seconds, translate),
  });
}

export function formatVisualEta(seconds: number | null | undefined, translate: Translate): string {
  if (seconds === null || seconds === undefined) return translate('transcription.visualEtaCalculating');
  if (seconds < 1) return translate('transcription.visualEtaLessThanSecond');
  const rounded = Math.ceil(seconds);
  if (rounded < 60) return translate('transcription.visualEtaSeconds', { seconds: rounded });
  return translate('transcription.visualEtaMinutes', {
    minutes: Math.floor(rounded / 60),
    seconds: rounded % 60,
  });
}

export function formatVisualProgressStatus(detail: VisualProcessingProgress, translate: Translate): string {
  const key = detail.unit === 'candidates'
    ? 'transcription.visualProgressCandidates'
    : 'transcription.visualProgressFrames';
  return translate(key, {
    processed: detail.processed,
    total: detail.total,
    remaining: detail.remaining,
    eta: formatVisualEta(detail.eta_seconds, translate),
  });
}

export function formatVisualProgressLog(detail: VisualProcessingProgress, translate: Translate): string {
  if (!detail.decision) {
    return translate('transcription.visualLogStarted', {
      captured: detail.captured_frames,
      total: detail.total,
      mode: detail.routing_mode,
    });
  }
  const decision = translate(`transcription.visualDecision_${detail.decision}`);
  const task = detail.task ? ` · ${detail.task}` : '';
  const sequence = detail.sequence === null || detail.sequence === undefined ? '-' : detail.sequence;
  return translate('transcription.visualLogEntry', {
    sequence,
    task,
    decision,
    processed: detail.processed,
    total: detail.total,
    eta: formatVisualEta(detail.eta_seconds, translate),
  });
}
