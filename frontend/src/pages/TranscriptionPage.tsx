import { TERMINAL_JOB_STATUSES } from '../api/jobEvents';
import type { AudioImportsState } from '../hooks/useAudioImports';
import React, { useState, useEffect, useRef } from 'react';
import { ApiClient, ASRTrackProgress, Recording, Transcription, VisualProcessingProgress } from '../api/apiClient';
import { DEFAULTS } from '../api/config';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import SourceStep from './transcription/components/SourceStep';
import ConfigureStep from './transcription/components/ConfigureStep';
import ProcessingStep from './transcription/components/ProcessingStep';
import ResultsStep from './transcription/components/ResultsStep';
import { TourTranscriptionResult } from '../features/tour/TourTranscriptionResult';
import { asrConfigFromSettings } from '../features/config/asrConfig';
import {
  formatASRTrackProgressLog,
  formatASRTrackProgressStatus,
  formatVisualProgressLog,
  formatVisualProgressStatus,
  getTranscriptionActiveStep,
  isASRTrackProgress,
  isVisualProcessingProgress,
  localizeJobStep,
} from '../utils/jobs';
import { transcriptionHasWarnings } from '../utils/diagnostics';
import { parseRecordingTranscriptionRoute } from '../utils/transcriptionRoute';

interface TranscriptionPageProps {
  detailPath: string | null;
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
  audioImports: AudioImportsState;
}

