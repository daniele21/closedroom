import { ListChecks, Sparkles } from 'lucide-react';

interface MeetingAnalysisChoicesProps {
  lang: string;
  hasTranscription: boolean;
  disabled: boolean;
  onPrepare: () => void;
  onDeepAnalysis: () => void;
}

// Outcome selection is purely presentational. MeetingDetailPage owns
// preparation/pipeline submission, provenance and error recovery.
export function MeetingAnalysisChoices({
  lang, hasTranscription, disabled, onPrepare, onDeepAnalysis,
}: MeetingAnalysisChoicesProps) {
  const it = lang === 'it';
  return (
    <section aria-labelledby="meeting-analysis-choices-title" className="space-y-4" data-meeting-analysis-choices="true">
      <div>
        <h4 id="meeting-analysis-choices-title" className="text-base font-semibold text-text-primary">
          {it ? 'Cosa vuoi ottenere?' : 'What would you like to get?'}
        </h4>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          {it
            ? 'Scegli un risultato. ClosedRoom usa le fonti già salvate del meeting.'
            : 'Choose an outcome. ClosedRoom uses this meeting’s existing saved sources.'}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <button
          type="button"
          data-meeting-outcome="summary"
          onClick={onPrepare}
          disabled={disabled}
          className="flex min-h-28 flex-col items-start gap-2 rounded-xl border border-accent/40 bg-accent/10 p-4 text-left transition-colors hover:bg-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Sparkles className="h-5 w-5 text-accent" aria-hidden="true" />
          <span className="text-sm font-semibold text-text-primary">
            {it ? 'Sintesi e prossimi passi' : 'Summary and next steps'}
          </span>
          <span className="text-xs leading-relaxed text-text-secondary">
            {hasTranscription
              ? (it ? 'Riassunto, decisioni e azioni dalla trascrizione.' : 'Summary, decisions and actions from the transcript.')
              : (it ? 'Prima trascrive la chiamata, poi prepara le note.' : 'First transcribes the call, then prepares notes.')}
          </span>
        </button>
        <button
          type="button"
          data-meeting-outcome="deep"
          onClick={onDeepAnalysis}
          disabled={disabled || !hasTranscription}
          className="flex min-h-28 flex-col items-start gap-2 rounded-xl border border-border-subtle bg-bg-surface p-4 text-left transition-colors hover:border-border-focus hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:cursor-not-allowed disabled:opacity-60"
        >
          <ListChecks className="h-5 w-5 text-accent" aria-hidden="true" />
          <span className="text-sm font-semibold text-text-primary">
            {it ? 'Approfondisci il meeting' : 'Explore the meeting in depth'}
          </span>
          <span className="text-xs leading-relaxed text-text-secondary">
            {hasTranscription
              ? (it ? 'Configura l’analisi approfondita e consulta i risultati.' : 'Configure deep analysis and review its results.')
              : (it ? 'Disponibile dopo la trascrizione.' : 'Available after transcription.')}
          </span>
        </button>
      </div>
    </section>
  );
}
