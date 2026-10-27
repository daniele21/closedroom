import { useState, useEffect } from 'react';
import { ApiClient, AudioIntelligence, CaptureWindow, ProjectItem, Recording } from '../api/apiClient';
import { NEW_RECORDING_PROJECT_STORAGE_KEY } from '../api/config';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { capturePermissionFailureMessage, getNativeCaptureUnavailableMessage } from '../utils/capturePermissionMessages';
import { useRecorder, openBrowserPopup } from '../hooks/useRecorder';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { Badge } from '../components/ui/Badge';
import { Checkbox } from '../components/ui/Checkbox';
import { ProjectPromptModal } from '../components/ui/ProjectPromptModal';
import { formatBytes, formatProjectDate } from '../utils/formatters';
import AudioIntelligencePanel from './recording/AudioIntelligencePanel';
import { recordingTranscriptionRoute } from '../utils/transcriptionRoute';

interface RecordingPageProps {
  detailId: string | null;
  navigateTo: (page: string, detail?: string | null) => void;
}

const captureWindowLabel = (source: CaptureWindow) =>
  [source.application_name, source.title].filter(Boolean).join(' — ');

export default function RecordingPage({ detailId, navigateTo }: RecordingPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const [projectDetail, setProjectDetail] = useState<ProjectItem | null>(null);
  const [audioIntelligence, setAudioIntelligence] = useState<AudioIntelligence | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState('');

  // New Recording Form State
  const [title, setTitle] = useState('');
  const [projectName, setProjectName] = useState('');
  const [sourceMode, setSourceMode] = useState<'both' | 'mic_only' | 'pc_only'>('both');
  const [recordingsDir, setRecordingsDir] = useState('');
  const [visualIntelligenceEnabled, setVisualIntelligenceEnabled] = useState(false);
  const [speakerDiarizationEnabled, setSpeakerDiarizationEnabled] = useState(false);
  const [visualModel, setVisualModel] = useState('');
  const [captureWindows, setCaptureWindows] = useState<CaptureWindow[]>([]);
  const [selectedVisualWindowId, setSelectedVisualWindowId] = useState('');
  const [captureWindowsLoading, setCaptureWindowsLoading] = useState(false);
  const [captureWindowsError, setCaptureWindowsError] = useState('');
  const [enrichmentSaving, setEnrichmentSaving] = useState<'diarization' | 'visual' | null>(null);

  // Project suggestions (datalist)
  const [projectsList, setProjectsList] = useState<string[]>([]);
  const [showAdvancedAudio, setShowAdvancedAudio] = useState(false);
  const [showSetupInfo, setShowSetupInfo] = useState(false);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionError, setPermissionError] = useState<string | null>(null);

  const onRecordingSaved = (recording: Recording) => {
    // A saved recording is reviewed in the canonical Meeting workspace.
    navigateTo('meeting', recording.id);
  };

  const recorder = useRecorder(onRecordingSaved);
  const nativeCaptureReady = recorder.captureCapabilities?.default_backend === 'native' && recorder.captureCapabilities.native.available;
  const nativeCaptureChecked = Boolean(recorder.captureCapabilities);
  const nativeCaptureUnavailableReason = recorder.captureCapabilities?.native.reason || recorder.captureCapabilities?.native.error || '';
  const nativeCaptureUnavailableMessage = getNativeCaptureUnavailableMessage(nativeCaptureUnavailableReason, t);

  const needsComputerAudio = sourceMode !== 'mic_only';
  const micReady = nativeCaptureReady
    ? (sourceMode === 'pc_only' || recorder.capturePermissions?.microphone === 'authorized')
    : (sourceMode === 'pc_only' || recorder.microphones.length > 0 || recorder.selectedMicrophone === '');
  const visualCaptureSelected = visualIntelligenceEnabled && selectedVisualWindowId !== '';
  const selectedVisualWindow = captureWindows.find((window) => String(window.id) === selectedVisualWindowId);
  const visualCaptureLabel = selectedVisualWindow
    ? captureWindowLabel(selectedVisualWindow)
    : '';
  const computerReady = nativeCaptureReady
    ? ((sourceMode === 'mic_only' && !visualCaptureSelected) || recorder.capturePermissions?.screen_capture === 'granted')
    : (!needsComputerAudio || Boolean(recorder.audioRouteStatus?.ready_to_record) || recorder.systemDevices.length > 0);
  const storageReady = recordingsDir.trim().length > 0;
  const readyToRecord = nativeCaptureReady
    ? ((recorder.capturePermissions?.modes?.[sourceMode]?.ok ?? false) && storageReady)
    : (micReady && computerReady && storageReady);
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
  const microphoneStatusLabel = (status?: string) => {
    switch (status) {
      case 'authorized':
        return t('recording.permissionMicAuthorized');
      case 'notDetermined':
        return t('recording.permissionMicNotDetermined');
      case 'denied':
        return t('recording.permissionMicDenied');
      case 'restricted':
        return t('recording.permissionMicRestricted');
      default:
        return t('recording.permissionMicUnknown');
    }
  };

  useEffect(() => {
    if (detailId) return;
    const projectFromWorkspace = sessionStorage.getItem(NEW_RECORDING_PROJECT_STORAGE_KEY);
    if (!projectFromWorkspace) return;
    setProjectName(projectFromWorkspace);
    sessionStorage.removeItem(NEW_RECORDING_PROJECT_STORAGE_KEY);
  }, [detailId]);
  const screenCaptureStatusLabel = (status?: string) => {
    if (status === 'granted') return t('recording.permissionScreenGranted');
    if (status === 'required') return t('recording.permissionScreenRequired');
    return t('recording.permissionScreenUnknown');
  };
  const handleAuthorizeCapture = async () => {
    setPermissionLoading(true);
    setPermissionError(null);
    try {
      const permissionMode = visualCaptureSelected && sourceMode === 'mic_only' ? 'both' : sourceMode;
      const result = await ApiClient.ensureCapturePermissions(permissionMode);
      await recorder.refreshCapturePermissions();
      if (!result.ok) {
        setPermissionError(capturePermissionFailureMessage(result.diagnostics, t));
      }
    } catch (err) {
      setPermissionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPermissionLoading(false);
    }
  };
  const userQualityWarnings = (recording?: Recording | null) => {
    const warnings = recording?.warnings || [];
    return warnings
      .filter((warning) => !/^track_.*_invalid$/.test(warning) && !warning.startsWith('Visual') && !warning.includes('ScreenCaptureKit'))
      .map((warning) => {
        if (warning === 'track_mic_empty') return t('recording.qualityMicEmpty');
        if (warning === 'track_system_empty') return t('recording.qualitySystemEmpty');
        if (warning === 'track_mixed_empty') return t('recording.qualityMixedEmpty');
        if (warning === 'sync_duration_warning') return t('recording.qualitySyncWarning');
        if (warning === 'sync_duration_serious_warning') return t('recording.qualitySyncSeriousWarning');
        if (warning === 'sync_duration_unreliable') return t('recording.qualitySyncUnreliable');
        return warning;
      });
  };

  // Load Settings for recordings directory
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await ApiClient.getSettings();
        setRecordingsDir(settings.recordings_dir || '');
        setSpeakerDiarizationEnabled(Boolean(settings.speaker_diarization_enabled));
        setVisualIntelligenceEnabled(Boolean(settings.visual_intelligence_enabled));
        setVisualModel(settings.visual_llm_model || '');
        
        const projs = await ApiClient.listProjects();
        setProjectsList(
          (projs.items || [])
            .filter((p) => !p.is_unassigned)
            .map((p) => p.name)
        );
      } catch {}
    };
    loadSettings();
  }, []);

  const updateEnrichmentSetting = async (
    setting: 'speaker_diarization_enabled' | 'visual_intelligence_enabled',
    enabled: boolean,
  ) => {
    const previous = setting === 'speaker_diarization_enabled'
      ? speakerDiarizationEnabled
      : visualIntelligenceEnabled;
    const savingKey = setting === 'speaker_diarization_enabled' ? 'diarization' : 'visual';
    if (setting === 'speaker_diarization_enabled') setSpeakerDiarizationEnabled(enabled);
    else setVisualIntelligenceEnabled(enabled);
    setEnrichmentSaving(savingKey);
    try {
      await ApiClient.updateSettings({ [setting]: enabled });
    } catch (err) {
      if (setting === 'speaker_diarization_enabled') setSpeakerDiarizationEnabled(previous);
      else setVisualIntelligenceEnabled(previous);
      showToast(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setEnrichmentSaving(null);
    }
  };

  const refreshCaptureWindows = async () => {
    setCaptureWindowsLoading(true);
    setCaptureWindowsError('');
    try {
      const result = await ApiClient.captureWindows();
      setCaptureWindows(result.windows || []);
    } catch (err) {
      setCaptureWindows([]);
      setCaptureWindowsError(err instanceof Error ? err.message : String(err));
    } finally {
      setCaptureWindowsLoading(false);
    }
  };

  useEffect(() => {
    if (!nativeCaptureReady || !visualIntelligenceEnabled || detailId) {
      setCaptureWindows([]);
      setSelectedVisualWindowId('');
      return;
    }
    refreshCaptureWindows();
  }, [nativeCaptureReady, visualIntelligenceEnabled, detailId]);

  // Load Project Detail if detailId is provided
  useEffect(() => {
    const loadProjectDetail = async () => {
      if (!detailId) {
        setProjectDetail(null);
        setAudioIntelligence(null);
        return;
      }
      try {
        setDetailLoading(true);
        const data = await ApiClient.recordingProject(detailId);
        setProjectDetail(data);
        if (data.transcription) {
          setIntelligenceLoading(true);
          ApiClient.recordingIntelligence(detailId)
            .then(setAudioIntelligence)
            .catch(() => setAudioIntelligence(null))
            .finally(() => setIntelligenceLoading(false));
        } else {
          setIntelligenceLoading(false);
          setAudioIntelligence(null);
        }
      } catch (err: any) {
        showToast(err.message || 'Errore nel caricamento dei dettagli del progetto', 'error');
        navigateTo('recording');
      } finally {
        setDetailLoading(false);
      }
    };
    loadProjectDetail();
  }, [detailId, navigateTo, showToast]);

  const handleConfirmProject = async (newProj: string) => {
    if (!projectDetail) return;
    try {
      await ApiClient.updateRecording(projectDetail.recording.id, { project_name: newProj });
      showToast('Progetto aggiornato!', 'success');
      const updated = await ApiClient.recordingProject(projectDetail.recording.id);
      setProjectDetail(updated);
      setIsProjectModalOpen(false);
    } catch (err: any) {
      showToast(err.message || 'Errore durante l\'aggiornamento del progetto', 'error');
    }
  };

  const handleSaveTitle = async () => {
    if (!projectDetail) return;
    const cleanTitle = editTitleValue.trim();
    if (!cleanTitle) {
      showToast(t('transcription.titleEmptyError') || 'Il titolo non può essere vuoto', 'error');
      return;
    }
    try {
      await ApiClient.updateRecording(projectDetail.recording.id, { title: cleanTitle });
      showToast(t('transcription.titleSaveSuccess') || 'Titolo aggiornato!', 'success');
      setIsEditingTitle(false);
      const updated = await ApiClient.recordingProject(projectDetail.recording.id);
      setProjectDetail(updated);
    } catch (err: any) {
      showToast(t('transcription.titleSaveError', { error: err.message }) || 'Impossibile salvare il titolo', 'error');
    }
  };

  const handleSaveSettings = async () => {
    try {
      await ApiClient.updateSettings({ recordings_dir: recordingsDir.trim() });
      showToast(t('transcription.saveSuccessAudioDir'), 'success');
    } catch (err: any) {
      showToast(err.message || 'Impossibile salvare la directory', 'error');
    }
  };

  const handleBrowseDir = async () => {
    try {
      const result = await ApiClient.selectDirectory();
      if (result && result.path) {
        setRecordingsDir(result.path);
        showToast(t('transcription.browseSelectDir'), 'info');
      }
    } catch (err: any) {
      showToast(err.message || t('transcription.browseError'), 'error');
    }
  };



  // 1. NESTED PROJECT DETAIL VIEW
  if (detailId && projectDetail) {
    const recording = projectDetail.recording;
    const transcription = projectDetail.transcription;
    const analysis = projectDetail.analysis;

    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-border-subtle pb-3 gap-2">
          <div>
            <span className="text-[10px] font-bold text-accent tracking-wider uppercase">RECORDINGS</span>
            {isEditingTitle ? (
              <div className="flex items-center gap-2 mt-1">
                <input
                  type="text"
                  className="px-3 py-1.5 bg-bg-surface border border-border-focus rounded-lg text-sm focus:outline-none text-text-primary font-bold text-xl"
                  value={editTitleValue}
                  onChange={(e) => setEditTitleValue(e.target.value)}
                  maxLength={200}
                />
                <Button size="sm" onClick={handleSaveTitle}>
                  Salva
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setIsEditingTitle(false)}>
                  {t('common.cancel')}
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2 mt-1">
                <h2 className="text-2xl font-bold text-text-primary">{recording.title}</h2>
                <button
                  onClick={() => {
                    setIsEditingTitle(true);
                    setEditTitleValue(recording.title);
                  }}
                  className="text-text-muted hover:text-text-primary transition-colors cursor-pointer"
                  title="Rinomina"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-4 h-4">
                    <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </button>
              </div>
            )}
            <p className="text-xs text-text-secondary mt-1">
              {formatProjectDate(recording.created_at, lang)} · {formatBytes(recording.bytes_written || 0)}
            </p>
          </div>
          <Button variant="ghost" onClick={() => navigateTo('recording')}>
            {t('recording.btnBackToRecording')}
          </Button>
        </div>

        {detailLoading ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin"></div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Audio card */}
            <Card className="flex flex-col justify-between gap-4">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-accent font-bold">01</span>
                  <h3 className="text-sm font-bold text-text-primary">Audio</h3>
                </div>
                <audio
                  controls
                  src={`/v1/recordings/${recording.id}/audio`}
                  className="w-full mt-2"
                ></audio>
                <p className="text-xs text-text-secondary mt-2 truncate">
                  {recording.audio_file || 'Audio locale'}
                </p>
                {recording.audio_tracks && recording.audio_tracks.length > 1 && (
                  <div className="flex flex-col gap-2 mt-2">
                    <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
                      Tracce sorgente
                    </span>
                    {recording.audio_tracks
                      .filter((track) => !track.primary)
                      .map((track) => (
                        <div key={track.id} className="flex flex-col gap-1.5 p-2 rounded-lg border border-border-subtle/70 bg-bg-surface/40">
                          <div className="flex items-center justify-between text-[10px] text-text-secondary font-bold uppercase tracking-wider">
                            <span>{track.source === 'mic' ? '🎙️' : '🖥️'} {track.label}</span>
                            <span>{formatBytes(track.bytes_written || 0)}</span>
                          </div>
                          <audio
                            controls
                            src={`/v1/recordings/${recording.id}/tracks/${track.id}/audio`}
                            className="w-full h-8"
                          />
                        </div>
                      ))}
                  </div>
                )}
                <p className="text-xs text-text-secondary">
                  <strong>Progetto:</strong> {recording.project_name || 'Senza progetto'}
                </p>
                {(recording.quality_report || (recording.warnings && recording.warnings.length > 0)) && (() => {
                  const qualityWarnings = userQualityWarnings(recording);
                  const hasProbeOnlyWarning = (recording.warnings || []).some((warning) => /^track_.*_invalid$/.test(warning));
                  return (
                  <div className="mt-2 rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-3 text-xs text-text-secondary">
                    <div className="flex items-center justify-between font-bold text-text-primary">
                      <span>{t('recording.qualityTitle')}</span>
                      <span className={qualityWarnings.length ? 'text-warning' : 'text-success'}>
                        {qualityWarnings.length ? t('recording.qualityCheck') : t('recording.qualityOk')}
                      </span>
                    </div>
                    {recording.quality_report?.sync?.duration_delta_ms != null && (
                      <p className="mt-1">
                        {t('recording.qualitySyncLabel')}: {recording.quality_report.sync.duration_delta_ms} ms
                      </p>
                    )}
                    {qualityWarnings.length > 0 && (
                      <p className="mt-1 text-warning">
                        {qualityWarnings.slice(0, 3).join(' · ')}
                      </p>
                    )}
                    {qualityWarnings.length === 0 && hasProbeOnlyWarning && (
                      <p className="mt-1 text-text-muted">
                        {t('recording.qualityProbeUnavailable')}
                      </p>
                    )}
                  </div>
                  );
                })()}
              </div>
              <Button
                variant="secondary"
                onClick={() => setIsProjectModalOpen(true)}
              >
                Cambia progetto
              </Button>
            </Card>

            {/* Transcription card */}
            <Card className="flex flex-col justify-between gap-4">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-accent font-bold">02</span>
                  <h3 className="text-sm font-bold text-text-primary">{t('projects.transcription')}</h3>
                </div>
                <p className="text-xs text-text-secondary leading-relaxed mt-2 line-clamp-5">
                  {transcription ? transcription.text : 'Nessuna trascrizione collegata.'}
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (transcription) {
                      navigateTo('transcription', transcription.id);
                    } else {
                      navigateTo('transcription', recordingTranscriptionRoute(recording.id));
                    }
                  }}
                >
                  {transcription ? 'Apri trascrizione' : 'Trascrivi audio'}
                </Button>
                {transcription && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      const confirmText = lang === 'it' 
                        ? "Sei sicuro di voler trascrivere nuovamente questo audio? La nuova trascrizione sostituirà quella precedente nei risultati principali."
                        : "Are you sure you want to transcribe this audio again? The new transcription will replace the previous one in the main results.";
                      if (window.confirm(confirmText)) {
                        navigateTo('transcription', recordingTranscriptionRoute(recording.id, 'retranscribe'));
                      }
                    }}
                  >
                    🔄 {lang === 'it' ? 'Trascrivi di nuovo' : 'Transcribe again'}
                  </Button>
                )}
              </div>
            </Card>

            {/* Analysis card */}
            <Card className="flex flex-col justify-between gap-4">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-accent font-bold">03</span>
                  <h3 className="text-sm font-bold text-text-primary">{t('projects.analysis')}</h3>
                </div>
                <p className="text-xs text-text-secondary leading-relaxed mt-2 line-clamp-5">
                  {analysis ? (analysis.summary || analysis.title || 'Analisi disponibile.') : 'Nessuna analisi collegata.'}
                </p>
              </div>
              <Button
                variant="secondary"
                disabled={!transcription}
                onClick={() => {
                  if (!transcription) return;
                  navigateTo('analysis', transcription.id);
                }}
              >
                {!transcription ? 'Trascrivi prima' : (analysis ? 'Apri analisi' : 'Genera analisi')}
              </Button>
            </Card>
            <AudioIntelligencePanel
              intelligence={audioIntelligence}
              loading={intelligenceLoading}
              hasTranscription={Boolean(transcription)}
              onTranscribe={() => navigateTo('transcription', recordingTranscriptionRoute(recording.id))}
            />
          </div>
        )}
        <ProjectPromptModal
          isOpen={isProjectModalOpen}
          initialValue={recording.project_name || ''}
          onConfirm={handleConfirmProject}
          onCancel={() => setIsProjectModalOpen(false)}
          existingProjects={projectsList}
        />
      </div>
    );
  }

  // 2. RECORDER DASHBOARD VIEW
  return (
    <div className="flex flex-col gap-6">
      <div className="border-b border-border-subtle pb-3">
        <span className="text-xs font-bold text-accent tracking-widest uppercase">{t('recording.title')}</span>
        <h2 className="text-2xl font-bold text-text-primary mt-1">{t('recording.panelTitle')}</h2>
        <p className="text-xs text-text-secondary mt-1">{t('recording.panelDesc')}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column: Controls Panel */}
        <Card className="lg:col-span-2 flex flex-col gap-5">
          <div className="flex items-center justify-between border-b border-border-subtle pb-2">
            <h3 className="text-sm font-bold text-text-primary uppercase tracking-wider">
              {t('recording.recordingLocal')}
            </h3>
            <Badge variant={recorder.isRecording ? 'online' : 'idle'} pulse={recorder.isRecording}>
              {recorder.statusText}
            </Badge>
          </div>

          {recorder.fallbackNotice && (
            <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
              {recorder.fallbackNotice}
            </div>
          )}

          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Input
                label={t('recording.formTitleLabel')}
                placeholder={t('recording.formTitlePlaceholder')}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={recorder.isRecording}
              />

              <div className="flex flex-col gap-1.5 w-full relative">
                <label htmlFor="recording-project" className="text-sm font-medium text-text-secondary">
                  {t('recording.formProjectLabel')}
                </label>
                <input
                  id="recording-project"
                  type="text"
                  list="projects-datalist"
                  placeholder={t('recording.formProjectPlaceholder') || 'Nome progetto o meeting'}
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  disabled={recorder.isRecording}
                  className="px-4 py-2 bg-bg-surface border border-border-subtle rounded-lg text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-border-focus focus:ring-1 focus:ring-border-focus transition-all duration-150 disabled:opacity-50"
                />
                <datalist id="projects-datalist">
                  {projectsList.map((p, idx) => (
                    <option key={idx} value={p} />
                  ))}
                </datalist>
              </div>
            </div>

            {/* Signal panel & timer */}
            <div className="flex flex-col sm:flex-row items-center justify-between p-4 bg-bg-surface border border-border-subtle rounded-xl gap-4">
              <div className="flex items-center gap-4">
                <span className={`w-3.5 h-3.5 rounded-full bg-danger shadow-[0_0_8px_var(--danger)] ${recorder.isRecording ? 'animate-pulse' : 'opacity-40'}`}></span>
                <span className="text-3xl font-mono font-bold">{recorder.timer}</span>
              </div>
              <div className="text-xs text-text-secondary text-right">
                <span className="block font-medium">{recorder.progressText}</span>
                <span className="block text-text-muted mt-0.5">
                  🎙️ Mic: <strong className="text-text-primary mr-2">{recorder.signalLevelMic}</strong>
                  🖥️ PC: <strong className="text-text-primary">{recorder.signalLevelSystem}</strong>
                </span>
              </div>
            </div>

            {/* Canvas Meter */}
            <div className="relative w-full h-40 bg-bg-surface border border-border-subtle rounded-xl overflow-hidden">
              <canvas
                ref={recorder.canvasRef}
                width="960"
                height="240"
                className="w-full h-full object-cover"
              ></canvas>
              <div className="absolute bottom-2 right-4 flex gap-4 text-[10px] text-text-muted select-none">
                <span>-48</span><span>-36</span><span>-24</span><span>-12</span><span>-6</span><span>0 dB</span>
              </div>
            </div>

            {recorder.permissionsErrorDetails && (
              <div className="p-5 border border-danger/30 bg-danger/5 rounded-xl flex flex-col gap-4 text-xs text-text-secondary animate-in fade-in duration-200">
                <div className="flex items-center gap-2 text-danger font-bold text-sm">
                  <span>⚠️</span>
                  <span>{t('recording.permissionsErrorTitle') || 'Dettagli Errore Permessi macOS'}</span>
                </div>
                <p className="text-text-primary font-medium">
                  {recorder.permissionsErrorDetails.code_signature === 'unsigned'
                    ? (t('recording.permissionsUnsignedHelper') || 'Il componente nativo di registrazione non è firmato correttamente. Reinstalla o ricompila ClosedRoom.')
                    : (t('recording.permissionsErrorDesc') || 'ClosedRoom non riesce ad accedere al microfono o all\'audio di sistema dal processo di cattura nativo.')}
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-3 rounded-lg bg-bg-surface/50 border border-border-subtle/70 font-mono text-[10px] text-text-muted">
                  <div>
                    <span className="block text-text-secondary font-bold mb-1">Processo effettivo:</span>
                    <span className="block break-all bg-bg-surface p-1.5 rounded border border-border-subtle select-all">
                      {recorder.permissionsErrorDetails.executable_path || 'N/A'}
                    </span>
                    <span className="block mt-2 text-text-secondary font-bold mb-1">Bundle identifier:</span>
                    <span className="block break-all bg-bg-surface p-1.5 rounded border border-border-subtle select-all">
                      {recorder.permissionsErrorDetails.bundle_identifier || 'N/A'}
                    </span>
                  </div>
                  <div>
                    <span className="block text-text-secondary font-bold mb-1">Stato macOS rilevato:</span>
                    <span className="block">
                      🔏 Code Signature: <strong className={recorder.permissionsErrorDetails.code_signature === 'signed' ? 'text-success' : 'text-danger'}>
                        {recorder.permissionsErrorDetails.code_signature}
                      </strong>
                    </span>
                    <span className="block mt-1">
                      🎤 Microphone: <strong className={recorder.permissionsErrorDetails.microphone === 'authorized' ? 'text-success' : 'text-danger'}>
                        {recorder.permissionsErrorDetails.microphone}
                      </strong>
                    </span>
                    <span className="block mt-1">
                      🖥️ Screen Capture: <strong className={recorder.permissionsErrorDetails.screen_capture === 'granted' ? 'text-success' : 'text-danger'}>
                        {recorder.permissionsErrorDetails.screen_capture}
                      </strong>
                    </span>
                    {recorder.permissionsErrorDetails.identifier && (
                      <span className="block mt-1">
                        Identifier: <strong className="text-text-primary">{recorder.permissionsErrorDetails.identifier}</strong>
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <span className="font-bold text-text-primary">{t('recording.permissionsActionsTitle') || 'Azioni consigliate:'}</span>
                  <ul className="list-disc pl-4 flex flex-col gap-1.5 text-text-secondary">
                    <li>{t('recording.permissionsAction1') || 'Riavvia ClosedRoom dopo aver concesso i permessi in Impostazioni di Sistema.'}</li>
                    <li>
                      {t('recording.permissionsAction2') || 'Se sei in dev mode, esegui il reset pratico dei permessi TCC dal terminale:'}
                      <pre className="mt-1.5 p-2 bg-bg-surface rounded border border-border-subtle text-[10px] font-mono text-text-muted select-all">
                        tccutil reset Microphone{"\n"}
                        tccutil reset ScreenCapture
                      </pre>
                    </li>
                    <li>{t('recording.permissionsAction3') || 'Se il problema persiste, verifica che l\'eseguibile sia firmato e abbia gli entitlements corretti.'}</li>
                  </ul>
                </div>
              </div>
            )}

            {/* Meeting intelligence is an explicit recording decision, not a hidden default. */}
            <section className="rounded-xl border border-border-subtle bg-bg-surface/20 p-4 flex flex-col gap-4">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">{t('recording.intelligenceTitle')}</h3>
                  <p className="text-xs text-text-muted mt-1">{t('recording.intelligenceDesc')}</p>
                </div>
                <Badge variant={speakerDiarizationEnabled && visualCaptureSelected ? 'success' : 'warning'}>
                  {speakerDiarizationEnabled && visualCaptureSelected
                    ? t('recording.intelligenceReady')
                    : t('recording.intelligencePartial')}
                </Badge>
              </div>

              <div className="flex flex-col gap-2">
                <Checkbox
                  variant="toggle"
                  label={t('settings.speakerDiarization')}
                  checked={speakerDiarizationEnabled}
                  disabled={Boolean(enrichmentSaving) || recorder.isRecording}
                  onChange={(event) => updateEnrichmentSetting('speaker_diarization_enabled', event.target.checked)}
                />
                <p className="text-xs text-text-muted pl-[52px]">{t('recording.diarizationInlineDesc')}</p>
              </div>

              <div className="flex flex-col gap-3 border-t border-border-subtle pt-4">
                <Checkbox
                  variant="toggle"
                  label={t('settings.visualIntelligence')}
                  checked={visualIntelligenceEnabled}
                  disabled={Boolean(enrichmentSaving) || recorder.isRecording}
                  onChange={(event) => updateEnrichmentSetting('visual_intelligence_enabled', event.target.checked)}
                />

                {visualIntelligenceEnabled && !nativeCaptureReady && (
                  <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-text-secondary">
                    <strong className="text-warning">{t('recording.visualUnavailableTitle')}</strong>
                    <p className="mt-1">{t('recording.visualUnavailableDesc')}</p>
                  </div>
                )}

                {visualIntelligenceEnabled && nativeCaptureReady && (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-end gap-2">
                      <div className="flex-1 min-w-0">
                        <Select
                          label={t('recording.visualWindowLabel')}
                          value={selectedVisualWindowId}
                          onChange={(event) => setSelectedVisualWindowId(event.target.value)}
                          disabled={captureWindowsLoading || recorder.isRecording}
                        >
                          <option value="">
                            {captureWindowsLoading ? t('recording.visualWindowsLoading') : t('recording.visualWindowDisabled')}
                          </option>
                          {captureWindows.map((window) => (
                            <option key={window.id} value={window.id}>
                              {captureWindowLabel(window)}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={refreshCaptureWindows}
                        disabled={captureWindowsLoading || recorder.isRecording}
                      >
                        {t('recording.visualWindowsRefresh')}
                      </Button>
                    </div>
                    {captureWindowsError && <p className="text-xs text-danger">{captureWindowsError}</p>}
                    {!captureWindowsLoading && !captureWindowsError && captureWindows.length === 0 && (
                      <p className="text-xs text-warning">{t('recording.visualWindowsEmpty')}</p>
                    )}
                    <p className="text-xs text-text-muted">
                      {t('recording.visualModelDesc', { model: visualModel || t('common.notAvailable') })}
                    </p>
                    {visualCaptureLabel && (
                      <div
                        className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
                          recorder.isRecording
                            ? 'border-success/35 bg-success/10 text-success'
                            : 'border-accent/30 bg-accent/10 text-text-secondary'
                        }`}
                      >
                        <span className={recorder.isRecording ? 'animate-pulse' : ''} aria-hidden="true">◉</span>
                        <p>
                          <strong>
                            {recorder.isRecording
                              ? t('recording.visualCaptureActive')
                              : t('recording.visualCaptureSelected')}
                          </strong>
                          {' '}
                          {visualCaptureLabel}
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {visualIntelligenceEnabled && !speakerDiarizationEnabled && (
                  <p className="text-xs text-warning">{t('recording.visualNeedsDiarization')}</p>
                )}
              </div>
            </section>

            {/* Controls Actions */}
            <div className="flex flex-wrap gap-4 mt-2">
              {!recorder.isRecording ? (
                <>
                  <Button
                    size="lg"
                    className="flex-1 min-w-[200px]"
                    onClick={() => recorder.startRecording(
                      title,
                      projectName,
                      '',
                      sourceMode,
                      visualCaptureSelected ? Number(selectedVisualWindowId) : undefined,
                      visualCaptureSelected ? visualCaptureLabel : '',
                    )}
                    disabled={recorder.isVerifying || !readyToRecord}
                  >
                    🎙️ {t('recording.btnStart')}
                  </Button>
                   <Button
                    size="lg"
                    variant="secondary"
                    className="px-4"
                    onClick={async () => {
                      try {
                        const res = await ApiClient.toggleOverlay(true);
                        if (!res.success) openBrowserPopup();
                      } catch {
                        openBrowserPopup();
                      }
                    }}
                    title="Mostra la miniatura fluttuante di registrazione"
                  >
                    🖥️ {t('recording.btnShowOverlay') || 'Miniatura'}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="lg"
                    variant="danger"
                    className="flex-1 min-w-[200px]"
                    onClick={recorder.stopRecording}
                  >
                    ⏹ {t('recording.btnStop')}
                  </Button>
                   <Button
                    size="lg"
                    variant="secondary"
                    className="px-4"
                    onClick={async () => {
                      try {
                        const res = await ApiClient.toggleOverlay(true);
                        if (!res.success) openBrowserPopup();
                      } catch {
                        openBrowserPopup();
                      }
                    }}
                    title="Mostra la miniatura fluttuante di registrazione"
                  >
                    🖥️ {t('recording.btnShowOverlay') || 'Miniatura'}
                  </Button>
                </>
              )}
            </div>

            {/* Capture backend and advanced fallback details */}
            <div className="border border-border-subtle rounded-xl overflow-hidden mt-2">
              <button
                type="button"
                onClick={() => setShowAdvancedAudio(!showAdvancedAudio)}
                className="w-full p-4 flex items-center justify-between text-sm font-semibold text-text-primary bg-bg-surface/30 cursor-pointer"
              >
                <span>{nativeCaptureReady ? '✅' : '⚠️'} {t('recording.captureBackendTitle')}</span>
                <span className={`transform transition-transform ${showAdvancedAudio ? 'rotate-180' : ''}`}>▼</span>
              </button>

              {showAdvancedAudio && (
                <div className="p-4 flex flex-col gap-4 border-t border-border-subtle bg-bg-surface/10 animate-in fade-in duration-200">
                  {nativeCaptureReady ? (
                    <div className="rounded-lg border border-success/30 bg-success/10 p-3 text-xs text-text-secondary flex flex-col gap-3">
                      <div>
                        <strong className="block text-text-primary mb-1">
                          {t('recording.nativeCaptureTitle')}
                        </strong>
                        <p>{t('recording.nativeCaptureDesc')}</p>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <span>{microphoneStatusLabel(recorder.capturePermissions?.microphone)}</span>
                        <span>{screenCaptureStatusLabel(recorder.capturePermissions?.screen_capture)}</span>
                      </div>
                      {!readyToRecord && (
                        <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center pt-2 border-t border-success/20">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            onClick={handleAuthorizeCapture}
                            disabled={permissionLoading}
                          >
                            {permissionLoading ? t('common.loading') : t('recording.btnAuthorizeCapture')}
                          </Button>
                          {permissionError && (
                            <span className="text-[11px] text-danger">{permissionError}</span>
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    <>
                      <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-text-secondary">
                        <strong className="block text-text-primary mb-1">
                          {nativeCaptureChecked ? t('recording.nativeCaptureUnavailableTitle') : t('recording.nativeCaptureCheckingTitle')}
                        </strong>
                        <p>
                          {nativeCaptureChecked
                            ? t('recording.nativeCaptureUnavailableDesc', { reason: nativeCaptureUnavailableMessage })
                            : t('recording.nativeCaptureCheckingDesc')}
                        </p>
                        {nativeCaptureChecked && (nativeCaptureUnavailableReason === 'screen_recording_permission_required' || nativeCaptureUnavailableReason === 'microphone_permission_required') && (
                          <div className="mt-3 pt-3 border-t border-warning/20 text-[11px] flex flex-col gap-1.5">
                            <strong className="text-text-primary">{t('recording.nativeCaptureInstructionsTitle')}</strong>
                            <ol className="list-decimal pl-4 flex flex-col gap-1 text-text-secondary">
                              <li>{t('recording.nativeCaptureInstructionStep1')}</li>
                              <li>
                                {nativeCaptureUnavailableReason === 'screen_recording_permission_required'
                                  ? t('recording.nativeCaptureInstructionStep2Screen')
                                  : t('recording.nativeCaptureInstructionStep2Mic')}
                              </li>
                              <li>{t('recording.nativeCaptureInstructionStep3')}</li>
                            </ol>
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <Select
                          label={t('recording.microphone')}
                          value={recorder.selectedMicrophone}
                          onChange={(e) => recorder.setSelectedMicrophone(e.target.value)}
                        >
                          <option value="">{t('recording.deviceAuto')}</option>
                          {recorder.microphones.map((d) => (
                            <option key={d.deviceId} value={d.deviceId}>
                              {d.label}
                            </option>
                          ))}
                        </Select>

                        <Select
                          label={t('recording.computerAudio')}
                          value={recorder.selectedSystemDevice}
                          onChange={(e) => recorder.setSelectedSystemDevice(e.target.value)}
                        >
                          {recorder.systemDevices.length === 0 ? (
                            <option value="">{t('recording.searchingBlackhole')}</option>
                          ) : (
                            recorder.systemDevices.map((d) => (
                              <option key={d.deviceId} value={d.deviceId}>
                                {d.label}
                              </option>
                            ))
                          )}
                        </Select>
                      </div>
                    </>
                  )}

                  <Select
                    label={t('recording.captureModeLabel')}
                    value={sourceMode}
                    onChange={(e) => setSourceMode(e.target.value as any)}
                  >
                    {captureModeOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>

                  {!nativeCaptureReady && (
                    <div className="flex gap-3 mt-1">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="flex-1"
                        onClick={recorder.toggleTestAudioRoute}
                        disabled={recorder.isVerifying}
                      >
                        {recorder.isTestRouted ? t('recording.btnRestoreOriginalAudio') : t('recording.testAudioRoute')}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="flex-1"
                        onClick={() => setShowSetupInfo(true)}
                      >
                        ℹ️ {t('recording.routingInfo')}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Right column: Storage settings */}
        <div className="flex flex-col gap-6">
          {/* Readiness check panel */}
          <Card className="flex flex-col gap-3.5 border-border-subtle/50">
            <h3 className="text-xs font-bold text-text-secondary uppercase tracking-wider border-b border-border-subtle pb-2">
              {t('recording.audioSetupTitle')}
            </h3>

            <div className="flex items-start gap-3 mt-1">
              <span className="text-xl">
                {readyToRecord ? '✅' : '⚠️'}
              </span>
              <div className="flex flex-col leading-snug">
                <strong className="text-xs text-text-primary font-bold">
                  {readyToRecord ? t('recording.readyToRecordTitle') : t('recording.notReadyToRecordTitle')}
                </strong>
                <span className="text-[11px] text-text-secondary mt-1">
                  {readyToRecord ? t('recording.readyToRecordStatus') : t('recording.notReadyToRecordStatus')}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-1.5 text-[11px] text-text-secondary">
              <span>
                {sourceMode === 'pc_only'
                  ? `✅ ${t('recording.microphone')} (${t('recording.notNeeded') || 'Non richiesto'})`
                  : micReady
                    ? `✅ ${nativeCaptureReady ? microphoneStatusLabel(recorder.capturePermissions?.microphone) : t('recording.readinessMicOk')}`
                    : `⚠️ ${nativeCaptureReady ? microphoneStatusLabel(recorder.capturePermissions?.microphone) : t('recording.readinessMicMissing')}`
                }
              </span>
              <span>
                {sourceMode === 'mic_only'
                  ? `✅ ${t('recording.computerAudio')} (${t('recording.notNeeded') || 'Non richiesto'})`
                  : computerReady
                    ? `✅ ${nativeCaptureReady ? screenCaptureStatusLabel(recorder.capturePermissions?.screen_capture) : t('recording.readinessComputerOk')}`
                    : `⚠️ ${nativeCaptureReady ? screenCaptureStatusLabel(recorder.capturePermissions?.screen_capture) : t('recording.readinessComputerMissing')}`
                }
              </span>
              <span>
                {storageReady
                  ? `✅ ${t('recording.storageConfigTitle')}`
                  : `❌ ${t('recording.storageConfigTitle')} (${t('recording.storageConfigMissing') || 'Configurazione cartella mancante'})`
                }
              </span>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={recorder.verifyAudioSetup}
              disabled={recorder.isVerifying}
              className="mt-2"
            >
              🔄 {t('recording.btnVerifyConfig')}
            </Button>
          </Card>

          {/* Folder storage settings card */}
          <Card className="flex flex-col gap-4">
            <div className="border-b border-border-subtle pb-2">
              <h3 className="text-xs font-bold text-text-secondary uppercase tracking-wider">
                {t('recording.storageConfigTitle')}
              </h3>
              <p className="text-[10px] text-text-muted mt-0.5">{t('recording.storageConfigDesc')}</p>
            </div>

            <div className="flex flex-col gap-3">
              <Input
                value={recordingsDir}
                onChange={(e) => setRecordingsDir(e.target.value)}
                placeholder={t('recording.storagePlaceholder')}
              />
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" className="flex-1" onClick={handleBrowseDir}>
                  {t('settings.btnBrowse')}
                </Button>
                <Button size="sm" className="flex-1" onClick={handleSaveSettings}>
                  {t('transcription.save')}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Helper Dialog / Setup modal panel */}
      {showSetupInfo && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <Card className="max-w-md w-full flex flex-col gap-4 animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-border-subtle pb-2">
              <h3 className="text-sm font-bold text-text-primary uppercase tracking-wider">
                {t('recording.computerAudioHeading')}
              </h3>
              <button
                onClick={() => setShowSetupInfo(false)}
                className="text-text-muted hover:text-text-primary text-xl cursor-pointer"
              >
                ×
              </button>
            </div>

            <div className="text-xs leading-relaxed text-text-secondary flex flex-col gap-3">
              <p>{t('recording.audioSetupIntro')}</p>
              <p><strong>{t('recording.audioSetupStepsTitle')}</strong></p>
              <ol className="list-decimal pl-5 flex flex-col gap-1.5 font-medium">
                <li>{t('recording.audioSetupStep1')}</li>
                <li>{t('recording.audioSetupStep2')}</li>
                <li>{t('recording.audioSetupStep3')}</li>
                <li>{t('recording.audioSetupStep4')}</li>
              </ol>
              <p className="text-[10px] text-text-muted border-t border-border-subtle/50 pt-2 mt-1">
                {t('recording.blackholeRequirement')}
              </p>
            </div>

            <Button onClick={() => setShowSetupInfo(false)} className="w-full mt-2">
              {t('common.cancel')}
            </Button>
          </Card>
        </div>
      )}
    </div>
  );
}