export default function TranscriptionPage({ detailPath, navigateTo, audioImports, demoMode = false }: TranscriptionPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();
  const showTranscriptionOutcome = (result: Transcription) => {
    if (transcriptionHasWarnings(result)) {
      showToast(t('transcription.completedWithWarningsToast'), 'warning');
      return;
    }
    showToast(t('transcription.successTitle'), 'success');
  };

  const openCompletedTranscription = (result: Transcription, recordingId?: string | null) => {
    const canonicalRecordingId = result.recording_id || recordingId;
    if (canonicalRecordingId) {
      navigateTo('meeting', canonicalRecordingId);
      return;
    }
    const transcriptionId = result.id || result.saved_id;
    if (transcriptionId) {
      navigateTo('transcription', transcriptionId);
    }
  };

  const [projectItemsMap, setProjectItemsMap] = useState<Map<string, { transcription: any; analysis: any }>>(new Map());
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
      }
    };
  }, []);

  const togglePlayAudio = (e: React.MouseEvent, recId: string) => {
    e.stopPropagation();
    if (playingAudioId === recId) {
      currentAudioRef.current?.pause();
      setPlayingAudioId(null);
    } else {
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
      }
      const audio = new Audio(`/v1/recordings/${recId}/audio`);
      currentAudioRef.current = audio;
      setPlayingAudioId(recId);
      audio.play().catch(() => {
        setPlayingAudioId(null);
      });
      audio.onended = () => {
        setPlayingAudioId(null);
      };
    }
  };

  const handleCardProjectChange = async (recordingId: string, newProjName: string) => {
    if (newProjName === '__NEW_PROJECT__') {
      const promptMsg = lang === 'it' ? 'Inserisci il nome del nuovo progetto:' : 'Enter the new project name:';
      const newName = prompt(promptMsg);
      if (newName && newName.trim()) {
        const trimmed = newName.trim();
        try {
          await ApiClient.updateRecording(recordingId, { project_name: trimmed });
          showToast(t('transcription.projectUpdateSuccess') || 'Progetto aggiornato!', 'success');
          loadRecordings();
        } catch (err: any) {
          showToast(t('transcription.projectUpdateError', { error: err.message }) || 'Errore', 'error');
        }
      }
    } else {
      try {
        await ApiClient.updateRecording(recordingId, { project_name: newProjName });
        showToast(t('transcription.projectUpdateSuccess') || 'Progetto aggiornato!', 'success');
        loadRecordings();
      } catch (err: any) {
        showToast(t('transcription.projectUpdateError', { error: err.message }) || 'Errore', 'error');
      }
    }
  };

  const handleCardTitleChange = async (recordingId: string, newTitle: string) => {
    try {
      await ApiClient.updateRecording(recordingId, { title: newTitle });
      showToast(t('transcription.titleSaveSuccess') || 'Titolo aggiornato!', 'success');
      loadRecordings();
    } catch (err: any) {
      showToast(t('transcription.titleSaveError', { error: err.message }) || 'Errore', 'error');
    }
  };

  const [step, setStep] = useState<'upload' | 'transcribe' | 'results'>('upload');
  const [sourceMode, setSourceMode] = useState<'recordings' | 'file' | 'merge'>('recordings');
  const [isMerging, setIsMerging] = useState(false);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [recordingsCountText, setRecordingsCountText] = useState('0 elementi');
  const [recordingsFolder, setRecordingsFolder] = useState('');
  const [projectsList, setProjectsList] = useState<string[]>([]);
  
  // Selection
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedRecordingId, setSelectedRecordingId] = useState<string | null>(null);
  const [selectedObjectUrl, setSelectedObjectUrl] = useState<string | null>(null);

  // Settings Form
  const [targetLanguage, setTargetLanguage] = useState('');
  const [targetTask, setTargetTask] = useState('transcribe');
  const [targetModel, setTargetModel] = useState('');
  const [asrProvider, setAsrProvider] = useState(DEFAULTS.asrProvider);
  const [speechmaticsRegion, setSpeechmaticsRegion] = useState(DEFAULTS.speechmaticsRegion);
  const [speechmaticsModel, setSpeechmaticsModel] = useState(DEFAULTS.speechmaticsModel);
  const [diarizationProvider, setDiarizationProvider] = useState('none');
  const [visualIntelligenceEnabled, setVisualIntelligenceEnabled] = useState(false);
  const [speechmaticsConfigured, setSpeechmaticsConfigured] = useState(false);
  const [temperature, setTemperature] = useState('');
  const [wordTimestamps, setWordTimestamps] = useState(false);
  const [conditionOnPrevious, setConditionOnPrevious] = useState(DEFAULTS.conditionOnPreviousText);
  const [vadGuided, setVadGuided] = useState(DEFAULTS.vadGuided);
  const [modelCacheStatus, setModelCacheStatus] = useState('Verifica...');

  // Processing state
  const [isProcessing, setIsProcessing] = useState(false);
  const [progressStatus, setProgressStatus] = useState('');
  const [progressPercent, setProgressPercent] = useState(0);
  const [progressStep, setProgressStep] = useState('queued');
  const [liveConsoleLines, setLiveConsoleLines] = useState<string[]>([]);
  const [livePreviewText, setLivePreviewText] = useState('');
  const [elapsedTime, setElapsedTime] = useState('0.0s');
  const [visualProgress, setVisualProgress] = useState<VisualProcessingProgress | null>(null);
  const [asrProgress, setASRProgress] = useState<ASRTrackProgress | null>(null);
  const [isCancelling, setIsCancelling] = useState(false);

  // Results State
  const [transcriptionResult, setTranscriptionResult] = useState<Transcription | null>(null);
  const [resultTab, setResultTab] = useState<'text' | 'segments' | 'raw' | 'analysis'>('text');
  const [copiedText, setCopiedText] = useState(t('transcription.copyFullTranscription'));

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const timerIntervalRef = useRef<any>(null);
  const lastVisualProgressRef = useRef('');
  const lastASRProgressRef = useRef('');
  const lastJobStepRef = useRef('');
  const activeJobIdRef = useRef<string | null>(null);
  const pendingSubmissionRef = useRef<{ signature: string; id: string } | null>(null);

  const loadRecordings = async () => {
    try {
      const sourceData = await ApiClient.transcriptionSourceData();
      const list = sourceData.recordings || [];
      setRecordings(list);
      setRecordingsCountText(`${list.length} ${list.length === 1 ? 'elemento' : 'elementi'}`);

      const map = new Map<string, { transcription: any; analysis: any }>();
      const projs: string[] = [];
      (sourceData.projects || []).forEach((proj: any) => {
        if (!proj.is_unassigned && proj.name) {
          projs.push(proj.name);
        }
        (proj.items || []).forEach((item: any) => {
          if (item.recording?.id) {
            map.set(item.recording.id, {
              transcription: item.transcription,
              analysis: item.analysis,
            });
          }
        });
      });
      setProjectItemsMap(map);
      setProjectsList(projs);
      
      const settings = sourceData.settings || {};
      const asr = asrConfigFromSettings(settings);
      setRecordingsFolder(settings.recordings_dir || '-');
      if (!targetModel) setTargetModel(asr.model);
      if (!targetLanguage) setTargetLanguage(asr.language);
      if (!targetTask) setTargetTask(asr.task);
      setAsrProvider(asr.provider);
      setSpeechmaticsRegion(asr.speechmaticsRegion);
      setSpeechmaticsModel(asr.speechmaticsModel);
      setDiarizationProvider(settings.speaker_diarization_enabled ? 'local' : 'none');
      setVisualIntelligenceEnabled(Boolean(settings.visual_intelligence_enabled));
      setSpeechmaticsConfigured(Boolean(settings.speechmatics_api_key_configured));
      setWordTimestamps(asr.wordTimestamps);
      setConditionOnPrevious(asr.conditionOnPrevious);
    } catch {}
  };

  useEffect(() => {
    if (demoMode) return;
    loadRecordings();
  }, [demoMode, t]);

  // Check model cache on model select change
  useEffect(() => {
    if (demoMode) return;
    const checkCache = async () => {
      if (asrProvider !== 'local') {
        setModelCacheStatus('Cloud ASR');
        return;
      }
      if (!targetModel) return;
      setModelCacheStatus('Verifica...');
      try {
        const res = await ApiClient.checkModelCache(targetModel);
        if (res.cached) {
          setModelCacheStatus('Modello pronto ✅');
        } else {
          setModelCacheStatus('Richiede download 📥');
        }
      } catch {
        setModelCacheStatus('Errore verifica');
      }
    };
    checkCache();
  }, [asrProvider, demoMode, targetModel]);

  // Handle URL Preselections (e.g. from Recording detail action)
  useEffect(() => {
    if (demoMode) return;
    let cancelled = false;

    if (detailPath) {
      const recordingRoute = parseRecordingTranscriptionRoute(detailPath);
      if (recordingRoute) {
        const recordingId = recordingRoute.recordingId;
        // Load recording details and select it
        ApiClient.getRecording(recordingId).then(async (rec: Recording) => {
          // Fetch audio blob
          const blob = await ApiClient.recordingAudio(rec.id);
          if (cancelled) return;
          const ext = rec.audio_file.split('.').pop() || 'webm';
          const fileObj = new File([blob], `${rec.title}.${ext}`, { type: rec.mime_type || blob.type });

          setSelectedRecordingId(rec.id);
          handleSelectAudioFile(fileObj);
        }).catch((err: any) => {
          if (cancelled) return;
          setSelectedRecordingId(null);
          showToast(t('transcription.preselectSourceError', { error: err?.message || String(err) }), 'error');
        });
      } else {
        // It's a transcription ID, load and display results
        ApiClient.getTranscription(detailPath).then((tr) => {
          if (cancelled) return;
          setTranscriptionResult(tr);
          setStep('results');
          if (tr.analysis) {
            setResultTab('analysis');
          } else {
            setResultTab('text');
          }
        }).catch((err: any) => {
          if (cancelled) return;
          showToast(t('transcription.preselectResultError', { error: err?.message || String(err) }), 'error');
        });
      }
    }

    return () => {
      cancelled = true;
    };
  }, [demoMode, detailPath]);

  const handleSelectAudioFile = (file: File) => {
    if (selectedObjectUrl) URL.revokeObjectURL(selectedObjectUrl);
    
    setSelectedFile(file);
    const objectUrl = URL.createObjectURL(file);
    setSelectedObjectUrl(objectUrl);
    
    if (audioRef.current) {
      audioRef.current.src = objectUrl;
    }
    
    setStep('transcribe');
  };

  const selectTranscription = (tr: Transcription) => {
    setTranscriptionResult(tr);
    setStep('results');
    if (tr.analysis) {
      setResultTab('analysis');
    } else {
      setResultTab('text');
    }
    navigateTo('transcription', tr.id);
  };

  const selectRecording = async (recording: Recording) => {
    const status = projectItemsMap.get(recording.id);
    if (status?.transcription?.id) {
      navigateTo('meeting', recording.id);
      return;
    }

    try {
      setSelectedRecordingId(recording.id);
      let blob: Blob;
      try {
        blob = await ApiClient.recordingAudio(recording.id);
      } catch (audioErr) {
        console.warn('Could not load recording audio, falling back to empty blob:', audioErr);
        blob = new Blob([], { type: recording.mime_type || 'audio/webm' });
      }
      const extension = recording.audio_file.split('.').pop() || 'webm';
      const fileObj = new File(
        [blob],
        `${recording.title}.${extension}`,
        { type: recording.mime_type || blob.type }
      );
      handleSelectAudioFile(fileObj);
    } catch (err: any) {
      showToast(`Impossibile caricare l'audio: ${err.message}`, 'error');
    }
  };

  const handleMergeTranscriptions = async (ids: string[], title: string) => {
    try {
      setIsMerging(true);
      const result = await ApiClient.mergeTranscriptions(ids, title);
      setTranscriptionResult(result);
      setStep('results');
      setResultTab('text');
      showToast(t('transcription.successTitle'), 'success');
      if (result.id) {
        navigateTo('transcription', result.id);
      }
    } catch (err: any) {
      showToast(`Impossibile unire le trascrizioni: ${err.message}`, 'error');
    } finally {
      setIsMerging(false);
    }
  };

  const goToUploadStep = () => {
    setSelectedFile(null);
    setSelectedRecordingId(null);
    setTranscriptionResult(null);
    if (selectedObjectUrl) {
      URL.revokeObjectURL(selectedObjectUrl);
      setSelectedObjectUrl(null);
    }
    setStep('upload');
    navigateTo('transcription');
  };

  // Live Audio Streaming Transcription parser
  const startTranscription = async () => {
    if (!selectedFile) return;
    if (diarizationProvider === 'speechmatics' && !speechmaticsConfigured) {
      showToast(t('transcription.rediarizationSpeechmaticsMissingKey'), 'error');
      return;
    }
    if (
      diarizationProvider === 'speechmatics'
      && !window.confirm(t('transcription.initialDiarizationCloudConfirm'))
    ) {
      return;
    }
    
    setIsProcessing(true);
    setIsCancelling(false);
    setLiveConsoleLines([]);
    setLivePreviewText('');
    setVisualProgress(null);
    setASRProgress(null);
    lastVisualProgressRef.current = '';
    lastASRProgressRef.current = '';
    lastJobStepRef.current = '';
    setProgressPercent(0);
    setProgressStep('queued');
    setProgressStatus(t('transcription.preparing'));

    const timerStart = performance.now();
    setElapsedTime('0.0s');
    timerIntervalRef.current = setInterval(() => {
      const elapsed = ((performance.now() - timerStart) / 1000).toFixed(1);
      setElapsedTime(`${elapsed}s`);
    }, 100);

    abortControllerRef.current = new AbortController();

    try {
      const options = {
        model: asrProvider === 'local' ? targetModel || undefined : undefined,
        language: targetLanguage || undefined,
        task: targetTask,
        response_format: 'verbose_json',
        word_timestamps: wordTimestamps,
        condition_on_previous_text: conditionOnPrevious,
        temperature: temperature ? Number(temperature) : null,
        vad_guided: vadGuided,
        asr_provider: asrProvider,
        speechmatics_region: speechmaticsRegion,
        speechmatics_model: speechmaticsModel,
        speechmatics_diarization: (
          asrProvider === 'speechmatics' && diarizationProvider === 'speechmatics'
            ? 'speaker'
            : 'none'
        ),
        diarization_provider: diarizationProvider,
        visual_intelligence_enabled: visualIntelligenceEnabled,
      };
      if (!selectedRecordingId) {
        audioImports.startTranscription(selectedFile, options);
        showToast(lang === 'it'
          ? 'Importazione avviata. Puoi continuare a usare ClosedRoom e seguire l\'attività.'
          : 'Import started. You can keep using ClosedRoom and follow progress in Activities.', 'info');
        navigateTo('activities');
        return;
      }
      setProgressStatus(lang === 'it' ? 'Trascrizione tracce della registrazione...' : 'Transcribing recording tracks...');
      setProgressPercent(10);
        // Preserve this identity if the POST fails before its response arrives.
        // A new deliberate run after an acknowledged submit uses a new ID.
        const signature = JSON.stringify([selectedRecordingId, options]);
        const requestId = (
          pendingSubmissionRef.current?.signature === signature
            ? pendingSubmissionRef.current.id
            : crypto.randomUUID()
        );
        pendingSubmissionRef.current = { signature, id: requestId };
        const job = await ApiClient.createTranscriptionJob(
          selectedRecordingId, options, requestId,
        );
        pendingSubmissionRef.current = null;
        activeJobIdRef.current = job.id;
        let currentJob = job;
        while (!TERMINAL_JOB_STATUSES.has(currentJob.status)) {
          setProgressPercent(currentJob.progress || 10);
          setProgressStep(currentJob.current_step || currentJob.status);
          const currentStepName = currentJob.current_step || currentJob.status;
          if (currentStepName !== lastJobStepRef.current) {
            lastJobStepRef.current = currentStepName;
            setLiveConsoleLines((previous) => [
              ...previous,
              t('transcription.jobStepLog', {
                step: localizeJobStep(currentStepName, t),
                progress: currentJob.progress || 0,
              }),
            ].slice(-500));
          }
          if (isASRTrackProgress(currentJob.progress_detail)) {
            const detail = currentJob.progress_detail;
            setVisualProgress(null);
            setASRProgress(detail);
            setProgressStatus(formatASRTrackProgressStatus(detail, t));
            const fingerprint = [
              detail.track_id,
              detail.track_index,
              detail.processed_audio_seconds,
              detail.track_percent,
            ].join(':');
            if (fingerprint !== lastASRProgressRef.current) {
              lastASRProgressRef.current = fingerprint;
              setLiveConsoleLines((previous) => [
                ...previous,
                formatASRTrackProgressLog(detail, t),
              ].slice(-500));
            }
          } else if (isVisualProcessingProgress(currentJob.progress_detail)) {
            const detail = currentJob.progress_detail;
            setASRProgress(null);
            setVisualProgress(detail);
            setProgressStatus(formatVisualProgressStatus(detail, t));
            const fingerprint = [
              detail.processed,
              detail.total,
              detail.decision,
              detail.sequence,
              detail.task,
            ].join(':');
            if (fingerprint !== lastVisualProgressRef.current) {
              lastVisualProgressRef.current = fingerprint;
              setLiveConsoleLines((previous) => [
                ...previous,
                formatVisualProgressLog(detail, t),
              ].slice(-500));
            }
          } else {
            setVisualProgress(null);
            setASRProgress(null);
            setProgressStatus(localizeJobStep(currentJob.current_step || currentJob.status, t));
          }
          await new Promise((resolve) => setTimeout(resolve, 800));
          currentJob = await ApiClient.getJob(job.id);
        }
        if (currentJob.status === 'cancelled') {
          showToast(t('transcription.processCancelled'), 'success');
          return;
        }
        if (currentJob.status !== 'completed' || !currentJob.result) {
          throw new Error(currentJob.error || currentJob.status);
        }
        const result = currentJob.result;
        setProgressPercent(100);
        setTranscriptionResult(result);
        setStep('results');
        setResultTab('text');
        showTranscriptionOutcome(result);
        openCompletedTranscription(result, selectedRecordingId);
        return;
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        showToast(`${t('transcription.toastTranscriptionError')}: ${err.message}`, 'error');
      }
    } finally {
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
      activeJobIdRef.current = null;
      abortControllerRef.current = null;
      setIsCancelling(false);
      setIsProcessing(false);
      loadRecordings();
    }
  };

  const cancelTranscription = async () => {
    if (isCancelling) return;
    setIsCancelling(true);
    setProgressStatus(t('transcription.cancellingProcess'));
    try {
      if (activeJobIdRef.current) {
        await ApiClient.cancelJob(activeJobIdRef.current);
      } else {
        abortControllerRef.current?.abort();
      }
    } catch (err: any) {
      setIsCancelling(false);
      showToast(`${t('transcription.cancelProcessError')}: ${err.message}`, 'error');
    }
  };

  const copyToClipboard = () => {
    if (!transcriptionResult) return;
    const text = transcriptionResult.text || '';

    navigator.clipboard.writeText(text).then(() => {
      showToast(t('transcription.fullTranscriptionCopied'), 'success');
      setCopiedText(t('transcription.copied') || 'Copiato!');
      setTimeout(() => setCopiedText(t('transcription.copyFullTranscription')), 2000);
    }).catch(() => {
      showToast(t('transcription.copyFailed'), 'error');
    });
  };

  if (demoMode) return <TourTranscriptionResult />;

  return (
    <div className="flex flex-col gap-6">
      {/* Stepper progress indicator */}
      <nav className="flex items-center justify-center p-2 select-none border border-border-subtle bg-bg-elevated/20 rounded-full max-w-xl mx-auto w-full">
        <button
          onClick={() => step !== 'upload' && setStep('upload')}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold ${
            step === 'upload' ? 'bg-accent text-white' : 'text-text-muted hover:text-text-secondary cursor-pointer'
          }`}
        >
          <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">1</span>
          <span>Sorgente</span>
        </button>
        <div className="w-8 h-[2px] bg-border-subtle mx-2"></div>
        <button
          onClick={() => step === 'results' && setStep('transcribe')}
          disabled={!selectedFile}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold ${
            step === 'transcribe' ? 'bg-accent text-white' : 'text-text-muted hover:text-text-secondary disabled:pointer-events-none'
          }`}
        >
          <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">2</span>
          <span>Configura</span>
        </button>
        <div className="w-8 h-[2px] bg-border-subtle mx-2"></div>
        <button
          disabled={!transcriptionResult}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold ${
            step === 'results' ? 'bg-accent text-white' : 'text-text-muted disabled:pointer-events-none'
          }`}
        >
          <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">3</span>
          <span>Risultato</span>
        </button>
      </nav>

      {/* Steps contents rendering */}
      {step === 'upload' && (
        <SourceStep
          sourceMode={sourceMode}
          setSourceMode={setSourceMode}
          recordings={recordings}
          recordingsCountText={recordingsCountText}
          recordingsFolder={recordingsFolder}
          projectItemsMap={projectItemsMap}
          projectsList={projectsList}
          playingAudioId={playingAudioId}
          togglePlayAudio={togglePlayAudio}
          handleCardProjectChange={handleCardProjectChange}
          handleCardTitleChange={handleCardTitleChange}
          selectRecording={selectRecording}
          handleSelectAudioFile={(file) => {
            setSelectedRecordingId(null);
            handleSelectAudioFile(file);
          }}
          fileInputRef={fileInputRef}
          onMerge={handleMergeTranscriptions}
          isMerging={isMerging}
          onSelectTranscription={selectTranscription}
        />
      )}

      {step === 'transcribe' && !isProcessing && (
        <ConfigureStep
          selectedFile={selectedFile}
          selectedRecordingId={selectedRecordingId}
          isProcessing={isProcessing}
          goToUploadStep={goToUploadStep}
          targetLanguage={targetLanguage}
          setTargetLanguage={setTargetLanguage}
          targetTask={targetTask}
          setTargetTask={setTargetTask}
          targetModel={targetModel}
          setTargetModel={setTargetModel}
          asrProvider={asrProvider}
          setAsrProvider={setAsrProvider}
          speechmaticsRegion={speechmaticsRegion}
          setSpeechmaticsRegion={setSpeechmaticsRegion}
          speechmaticsModel={speechmaticsModel}
          setSpeechmaticsModel={setSpeechmaticsModel}
          diarizationProvider={diarizationProvider}
          setDiarizationProvider={setDiarizationProvider}
          visualIntelligenceEnabled={visualIntelligenceEnabled}
          setVisualIntelligenceEnabled={setVisualIntelligenceEnabled}
          modelCacheStatus={modelCacheStatus}
          temperature={temperature}
          setTemperature={setTemperature}
          wordTimestamps={wordTimestamps}
          setWordTimestamps={setWordTimestamps}
          conditionOnPrevious={conditionOnPrevious}
          setConditionOnPrevious={setConditionOnPrevious}
          vadGuided={vadGuided}
          setVadGuided={setVadGuided}
          audioRef={audioRef}
          startTranscription={startTranscription}
        />
      )}

      {step === 'transcribe' && isProcessing && (
        <ProcessingStep
          progressStatus={progressStatus}
          progressPercent={progressPercent}
          activeStep={getTranscriptionActiveStep(progressStep, progressPercent)}
          currentStep={progressStep}
          livePreviewText={livePreviewText}
          liveConsoleLines={liveConsoleLines}
          elapsedTime={elapsedTime}
          visualProgress={visualProgress}
          asrProgress={asrProgress}
          isCancelling={isCancelling}
          onCancel={cancelTranscription}
        />
      )}

      {step === 'results' && transcriptionResult && (
        <ResultsStep
          transcriptionResult={transcriptionResult}
          copiedText={copiedText}
          goToUploadStep={goToUploadStep}
          copyToClipboard={copyToClipboard}
          resultTab={resultTab}
          setResultTab={setResultTab}
          navigateTo={navigateTo}
          onTranscriptionUpdated={setTranscriptionResult}
        />
      )}
    </div>
  );
}
