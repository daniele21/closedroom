import { useState, useEffect, useRef, useMemo } from 'react';
import { Card } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import { ApiClient, RecordingVisualFrame, Transcription } from '../../../api/apiClient';
import { useTranslation } from '../../../i18n/i18n';
import { formatTime } from '../../../utils/formatters';
import { countTranscriptWords, getTranscriptionAsrMetadata } from '../../../utils/transcriptionMetadata';
import { renderMarkdown } from '../../../utils/markdown';
import { useToast } from '../../../context/ToastContext';
import { ProjectPromptModal } from '../../../components/ui/ProjectPromptModal';
import { Badge } from '../../../components/ui/Badge';
import { diagnosticWarnings, transcriptionDiagnostics, transcriptionHasWarnings } from '../../../utils/diagnostics';
import { recordingTranscriptionRoute } from '../../../utils/transcriptionRoute';
import { ASR_PROVIDERS, SPEECHMATICS_MODELS, SPEECHMATICS_REGIONS } from '../../../api/config';
import { SpeakerDiarizationEditor } from '../../../components/meeting/SpeakerDiarizationEditor';
import TranscriptTextView from '../../../components/transcription/TranscriptTextView';
import FullTextView from '../../../components/transcription/FullTextView';
import { ChevronDown, Clock, Settings, Layers } from 'lucide-react';

interface ResultsStepProps {
  transcriptionResult: Transcription;
  copiedText: string;
  goToUploadStep: () => void;
  copyToClipboard: () => void;
  resultTab: 'text' | 'segments' | 'raw' | 'analysis';
  setResultTab: (tab: 'text' | 'segments' | 'raw' | 'analysis') => void;
  navigateTo: (page: string, detail?: string | null) => void;
  onTranscriptionUpdated: (transcription: Transcription) => void;
}

