import { useState } from 'react';
import { Clock3, Loader2, XCircle } from 'lucide-react';
import type { TranscriptionJob } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { localizeJobStep } from '../../utils/jobs';
import { Button } from '../ui/Button';

type ProgressJob = Pick<TranscriptionJob, 'id' | 'type' | 'status' | 'current_step' | 'progress'> & { label?: string; cancellable?: boolean };

function JobProgress({ job, onCancel }: { job: ProgressJob; onCancel: (id: string, type?: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const waiting = ['queued', 'waiting_for_service', 'retrying'].includes(job.status);
  const cancelling = job.status === 'cancelling' || submitting;
  // Analysis only emits start/end markers; 10% is not measured inference progress.
  const percent = !waiting && !cancelling && job.type !== 'analysis' && Number.isFinite(job.progress) && job.progress > 0
    ? Math.min(100, Math.round(job.progress)) : null;
  const statusKey = cancelling ? 'cancelling' : waiting ? job.status : 'running';
  const stepKeys: Record<string, string> = {
    preparing_transcript: 'transcript', preparing_visual_evidence: 'visual', preparing_notes: 'notes',
    analysis: 'analysis', loading_model: 'loadingModel', downloading: 'downloading', transcribing: 'transcribing',
  };
  const rawStep = job.current_step;
  const localized = localizeJobStep(rawStep, t);
  const step = job.label || (stepKeys[rawStep] ? t(`meetingProgress.${stepKeys[rawStep]}`)
    : localized !== rawStep ? localized : t(`meetingProgress.${job.type === 'meeting_preparation' ? 'preparation' : job.type === 'analysis' ? 'analysis' : 'processing'}`));
  const stateText = t(`meetingProgress.${statusKey}`);

  const cancel = async () => {
    setSubmitting(true);
    try { await onCancel(job.id, job.type); } finally { setSubmitting(false); }
  };

  return (
    <div className="min-w-0" data-meeting-job-progress={job.type} data-progress-state={statusKey}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-text-primary">{step}</span>
        <span className="text-xs text-text-secondary tabular-nums" role="status" aria-live="polite" aria-atomic="true">
          {percent === null ? stateText : `${percent}% · ${t('meetingProgress.byStages')}`}
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
          aria-valuetext={percent === null ? stateText : `${percent}% · ${t('meetingProgress.byStages')}`}
        >
          <div className={percent === null ? 'meeting-progress-indeterminate' : 'meeting-progress-fill'} style={percent === null ? undefined : { width: `${percent}%` }} />
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-xs leading-relaxed text-text-secondary">
          {t(`meetingProgress.${cancelling ? 'cancellingHint' : waiting ? 'waitingHint' : percent === null ? 'indeterminateHint' : 'stagesHint'}`)}
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
