/**
 * DashboardPage.tsx
 * Main "Today" view — progressive disclosure layout.
 *
 * Information hierarchy:
 *   Level 1 (Hero)      — Period, search, summary links and guidance
 *   Level 2 (Spotlight) — Top 3 meetings and top 2 digest snippets
 *   Level 3 (On-demand) — Full lists, actions, decisions, risks and diagnostics
 */

import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ChevronDown,
  ChevronRight,
  FileAudio,
  Info,
  ListChecks,
  Mic,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
} from 'lucide-react';
import { ApiClient, Meeting } from '../api/apiClient';
import { getDemoMeetings } from '../features/demo/demoData';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Tooltip } from '../components/ui/Tooltip';
import { Dialog, DialogContent, DialogHeader, DialogBody } from '../components/ui/Dialog';
import { TaskProcessingLoader } from '../components/workspace/TaskProcessingLoader';
import { InsightDetailDialog, InsightTab } from '../components/workspace/InsightDetailDialog';
import { MeetingListDialog } from '../components/workspace/MeetingListDialog';
import { MeetingSearchDialog } from '../components/workspace/MeetingSearchDialog';
import {
  DigestPanel,
  EmptyState,
  GuidanceCallout,
  MeetingCard,
  SectionHeader,
} from '../components/workspace/MeetingWorkspace';
import { EmptyStateHero } from '../components/ui/EmptyStateHero';
import {
  TimeRangeState,
  extractActionItems,
  extractDecisions,
  extractDigest,
  extractRisks,
  formatTimeRangeLabel,
  isWithinTimeRange,
  meetingTitle,
  resolveTimeRange,
  sortByNewest,
  sourceFromMeeting,
  uniqueInsightItems,
} from '../utils/meetingInsights';
import { useTranslation } from '../i18n/i18n';
import { cn } from '../utils/cn';
import { useToast } from '../context/ToastContext';

interface DashboardPageProps {
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
  onActivateDemo?: () => void;
}

function ViewAllLink({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" onClick={onClick} className="view-all-link">
      {label}
      <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  );
}

function InsightPreviewCard({
  text,
  meta,
  onClick,
  variant = 'default',
}: {
  text: string;
  meta?: string;
  onClick?: () => void;
  variant?: 'default' | 'warning';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'insight-card-compact w-full text-left',
        variant === 'warning' && 'border-warning/20 bg-warning/5 hover:border-warning/40 hover:bg-warning/10',
      )}
    >
      <p className="line-clamp-2 text-sm leading-snug text-text-primary">{text}</p>
      {meta && <p className="mt-1 truncate text-xs text-text-muted">{meta}</p>}
    </button>
  );
}