export default function ResultsStep({
  transcriptionResult,
  copiedText,
  goToUploadStep,
  copyToClipboard,
  resultTab,
  setResultTab,
  navigateTo,
  onTranscriptionUpdated,
}: ResultsStepProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();
  const recordingId = transcriptionResult.recording_id;
  const [isSplitting, setIsSplitting] = useState(false);
  const [projectName, setProjectName] = useState<string>('');
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [projectsList, setProjectsList] = useState<string[]>([]);
  const [recordingTitles, setRecordingTitles] = useState<Map<string, string>>(new Map());
  const [visualFrames, setVisualFrames] = useState<RecordingVisualFrame[]>([]);
  const [diarizationProvider, setDiarizationProvider] = useState<'local' | 'speechmatics'>('local');
  const [speechmaticsRegion, setSpeechmaticsRegion] = useState('eu');
  const [speechmaticsModel, setSpeechmaticsModel] = useState('standard');
  const [speechmaticsConfigured, setSpeechmaticsConfigured] = useState(false);
  const [isRediarizing, setIsRediarizing] = useState(false);
  const [rediarizationProgress, setRediarizationProgress] = useState('');
  
  // Stati per la UX migliorata
  const [currentTime, setCurrentTime] = useState(0);
  const [isTechOpen, setIsTechOpen] = useState(false);
  const [isDiarizationOpen, setIsDiarizationOpen] = useState(false);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);

  const loadProjectInfo = async () => {
    try {
      const projsData = await ApiClient.listProjects();
      const list = (projsData.items || [])
        .filter((p) => !p.is_unassigned)
        .map((p) => p.name);
      setProjectsList(list);

      if (transcriptionResult.recording_id) {
        const rec = await ApiClient.getRecording(transcriptionResult.recording_id);
        setProjectName(rec.project_name || '');
      } else if (transcriptionResult.merged_sources && transcriptionResult.merged_sources.length > 0) {
        const firstRecSource = transcriptionResult.merged_sources.find(src => src.recording_id);
        if (firstRecSource?.recording_id) {
          const rec = await ApiClient.getRecording(firstRecSource.recording_id);
          setProjectName(rec.project_name || '');
        }

        const titlesMap = new Map<string, string>();
        await Promise.all(
          transcriptionResult.merged_sources.map(async (src) => {
            if (src.recording_id) {
              try {
                const rec = await ApiClient.getRecording(src.recording_id);
                titlesMap.set(src.recording_id, rec.title);
              } catch (err) {
                console.error(`Error loading recording ${src.recording_id}:`, err);
              }
            }
          })
        );
        setRecordingTitles(titlesMap);
      }
    } catch (err) {
      console.error('Error loading project info:', err);
    }
  };

  useEffect(() => {
    loadProjectInfo();
  }, [transcriptionResult]);

  useEffect(() => {
    if (!recordingId) {
      setVisualFrames([]);
      return;
    }
    ApiClient.recordingVisualFrames(recordingId)
      .then((result) => setVisualFrames(result.items || []))
      .catch(() => setVisualFrames([]));
  }, [recordingId]);

  useEffect(() => {
    if (!recordingId) return;
    ApiClient.getSettings()
      .then((settings) => {
        setSpeechmaticsConfigured(Boolean(settings.speechmatics_api_key_configured));
        setSpeechmaticsRegion(settings.speechmatics_region || 'eu');
        setSpeechmaticsModel(settings.speechmatics_model || 'standard');
      })
      .catch(() => setSpeechmaticsConfigured(false));
  }, [recordingId]);

  // Listener per aggiornare il tempo corrente dell'audio per la sincronizzazione
  useEffect(() => {
    const audio = audioPlayerRef.current;
    if (!audio) return;

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
    };

    audio.addEventListener('timeupdate', handleTimeUpdate);
    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate);
    };
  }, [audioPlayerRef.current, transcriptionResult]);

  const handleTimestampClick = (time: number) => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.currentTime = time;
      audioPlayerRef.current.play().catch(() => {});
    }
  };

  const handleRediarize = async () => {
    const transcriptionId = transcriptionResult.id || transcriptionResult.saved_id;
    if (!transcriptionId || !recordingId) return;
    if (diarizationProvider === 'speechmatics' && !speechmaticsConfigured) {
      showToast(t('transcription.rediarizationSpeechmaticsMissingKey'), 'error');
      return;
    }
    if (
      diarizationProvider === 'speechmatics'
      && !window.confirm(t('transcription.rediarizationCloudConfirm'))
    ) {
      return;
    }

    try {
      setIsRediarizing(true);
      setRediarizationProgress(t('jobSteps.queued'));
      const job = await ApiClient.createDiarizationJob(transcriptionId, {
        provider: diarizationProvider,
        speechmatics_region: speechmaticsRegion,
        speechmatics_model: speechmaticsModel,
      });
      let currentJob = job;
      while (!['completed', 'failed', 'cancelled', 'interrupted'].includes(currentJob.status)) {
        setRediarizationProgress(
          `${t(`jobSteps.${currentJob.current_step}`)} · ${currentJob.progress || 0}%`,
        );
        await new Promise((resolve) => setTimeout(resolve, 1000));
        currentJob = await ApiClient.getJob(job.id);
      }
      if (currentJob.status !== 'completed' || !currentJob.result) {
        throw new Error(currentJob.error || currentJob.status);
      }
      onTranscriptionUpdated(currentJob.result);
      setRediarizationProgress('');
      showToast(t('transcription.rediarizationCompleted'), 'success');
    } catch (err: any) {
      showToast(t('transcription.rediarizationError', { error: err.message }), 'error');
    } finally {
      setIsRediarizing(false);
    }
  };

  const handleConfirmProject = async (newProjName: string) => {
    try {
      if (transcriptionResult.recording_id) {
        await ApiClient.updateRecording(transcriptionResult.recording_id, { project_name: newProjName });
      }
      if (transcriptionResult.merged_sources && transcriptionResult.merged_sources.length > 0) {
        const updatePromises = transcriptionResult.merged_sources
          .filter(src => src.recording_id)
          .map(src => ApiClient.updateRecording(src.recording_id!, { project_name: newProjName }));
        await Promise.all(updatePromises);
      }
      setProjectName(newProjName);
      showToast(t('transcription.projectUpdateSuccess') || 'Progetto aggiornato!', 'success');
      setIsProjectModalOpen(false);
    } catch (err: any) {
      showToast(t('transcription.projectUpdateError', { error: err.message }) || 'Errore', 'error');
    }
  };

  const handleSplit = async () => {
    const confirmMsg = lang === 'it' 
      ? 'Sei sicuro di voler dividere questa trascrizione unita? Verranno ripristinate le trascrizioni originali e questa verrà eliminata.' 
      : 'Are you sure you want to split this merged transcription? The original transcripts will be restored and this one will be deleted.';
      
    if (!confirm(confirmMsg)) return;

    try {
      setIsSplitting(true);
      await ApiClient.splitTranscription(transcriptionResult.id);
      showToast(
        lang === 'it' 
          ? 'Trascrizione divisa con successo! Trascrizioni originali ripristinate.' 
          : 'Transcription split successfully! Original transcripts restored.', 
        'success'
      );
      goToUploadStep();
    } catch (err: any) {
      showToast(`Errore durante la divisione: ${err.message}`, 'error');
    } finally {
      setIsSplitting(false);
    }
  };

  const getAnalysisMarkdown = () => {
    if (!transcriptionResult.analysis) return '';
    const obj = transcriptionResult.analysis.result || transcriptionResult.analysis;
    if (typeof obj === 'string') return obj;
    if (obj && typeof obj === 'object') {
      if (obj.markdown) return obj.markdown;
      const lines = [];
      if (obj.title) lines.push(`# ${obj.title}\n`);
      if (obj.summary) lines.push(`## Riassunto\n${obj.summary}\n`);
      if (Array.isArray(obj.key_points) && obj.key_points.length > 0) {
        lines.push("## Punti Chiave");
        obj.key_points.forEach((kp: string) => lines.push(`- ${kp}`));
        lines.push("");
      }
      if (Array.isArray(obj.action_items) && obj.action_items.length > 0) {
        lines.push("## Prossimi Passi");
        obj.action_items.forEach((ai: string) => lines.push(`- ${ai}`));
        lines.push("");
      }
      return lines.join('\n');
    }
    return '';
  };

  const asrMetadata = getTranscriptionAsrMetadata(transcriptionResult);
  const wordCount = countTranscriptWords(transcriptionResult.text);
  const diagnostics = transcriptionDiagnostics(transcriptionResult);
  const warnings = diagnosticWarnings(diagnostics);
  const hasWarnings = transcriptionHasWarnings(transcriptionResult);
  const diarization = transcriptionResult.stats?.speaker_diarization;
  const visualIntelligence = transcriptionResult.stats?.visual_intelligence;
  const speakerMappings = useMemo(() => {
    const mappings = transcriptionResult.stats?.speaker_attribution?.mappings || [];
    if (mappings.length > 0) return mappings;
    const segments = transcriptionResult.segments || [];
    const labels = new Set<string>();
    segments.forEach((seg) => {
      if (seg.speaker_label) labels.add(seg.speaker_label);
    });
    return Array.from(labels).map((label) => ({
      speaker_cluster: label,
      display_name: null as string | null,
    }));
  }, [transcriptionResult]);

  return (
    <div className="flex flex-col gap-5 animate-in fade-in duration-150">
      {/* Header compact */}
      <div className="flex flex-col xl:flex-row xl:items-start justify-between border-b border-border-subtle pb-3 gap-3">
        <div className="min-w-0">
          <span className="text-xs font-bold text-accent tracking-widest uppercase">
            {t('transcription.resultTitle')}
          </span>
          <h2 className="text-xl font-bold text-text-primary mt-1">
            {transcriptionResult.audio_filename}
          </h2>
          <div className="flex items-center gap-2 mt-1.5 text-xs text-text-secondary">
            <span>📁 {t('recording.formProjectLabel') || 'Progetto'}:</span>
            <span className="font-semibold text-text-primary">{projectName || t('projects.empty') || 'Senza progetto'}</span>
            {(transcriptionResult.recording_id || (transcriptionResult.merged_sources && transcriptionResult.merged_sources.length > 0)) && (
              <button
                onClick={() => setIsProjectModalOpen(true)}
                className="text-accent hover:text-accent-hover font-semibold transition-colors cursor-pointer ml-1 bg-transparent border-none p-0"
              >
                ({lang === 'it' ? 'modifica' : 'edit'})
              </button>
            )}
          </div>
        </div>
        <div className="flex max-w-full flex-wrap justify-start gap-2 xl:justify-end">
          {transcriptionResult.merged_sources && transcriptionResult.merged_sources.length > 0 && (
            <Button variant="danger" onClick={handleSplit} isLoading={isSplitting} disabled={isSplitting}>
              ✂️ {lang === 'it' ? 'Dividi' : 'Split'}
            </Button>
          )}
          {recordingId && (
            <Button
              variant="ghost"
              onClick={() => {
                const confirmText = lang === 'it' 
                  ? "Sei sicuro di voler trascrivere nuovamente questo audio? La nuova trascrizione sostituirà quella precedente nei risultati principali."
                  : "Are you sure you want to transcribe this audio again? The new transcription will replace the previous one in the main results.";
                if (window.confirm(confirmText)) {
                  navigateTo('transcription', recordingTranscriptionRoute(recordingId, 'retranscribe'));
                }
              }}
              disabled={isSplitting}
            >
              🔄 {lang === 'it' ? 'Trascrivi di nuovo' : 'Transcribe again'}
            </Button>
          )}
          {recordingId && (
            <Button onClick={() => navigateTo('meeting', recordingId)} disabled={isSplitting}>
              {lang === 'it' ? 'Apri meeting' : 'Open meeting'}
            </Button>
          )}
          <Button variant="secondary" onClick={goToUploadStep} disabled={isSplitting}>
            🔄 {t('transcription.newTranscription')}
          </Button>
          <Button variant={recordingId ? 'secondary' : 'primary'} onClick={copyToClipboard} disabled={isSplitting}>
            📄 {copiedText}
          </Button>
        </div>
      </div>

      {hasWarnings && (
        <section className="rounded-xl border border-warning/40 bg-warning/10 p-4 flex flex-col gap-3" role="alert">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-text-primary">{t('transcription.completedWithWarningsTitle')}</h3>
              <p className="text-xs text-text-secondary mt-1">{t('transcription.diagnosticsDesc')}</p>
            </div>
            <Badge variant="warning">{t('meeting.completedWithWarnings')}</Badge>
          </div>
          <div className="divide-y divide-warning/20 border-t border-warning/20">
            {warnings.map((item, index) => (
              <div key={`${item.component}-${index}`} className="py-3 text-xs flex flex-col gap-1">
                <strong className="text-text-primary">{item.component}</strong>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-text-secondary">
                  {item.requested_backend && <span>{t('transcription.requestedBackend')}: <b>{item.requested_backend}</b></span>}
                  {item.actual_backend && <span>{t('transcription.actualBackend')}: <b>{item.actual_backend}</b></span>}
                  {item.fallback_reason && <span>{t('transcription.fallbackReason')}: <b>{item.fallback_reason}</b></span>}
                  {item.error && <span className="text-danger">{item.error}</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Layout a 2 colonne su schermi larghi */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Colonna Sinistra (Principale, 2/3): Testo, Segmenti e Analisi */}
        <div className="lg:col-span-2 flex flex-col gap-5">
          {/* Tabs bar */}
          <div className="flex border-b border-border-subtle gap-4 text-xs font-semibold select-none">
            {[
              { id: 'text' as const, label: t('transcription.tabText') },
              { id: 'analysis' as const, label: t('transcription.tabAnalysis') || 'Analisi', hide: !transcriptionResult.analysis },
              { id: 'segments' as const, label: t('transcription.tabSegments'), hide: !transcriptionResult.segments || transcriptionResult.segments.length === 0 },
            ].map(
              (tab) =>
                !tab.hide && (
                  <button
                    key={tab.id}
                    onClick={() => setResultTab(tab.id as any)}
                    className={`pb-2 border-b-2 transition-colors cursor-pointer bg-transparent border-none ${
                      resultTab === tab.id
                        ? 'border-accent text-accent'
                        : 'border-transparent text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    {tab.label}
                  </button>
                )
            )}
          </div>

          {/* Display panels */}
          <Card className="min-h-80 select-text leading-relaxed text-sm text-text-secondary p-5">
            {resultTab === 'analysis' && transcriptionResult.analysis && (
              <div className="prose prose-sm max-w-none text-text-secondary">
                {renderMarkdown(getAnalysisMarkdown())}
              </div>
            )}

            {resultTab === 'text' && (
              <FullTextView
                segments={transcriptionResult.segments || []}
                speakerMappings={speakerMappings}
              />
            )}

            {resultTab === 'segments' && transcriptionResult.segments && (
              <TranscriptTextView
                segments={transcriptionResult.segments}
                speakerMappings={speakerMappings}
                onTimestampClick={handleTimestampClick}
                currentTime={currentTime}
              />
            )}
          </Card>

          {/* Inline Action Card - Analyze with AI */}
          {(transcriptionResult.id || transcriptionResult.saved_id) && !transcriptionResult.analysis && (
            <div className="p-4 border border-accent/25 bg-accent/5 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <span className="text-xl">💡</span>
                <span className="text-xs text-text-secondary font-medium">
                  La trascrizione è stata salvata. Vuoi estrarre riassunti e punti chiave con l'IA?
                </span>
              </div>
              <Button
                size="sm"
                onClick={() => {
                  if (recordingId) navigateTo('meeting', recordingId);
                  else navigateTo('analysis', transcriptionResult.id || transcriptionResult.saved_id);
                }}
              >
                🧠 {recordingId ? (lang === 'it' ? 'Prepara note nel meeting' : 'Prepare notes in Meeting') : t('transcription.ctaAnalyze')}
              </Button>
            </div>
          )}

          {visualFrames.length > 0 && (
            <section className="rounded-xl border border-border-subtle bg-bg-glass p-4">
              <div>
                <h3 className="text-sm font-semibold text-text-primary">
                  {t('transcription.capturedFramesTitle')}
                </h3>
                <p className="mt-1 text-xs text-text-secondary">
                  {t('transcription.capturedFramesDesc', { count: visualFrames.length })}
                </p>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                {visualFrames.map((frame) => (
                  <figure
                    key={frame.sequence}
                    className="overflow-hidden rounded-xl border border-border-subtle bg-bg-surface"
                  >
                    <a href={frame.url} target="_blank" rel="noreferrer">
                      <img
                        src={frame.url}
                        alt={t('transcription.capturedFrameAlt', { sequence: frame.sequence })}
                        loading="lazy"
                        className="aspect-video w-full object-cover transition-transform duration-200 hover:scale-[1.02]"
                      />
                    </a>
                    <figcaption className="flex items-center justify-between gap-2 px-2.5 py-2 text-[10px] text-text-muted">
                      <span>#{frame.sequence}</span>
                      <span>{formatTime(frame.timestamp)}</span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* Colonna Destra (Sidebar, 1/3): Player, Speaker Names, Stats, Tech Details */}
        <div className="flex flex-col gap-5 lg:sticky lg:top-5">
          {/* Mini Audio Player Card */}
          {transcriptionResult.recording_id && !transcriptionResult.merged_sources && (
            <Card className="flex flex-col gap-2 p-4">
              <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-accent" />
                {t('transcription.audioTrackTitle') || 'Traccia Audio'}
              </span>
              <audio
                ref={audioPlayerRef}
                controls
                src={`/v1/recordings/${transcriptionResult.recording_id}/audio`}
                className="w-full mt-1 h-9"
              />
              {transcriptionResult.source_tracks && transcriptionResult.source_tracks.length > 1 && (
                <div className="flex flex-col gap-2 mt-2 border-t border-border-subtle/50 pt-2">
                  <span className="text-[9px] text-text-muted uppercase tracking-wider font-bold">Tracce separate</span>
                  {transcriptionResult.source_tracks.map((track) => (
                    <div key={track.id} className="p-2 bg-bg-surface/50 border border-border-subtle/40 rounded-lg flex flex-col gap-1">
                      <div className="flex items-center justify-between text-[10px] text-text-primary font-semibold">
                        <span>{track.source === 'mic' ? '🎙️' : '🖥️'} {track.label}</span>
                      </div>
                      <audio
                        controls
                        src={`/v1/recordings/${transcriptionResult.recording_id}/tracks/${track.id}/audio`}
                        className="w-full h-6"
                      />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* Merged Sources Players in Sidebar */}
          {transcriptionResult.merged_sources && transcriptionResult.merged_sources.length > 0 && (
            <Card className="flex flex-col gap-3 p-4">
              <div className="border-b border-border-subtle pb-2">
                <span className="text-[10px] text-accent font-bold uppercase tracking-wider flex items-center gap-1">
                  <Layers className="w-3.5 h-3.5" />
                  {t('transcription.mergeTrackTitle') || 'Tracce Unite'}
                </span>
              </div>
              <div className="flex flex-col gap-2 max-h-60 overflow-y-auto">
                {transcriptionResult.merged_sources.map((src, index) => {
                  const displayTitle = src.recording_id && recordingTitles.has(src.recording_id)
                    ? recordingTitles.get(src.recording_id)
                    : src.audio_filename;
                  return (
                    <div key={src.id} className="p-2 bg-bg-surface/50 border border-border-subtle/40 rounded-lg flex flex-col gap-1 text-[11px]">
                      <span className="font-semibold text-text-primary truncate" title={displayTitle}>
                        Part {index + 1}: {displayTitle}
                      </span>
                      {src.recording_id ? (
                        <audio
                          controls
                          src={`/v1/recordings/${src.recording_id}/audio`}
                          className="w-full h-7 mt-0.5"
                        />
                      ) : (
                        <p className="text-[10px] text-text-muted italic">
                          Audio non riproducibile
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Speaker Attrib Editor */}
          <SpeakerDiarizationEditor
            transcription={transcriptionResult}
            onUpdated={onTranscriptionUpdated}
          />

          {/* Rediarization Accordion */}
          {recordingId && !transcriptionResult.merged_sources && (
            <div className="border border-border-subtle rounded-xl overflow-hidden bg-bg-glass">
              <button
                onClick={() => setIsDiarizationOpen(!isDiarizationOpen)}
                className="w-full px-4 py-3 flex items-center justify-between text-left text-xs font-semibold text-text-primary bg-bg-surface/50 hover:bg-bg-hover transition-colors cursor-pointer border-none"
              >
                <span className="flex items-center gap-2">
                  <Settings className="w-3.5 h-3.5 text-text-muted" />
                  {t('transcription.rediarizationTitle')}
                </span>
                <ChevronDown className={`w-4 h-4 transition-transform ${isDiarizationOpen ? 'rotate-180' : ''}`} />
              </button>

              {isDiarizationOpen && (
                <div className="p-4 border-t border-border-subtle flex flex-col gap-3">
                  <p className="text-[11px] leading-relaxed text-text-secondary">
                    {t('transcription.rediarizationDesc')}
                  </p>
                  <label className="flex flex-col gap-1 text-[11px] text-text-secondary">
                    <span>{t('transcription.rediarizationProvider')}</span>
                    <select
                      value={diarizationProvider}
                      onChange={(event) => setDiarizationProvider(event.target.value as 'local' | 'speechmatics')}
                      disabled={isRediarizing}
                      className="rounded-lg border border-border-subtle bg-bg-elevated px-2 py-1.5 text-xs text-text-primary outline-none"
                    >
                      {ASR_PROVIDERS.map((provider) => (
                        <option key={provider.value} value={provider.value}>
                          {provider.value === 'local'
                            ? t('transcription.rediarizationLocalProvider')
                            : t('transcription.rediarizationSpeechmaticsProvider')}
                        </option>
                      ))}
                    </select>
                  </label>
                  {diarizationProvider === 'speechmatics' && (
                    <>
                      <label className="flex flex-col gap-1 text-[11px] text-text-secondary">
                        <span>{t('transcription.rediarizationRegion')}</span>
                        <select
                          value={speechmaticsRegion}
                          onChange={(event) => setSpeechmaticsRegion(event.target.value)}
                          disabled={isRediarizing}
                          className="rounded-lg border border-border-subtle bg-bg-elevated px-2 py-1.5 text-xs text-text-primary outline-none"
                        >
                          {SPEECHMATICS_REGIONS.map((region) => (
                            <option key={region.value} value={region.value}>{region.label}</option>
                          ))}
                        </select>
                      </label>
                      <label className="flex flex-col gap-1 text-[11px] text-text-secondary">
                        <span>{t('transcription.rediarizationModel')}</span>
                        <select
                          value={speechmaticsModel}
                          onChange={(event) => setSpeechmaticsModel(event.target.value)}
                          disabled={isRediarizing}
                          className="rounded-lg border border-border-subtle bg-bg-elevated px-2 py-1.5 text-xs text-text-primary outline-none"
                        >
                          {SPEECHMATICS_MODELS.map((model) => (
                            <option key={model.value} value={model.value}>{model.label}</option>
                          ))}
                        </select>
                      </label>
                      <p className="text-[10px] text-warning">
                        {t('transcription.rediarizationCloudNotice')}
                      </p>
                    </>
                  )}
                  <div className="flex items-center gap-2 mt-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={handleRediarize}
                      isLoading={isRediarizing}
                      disabled={isRediarizing}
                      className="text-xs"
                    >
                      {t('transcription.rediarizationRun')}
                    </Button>
                    {rediarizationProgress && (
                      <span className="text-[10px] text-text-secondary">{rediarizationProgress}</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Stats Compact Card */}
          <Card className="p-4 flex flex-col gap-3">
            <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
              Stats Trascrizione
            </span>
            <div className="grid grid-cols-2 gap-3 text-xs text-text-secondary">
              <div className="flex flex-col">
                <span className="text-[9px] text-text-muted uppercase">ASR Provider</span>
                <span className="font-semibold text-text-primary truncate" title={asrMetadata.providerLabel}>
                  {asrMetadata.providerLabel}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-text-muted uppercase">Durata</span>
                <span className="font-semibold text-text-primary">
                  {transcriptionResult.stats?.time_total_seconds
                    ? `${transcriptionResult.stats.time_total_seconds.toFixed(1)}s`
                    : 'N/A'}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-text-muted uppercase">Lingua</span>
                <span className="font-semibold text-text-primary uppercase">
                  {transcriptionResult.language || 'N/A'}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-text-muted uppercase">Parole</span>
                <span className="font-semibold text-text-primary">{wordCount}</span>
              </div>
            </div>
          </Card>

          {/* Dettagli Tecnici Accordion */}
          <div className="border border-border-subtle rounded-xl overflow-hidden bg-bg-glass">
            <button
              onClick={() => setIsTechOpen(!isTechOpen)}
              className="w-full px-4 py-2 flex items-center justify-between text-left text-xs font-semibold text-text-secondary bg-bg-surface/30 hover:bg-bg-hover transition-colors cursor-pointer border-none"
            >
              <span>⚙️ {lang === 'it' ? 'Diagnostica & Backend' : 'Diagnostics & Backend'}</span>
              <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isTechOpen ? 'rotate-180' : ''}`} />
            </button>

            {isTechOpen && (
              <div className="p-3 border-t border-border-subtle bg-bg-surface/20 flex flex-col gap-2 text-[11px] text-text-secondary">
                <div className="flex justify-between">
                  <span>Backend:</span>
                  <code className="text-text-primary">{asrMetadata.backend || 'N/A'}</code>
                </div>
                <div className="flex justify-between">
                  <span>Model ID:</span>
                  <code className="text-text-primary truncate max-w-[150px]" title={asrMetadata.model}>{asrMetadata.model || 'N/A'}</code>
                </div>
                {diarization?.status && (
                  <div className="flex justify-between">
                    <span>Diarizzazione:</span>
                    <span className="font-semibold text-text-primary">{diarization.status}</span>
                  </div>
                )}
                {visualIntelligence?.status && (
                  <div className="flex justify-between">
                    <span>Visual Intel:</span>
                    <span className="font-semibold text-text-primary">{visualIntelligence.status}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <ProjectPromptModal
        isOpen={isProjectModalOpen}
        initialValue={projectName}
        onConfirm={handleConfirmProject}
        onCancel={() => setIsProjectModalOpen(false)}
        existingProjects={projectsList}
      />
    </div>
  );
}
