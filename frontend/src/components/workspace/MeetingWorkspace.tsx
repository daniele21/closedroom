import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Edit3,
  FileAudio,
  FolderKanban,
  Info,
  ListChecks,
  MessageSquare,
  Search,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  Target,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Meeting, Project } from '../../api/apiClient';
import { ANALYSIS_TYPE_LABELS } from '../../api/config';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import { formatProjectDate, getDurationSeconds } from '../../utils/formatters';
import { DigestItem, InsightItem, meetingTitle } from '../../utils/meetingInsights';
import { cn } from '../../utils/cn';
import { useTranslation } from '../../i18n/i18n';

function limitText(value: string, max = 150): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}...`;
}


export function ExplainTooltip({ content }: { content: string }) {
  return (
    <Tooltip content={content}>
      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border-subtle text-text-muted hover:border-border-focus hover:text-text-primary">
        <Info className="h-3.5 w-3.5" />
      </span>
    </Tooltip>
  );
}

export function SectionHeader({
  icon: Icon,
  title,
  description,
  tooltip,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  tooltip?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-border-subtle bg-bg-glass shadow-[inset_0_1px_0_var(--surface-highlight)]">
            <Icon className="h-4 w-4 text-accent" />
          </span>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {tooltip && <ExplainTooltip content={tooltip} />}
        </div>
        {description && <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function GuidanceCallout({
  title,
  description,
  icon: Icon = ShieldCheck,
  className,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <div className={cn('guidance-callout rounded-xl p-3 text-left', className)}>
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-text-primary">{title}</p>
          <p className="mt-1 text-xs leading-relaxed text-text-secondary">{description}</p>
        </div>
      </div>
    </div>
  );
}

export function PageHero({
  eyebrow,
  title,
  description,
  metadata,
  primaryAction,
  secondaryAction,
  controls,
  guidance,
  className,
}: {
  eyebrow?: string;
  title: ReactNode;
  description: string;
  metadata?: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  controls?: ReactNode;
  guidance?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('premium-hero page-hero rounded-2xl p-5 sm:p-6 animate-page-in', className)}>
      <span className="hero-orbital-line" aria-hidden="true" />
      <div className="page-hero-layout">
        <div className="page-hero-copy min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {eyebrow && <span className="text-xs font-semibold uppercase text-accent">{eyebrow}</span>}
            {metadata}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {typeof title === 'string' ? (
              <h2 className="break-words text-3xl font-bold text-text-primary sm:text-4xl">{title}</h2>
            ) : (
              title
            )}
          </div>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-text-secondary">{description}</p>
        </div>
        {guidance && (
          <div className="page-hero-center w-full">
            {guidance}
          </div>
        )}
        {(primaryAction || secondaryAction) && (
          <div className="page-hero-side">
            <div className="page-hero-actions">
              {primaryAction}
              {secondaryAction}
            </div>
          </div>
        )}
        {controls && <div className="page-hero-controls">{controls}</div>}
      </div>
    </section>
  );
}

export function EmptyState({
  icon: Icon = Circle,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('empty-state-panel rounded-xl border border-dashed border-border-subtle px-5 py-8 text-center animate-fade-in', className)}>
      <Icon className="mx-auto mb-3 h-8 w-8 text-text-muted" />
      <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
      <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-text-secondary">{description}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function AdvancedDetailsAccordion({
  children,
  title,
  description,
}: {
  children: ReactNode;
  title?: string;
  description?: string;
}) {
  const { t } = useTranslation();
  const displayTitle = title || t('workspace.advancedTitle');
  const displayDesc = description || t('workspace.advancedDesc');
  return (
    <details className="surface-advanced group rounded-xl overflow-hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-text-primary transition-premium hover:bg-bg-hover/40">
        <span>
          {displayTitle}
          <span className="block text-xs font-normal text-text-muted">{displayDesc}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-text-muted transition-transform group-open:rotate-180" />
      </summary>
      <div className="grid grid-rows-[0fr] transition-[grid-template-rows] duration-300 group-open:grid-rows-[1fr]">
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-border-subtle p-4 animate-fade-in">
            <p className="mb-3 rounded-lg border border-border-subtle bg-bg-glass px-3 py-2 text-xs leading-relaxed text-text-muted">
              {t('workspace.advancedHelper')}
            </p>
            {children}
          </div>
        </div>
      </div>
    </details>
  );
}

export function MeetingCard({
  meeting,
  lang,
  onOpen,
  onTranscribe,
  isEditing = false,
  editTitleValue = '',
  setEditTitleValue = () => {},
  onRename = () => {},
  onSaveRename = () => {},
  onCancelRename = () => {},
  demoMode = false,
}: {
  meeting: Meeting;
  lang: string;
  onOpen: () => void;
  onTranscribe?: () => void;
  isEditing?: boolean;
  editTitleValue?: string;
  setEditTitleValue?: (value: string) => void;
  onRename?: () => void;
  onSaveRename?: () => void;
  onCancelRename?: () => void;
  demoMode?: boolean;
}) {
  const { t } = useTranslation();
  const statusMeta = {
    recording: { label: t('workspace.statusRecording'), variant: 'warning' as const },
    recorded: { label: t('workspace.statusRecorded'), variant: 'idle' as const },
    transcribed: { label: t('workspace.statusTranscribed'), variant: 'info' as const },
    analyzing: { label: t('workspace.statusAnalyzing'), variant: 'warning' as const },
    ready: { label: t('workspace.statusReady'), variant: 'success' as const },
    failed: { label: t('workspace.statusFailed'), variant: 'danger' as const },
  }[meeting.status] || { label: meeting.status, variant: 'idle' as const };

  const duration = getDurationSeconds(meeting.recording);
  const analysisTypes = Object.keys(meeting.latest_analysis || {});
  
  return (
    <article className="metric-card group rounded-xl border border-border-subtle px-4 py-3 transition-premium hover-lift hover:border-border-focus hover:bg-bg-hover">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 flex-1 gap-3">
          <button
            type="button"
            onClick={onOpen}
            className="mt-0.5 hidden h-10 w-10 shrink-0 place-items-center rounded-xl border border-border-subtle bg-bg-glass text-accent shadow-[inset_0_1px_0_var(--surface-highlight)] transition-colors hover:border-border-focus hover:text-accent sm:grid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            title={lang === 'it' ? 'Apri meeting' : 'Open meeting'}
            aria-label={lang === 'it' ? 'Apri meeting' : 'Open meeting'}
          >
            <FileAudio className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {isEditing ? (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center w-full max-w-md" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="text"
                    value={editTitleValue}
                    onChange={(event) => setEditTitleValue(event.target.value)}
                    maxLength={200}
                    className="min-w-0 flex-1 rounded-lg border border-border-focus bg-bg-surface px-3 py-1.5 text-sm text-text-primary outline-none"
                    autoFocus
                  />
                  <div className="flex gap-2 shrink-0">
                    <Button size="sm" onClick={onSaveRename}>{lang === 'it' ? 'Salva' : 'Save'}</Button>
                    <Button size="sm" variant="ghost" onClick={onCancelRename}>{lang === 'it' ? 'Annulla' : 'Cancel'}</Button>
                  </div>
                </div>
              ) : (
                <div className="flex min-w-0 items-center gap-2 group/title">
                  <button
                    type="button"
                    onClick={onOpen}
                    className="truncate text-left text-sm font-semibold text-text-primary transition-colors hover:text-accent focus-visible:outline-none focus-visible:underline"
                    title={lang === 'it' ? 'Apri meeting' : 'Open meeting'}
                  >
                    {meetingTitle(meeting)}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRename();
                    }}
                    disabled={demoMode}
                    className="text-text-muted transition-colors hover:text-text-primary opacity-0 group-hover/title:opacity-100 focus:opacity-100"
                    aria-label={lang === 'it' ? 'Rinomina meeting' : 'Rename meeting'}
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              {!isEditing && <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-text-muted">
              <span className="inline-flex items-center gap-1">
                <CalendarDays className="h-3.5 w-3.5" />
                {formatProjectDate(meeting.created_at, lang)}
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {duration > 0 ? `${Math.round(duration / 60)} min` : t('projects.durationNotAvailable')}
              </span>
              {meeting.project_name && (
                <span className="inline-flex items-center gap-1">
                  <FolderKanban className="h-3.5 w-3.5" />
                  {meeting.project_name}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2 lg:min-w-[200px] lg:items-end">
          <div className="flex flex-wrap gap-1.5 lg:justify-end">
            {meeting.transcription && (
              <span className="inline-flex items-center gap-1 rounded-md border border-success/25 bg-success/10 px-2 py-1 text-[11px] text-success">
                <CheckCircle2 className="h-3 w-3" />
                {t('workspace.transcriptionBadge')}
              </span>
            )}
            {analysisTypes.slice(0, 3).map((type) => (
              <span key={type} className="rounded-md border border-border-subtle bg-bg-surface px-2 py-1 text-[11px] text-text-secondary">
                {ANALYSIS_TYPE_LABELS[type] || type}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto lg:justify-end">
            <Button size="sm" className="flex-1 lg:flex-initial lg:px-4" onClick={onOpen}>
              {lang === 'it' ? 'Apri' : 'Open'}
            </Button>
            {!meeting.transcription && onTranscribe && !demoMode && (
              <Button size="sm" variant="secondary" className="flex-1 lg:flex-initial lg:px-3" onClick={onTranscribe}>
                {lang === 'it' ? 'Trascrivi' : 'Transcribe'}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Action Required Banner inside card */}
      {meeting.status !== 'ready' && meeting.status !== 'recording' && meeting.status !== 'analyzing' && (
        <div className={cn(
          "mt-3 flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-xs text-text-primary animate-in fade-in duration-200",
          !meeting.transcription
            ? "border-warning/20 bg-warning/5"
            : "border-info/20 bg-info/5"
        )}>
          <div className="flex items-center gap-2 min-w-0">
            <AlertTriangle className={cn(
              "h-3.5 w-3.5 shrink-0",
              !meeting.transcription ? "text-warning" : "text-info"
            )} />
            <span className={cn("font-semibold", !meeting.transcription ? "text-warning" : "text-info")}>
              {lang === 'it' ? 'Da completare:' : 'To complete:'}
            </span>
            <span className="truncate text-text-secondary">
              {!meeting.transcription
                ? (lang === 'it' ? 'Trascrizione mancante (richiede Whisper)' : 'Missing transcription (requires Whisper)')
                : (lang === 'it' ? 'Analisi AI / Insight da completare' : 'AI analysis / Insights to complete')}
            </span>
          </div>
        </div>
      )}
    </article>
  );
}

export function ActionChecklist({
  items,
  emptyTitle,
  emptyDescription,
}: {
  items: InsightItem[];
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const { t } = useTranslation();
  const displayEmptyTitle = emptyTitle || t('workspace.emptyActionsTitle');
  const displayEmptyDesc = emptyDescription || t('workspace.emptyActionsDesc');

  if (items.length === 0) {
    return <EmptyState icon={ListChecks} title={displayEmptyTitle} description={displayEmptyDesc} className="py-7" />;
  }
  return (
    <div className="metric-card flex flex-col divide-y divide-border-subtle rounded-xl border border-border-subtle overflow-hidden">
      {items.map((item) => (
        <div key={item.id} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 px-3.5 py-3 transition-premium hover:bg-bg-hover/35">
          <span
            role="checkbox"
            aria-checked={Boolean(item.completed)}
            aria-label={`Stato azione: ${item.text}`}
            title={t('workspace.actionsReadOnly')}
            className={cn(
              'mt-0.5 grid h-5 w-5 place-items-center rounded-md border transition-premium',
              item.completed
                ? 'border-success/40 bg-success/15 text-success'
                : 'border-border-subtle bg-bg-glass text-transparent shadow-[inset_0_1px_0_var(--surface-highlight)]'
            )}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <p className={cn('text-sm leading-snug text-text-primary', item.completed && 'line-through text-text-muted')}>
              {limitText(item.text, 180)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-text-muted">
              {item.projectName && <Badge variant="info">{item.projectName}</Badge>}
              {item.owner && (
                <span className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-bg-glass px-2 py-1">
                  <UserRound className="h-3 w-3" />
                  {item.owner}
                </span>
              )}
              {item.dueDate && <Badge variant="warning">{t('workspace.dueDateLabel')} {item.dueDate}</Badge>}
              {item.priority && <Badge variant={item.priority.toLowerCase().includes('high') || item.priority.toLowerCase().includes('alta') ? 'warning' : 'idle'}>{item.priority}</Badge>}
              <span className="inline-flex rounded-full border border-border-subtle bg-bg-glass px-2 py-1">{item.sourceTitle}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function DecisionLog({
  items,
  emptyTitle,
  emptyDescription,
}: {
  items: InsightItem[];
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const { t, lang } = useTranslation();
  const displayEmptyTitle = emptyTitle || t('workspace.emptyDecisionsTitle');
  const displayEmptyDesc = emptyDescription || t('workspace.emptyDecisionsDesc');

  if (items.length === 0) {
    return <EmptyState icon={MessageSquare} title={displayEmptyTitle} description={displayEmptyDesc} className="py-7" />;
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => (
        <div key={item.id} className="metric-card rounded-xl border border-border-subtle px-3.5 py-2.5 transition-premium hover-lift hover:border-border-focus hover:bg-bg-hover">
          <p className="text-sm leading-snug text-text-primary">{limitText(item.text, 190)}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-text-muted">
            {item.projectName && <span>{item.projectName}</span>}
            <span>{formatProjectDate(item.sourceDate, lang)}</span>
            <span>{item.sourceTitle}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function RiskPanel({
  items,
  emptyTitle,
  emptyDescription,
}: {
  items: InsightItem[];
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const { t } = useTranslation();
  const displayEmptyTitle = emptyTitle || t('workspace.emptyRisksTitle');
  const displayEmptyDesc = emptyDescription || t('workspace.emptyRisksDesc');

  if (items.length === 0) {
    return <EmptyState icon={ShieldAlert} title={displayEmptyTitle} description={displayEmptyDesc} className="py-7" />;
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => (
        <div key={item.id} className="rounded-xl border border-warning/20 bg-warning/5 px-3.5 py-2.5 transition-premium hover:border-warning/35 hover:bg-warning/10">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm leading-snug text-text-primary">{limitText(item.text, 180)}</p>
            {item.severity && <Badge variant="warning">{item.severity}</Badge>}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-text-muted">
            {item.projectName && <span>{item.projectName}</span>}
            <span>{item.sourceTitle}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function DigestPanel({
  items,
  title,
  generatedAt,
}: {
  items: DigestItem[];
  title?: string;
  generatedAt?: string | null;
}) {
  const { t, lang } = useTranslation();
  const displayTitle = title || t('workspace.digestTitle');

  return (
    <section className="insight-panel rounded-2xl p-4 theme-digest">
      <SectionHeader
        icon={Sparkles}
        title={displayTitle}
        description={t('workspace.digestSubtitle')}
        tooltip={t('workspace.digestTooltip')}
      />
      {generatedAt && <p className="mt-1.5 text-[11px] text-text-muted">{lang === 'it' ? 'Situazione aggiornata' : 'Situation updated'}: {generatedAt}</p>}
      {items.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title={t('workspace.digestEmptyTitle')}
          description={t('workspace.digestEmptyDesc')}
          className="mt-3 py-6"
        />
      ) : (
        <div className="mt-3 flex flex-col gap-2.5">
          {items.slice(0, 4).map((item) => (
            <div key={item.id} className="rounded-xl border border-border-subtle bg-bg-glass p-3 shadow-[inset_0_1px_0_var(--surface-highlight)] transition-premium hover:border-accent/30 hover:bg-bg-hover/40">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
                <span>{item.title}</span>
                {item.projectName && <span>{item.projectName}</span>}
                <span>{item.sourceTitle}</span>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-text-secondary">{limitText(item.text, 260)}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function ProjectDigestPanel({
  items,
  generatedAt,
}: {
  items: DigestItem[];
  generatedAt?: string | null;
}) {
  const { t } = useTranslation();
  return <DigestPanel items={items} title={t('workspace.projectDigestTitle')} generatedAt={generatedAt} />;
}

function getInitials(name: string): string {
  const clean = name.replace(/[^\w\s]/g, '').trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return clean.slice(0, 2).toUpperCase() || 'P';
}

export function ProjectSidebar({
  projects,
  selectedName,
  query,
  onQueryChange,
  onSelect,
  isCollapsed = false,
  onToggleCollapse,
}: {
  projects: Project[];
  selectedName: string;
  query: string;
  onQueryChange: (value: string) => void;
  onSelect: (name: string) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const { t } = useTranslation();
  const filtered = projects.filter((project) => project.name.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <aside
      className={cn(
        "surface-primary rounded-2xl lg:sticky lg:top-5 flex flex-col gap-3 transition-all duration-300",
        isCollapsed
          ? "w-[52px] p-2 items-center overflow-hidden"
          : "w-full p-3 h-fit lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto"
      )}
    >
      <div className={cn("px-1 pb-1 w-full", isCollapsed ? "flex flex-col items-center gap-3" : "")}>
        <div className="flex items-center justify-between gap-2 w-full">
          {!isCollapsed && (
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-text-primary">{t('workspace.projectsTitle')}</h2>
              <Tooltip content={t('workspace.projectsDesc')}>
                <span className="cursor-help text-text-muted hover:text-text-primary transition-colors">
                  <Info className="h-3.5 w-3.5" />
                </span>
              </Tooltip>
            </div>
          )}
          {onToggleCollapse && (
            <button
              type="button"
              onClick={onToggleCollapse}
              className={cn(
                "p-1.5 rounded-lg border border-border-subtle bg-bg-glass text-text-muted hover:text-text-primary hover:border-border-focus transition-all flex items-center justify-center",
                isCollapsed ? "mx-auto" : ""
              )}
              title={isCollapsed ? t('projects.expandSidebar') || 'Espandi' : t('projects.collapseSidebar') || 'Riduci'}
            >
              {isCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
        {!isCollapsed && (
          <label className="mt-3 flex h-9 items-center gap-2 rounded-lg border border-border-subtle bg-bg-glass px-3 shadow-[inset_0_1px_0_var(--surface-highlight)] w-full">
            <Search className="h-4 w-4 text-text-muted" />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder={t('workspace.searchPlaceholder')}
              className="min-w-0 flex-1 border-0 bg-transparent text-xs text-text-primary outline-none placeholder:text-text-muted"
            />
          </label>
        )}
      </div>
      <div className={cn("stagger-list flex flex-col gap-1 w-full", isCollapsed ? "items-center" : "")}>
        {filtered.map((project) => {
          const initials = getInitials(project.name);
          const isSelected = selectedName === project.name;
          if (isCollapsed) {
            return (
              <Tooltip key={project.name} content={`${project.name} (${project.items.length} meeting)`}>
                <button
                  type="button"
                  onClick={() => onSelect(project.name)}
                  className={cn(
                    'h-10 w-10 flex items-center justify-center rounded-xl border text-xs font-bold transition-premium shrink-0',
                    isSelected
                      ? 'primary-gradient-surface border-white/15 text-white shadow-[0_4px_12px_rgba(61,125,255,0.25)]'
                      : 'border-transparent bg-bg-glass text-text-secondary hover:border-border-subtle hover:bg-bg-hover hover:text-text-primary'
                  )}
                >
                  {initials}
                </button>
              </Tooltip>
            );
          }
          return (
            <button
              key={project.name}
              type="button"
              onClick={() => onSelect(project.name)}
              className={cn(
                'rounded-xl border px-3 py-2 text-left transition-premium w-full shrink-0',
                isSelected
                  ? 'primary-gradient-surface border-white/15 text-white shadow-[0_4px_12px_rgba(61,125,255,0.25)]'
                  : 'border-transparent text-text-secondary hover:border-border-subtle hover:bg-bg-hover hover:text-text-primary'
              )}
            >
              <span className="block truncate text-sm font-medium">{project.name}</span>
              <span className={cn('mt-0.5 block text-[11px]', isSelected ? 'text-white/75' : 'text-text-muted')}>
                {project.items.length} meeting
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export function ProjectStatusPanel({
  meetingCount,
  transcribedCount,
  readyCount,
  actionCount,
  decisionCount,
  riskCount,
}: {
  meetingCount: number;
  transcribedCount: number;
  readyCount: number;
  actionCount: number;
  decisionCount: number;
  riskCount: number;
}) {
  const { t } = useTranslation();
  const stats = [
    { label: t('workspace.statMeetings'), value: meetingCount, icon: FileAudio, color: 'text-accent', bgColor: 'bg-accent/10 border-accent/20' },
    { label: t('workspace.statTranscribed'), value: transcribedCount, icon: CheckCircle2, color: 'text-info', bgColor: 'bg-info/10 border-info/20' },
    { label: t('workspace.statWithInsights'), value: readyCount, icon: Sparkles, color: 'text-accent', bgColor: 'bg-accent/10 border-accent/20' },
    { label: t('workspace.statOpenActions'), value: actionCount, icon: ListChecks, color: 'text-success', bgColor: 'bg-success/10 border-success/20' },
    { label: t('workspace.statDecisions'), value: decisionCount, icon: Target, color: 'text-info', bgColor: 'bg-info/10 border-info/20' },
    { label: t('workspace.statRisks'), value: riskCount, icon: ShieldAlert, color: 'text-warning', bgColor: 'bg-warning/10 border-warning/20' },
  ];
  return (
    <section className="stagger-list grid grid-cols-2 gap-3 lg:grid-cols-3">
      {stats.map((stat) => (
        <div key={stat.label} className="metric-card group relative overflow-hidden rounded-xl border border-border-subtle p-3.5 transition-premium hover-lift hover:border-border-focus hover:bg-bg-hover hover:shadow-[0_8px_24px_rgba(0,0,0,0.1)]">
          <div className="absolute -right-6 -top-6 h-12 w-12 rounded-full bg-accent/5 blur-lg transition-all duration-500 group-hover:scale-150" />
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase text-text-muted transition-colors group-hover:text-text-secondary">{stat.label}</span>
            <span className={`inline-flex items-center justify-center rounded-lg border p-1 ${stat.bgColor}`}>
              <stat.icon className={`h-3.5 w-3.5 ${stat.color}`} />
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-1">
            <div className="text-2xl font-bold text-text-primary">{stat.value}</div>
          </div>
        </div>
      ))}
    </section>
  );
}

export function AnalysisCTAButton({
  onClick,
  disabled,
  isGenerated,
}: {
  onClick: () => void;
  disabled?: boolean;
  isGenerated?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Tooltip content={t('workspace.digestCtaTooltip')}>
      <span>
        <Button size="lg" onClick={onClick} disabled={disabled} className="w-full sm:w-auto">
          <Sparkles className="h-5 w-5" />
          {isGenerated ? t('workspace.digestCtaUpdate') : t('workspace.digestCtaGenerate')}
        </Button>
      </span>
    </Tooltip>
  );
}
