/**
 * MeetingListDialog.tsx
 * Drawer showing the complete filtered list of meetings.
 * Used by DashboardPage as progressive disclosure for the meeting list.
 */

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarDays, CheckCircle2, Clock3, FileAudio, FolderKanban, Search, Sparkles, X } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogBody } from '../ui/Dialog';
import { Badge } from '../ui/Badge';
import { cn } from '../../utils/cn';
import { useTranslation } from '../../i18n/i18n';
import { formatProjectDate, getDurationSeconds } from '../../utils/formatters';
import { meetingTitle } from '../../utils/meetingInsights';
import { ANALYSIS_TYPE_LABELS } from '../../api/config';
import { ApiClient, type Meeting } from '../../api/apiClient';

// ─── Status filter options ───────────────────────────────────────────────────

type StatusFilter = 'all' | 'ready' | 'transcribed' | 'recorded';

// ─── Row component ───────────────────────────────────────────────────────────

function MeetingRow({
  meeting,
  lang,
  onClick,
}: {
  meeting: Meeting;
  lang: string;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const duration = getDurationSeconds(meeting.recording);
  const analysisTypes = Object.keys(meeting.latest_analysis || {});

  const statusMeta = {
    recording: { label: t('workspace.statusRecording'), variant: 'warning' as const },
    recorded: { label: t('workspace.statusRecorded'), variant: 'idle' as const },
    transcribed: { label: t('workspace.statusTranscribed'), variant: 'info' as const },
    analyzing: { label: t('workspace.statusAnalyzing'), variant: 'warning' as const },
    ready: { label: t('workspace.statusReady'), variant: 'success' as const },
    failed: { label: t('workspace.statusFailed'), variant: 'danger' as const },
  }[meeting.status] || { label: meeting.status, variant: 'idle' as const };

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-3 rounded-xl border border-transparent px-4 py-3 text-left transition-all hover:border-border-focus hover:bg-bg-hover"
    >
      {/* Icon */}
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border-subtle bg-bg-glass text-accent">
        <FileAudio className="h-4 w-4" />
      </span>

      {/* Main content */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-text-primary group-hover:text-accent transition-colors">
            {meetingTitle(meeting)}
          </span>
          <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1">
            <CalendarDays className="h-3.5 w-3.5" />
            {formatProjectDate(meeting.created_at, lang)}
          </span>
          {duration > 0 && (
            <span className="inline-flex items-center gap-1">
              <Clock3 className="h-3.5 w-3.5" />
              {Math.round(duration / 60)} min
            </span>
          )}
          {meeting.project_name && (
            <span className="inline-flex items-center gap-1">
              <FolderKanban className="h-3.5 w-3.5" />
              {meeting.project_name}
            </span>
          )}
        </div>
      </div>

      {/* Badges */}
      <div className="hidden shrink-0 flex-wrap justify-end gap-1.5 sm:flex">
        {meeting.transcription ? (
          <span className="inline-flex items-center gap-1 rounded-md border border-success/25 bg-success/10 px-2 py-1 text-[11px] text-success">
            <CheckCircle2 className="h-3 w-3" />
            {t('workspace.transcriptionBadge')}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md border border-warning/25 bg-warning/10 px-2 py-1 text-[11px] text-warning">
            <AlertTriangle className="h-3 w-3" />
            {t('workspace.toTranscribeBadge')}
          </span>
        )}
        {analysisTypes.slice(0, 2).map((type) => (
          <span key={type} className="rounded-md border border-border-subtle bg-bg-surface px-2 py-1 text-[11px] text-text-secondary">
            {ANALYSIS_TYPE_LABELS[type] || type}
          </span>
        ))}
      </div>
    </button>
  );
}

// ─── Main drawer ─────────────────────────────────────────────────────────────

export interface MeetingListDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  meetings: Meeting[];
  onOpenMeeting: (meetingId: string) => void;
  title?: string;
  dataTour?: string;
}

