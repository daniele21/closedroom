import { ListTodo } from 'lucide-react';
import { ApiClient, type ActivityJob } from '../api/apiClient';
import { TERMINAL_JOB_STATUSES } from '../api/jobEvents';
import type { ActivitiesState } from '../hooks/useActivities';
import type { AudioImportsState } from '../hooks/useAudioImports';
import { useTranslation } from '../i18n/i18n';
import { JobProgress } from '../components/meeting/MeetingProcessingStatus';
import { Button } from '../components/ui/Button';

export default function ActivitiesPage({ activities, audioImports, navigateTo }: {
  activities: ActivitiesState;
  audioImports: AudioImportsState;
  navigateTo: (page: string, detail?: string | null) => void;
}) {
  const { t } = useTranslation();
  const active = activities.items.filter((job) => !TERMINAL_JOB_STATUSES.has(job.status));
  const recent = activities.items.filter((job) => TERMINAL_JOB_STATUSES.has(job.status));
  const uploads = audioImports.items.filter((item) => !['submitted', 'cancelled'].includes(item.phase));
  const open = (job: ActivityJob) => {
    if (job.scope_type === 'recording' && job.scope_id) navigateTo('meeting', job.scope_id);
    else if (job.scope_type === 'inline_text' && job.scope_id) navigateTo('analysis', job.scope_id);
    else if (job.scope_type === 'transcription' && job.scope_id) navigateTo('transcription', job.scope_id);
  };
  const canOpen = (job: ActivityJob) => Boolean(job.scope_id && ['recording', 'inline_text', 'transcription'].includes(job.scope_type || ''));
  const cancel = async (job: ActivityJob) => {
    if (job.type === 'meeting_preparation' && job.scope_id) await ApiClient.cancelMeetingPreparation(job.scope_id, job.id);
    else await ApiClient.cancelJob(job.id);
    await activities.refresh();
  };
  const row = (job: ActivityJob, running: boolean) => (
    <li key={job.id} className="py-5" data-activity-id={job.id}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold text-text-primary">{job.source_label || t('activities.unknownSource')}</p>
          <p className="mt-1 text-xs text-text-secondary">{t(`activities.${job.type || 'unknownSource'}`)} · {new Date(job.created_at * 1000).toLocaleString()}</p>
        </div>
        {canOpen(job) && <Button variant="secondary" size="sm" onClick={() => open(job)}>{t(job.status === 'completed' ? 'activities.openResult' : 'activities.open')}</Button>}
      </div>
      {running ? <JobProgress job={{ ...job, progress_detail: activities.children.find((child) => child.parent_job_id === job.id && child.status !== 'queued' && !TERMINAL_JOB_STATUSES.has(child.status))?.progress_detail || job.progress_detail, cancellable: !activities.stale }} onCancel={() => cancel(job)} /> : (
        <p className={`text-sm ${job.status === 'failed' ? 'text-danger' : 'text-text-secondary'}`}>{t(`activities.${job.status}`)}</p>
      )}
      {running && job.status === 'queued' && !activities.stale && (activities.capture_blocked || activities.active_count > 0) && (
        <p className="mt-2 text-xs text-text-secondary">{t(activities.capture_blocked ? 'activities.captureWait' : 'activities.queueWait')}</p>
      )}
    </li>
  );
  return <div className="mx-auto w-full max-w-4xl space-y-8" data-activities-page>
    <header className="flex items-start justify-between gap-4">
      <div><h1 className="flex items-center gap-3 text-2xl font-semibold text-text-primary"><ListTodo className="h-6 w-6" aria-hidden="true" />{t('activities.title')}</h1>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">{t('activities.description')}</p></div>
      <Button variant="ghost" size="sm" onClick={() => void activities.refresh()}>{t('activities.refresh')}</Button>
    </header>
    {activities.stale && <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-text-secondary" role="alert">{t('activities.offline')}</p>}
    <section aria-labelledby="active-activities"><h2 id="active-activities" className="text-sm font-semibold text-text-primary">{t('activities.active')} · {active.length}</h2>
      {activities.loading ? <p className="py-5 text-sm text-text-secondary" role="status">{t('common.loading')}</p> : active.length ? <ul className="divide-y divide-border-subtle">{active.map((job) => row(job, true))}</ul> : <p className="py-5 text-sm text-text-secondary">{t('activities.empty')}</p>}
    </section>
    {uploads.length > 0 && <section aria-labelledby="import-activities">
      <h2 id="import-activities" className="text-sm font-semibold text-text-primary">{t('activities.imports')}</h2>
      <ul className="divide-y divide-border-subtle">
        {uploads.map((upload) => <li key={upload.id} className="py-4" data-audio-import={upload.id}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate font-medium text-text-primary">{upload.name}</p>
              <p className="text-sm text-text-secondary" role="status">
                {upload.phase === 'uploading' ? t('activities.importing')
                  : upload.phase === 'submitting' ? t('activities.importSubmitting')
                  : upload.phase === 'cancelling' ? t('activities.importCancelling')
                  : t('activities.importFailed')}
              </p>
              {upload.error && <p className="text-sm text-danger" role="alert">{upload.error}</p>}
            </div>
            {upload.phase === 'uploading' && <Button variant="secondary" size="sm"
              onClick={() => void audioImports.cancel(upload.id)}>{t('activities.cancel')}</Button>}
            {upload.recordingId && <Button variant="ghost" size="sm"
              onClick={() => navigateTo('meeting', upload.recordingId)}>{t('activities.open')}</Button>}
          </div>
        </li>)}
      </ul>
    </section>}
    {recent.length > 0 && <section aria-labelledby="recent-activities"><h2 id="recent-activities" className="text-sm font-semibold text-text-primary">{t('activities.recent')}</h2><ul className="divide-y divide-border-subtle">{recent.map((job) => row(job, false))}</ul></section>}
  </div>;
}
