export const MODELS = [
  { value: '', label: 'Predefinito del Server', badge: 'default' },
  { value: 'mlx-community/whisper-large-v3-turbo', label: 'Whisper Large V3 Turbo', badge: 'recommended' },
  { value: 'mlx-community/nemotron-3.5-asr-streaming-0.6b', label: 'Nemotron 3.5 ASR Streaming 0.6B', badge: 'streaming' },
];

export const LOCAL_LLM_MODELS = [
  { value: 'nemotron-nano-4b-q8', label: 'Nemotron Nano 4B Q8 (Default)' },
  { value: 'voxtral-mini-3b', label: 'Voxtral Mini 3B (Audio Multimodal)' },
  { value: 'custom', label: 'File .gguf personalizzato...' },
];

export const LLM_PROVIDERS = [
  { value: 'mock', labelKey: 'analysis.providerMock', settingsLabelKey: 'settings.providerMock' },
  { value: 'gemini', labelKey: 'analysis.providerGemini', settingsLabelKey: 'settings.providerGemini' },
  { value: 'nemotron_local', labelKey: 'analysis.providerNemotron', settingsLabelKey: 'settings.providerNemotron' },
  { value: 'voxtral_local', labelKey: 'analysis.providerVoxtral', settingsLabelKey: 'settings.providerVoxtral' },
];

export const LOCAL_LLM_QUALITY_PRESETS = [
  { value: 'precise', labelKey: 'settings.localLlmQualityPrecise' },
  { value: 'balanced', labelKey: 'settings.localLlmQualityBalanced' },
  { value: 'creative', labelKey: 'settings.localLlmQualityCreative' },
];

export const LOCAL_LLM_REASONING_OPTIONS = [
  { value: 'auto', labelKey: 'settings.localLlmReasoningAuto' },
  { value: 'on', labelKey: 'settings.localLlmReasoningOn' },
  { value: 'off', labelKey: 'settings.localLlmReasoningOff' },
];

export const ASR_PROVIDERS = [
  { value: 'local', label: 'Locale MLX', cloud: false },
  { value: 'speechmatics', label: 'Speechmatics Batch', cloud: true },
];

export const SPEECHMATICS_MODELS = [
  { value: 'standard', label: 'Standard' },
  { value: 'enhanced', label: 'Enhanced' },
];

export const SPEECHMATICS_REGIONS = [
  { value: 'eu', label: 'EU' },
  { value: 'us', label: 'US' },
];

export const SPEECHMATICS_DIARIZATION = [
  { value: 'none', label: 'Disattivata' },
  { value: 'speaker', label: 'Speaker diarization' },
];

export const DIARIZATION_PROVIDERS = [
  { value: 'none', labelKey: 'transcription.initialDiarizationDisabled' },
  { value: 'local', labelKey: 'transcription.initialDiarizationLocal' },
  { value: 'speechmatics', labelKey: 'transcription.initialDiarizationSpeechmatics' },
];

export const GEMINI_MODELS = [
  { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro Preview' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'custom', label: 'Custom' },
];

export const LANGUAGES = [
  { value: 'it', label: 'Italiano' },
  { value: 'en', label: 'Inglese' },
  { value: 'es', label: 'Spagnolo' },
  { value: 'fr', label: 'Francese' },
  { value: 'de', label: 'Tedesco' },
  { value: '', label: 'Rilevamento Automatico' },
];

export const TASKS = [
  { value: 'transcribe', label: 'Trascrizione' },
  { value: 'translate', label: 'Traduzione in Inglese' },
];

export const OUTPUT_FORMATS = [
  { value: 'json', label: 'Semplice (JSON)' },
  { value: 'verbose_json', label: 'Dettagliato (Verbose JSON)' },
  { value: 'text', label: 'Solo Testo' },
];

export const DEFAULTS = {
  language: 'it',
  task: 'transcribe',
  outputFormat: 'json',
  temperature: '0.0',
  wordTimestamps: false,
  conditionOnPreviousText: false,
  vadGuided: true,
  asrProvider: 'local',
  speechmaticsModel: 'standard',
  speechmaticsRegion: 'eu',
  speechmaticsDiarization: 'none',
  llmProvider: 'mock',
  geminiModel: 'gemini-3.5-flash',
  localLlmModel: 'nemotron-nano-4b-q8',
  localLlmQualityPreset: 'balanced',
  localLlmReasoning: 'auto',
  localLlmJsonMode: true,
  theme: 'dark' as 'dark' | 'light',
};

export const ANALYSIS_TYPE_ORDER = [
  'meeting_brief',
  'action_items',
  'decisions',
  'risks_blockers',
  'meeting_minutes',
  'open_questions',
  'project_update',
  'custom_question',
];

export const ANALYSIS_TYPE_LABELS: Record<string, string> = {
  meeting_brief: 'Brief',
  action_items: 'Actions',
  decisions: 'Decisions',
  risks_blockers: 'Risks',
  meeting_minutes: 'Minutes',
  open_questions: 'Questions',
  project_update: 'Project',
  custom_question: 'Custom',
};

export const ACCEPTED_EXTENSIONS = /\.(mp3|wav|m4a|webm|flac|ogg|aac|oga)$/i;
export const ACCEPTED_MIME_PREFIX = 'audio/';
export const MAX_FILE_SIZE_MB = 25;
export const RECORDING_CHUNK_INTERVAL_MS = 5000;
export const HEALTH_CHECK_INTERVAL_MS = 60000;
export const TOAST_DURATION_MS = 4000;
export const NEW_RECORDING_PROJECT_STORAGE_KEY = 'closedroom:new-recording-project';
