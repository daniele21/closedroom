import { useEffect, useState } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogBody, DialogFooter } from './Dialog';
import { Button } from './Button';
import { Checkbox } from './Checkbox';
import { Input } from './Input';
import { Select } from './Select';
import { ApiClient, AnalysisSetupPayload, Settings } from '../../api/apiClient';
import {
  DEFAULTS,
  GEMINI_MODELS,
  LLM_PROVIDERS,
  LOCAL_LLM_MODELS,
  LOCAL_LLM_QUALITY_PRESETS,
  LOCAL_LLM_REASONING_OPTIONS,
} from '../../api/config';
import { useTranslation } from '../../i18n/i18n';
import {
  isLocalLlmProvider,
  llmAnalysisPayload,
  llmConfigFromSettings,
  type LocalLlmQualityPreset,
  type LocalLlmReasoning,
} from '../../features/config/llmConfig';

export interface AnalysisSetupSelection extends AnalysisSetupPayload {}

interface AnalysisSetupModalProps {
  isOpen: boolean;
  onConfirm: (selection: AnalysisSetupSelection) => void;
  onCancel: () => void;
  demoMode?: boolean;
  title?: string;
  description?: string;
}

export function AnalysisSetupModal({
  isOpen,
  onConfirm,
  onCancel,
  demoMode = false,
  title,
  description,
}: AnalysisSetupModalProps) {
  const { t, lang } = useTranslation();
  const [provider, setProvider] = useState(DEFAULTS.llmProvider);
  const [apiKey, setApiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState(DEFAULTS.geminiModel);
  const [customGeminiModel, setCustomGeminiModel] = useState('');
  const [localModel, setLocalModel] = useState(DEFAULTS.localLlmModel);
  const [localModelPath, setLocalModelPath] = useState('');
  const [qualityPreset, setQualityPreset] = useState<LocalLlmQualityPreset>(DEFAULTS.localLlmQualityPreset as LocalLlmQualityPreset);
  const [temperature, setTemperature] = useState('');
  const [reasoning, setReasoning] = useState<LocalLlmReasoning>(DEFAULTS.localLlmReasoning as LocalLlmReasoning);
  const [maxTokens, setMaxTokens] = useState('');
  const [jsonMode, setJsonMode] = useState(DEFAULTS.localLlmJsonMode);
  const [llmService, setLlmService] = useState<any>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setShowAdvanced(false);
    if (demoMode) return;
    let mounted = true;

    const load = async () => {
      try {
        const settings: Settings = await ApiClient.getSettings();
        if (!mounted) return;
        const config = llmConfigFromSettings(settings);
        setProvider(config.provider);
        setApiKey('');
        setGeminiModel(config.geminiModel);
        setCustomGeminiModel(config.customGeminiModel);
        setLocalModel(config.localModel);
        setLocalModelPath(config.localModelPath);
        setQualityPreset(config.qualityPreset);
        setTemperature(config.temperature);
        setReasoning(config.reasoning);
        setMaxTokens(config.maxOutputTokens);
        setJsonMode(config.jsonMode);
      } catch {}

      try {
        const service = await ApiClient.getLlmService();
        if (mounted) setLlmService(service);
      } catch {}
    };

    load();
    return () => {
      mounted = false;
    };
  }, [isOpen, demoMode]);

  const confirm = () => {
    onConfirm(llmAnalysisPayload({
      provider,
      geminiModel,
      customGeminiModel,
      localMode: 'auto',
      localUrl: '',
      localModel,
      localModelPath,
      qualityPreset,
      temperature,
      reasoning,
      maxOutputTokens: maxTokens,
      jsonMode,
    }, apiKey));
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onCancel(); }}>
      <DialogContent size="lg">
        <DialogHeader
          title={title || t('meeting.analysisSetupTitle')}
          description={description || t('meeting.analysisSetupDescription')}
        />
        <DialogBody className="flex flex-col gap-4">
          <Select label={t('settings.providerLabel')} value={provider} onChange={(e) => setProvider(e.target.value)}>
            {LLM_PROVIDERS.map((item) => (
              <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
            ))}
          </Select>

          {provider === 'gemini' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Select label={lang === 'it' ? 'Modello Gemini' : 'Gemini model'} value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}>
                {GEMINI_MODELS.map((model) => (
                  <option key={model.value} value={model.value}>{model.label}</option>
                ))}
              </Select>
              <Input
                label={t('settings.apiKeyLabel')}
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={lang === 'it' ? 'Lascia vuoto per usare la chiave salvata' : 'Leave blank to use saved key'}
              />
              {geminiModel === 'custom' && (
                <Input
                  label="Gemini model ID"
                  value={customGeminiModel}
                  onChange={(e) => setCustomGeminiModel(e.target.value)}
                  placeholder="gemini-..."
                  className="sm:col-span-2"
                />
              )}
            </div>
          )}

          {isLocalLlmProvider(provider) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Select label={t('settings.localLlmActiveModel')} value={localModel} onChange={(e) => setLocalModel(e.target.value)}>
                {LOCAL_LLM_MODELS.map((model) => (
                  <option key={model.value} value={model.value}>{model.label}</option>
                ))}
              </Select>
              <Select label={t('settings.localLlmQuality')} value={qualityPreset} onChange={(e) => setQualityPreset(e.target.value as LocalLlmQualityPreset)}>
                {LOCAL_LLM_QUALITY_PRESETS.map((item) => (
                  <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
                ))}
              </Select>
            </div>
          )}

          {isLocalLlmProvider(provider) && (
            <section className="rounded-xl border border-border-subtle bg-bg-surface/30">
              <button
                type="button"
                aria-expanded={showAdvanced}
                aria-controls="analysis-advanced-settings"
                onClick={() => setShowAdvanced((open) => !open)}
                className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-xs font-semibold text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
              >
                <span className="inline-flex items-center gap-2">
                  <SlidersHorizontal className="h-4 w-4 text-text-muted" />
                  {lang === 'it' ? 'Impostazioni avanzate' : 'Advanced settings'}
                </span>
                <ChevronDown className={`h-4 w-4 text-text-muted transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
              </button>

              {showAdvanced && (
                <div id="analysis-advanced-settings" className="flex flex-col gap-4 border-t border-border-subtle p-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Input
                      label={t('settings.localLlmTemperature')}
                      type="number"
                      step="0.05"
                      min="0"
                      max="2"
                      value={temperature}
                      onChange={(e) => setTemperature(e.target.value)}
                      placeholder={lang === 'it' ? 'Default del preset' : 'Preset default'}
                    />
                    <Select label={t('settings.localLlmReasoning')} value={reasoning} onChange={(e) => setReasoning(e.target.value as LocalLlmReasoning)}>
                      {LOCAL_LLM_REASONING_OPTIONS.map((item) => (
                        <option key={item.value} value={item.value}>{t(item.labelKey)}</option>
                      ))}
                    </Select>
                    <Input
                      label={t('settings.localLlmMaxTokens')}
                      type="number"
                      min="1"
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(e.target.value)}
                      placeholder={lang === 'it' ? 'Nessun limite specifico' : 'No specific limit'}
                    />
                    <div className="flex items-end pb-2">
                      <Checkbox
                        variant="toggle"
                        label={t('settings.localLlmJsonMode')}
                        checked={jsonMode}
                        onChange={(e) => setJsonMode(e.target.checked)}
                      />
                    </div>
                  </div>

                  <Input
                    label={lang === 'it' ? 'Percorso modello .gguf' : 'Model .gguf path'}
                    value={localModelPath}
                    onChange={(e) => setLocalModelPath(e.target.value)}
                    placeholder={lang === 'it' ? 'Lascia vuoto per usare il path salvato' : 'Leave blank to use saved path'}
                  />

                  <div className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-xs text-text-secondary">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-semibold text-text-primary">{t('settings.localLlmActiveModel')}</span>
                      <span className="font-mono">{llmService?.loaded_model || llmService?.model || t('common.notAvailable')}</span>
                      {llmService?.loaded_model_backend && <span>{llmService.loaded_model_backend}</span>}
                    </div>
                  </div>
                </div>
              )}
            </section>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="button" onClick={confirm}>
            {t('meeting.analysisSetupConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default AnalysisSetupModal;
