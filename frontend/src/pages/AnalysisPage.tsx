import { useState, useEffect, useRef } from 'react';
import { ApiClient, AnalysisTemplate, Transcription } from '../api/apiClient';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { Input } from '../components/ui/Input';
import { Checkbox } from '../components/ui/Checkbox';
import { TaskProcessingLoader } from '../components/workspace/TaskProcessingLoader';
import {
  DEFAULTS,
  GEMINI_MODELS,
  LLM_PROVIDERS,
  LOCAL_LLM_MODELS,
  LOCAL_LLM_QUALITY_PRESETS,
  LOCAL_LLM_REASONING_OPTIONS,
} from '../api/config';

import { renderMarkdown } from '../utils/markdown';
import { estimateTokenCount } from '../utils/formatters';
import { TourAnalysisResult } from '../features/tour/TourAnalysisResult';
import {
  llmAnalysisPayload,
  llmConfigFromSettings,
  llmSettingsPatch,
  type LlmConfigForm,
  type LocalLlmQualityPreset,
  type LocalLlmReasoning,
} from '../features/config/llmConfig';

interface AnalysisPageProps {
  detailId: string | null;
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
}

interface AnalysisResult {
  title?: string;
  summary?: string;
  key_points?: string[] | null;
  action_items?: string[] | null;
  markdown?: string;
  // Allow arbitrary additional fields from different LLM providers
  [key: string]: any;
}

