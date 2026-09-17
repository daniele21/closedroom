import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useState, useRef } from 'react';
import {
  ArrowLeft,
  ChevronDown,
  CheckCircle2,
  Clock3,
  FileText,
  History,
  Info,
  ListChecks,
  Loader2,
  PlayCircle,
  RefreshCw,
  Sparkles,
  Users,
  XCircle,
} from 'lucide-react';
import { ApiClient, AnalysisRun, Meeting, MeetingDiagnostics } from '../api/apiClient';
import { createVisualIntelligenceJob, cancelVisualIntelligenceJob } from '../api/visualJobs';
import { prepareMeetingNotes, cancelMeetingPreparation } from '../api/meetingPreparation';
import { ANALYSIS_TYPE_LABELS, ANALYSIS_TYPE_ORDER } from '../api/config';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { AdvancedDetailsAccordion } from '../components/workspace/MeetingWorkspace';
import { renderMarkdown } from '../utils/markdown';
import { formatBytes, formatProjectDate, getDurationSeconds } from '../utils/formatters';
import { useTranslation } from '../i18n/i18n';
import { getDemoMeetings } from '../features/demo/demoData';
import { AnalysisSetupModal, AnalysisSetupSelection } from '../components/ui/AnalysisSetupModal';
import { Sheet, SheetContent, SheetHeader, SheetBody } from '../components/ui/Sheet';
import { cn } from '../utils/cn';
import { formatJobProgress } from '../utils/jobs';
import { VisualIntelligencePanel } from '../components/meeting/VisualIntelligencePanel';
import { VisualDebugPanel } from '../components/meeting/VisualDebugPanel';
import { StructuredNotesEditor } from '../components/meeting/StructuredNotesEditor';
import { useMeetingJobEvents } from '../hooks/useMeetingJobEvents';
import { useVisualIntelligence } from '../hooks/useVisualIntelligence';
import { recordingTranscriptionRoute } from '../utils/transcriptionRoute';
import { SpeakerDiarizationEditor } from '../components/meeting/SpeakerDiarizationEditor';
import TranscriptTextView from '../components/transcription/TranscriptTextView';

interface MeetingDetailPageProps {
  recordingId: string | null;
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
}

type MeetingTab = 'transcript' | 'analysis' | 'speakers';
type VisualFramesState = 'idle' | 'loading' | 'ready' | 'error';

const activeJobStatuses = new Set(['queued', 'running', 'waiting_for_service', 'retrying', 'cancelling']);
const recoverablePreparationStatuses = new Set(['failed', 'interrupted']);
const meetingTabs: MeetingTab[] = ['transcript', 'analysis', 'speakers'];

function runMarkdown(run: AnalysisRun): string {
  return run.result_markdown || run.result?.markdown || '';
}

function analysisLabel(type: string): string {
  return ANALYSIS_TYPE_LABELS[type] || type;
}

function meetingStatusLabel(status: string, lang: string): string {
  const labels: Record<string, { it: string; en: string }> = {
    ready: { it: 'Pronto', en: 'Ready' },
    analyzing: { it: 'Analisi in corso', en: 'Analyzing' },
    processing: { it: 'Elaborazione', en: 'Processing' },
    recording: { it: 'Registrazione', en: 'Recording' },
    completed: { it: 'Completato', en: 'Completed' },
    failed: { it: 'Errore', en: 'Failed' },
  };
  return labels[status]?.[lang === 'it' ? 'it' : 'en'] || status;
}

function preparationProgressLabel(step: string, lang: string): string {
  if (step === 'preparing_transcript') {
    return lang === 'it' ? 'Preparazione trascrizione' : 'Preparing transcript';
  }
  if (step === 'preparing_notes') {
    return lang === 'it' ? 'Trascrizione pronta · preparazione note' : 'Transcript ready · preparing notes';
  }
  if (step === 'cancelling') {
    return lang === 'it' ? 'Interruzione in corso' : 'Stopping preparation';
  }
  return lang === 'it' ? 'Preparazione meeting' : 'Preparing meeting';
}

