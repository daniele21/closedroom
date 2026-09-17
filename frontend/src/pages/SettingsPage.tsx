import { useEffect, useState } from 'react';
import { Bug, ChevronDown, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { AccessibilityStatus, ApiClient, Settings } from '../api/apiClient';
import {
  ASR_PROVIDERS,
  DEFAULTS,
  GEMINI_MODELS,
  LANGUAGES,
  LLM_PROVIDERS,
  LOCAL_LLM_MODELS,
  LOCAL_LLM_QUALITY_PRESETS,
  LOCAL_LLM_REASONING_OPTIONS,
  MODELS,
  SPEECHMATICS_DIARIZATION,
  SPEECHMATICS_MODELS,
  SPEECHMATICS_REGIONS,
  TASKS,
} from '../api/config';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { Checkbox } from '../components/ui/Checkbox';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { asrConfigFromSettings, asrSettingsPatch } from '../features/config/asrConfig';
import {
  isLocalLlmProvider,
  llmConfigFromSettings,
  llmSettingsPatch,
  type LocalLlmMode,
  type LocalLlmQualityPreset,
  type LocalLlmReasoning,
} from '../features/config/llmConfig';

export default function SettingsPage() {
  const { t, lang } = useTranslation();
  const { showToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [recordingsDir, setRecordingsDir] = useState('');
  const [transcriptionsDir, setTranscriptionsDir] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [defaultLanguage, setDefaultLanguage] = useState('it');
  const [defaultTask, setDefaultTask] = useState('transcribe');
  const [asrProvider, setAsrProvider] = useState(DEFAULTS.asrProvider);
  const [speechmaticsApiKey, setSpeechmaticsApiKey] = useState('');
  const [speechmaticsKeyConfigured, setSpeechmaticsKeyConfigured] = useState(false);
  const [speechmaticsRegion, setSpeechmaticsRegion] = useState(DEFAULTS.speechmaticsRegion);
  const [speechmaticsModel, setSpeechmaticsModel] = useState(DEFAULTS.speechmaticsModel);
  const [speechmaticsDiarization, setSpeechmaticsDiarization] = useState(DEFAULTS.speechmaticsDiarization);
  const [speechmaticsTimeout, setSpeechmaticsTimeout] = useState('900');
  const [speechmaticsPollInterval, setSpeechmaticsPollInterval] = useState('5');
  const [defaultTemperature, setDefaultTemperature] = useState('');
  const [wordTimestamps, setWordTimestamps] = useState(false);
  const [conditionOnPrevious, setConditionOnPrevious] = useState(true);

  const [llmProvider, setLlmProvider] = useState(DEFAULTS.llmProvider);
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState(DEFAULTS.geminiModel);
  const [customGeminiModel, setCustomGeminiModel] = useState('');
  const [localLlmUrl, setLocalLlmUrl] = useState('');
  const [localLlmMode, setLocalLlmMode] = useState<LocalLlmMode>('auto');
  const [localLlmModel, setLocalLlmModel] = useState(DEFAULTS.localLlmModel);
  const [localLlmModelPath, setLocalLlmModelPath] = useState('');
  const [localLlmQualityPreset, setLocalLlmQualityPreset] = useState<LocalLlmQualityPreset>(DEFAULTS.localLlmQualityPreset as LocalLlmQualityPreset);
  const [localLlmTemperature, setLocalLlmTemperature] = useState('');
  const [localLlmReasoning, setLocalLlmReasoning] = useState<LocalLlmReasoning>(DEFAULTS.localLlmReasoning as LocalLlmReasoning);
  const [localLlmMaxOutputTokens, setLocalLlmMaxOutputTokens] = useState('');
  const [localLlmJsonMode, setLocalLlmJsonMode] = useState(DEFAULTS.localLlmJsonMode);
  const [showAdvancedProcessing, setShowAdvancedProcessing] = useState(false);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [llmService, setLlmService] = useState<any>(null);
  const [llmAction, setLlmAction] = useState('');
  const [llmLogs, setLlmLogs] = useState('');

  const [meetingAutoAnalysis, setMeetingAutoAnalysis] = useState(false);
  const [meetingDefaultPipeline, setMeetingDefaultPipeline] = useState('meeting_default');
  const [speakerDiarizationEnabled, setSpeakerDiarizationEnabled] = useState(false);
  const [visualIntelligenceEnabled, setVisualIntelligenceEnabled] = useState(false);
  const [accessibility, setAccessibility] = useState<AccessibilityStatus | null>(null);
  const [sysInfo, setSysInfo] = useState({
    server: '127.0.0.1:1236',
    activeModel: '',
    version: '1.0.0',
    menubar: '',
  });

  const refreshLlmService = async () => {
    try {
      setLlmService(await ApiClient.getLlmService());
    } catch (err: any) {
      setLlmService({ name: 'llm', status: 'unknown', error: err.message });
    }
  };

  const loadSettings = async () => {
    try {
      setLoading(true);
      const settings = await ApiClient.getSettings();
      const asr = asrConfigFromSettings(settings);
      const llm = llmConfigFromSettings(settings);

      setRecordingsDir(settings.recordings_dir || '');
      setTranscriptionsDir(settings.transcriptions_dir || '');
      setDefaultModel(asr.model);
      setDefaultLanguage(asr.language);
      setDefaultTask(asr.task);
      setAsrProvider(asr.provider);
      setSpeechmaticsApiKey('');
      setSpeechmaticsKeyConfigured(asr.speechmaticsKeyConfigured);
      setSpeechmaticsRegion(asr.speechmaticsRegion);
      setSpeechmaticsModel(asr.speechmaticsModel);
      setSpeechmaticsDiarization(asr.speechmaticsDiarization);
      setSpeechmaticsTimeout(asr.speechmaticsTimeout);
      setSpeechmaticsPollInterval(asr.speechmaticsPollInterval);
      setDefaultTemperature(asr.temperature);
      setWordTimestamps(asr.wordTimestamps);
      setConditionOnPrevious(asr.conditionOnPrevious);

      setLlmProvider(llm.provider);
      setGeminiApiKey('');
      setGeminiModel(llm.geminiModel);
      setCustomGeminiModel(llm.customGeminiModel);
      setLocalLlmUrl(llm.localUrl);
      setLocalLlmMode(llm.localMode);
      setLocalLlmModel(llm.localModel);
      setLocalLlmModelPath(llm.localModelPath);
      setLocalLlmQualityPreset(llm.qualityPreset);
      setLocalLlmTemperature(llm.temperature);
      setLocalLlmReasoning(llm.reasoning);
      setLocalLlmMaxOutputTokens(llm.maxOutputTokens);
      setLocalLlmJsonMode(llm.jsonMode);

      setMeetingAutoAnalysis(settings.meeting_auto_analysis || false);
      setMeetingDefaultPipeline(settings.meeting_default_pipeline || 'meeting_default');
      setSpeakerDiarizationEnabled(Boolean(settings.speaker_diarization_enabled));
      setVisualIntelligenceEnabled(Boolean(settings.visual_intelligence_enabled));

      void refreshLlmService();
      ApiClient.accessibilityStatus()
        .then(setAccessibility)
        .catch((err) => setAccessibility({
          available: false,
          trusted: false,
          required_for: ['global_hotkeys'],
          reason: 'accessibility_status_unavailable',
          error: err instanceof Error ? err.message : String(err),
        }));

      setSysInfo({
        server: '127.0.0.1:1236',
        activeModel: settings.default_model || t('common.notAvailable'),
        version: '1.0.0',
        menubar: t('settings.sysActive'),
      });
    } catch (err: any) {
      showToast(err.message || (lang === 'it' ? 'Errore nel caricamento delle impostazioni' : 'Failed to load settings'), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
  }, [t]);

  const runLlmAction = async (action: 'start' | 'stop' | 'restart' | 'logs') => {
    setLlmAction(action);
    try {
      if (action === 'start') await ApiClient.startLlmService();
      if (action === 'stop') await ApiClient.stopLlmService();
      if (action === 'restart') await ApiClient.restartLlmService();
      if (action === 'logs') {
        const logs = await ApiClient.getLlmLogs(200);
        setLlmLogs(logs.text || t('common.notAvailable'));
      }
      await refreshLlmService();
    } catch (err: any) {
      showToast(err.message || t('common.error'), 'error');
    } finally {
      setLlmAction('');
    }
  };

  const handleBrowse = async (target: 'recordings' | 'transcriptions' | 'model') => {
    try {
      const result = target === 'model'
        ? await ApiClient.selectFile()
        : await ApiClient.selectDirectory();
      if (!result?.path) return;
      if (target === 'recordings') setRecordingsDir(result.path);
      if (target === 'transcriptions') setTranscriptionsDir(result.path);
      if (target === 'model') setLocalLlmModelPath(result.path);
      showToast(t('transcription.browseSelectDir'), 'info');
    } catch (err: any) {
      showToast(err.message || t('transcription.browseError'), 'error');
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const payload: Partial<Settings> = {
        transcriptions_dir: transcriptionsDir.trim(),
        recordings_dir: recordingsDir.trim(),
        ...asrSettingsPatch({
          provider: asrProvider,
          model: defaultModel,
          language: defaultLanguage,
          task: defaultTask,
          temperature: defaultTemperature,
          wordTimestamps,
          conditionOnPrevious,
          speechmaticsRegion,
          speechmaticsModel,
          speechmaticsDiarization,
          speechmaticsTimeout,
          speechmaticsPollInterval,
          speechmaticsKeyConfigured,
        }),
        ...llmSettingsPatch({
          provider: llmProvider,
          geminiModel,
          customGeminiModel,
          localMode: localLlmMode,
          localUrl: localLlmUrl,
          localModel: localLlmModel,
          localModelPath: localLlmModelPath,
          qualityPreset: localLlmQualityPreset,
          temperature: localLlmTemperature,
          reasoning: localLlmReasoning,
          maxOutputTokens: localLlmMaxOutputTokens,
          jsonMode: localLlmJsonMode,
        }, showDiagnostics),
        meeting_auto_analysis: meetingAutoAnalysis,
        meeting_default_pipeline: meetingDefaultPipeline,
        speaker_diarization_enabled: speakerDiarizationEnabled,
        visual_intelligence_enabled: visualIntelligenceEnabled,
      };
      if (geminiApiKey.trim()) payload.gemini_api_key = geminiApiKey.trim();
      if (speechmaticsApiKey.trim()) payload.speechmatics_api_key = speechmaticsApiKey.trim();

      await ApiClient.updateSettings(payload);
      showToast(t('settings.successSave'), 'success');
      await loadSettings();
    } catch (err: any) {
      showToast(err.message || (lang === 'it' ? 'Errore nel salvataggio delle impostazioni' : 'Failed to save settings'), 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20" role="status" aria-live="polite">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-accent border-t-transparent" />
        <span className="text-sm text-text-secondary">{t('common.loading')}</span>
      </div>
    );
  }

  const localProvider = isLocalLlmProvider(llmProvider);
  const asrLocation = asrProvider === 'local'
    ? (lang === 'it' ? 'Sul Mac' : 'On this Mac')
    : 'Speechmatics cloud';
  const analysisLocation = localProvider
    ? (lang === 'it' ? 'Sul Mac' : 'On this Mac')
    : llmProvider === 'gemini'
      ? 'Gemini cloud'
      : (lang === 'it' ? 'Configurazione personalizzata' : 'Custom configuration');

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <header className="border-b border-border-subtle pb-3">
        <h2 className="text-2xl font-bold text-text-primary">{t('settings.title')}</h2>
        <p className="mt-1 text-sm text-text-secondary">
          {lang === 'it'
            ? 'Qui imposti preferenze comprensibili. Provider, modelli e runtime restano disponibili solo quando vuoi controllarli esplicitamente.'
            : 'Set understandable preferences here. Providers, models and runtimes stay available only when you explicitly want to control them.'}
        </p>
      </header>

      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <Card className="flex flex-col gap-4">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">{t('settings.storageTitle')}</h3>
            <p className="mt-1 text-xs text-text-muted">
              {lang === 'it' ? 'Dove ClosedRoom conserva audio e trascrizioni locali.' : 'Where ClosedRoom stores local audio and transcripts.'}
            </p>
          </div>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="settings-recordings-dir" className="text-sm font-medium text-text-secondary">{t('settings.recordingsFolderLabel')}</label>
              <div className="flex gap-2">
                <Input id="settings-recordings-dir" value={recordingsDir} onChange={(event) => setRecordingsDir(event.target.value)} required className="flex-1" />
                <Button type="button" variant="secondary" onClick={() => handleBrowse('recordings')}>{t('settings.btnBrowse')}</Button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="settings-transcriptions-dir" className="text-sm font-medium text-text-secondary">{t('settings.transcriptionsFolderLabel')}</label>
              <div className="flex gap-2">
                <Input id="settings-transcriptions-dir" value={transcriptionsDir} onChange={(event) => setTranscriptionsDir(event.target.value)} required className="flex-1" />
                <Button type="button" variant="secondary" onClick={() => handleBrowse('transcriptions')}>{t('settings.btnBrowse')}</Button>
              </div>
            </div>
          </div>
        </Card>

        <Card className="flex flex-col gap-4">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">
              {lang === 'it' ? 'Meeting' : 'Meetings'}
            </h3>
            <p className="mt-1 text-xs text-text-muted">
              {lang === 'it'
                ? 'Preferenze che cambiano il risultato, non il motore che ClosedRoom usa per ottenerlo.'
                : 'Preferences that change the outcome, not the engine ClosedRoom uses to produce it.'}
            </p>
          </div>
          <Select label={t('transcription.languageLabel')} value={defaultLanguage} onChange={(event) => setDefaultLanguage(event.target.value)}>
            {LANGUAGES.map((language) => <option key={language.value} value={language.value}>{language.label}</option>)}
          </Select>
          <Checkbox
            variant="toggle"
            label={t('settings.meetingAutoAnalysis')}
            checked={meetingAutoAnalysis}
            onChange={(event) => setMeetingAutoAnalysis(event.target.checked)}
          />
        </Card>

        <Card className="flex flex-col gap-4">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">
              {lang === 'it' ? 'Privacy e processing' : 'Privacy & processing'}
            </h3>
            <p className="mt-1 text-xs text-text-muted">
              {lang === 'it'
                ? 'ClosedRoom usa le scelte correnti automaticamente. Apri Avanzate solo se vuoi cambiare provider o modello.'
                : 'ClosedRoom uses the current choices automatically. Open Advanced only if you want to change a provider or model.'}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-border-subtle bg-bg-surface/30 p-4">
              <span className="block text-xs text-text-muted">{lang === 'it' ? 'Trascrizione' : 'Transcription'}</span>
              <strong className="mt-1 block text-sm text-text-primary">{asrLocation}</strong>
            </div>
            <div className="rounded-xl border border-border-subtle bg-bg-surface/30 p-4">
              <span className="block text-xs text-text-muted">{lang === 'it' ? 'Note e analisi' : 'Notes & analysis'}</span>
              <strong className="mt-1 block text-sm text-text-primary">{analysisLocation}</strong>
            </div>
          </div>
        </Card>

        <Card className="overflow-hidden p-0">
          <button
            type="button"
            onClick={() => setShowAdvancedProcessing((open) => !open)}
            aria-expanded={showAdvancedProcessing}
            aria-controls="settings-advanced-processing"
            className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
          >
            <span className="flex items-start gap-3">
              <SlidersHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
              <span>
                <span className="block text-sm font-semibold text-text-primary">
                  {lang === 'it' ? 'Processing avanzato' : 'Advanced processing'}
                </span>
                <span className="mt-0.5 block text-xs font-normal text-text-muted">
                  {lang === 'it'
                    ? 'Provider, modelli e override di qualità. Non servono nell’uso normale.'
                    : 'Providers, models and quality overrides. Normal use does not require these.'}
                </span>
              </span>
            </span>
            <ChevronDown className={`h-4 w-4 shrink-0 text-text-muted transition-transform ${showAdvancedProcessing ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>

          {showAdvancedProcessing && (
            <div id="settings-advanced-processing" className="flex flex-col gap-6 border-t border-border-subtle p-5">
              <section className="flex flex-col gap-4">
                <div>
                  <h4 className="text-sm font-semibold text-text-primary">{t('settings.transcriptionDefaultsTitle')}</h4>
                  <p className="mt-1 text-xs text-text-muted">{t('settings.transcriptionDefaultsDesc')}</p>
                </div>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <Select label="Provider ASR" value={asrProvider} onChange={(event) => setAsrProvider(event.target.value)}>
                    {ASR_PROVIDERS.map((provider) => <option key={provider.value} value={provider.value}>{provider.label}</option>)}
                  </Select>
                  {asrProvider === 'local' && (
                    <Select label={t('transcription.modelLabel')} value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)}>
                      {MODELS.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
                    </Select>
                  )}
                  {asrProvider === 'local' && (
                    <Select label={t('transcription.taskLabel')} value={defaultTask} onChange={(event) => setDefaultTask(event.target.value)}>
                      {TASKS.map((task) => <option key={task.value} value={task.value}>{task.label}</option>)}
                    </Select>
                  )}
                  {asrProvider === 'local' && (
                    <Input
                      label={t('transcription.temperatureLabel')}
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      placeholder="Auto"
                      value={defaultTemperature}
                      onChange={(event) => setDefaultTemperature(event.target.value)}
                    />
                  )}
                </div>

                {asrProvider === 'speechmatics' && (
                  <div className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-bg-surface/30 p-4 md:grid-cols-2">
                    <Select label="Speechmatics region" value={speechmaticsRegion} onChange={(event) => setSpeechmaticsRegion(event.target.value)}>
                      {SPEECHMATICS_REGIONS.map((region) => <option key={region.value} value={region.value}>{region.label}</option>)}
                    </Select>
                    <Select label="Speechmatics model" value={speechmaticsModel} onChange={(event) => setSpeechmaticsModel(event.target.value)}>
                      {SPEECHMATICS_MODELS.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
                    </Select>
                    <Select label="Diarization" value={speechmaticsDiarization} onChange={(event) => setSpeechmaticsDiarization(event.target.value)}>
                      {SPEECHMATICS_DIARIZATION.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
                    </Select>
                    <Input
                      label={`API key${speechmaticsKeyConfigured ? (lang === 'it' ? ' configurata' : ' configured') : ''}`}
                      type="password"
                      value={speechmaticsApiKey}
                      onChange={(event) => setSpeechmaticsApiKey(event.target.value)}
                      placeholder={speechmaticsKeyConfigured
                        ? (lang === 'it' ? 'Lascia vuoto per mantenere la chiave salvata' : 'Leave blank to keep the saved key')
                        : 'Speechmatics API key'}
                    />
                  </div>
                )}

                {asrProvider === 'local' && (
                  <div className="flex flex-col gap-3 border-t border-border-subtle pt-4">
                    <Checkbox variant="toggle" label={t('transcription.wordTimestampsLabel')} checked={wordTimestamps} onChange={(event) => setWordTimestamps(event.target.checked)} />
                    <Checkbox variant="toggle" label={t('transcription.conditionLabel')} checked={conditionOnPrevious} onChange={(event) => setConditionOnPrevious(event.target.checked)} />
                  </div>
                )}
              </section>

              <section className="flex flex-col gap-4 border-t border-border-subtle pt-5">
                <div>
                  <h4 className="text-sm font-semibold text-text-primary">{t('settings.aiAnalysisTitle')}</h4>
                  <p className="mt-1 text-xs text-text-muted">
                    {lang === 'it'
                      ? 'Override espliciti per note e analisi.'
                      : 'Explicit overrides for notes and analysis.'}
                  </p>
                </div>
                <Select
                  label={t('settings.providerLabel')}
                  value={llmProvider}
                  onChange={(event) => {
                    const provider = event.target.value;
                    setLlmProvider(provider);
                    if (provider === 'nemotron_local') setLocalLlmModel(DEFAULTS.localLlmModel);
                    if (provider === 'voxtral_local') setLocalLlmModel('voxtral-mini-3b');
                  }}
                >
                  {LLM_PROVIDERS.map((provider) => <option key={provider.value} value={provider.value}>{t(provider.settingsLabelKey)}</option>)}
                </Select>

                {llmProvider === 'gemini' && (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Select label={lang === 'it' ? 'Modello Gemini' : 'Gemini model'} value={geminiModel} onChange={(event) => setGeminiModel(event.target.value)}>
                      {GEMINI_MODELS.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
                    </Select>
                    <Input
                      label={t('settings.apiKeyLabel')}
                      type="password"
                      value={geminiApiKey}
                      onChange={(event) => setGeminiApiKey(event.target.value)}
                      placeholder={lang === 'it' ? 'Lascia vuoto per usare la chiave salvata' : 'Leave blank to use the saved key'}
                    />
                    {geminiModel === 'custom' && (
                      <Input label="Gemini model ID" value={customGeminiModel} onChange={(event) => setCustomGeminiModel(event.target.value)} placeholder="gemini-..." className="md:col-span-2" />
                    )}
                  </div>
                )}

                {localProvider && (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Select label={t('settings.localLlmActiveModel')} value={localLlmModel} onChange={(event) => setLocalLlmModel(event.target.value)}>
                      {LOCAL_LLM_MODELS.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
                    </Select>
                    <Select label={t('settings.localLlmQuality')} value={localLlmQualityPreset} onChange={(event) => setLocalLlmQualityPreset(event.target.value as LocalLlmQualityPreset)}>
                      {LOCAL_LLM_QUALITY_PRESETS.map((preset) => <option key={preset.value} value={preset.value}>{t(preset.labelKey)}</option>)}
                    </Select>
                  </div>
                )}
              </section>

              <section className="flex flex-col gap-4 border-t border-border-subtle pt-5">
                <div>
                  <h4 className="text-sm font-semibold text-text-primary">
                    {lang === 'it' ? 'Override workflow' : 'Workflow overrides'}
                  </h4>
                  <p className="mt-1 text-xs text-text-muted">
                    {lang === 'it'
                      ? 'Compatibilità e controlli esperti. ClosedRoom li renderà progressivamente automatici o on-demand.'
                      : 'Compatibility and expert controls. ClosedRoom will progressively make these automatic or on-demand.'}
                  </p>
                </div>
                <Checkbox variant="toggle" label={t('settings.speakerDiarization')} checked={speakerDiarizationEnabled} onChange={(event) => setSpeakerDiarizationEnabled(event.target.checked)} />
                <Checkbox variant="toggle" label={t('settings.visualIntelligence')} checked={visualIntelligenceEnabled} onChange={(event) => setVisualIntelligenceEnabled(event.target.checked)} />
                <Select label={t('settings.meetingDefaultPipeline')} value={meetingDefaultPipeline} onChange={(event) => setMeetingDefaultPipeline(event.target.value)}>
                  <option value="meeting_default">{t('settings.meetingPipelineDefault')}</option>
                  <option value="meeting_deep">{t('settings.meetingPipelineDeep')}</option>
                </Select>
              </section>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden p-0">
          <button
            type="button"
            onClick={() => setShowDiagnostics((open) => !open)}
            aria-expanded={showDiagnostics}
            aria-controls="settings-developer-diagnostics"
            className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
          >
            <span className="flex items-start gap-3">
              <Bug className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
              <span>
                <span className="block text-sm font-semibold text-text-primary">
                  {lang === 'it' ? 'Sviluppatore e diagnostica' : 'Developer & diagnostics'}
                </span>
                <span className="mt-0.5 block text-xs font-normal text-text-muted">
                  {lang === 'it'
                    ? 'Runtime, endpoint, path modello, parametri interni e log.'
                    : 'Runtime, endpoints, model paths, internal parameters and logs.'}
                </span>
              </span>
            </span>
            <ChevronDown className={`h-4 w-4 shrink-0 text-text-muted transition-transform ${showDiagnostics ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>

          {showDiagnostics && (
            <div id="settings-developer-diagnostics" className="flex flex-col gap-5 border-t border-border-subtle p-5">
              {localProvider && (
                <section className="flex flex-col gap-4">
                  <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-secondary">
                    <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                    {lang === 'it' ? 'Runtime locale' : 'Local runtime'}
                  </h4>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Select label={t('settings.localLlmMode')} value={localLlmMode} onChange={(event) => setLocalLlmMode(event.target.value as LocalLlmMode)}>
                      <option value="auto">{t('settings.localLlmModeAuto')}</option>
                      <option value="external">{t('settings.localLlmModeExternal')}</option>
                      <option value="disabled">{t('settings.localLlmModeDisabled')}</option>
                    </Select>
                    <Select label={t('settings.localLlmReasoning')} value={localLlmReasoning} onChange={(event) => setLocalLlmReasoning(event.target.value as LocalLlmReasoning)}>
                      {LOCAL_LLM_REASONING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{t(option.labelKey)}</option>)}
                    </Select>
                    <Input
                      label={t('settings.localLlmTemperature')}
                      type="number"
                      step="0.05"
                      min="0"
                      max="2"
                      value={localLlmTemperature}
                      onChange={(event) => setLocalLlmTemperature(event.target.value)}
                      placeholder={lang === 'it' ? 'Default del preset' : 'Preset default'}
                    />
                    <Input
                      label={t('settings.localLlmMaxTokens')}
                      type="number"
                      min="1"
                      value={localLlmMaxOutputTokens}
                      onChange={(event) => setLocalLlmMaxOutputTokens(event.target.value)}
                      placeholder={lang === 'it' ? 'Nessun limite specifico' : 'No specific limit'}
                    />
                  </div>
                  <Checkbox variant="toggle" label={t('settings.localLlmJsonMode')} checked={localLlmJsonMode} onChange={(event) => setLocalLlmJsonMode(event.target.checked)} />

                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="settings-local-model-path" className="text-sm font-medium text-text-secondary">
                      {lang === 'it' ? 'Percorso modello .gguf' : 'Model .gguf path'}
                    </label>
                    <div className="flex gap-2">
                      <Input id="settings-local-model-path" value={localLlmModelPath} onChange={(event) => setLocalLlmModelPath(event.target.value)} className="flex-1" />
                      <Button type="button" variant="secondary" onClick={() => handleBrowse('model')}>{t('settings.btnBrowse')}</Button>
                    </div>
                  </div>

                  {localLlmMode === 'external' && (
                    <Input label={t('settings.localLlmUrl')} value={localLlmUrl} onChange={(event) => setLocalLlmUrl(event.target.value)} placeholder="http://127.0.0.1:1235" />
                  )}
                </section>
              )}

              {(localProvider || visualIntelligenceEnabled) && (
                <section className="flex flex-col gap-4 border-t border-border-subtle pt-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <Bug className="h-4 w-4 text-text-muted" aria-hidden="true" />
                        <h4 className="text-sm font-semibold text-text-primary">{t('settings.localLlmServiceTitle')}</h4>
                        <Badge variant={llmService?.status === 'ready' ? 'success' : llmService?.status === 'failed' || llmService?.status === 'crashed' ? 'danger' : 'warning'}>
                          {llmService?.status || 'unknown'}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-text-muted">{t('settings.localLlmServiceDesc')}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" size="sm" variant="secondary" onClick={() => runLlmAction('start')} isLoading={llmAction === 'start'}>{t('settings.localLlmStart')}</Button>
                      <Button type="button" size="sm" variant="secondary" onClick={() => runLlmAction('stop')} isLoading={llmAction === 'stop'}>{t('settings.localLlmStop')}</Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => runLlmAction('restart')} isLoading={llmAction === 'restart'}>{t('settings.localLlmRestart')}</Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => runLlmAction('logs')} isLoading={llmAction === 'logs'}>{t('settings.localLlmLogs')}</Button>
                      <Button type="button" size="sm" variant="ghost" onClick={refreshLlmService}>
                        <RefreshCw className="h-4 w-4" />
                        {lang === 'it' ? 'Aggiorna' : 'Refresh'}
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-2 rounded-xl border border-border-subtle bg-bg-surface/30 p-4 text-xs text-text-muted md:grid-cols-2">
                    <span>{t('settings.localLlmManaged')}: {llmService?.managed ? 'yes' : 'no'}</span>
                    <span>{t('settings.localLlmPort')}: {llmService?.port || t('common.notAvailable')}</span>
                    {llmService?.loaded_model && (
                      <span className="md:col-span-2">
                        <strong className="text-text-secondary">{t('settings.localLlmActiveModel')}</strong>: {llmService.loaded_model}{' '}
                        {llmService.loaded_model_id && `(${llmService.loaded_model_id})`}{' '}
                        {llmService.loaded_model_backend ? `[${llmService.loaded_model_backend}]` : ''}
                      </span>
                    )}
                    {llmService?.url && (
                      <span className="break-all md:col-span-2">
                        <strong className="text-text-secondary">{t('settings.localLlmWebUi')}</strong>: {llmService.url}
                      </span>
                    )}
                    {llmService?.error && <span className="text-danger md:col-span-2">{llmService.error}</span>}
                  </div>

                  {llmLogs && (
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-bg-base p-3 text-[11px] text-text-secondary">{llmLogs}</pre>
                  )}
                </section>
              )}

              <section className="grid grid-cols-2 gap-3 border-t border-border-subtle pt-5 text-xs">
                <span className="text-text-muted">{t('settings.sysServer')}</span>
                <span className="font-mono text-text-primary">{sysInfo.server}</span>
                <span className="text-text-muted">{t('settings.sysActiveModel')}</span>
                <span className="font-medium text-text-primary">{sysInfo.activeModel}</span>
                <span className="text-text-muted">{t('settings.sysVersion')}</span>
                <span className="font-mono text-text-primary">{sysInfo.version}</span>
                <span className="text-text-muted">{t('settings.sysMacosMenu')}</span>
                <span className="font-medium text-success">{sysInfo.menubar}</span>
              </section>
            </div>
          )}
        </Card>

        {accessibility && !accessibility.trusted && (
          <Card className="border-warning/30 bg-warning/10" role="alert">
            <strong className="text-sm text-warning">{t('settings.accessibilityWarningTitle')}</strong>
            <p className="mt-1 text-xs text-text-secondary">{t('settings.accessibilityWarningDesc')}</p>
            <p className="mt-2 text-xs font-medium text-text-primary">{t('settings.accessibilityWarningAction')}</p>
            {accessibility.error && <p className="mt-2 text-xs text-danger">{accessibility.error}</p>}
          </Card>
        )}

        <div className="flex justify-end">
          <Button type="submit" size="lg" isLoading={saving} className="w-full sm:w-auto">
            {t('settings.btnSave')}
          </Button>
        </div>
      </form>
    </div>
  );
}