export default function DashboardPage({
  navigateTo,
  demoMode = false,
  onActivateDemo,
}: DashboardPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [timeRange, setTimeRange] = useState<TimeRangeState>({ mode: 'today' });
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [dropdownCoords, setDropdownCoords] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const periodMenuRef = useRef<HTMLDivElement>(null);

  const [editingRecordingId, setEditingRecordingId] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');

  const [insightDialogOpen, setInsightDialogOpen] = useState(false);
  const [insightDialogTab, setInsightDialogTab] = useState<InsightTab>('actions');
  const [meetingListDialogOpen, setMeetingListDialogOpen] = useState(false);
  const [techDetailsOpen, setTechDetailsOpen] = useState(false);

  useEffect(() => {
    if (isDropdownOpen && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropdownCoords({ top: rect.bottom + window.scrollY, left: rect.left + window.scrollX });
    }
  }, [isDropdownOpen]);

  useEffect(() => {
    if (!isDropdownOpen) return;
    const frame = window.requestAnimationFrame(() => {
      periodMenuRef.current
        ?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]')
        ?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isDropdownOpen]);

  const rangeOptions = useMemo(() => [
    { mode: 'today' as const, label: lang === 'it' ? 'Oggi' : 'Today' },
    { mode: 'last3' as const, label: lang === 'it' ? 'Ultimi 3 giorni' : 'Last 3 days' },
    { mode: 'week' as const, label: lang === 'it' ? 'Settimana' : 'This week' },
    { mode: 'custom' as const, label: lang === 'it' ? 'Range custom' : 'Custom range' },
  ], [lang]);

  const handlePeriodMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      periodMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [],
    );
    if (!items.length) return;

    const currentIndex = Math.max(0, items.indexOf(document.activeElement as HTMLButtonElement));
    let nextIndex = currentIndex;
    if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % items.length;
    else if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + items.length) % items.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = items.length - 1;
    else if (event.key === 'Escape') {
      event.preventDefault();
      setIsDropdownOpen(false);
      triggerRef.current?.focus();
      return;
    } else {
      return;
    }

    event.preventDefault();
    items[nextIndex]?.focus();
  };

  const selectRange = (mode: TimeRangeState['mode']) => {
    setTimeRange((current) => ({ ...current, mode }));
    setIsDropdownOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const load = async () => {
    try {
      setLoading(true);
      if (demoMode) { setMeetings(getDemoMeetings(lang)); return; }
      const data = await ApiClient.listMeetings(120);
      setMeetings(data.items || []);
    } catch (error) {
      console.error('Failed to load meetings:', error);
      setMeetings(demoMode ? getDemoMeetings(lang) : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [demoMode, lang]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsSearchOpen(true);
      }
      if (e.key === 'Escape') setIsDropdownOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const resolvedRange = useMemo(() => resolveTimeRange(timeRange), [timeRange]);
  const rangeLabel = useMemo(() => formatTimeRangeLabel(timeRange, lang), [timeRange, lang]);
  const periodMeetings = useMemo(
    () => meetings.filter((meeting) => isWithinTimeRange(meeting.created_at, resolvedRange)),
    [meetings, resolvedRange],
  );

  const sources = useMemo(() => periodMeetings.map(sourceFromMeeting), [periodMeetings]);
  const actionItems = useMemo(
    () => sortByNewest(uniqueInsightItems(sources.flatMap(extractActionItems))).filter((item) => !item.completed),
    [sources],
  );
  const decisions = useMemo(() => sortByNewest(uniqueInsightItems(sources.flatMap(extractDecisions))), [sources]);
  const risks = useMemo(() => sortByNewest(uniqueInsightItems(sources.flatMap(extractRisks))), [sources]);
  const digestItems = useMemo(
    () => sortByNewest(sources.map(extractDigest).filter((item): item is NonNullable<typeof item> => Boolean(item))),
    [sources],
  );

  const analyzingCount = periodMeetings.filter(
    (m) => m.status === 'analyzing' || m.jobs.some((j) => !['completed', 'failed', 'cancelled', 'interrupted'].includes(j.status)),
  ).length;
  const readyCount = periodMeetings.filter((m) => m.status === 'ready').length;
  const hasAnyData = meetings.length > 0;

  const handleRenameClick = (meeting: Meeting) => {
    if (demoMode) return;
    setEditingRecordingId(meeting.recording.id);
    setEditTitleValue(meeting.recording.title || meetingTitle(meeting));
  };

  const handleSaveRename = async (meeting: Meeting) => {
    if (demoMode) return;
    const title = editTitleValue.trim();
    if (!title) {
      showToast(t('transcription.titleEmptyError') || 'Title cannot be empty.', 'error');
      return;
    }
    try {
      setMeetings((prev) =>
        prev.map((m) =>
          m.id === meeting.id ? { ...m, recording: { ...m.recording, title } } : m
        )
      );
      setEditingRecordingId(null);

      await ApiClient.updateRecording(meeting.recording.id, { title });
      showToast(t('transcription.titleSaveSuccess') || 'Title updated successfully', 'success');

      const data = await ApiClient.listMeetings(120);
      setMeetings(data.items || []);
    } catch (err: any) {
      showToast(t('transcription.titleSaveError', { error: err.message }) || 'Error updating title', 'error');
      load();
    }
  };

  if (loading) {
    return (
      <div className="py-16">
        <TaskProcessingLoader
          title={t('workspace.loaderDashboardTitle')}
          description={t('workspace.loaderDashboardDesc')}
          steps={[t('workspace.loaderDashboardStep1'), t('workspace.loaderDashboardStep2'), t('workspace.loaderDashboardStep3')]}
          activeStep={1}
          progress={66}
          variant="analysis"
          helperText={t('workspace.loaderLocalHelper')}
        />
      </div>
    );
  }

  const activeOption = rangeOptions.find((opt) => opt.mode === timeRange.mode);
  const activeLabel = activeOption ? activeOption.label : '';

  if (!hasAnyData && !demoMode) {
    return (
      <EmptyStateHero
        icon={Mic}
        title={t('demo.emptyTitle')}
        description={t('demo.emptyDesc')}
        primaryAction={
          <Button size="lg" onClick={() => navigateTo('recording')}>
            <Mic className="h-5 w-5" aria-hidden="true" />
            {t('demo.emptyCta')}
          </Button>
        }
        secondaryAction={
          onActivateDemo ? (
            <Button size="lg" variant="secondary" onClick={onActivateDemo}>
              <Sparkles className="h-5 w-5" aria-hidden="true" />
              {t('demo.emptyCtaDemo')}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <section
        data-tour="today-summary"
        className="premium-hero page-hero rounded-2xl p-5 sm:p-6"
      >
        <span className="hero-orbital-line" aria-hidden="true" />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase text-accent">{rangeLabel}</span>
              <Badge variant="success">{t('dashboard.localBadge')}</Badge>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="relative">
                <button
                  ref={triggerRef}
                  type="button"
                  onClick={() => setIsDropdownOpen((open) => !open)}
                  className="flex items-center gap-2 rounded-xl bg-transparent px-0 py-0 text-3xl font-bold text-text-primary outline-none transition-colors hover:text-accent focus-visible:ring-2 focus-visible:ring-border-focus sm:text-4xl"
                  aria-haspopup="menu"
                  aria-expanded={isDropdownOpen}
                  aria-controls="dashboard-period-menu"
                  aria-label={lang === 'it' ? `Periodo: ${activeLabel}` : `Period: ${activeLabel}`}
                >
                  <span>{activeLabel}</span>
                  <ChevronDown className="h-6 w-6 shrink-0 text-text-muted" aria-hidden="true" />
                </button>
                {isDropdownOpen && dropdownCoords && createPortal(
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onMouseDown={() => setIsDropdownOpen(false)}
                      aria-hidden="true"
                    />
                    <div
                      id="dashboard-period-menu"
                      ref={periodMenuRef}
                      role="menu"
                      aria-label={lang === 'it' ? 'Seleziona periodo' : 'Select period'}
                      onKeyDown={handlePeriodMenuKeyDown}
                      style={{ position: 'absolute', top: `${dropdownCoords.top + 6}px`, left: `${dropdownCoords.left}px` }}
                      className="z-50 w-48 rounded-xl border border-border-subtle bg-bg-elevated p-1 shadow-premium"
                    >
                      {rangeOptions.map((option) => (
                        <button
                          key={option.mode}
                          type="button"
                          role="menuitemradio"
                          aria-checked={timeRange.mode === option.mode}
                          onClick={() => selectRange(option.mode)}
                          className={`w-full rounded-lg px-3 py-2 text-left text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus ${
                            timeRange.mode === option.mode
                              ? 'bg-accent/15 text-accent'
                              : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </>,
                  document.body,
                )}
              </div>

              {timeRange.mode === 'custom' && (
                <div className="flex items-center gap-1.5 text-xs">
                  <input
                    type="date"
                    value={timeRange.startDate || ''}
                    onChange={(e) => setTimeRange({ ...timeRange, startDate: e.target.value })}
                    aria-label={lang === 'it' ? 'Data iniziale' : 'Start date'}
                    className="h-8 rounded-lg border border-border-subtle bg-bg-elevated px-2 text-xs text-text-primary outline-none focus:border-border-focus focus:ring-1 focus:ring-border-focus"
                  />
                  <span className="text-text-muted" aria-hidden="true">–</span>
                  <input
                    type="date"
                    value={timeRange.endDate || ''}
                    onChange={(e) => setTimeRange({ ...timeRange, endDate: e.target.value })}
                    aria-label={lang === 'it' ? 'Data finale' : 'End date'}
                    className="h-8 rounded-lg border border-border-subtle bg-bg-elevated px-2 text-xs text-text-primary outline-none focus:border-border-focus focus:ring-1 focus:ring-border-focus"
                  />
                </div>
              )}

              <Tooltip content={t('dashboard.searchPlaceholder')}>
                <button
                  type="button"
                  onClick={() => setIsSearchOpen(true)}
                  aria-label={t('dashboard.searchPlaceholder')}
                  className="pressable rounded-xl border border-transparent p-2 text-text-muted transition-colors hover:border-border-focus hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                >
                  <Search className="h-4 w-4" aria-hidden="true" />
                </button>
              </Tooltip>

              <Tooltip content={lang === 'it' ? 'Dettagli tecnici' : 'Technical status'}>
                <button
                  type="button"
                  onClick={() => setTechDetailsOpen(true)}
                  aria-label={lang === 'it' ? 'Apri dettagli tecnici' : 'Open technical status'}
                  className="pressable rounded-xl border border-transparent p-2 text-text-muted transition-colors hover:border-border-focus hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                >
                  <Info className="h-4 w-4" aria-hidden="true" />
                </button>
              </Tooltip>
            </div>
            <p className="mt-2 max-w-lg text-sm leading-relaxed text-text-secondary">{t('dashboard.subtitle')}</p>
            {periodMeetings.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2.5">
                <button
                  type="button"
                  onClick={() => setMeetingListDialogOpen(true)}
                  className="flex items-center gap-2 rounded-xl border border-border-subtle bg-bg-glass/40 px-3 py-1.5 text-xs font-semibold text-text-secondary transition-colors hover:border-border-focus hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                >
                  <FileAudio className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                  <span>
                    <strong>{periodMeetings.length}</strong> {lang === 'it' ? 'Meeting nel periodo' : 'Meetings in period'}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => { setInsightDialogTab('actions'); setInsightDialogOpen(true); }}
                  className="flex items-center gap-2 rounded-xl border border-border-subtle bg-bg-glass/40 px-3 py-1.5 text-xs font-semibold text-text-secondary transition-colors hover:border-border-focus hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                >
                  <ListChecks className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                  <span>
                    <strong>{actionItems.length}</strong> {lang === 'it' ? 'Azioni aperte' : 'Open actions'}
                  </span>
                </button>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <GuidanceCallout
              icon={ShieldCheck}
              title={t('dashboard.heroGuidanceTitle')}
              description={demoMode ? t('dashboard.demoReadonlyHint') : t('dashboard.heroGuidanceDesc')}
              className="hidden xl:block max-w-sm"
            />
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.8fr)_minmax(300px,1fr)]">
        <main className="flex min-w-0 flex-col gap-5">
          <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4 theme-audio" data-tour="today-meetings">
            <div className="flex items-center justify-between gap-3">
              <SectionHeader
                icon={FileAudio}
                title={t('dashboard.meetingsTitle')}
                description={t('dashboard.meetingsDesc')}
                tooltip={t('dashboard.meetingsTooltip')}
              />
              {periodMeetings.length > 3 && (
                <ViewAllLink
                  onClick={() => setMeetingListDialogOpen(true)}
                  label={`${t('demo.viewAllMeetings').replace('→', '')}(${periodMeetings.length}) →`}
                />
              )}
            </div>

            {periodMeetings.length === 0 ? (
              <EmptyState
                icon={Mic}
                title={timeRange.mode === 'today' ? t('dashboard.emptyMeetingsTodayTitle') : t('dashboard.emptyMeetingsTitle')}
                description={t('dashboard.emptyMeetingsDesc')}
                className="mx-auto w-full max-w-md py-6"
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button onClick={() => navigateTo('recording')} disabled={demoMode}>{t('dashboard.btnRecord')}</Button>
                    <Button variant="secondary" onClick={() => navigateTo('transcription')} disabled={demoMode}>{t('dashboard.btnImport')}</Button>
                  </div>
                }
              />
            ) : (
              <div className="flex flex-col gap-3">
                {periodMeetings.slice(0, 3).map((meeting) => (
                  <MeetingCard
                    key={meeting.id}
                    meeting={meeting}
                    lang={lang}
                    onOpen={() => navigateTo('meeting', meeting.id)}
                    isEditing={editingRecordingId === meeting.recording.id}
                    editTitleValue={editTitleValue}
                    setEditTitleValue={setEditTitleValue}
                    onRename={() => handleRenameClick(meeting)}
                    onSaveRename={() => handleSaveRename(meeting)}
                    onCancelRename={() => setEditingRecordingId(null)}
                    demoMode={demoMode}
                  />
                ))}
                {periodMeetings.length > 3 && (
                  <button
                    type="button"
                    onClick={() => setMeetingListDialogOpen(true)}
                    className="rounded-xl border border-dashed border-border-subtle py-3 text-center text-xs font-semibold text-text-muted transition-colors hover:border-border-focus hover:bg-bg-hover hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    {lang === 'it'
                      ? `+ ${periodMeetings.length - 3} altri meeting`
                      : `+ ${periodMeetings.length - 3} more meetings`}
                  </button>
                )}
              </div>
            )}
          </section>
        </main>

        <aside className="flex flex-col gap-4">
          <DigestPanel items={digestItems.slice(0, 2)} title={t('dashboard.digestTitle')} />
        </aside>
      </section>

      {(periodMeetings.length > 0 || actionItems.length > 0 || decisions.length > 0 || risks.length > 0) && (
        <section className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <section
            className="surface-primary flex flex-col gap-3 rounded-2xl p-4 theme-tasks"
            data-tour="open-actions"
          >
            <div className="flex items-center justify-between gap-3">
              <SectionHeader
                icon={ListChecks}
                title={t('dashboard.statOpenActions')}
                description={t('dashboard.openActionsDesc')}
                tooltip={t('dashboard.openActionsTooltip')}
              />
              {actionItems.length > 3 && (
                <ViewAllLink
                  onClick={() => { setInsightDialogTab('actions'); setInsightDialogOpen(true); }}
                  label={t('demo.viewAllActions')}
                />
              )}
            </div>

            {actionItems.length === 0 ? (
              <p className="text-xs text-text-muted py-3">{t('workspace.emptyActionsTitle')}</p>
            ) : (
              <div className="flex flex-col gap-2">
                {actionItems.slice(0, 3).map((item) => (
                  <InsightPreviewCard
                    key={item.id}
                    text={item.text}
                    meta={[item.owner, item.dueDate ? `${t('workspace.dueDateLabel')} ${item.dueDate}` : '', item.priority, item.sourceTitle].filter(Boolean).join(' · ')}
                    onClick={() => { setInsightDialogTab('actions'); setInsightDialogOpen(true); }}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4 theme-decisions" data-tour="decision-log">
            <div className="flex items-center justify-between gap-3">
              <SectionHeader icon={Target} title={t('dashboard.decisionsTitle')} description={t('dashboard.decisionsDesc')} />
              {decisions.length > 2 && (
                <ViewAllLink
                  onClick={() => { setInsightDialogTab('decisions'); setInsightDialogOpen(true); }}
                  label={t('demo.viewAllDecisions')}
                />
              )}
            </div>
            {decisions.length === 0 ? (
              <p className="text-xs text-text-muted py-3">{t('workspace.emptyDecisionsTitle')}</p>
            ) : (
              <div className="flex flex-col gap-2">
                {decisions.slice(0, 2).map((item) => (
                  <InsightPreviewCard
                    key={item.id}
                    text={item.text}
                    meta={item.sourceTitle}
                    onClick={() => { setInsightDialogTab('decisions'); setInsightDialogOpen(true); }}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4 theme-risks" data-tour="risk-panel">
            <div className="flex items-center justify-between gap-3">
              <SectionHeader icon={ShieldAlert} title={t('dashboard.risksTitle')} description={t('dashboard.risksDesc')} />
              {risks.length > 2 && (
                <ViewAllLink
                  onClick={() => { setInsightDialogTab('risks'); setInsightDialogOpen(true); }}
                  label={t('demo.viewAllRisks')}
                />
              )}
            </div>
            {risks.length === 0 ? (
              <p className="text-xs text-text-muted py-3">{t('workspace.emptyRisksTitle')}</p>
            ) : (
              <div className="flex flex-col gap-2">
                {risks.slice(0, 2).map((item) => (
                  <InsightPreviewCard
                    key={item.id}
                    text={item.text}
                    meta={item.sourceTitle}
                    variant="warning"
                    onClick={() => { setInsightDialogTab('risks'); setInsightDialogOpen(true); }}
                  />
                ))}
              </div>
            )}
          </section>
        </section>
      )}

      <InsightDetailDialog
        dataTour="insight-detail-dialog-content"
        open={insightDialogOpen}
        onOpenChange={setInsightDialogOpen}
        initialTab={insightDialogTab}
        actions={actionItems}
        decisions={decisions}
        risks={risks}
      />

      <MeetingListDialog
        dataTour="meeting-list-dialog-content"
        open={meetingListDialogOpen}
        onOpenChange={setMeetingListDialogOpen}
        meetings={periodMeetings}
        onOpenMeeting={(id) => navigateTo('meeting', id)}
      />

      <Dialog open={techDetailsOpen} onOpenChange={setTechDetailsOpen}>
        <DialogContent size="sm" dataTour="tech-details-dialog-content">
          <DialogHeader
            title={t('workspace.advancedTitle')}
            description={t('workspace.advancedDesc')}
          />
          <DialogBody>
            <p className="mb-4 rounded-lg border border-border-subtle bg-bg-glass px-3 py-2 text-xs leading-relaxed text-text-muted">
              {t('workspace.advancedHelper')}
            </p>
            <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-3 text-xs">
              <dt className="text-text-muted">{t('dashboard.techLoaded')}</dt>
              <dd className="font-semibold text-text-secondary">{meetings.length}</dd>
              <dt className="text-text-muted">{t('dashboard.techFiltered')}</dt>
              <dd className="font-semibold text-text-secondary">{periodMeetings.length}</dd>
              <dt className="text-text-muted">{t('dashboard.techReady')}</dt>
              <dd className="font-semibold text-text-secondary">{readyCount}</dd>
              <dt className="text-text-muted">{t('dashboard.techActive')}</dt>
              <dd className="font-semibold text-text-secondary">{analyzingCount}</dd>
              <dt className="text-text-muted">{t('dashboard.techRange')}</dt>
              <dd className="truncate font-semibold text-text-secondary">{rangeLabel}</dd>
            </dl>
          </DialogBody>
        </DialogContent>
      </Dialog>

      <MeetingSearchDialog
        open={isSearchOpen}
        onOpenChange={setIsSearchOpen}
        onOpenMeeting={(id) => navigateTo('meeting', id)}
        lang={lang}
        demoMeetings={demoMode ? meetings : undefined}
      />
    </div>
  );
}