export default function MeetingDetailPage({ recordingId, navigateTo, demoMode = false }: MeetingDetailPageProps) {
  const { t, lang } = useTranslation();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [diagnosticReport, setDiagnosticReport] = useState<MeetingDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [visualFrameCount, setVisualFrameCount] = useState(0);
  const [visualFramesState, setVisualFramesState] = useState<VisualFramesState>('idle');
  const [visualFramesError, setVisualFramesError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [selectedAnalysisType, setSelectedAnalysisType] = useState('meeting_brief');
  const [error, setError] = useState<string | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [analysisSetupOpen, setAnalysisSetupOpen] = useState(false);
  const [analysisPipelineTarget, setAnalysisPipelineTarget] = useState('meeting_default');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [showAudioPlayer, setShowAudioPlayer] = useState(false);
  const [activeTab, setActiveTab] = useState<MeetingTab>('transcript');
  const [currentTime, setCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const tabListRef = useRef<HTMLDivElement | null>(null);
  const analysisMenuRef = useRef<HTMLDivElement | null>(null);
  const analysisMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const loadGenerationRef = useRef(0);
  const loadInFlightRef = useRef<{ key: string; generation: number; promise: Promise<void> } | null>(null);
  const loadQueuedRef = useRef(false);
  const diagnosticsGenerationRef = useRef(0);
  const visualFramesGenerationRef = useRef(0);
  const userSelectedTabRef = useRef(false);

  const handleTimestampClick = (time: number) => {
    setShowAudioPlayer(true);
    setTimeout(() => {
      if (audioRef.current) {
        audioRef.current.currentTime = time;
        audioRef.current.play().catch(() => {});
      }
    }, 100);
  };
  const visualEnabled = meeting?.transcription?.stats?.visual_intelligence?.version === 2;
  const { data: visualData, loading: visualLoading, error: visualError } = useVisualIntelligence(
    demoMode ? null : recordingId, visualEnabled && activeTab === 'analysis',
  );

  const load = () => {
    if (!recordingId) return Promise.resolve();
    const key = `${recordingId}:${demoMode ? 'demo' : 'live'}:${lang}`;
    const activeLoad = loadInFlightRef.current;
    if (activeLoad?.key === key) {
      loadQueuedRef.current = true;
      return activeLoad.promise;
    }

    const generation = ++loadGenerationRef.current;
    loadQueuedRef.current = false;
    const promise = (async () => {
      try {
        setError(null);
        let data: Meeting;
        if (demoMode) {
          const demoMeetings = getDemoMeetings(lang);
          const matched = demoMeetings.find((m) => m.id === recordingId);
          if (!matched) {
            throw new Error(t('meeting.errorNotFound'));
          }
          data = matched;
        } else {
          data = await ApiClient.getMeeting(recordingId);
        }
        if (generation !== loadGenerationRef.current) return;
        setMeeting(data);
        const availableTypes = Object.keys(data.latest_analysis || {});
        if (availableTypes.length > 0) {
          if (!data.latest_analysis[selectedAnalysisType]) {
            setSelectedAnalysisType(availableTypes[0]);
          }
          if (!userSelectedTabRef.current) {
            setActiveTab('analysis');
          }
        }
      } catch (err: any) {
        if (generation !== loadGenerationRef.current) return;
        setError(err?.message || t('meeting.errorNotAvailable'));
      } finally {
        if (generation === loadGenerationRef.current) {
          setLoading(false);
        }
      }
    })().finally(() => {
      if (loadInFlightRef.current?.generation !== generation) return;
      loadInFlightRef.current = null;
      if (loadQueuedRef.current) {
        loadQueuedRef.current = false;
        void load();
      }
    });
    loadInFlightRef.current = { key, generation, promise };
    return promise;
  };

  const loadDiagnostics = async () => {
    if (!recordingId || demoMode) return;
    const generation = ++diagnosticsGenerationRef.current;
    setDiagnosticsLoading(true);
    setDiagnosticsError(null);
    try {
      const report = await ApiClient.getMeetingDiagnostics(recordingId);
      if (generation !== diagnosticsGenerationRef.current) return;
      setDiagnosticReport(report);
    } catch (err: any) {
      if (generation !== diagnosticsGenerationRef.current) return;
      setDiagnosticsError(
        err?.message || (lang === 'it' ? 'Diagnostica dettagliata non disponibile' : 'Detailed diagnostics unavailable'),
      );
    } finally {
      if (generation === diagnosticsGenerationRef.current) {
        setDiagnosticsLoading(false);
      }
    }
  };

  const loadVisualFrames = async () => {
    if (!recordingId || demoMode) return;
    const generation = ++visualFramesGenerationRef.current;
    setVisualFramesState('loading');
    setVisualFramesError(null);
    try {
      const visualFrames = await ApiClient.recordingVisualFrames(recordingId);
      if (generation !== visualFramesGenerationRef.current) return;
      setVisualFrameCount(visualFrames.total || 0);
      setVisualFramesState('ready');
    } catch (err: any) {
      if (generation !== visualFramesGenerationRef.current) return;
      setVisualFramesError(
        err?.message || (lang === 'it' ? 'Contesto schermo non disponibile' : 'Screen context unavailable'),
      );
      setVisualFramesState('error');
    }
  };

  useEffect(() => {
    setLoading(true);
    setMeeting(null);
    setDiagnosticReport(null);
    setDiagnosticsLoading(false);
    setDiagnosticsError(null);
    setVisualFrameCount(0);
    setVisualFramesState('idle');
    setVisualFramesError(null);
    userSelectedTabRef.current = false;
    void load();
    return () => {
      loadGenerationRef.current += 1;
      diagnosticsGenerationRef.current += 1;
      visualFramesGenerationRef.current += 1;
    };
  }, [recordingId, demoMode, lang]);

  useEffect(() => {
    if (!detailsOpen || !recordingId || demoMode || diagnosticReport || diagnosticsLoading || diagnosticsError) return;
    void loadDiagnostics();
  }, [detailsOpen, recordingId, demoMode, diagnosticReport, diagnosticsLoading, diagnosticsError]);

  useEffect(() => {
    if (
      activeTab !== 'analysis'
      || !recordingId
      || demoMode
      || !meeting?.transcription
      || visualEnabled
      || visualFramesState !== 'idle'
    ) return;
    void loadVisualFrames();
  }, [activeTab, recordingId, demoMode, meeting?.transcription?.id, visualEnabled, visualFramesState]);

  const activeJobs = useMemo(
    () => (meeting?.jobs || []).filter((job) => activeJobStatuses.has(job.status)),
    [meeting],
  );
  const preparationJobs = useMemo(
    () => (meeting?.jobs || []).filter((job) => job.type === 'meeting_preparation'),
    [meeting],
  );
  const activePreparation = activeJobs.find((job) => job.type === 'meeting_preparation');
  const latestPreparation = preparationJobs[0];
  const displayedActiveJobs = activePreparation
    ? [activePreparation]
    : activeJobs;

  const isBusy = busyAction !== null
    || activeJobs.length > 0
    || (meeting?.analysis_runs || []).some((run) => activeJobStatuses.has(run.status));

  useMeetingJobEvents(demoMode ? null : meeting, setMeeting, load);

  useEffect(() => {
    if (!moreOpen) return;
    const frame = window.requestAnimationFrame(() => {
      analysisMenuRef.current
        ?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')
        ?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [moreOpen]);

  const openAdvancedTranscription = () => {
    if (!meeting || demoMode || isBusy) return;
    navigateTo(
      'transcription',
      recordingTranscriptionRoute(meeting.id, meeting.transcription ? 'retranscribe' : 'transcribe'),
    );
  };

  const startDefaultTranscription = async () => {
    if (!meeting || demoMode || isBusy) return;
    setBusyAction('transcription');
    setError(null);
    try {
      await ApiClient.createTranscriptionJob(meeting.id, {
        visual_intelligence_enabled: false,
      });
      await load();
    } catch (err: any) {
      setError(err?.message || (lang === 'it' ? 'Impossibile avviare la trascrizione' : 'Failed to start transcription'));
    } finally {
      setBusyAction(null);
    }
  };

  const startPreparation = async () => {
    if (!meeting || demoMode || isBusy) return;
    setBusyAction('meeting_preparation');
    setError(null);
    try {
      await prepareMeetingNotes(meeting.id);
      await load();
    } catch (err: any) {
      setError(err?.message || (lang === 'it' ? 'Impossibile preparare le note' : 'Failed to prepare meeting notes'));
    } finally {
      setBusyAction(null);
    }
  };

  const startVisualContextAnalysis = async () => {
    if (!meeting?.transcription || demoMode || isBusy || visualFrameCount <= 0) return;
    setBusyAction('visual_intelligence');
    setError(null);
    try {
      await createVisualIntelligenceJob(meeting.id);
      await load();
    } catch (err: any) {
      setError(err?.message || (lang === 'it' ? 'Impossibile analizzare il contesto schermo' : 'Failed to analyze screen context'));
    } finally {
      setBusyAction(null);
    }
  };

  const openAnalysisSetup = (pipelineId = 'meeting_default') => {
    setAnalysisPipelineTarget(pipelineId);
    setAnalysisSetupOpen(true);
  };

  const startPipeline = async (pipelineId = 'meeting_default', selection: AnalysisSetupSelection = {}) => {
    if (!meeting) return;
    if (demoMode || isBusy) return;
    setBusyAction(pipelineId);
    try {
      await ApiClient.createAnalysisPipeline({
        recording_id: meeting.id,
        transcription_id: meeting.transcription?.id,
        pipeline_id: pipelineId,
        ...selection,
      });
      window.setTimeout(load, 700);
    } catch (err: any) {
      setError(err?.message || t('meeting.errorPipelineNotStarted'));
    } finally {
      setBusyAction(null);
    }
  };

  const handleCancelJob = async (jobId: string, jobType?: string) => {
    if (demoMode || !meeting) return;
    try {
      if (jobType === 'visual_intelligence') {
        await cancelVisualIntelligenceJob(jobId);
      } else if (jobType === 'meeting_preparation') {
        await cancelMeetingPreparation(meeting.id, jobId);
      } else {
        await ApiClient.cancelJob(jobId);
      }
      load();
    } catch (err: any) {
      setError(err?.message || (lang === 'it' ? 'Impossibile annullare il job' : 'Failed to cancel job'));
    }
  };

  const focusTab = (tab: MeetingTab) => {
    userSelectedTabRef.current = true;
    setActiveTab(tab);
    window.requestAnimationFrame(() => {
      document.getElementById(`meeting-tab-${tab}`)?.focus();
    });
  };

  const selectTab = (tab: MeetingTab) => {
    userSelectedTabRef.current = true;
    setActiveTab(tab);
  };

  const handleTabListKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const currentIndex = meetingTabs.indexOf(activeTab);
    let nextIndex = currentIndex;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % meetingTabs.length;
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + meetingTabs.length) % meetingTabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = meetingTabs.length - 1;
    event.preventDefault();
    focusTab(meetingTabs[nextIndex]);
  };

  const handleAnalysisMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      analysisMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [],
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
      setMoreOpen(false);
      analysisMenuTriggerRef.current?.focus();
      return;
    } else {
      return;
    }
    event.preventDefault();
    items[nextIndex]?.focus();
  };

  if (!recordingId) {
    return (
      <div className="border border-border-subtle rounded-lg p-8 text-center">
        <p className="text-text-secondary">{t('meeting.selectMeetingFromToday')}</p>
        <Button className="mt-4" variant="secondary" onClick={() => navigateTo('home')}>{t('meeting.backToToday')}</Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3" role="status" aria-live="polite">
        <Loader2 className="w-8 h-8 animate-spin text-accent" aria-hidden="true" />
        <span className="text-sm text-text-secondary">{t('meeting.loadingMeeting')}</span>
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="border border-border-subtle rounded-lg p-8 text-center" role="alert">
        <p className="text-danger">{error || t('meeting.errorNotFound')}</p>
        <Button className="mt-4" variant="secondary" onClick={() => navigateTo('home')}>{t('meeting.backToToday')}</Button>
      </div>
    );
  }

  const title = meeting.recording.title || `Meeting ${meeting.id.slice(0, 8)}`;
  const analysisTypes = Array.from(new Set([
    ...ANALYSIS_TYPE_ORDER,
    ...meeting.analysis_runs.map((run) => run.analysis_type),
  ])).filter((type) => type !== 'custom_question' || meeting.latest_analysis[type]);
  const selectedRun = meeting.latest_analysis?.[selectedAnalysisType];
  const selectedHistory = meeting.analysis_runs.filter((run) => run.analysis_type === selectedAnalysisType);
  const recordingDuration = getDurationSeconds(meeting.recording);
  const canAnalyze = Boolean(meeting.transcription) && !demoMode;
  const diarization = meeting.transcription?.stats?.speaker_diarization;
  const visualIntelligence = meeting.transcription?.stats?.visual_intelligence;
  const diagnostics = diagnosticReport?.diagnostics || meeting.transcription?.stats?.diagnostics || [];
  const outcomeStatus = diagnosticReport?.outcome_status || meeting.transcription?.stats?.outcome_status;
  const diagnosticWarnings = diagnostics.filter((item) =>
    item.status === 'failed' || item.status === 'degraded' || item.fallback_used,
  );
  const acceptedSpeakerMappings = (meeting.transcription?.stats?.speaker_attribution?.mappings || [])
    .filter((mapping) => mapping.status === 'accepted' && mapping.display_name);
  const speakerMappings = meeting.transcription?.stats?.speaker_attribution?.mappings || [];
  const hasCurrentNotes = Object.keys(meeting.latest_analysis || {}).length > 0;
  const canResumePreparation = Boolean(
    latestPreparation && recoverablePreparationStatuses.has(latestPreparation.status),
  );

  const enrichmentBadge = (status?: string) => {
    if (status === 'completed') return <Badge variant="success">{t('meeting.enrichmentCompleted')}</Badge>;
    if (status === 'failed' || status === 'degraded' || status === 'completed_with_warnings') {
      return <Badge variant="warning">{t('meeting.enrichmentFailed')}</Badge>;
    }
    return <Badge variant="idle">{t('meeting.enrichmentUnavailable')}</Badge>;
  };

  const tabId = (tab: MeetingTab) => `meeting-tab-${tab}`;
  const panelId = (tab: MeetingTab) => `meeting-panel-${tab}`;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-4 border-b border-border-subtle pb-4">
        <div className="flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={() => navigateTo('home')}
            className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" />
            <span>{t('dashboard.title')}</span>
          </button>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-2xl font-bold text-text-primary tracking-tight truncate">{title}</h2>
              {meeting.project_name && (
                <span className="rounded-md border border-border-subtle bg-bg-surface px-2 py-0.5 text-[11px] font-medium text-text-muted">
                  {meeting.project_name}
                </span>
              )}
              <Badge variant={meeting.status === 'ready' ? 'success' : meeting.status === 'analyzing' ? 'warning' : 'idle'}>
                {meetingStatusLabel(meeting.status, lang)}
              </Badge>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-muted">
              <span>{formatProjectDate(meeting.created_at, lang)}</span>
              <span aria-hidden="true">•</span>
              <span>{recordingDuration > 0 ? `${Math.round(recordingDuration / 60)} min` : t('projects.durationNotAvailable')}</span>
              <span aria-hidden="true">•</span>
              <span>{formatBytes(meeting.recording.bytes_written || 0)}</span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 mt-2 sm:mt-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowAudioPlayer((prev) => !prev)}
              className={cn('h-8 px-2.5', showAudioPlayer && 'bg-bg-hover text-text-primary')}
              aria-expanded={showAudioPlayer}
              aria-controls="meeting-audio-player"
            >
              <PlayCircle className="w-4 h-4 text-accent" aria-hidden="true" />
              <span>{t('meeting.audioTitle')}</span>
            </Button>
            <Button variant="ghost" size="sm" onClick={load} className="h-8 px-2.5">
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              <span>{t('meeting.btnUpdate')}</span>
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setDetailsOpen(true)} className="h-8 px-2.5">
              <Info className="w-4 h-4 text-text-muted" aria-hidden="true" />
              <span>{lang === 'it' ? 'Dettagli' : 'Details'}</span>
            </Button>
          </div>
        </div>

        {showAudioPlayer && (
          <div id="meeting-audio-player" className="workspace-panel rounded-xl border border-border-subtle p-3.5 animate-in slide-in-from-top-3 duration-200">
            <div className="flex items-center justify-between gap-3 mb-2">
              <span className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                <PlayCircle className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                {t('meeting.audioTitle')}
              </span>
              <button
                type="button"
                onClick={() => setShowAudioPlayer(false)}
                className="text-[10px] text-text-muted hover:text-text-primary transition-colors font-semibold cursor-pointer"
              >
                {lang === 'it' ? 'Nascondi' : 'Hide'}
              </button>
            </div>
            <audio
              ref={audioRef}
              controls
              src={`/v1/recordings/${meeting.id}/audio`}
              className="h-9 w-full"
              autoPlay
              onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
            />
          </div>
        )}
      </section>

      {outcomeStatus === 'completed_with_warnings' && (
        <section className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-xs text-text-secondary">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-semibold text-warning">{t('meeting.completedWithWarnings')}</p>
              <p className="mt-1">{t('meeting.completedWithWarningsDesc')}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setDetailsOpen(true)}>
              {t('meeting.showDiagnostics')}
            </Button>
          </div>
        </section>
      )}

      {(activeJobs.length > 0 || meeting.analysis_runs.some((run) => activeJobStatuses.has(run.status))) && (
        <section
          className="border border-warning/30 bg-warning/5 rounded-xl px-4 py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs animate-in fade-in duration-200"
          role="status"
          aria-live="polite"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-text-primary shrink-0">
              <Clock3 className="w-4 h-4 text-warning" aria-hidden="true" />
              <span>{activePreparation
                ? (lang === 'it' ? 'Preparazione note' : 'Preparing notes')
                : t('meeting.processingTitle')}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-text-secondary">
              {displayedActiveJobs.map((job) => (
                <div key={job.id} className="flex items-center gap-2">
                  <span className="font-medium text-text-primary">
                    {job.type === 'meeting_preparation'
                      ? preparationProgressLabel(job.current_step, lang)
                      : `${job.type}: ${formatJobProgress(job, t)}`}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleCancelJob(job.id, job.type)}
                    className="text-danger hover:text-danger-hover transition-colors font-semibold text-[11px] flex items-center gap-1 cursor-pointer bg-danger/10 hover:bg-danger/20 px-2 py-0.5 rounded"
                  >
                    <XCircle className="w-3 h-3" aria-hidden="true" />
                    {t('common.cancel')}
                  </button>
                </div>
              ))}
              {!activePreparation && meeting.analysis_runs.filter((run) => activeJobStatuses.has(run.status)).map((run) => (
                <div key={run.id} className="flex items-center gap-2">
                  <span className="font-medium text-text-primary">{analysisLabel(run.analysis_type)}: {run.status}</span>
                  {run.job_id && (
                    <button
                      type="button"
                      onClick={() => handleCancelJob(run.job_id!)}
                      className="text-danger hover:text-danger-hover transition-colors font-semibold text-[11px] flex items-center gap-1 cursor-pointer bg-danger/10 hover:bg-danger/20 px-2 py-0.5 rounded"
                    >
                      <XCircle className="w-3 h-3" aria-hidden="true" />
                      {t('common.cancel')}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setDetailsOpen(true)} className="shrink-0">
            {lang === 'it' ? 'Dettagli' : 'Details'}
          </Button>
        </section>
      )}

      <div className="flex flex-col gap-5 w-full">
        {!isBusy && !hasCurrentNotes && (
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 px-4 py-3.5 rounded-xl border border-accent/25 bg-accent-soft">
            <div className="flex items-start gap-2.5 min-w-0">
              <Sparkles className="h-5 w-5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
              <div>
                <h4 className="text-xs font-semibold text-text-primary">
                  {canResumePreparation
                    ? (lang === 'it' ? 'Riprendi la preparazione' : 'Resume preparation')
                    : (lang === 'it' ? 'Prepara le note del meeting' : 'Prepare meeting notes')}
                </h4>
                <p className="text-[11px] text-text-secondary leading-relaxed mt-0.5">
                  {meeting.transcription
                    ? (lang === 'it'
                      ? 'La trascrizione è pronta. ClosedRoom prepara sintesi, azioni, decisioni e rischi.'
                      : 'The transcript is ready. ClosedRoom will prepare summary, actions, decisions and risks.')
                    : (lang === 'it'
                      ? 'Un’unica azione prepara prima la trascrizione e poi le note, usando le impostazioni correnti.'
                      : 'One action prepares the transcript first and then the notes using your current settings.')}
                </p>
                {latestPreparation?.error && canResumePreparation && (
                  <p className="text-[10px] text-warning mt-1 line-clamp-2">{latestPreparation.error}</p>
                )}
              </div>
            </div>
            <div className="flex w-full sm:w-auto items-center gap-2">
              {!meeting.transcription && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={demoMode}
                  onClick={startDefaultTranscription}
                  isLoading={busyAction === 'transcription'}
                  className="flex-1 sm:flex-none"
                >
                  <FileText className="h-4 w-4" aria-hidden="true" />
                  {lang === 'it' ? 'Solo trascrizione' : 'Transcript only'}
                </Button>
              )}
              <Button
                size="sm"
                disabled={demoMode}
                onClick={startPreparation}
                isLoading={busyAction === 'meeting_preparation'}
                className="flex-1 sm:flex-none shadow-cta"
              >
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                {canResumePreparation
                  ? (lang === 'it' ? 'Riprendi' : 'Resume')
                  : (lang === 'it' ? 'Prepara note' : 'Prepare notes')}
              </Button>
            </div>
          </div>
        )}

        {activeTab === 'analysis' && !isBusy && meeting.transcription && visualFrameCount > 0 && !visualEnabled && (
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 px-4 py-3 rounded-xl border border-border-subtle bg-bg-surface/30">
            <div className="flex items-start gap-2.5 min-w-0">
              <Sparkles className="h-4 w-4 text-text-muted shrink-0 mt-0.5" aria-hidden="true" />
              <div>
                <h4 className="text-xs font-semibold text-text-primary">
                  {lang === 'it' ? 'Contesto schermo disponibile' : 'Screen context available'}
                </h4>
                <p className="text-[11px] text-text-secondary leading-relaxed mt-0.5">
                  {lang === 'it'
                    ? 'Hai scelto di catturarlo durante il meeting. Analizzalo solo quando ti serve.'
                    : 'You chose to capture it during the meeting. Analyze it only when you need it.'}
                </p>
              </div>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={startVisualContextAnalysis}
              isLoading={busyAction === 'visual_intelligence'}
              className="shrink-0 w-full sm:w-auto"
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              {lang === 'it' ? 'Analizza contesto schermo' : 'Analyze screen context'}
            </Button>
          </div>
        )}

        {activeTab === 'analysis' && meeting.transcription && !visualEnabled && visualFramesState === 'error' && (
          <div className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs text-text-secondary sm:flex-row sm:items-center sm:justify-between" role="status">
            <div>
              <p className="font-semibold text-text-primary">
                {lang === 'it' ? 'Contesto schermo non disponibile' : 'Screen context unavailable'}
              </p>
              <p className="mt-0.5 text-text-muted">{visualFramesError}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={loadVisualFrames}>
              {lang === 'it' ? 'Riprova' : 'Retry'}
            </Button>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger animate-fade-in" role="alert">
            {error}
          </div>
        )}

        <main className="flex flex-col gap-5 w-full">
          <div
            ref={tabListRef}
            className="flex border border-border-subtle bg-bg-surface/30 p-1 rounded-xl gap-1"
            role="tablist"
            aria-orientation="horizontal"
            aria-label={lang === 'it' ? 'Contenuto del meeting' : 'Meeting content'}
            onKeyDown={handleTabListKeyDown}
          >
            <button
              type="button"
              id={tabId('transcript')}
              role="tab"
              aria-selected={activeTab === 'transcript'}
              aria-controls={panelId('transcript')}
              tabIndex={activeTab === 'transcript' ? 0 : -1}
              onClick={() => selectTab('transcript')}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-semibold transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
                activeTab === 'transcript'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover',
              )}
            >
              <FileText className="w-4 h-4" aria-hidden="true" />
              <span>{t('meeting.tabTranscript')}</span>
              {meeting.transcription && (
                <span className={cn(
                  'ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold border',
                  activeTab === 'transcript' ? 'bg-white/20 border-white/20 text-white' : 'bg-bg-elevated border-border-subtle text-text-secondary',
                )}>
                  {meeting.transcription.segments?.length || 0}
                </span>
              )}
            </button>
            <button
              type="button"
              id={tabId('analysis')}
              role="tab"
              aria-selected={activeTab === 'analysis'}
              aria-controls={panelId('analysis')}
              tabIndex={activeTab === 'analysis' ? 0 : -1}
              onClick={() => selectTab('analysis')}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-semibold transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
                activeTab === 'analysis'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover',
              )}
            >
              <Sparkles className="w-4 h-4" aria-hidden="true" />
              <span>{t('meeting.tabAnalysis')}</span>
              {meeting.analysis_runs.length > 0 && (
                <span className={cn(
                  'ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold border',
                  activeTab === 'analysis' ? 'bg-white/20 border-white/20 text-white' : 'bg-bg-elevated border-border-subtle text-text-secondary',
                )}>
                  {meeting.analysis_runs.length}
                </span>
              )}
            </button>
            <button
              type="button"
              id={tabId('speakers')}
              role="tab"
              aria-selected={activeTab === 'speakers'}
              aria-controls={panelId('speakers')}
              tabIndex={activeTab === 'speakers' ? 0 : -1}
              onClick={() => selectTab('speakers')}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-semibold transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
                activeTab === 'speakers'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover',
              )}
            >
              <Users className="w-4 h-4" aria-hidden="true" />
              <span>{t('meeting.tabSpeakers')}</span>
              {speakerMappings.length > 0 && (
                <span className={cn(
                  'ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold border',
                  activeTab === 'speakers' ? 'bg-white/20 border-white/20 text-white' : 'bg-bg-elevated border-border-subtle text-text-secondary',
                )}>
                  {speakerMappings.length}
                </span>
              )}
            </button>
          </div>

          <div className="flex flex-col gap-5 w-full">
            {activeTab === 'transcript' && (
              <div
                id={panelId('transcript')}
                role="tabpanel"
                aria-labelledby={tabId('transcript')}
                tabIndex={0}
                className="surface-primary rounded-xl border border-border-subtle shadow-premium overflow-hidden"
              >
                {meeting.transcription && !demoMode && (
                  <div className="px-4 py-3 border-b border-border-subtle bg-bg-elevated flex items-center justify-between gap-3">
                    <span className="text-xs text-text-secondary font-medium">
                      {meeting.transcription?.text && (
                        <span>
                          {meeting.transcription.text.split(/\s+/).filter(Boolean).length} {lang === 'it' ? 'parole' : 'words'}
                        </span>
                      )}
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => navigateTo('transcription', meeting.transcription?.id || null)}
                    >
                      {t('meeting.openTranscriptTools')}
                    </Button>
                  </div>
                )}
                {meeting.transcription?.segments?.length ? (
                  <div className="p-4 sm:p-5 bg-bg-elevated">
                    <TranscriptTextView
                      segments={meeting.transcription.segments}
                      speakerMappings={speakerMappings}
                      onTimestampClick={handleTimestampClick}
                      currentTime={currentTime}
                    />
                  </div>
                ) : meeting.transcription?.text ? (
                  <div className="p-5 bg-bg-elevated">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-secondary">
                      {meeting.transcription.text}
                    </p>
                  </div>
                ) : (
                  <div className="text-center py-16 bg-bg-elevated">
                    <FileText className="w-8 h-8 mx-auto text-text-muted mb-3" aria-hidden="true" />
                    <p className="text-sm text-text-secondary">{t('meeting.transcriptNotAvailable')}</p>
                    {!isBusy && !demoMode && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={startDefaultTranscription}
                        isLoading={busyAction === 'transcription'}
                        className="mt-4"
                      >
                        {lang === 'it' ? 'Solo trascrizione' : 'Transcript only'}
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'analysis' && (
              <div
                id={panelId('analysis')}
                role="tabpanel"
                aria-labelledby={tabId('analysis')}
                tabIndex={0}
                className="surface-primary rounded-xl overflow-hidden border border-border-subtle shadow-premium"
              >
                <div className="px-4 py-3 border-b border-border-subtle bg-bg-elevated flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-accent" aria-hidden="true" />
                    <h3 className="text-sm font-semibold text-text-primary">{t('meeting.analysisTitle')}</h3>
                  </div>
                  <div className="flex items-center gap-2">
                    {meeting.transcription && (
                      <div className="relative">
                        <Button
                          ref={analysisMenuTriggerRef}
                          size="sm"
                          variant="ghost"
                          onClick={() => setMoreOpen((open) => !open)}
                          aria-expanded={moreOpen}
                          aria-haspopup="menu"
                          aria-controls="meeting-analysis-menu"
                          className="h-7 text-xs text-text-muted hover:text-text-primary"
                        >
                          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                          <span>{lang === 'it' ? 'Altre analisi' : 'More analysis'}</span>
                          <ChevronDown className="h-3 w-3" aria-hidden="true" />
                        </Button>
                        {moreOpen && (
                          <div
                            id="meeting-analysis-menu"
                            ref={analysisMenuRef}
                            role="menu"
                            aria-label={lang === 'it' ? 'Scegli analisi' : 'Choose analysis'}
                            onKeyDown={handleAnalysisMenuKeyDown}
                            className="absolute right-0 top-8 z-40 w-48 rounded-lg border border-border-subtle bg-bg-surface p-1 shadow-premium"
                          >
                            <button
                              type="button"
                              role="menuitem"
                              disabled={demoMode || isBusy}
                              onClick={() => {
                                setMoreOpen(false);
                                startPreparation();
                              }}
                              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:opacity-50"
                            >
                              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                              {lang === 'it' ? 'Prepara note' : 'Prepare notes'}
                            </button>
                            <button
                              type="button"
                              role="menuitem"
                              disabled={demoMode || isBusy}
                              onClick={() => {
                                setMoreOpen(false);
                                openAnalysisSetup('meeting_deep');
                              }}
                              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:opacity-50"
                            >
                              <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
                              {t('meeting.deepDetail')}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                    <span className="text-xs text-text-muted border-l border-border-subtle pl-2.5">
                      {meeting.analysis_runs.length} run
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1 p-2 border-b border-border-subtle bg-bg-surface/50">
                  {analysisTypes
                    .filter((type) => meeting.latest_analysis?.[type] || (!Object.keys(meeting.latest_analysis || {}).length && type === 'meeting_brief'))
                    .map((type) => {
                      const run = meeting.latest_analysis?.[type];
                      return (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setSelectedAnalysisType(type)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors duration-200 cursor-pointer ${
                            selectedAnalysisType === type
                              ? 'bg-accent text-white border-accent shadow-sm'
                              : 'bg-bg-elevated text-text-secondary border-border-subtle hover:bg-bg-hover hover:text-text-primary'
                          }`}
                        >
                          {analysisLabel(type)}
                          {run && <CheckCircle2 className="inline-block ml-1.5 w-3.5 h-3.5 text-white" aria-hidden="true" />}
                        </button>
                      );
                    })}
                </div>

                <div className="p-5 sm:p-6 bg-bg-elevated min-h-[220px]">
                  {selectedRun ? (
                    selectedRun.result?.schema?.id === 'closedroom.meeting_notes' && selectedRun.result?.schema?.version === 2 ? (
                      <StructuredNotesEditor
                        run={selectedRun}
                        analysisType={selectedAnalysisType}
                        lang={lang}
                        onSeek={handleTimestampClick}
                        onChanged={async () => { await load(); }}
                        readOnly={demoMode}
                      />
                    ) : (
                      <div className="max-w-none prose prose-invert prose-sm animate-in fade-in duration-200">
                        {renderMarkdown(runMarkdown(selectedRun))}
                      </div>
                    )
                  ) : (
                    <div className="text-center py-12">
                      <Sparkles className="w-8 h-8 mx-auto text-text-muted mb-3" aria-hidden="true" />
                      <p className="text-sm text-text-secondary">{t('meeting.noAnalysisAvailable', { type: analysisLabel(selectedAnalysisType) })}</p>
                      {!isBusy && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={startPreparation}
                          isLoading={busyAction === 'meeting_preparation'}
                          className="mt-4"
                        >
                          {lang === 'it' ? 'Prepara note' : 'Prepare notes'}
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'speakers' && (
              <div
                id={panelId('speakers')}
                role="tabpanel"
                aria-labelledby={tabId('speakers')}
                tabIndex={0}
                className="animate-in fade-in duration-200"
              >
                {meeting.transcription ? (
                  <SpeakerDiarizationEditor
                    transcription={meeting.transcription}
                    readOnly={demoMode}
                    onUpdated={(transcription) => setMeeting((current) => (
                      current ? { ...current, transcription } : current
                    ))}
                  />
                ) : (
                  <div className="text-center py-16 bg-bg-elevated rounded-xl border border-border-subtle">
                    <Users className="w-8 h-8 mx-auto text-text-muted mb-3" aria-hidden="true" />
                    <p className="text-sm text-text-secondary">{t('meeting.noSpeakerClusters')}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {(visualData || visualLoading || visualError) && (
            <VisualIntelligencePanel
              data={visualData}
              mappings={speakerMappings}
              loading={visualLoading}
              error={visualError}
            />
          )}
        </main>
      </div>

      <Sheet open={detailsOpen} onOpenChange={setDetailsOpen}>
        <SheetContent side="right" className="bg-bg-elevated border-l border-border-subtle w-full sm:w-[420px]">
          <SheetHeader
            title={t('meeting.statusTitle')}
            description={t('workspace.advancedDesc')}
          />
          <SheetBody className="flex flex-col gap-5 overflow-y-auto pt-2">
            <div className="rounded-xl border border-border-subtle bg-bg-surface p-4">
              <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-3">
                {lang === 'it' ? 'Stato Componenti' : 'Component Status'}
              </h4>
              <div className="flex flex-col gap-3 text-xs text-text-secondary">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('meeting.audioTitle')}</span>
                  <Badge variant="success">{t('meeting.statusSaved')}</Badge>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>{t('meeting.transcriptionLabel')}</span>
                  <Badge variant={meeting.transcription ? 'success' : 'warning'}>
                    {meeting.transcription ? t('meeting.statusReady') : t('meeting.statusMissing')}
                  </Badge>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>{t('meeting.analysisLabel')}</span>
                  <Badge variant={hasCurrentNotes ? 'success' : 'idle'}>
                    {hasCurrentNotes ? t('meeting.statusReady') : t('meeting.statusMissing')}
                  </Badge>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>{t('meeting.diarizationLabel')}</span>
                  {enrichmentBadge(diarization?.status)}
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>{t('meeting.visualEvidenceLabel')}</span>
                  {enrichmentBadge(visualIntelligence?.status)}
                </div>
              </div>
            </div>

            {meeting.transcription && (
              <div className="rounded-xl border border-border-subtle bg-bg-surface p-4">
                <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-3">
                  {t('meeting.speakerAttributionLabel')}
                </h4>
                {acceptedSpeakerMappings.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    {acceptedSpeakerMappings.map((mapping) => (
                      <div key={mapping.speaker_cluster} className="flex items-center justify-between gap-3 text-xs">
                        <span className="font-mono text-text-muted">{mapping.speaker_cluster}</span>
                        <span className="font-semibold text-text-primary">{mapping.display_name}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-text-muted">{t('meeting.noSpeakerAttribution')}</p>
                )}
              </div>
            )}

            {diagnosticsLoading && (
              <div className="flex items-center gap-2 rounded-xl border border-border-subtle bg-bg-surface px-4 py-3 text-xs text-text-muted" role="status">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                <span>{lang === 'it' ? 'Caricamento diagnostica dettagliata…' : 'Loading detailed diagnostics…'}</span>
              </div>
            )}

            {diagnosticsError && (
              <div className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs text-text-secondary" role="status">
                <p className="font-semibold text-text-primary">
                  {lang === 'it' ? 'Diagnostica dettagliata non disponibile' : 'Detailed diagnostics unavailable'}
                </p>
                <p className="mt-1 text-text-muted">{diagnosticsError}</p>
                <Button size="sm" variant="ghost" onClick={loadDiagnostics} className="mt-2">
                  {lang === 'it' ? 'Riprova' : 'Retry'}
                </Button>
              </div>
            )}

            <div className="rounded-xl border border-border-subtle bg-bg-surface p-4">
              <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-3">
                {lang === 'it' ? 'Azioni Disponibili' : 'Available Actions'}
              </h4>
              <div className="flex flex-col gap-2">
                {!hasCurrentNotes && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={demoMode || isBusy}
                    onClick={() => {
                      setDetailsOpen(false);
                      startPreparation();
                    }}
                    className="w-full justify-start text-left text-xs"
                  >
                    <Sparkles className="h-3.5 w-3.5 mr-2 text-accent" aria-hidden="true" />
                    {lang === 'it' ? 'Prepara note' : 'Prepare notes'}
                  </Button>
                )}
                {!meeting.transcription && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={demoMode || isBusy}
                    onClick={startDefaultTranscription}
                    className="w-full justify-start text-left text-xs"
                  >
                    <FileText className="h-3.5 w-3.5 mr-2 text-text-muted" aria-hidden="true" />
                    {lang === 'it' ? 'Solo trascrizione' : 'Transcript only'}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={demoMode || isBusy}
                  onClick={() => {
                    setDetailsOpen(false);
                    openAdvancedTranscription();
                  }}
                  className="w-full justify-start text-left text-xs"
                >
                  <FileText className="h-3.5 w-3.5 mr-2 text-text-muted" aria-hidden="true" />
                  {lang === 'it' ? 'Trascrizione avanzata' : 'Advanced transcription'}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!canAnalyze || isBusy}
                  onClick={() => {
                    setDetailsOpen(false);
                    startPipeline('meeting_default');
                  }}
                  className="w-full justify-start text-left text-xs"
                >
                  <Sparkles className="h-3.5 w-3.5 mr-2 text-accent" aria-hidden="true" />
                  {lang === 'it' ? 'Rigenera solo analisi' : 'Regenerate analysis only'}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!canAnalyze || isBusy}
                  onClick={() => {
                    setDetailsOpen(false);
                    openAnalysisSetup('meeting_deep');
                  }}
                  className="w-full justify-start text-left text-xs"
                >
                  <ListChecks className="h-3.5 w-3.5 mr-2 text-accent" aria-hidden="true" />
                  {t('meeting.btnDeep')} (Pipeline completa)
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border-subtle bg-bg-surface p-4">
              <div className="flex items-center gap-2 mb-3">
                <History className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
                <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider">
                  {t('meeting.runHistoryTitle')}
                </h4>
              </div>
              <div className="flex flex-col gap-2 max-h-[220px] overflow-auto">
                {selectedHistory.length === 0 ? (
                  <p className="text-xs text-text-muted">{t('meeting.noRunForType')}</p>
                ) : (
                  selectedHistory.map((run) => (
                    <div key={run.id} className="rounded-lg border border-border-subtle bg-bg-surface/50 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-text-primary">{analysisLabel(run.analysis_type)}</span>
                        <Badge variant={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'warning'}>
                          {run.status}
                        </Badge>
                      </div>
                      <div className="mt-1 text-[10px] text-text-muted">
                        {new Date(run.created_at * 1000).toLocaleString(lang === 'it' ? 'it-IT' : 'en-US')}
                      </div>
                      {run.error && <div className="mt-1 text-[10px] text-danger">{run.error}</div>}
                    </div>
                  ))
                )}
              </div>
            </div>

            {(diagnostics.length > 0 || diagnosticReport?.log_file || (recordingId && visualEnabled)) && (
              <AdvancedDetailsAccordion title={t('meeting.diagnosticsTitle')}>
                <div className="flex flex-col gap-3 pt-1">
                  {diagnostics.map((item, index) => (
                    <div key={`${item.component}-${index}`} className="border-b border-border-subtle pb-3 last:border-0 last:pb-0 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-text-primary">{item.component}</span>
                        {enrichmentBadge(item.status)}
                      </div>
                      {(item.requested_backend || item.actual_backend) && (
                        <p className="mt-1 text-text-muted font-mono break-all">
                          {item.requested_backend || '—'} → {item.actual_backend || '—'}
                        </p>
                      )}
                      {(item.fallback_used || item.fallback_reason) && (
                        <p className="mt-1 text-warning">{t('meeting.fallbackLabel')}: {item.fallback_reason || 'fallback'}</p>
                      )}
                      {item.error && <p className="mt-1 text-danger break-words">{item.error}</p>}
                      {Boolean(item.details?.model_path) && (
                        <p className="mt-1 text-text-muted font-mono break-all">
                          {t('meeting.modelPathLabel')}: {String(item.details?.model_path)}
                        </p>
                      )}
                    </div>
                  ))}
                  {diagnostics.length > 0 && diagnosticWarnings.length === 0 && (
                    <p className="text-xs text-text-muted">{t('meeting.noDiagnosticWarnings')}</p>
                  )}
                  {diagnosticReport?.log_file && (
                    <div className="border-t border-border-subtle pt-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">{t('meeting.logFileLabel')}</p>
                      <button
                        type="button"
                        className="mt-1 text-left text-xs font-mono text-accent hover:underline break-all"
                        onClick={() => navigator.clipboard?.writeText(diagnosticReport.log_file || '')}
                        title={t('meeting.copyLogPath')}
                      >
                        {diagnosticReport.log_file}
                      </button>
                      {diagnosticReport.log_lines.length > 0 && (
                        <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap rounded-md bg-bg-elevated p-2 text-[10px] text-text-muted">
                          {diagnosticReport.log_lines.join('\n')}
                        </pre>
                      )}
                    </div>
                  )}
                  {recordingId && visualEnabled && (
                    <div className="border-t border-border-subtle pt-3">
                      <VisualDebugPanel recordingId={recordingId} />
                    </div>
                  )}
                </div>
              </AdvancedDetailsAccordion>
            )}

            <AdvancedDetailsAccordion title={t('meeting.techDetailsTitle')}>
              <dl className="grid grid-cols-[100px_minmax(0,1fr)] gap-2 text-[11px] pt-1">
                <dt className="text-text-muted">Recording ID</dt>
                <dd className="text-text-secondary truncate select-all" title={meeting.id}>{meeting.id}</dd>
                <dt className="text-text-muted">{t('meeting.transcriptionLabel')}</dt>
                <dd className="text-text-secondary truncate select-all" title={meeting.transcription?.id || ''}>{meeting.transcription?.id || '-'}</dd>
                <dt className="text-text-muted">Backend</dt>
                <dd className="text-text-secondary">{meeting.recording.capture_backend || '-'}</dd>
                <dt className="text-text-muted">Modalità</dt>
                <dd className="text-text-secondary">{meeting.recording.capture_mode || '-'}</dd>
              </dl>
            </AdvancedDetailsAccordion>
          </SheetBody>
        </SheetContent>
      </Sheet>

      <AnalysisSetupModal
        isOpen={analysisSetupOpen}
        onConfirm={(selection) => {
          setAnalysisSetupOpen(false);
          startPipeline(analysisPipelineTarget, selection);
        }}
        onCancel={() => setAnalysisSetupOpen(false)}
        demoMode={demoMode}
      />
    </div>
  );
}