export default function AnalysisPage({ detailId, navigateTo: _navigateTo, demoMode = false }: AnalysisPageProps) {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState<'history' | 'import'>('history');
  const [transcriptions, setTranscriptions] = useState<Transcription[]>([]);
  const [selectedTranscriptionId, setSelectedTranscriptionId] = useState('');
  
  // File Import State
  const [importedFile, setImportedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Only preserve the identity of an unacknowledged POST in the mounted page.
  // Global/route recovery belongs to BG-3, not local persistent storage.
  const pendingAnalysisSubmitRef = useRef<{ signature: string; id: string } | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  // Settings & Provider State
  const [provider, setProvider] = useState(DEFAULTS.llmProvider);
  const [apiKey, setApiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState(DEFAULTS.geminiModel);
  const [customGeminiModel, setCustomGeminiModel] = useState('');
  const [audioTask, setAudioTask] = useState('analysis');
  const [question, setQuestion] = useState('');
  const [promptType, setPromptType] = useState('meeting_brief');
  const [customPrompt, setCustomPrompt] = useState('');
  const [localLlmModel, setLocalLlmModel] = useState(DEFAULTS.localLlmModel);
  const [localLlmModelPath, setLocalLlmModelPath] = useState('');
  const [localLlmQualityPreset, setLocalLlmQualityPreset] = useState<LocalLlmQualityPreset>(DEFAULTS.localLlmQualityPreset as LocalLlmQualityPreset);
  const [localLlmTemperature, setLocalLlmTemperature] = useState('');
  const [localLlmReasoning, setLocalLlmReasoning] = useState<LocalLlmReasoning>(DEFAULTS.localLlmReasoning as LocalLlmReasoning);
  const [localLlmMaxOutputTokens, setLocalLlmMaxOutputTokens] = useState('');
  const [localLlmJsonMode, setLocalLlmJsonMode] = useState(DEFAULTS.localLlmJsonMode);
  const [llmService, setLlmService] = useState<any>(null);

  const [templates, setTemplates] = useState<AnalysisTemplate[]>([]);

  // Results & Progress State
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [copiedText, setCopiedText] = useState(t('analysis.resultCopy'));

  const loadTranscriptions = async () => {
    try {
      const { items } = await ApiClient.listTranscriptions(1, 100);
      setTranscriptions(items || []);
    } catch {}
  };

  const loadTemplates = async () => {
    try {
      const data = await ApiClient.listAnalysisTemplates();
      setTemplates(data.items || []);
    } catch {}
  };

  const loadSettings = async () => {
    try {
      const settings = await ApiClient.getSettings();
      const config = llmConfigFromSettings(settings);
      setProvider(config.provider);
      setApiKey('');
      setGeminiModel(config.geminiModel);
      setCustomGeminiModel(config.customGeminiModel);
      setLocalLlmModel(config.localModel);
      setLocalLlmModelPath(config.localModelPath);
      setLocalLlmQualityPreset(config.qualityPreset);
      setLocalLlmTemperature(config.temperature);
      setLocalLlmReasoning(config.reasoning);
      setLocalLlmMaxOutputTokens(config.maxOutputTokens);
      setLocalLlmJsonMode(config.jsonMode);
      try {
        const service = await ApiClient.getLlmService();
        setLlmService(service);
      } catch {}
    } catch {}
  };

  const currentLlmConfig = (): LlmConfigForm => ({
    provider,
    geminiModel,
    customGeminiModel,
    localMode: 'auto',
    localUrl: '',
    localModel: localLlmModel,
    localModelPath: localLlmModelPath,
    qualityPreset: localLlmQualityPreset,
    temperature: localLlmTemperature,
    reasoning: localLlmReasoning,
    maxOutputTokens: localLlmMaxOutputTokens,
    jsonMode: localLlmJsonMode,
  });

  useEffect(() => {
    if (demoMode) return;
    loadTranscriptions();
    loadTemplates();
    loadSettings();
  }, [demoMode]);

  // Route to a persisted result by its canonical run ID. Inline analyses
  // have no transcription, so never feed their run ID to getTranscription.
  useEffect(() => {
    if (demoMode || !detailId) return;
    let cancelled = false;
    if (detailId.startsWith('run/')) {
      setSelectedTranscriptionId('');
      ApiClient.getAnalysisRun(detailId.slice(4)).then((run) => {
        if (!cancelled && run.result) setAnalysisResult(run.result);
      }).catch(() => {
        if (!cancelled) showToast(
          lang === 'it' ? 'Risultato analisi non disponibile.' : 'Analysis result unavailable.',
          'error',
        );
      });
    } else {
      setSelectedTranscriptionId(detailId);
      ApiClient.getTranscription(detailId).then((tr) => {
        if (!cancelled && tr.analysis) setAnalysisResult(tr.analysis.result || tr.analysis);
      }).catch(() => {});
    }
    return () => { cancelled = true; };
  }, [demoMode, detailId]);



  const handleImportFile = (file: File) => {
    setImportedFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files.length > 0) {
      handleImportFile(e.dataTransfer.files[0]);
    }
  };

  const readFileAsText = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(new Error(lang === 'it' ? 'Errore durante la lettura del file.' : 'Error reading file.'));
      reader.readAsText(file);
    });
  };

  const runAnalysis = async () => {
    setLoading(true);
    setAnalysisResult(null);

    try {
      const payload: any = llmAnalysisPayload(currentLlmConfig(), apiKey);

      if (provider === 'voxtral_local') {
        payload.audio_task = audioTask;
        if (audioTask === 'qa') {
          payload.question = question;
        }
      } else {
        if (promptType === 'custom_question') {
          payload.prompt = customPrompt;
          payload.analysis_type = 'custom_question';
          payload.template_id = 'custom_question';
        } else {
          const template = templates.find((item) => item.id === promptType);
          payload.template_id = promptType;
          payload.analysis_type = template?.analysis_type;
        }
      }

      if (activeTab === 'history') {
        if (!selectedTranscriptionId) {
          throw new Error(t('analysis.selectSourceError'));
        }
        payload.transcription_id = selectedTranscriptionId;
        const selectedTr = transcriptions.find((t) => t.id === selectedTranscriptionId);
        if (selectedTr?.recording_id) {
          payload.recording_id = selectedTr.recording_id;
        }
        setStatusText(t('analysis.preparing'));
      } else {
        if (!importedFile) {
          throw new Error(t('analysis.selectSourceError'));
        }
        const fileName = importedFile.name.toLowerCase();

        if (fileName.endsWith('.txt')) {
          setStatusText(lang === 'it' ? 'Lettura file di testo...' : 'Reading text file...');
          const text = await readFileAsText(importedFile);
          payload.text = text;
        } else if (fileName.endsWith('.json')) {
          setStatusText(lang === 'it' ? 'Lettura file JSON...' : 'Reading JSON file...');
          const text = await readFileAsText(importedFile);
          try {
            const parsed = JSON.parse(text);
            payload.text = parsed.text || parsed.transcript || text;
          } catch {
            payload.text = text;
          }
        } else {
          // It's an audio file, must transcribe it first!
          setStatusText(t('transcription.transcribingStatus'));
          const formData = new FormData();
          formData.append('file', importedFile);
          formData.append('stream', 'false');

          const response = await ApiClient.transcribe(formData);
          const data = await response.json();
          if (!data.text) {
            throw new Error(t('analysis.selectSourceError'));
          }
          payload.text = data.text;
        }
        setStatusText(t('analysis.analyzingStatus'));
      }

      const signature = JSON.stringify(payload);
      const requestId = pendingAnalysisSubmitRef.current?.signature === signature
        ? pendingAnalysisSubmitRef.current.id
        : crypto.randomUUID();
      pendingAnalysisSubmitRef.current = { signature, id: requestId };
      const created = await ApiClient.createAnalysisJob(payload, requestId);
      pendingAnalysisSubmitRef.current = null;
      let job = await ApiClient.getJob(created.job_id);
      while (!['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        job = await ApiClient.getJob(created.job_id);
      }
      if (job.status !== 'completed') {
        throw new Error(job.error || `Analysis job ${job.status}`);
      }
      setAnalysisResult(job.result?.analysis || job.result);

      // Save counts and settings update
      try {
        const currentCount = parseInt(localStorage.getItem('analyses_count') || '0', 10);
        localStorage.setItem('analyses_count', String(currentCount + 1));
      } catch {}

      showToast(t('analysis.successTitle'), 'success');

      // Update provider settings in background
      await ApiClient.updateSettings({
        ...llmSettingsPatch(currentLlmConfig(), false),
        ...(apiKey.trim() ? { gemini_api_key: apiKey.trim() } : {}),
      });

    } catch (err: any) {
      showToast(`Analisi fallita: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const copyResults = () => {
    if (!analysisResult) return;
    const formatted = analysisResult.markdown || '';

    navigator.clipboard.writeText(formatted).then(() => {
      showToast(t('analysis.copySuccess'), 'success');
      setCopiedText(t('transcription.copied') || 'Copiato!');
      setTimeout(() => setCopiedText(t('analysis.resultCopy')), 2000);
    }).catch(() => {
      showToast(t('analysis.copyError'), 'error');
    });
  };

  const getDisplayTitle = () => {
    if (!analysisResult) return '';
    if (analysisResult.title) return analysisResult.title;
    if (analysisResult.markdown) {
      const match = analysisResult.markdown.match(/^#\s+(.+)$/m);
      if (match) return match[1];
    }
    return t('analysis.resultTitle');
  };

  const getMarkdownBody = () => {
    if (!analysisResult || !analysisResult.markdown) return '';
    const lines = analysisResult.markdown.split('\n');
    if (lines[0] && lines[0].startsWith('# ')) {
      return lines.slice(1).join('\n').trim();
    }
    return analysisResult.markdown;
  };



  const isStartButtonDisabled = () => {
    if (loading) return true;
    if (provider === 'voxtral_local' && audioTask === 'qa' && !question.trim()) return true;
    if (activeTab === 'history') {
      return !selectedTranscriptionId;
    }
    return !importedFile;
  };

  if (demoMode) return <TourAnalysisResult />;

  return (
    <div className="flex flex-col gap-6">
      <div className="border-b border-border-subtle pb-3">
        <span className="text-xs font-bold text-accent tracking-widest uppercase">{t('analysis.title')}</span>
        <h2 className="text-2xl font-bold text-text-primary mt-1">{t('analysis.panelTitle')}</h2>
        <p className="text-xs text-text-secondary mt-1">{t('analysis.panelDesc')}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Form Settings */}
        <div className="lg:col-span-1 flex flex-col gap-6">
          {/* Source Select Tab */}
          <Card className="flex flex-col gap-4">
            <div className="flex bg-bg-surface border border-border-subtle rounded-lg p-0.5 gap-1 w-full select-none text-xs">
              <button
                type="button"
                onClick={() => setActiveTab('history')}
                className={`flex-1 py-1.5 rounded-md text-center font-semibold cursor-pointer transition-colors ${
                  activeTab === 'history' ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {t('analysis.historyTab')}
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('import')}
                className={`flex-1 py-1.5 rounded-md text-center font-semibold cursor-pointer transition-colors ${
                  activeTab === 'import' ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {t('analysis.importTab')}
              </button>
            </div>

            {activeTab === 'history' ? (
              <div className="flex flex-col gap-3">
                <Select
                  label={t('analysis.chooseExisting')}
                  value={selectedTranscriptionId}
                  onChange={(e) => {
                    setSelectedTranscriptionId(e.target.value);
                    setAnalysisResult(null);
                  }}
                >
                  <option value="">-- {t('analysis.selectTranscriptionLabel')} --</option>
                  {transcriptions.map((tr) => (
                    <option key={tr.id} value={tr.id}>
                      {new Date(tr.timestamp).toLocaleString(lang === 'it' ? 'it-IT' : 'en-US', {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      })}{' '}
                      - {tr.audio_filename}
                    </option>
                  ))}
                </Select>
                {selectedTranscriptionId && (() => {
                  const selectedTr = transcriptions.find((tr) => tr.id === selectedTranscriptionId);
                  if (!selectedTr) return null;
                  const tokenCount = estimateTokenCount(selectedTr.text);
                  const charCount = selectedTr.text?.length || 0;
                  return (
                    <div className="text-[11px] text-text-secondary bg-bg-surface border border-border-subtle/55 rounded-xl p-3 flex flex-col gap-1.5 animate-in fade-in duration-100">
                      <div className="flex justify-between items-center">
                        <span className="font-medium text-text-muted">{t('analysis.selectedChars') || 'Caratteri:'}</span>
                        <strong className="text-text-primary font-semibold">{charCount}</strong>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="font-medium text-text-muted">{t('analysis.selectedTokens') || 'Token stimati:'}</span>
                        <strong className="text-accent font-bold">{tokenCount}</strong>
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <input
                  type="file"
                  ref={fileInputRef}
                  accept="audio/*,application/json,text/plain"
                  className="sr-only"
                  onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                      handleImportFile(e.target.files[0]);
                    }
                  }}
                />
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragOver(true);
                  }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-6 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
                    isDragOver ? 'border-accent bg-accent-glow' : 'border-border-subtle hover:border-accent-hover/40'
                  }`}
                >
                  <span className="text-3xl p-2 bg-accent-glow rounded-full mb-3">📥</span>
                  <strong className="text-xs font-semibold block text-text-primary mb-1">
                    {t('analysis.dropzoneImportTitle')}
                  </strong>
                  <span className="text-[10px] text-text-muted mb-3 block">JSON, TXT, MP3, WAV, WEBM</span>
                  <Button type="button" size="sm" variant="secondary" onClick={(e) => {
                    e.stopPropagation();
                    fileInputRef.current?.click();
                  }}>
                    {t('analysis.selectFile')}
                  </Button>
                </div>

                {importedFile && (
                  <div className="p-3 bg-bg-surface border border-border-subtle rounded-xl flex items-center justify-between text-xs">
                    <div className="truncate pr-2">
                      <strong className="block truncate text-text-primary">{importedFile.name}</strong>
                      <span className="text-[10px] text-text-muted mt-0.5 block">
                        {(importedFile.size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                    </div>
                    <button
                      onClick={() => setImportedFile(null)}
                      className="text-text-muted hover:text-text-primary text-base px-1.5 cursor-pointer"
                    >
                      ×
                    </button>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* AI Settings */}
          <Card className="flex flex-col gap-4">
            <h3 className="text-xs font-bold text-text-secondary uppercase tracking-wider border-b border-border-subtle pb-2">
              {t('analysis.llmConfig')}
            </h3>

            <div className="flex flex-col gap-4">
              <Select label="Provider LLM" value={provider} onChange={(e) => setProvider(e.target.value)}>
                {LLM_PROVIDERS.map((item) => (
                  <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
                ))}
              </Select>

              {(provider === 'nemotron_local' || provider === 'voxtral_local') && (
                <div className="flex flex-col gap-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Select label={t('settings.localLlmActiveModel')} value={localLlmModel} onChange={(e) => setLocalLlmModel(e.target.value)}>
                      {LOCAL_LLM_MODELS.map((model) => (
                        <option key={model.value} value={model.value}>{model.label}</option>
                      ))}
                    </Select>
                  <Select label={t('settings.localLlmQuality')} value={localLlmQualityPreset} onChange={(e) => setLocalLlmQualityPreset(e.target.value as LocalLlmQualityPreset)}>
                      {LOCAL_LLM_QUALITY_PRESETS.map((item) => (
                        <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
                      ))}
                    </Select>
                    <Input
                      label={t('settings.localLlmTemperature')}
                      type="number"
                      step="0.05"
                      min="0"
                      max="2"
                      value={localLlmTemperature}
                      onChange={(e) => setLocalLlmTemperature(e.target.value)}
                      placeholder={lang === 'it' ? 'Default del preset' : 'Preset default'}
                    />
                  <Select label={t('settings.localLlmReasoning')} value={localLlmReasoning} onChange={(e) => setLocalLlmReasoning(e.target.value as LocalLlmReasoning)}>
                      {LOCAL_LLM_REASONING_OPTIONS.map((item) => (
                        <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
                      ))}
                    </Select>
                    <Input
                      label={t('settings.localLlmMaxTokens')}
                      type="number"
                      min="1"
                      value={localLlmMaxOutputTokens}
                      onChange={(e) => setLocalLlmMaxOutputTokens(e.target.value)}
                      placeholder={lang === 'it' ? 'Nessun limite specifico' : 'No specific limit'}
                    />
                    <div className="flex items-end pb-2">
                      <Checkbox
                        variant="toggle"
                        label={t('settings.localLlmJsonMode')}
                        checked={localLlmJsonMode}
                        onChange={(e) => setLocalLlmJsonMode(e.target.checked)}
                      />
                    </div>
                  </div>
                  <Input
                    label={lang === 'it' ? 'Percorso modello .gguf' : 'Model .gguf path'}
                    value={localLlmModelPath}
                    onChange={(e) => setLocalLlmModelPath(e.target.value)}
                    placeholder={lang === 'it' ? 'Lascia vuoto per usare il path salvato' : 'Leave blank to use saved path'}
                  />
                  <div className="flex flex-col gap-2 p-3.5 rounded-xl border border-border-subtle bg-bg-surface text-xs text-text-secondary">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">{t('settings.localLlmActiveModel')}:</span>
                      <span className="font-mono text-text-primary">
                        {llmService?.loaded_model || t('common.notAvailable')}
                      </span>
                    </div>
                    {llmService?.loaded_model_id && (
                      <div className="flex items-center justify-between">
                        <span className="opacity-75">Model ID:</span>
                        <span className="font-mono text-text-primary">{llmService.loaded_model_id}</span>
                      </div>
                    )}
                    {llmService?.loaded_model_backend && (
                      <div className="flex items-center justify-between">
                        <span className="opacity-75">Backend:</span>
                        <span className="font-mono text-text-primary">{llmService.loaded_model_backend}</span>
                      </div>
                    )}
                    {llmService?.url && (
                      <div className="flex flex-col gap-1 mt-1 pt-1.5 border-t border-border-subtle/50">
                        <span className="font-semibold">{t('settings.localLlmWebUi')}:</span>
                        <a
                          href={llmService.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent hover:underline font-mono"
                        >
                          {llmService.url} ↗
                        </a>
                        <span className="text-[10px] text-text-muted italic mt-0.5">
                          {t('settings.localLlmChangeModelNote')}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {provider === 'gemini' && (
                <div className="flex flex-col gap-3">
                  <Select label="Modello Gemini" value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}>
                    {GEMINI_MODELS.map((model) => (
                      <option key={model.value} value={model.value}>{model.label}</option>
                    ))}
                  </Select>
                  {geminiModel === 'custom' && (
                    <Input
                      label="Gemini model ID"
                      value={customGeminiModel}
                      onChange={(e) => setCustomGeminiModel(e.target.value)}
                      placeholder="gemini-..."
                    />
                  )}
                  <Input
                    label={t('settings.apiKeyLabel')}
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="AIzaSy..."
                  />
                </div>
              )}

              {provider === 'voxtral_local' && (
                <div className="flex flex-col gap-4">
                  <Select
                    label={lang === 'it' ? 'Task Audio' : 'Audio Task'}
                    value={audioTask}
                    onChange={(e) => setAudioTask(e.target.value)}
                  >
                    <option value="analysis">{lang === 'it' ? 'Analisi completa' : 'Full analysis'}</option>
                    <option value="summary">{lang === 'it' ? 'Riassunto' : 'Summary'}</option>
                    <option value="transcribe">{lang === 'it' ? 'Trascrizione diretta' : 'Direct transcription'}</option>
                    <option value="insights">{lang === 'it' ? 'Insight e azioni' : 'Insights and actions'}</option>
                    <option value="qa">{lang === 'it' ? 'Domanda (Q&A)' : 'Question (Q&A)'}</option>
                  </Select>

                  {audioTask === 'qa' && (
                    <Input
                      label={lang === 'it' ? 'La tua domanda' : 'Your question'}
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder={lang === 'it' ? 'Es. Quali sono state le decisioni sul budget?' : 'e.g. What were the decisions on the budget?'}
                      required
                    />
                  )}
                  
                  {activeTab === 'history' && selectedTranscriptionId && !transcriptions.find(t => t.id === selectedTranscriptionId)?.recording_id && (
                    <span className="text-[10px] text-text-muted">
                      {lang === 'it' 
                        ? '⚠️ Questa trascrizione non ha una registrazione audio associata. Verrà usata l\'analisi del testo.'
                        : '⚠️ This transcription has no associated audio recording. Text analysis fallback will be used.'}
                    </span>
                  )}
                  {activeTab === 'import' && (
                    <span className="text-[10px] text-text-muted">
                      {lang === 'it'
                        ? '⚠️ I file importati non supportano l\'analisi audio diretta. Verrà usata l\'analisi del testo.'
                        : '⚠️ Imported files do not support direct audio analysis. Text analysis fallback will be used.'}
                    </span>
                  )}
                </div>
              )}

              {provider !== 'voxtral_local' && (
                <div className="flex flex-col gap-3">
                  <Select
                    label={t('analysis.promptLabel')}
                    value={promptType}
                    onChange={(e) => setPromptType(e.target.value)}
                  >
                    {(templates.length > 0 ? templates : [
                      { id: 'meeting_brief', label: t('analysis.promptSummary'), analysis_type: 'meeting_brief' },
                      { id: 'meeting_minutes', label: t('analysis.promptMinutes'), analysis_type: 'meeting_minutes' },
                      { id: 'action_items', label: t('analysis.promptActions'), analysis_type: 'action_items' },
                      { id: 'custom_question', label: t('analysis.promptCustom'), analysis_type: 'custom_question' },
                    ] as AnalysisTemplate[]).map((template) => (
                      <option key={template.id} value={template.id}>{template.label}</option>
                    ))}
                  </Select>

                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-text-secondary">
                      {lang === 'it' ? 'Istruzioni prompt' : 'Prompt instructions'}
                    </label>
                    <textarea
                      value={customPrompt}
                      onChange={(e) => {
                        setPromptType('custom_question');
                        setCustomPrompt(e.target.value);
                      }}
                      placeholder={t('analysis.customPromptPlaceholder')}
                      className="w-full bg-bg-surface border border-border-subtle rounded-xl p-3 text-xs text-text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent resize-y min-h-[100px] leading-relaxed"
                    />
                  </div>
                </div>
              )}

              <Button
                size="lg"
                onClick={runAnalysis}
                disabled={isStartButtonDisabled()}
                isLoading={loading}
                className="w-full mt-2"
              >
                📊 {t('analysis.btnStartAnalysis')}
              </Button>
            </div>
          </Card>
        </div>

        {/* Right Column: Display Panel */}
        <div className="lg:col-span-2">
          {loading ? (
            <TaskProcessingLoader
              title={t('workspace.loaderAnalysisTitle')}
              description={t('workspace.loaderAnalysisDesc')}
              steps={[
                t('workspace.loaderAnalysisStep1'),
                t('workspace.loaderAnalysisStep2'),
                t('workspace.loaderAnalysisStep3'),
                t('workspace.loaderAnalysisStep4'),
              ]}
              activeStep={2}
              progress={68}
              variant="analysis"
              helperText={statusText || t('workspace.loaderLocalHelper')}
            />
          ) : analysisResult ? (
            <div className="flex flex-col gap-4">
              <div className="flex justify-between items-center bg-bg-elevated/40 border border-border-subtle rounded-xl px-4 py-3.5">
                <h3 className="text-sm font-bold text-text-primary">
                  {getDisplayTitle()}
                </h3>
                <Button size="sm" variant="secondary" onClick={copyResults}>
                  📄 {copiedText}
                </Button>
              </div>

              <Card className="flex flex-col gap-5 max-h-[70vh] overflow-y-auto">
                <div className="prose prose-sm max-w-none text-text-secondary">
                  {renderMarkdown(getMarkdownBody())}
                </div>
              </Card>
            </div>
          ) : (
            <Card className="h-96 flex flex-col items-center justify-center text-center p-6 gap-3">
              <span className="text-4xl bg-bg-hover rounded-full p-4">🧠</span>
              <strong className="text-sm font-bold text-text-primary mt-2">{t('analysis.waitingAnalysis')}</strong>
              <p className="text-xs text-text-secondary max-w-sm leading-relaxed">
                {t('analysis.waitingAnalysisDesc')}
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
