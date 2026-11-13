import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  Edit3,
  FileAudio,
  FolderKanban,
  History,
  ListChecks,
  Menu,
  Mic,
  ShieldAlert,
  Sparkles,
  Target,
  X,
} from 'lucide-react';
import { ApiClient, Project, ProjectItem, Recording } from '../api/apiClient';
import { NEW_RECORDING_PROJECT_STORAGE_KEY } from '../api/config';
import { getDemoProjects } from '../features/demo/demoData';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ProjectPromptModal } from '../components/ui/ProjectPromptModal';
import { TimeRangeFilter } from '../components/workspace/TimeRangeFilter';
import { InsightDetailDialog, type InsightTab } from '../components/workspace/InsightDetailDialog';
import {
  ActionChecklist,
  AdvancedDetailsAccordion,
  DecisionLog,
  EmptyState,
  ProjectSidebar,
  RiskPanel,
  SectionHeader,
} from '../components/workspace/MeetingWorkspace';
import {
  TimeRangeState,
  extractActionItems,
  extractDecisions,
  extractDigest,
  extractRisks,
  formatTimeRangeLabel,
  isWithinTimeRange,
  projectItemHasAnalysis,
  projectItemStatus,
  recordingTitle,
  resolveTimeRange,
  sortByNewest,
  sourceFromProjectItem,
  uniqueInsightItems,
} from '../utils/meetingInsights';
import { formatDuration, formatProjectDate, getDurationSeconds } from '../utils/formatters';
import { cn } from '../utils/cn';
function limitText(value: string, max = 150): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}...`;
}

interface ProjectsPageProps {
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
}



const PROJECT_VIEW_STORAGE_KEY = 'closedroom.projects.view';
// Ephemeral, in-memory view snapshot. The backend remains the canonical project owner.
// Show it immediately on return and always reconcile against the local API.
let projectViewSnapshot: Project[] | null = null;

function restoreProjectView(): { name: string; range: TimeRangeState; query: string; showAll: boolean } {
  const fallback = { name: '', range: { mode: 'all' } as TimeRangeState, query: '', showAll: false };
  try {
    const raw = sessionStorage.getItem(PROJECT_VIEW_STORAGE_KEY);
    if (!raw) return fallback;
    const saved: unknown = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return fallback;
    const data = saved as Record<string, unknown>;
    const range = data.range && typeof data.range === 'object' ? data.range as Record<string, unknown> : null;
    const mode = range && ['last7', 'last30', 'all', 'custom'].includes(String(range.mode)) ? String(range.mode) : 'all';
    const validRange = {
      mode,
      ...(range?.startDate && typeof range.startDate === 'string' ? { startDate: range.startDate } : {}),
      ...(range?.endDate && typeof range.endDate === 'string' ? { endDate: range.endDate } : {}),
    } as TimeRangeState;
    return {
      name: typeof data.name === 'string' ? data.name : '',
      range: validRange,
      query: typeof data.query === 'string' ? data.query.slice(0, 200) : '',
      showAll: data.showAll === true,
    };
  } catch {
    return fallback;
  }
}

export default function ProjectsPage({ navigateTo, demoMode = false }: ProjectsPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const savedProjectView = useMemo(restoreProjectView, []);
  const [loading, setLoading] = useState(() => !demoMode && projectViewSnapshot === null);
  const [projects, setProjects] = useState<Project[]>(() =>
    demoMode ? getDemoProjects(lang) : (projectViewSnapshot ?? [])
  );
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const [selectedProjectName, setSelectedProjectName] = useState(savedProjectView.name);
  const [sidebarQuery, setSidebarQuery] = useState(savedProjectView.query);
  const [projectRange, setProjectRange] = useState<TimeRangeState>(savedProjectView.range);
  const [editingRecordingId, setEditingRecordingId] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [activeRecordingForProject, setActiveRecordingForProject] = useState<Recording | null>(null);
  const [existingProjectsList, setExistingProjectsList] = useState<string[]>([]);
  const [showAllTimeline, setShowAllTimeline] = useState(savedProjectView.showAll);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => localStorage.getItem('projects_sidebar_collapsed') === 'true');
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);

  const handleToggleSidebar = () => {
    setIsSidebarCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem('projects_sidebar_collapsed', String(next));
      return next;
    });
  };

  // Insight dialog state
  const [insightDialogOpen, setInsightDialogOpen] = useState(false);
  const [insightDialogTab, setInsightDialogTab] = useState<InsightTab>('actions');

  const openInsightDialog = (tab: InsightTab) => {
    setInsightDialogTab(tab);
    setInsightDialogOpen(true);
  };

  const projectRangeOptions = useMemo(() => [
    { mode: 'last7' as const, label: '7g' },
    { mode: 'last30' as const, label: '30g' },
    { mode: 'all' as const, label: lang === 'it' ? 'Tutto' : 'All' },
    { mode: 'custom' as const, label: lang === 'it' ? 'Custom' : 'Custom' },
  ], [lang]);

  const loadProjects = async () => {
    const generation = ++requestGeneration.current;
    setRefreshError(null);
    if (demoMode) {
      setProjects(getDemoProjects(lang));
      setSelectedProjectName('ClosedRoom Beta Launch');
      setLoading(false);
      setRefreshing(false);
      return;
    }

    // Do not remount the heavy route loader for a previously explored project.
    // All reads and refreshes still go to the local canonical /v1/projects API.
    if (projectViewSnapshot !== null) {
      setProjects(projectViewSnapshot);
      setLoading(false);
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const response = await ApiClient.listProjects();
      if (generation !== requestGeneration.current) return;
      const items = response.items || [];
      projectViewSnapshot = items;
      setProjects(items);
    } catch (err: unknown) {
      if (generation !== requestGeneration.current) return;
      const message = err instanceof Error ? err.message : String(err);
      setRefreshError(message);
      if (projectViewSnapshot === null) {
        showToast(message || t('projects.loading') || 'Errore', 'error');
      }
    } finally {
      if (generation === requestGeneration.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  };

  useEffect(() => {
    void loadProjects();
    return () => { requestGeneration.current += 1; };
  }, [demoMode, lang]);

  useEffect(() => {
    if (loading) return; // Wait for the canonical project list before validating a restored selection.
    if (projects.length === 0) {
      setSelectedProjectName('');
      return;
    }
    if (!selectedProjectName || !projects.some((project) => project.name === selectedProjectName)) {
      setSelectedProjectName(projects[0].name);
    }
  }, [projects, selectedProjectName, loading]);

  // The Projects view alone owns its ephemeral selection and time filters.
  // Restoring a Meeting's origin never creates a second route or persistence owner.
  useEffect(() => {
    if (loading || demoMode) return;
    sessionStorage.setItem(PROJECT_VIEW_STORAGE_KEY, JSON.stringify({
      name: selectedProjectName,
      range: projectRange,
      query: sidebarQuery,
      showAll: showAllTimeline,
    }));
  }, [loading, demoMode, selectedProjectName, projectRange, sidebarQuery, showAllTimeline]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.name === selectedProjectName) || projects[0],
    [projects, selectedProjectName]
  );

  const resolvedProjectRange = useMemo(() => resolveTimeRange(projectRange), [projectRange]);
  const projectRangeLabel = useMemo(() => formatTimeRangeLabel(projectRange, lang), [projectRange, lang]);

  const periodItems = useMemo(() => {
    if (!selectedProject) return [];
    return selectedProject.items.filter((item) => isWithinTimeRange(item.recording.created_at, resolvedProjectRange));
  }, [selectedProject, resolvedProjectRange]);

  const sources = useMemo(
    () => selectedProject ? periodItems.map((item) => sourceFromProjectItem(item, selectedProject.name)) : [],
    [periodItems, selectedProject]
  );

  const actionItemsAll = useMemo(
    () => sortByNewest(uniqueInsightItems(sources.flatMap(extractActionItems))).filter((item) => !item.completed),
    [sources]
  );
  const decisions = useMemo(
    () => sortByNewest(uniqueInsightItems(sources.flatMap(extractDecisions))),
    [sources]
  );
  const risks = useMemo(
    () => sortByNewest(uniqueInsightItems(sources.flatMap(extractRisks))),
    [sources]
  );
  const digestItems = useMemo(
    () => sortByNewest(sources.map(extractDigest).filter((item): item is NonNullable<typeof item> => Boolean(item))),
    [sources]
  );

  const actionItems = actionItemsAll;

  const visibleTimelineItems = useMemo(
    () => showAllTimeline ? periodItems : periodItems.slice(0, 12),
    [periodItems, showAllTimeline]
  );

  const handleRenameClick = (recording: Recording) => {
    if (demoMode) return;
    setEditingRecordingId(recording.id);
    setEditTitleValue(recording.title);
  };

  const handleSaveRename = async (recording: Recording) => {
    if (demoMode) return;
    const title = editTitleValue.trim();
    if (!title) {
      showToast(t('transcription.titleEmptyError'), 'error');
      return;
    }
    try {
      await ApiClient.updateRecording(recording.id, { title });
      showToast(t('transcription.titleSaveSuccess'), 'success');
      setEditingRecordingId(null);
      loadProjects();
    } catch (err: any) {
      showToast(t('transcription.titleSaveError', { error: err.message }), 'error');
    }
  };

  const handleAssignProject = async (recording: Recording) => {
    if (demoMode) {
      showToast(t('dashboard.toastDemoNoModify'), 'info');
      return;
    }
    let list: string[] = [];
    try {
      const projsData = await ApiClient.listProjects();
      list = (projsData.items || [])
        .filter((project) => !project.is_unassigned)
        .map((project) => project.name);
    } catch {}

    setExistingProjectsList(list);
    setActiveRecordingForProject(recording);
    setIsProjectModalOpen(true);
  };

  const handleConfirmProject = async (projectName: string) => {
    if (demoMode) return;
    if (!activeRecordingForProject) return;
    try {
      await ApiClient.updateRecording(activeRecordingForProject.id, { project_name: projectName });
      showToast(t('transcription.projectUpdateSuccess'), 'success');
      setIsProjectModalOpen(false);
      setActiveRecordingForProject(null);
      loadProjects();
    } catch (err: any) {
      showToast(t('transcription.projectUpdateError', { error: err.message }), 'error');
    }
  };

  const handleNewMeetingForProject = () => {
    if (demoMode) {
      showToast(t('dashboard.toastDemoNoRecord'), 'info');
      return;
    }
    if (selectedProject && !selectedProject.is_unassigned) {
      sessionStorage.setItem(NEW_RECORDING_PROJECT_STORAGE_KEY, selectedProject.name);
    }
    navigateTo('recording');
  };

  if (loading) {
    return (
      <div role="status" aria-live="polite" aria-busy="true" className="surface-supporting rounded-xl px-4 py-5 text-sm text-text-secondary">
        {lang === 'it' ? 'Caricamento elenco progetti dal dispositivo…' : 'Loading projects from this device…'}
      </div>
    );
  }

  if (!selectedProject && refreshError && !demoMode) {
    return (
      <div role="alert" className="surface-supporting flex flex-wrap items-center gap-3 rounded-xl p-4 text-sm text-text-secondary">
        <span>{lang === 'it' ? 'Impossibile leggere i progetti locali.' : 'Could not load local projects.'}</span>
        <Button size="sm" variant="secondary" onClick={() => void loadProjects()}>
          {lang === 'it' ? 'Riprova' : 'Retry'}
        </Button>
      </div>
    );
  }

  if (!selectedProject) {
    return (
      <EmptyState
        icon={FolderKanban}
        title={t('projects.empty')}
        description={lang === 'it' ? 'Assegna un progetto a un meeting o crea una nuova registrazione per iniziare.' : 'Assign a project to a meeting or create a new recording to start.'}
        action={<Button onClick={() => navigateTo('recording')}>{lang === 'it' ? 'Registra meeting' : 'Record meeting'}</Button>}
      />
    );
  }

  const readyCount = periodItems.filter(projectItemHasAnalysis).length;

  return (
    <>
      {/* Mobile Drawer Overlay */}
      {isMobileDrawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300"
            onClick={() => setIsMobileDrawerOpen(false)}
          />
          {/* Drawer Content */}
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-bg-elevated p-4 shadow-2xl transition-transform duration-300 flex flex-col gap-4 animate-in slide-in-from-left duration-200">
            <div className="flex items-center justify-between border-b border-border-subtle pb-3">
              <div className="flex items-center gap-2 text-sm font-bold text-text-primary">
                <FolderKanban className="h-4 w-4 text-accent" />
                <span>{t('workspace.projectsTitle')}</span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setIsMobileDrawerOpen(false)} className="h-8 w-8 text-text-muted hover:text-text-primary flex items-center justify-center p-0">
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0 pr-1">
              <ProjectSidebar
                projects={projects}
                selectedName={selectedProject.name}
                query={sidebarQuery}
                onQueryChange={setSidebarQuery}
                onSelect={(name) => {
                  setSelectedProjectName(name);
                  setIsMobileDrawerOpen(false);
                }}
                isCollapsed={false}
              />
            </div>
          </div>
        </div>
      )}

      <div className={cn(
        "grid grid-cols-1 gap-6 animate-page-in transition-all duration-300",
        isSidebarCollapsed ? "lg:grid-cols-[52px_minmax(0,1fr)]" : "lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start"
      )}>
        {/* Desktop Sidebar */}
        <div className={cn("hidden lg:block", !isSidebarCollapsed && "lg:self-start")} data-tour="project-sidebar">
          <ProjectSidebar
            projects={projects}
            selectedName={selectedProject.name}
            query={sidebarQuery}
            onQueryChange={setSidebarQuery}
            onSelect={setSelectedProjectName}
            isCollapsed={isSidebarCollapsed}
            onToggleCollapse={handleToggleSidebar}
          />
        </div>

        <main className="flex min-w-0 flex-col gap-6">
          {/* Compact Hero Bar */}
          <section className="surface-primary rounded-2xl p-4 sm:p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4" data-tour="project-situation">
            <div className="min-w-0 flex items-start gap-3">
              <Button
                variant="ghost"
                size="sm"
                className="lg:hidden shrink-0 h-9 w-9 border border-border-subtle bg-bg-glass text-text-muted hover:text-text-primary flex items-center justify-center p-0"
                onClick={() => setIsMobileDrawerOpen(true)}
                title={t('workspace.projectsTitle')}
              >
                <Menu className="h-4 w-4" />
              </Button>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold uppercase text-accent">{t('projects.projectLabel')}</span>
                  <Badge variant={readyCount > 0 ? 'success' : 'info'}>{projectRangeLabel}</Badge>
                </div>
                <h2 className="mt-1.5 break-words text-xl font-bold text-text-primary">
                  {selectedProject.name}
                </h2>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="bg-bg-glass/30 border border-border-subtle rounded-xl p-1">
                <TimeRangeFilter value={projectRange} options={projectRangeOptions} onChange={setProjectRange} className="flex-row gap-0" />
              </div>
              <Button size="sm" variant="secondary" onClick={handleNewMeetingForProject} disabled={demoMode}>
                <Mic className="h-4 w-4" />
                {lang === 'it' ? 'Nuovo meeting nel progetto' : 'New meeting in project'}
              </Button>
            </div>
          </section>

        {refreshing && (
          <p role="status" className="text-xs text-text-muted">
            {lang === 'it' ? 'Aggiornamento progetti dal dispositivo…' : 'Refreshing projects from this device…'}
          </p>
        )}
        {refreshError && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-border-subtle px-3 py-2 text-xs text-text-secondary">
            <span>{lang === 'it' ? 'Dati precedenti: aggiornamento non riuscito.' : 'Showing previous data: refresh failed.'}</span>
            <Button size="sm" variant="secondary" onClick={() => void loadProjects()}>
              {lang === 'it' ? 'Riprova' : 'Retry'}
            </Button>
          </div>
        )}

        {/* Timeline of meetings - full width */}
        <section className="surface-supporting flex flex-col gap-3 rounded-2xl p-4" data-tour="project-timeline">
          <SectionHeader
            icon={History}
            title={t('projects.timelineTitle')}
            description={t('projects.timelineDesc')}
            action={
              periodItems.length > 12 && (
                <button
                  type="button"
                  onClick={() => setShowAllTimeline(!showAllTimeline)}
                  className="view-all-link text-xs font-semibold text-accent hover:text-accent/80 transition-colors"
                >
                  {showAllTimeline
                    ? (lang === 'it' ? 'Mostra meno' : 'Show less')
                    : `${lang === 'it' ? 'Mostra tutti' : 'Show all'} (${periodItems.length})`}
                </button>
              )
            }
          />
          {periodItems.length === 0 ? (
            <EmptyState
              icon={FileAudio}
              title={t('projects.emptyTimelineTitle')}
              description={t('projects.emptyTimelineDesc')}
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border-subtle bg-bg-glass shadow-[var(--shadow-soft)]">
              {visibleTimelineItems.map((item) => (
                <ProjectTimelineItem
                  key={item.recording.id}
                  item={item}
                  lang={lang}
                  isEditing={editingRecordingId === item.recording.id}
                  editTitleValue={editTitleValue}
                  setEditTitleValue={setEditTitleValue}
                  onRename={() => handleRenameClick(item.recording)}
                  onSaveRename={() => handleSaveRename(item.recording)}
                  onCancelRename={() => setEditingRecordingId(null)}
                  onAssignProject={() => handleAssignProject(item.recording)}
                  onOpen={() => navigateTo('meeting', item.recording.id)}
                  demoMode={demoMode}
                />
              ))}
            </div>
          )}
        </section>

        <p className="text-xs text-text-muted" data-tour="project-status">
          {periodItems.length} {lang === 'it' ? 'meeting' : 'meetings'} · {readyCount} {lang === 'it' ? 'analizzati' : 'analyzed'}
        </p>

        {periodItems.length > 0 && readyCount === 0 && (
          <p className="text-xs text-text-muted">
            {lang === 'it'
              ? 'I meeting sono disponibili qui sopra. Azioni, decisioni e rischi appariranno dopo un’analisi del meeting.'
              : 'Meetings are available above. Actions, decisions and risks will appear after meeting analysis.'}
          </p>
        )}

        {/* Project insights are a projection of existing meeting analyses; no fake AI task. */}
        {digestItems.length > 0 && (
          <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
            <SectionHeader
              icon={Sparkles}
              title={t('workspace.projectDigestTitle')}
              description={t('workspace.digestSubtitle')}
              tooltip={t('workspace.digestTooltip')}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {digestItems.slice(0, 4).map((item) => (
                <div key={item.id} className="rounded-xl border border-border-subtle bg-bg-glass p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-text-muted">
                    <span>{item.title}</span>
                    <span>{item.sourceTitle}</span>
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">{limitText(item.text, 220)}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Actions - full width */}
        {actionItems.length > 0 && <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4" data-tour="project-actions">
          <SectionHeader
            icon={ListChecks}
            title={t('projects.actionsTitle')}
            description={t('projects.actionsDesc')}
            action={
              actionItems.length > 5 ? (
                <button type="button" onClick={() => openInsightDialog('actions')} className="view-all-link">
                  {t('demo.viewAll')} ({actionItems.length})
                </button>
              ) : undefined
            }
          />
          <ActionChecklist items={actionItems.slice(0, 5)} />
        </section>}

        {/* Decisions and Risks Side-by-Side */}
        {(decisions.length > 0 || risks.length > 0) && <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {decisions.length > 0 && <div className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
            <SectionHeader
              icon={Target}
              title={t('projects.decisionsTitle')}
              description={t('projects.decisionsDesc')}
              action={
                decisions.length > 4 ? (
                  <button type="button" onClick={() => openInsightDialog('decisions')} className="view-all-link">
                    {t('demo.viewAll')} ({decisions.length})
                  </button>
                ) : undefined
              }
            />
            <DecisionLog items={decisions.slice(0, 4)} />
          </div>}

          {risks.length > 0 && <div className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
            <SectionHeader
              icon={ShieldAlert}
              title={t('projects.risksTitle')}
              description={t('projects.risksDesc')}
              action={
                risks.length > 4 ? (
                  <button type="button" onClick={() => openInsightDialog('risks')} className="view-all-link">
                    {t('demo.viewAll')} ({risks.length})
                  </button>
                ) : undefined
              }
            />
            <RiskPanel items={risks.slice(0, 4)} />
          </div>}
        </div>}

        {/* Advanced details at the bottom */}
        <div className="mt-2">
          <AdvancedDetailsAccordion>
            <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-2 text-xs">
              <dt className="text-text-muted">{t('projects.techTotalMeetings')}</dt>
              <dd className="text-text-secondary">{selectedProject.items.length}</dd>
              <dt className="text-text-muted">{t('projects.techInRange')}</dt>
              <dd className="text-text-secondary">{periodItems.length}</dd>
              <dt className="text-text-muted">{t('projects.techAnalysisRuns')}</dt>
              <dd className="text-text-secondary">
                {periodItems.reduce((count, item) => count + (item.analysis_runs?.length || 0), 0)}
              </dd>
              <dt className="text-text-muted">{t('projects.techRange')}</dt>
              <dd className="truncate text-text-secondary">{projectRangeLabel}</dd>
            </dl>
          </AdvancedDetailsAccordion>
        </div>
      </main>

      <ProjectPromptModal
        isOpen={isProjectModalOpen}
        initialValue={activeRecordingForProject?.project_name || ''}
        onConfirm={handleConfirmProject}
        onCancel={() => {
          setIsProjectModalOpen(false);
          setActiveRecordingForProject(null);
        }}
        existingProjects={existingProjectsList}
      />

      {/* Insight detail dialog — progressive disclosure */}
      <InsightDetailDialog
        open={insightDialogOpen}
        onOpenChange={setInsightDialogOpen}
        initialTab={insightDialogTab}
        actions={actionItemsAll}
        decisions={decisions}
        risks={risks}
      />
    </div>
    </>
  );
}

function ProjectTimelineItem({
  item,
  lang,
  isEditing,
  editTitleValue,
  setEditTitleValue,
  onRename,
  onSaveRename,
  onCancelRename,
  onAssignProject,
  onOpen,
  demoMode,
}: {
  item: ProjectItem;
  lang: string;
  isEditing: boolean;
  editTitleValue: string;
  setEditTitleValue: (value: string) => void;
  onRename: () => void;
  onSaveRename: () => void;
  onCancelRename: () => void;
  onAssignProject: () => void;
  onOpen: () => void;
  demoMode?: boolean;
}) {
  const status = projectItemStatus(item);
  const duration = getDurationSeconds(item.recording);
  const statusMeta = {
    recorded: { label: lang === 'it' ? 'Da trascrivere' : 'To transcribe', variant: 'warning' as const },
    transcribed: { label: lang === 'it' ? 'Da analizzare' : 'To analyze', variant: 'info' as const },
    ready: { label: lang === 'it' ? 'Insight pronti' : 'Insights ready', variant: 'success' as const },
  }[status];

  return (
    <div className="grid grid-cols-1 gap-3 border-b border-border-subtle px-4 py-3 last:border-b-0 lg:grid-cols-[minmax(0,1fr)_180px_220px] lg:items-center">
      <div className="min-w-0">
        {isEditing ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="text"
              value={editTitleValue}
              onChange={(event) => setEditTitleValue(event.target.value)}
              maxLength={200}
              className="min-w-0 rounded-lg border border-border-focus bg-bg-surface px-3 py-2 text-sm text-text-primary outline-none"
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={onSaveRename}>{lang === 'it' ? 'Salva' : 'Save'}</Button>
              <Button size="sm" variant="ghost" onClick={onCancelRename}>{lang === 'it' ? 'Annulla' : 'Cancel'}</Button>
            </div>
          </div>
        ) : (
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-text-primary">{recordingTitle(item.recording)}</h3>
            <button
              type="button"
              onClick={onRename}
              disabled={demoMode}
              className="text-text-muted transition-colors hover:text-text-primary"
              aria-label={lang === 'it' ? 'Rinomina meeting' : 'Rename meeting'}
            >
              <Edit3 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-text-muted">
          <span>{formatProjectDate(item.recording.created_at, lang)}</span>
          <span>{formatDuration(duration, (key, options) => {
            if (key === 'recording.durationNotAvailable') return lang === 'it' ? 'Durata n/d' : 'Duration n/a';
            if (key === 'recording.durationFormat') return `${options.mins}m ${options.secs}s`;
            return key;
          })}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
        {item.transcription && <CheckCircle2 className="h-4 w-4 text-success" />}
        {projectItemHasAnalysis(item) && <Sparkles className="h-4 w-4 text-accent" />}
      </div>
      <div className="flex flex-wrap gap-2 lg:justify-end">
        <Button size="sm" onClick={onOpen} aria-label={`${lang === 'it' ? 'Apri meeting' : 'Open meeting'}: ${recordingTitle(item.recording)}`}>
          {lang === 'it' ? 'Apri' : 'Open'}
        </Button>
        {!demoMode && (
          <Button size="sm" variant="ghost" onClick={onAssignProject}>
            {lang === 'it' ? 'Progetto' : 'Project'}
          </Button>
        )}
      </div>
    </div>
  );
}