export function MeetingListDialog({
  open,
  onOpenChange,
  meetings,
  onOpenMeeting,
  title,
  dataTour,
}: MeetingListDialogProps) {
  const { t, lang } = useTranslation();
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [showArchived, setShowArchived] = useState(false);
  const [archivedMeetings, setArchivedMeetings] = useState<Meeting[]>([]);
  const [archivedPage, setArchivedPage] = useState(0);
  const [archiveHasMore, setArchiveHasMore] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState(false);

  useEffect(() => {
    if (!open) {
      setShowArchived(false);
      return;
    }
    // Each opening starts with the main collection and a fresh archive view.
    setArchivedMeetings([]);
    setArchivedPage(0);
    setArchiveHasMore(false);
  }, [open]);

  const loadArchived = async (page: number) => {
    setArchiveLoading(true);
    setArchiveError(false);
    try {
      const result = await ApiClient.listArchivedMeetings(page);
      setArchivedMeetings((previous) => page === 1 ? result.items : [...previous, ...result.items]);
      setArchivedPage(page);
      setArchiveHasMore(result.has_more);
    } catch {
      setArchiveError(true);
    } finally {
      setArchiveLoading(false);
    }
  };

  useEffect(() => {
    if (open && showArchived && archivedPage === 0 && !archiveLoading && !archiveError) {
      void loadArchived(1);
    }
  }, [open, showArchived, archivedPage, archiveLoading, archiveError]);

  const visibleMeetings = showArchived ? archivedMeetings : meetings;
  const displayTitle = title ?? t('dashboard.meetingsTitle');

  const filtered = useMemo(() => {
    let result = visibleMeetings;
    if (statusFilter === 'ready') result = result.filter((m) => m.status === 'ready');
    else if (statusFilter === 'transcribed') result = result.filter((m) => Boolean(m.transcription));
    else if (statusFilter === 'recorded') result = result.filter((m) => !m.transcription);

    if (query.trim()) {
      const needle = query.toLowerCase();
      result = result.filter((m) =>
        [meetingTitle(m), m.project_name, m.transcription?.text?.slice(0, 200)]
          .join(' ')
          .toLowerCase()
          .includes(needle),
      );
    }
    return result;
  }, [visibleMeetings, query, statusFilter]);

  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: lang === 'it' ? 'Tutti' : 'All' },
    { value: 'ready', label: lang === 'it' ? 'Con insight' : 'With insights' },
    { value: 'transcribed', label: lang === 'it' ? 'Trascritti' : 'Transcribed' },
    { value: 'recorded', label: lang === 'it' ? 'Da trascrivere' : 'To transcribe' },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        dataTour={dataTour}
        size="lg"
        className="max-h-[85vh] flex flex-col"
      >
        <DialogHeader
          title={displayTitle}
          description={showArchived
            ? (lang === 'it' ? 'Meeting archiviati · tutti i periodi' : 'Archived meetings · all periods')
            : (lang === 'it' ? `${meetings.length} meeting nel periodo selezionato` : `${meetings.length} meetings in selected period`)}
        />

        <div className="flex gap-2 border-b border-border-subtle px-5 pt-3">
          <button type="button" onClick={() => setShowArchived(false)} aria-pressed={!showArchived}
            className={cn('rounded-t-md px-3 py-2 text-xs font-semibold', !showArchived ? 'bg-bg-hover text-text-primary' : 'text-text-muted hover:text-text-primary')}>
            {lang === 'it' ? 'Attivi' : 'Active'}
          </button>
          <button type="button" onClick={() => setShowArchived(true)} aria-pressed={showArchived}
            className={cn('rounded-t-md px-3 py-2 text-xs font-semibold', showArchived ? 'bg-bg-hover text-text-primary' : 'text-text-muted hover:text-text-primary')} data-archived-meetings="true">
            {lang === 'it' ? 'Archiviati' : 'Archived'}
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle bg-bg-surface px-5 py-3">
          {/* Status filter tabs */}
          <div className="flex gap-1">
            {statusOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setStatusFilter(opt.value)}
                className={cn(
                  'rounded-lg px-2.5 py-1 text-xs font-semibold transition-all',
                  statusFilter === opt.value
                    ? 'bg-accent text-white'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary',
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Search */}
          <label className="ml-auto flex h-8 items-center gap-2 rounded-lg border border-border-subtle bg-bg-glass px-3 text-xs shadow-[inset_0_1px_0_var(--surface-highlight)] focus-within:border-border-focus">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('dashboard.searchPlaceholder')}
              className="w-36 bg-transparent text-text-primary outline-none placeholder:text-text-muted"
            />
            {query && (
              <button type="button" onClick={() => setQuery('')} className="text-text-muted hover:text-text-primary">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </label>

          {filtered.length !== visibleMeetings.length && (
            <span className="text-xs text-text-muted">
              {filtered.length} {lang === 'it' ? 'risultati' : 'results'}
            </span>
          )}
        </div>

        {/* List */}
        <DialogBody className="flex flex-col p-2 overflow-y-auto">
          {archiveError && showArchived && (
            <button type="button" onClick={() => void loadArchived(archivedPage || 1)} className="p-3 text-xs text-danger underline">
              {lang === 'it' ? 'Impossibile caricare l’archivio · Riprova' : 'Could not load archive · Retry'}
            </button>
          )}
          {archiveLoading && archivedPage === 0 ? (
            <p className="p-4 text-center text-xs text-text-muted">{lang === 'it' ? 'Caricamento archivio…' : 'Loading archive…'}</p>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Sparkles className="mb-3 h-8 w-8 text-text-muted" />
              <p className="text-sm text-text-muted">
                {query
                  ? (lang === 'it' ? 'Nessun meeting trovato per la ricerca.' : 'No meetings found for the search.')
                  : (lang === 'it' ? 'Nessun meeting nel periodo.' : 'No meetings in this period.')}
              </p>
            </div>
          ) : (
            <>
              {filtered.map((meeting) => (
                <MeetingRow
                  key={meeting.id}
                  meeting={meeting}
                  lang={lang}
                  onClick={() => {
                    onOpenMeeting(meeting.id);
                    onOpenChange(false);
                  }}
                />
              ))}
              {showArchived && archiveHasMore && !query && (
                <button type="button" disabled={archiveLoading} onClick={() => void loadArchived(archivedPage + 1)}
                  className="mx-auto my-2 rounded-lg border border-border-subtle px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-50">
                  {archiveLoading ? '…' : (lang === 'it' ? 'Carica altri' : 'Load more')}
                </button>
              )}
            </>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
