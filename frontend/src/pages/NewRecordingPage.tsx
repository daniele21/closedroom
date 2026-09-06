import { useEffect, useState } from 'react';
import {
  Bug,
  CheckCircle2,
  ChevronDown,
  FolderOpen,
  Info,
  Mic,
  Monitor,
  PanelTopOpen,
  RefreshCw,
  SlidersHorizontal,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { ApiClient, CaptureWindow, Recording } from '../api/apiClient';
import { NEW_RECORDING_PROJECT_STORAGE_KEY } from '../api/config';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { openBrowserPopup, useRecorder } from '../hooks/useRecorder';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';

interface NewRecordingPageProps {
  navigateTo: (page: string, detail?: string | null) => void;
}

export default function NewRecordingPage({ navigateTo }: NewRecordingPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const [title, setTitle] = useState('');
  const [projectName, setProjectName] = useState('');
  const [sourceMode, setSourceMode] = useState<'both' | 'mic_only' | 'pc_only'>('both');
  const [recordingsDir, setRecordingsDir] = useState('');
  const [storageConfigured, setStorageConfigured] = useState(false);
  const [projectsList, setProjectsList] = useState<string[]>([]);
  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [showAudioRecovery, setShowAudioRecovery] = useState(false);
  const [showScreenContext, setShowScreenContext] = useState(false);
  const [captureWindows, setCaptureWindows] = useState<CaptureWindow[]>([]);
  const [visualWindowId, setVisualWindowId] = useState('');
  const [visualSourcesLoading, setVisualSourcesLoading] = useState(false);
  const [visualSourcesError, setVisualSourcesError] = useState<string | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [storageSaving, setStorageSaving] = useState(false);

  const recorder = useRecorder((recording: Recording) => {
    // Meetings are addressed by recording id throughout the meeting API.
    navigateTo('meeting', recording.id);
  });

  const nativeCaptureReady = recorder.captureCapabilities?.default_backend === 'native'
    && recorder.captureCapabilities.native.available;
  const nativeCaptureChecked = Boolean(recorder.captureCapabilities);
  const nativeCaptureUnavailableReason = recorder.captureCapabilities?.native.reason
    || recorder.captureCapabilities?.native.error
    || '';
  const nativeCaptureUnavailableMessage = (() => {
    if (nativeCaptureUnavailableReason === 'screen_capture_stream_pending') return t('recording.nativeCapturePendingReason');
    if (nativeCaptureUnavailableReason === 'helper_missing') return t('recording.nativeCaptureHelperMissingReason');
    if (nativeCaptureUnavailableReason === 'macos_required' || nativeCaptureUnavailableReason === 'macos_14_required') {
      return t('recording.nativeCaptureMacosRequiredReason');
    }
    if (nativeCaptureUnavailableReason === 'screen_recording_permission_required') return t('recording.nativeCaptureScreenPermissionReason');
    if (nativeCaptureUnavailableReason === 'microphone_permission_required') return t('recording.nativeCaptureMicPermissionReason');
    return nativeCaptureUnavailableReason || t('recording.nativeCaptureUnavailableUnknown');
  })();

  const needsComputerAudio = sourceMode !== 'mic_only';
  const micReady = nativeCaptureReady
    ? (sourceMode === 'pc_only' || recorder.capturePermissions?.microphone === 'authorized')
    : (sourceMode === 'pc_only' || recorder.microphones.length > 0 || recorder.selectedMicrophone === '');
  const computerReady = nativeCaptureReady
    ? (sourceMode === 'mic_only' || recorder.capturePermissions?.screen_capture === 'granted')
    : (!needsComputerAudio || Boolean(recorder.audioRouteStatus?.ready_to_record) || recorder.systemDevices.length > 0);
  const storageReady = storageConfigured && recordingsDir.trim().length > 0;
  const readyToRecord = micReady && computerReady && storageReady;
  const selectedVisualWindow = captureWindows.find((window) => String(window.id) === visualWindowId);
  const recordingFlowLocked = recorder.isRecording || recorder.isPreparingRecording;

  const captureModeOptions = [
    { value: 'both', label: t('recording.captureModeBoth') },
    { value: 'mic_only', label: t('recording.captureModeMicOnly') },
    {
      value: 'pc_only',
      label: nativeCaptureReady
        ? t('recording.captureModeComputerOnly')
        : t('recording.captureModeComputerOnlyFallback'),
    },
  ] as const;

  useEffect(() => {
    const projectFromWorkspace = sessionStorage.getItem(NEW_RECORDING_PROJECT_STORAGE_KEY);
    if (projectFromWorkspace) {
      setProjectName(projectFromWorkspace);
      sessionStorage.removeItem(NEW_RECORDING_PROJECT_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await ApiClient.getSettings();
        const configuredDir = settings.recordings_dir || '';
        setRecordingsDir(configuredDir);
        setStorageConfigured(Boolean(configuredDir.trim()));
        const projects = await ApiClient.listProjects();
        setProjectsList((projects.items || []).filter((project) => !project.is_unassigned).map((project) => project.name));
      } catch {
        // Readiness below exposes configuration gaps without blocking the rest of the app shell.
      }
    };
    void loadSettings();
  }, []);

  const handleAuthorizeCapture = async () => {
    setPermissionLoading(true);
    setPermissionError(null);
    try {
      const result = await ApiClient.ensureCapturePermissions(sourceMode);
      await recorder.refreshCapturePermissions();
      if (!result.ok) {
        const message = result.diagnostics?.code_signature && result.diagnostics.code_signature !== 'signed'
          ? t('recording.permissionsUnsignedHelper')
          : result.diagnostics?.bundle_identifier && result.diagnostics.bundle_identifier !== 'com.closedroom.nativecapture'
            ? t('recording.permissionsInvalidHelper')
            : t('recording.permissionsRequired');
        setPermissionError(message);
      }
    } catch (err) {
      setPermissionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPermissionLoading(false);
    }
  };

  const loadVisualSources = async () => {
    if (!nativeCaptureReady || visualSourcesLoading) return;
    setVisualSourcesLoading(true);
    setVisualSourcesError(null);
    try {
      const result = await ApiClient.captureWindows();
      setCaptureWindows(result.windows || []);
    } catch (err) {
      setCaptureWindows([]);
      setVisualSourcesError(err instanceof Error ? err.message : String(err));
    } finally {
      setVisualSourcesLoading(false);
    }
  };

  const toggleScreenContext = () => {
    const next = !showScreenContext;
    setShowScreenContext(next);
    if (next && captureWindows.length === 0) void loadVisualSources();
  };

  const persistStorageDir = async (path: string) => {
    if (!path.trim()) return;
    setStorageSaving(true);
    try {
      await ApiClient.updateSettings({ recordings_dir: path.trim() });
      setRecordingsDir(path.trim());
      setStorageConfigured(true);
      showToast(t('transcription.saveSuccessAudioDir'), 'success');
    } catch (err) {
      setStorageConfigured(false);
      showToast(err instanceof Error ? err.message : t('common.error'), 'error');
    } finally {
      setStorageSaving(false);
    }
  };

  const handleBrowseDir = async () => {
    try {
      const result = await ApiClient.selectDirectory();
      if (result?.path) await persistStorageDir(result.path);
    } catch (err) {
      showToast(err instanceof Error ? err.message : t('transcription.browseError'), 'error');
    }
  };

  const statusSummary = (() => {
    if (recorder.isRecording) {
      return { tone: 'recording', title: t('recording.statusRecording'), detail: recorder.progressText };
    }
    if (recorder.isWaitingForAi) {
      return {
        tone: 'working',
        title: lang === 'it' ? 'Preparazione registrazione' : 'Preparing recording',
        detail: lang === 'it'
          ? 'Un’attività AI è già in corso. ClosedRoom la lascia terminare in sicurezza e avvia la registrazione appena le risorse sono libere.'
          : 'AI work is already running. ClosedRoom lets it finish safely and starts recording as soon as resources are free.',
      };
    }
    if (recorder.isPreparingRecording) {
      return {
        tone: 'working',
        title: lang === 'it' ? 'Avvio registrazione' : 'Starting recording',
        detail: lang === 'it'
          ? 'ClosedRoom sta verificando le sorgenti e preparando la registrazione. Il timer partirà solo quando la registrazione è davvero attiva.'
          : 'ClosedRoom is checking sources and preparing capture. The timer starts only when recording is actually active.',
      };
    }
    if (recorder.statusState === 'error') {
      return {
        tone: 'blocked',
        title: recorder.statusText || t('common.error'),
        detail: recorder.progressText || (lang === 'it' ? 'Controlla il problema e riprova.' : 'Check the issue and try again.'),
      };
    }
    if (readyToRecord) {
      return {
        tone: 'ready',
        title: lang === 'it' ? 'Pronto per registrare' : 'Ready to record',
        detail: sourceMode === 'both'
          ? (lang === 'it' ? 'Microfono e audio del computer sono pronti.' : 'Microphone and computer audio are ready.')
          : sourceMode === 'mic_only'
            ? (lang === 'it' ? 'Il microfono è pronto.' : 'Microphone is ready.')
            : (lang === 'it' ? 'L’audio del computer è pronto.' : 'Computer audio is ready.'),
      };
    }
    if (!storageReady) {
      return {
        tone: 'blocked',
        title: lang === 'it' ? 'Scegli dove salvare i meeting' : 'Choose where meetings are saved',
        detail: lang === 'it'
          ? 'Serve una cartella locale prima della prima registrazione.'
          : 'A local folder is required before the first recording.',
      };
    }
    if (nativeCaptureReady && (!micReady || !computerReady)) {
      return {
        tone: 'blocked',
        title: lang === 'it' ? 'ClosedRoom ha bisogno di un permesso' : 'ClosedRoom needs a permission',
        detail: !micReady
          ? (lang === 'it' ? 'Consenti l’accesso al microfono per continuare.' : 'Allow microphone access to continue.')
          : (lang === 'it'
            ? 'Consenti Registrazione schermo per acquisire l’audio del computer.'
            : 'Allow Screen Recording to capture computer audio.'),
      };
    }
    return {
      tone: 'blocked',
      title: lang === 'it' ? 'Configurazione audio da completare' : 'Audio setup needs attention',
      detail: lang === 'it'
        ? 'ClosedRoom non riesce a usare automaticamente l’audio. Apri Recupero audio per scegliere una sorgente.'
        : 'ClosedRoom could not configure audio automatically. Open Audio recovery to choose a source.',
    };
  })();

  const start = () => recorder.startRecording(
    title,
    projectName,
    '',
    sourceMode,
    visualWindowId ? Number(visualWindowId) : undefined,
    selectedVisualWindow
      ? `${selectedVisualWindow.application_name}: ${selectedVisualWindow.title}`
      : '',
  );

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
      <header className="border-b border-border-subtle pb-4">
        <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-accent">{t('header.newMeeting')}</span>
        <h2 className="mt-1 text-2xl font-bold tracking-tight text-text-primary">{t('recording.title')}</h2>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          {lang === 'it'
            ? 'Titolo e progetto sono opzionali. ClosedRoom registra microfono e audio del computer automaticamente quando sono disponibili.'
            : 'Title and project are optional. ClosedRoom records microphone and computer audio automatically when available.'}
        </p>
      </header>

      <Card className="flex flex-col gap-5 p-5 sm:p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label={t('recording.titleLabel')}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={recordingFlowLocked}
            placeholder={t('recording.titlePlaceholder')}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="new-meeting-project" className="text-sm font-medium text-text-secondary">
              {t('recording.projectLabel')}
            </label>
            <input
              id="new-meeting-project"
              list="new-meeting-projects"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              disabled={recordingFlowLocked}
              placeholder={t('recording.projectPlaceholder')}
              className="h-10 w-full rounded-lg border border-border-subtle bg-bg-surface px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-border-focus disabled:cursor-not-allowed disabled:opacity-60"
            />
            <datalist id="new-meeting-projects">
              {projectsList.map((project) => <option key={project} value={project} />)}
            </datalist>
          </div>
        </div>

        <section
          className={`rounded-xl border px-4 py-4 ${
            statusSummary.tone === 'ready'
              ? 'border-success/30 bg-success/10'
              : statusSummary.tone === 'recording'
                ? 'border-danger/30 bg-danger/10'
                : statusSummary.tone === 'working'
                  ? 'border-accent/30 bg-accent-soft'
                  : 'border-warning/30 bg-warning/10'
          }`}
          role="status"
          aria-live="polite"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              {statusSummary.tone === 'ready' ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden="true" />
              ) : statusSummary.tone === 'recording' ? (
                <Mic className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
              ) : statusSummary.tone === 'working' ? (
                <RefreshCw className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : (
                <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-semibold text-text-primary">{statusSummary.title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">{statusSummary.detail}</p>
                {permissionError && <p className="mt-2 text-xs text-danger">{permissionError}</p>}
                {recorder.fallbackNotice && <p className="mt-2 text-xs text-warning">{recorder.fallbackNotice}</p>}
              </div>
            </div>

            {!recordingFlowLocked && !readyToRecord && nativeCaptureReady && storageReady && (
              <Button type="button" size="sm" onClick={handleAuthorizeCapture} isLoading={permissionLoading} className="shrink-0">
                {lang === 'it' ? 'Consenti accesso' : 'Allow access'}
              </Button>
            )}
            {!recordingFlowLocked && !storageReady && (
              <Button type="button" size="sm" variant="secondary" onClick={handleBrowseDir} isLoading={storageSaving} className="shrink-0">
                <FolderOpen className="h-4 w-4" />
                {t('settings.btnBrowse')}
              </Button>
            )}
            {!recordingFlowLocked && !nativeCaptureReady && nativeCaptureChecked && !readyToRecord && storageReady && (
              <Button type="button" size="sm" variant="secondary" onClick={() => setShowAudioRecovery(true)} className="shrink-0">
                <SlidersHorizontal className="h-4 w-4" />
                {lang === 'it' ? 'Recupero audio' : 'Audio recovery'}
              </Button>
            )}
          </div>
        </section>

        {!storageReady && !recordingFlowLocked && (
          <section className="rounded-xl border border-border-subtle bg-bg-surface/30 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1">
                <Input
                  label={t('settings.recordingsFolderLabel')}
                  value={recordingsDir}
                  onChange={(event) => {
                    setRecordingsDir(event.target.value);
                    setStorageConfigured(false);
                  }}
                  placeholder="~/ClosedRoom/Recordings"
                />
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="secondary" onClick={handleBrowseDir} isLoading={storageSaving}>
                  <FolderOpen className="h-4 w-4" />
                  {t('settings.btnBrowse')}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => persistStorageDir(recordingsDir)}
                  isLoading={storageSaving}
                  disabled={!recordingsDir.trim()}
                >
                  {lang === 'it' ? 'Salva' : 'Save'}
                </Button>
              </div>
            </div>
          </section>
        )}

        {/* Keep the canvas mounted so useRecorder can bind its visualizer before capture starts. */}
        <section className={recorder.isRecording ? 'rounded-xl border border-border-subtle bg-bg-elevated p-4' : 'hidden'}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted">{t('recording.statusRecording')}</p>
              <p className="mt-1 font-mono text-4xl font-bold tabular-nums text-text-primary">{recorder.timer}</p>
            </div>
            <div className="grid min-w-[240px] grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-2">
                <span className="block text-text-muted">{lang === 'it' ? 'Microfono' : 'Microphone'}</span>
                <strong className="mt-1 block font-mono text-text-primary">{recorder.signalLevelMic}</strong>
              </div>
              <div className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-2">
                <span className="block text-text-muted">Computer</span>
                <strong className="mt-1 block font-mono text-text-primary">{recorder.signalLevelSystem}</strong>
              </div>
            </div>
          </div>
          <canvas ref={recorder.canvasRef} width={900} height={70} className="mt-4 h-16 w-full rounded-lg bg-bg-surface" aria-hidden="true" />
        </section>

        <div className="flex flex-col gap-3 sm:flex-row">
          {!recorder.isRecording ? (
            <>
              <Button
                type="button"
                size="lg"
                onClick={start}
                isLoading={recorder.isPreparingRecording}
                disabled={recorder.isPreparingRecording || recorder.isVerifying || !readyToRecord}
                className="min-h-12 flex-1 shadow-cta"
              >
                <Mic className="h-5 w-5" />
                {recorder.isWaitingForAi
                  ? (lang === 'it' ? 'In attesa dell’AI…' : 'Waiting for AI…')
                  : recorder.isPreparingRecording
                    ? (lang === 'it' ? 'Avvio registrazione…' : 'Starting recording…')
                    : t('recording.btnStart')}
              </Button>
              {recorder.isWaitingForAi && (
                <Button
                  type="button"
                  size="lg"
                  variant="secondary"
                  onClick={() => recorder.cancelPendingStart()}
                  className="min-h-12"
                >
                  {lang === 'it' ? 'Annulla' : 'Cancel'}
                </Button>
              )}
            </>
          ) : (
            <Button type="button" size="lg" variant="danger" onClick={() => recorder.stopRecording()} className="min-h-12 flex-1">
              <Square className="h-5 w-5" />
              {t('recording.btnStop')}
            </Button>
          )}

          {recorder.isRecording && (
            <Button type="button" size="lg" variant="secondary" onClick={() => openBrowserPopup()} className="min-h-12">
              <PanelTopOpen className="h-5 w-5" />
              {t('recording.btnOverlay')}
            </Button>
          )}
        </div>

        {nativeCaptureReady && !recordingFlowLocked && (
          <section className="rounded-xl border border-border-subtle bg-bg-surface/20">
            <button
              type="button"
              onClick={toggleScreenContext}
              aria-expanded={showScreenContext}
              aria-controls="new-meeting-screen-context"
              className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-xs font-semibold text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <Monitor className="h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
                <span>{lang === 'it' ? 'Contesto schermo (opzionale)' : 'Screen context (optional)'}</span>
                {visualWindowId && (
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-bold text-accent">
                    {lang === 'it' ? 'Attivo' : 'On'}
                  </span>
                )}
              </span>
              <ChevronDown className={`h-4 w-4 shrink-0 text-text-muted transition-transform ${showScreenContext ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>

            {showScreenContext && (
              <div id="new-meeting-screen-context" className="flex flex-col gap-4 border-t border-border-subtle p-4">
                <p className="text-xs leading-relaxed text-text-muted">
                  {lang === 'it'
                    ? 'Disattivato per default. Se scegli una finestra o uno schermo, ClosedRoom salva localmente frame a bassa frequenza. Nessuna AI visuale viene eseguita durante la registrazione.'
                    : 'Off by default. If you choose a window or screen, ClosedRoom stores low-frequency frames locally. No visual AI runs while recording.'}
                </p>
                <Select
                  label={lang === 'it' ? 'Finestra o schermo' : 'Window or screen'}
                  value={visualWindowId}
                  onChange={(event) => setVisualWindowId(event.target.value)}
                  disabled={visualSourcesLoading}
                >
                  <option value="">{lang === 'it' ? 'Non acquisire contesto schermo' : 'Do not capture screen context'}</option>
                  {captureWindows.map((window) => (
                    <option key={window.id} value={window.id}>
                      {window.application_name ? `${window.application_name} — ` : ''}{window.title || `#${window.id}`}
                    </option>
                  ))}
                </Select>
                {visualSourcesError && <p className="text-xs text-warning">{visualSourcesError}</p>}
                <div className="flex items-center justify-between gap-3 text-[11px] text-text-muted">
                  <span>
                    {visualWindowId
                      ? (lang === 'it' ? 'I frame verranno elaborati solo dopo il meeting, su tua richiesta.' : 'Frames are processed only after the meeting, when you ask for it.')
                      : (lang === 'it' ? 'Nessun frame viene acquisito senza una selezione esplicita.' : 'No frames are captured without an explicit selection.')}
                  </span>
                  <Button type="button" size="sm" variant="ghost" onClick={loadVisualSources} isLoading={visualSourcesLoading}>
                    <RefreshCw className="h-3.5 w-3.5" />
                    {lang === 'it' ? 'Aggiorna' : 'Refresh'}
                  </Button>
                </div>
              </div>
            )}
          </section>
        )}

        {!nativeCaptureReady && nativeCaptureChecked && !recordingFlowLocked && (
          <section className="rounded-xl border border-border-subtle bg-bg-surface/20">
            <button
              type="button"
              onClick={() => setShowAudioRecovery((open) => !open)}
              aria-expanded={showAudioRecovery}
              aria-controls="new-meeting-audio-recovery"
              className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-xs font-semibold text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
            >
              <span className="inline-flex items-center gap-2">
                <SlidersHorizontal className="h-4 w-4 text-text-muted" aria-hidden="true" />
                {lang === 'it' ? 'Recupero audio' : 'Audio recovery'}
              </span>
              <ChevronDown className={`h-4 w-4 text-text-muted transition-transform ${showAudioRecovery ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>

            {showAudioRecovery && (
              <div id="new-meeting-audio-recovery" className="flex flex-col gap-5 border-t border-border-subtle p-4">
                <p className="text-xs leading-relaxed text-text-muted">
                  {lang === 'it'
                    ? 'Queste opzioni servono solo quando ClosedRoom non riesce a configurare automaticamente microfono e audio del computer.'
                    : 'Use these options only when ClosedRoom cannot configure microphone and computer audio automatically.'}
                </p>
                <Select
                  label={lang === 'it' ? 'Audio da registrare' : 'Audio to record'}
                  value={sourceMode}
                  onChange={(event) => {
                    setSourceMode(event.target.value as 'both' | 'mic_only' | 'pc_only');
                    setPermissionError(null);
                  }}
                  disabled={recorder.isRecording}
                >
                  {captureModeOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </Select>

                <div className="grid grid-cols-1 gap-4 border-t border-border-subtle pt-4 sm:grid-cols-2">
                  {sourceMode !== 'pc_only' && (
                    <Select
                      label={t('recording.microphoneLabel')}
                      value={recorder.selectedMicrophone}
                      onChange={(event) => recorder.setSelectedMicrophone(event.target.value)}
                      disabled={recorder.isRecording}
                    >
                      <option value="">{t('recording.microphoneDefault')}</option>
                      {recorder.microphones.map((device) => (
                        <option key={device.deviceId} value={device.deviceId}>{device.label || device.deviceId}</option>
                      ))}
                    </Select>
                  )}
                  {sourceMode !== 'mic_only' && (
                    <Select
                      label={t('recording.systemAudioLabel')}
                      value={recorder.selectedSystemDevice}
                      onChange={(event) => recorder.setSelectedSystemDevice(event.target.value)}
                      disabled={recorder.isRecording}
                    >
                      <option value="">{t('recording.systemAudioDefault')}</option>
                      {recorder.systemDevices.map((device) => (
                        <option key={device.deviceId} value={device.deviceId}>{device.label || device.deviceId}</option>
                      ))}
                    </Select>
                  )}
                </div>
              </div>
            )}
          </section>
        )}

        <section className="rounded-xl border border-border-subtle bg-bg-surface/20">
          <button
            type="button"
            onClick={() => setShowDiagnostics((open) => !open)}
            aria-expanded={showDiagnostics}
            aria-controls="new-meeting-diagnostics"
            className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-xs font-semibold text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
          >
            <span className="inline-flex items-center gap-2">
              <Bug className="h-4 w-4" aria-hidden="true" />
              {lang === 'it' ? 'Diagnostica' : 'Diagnostics'}
            </span>
            <ChevronDown className={`h-4 w-4 transition-transform ${showDiagnostics ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>

          {showDiagnostics && (
            <div id="new-meeting-diagnostics" className="flex flex-col gap-4 border-t border-border-subtle p-4 text-xs text-text-secondary">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
                  <span className="block text-[10px] font-bold uppercase tracking-wider text-text-muted">Capture</span>
                  <strong className="mt-1 block text-text-primary">{nativeCaptureReady ? 'Native' : 'Browser fallback'}</strong>
                  {!nativeCaptureReady && nativeCaptureChecked && <p className="mt-1 text-warning">{nativeCaptureUnavailableMessage}</p>}
                </div>
                <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
                  <span className="block text-[10px] font-bold uppercase tracking-wider text-text-muted">Storage</span>
                  <strong className="mt-1 block break-all font-mono text-text-primary">{recordingsDir || t('common.notAvailable')}</strong>
                </div>
              </div>

              {nativeCaptureReady && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
                    <span className="text-text-muted">{lang === 'it' ? 'Microfono' : 'Microphone'}</span>
                    <strong className="mt-1 block text-text-primary">{recorder.capturePermissions?.microphone || 'unknown'}</strong>
                  </div>
                  <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
                    <span className="text-text-muted">Screen Capture</span>
                    <strong className="mt-1 block text-text-primary">{recorder.capturePermissions?.screen_capture || 'unknown'}</strong>
                  </div>
                </div>
              )}

              {recorder.permissionsErrorDetails && (
                <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 font-mono text-[11px] text-text-secondary">
                  <div><strong className="text-text-primary">Executable:</strong> {recorder.permissionsErrorDetails.executable_path || 'N/A'}</div>
                  <div className="mt-1"><strong className="text-text-primary">Bundle:</strong> {recorder.permissionsErrorDetails.bundle_identifier || 'N/A'}</div>
                  <div className="mt-1"><strong className="text-text-primary">Signature:</strong> {recorder.permissionsErrorDetails.code_signature || 'unknown'}</div>
                  <div className="mt-1"><strong className="text-text-primary">Identifier:</strong> {recorder.permissionsErrorDetails.identifier || 'N/A'}</div>
                </div>
              )}

              {!nativeCaptureReady && recorder.audioRouteStatus && (
                <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
                  <div><strong className="text-text-primary">Audio route:</strong> {recorder.audioRouteStatus.ready_to_record ? 'ready' : 'not ready'}</div>
                  {recorder.audioRouteStatus.physical_output && <div className="mt-1">Output: {recorder.audioRouteStatus.physical_output}</div>}
                  {recorder.audioRouteStatus.missing && recorder.audioRouteStatus.missing.length > 0 && (
                    <div className="mt-1 text-warning">Missing: {recorder.audioRouteStatus.missing.join(', ')}</div>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="secondary" onClick={() => recorder.verifyAudioSetup()} isLoading={recorder.isVerifying}>
                  <RefreshCw className="h-4 w-4" />
                  {t('recording.verifyConfig')}
                </Button>
                {nativeCaptureReady && (
                  <Button type="button" size="sm" variant="secondary" onClick={handleAuthorizeCapture} isLoading={permissionLoading}>
                    <Info className="h-4 w-4" />
                    {t('recording.authorizeCapture')}
                  </Button>
                )}
                {!nativeCaptureReady && (
                  <Button type="button" size="sm" variant="secondary" onClick={() => recorder.toggleTestAudioRoute()} isLoading={recorder.isVerifying}>
                    <Monitor className="h-4 w-4" />
                    {recorder.isTestRouted ? t('recording.restoreRoute') : t('recording.testRoute')}
                  </Button>
                )}
              </div>
            </div>
          )}
        </section>
      </Card>

      <p className="text-center text-xs text-text-muted">
        {lang === 'it'
          ? 'Dopo lo stop, ClosedRoom apre il meeting e ti guida alla trascrizione.'
          : 'After you stop, ClosedRoom opens the meeting and guides you to transcription.'}
      </p>
    </div>
  );
}
