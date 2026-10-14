import { useState } from 'react';
import { Clock3, Loader2, XCircle } from 'lucide-react';
import type { TranscriptionJob } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { formatASRTrackProgressStatus, formatDuration, formatVisualProgressStatus, isASRTrackProgress, isVisualProcessingProgress, localizeJobStep } from '../../utils/jobs';
import { Button } from '../ui/Button';

type ProgressJob = Pick<TranscriptionJob, 'id' | 'type' | 'status' | 'current_step' | 'progress' | 'progress_detail'> & { label?: string; cancellable?: boolean };

export function JobProgress({ job, onCancel }: { job: ProgressJob; onCancel: (id: string, type?: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);
  const waiting = ['queued', 'waiting_for_service', 'retrying'].includes(job.status);
  const cancelling = ['cancelling', 'cancel_requested'].includes(job.status) || submitting;
  const detail = job.progress_detail;
  const asr = isASRTrackProgress(detail) ? detail : null;
  const visual = isVisualProcessingProgress(detail) ? detail : null;
  const measured = asr && asr.phase === 'transcribing' && asr.processed_audio_seconds > 0 && Number(asr.audio_duration_seconds) > 0
    ? asr.track_percent : visual && visual.total > 0 ? (visual.processed / visual.total) * 100 : null;
  const percent = !waiting && !cancelling && measured !== null && Number.isFinite(measured)
    ? Math.min(100, Math.max(0, Math.round(measured))) : null;
  const progressText = asr && asr.phase === 'transcribing' && asr.processed_audio_seconds > 0
    ? formatASRTrackProgressStatus(asr, t) : asr && asr.phase === 'transcribing'
      ? t('meetingProgress.trackWaiting', { track: asr.track_label || asr.track_id || t('activities.unknownSource'), duration: formatDuration(asr.audio_duration_seconds) })
      : visual ? formatVisualProgressStatus(visual, t) : null;
  const statusKey = cancelling ? 'cancelling' : waiting ? job.status : 'running';
  const stepKeys: Record<string, string> = {
    preparing_transcript: 'transcript', preparing_visual_evidence: 'visual', preparing_notes: 'notes',
    analysis: 'analysis', loading_model: 'loadingModel', downloading: 'downloading', transcribing: 'transcribing',
  };
  const rawStep = asr && ['loading_model', 'downloading'].includes(asr.phase) ? asr.phase : job.current_step;
  const localized = localizeJobStep(rawStep, t);
  const step = job.label || (stepKeys[rawStep] ? t(`meetingProgress.${stepKeys[rawStep]}`)
    : localized !== rawStep ? localized : t(`meetingProgress.${job.type === 'meeting_preparation' ? 'preparation' : job.type === 'analysis' ? 'analysis' : 'processing'}`));
  const stateText = t(`meetingProgress.${statusKey}`);

  const cancel = async () => {
    setSubmitting(true);
    setError(false);
    try { await onCancel(job.id, job.type); } catch { setError(true); } finally { setSubmitting(false); }
  };

  return (
    <div className="min-w-0" data-meeting-job-progress={job.type} data-progress-state={statusKey}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-text-primary">{step}</span>
        <span className="text-xs text-text-secondary tabular-nums" role="status" aria-live="polite" aria-atomic="true">
          {percent === null ? stateText : `${percent}% · ${t(asr ? 'meetingProgress.measured' : 'meetingProgress.measuredItems')}`}
        </span>
      </div>
      {!waiting && !cancelling && (
        <div
          className="meeting-progress-track mt-2"
          role="progressbar"
          aria-label={step}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? undefined}
          aria-valuetext={percent === null ? stateText : `${percent}% · ${t(asr ? 'meetingProgress.measured' : 'meetingProgress.measuredItems')}`}
        >
          <div className={percent === null ? 'meeting-progress-indeterminate' : 'meeting-progress-fill'} style={percent === null ? undefined : { width: `${percent}%` }} />
        </div>
      )}
      {error && <p className="mt-2 text-xs text-danger" role="alert">{t('activities.actionFailed')}</p>}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-xs leading-relaxed text-text-secondary">
          {(!waiting && !cancelling ? progressText : null) || t(`meetingProgress.${cancelling ? 'cancellingHint' : waiting ? 'waitingHint' : 'indeterminateHint'}`)}
        </p>
        {job.cancellable !== false && <Button variant="ghost" size="sm" disabled={cancelling} onClick={() => void cancel()} className="min-h-8 shrink-0 text-danger hover:text-danger-hover" aria-label={`${t('common.cancel')} · ${step}`}>
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
          {cancelling ? t('meetingProgress.cancelling') : t('common.cancel')}
        </Button>}
      </div>
    </div>
  );
}

export function MeetingProcessingStatus({ jobs, onCancel, onDetails }: {
  jobs: ProgressJob[];
  onCancel: (id: string, type?: string) => Promise<void>;
  onDetails: () => void;
}) {
  const { t } = useTranslation();
  if (!jobs.length) return null;
  const waiting = jobs.every((job) => ['queued', 'waiting_for_service', 'retrying'].includes(job.status));
  const cancelling = jobs.every((job) => job.status === 'cancelling');
  return (
    <section className="rounded-xl border border-border-subtle bg-bg-elevated px-4 py-3 sm:px-5" aria-label={t('meetingProgress.processing')}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-text-primary" role="status" aria-live="polite">
          {waiting ? <Clock3 className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" /> : <Loader2 className="h-4 w-4 shrink-0 motion-safe:animate-spin text-accent" aria-hidden="true" />}
          <span>{t(`meetingProgress.${cancelling ? 'cancelling' : waiting ? 'waitingTitle' : 'processing'}`)}</span>
        </div>
        <Button variant="ghost" size="sm" onClick={onDetails} className="min-h-8 shrink-0">{t('meetingProgress.details')}</Button>
      </div>
      <div className="mt-3 space-y-3 divide-y divide-border-subtle [&>div+div]:pt-3">
        {jobs.map((job) => <JobProgress key={job.id} job={job} onCancel={onCancel} />)}
      </div>
    </section>
  );
}
