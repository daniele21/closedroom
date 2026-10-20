import { useEffect, useState } from 'react';
import { Bug, ChevronDown, PanelTop, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { AccessibilityStatus, ApiClient, MenuBarStatus, Settings } from '../api/apiClient';
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
  const [meetingDetectionEnabled, setMeetingDetectionEnabled] = useState(false);
  const [meetingDetectionWasEnabled, setMeetingDetectionWasEnabled] = useState(false);
  const [meetingDefaultPipeline, setMeetingDefaultPipeline] = useState('meeting_default');
  const [speakerDiarizationEnabled, setSpeakerDiarizationEnabled] = useState(false);
  const [diarizationEngine, setDiarizationEngine] = useState<"fluidaudio-community-1" | "nemotron3-coreml">("fluidaudio-community-1");
  const [nemotronPreset, setNemotronPreset] = useState<"fast128" | "c128-split-w8a8">("fast128");
  const [visualIntelligenceEnabled, setVisualIntelligenceEnabled] = useState(false);
  const [accessibility, setAccessibility] = useState<AccessibilityStatus | null>(null);
  const [menuBarStatus, setMenuBarStatus] = useState<MenuBarStatus | null>(null);
  const [menuBarAction, setMenuBarAction] = useState(false);
  const [sysInfo, setSysInfo] = useState({
    server: '127.0.0.1:1236',
    activeModel: '',
    version: '1.0.0',
  });

  const refreshLlmService = async () => {
    try {
      setLlmService(await ApiClient.getLlmService());
    } catch (err: any) {
      setLlmService({ name: 'llm', status: 'unknown', error: err.message });
    }
  };

  const refreshMenuBarStatus = async () => {
    try {
      setMenuBarStatus(await ApiClient.menuBarStatus());
    } catch (err: any) {
      setMenuBarStatus({
        available: false,
        visible: false,
        icon_loaded: false,
        state: 'unavailable',
        icon_asset: 'design/assets/brand/closedroom-microphone-mark.png',
        repair_count: 0,
        last_error: err?.message || 'menu_bar_status_unavailable',
      });
    }
  };

  const handleRefreshMenuBar = async () => {
    setMenuBarAction(true);
    try {
      const status = await ApiClient.refreshMenuBar();
      setMenuBarStatus(status);
      showToast(
        status.visible && status.icon_loaded
          ? (lang === 'it' ? 'Icona della menu bar ripristinata.' : 'Menu bar icon restored.')
          : (lang === 'it' ? 'ClosedRoom ha richiesto di mostrare di nuovo l’icona.' : 'ClosedRoom requested the menu bar icon again.'),
        status.visible && status.icon_loaded ? 'success' : 'info',
      );
    } catch (err: any) {
      showToast(
        err?.message || (lang === 'it' ? 'Impossibile ripristinare la menu bar.' : 'Unable to restore the menu bar.'),
        'error',
      );
      await refreshMenuBarStatus();
    } finally {
      setMenuBarAction(false);
    }
  };

  const handleOpenMenuBarSettings = async () => {
    try {
      const result = await ApiClient.openMenuBarSettings();
      if (!result.opened) throw new Error('System Settings unavailable');
      showToast(lang === 'it'
        ? 'In Barra dei menu, abilita ClosedRoom in “Consenti nella barra dei menu”.'
        : 'In Menu Bar, enable ClosedRoom under “Allow in the Menu Bar”.', 'info');
    } catch (err: any) {
      showToast(err?.message || t('common.error'), 'error');
    }
  };

  const handleMeetingNotificationPermission = async () => {
    if (!meetingDetectionWasEnabled) {
      showToast(lang === 'it' ? 'Prima salva le impostazioni.' : 'Save settings first.', 'warning');
      return;
    }
    try {
      const result = await ApiClient.authorizeMeetingDetection();
      if (!result.requested) {
        showToast(lang === 'it' ? 'Le notifiche native non sono disponibili.' : 'Native notifications are unavailable.', 'warning');
      }
      await refreshMenuBarStatus();
    } catch (err: any) {
      showToast(err?.message || t('common.error'), 'error');
    }
  };

  const handleOpenNotificationSettings = async () => {
    try {
      const result = await ApiClient.openNotificationSettings();
      if (!result.opened) throw new Error('System Settings unavailable');
    } catch (err: any) {
      showToast(err?.message || t('common.error'), 'error');
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
      setMeetingDetectionEnabled(Boolean(settings.meeting_detection_enabled));
      setMeetingDetectionWasEnabled(Boolean(settings.meeting_detection_enabled));
      setMeetingDefaultPipeline(settings.meeting_default_pipeline || 'meeting_default');
      setSpeakerDiarizationEnabled(Boolean(settings.speaker_diarization_enabled));
      setDiarizationEngine(settings.speaker_diarization_engine || "fluidaudio-community-1");
      setNemotronPreset(settings.speaker_diarization_nemotron_preset || "fast128");
      setVisualIntelligenceEnabled(Boolean(settings.visual_intelligence_enabled));

      void refreshLlmService();
      void refreshMenuBarStatus();
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
        meeting_detection_enabled: meetingDetectionEnabled,
        meeting_default_pipeline: meetingDefaultPipeline,
        speaker_diarization_enabled: speakerDiarizationEnabled,
        speaker_diarization_engine: diarizationEngine,
        speaker_diarization_nemotron_preset: nemotronPreset,
        visual_intelligence_enabled: visualIntelligenceEnabled,
      };
      if (geminiApiKey.trim()) payload.gemini_api_key = geminiApiKey.trim();
      if (speechmaticsApiKey.trim()) payload.speechmatics_api_key = speechmaticsApiKey.trim();

      await ApiClient.updateSettings(payload);
      if (meetingDetectionEnabled && !meetingDetectionWasEnabled) {
        // Permission is requested only after the user explicitly enables and saves.
        await ApiClient.authorizeMeetingDetection().catch(() => {
          showToast(lang === 'it' ? 'Notifiche non disponibili: puoi registrare dalla menu bar.' : 'Notifications unavailable: recording remains available from the menu bar.', 'warning');
        });
      }
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

        <Card className="flex flex-col gap-3" data-settings-meeting-detection="true">
          <h3 className="text-sm font-semibold text-text-primary">
            {lang === 'it' ? 'Rilevamento riunioni' : 'Meeting detection'}
          </h3>
          <p className="text-xs text-text-secondary">
            {lang === 'it'
              ? 'Quando Zoom o Teams usano il microfono, ClosedRoom può proporti di registrare. Il rilevamento avviene sul Mac senza ascoltare l’audio. Non registra senza un tuo click.'
              : 'When Zoom or Teams use the microphone, ClosedRoom can suggest recording. Detection stays on your Mac without listening to audio. Recording requires your click.'}
          </p>
          <Checkbox
            variant="toggle"
            label={lang === 'it' ? 'Suggerisci di registrare i meeting' : 'Suggest recording meetings'}
            checked={meetingDetectionEnabled}
            onChange={(event) => setMeetingDetectionEnabled(event.target.checked)}
          />
          <p className="text-xs text-text-muted" role="status">
            {lang === 'it'
              ? 'Disattivato inizialmente. Salva per attivare e richiedere il permesso per le notifiche; avvia ClosedRoom al login se vuoi ricevere i suggerimenti.'
              : 'Off by default. Save to enable and request notification permission; start ClosedRoom at login for background suggestions.'}
          </p>
          {meetingDetectionEnabled && menuBarStatus?.meeting_detection && (
            <div className="space-y-2 text-xs text-text-secondary" data-meeting-detection-diagnostics="true">
              <p role="status">
                {menuBarStatus.meeting_detection.active_apps?.length
                  ? (lang === 'it' ? 'Microfono attivo: ' : 'Active microphone: ') + menuBarStatus.meeting_detection.active_apps.join(', ')
                  : menuBarStatus.meeting_detection.capability === 'supported'
                    ? (lang === 'it'
                      ? 'Monitor disponibile · Nessuna chiamata Zoom/Teams identificata'
                      : 'Monitor available · No Zoom/Teams call identified')
                    : (lang === 'it' ? 'Monitor non disponibile: ' : 'Monitor unavailable: ') + menuBarStatus.meeting_detection.capability}
              </p>
              <p>
                {lang === 'it' ? 'Processi audio in input: ' : 'Active input processes: '}
                {menuBarStatus.meeting_detection.active_input_processes ?? 0}
                {' · '}{lang === 'it' ? 'Senza identità: ' : 'Unattributed: '}
                {menuBarStatus.meeting_detection.unattributed_input_processes ?? 0}
                {' · '}{lang === 'it' ? 'Notifiche: ' : 'Notifications: '}
                {menuBarStatus.meeting_detection.notifications}
              </p>
              {menuBarStatus.meeting_detection.notifications !== 'authorized' && (
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" onClick={handleMeetingNotificationPermission}>
                    {lang === 'it' ? 'Richiedi permesso notifiche' : 'Request notifications'}
                  </Button>
                  <Button type="button" variant="ghost" onClick={handleOpenNotificationSettings}>
                    {lang === 'it' ? 'Impostazioni notifiche macOS' : 'macOS notification settings'}
                  </Button>
                </div>
              )}
              {menuBarStatus.meeting_detection.notification_error && (
                <p role="alert" className="text-warning">{menuBarStatus.meeting_detection.notification_error}</p>
              )}
              <Button type="button" variant="ghost" onClick={refreshMenuBarStatus}>
                {lang === 'it' ? 'Aggiorna rilevamento' : 'Refresh detection status'}
              </Button>
            </div>
          )}
        </Card>

        <Card className="flex flex-col gap-4" data-settings-menubar="true">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border-subtle bg-bg-surface/40">
                <img
                  src="/brand/closedroom-microphone-mark.png"
                  alt=""
                  className="h-7 w-7 object-contain"
                  aria-hidden="true"
                />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <PanelTop className="h-4 w-4 text-text-muted" aria-hidden="true" />
                  <h3 className="text-sm font-semibold text-text-primary">Menu bar</h3>
                </div>
                <p className="mt-1 text-xs text-text-muted">
                  {lang === 'it'
                    ? 'Questa è l’icona che ClosedRoom prova a mantenere visibile nella barra dei menu.'
                    : 'This is the icon ClosedRoom tries to keep visible in the menu bar.'}
                </p>
              </div>
            </div>
            <Badge variant={menuBarStatus?.available && menuBarStatus?.icon_loaded ? 'info' : 'warning'}>
              {menuBarStatus?.available && menuBarStatus?.icon_loaded
                ? (lang === 'it' ? 'Item creato' : 'Item created')
                : (lang === 'it' ? 'Da verificare' : 'Check needed')}
            </Badge>
          </div>

          <div className="rounded-xl border border-border-subtle bg-bg-surface/30 p-4">
            <p className="text-sm text-text-secondary">
              {menuBarStatus?.visible && menuBarStatus?.icon_loaded
                ? (lang === 'it'
                    ? 'ClosedRoom ha creato correttamente l’item della menu bar. Se non lo vedi, è probabilmente nascosto da macOS o da un menu-bar manager.'
                    : 'ClosedRoom created the menu bar item correctly. If you still cannot see it, macOS or a menu bar manager is probably hiding it.')
                : (lang === 'it'
                    ? 'ClosedRoom non riesce ancora a confermare l’item della menu bar. Prova a ripristinarlo.'
                    : 'ClosedRoom cannot confirm the menu bar item yet. Try restoring it.')}
            </p>
            {menuBarStatus?.last_error && menuBarStatus.last_error !== 'menubar_controller_unavailable' && (
              <p className="mt-2 break-all font-mono text-[11px] text-danger">{menuBarStatus.last_error}</p>
            )}
            <p className="mt-2 text-xs text-text-muted">
              {lang === 'it'
                ? 'macOS 26 può nascondere l’item anche quando ClosedRoom lo segnala visibile.'
                : 'macOS 26 may hide this item even when ClosedRoom reports it as visible.'}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" variant="primary" onClick={handleOpenMenuBarSettings}>
                {lang === 'it' ? 'Apri Barra dei menu di macOS' : 'Open macOS Menu Bar settings'}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={handleRefreshMenuBar}
                disabled={menuBarAction || menuBarStatus?.available === false}
              >
                <RefreshCw className={`mr-2 h-4 w-4 ${menuBarAction ? 'animate-spin' : ''}`} aria-hidden="true" />
                {lang === 'it' ? 'Mostra di nuovo' : 'Show again'}
              </Button>
              <Button type="button" variant="ghost" onClick={refreshMenuBarStatus}>
                {lang === 'it' ? 'Ricontrolla' : 'Check again'}
              </Button>
            </div>
          </div>

          <details className="group rounded-xl border border-border-subtle bg-bg-surface/20 px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-text-primary">
              {lang === 'it' ? 'Non la vedi ancora?' : 'Still cannot see it?'}
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-5 text-text-secondary">
              <p>
                {lang === 'it'
                  ? '• Prima apri Impostazioni di Sistema → Barra dei menu e abilita ClosedRoom sotto “Consenti nella barra dei menu”. Poi verifica l’eventuale spazio insufficiente sul MacBook con notch.'
                  : '• First open System Settings → Menu Bar and enable ClosedRoom under “Allow in the Menu Bar”. Then check for insufficient space on MacBooks with a notch.'}
              </p>
              <p>
                {lang === 'it'
                  ? '• Se usi Bartender, Ice, Hidden Bar o app simili, imposta ClosedRoom tra gli elementi sempre visibili.'
                  : '• If you use Bartender, Ice, Hidden Bar, or a similar app, set ClosedRoom to always visible there.'}
              </p>
              <p>
                {lang === 'it'
                  ? '• ClosedRoom deve rimanere in esecuzione. Se lo stato sopra è “Attiva” ma l’icona non appare, chiudi e riapri ClosedRoom dopo aver liberato spazio nella barra.'
                  : '• ClosedRoom must keep running. If the status above says Active but the icon is still missing, quit and reopen ClosedRoom after freeing menu bar space.'}
              </p>
            </div>
          </details>
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
                {speakerDiarizationEnabled && (
                  <div className="space-y-3" data-settings-diarization-engine="true">
                    <Select
                      label={lang === 'it' ? 'Motore diarizzazione locale' : 'Local diarization engine'}
                      value={diarizationEngine}
                      onChange={(event) => setDiarizationEngine(event.target.value as typeof diarizationEngine)}
                    >
                      <option value="fluidaudio-community-1">FluidAudio Community-1 · {lang === 'it' ? 'Stabile' : 'Stable'}</option>
                      <option value="nemotron3-coreml">NVIDIA Nemotron 3 · {lang === 'it' ? 'Sperimentale' : 'Experimental'}</option>
                    </Select>
                    {diarizationEngine === 'nemotron3-coreml' && (
                      <>
                        <Select
                          label={lang === 'it' ? 'Preset Nemotron 3' : 'Nemotron 3 preset'}
                          value={nemotronPreset}
                          onChange={(event) => setNemotronPreset(event.target.value as typeof nemotronPreset)}
                        >
                          <option value="fast128">fast128 · {lang === 'it' ? 'Precisione' : 'Accuracy'}</option>
                          <option value="c128-split-w8a8">c128-split-w8a8 · {lang === 'it' ? 'Peso ridotto' : 'Smaller model'}</option>
                        </Select>
                        <p className="text-xs text-text-muted">
                          {lang === 'it'
                            ? 'Sperimentale: il primo utilizzo scarica solo i pesi del preset scelto. La registrazione non viene inviata online. Senza modello disponibile offline, la diarizzazione fallisce senza cambiare il transcript.'
                            : 'Experimental: first use downloads only the selected model weights. No recording is uploaded. If the model is unavailable offline, diarization fails without changing the transcript.'}
                        </p>
                      </>
                    )}
                  </div>
                )}
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
                <span className={`font-medium ${menuBarStatus?.visible && menuBarStatus?.icon_loaded ? 'text-success' : 'text-warning'}`}>
                  {menuBarStatus?.visible && menuBarStatus?.icon_loaded
                    ? (lang === 'it' ? 'Creata e visibile per macOS' : 'Created and visible to macOS')
                    : (lang === 'it' ? 'Da verificare' : 'Needs checking')}
                </span>
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
