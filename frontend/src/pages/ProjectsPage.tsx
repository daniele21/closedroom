import { useEffect, useMemo, useState } from 'react';
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
import { TaskProcessingLoader } from '../components/workspace/TaskProcessingLoader';
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
import { recordingTranscriptionRoute } from '../utils/transcriptionRoute';
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
import { formatBytes, formatDuration, formatProjectDate, getDurationSeconds } from '../utils/formatters';
import { cn } from '../utils/cn';
function limitText(value: string, max = 150): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}...`;
}

interface ProjectsPageProps {
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
}



const ACTION_SCOPE_OPTIONS = [
  { value: 'week', label: 'Settimana' },
  { value: 'month', label: 'Mese' },
  { value: 'all', label: 'Tutte' },
] as const;

type ActionScope = typeof ACTION_SCOPE_OPTIONS[number]['value'];

const PROJECT_VIEW_STORAGE_KEY = 'closedroom.projects.view';

function restoreProjectView(): { name: string; range: TimeRangeState; actionScope: ActionScope } {
  const fallback = { name: '', range: { mode: 'last7' } as TimeRangeState, actionScope: 'week' as ActionScope };
  try {
    const raw = sessionStorage.getItem(PROJECT_VIEW_STORAGE_KEY);
    if (!raw) return fallback;
    const saved: unknown = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return fallback;
    const data = saved as Record<string, unknown>;
    const range = data.range && typeof data.range === 'object' ? data.range as Record<string, unknown> : null;
    const mode = range && ['last7', 'last30', 'all', 'custom'].includes(String(range.mode)) ? String(range.mode) : 'last7';
    const validRange = {
      mode,
      ...(range?.startDate && typeof range.startDate === 'string' ? { startDate: range.startDate } : {}),
      ...(range?.endDate && typeof range.endDate === 'string' ? { endDate: range.endDate } : {}),
    } as TimeRangeState;
    return {
      name: typeof data.name === 'string' ? data.name : '',
      range: validRange,
      actionScope: ['week', 'month', 'all'].includes(String(data.actionScope)) ? data.actionScope as ActionScope : 'week',
    };
  } catch {
    return fallback;
  }
}

export default function ProjectsPage({ navigateTo, demoMode = false }: ProjectsPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const savedProjectView = useMemo(restoreProjectView, []);
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectName, setSelectedProjectName] = useState(savedProjectView.name);
  const [sidebarQuery, setSidebarQuery] = useState('');
  const [projectRange, setProjectRange] = useState<TimeRangeState>(savedProjectView.range);
  const [actionScope, setActionScope] = useState<ActionScope>(savedProjectView.actionScope);
  const [projectDigestGeneratedAt, setProjectDigestGeneratedAt] = useState<string | null>(null);
  const [isProjectGenerating, setIsProjectGenerating] = useState(false);
  const [editingRecordingId, setEditingRecordingId] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [activeRecordingForProject, setActiveRecordingForProject] = useState<Recording | null>(null);
  const [existingProjectsList, setExistingProjectsList] = useState<string[]>([]);
  const [showAllTimeline, setShowAllTimeline] = useState(false);
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

  const actionScopeOptions = useMemo(() => [
    { value: 'week' as const, label: lang === 'it' ? 'Settimana' : 'Week' },
    { value: 'month' as const, label: lang === 'it' ? 'Mese' : 'Month' },
    { value: 'all' as const, label: lang === 'it' ? 'Tutte' : 'All' },
  ], [lang]);

  const loadProjects = async () => {
    try {
      setLoading(true);
      if (demoMode) {
        setProjects(getDemoProjects(lang));
        setSelectedProjectName('ClosedRoom Beta Launch');
        return;
      }
      const data = await ApiClient.listProjects();
      setProjects(data.items || []);
    } catch (err: any) {
      if (demoMode) {
        setProjects(getDemoProjects(lang));
        setSelectedProjectName('ClosedRoom Beta Launch');
        return;
      }
      showToast(err.message || t('projects.loading') || 'Errore', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProjects();
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
      actionScope,
    }));
  }, [loading, demoMode, selectedProjectName, projectRange, actionScope]);

  useEffect(() => {
    setProjectDigestGeneratedAt(null);
    setIsProjectGenerating(false);
  }, [selectedProjectName, projectRange.mode, projectRange.startDate, projectRange.endDate]);

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

  const actionScopeRange = useMemo(() => {
    if (actionScope === 'week') return resolveTimeRange({ mode: 'last7' });
    if (actionScope === 'month') return resolveTimeRange({ mode: 'last30' });
    return resolveTimeRange({ mode: 'all' });
  }, [actionScope]);
  const actionItems = useMemo(
    () => actionItemsAll.filter((item) => isWithinTimeRange(item.sourceDate, actionScopeRange)),
    [actionItemsAll, actionScopeRange]
  );

  const visibleTimelineItems = useMemo(
    () => showAllTimeline ? periodItems : periodItems.slice(0, 3),
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

  const handleGenerateProjectSituation = () => {
    const insightCount = digestItems.length + actionItemsAll.length + decisions.length + risks.length;
    setIsProjectGenerating(true);
    window.setTimeout(() => {
      const timestamp = new Date().toLocaleString(lang === 'it' ? 'it-IT' : 'en-US', {
        dateStyle: 'short',
        timeStyle: 'short',
      });
      setProjectDigestGeneratedAt(timestamp);
      setIsProjectGenerating(false);
      showToast(
        insightCount > 0
          ? t('projects.toastDigestSuccess')
          : t('projects.toastDigestEmpty'),
        insightCount > 0 ? 'success' : 'info'
      );
    }, 850);
  };

  if (loading) {
    return (
      <div className="py-16">
        <TaskProcessingLoader
          title={t('workspace.loaderProjectsTitle')}
          description={t('workspace.loaderProjectsDesc')}
          steps={[t('workspace.loaderProjectsStep1'), t('workspace.loaderProjectsStep2'), t('workspace.loaderProjectsStep3')]}
          activeStep={1}
          progress={62}
          variant="project"
          helperText={t('workspace.loaderLocalHelper')}
        />
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
                {t('projects.btnNewMeetingShort') || 'Registra'}
              </Button>
            </div>
          </section>

        {/* Compact project status KPIs */}
        {periodItems.length > 0 && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-tour="project-status">
            <button
              type="button"
              onClick={() => {
                const timelineSec = document.querySelector('[data-tour="project-timeline"]');
                timelineSec?.scrollIntoView({ behavior: 'smooth' });
              }}
              className="surface-primary hover:border-border-focus p-4 rounded-xl text-left transition-premium hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(0,0,0,0.1)]"
            >
              <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">{lang === 'it' ? 'Meeting' : 'Meetings'}</div>
              <div className="mt-1 text-2xl font-bold text-accent">{periodItems.length}</div>
            </button>

            <button
              type="button"
              onClick={() => openInsightDialog('actions')}
              className="surface-primary hover:border-border-focus p-4 rounded-xl text-left transition-premium hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(0,0,0,0.1)]"
            >
              <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">{lang === 'it' ? 'Azioni aperte' : 'Open actions'}</div>
              <div className="mt-1 text-2xl font-bold text-success">{actionItemsAll.length}</div>
            </button>

            <button
              type="button"
              onClick={() => openInsightDialog('decisions')}
              className="surface-primary hover:border-border-focus p-4 rounded-xl text-left transition-premium hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(0,0,0,0.1)]"
            >
              <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">{lang === 'it' ? 'Decisioni' : 'Decisions'}</div>
              <div className="mt-1 text-2xl font-bold text-info">{decisions.length}</div>
            </button>

            <button
              type="button"
              onClick={() => openInsightDialog('risks')}
              className="surface-primary hover:border-border-focus p-4 rounded-xl text-left transition-premium hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(0,0,0,0.1)]"
            >
              <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">{lang === 'it' ? 'Rischi' : 'Risks'}</div>
              <div className="mt-1 text-2xl font-bold text-warning">{risks.length}</div>
            </button>
          </div>
        )}

        {/* Project Situation (Digest) - full width */}
        <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
          <SectionHeader
            icon={Sparkles}
            title={t('workspace.projectDigestTitle')}
            description={t('workspace.digestSubtitle')}
            tooltip={t('workspace.digestTooltip')}
            action={
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => navigateTo('analysis')}
                  className="text-xs"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {t('projects.btnCustomQuestion')}
                </Button>
                <Button
                  size="sm"
                  onClick={handleGenerateProjectSituation}
                  disabled={periodItems.length === 0 || isProjectGenerating}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {projectDigestGeneratedAt ? t('workspace.digestCtaUpdate') : t('workspace.digestCtaGenerate')}
                </Button>
              </div>
            }
          />
          
          {isProjectGenerating ? (
            <div className="py-4">
              <TaskProcessingLoader
                title={t('workspace.loaderProjectSituationTitle')}
                description={t('workspace.loaderProjectSituationDesc')}
                steps={[
                  t('workspace.loaderProjectSituationStep1'),
                  t('workspace.loaderProjectSituationStep2'),
                  t('workspace.loaderProjectSituationStep3'),
                  t('workspace.loaderProjectSituationStep4'),
                ]}
                activeStep={2}
                progress={72}
                variant="project"
                compact
                helperText={t('workspace.loaderLocalHelper')}
              />
            </div>
          ) : (
            <div className="mt-1">
              {projectDigestGeneratedAt && digestItems.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {digestItems.slice(0, 4).map((item) => (
                    <div key={item.id} className="rounded-xl border border-border-subtle bg-bg-glass p-3 shadow-[inset_0_1px_0_var(--surface-highlight)] transition-premium hover:border-accent/30 hover:bg-bg-hover/40">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-text-muted">
                        <span>{item.title}</span>
                        <span>{item.sourceTitle}</span>
                      </div>
                      <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">{limitText(item.text, 220)}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={Sparkles}
                  title={t('workspace.digestEmptyTitle')}
                  description={t('workspace.digestEmptyDesc')}
                  className="py-6"
                  action={
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={handleGenerateProjectSituation}
                      disabled={periodItems.length === 0 || isProjectGenerating}
                    >
                      <Sparkles className="h-4 w-4" />
                      {t('workspace.digestCtaGenerate')}
                    </Button>
                  }
                />
              )}
              {projectDigestGeneratedAt && (
                <p className="mt-2 text-[10px] text-text-muted text-right">
                  {lang === 'it' ? 'Situazione aggiornata' : 'Situation updated'}: {projectDigestGeneratedAt}
                </p>
              )}
            </div>
          )}
        </section>

        {/* Actions - full width */}
        <section className="surface-primary flex flex-col gap-3 rounded-2xl p-4" data-tour="project-actions">
          <SectionHeader
            icon={ListChecks}
            title={t('projects.actionsTitle')}
            description={t('projects.actionsDesc')}
            action={
              <div className="flex items-center gap-2">
                <div className="flex rounded-lg border border-border-subtle bg-bg-elevated p-1">
                  {actionScopeOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setActionScope(option.value)}
                      className={cn(
                        'rounded-md px-2.5 py-1 text-xs font-semibold transition-colors',
                        actionScope === option.value
                          ? 'bg-accent text-white'
                          : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                {actionItems.length > 5 && (
                  <button type="button" onClick={() => openInsightDialog('actions')} className="view-all-link">
                    {t('demo.viewAll')} ({actionItems.length})
                  </button>
                )}
              </div>
            }
          />
          <ActionChecklist items={actionItems.slice(0, 5)} />
        </section>

        {/* Decisions and Risks Side-by-Side */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
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
          </div>

          <div className="surface-primary flex flex-col gap-3 rounded-2xl p-4">
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
          </div>
        </div>

        {/* Timeline of meetings - full width */}
        <section className="surface-supporting flex flex-col gap-3 rounded-2xl p-4" data-tour="project-timeline">
          <SectionHeader
            icon={History}
            title={t('projects.timelineTitle')}
            description={t('projects.timelineDesc')}
            action={
              periodItems.length > 3 && (
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
              action={<Button onClick={handleNewMeetingForProject} disabled={demoMode}>{t('projects.btnNewMeetingShort')}</Button>}
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
                  onTranscribe={() => navigateTo('transcription', recordingTranscriptionRoute(item.recording.id))}
                  demoMode={demoMode}
                />
              ))}
            </div>
          )}
        </section>

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
  onTranscribe,
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
  onTranscribe: () => void;
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
          <span>{formatBytes(item.recording.bytes_written || 0)}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
        {item.transcription && <CheckCircle2 className="h-4 w-4 text-success" />}
        {projectItemHasAnalysis(item) && <Sparkles className="h-4 w-4 text-accent" />}
      </div>
      <div className="flex flex-wrap gap-2 lg:justify-end">
        <Button size="sm" onClick={onOpen}>
          {lang === 'it' ? 'Apri' : 'Open'}
        </Button>
        {!item.transcription && !demoMode && (
          <Button size="sm" variant="secondary" onClick={onTranscribe}>
            {lang === 'it' ? 'Trascrivi' : 'Transcribe'}
          </Button>
        )}
        {!demoMode && (
          <Button size="sm" variant="ghost" onClick={onAssignProject}>
            {lang === 'it' ? 'Progetto' : 'Project'}
          </Button>
        )}
      </div>
    </div>
  );
}
