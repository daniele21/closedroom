import { useMemo, useState } from 'react';
import type { TranscriptionSegment } from '../../api/apiClient';
import type { SpeakerDisplayMapping } from '../../utils/speakerPresentation';
import { formatTime } from '../../utils/formatters';
import { useTranslation } from '../../i18n/i18n';

interface Props {
  turns: TranscriptionSegment[];
  mappings: SpeakerDisplayMapping[];
  sourceTrackLabels: string[];
  overrides: Record<string, string>;
  onSave: (segment: TranscriptionSegment, target: string | null) => Promise<void>;
  onDismiss: () => void;
}

/** Scoped user correction, never a whole-cluster rename and never an ASR edit. */
export function TurnSpeakerCorrection({
  turns, mappings, sourceTrackLabels, overrides, onSave, onDismiss,
}: Props) {
  const { lang } = useTranslation();
  const it = lang === 'it';
  const [segmentId, setSegmentId] = useState(turns[0]?.id ?? -1);
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selected = turns.find((turn) => turn.id === segmentId);
  const override = selected && Object.prototype.hasOwnProperty.call(overrides, String(selected.id));
  const candidates = useMemo(() => {
    const sourceNames = new Set([...sourceTrackLabels, 'Computer', 'System', 'System track']
      .map((name) => name.toLocaleLowerCase()));
    return mappings.filter((entry) =>
      entry.speaker_cluster &&
      entry.status !== 'excluded' && entry.status !== 'merged' &&
      (entry.status === 'accepted' || !sourceNames.has(entry.speaker_cluster.toLocaleLowerCase()))
    );
  }, [mappings, sourceTrackLabels]);
  const originalGroup = selected?.speaker_group || selected?.provider_speaker || selected?.speaker_label;
  const valid = !!selected && !!target &&
    (target === '__restore_original__' ? Boolean(override) : target !== originalGroup);
  const submit = async () => {
    if (!valid || busy || !selected) return;
    setError('');
    setBusy(true);
    try {
      await onSave(selected, target === '__restore_original__' ? null : target);
      onDismiss();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-turn-correction="true" className="mt-3 rounded-lg border border-border-subtle bg-bg-surface p-3"
      onKeyDown={(event) => { if (event.key === 'Escape' && !busy) { event.stopPropagation(); onDismiss(); } }}>
      <p className="text-sm font-semibold text-text-primary">
        {it ? 'Correggi chi ha parlato' : 'Correct the speaker'}
      </p>
      <p className="mb-3 mt-1 text-xs text-text-secondary">
        {it ? 'Modifica soltanto la battuta selezionata, non tutte le frasi della voce.'
          : 'Change only the selected turn, not every turn from this voice.'}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          {it ? 'Battuta' : 'Turn'}
          <select value={segmentId} disabled={busy} data-turn-segment-select="true"
            onChange={(event) => { setSegmentId(Number(event.target.value)); setTarget(''); setError(''); }}
            className="w-full min-w-0 rounded-md border border-border-subtle bg-bg-elevated px-2 py-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-border-focus">
            {turns.map((turn) => (
              <option key={turn.id} value={turn.id}>
                {formatTime(turn.start)} · {turn.text.trim().slice(0, 60)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          {it ? 'Attribuisci a' : 'Assign to'}
          <select value={target} onChange={(event) => { setTarget(event.target.value); setError(''); }}
            data-turn-target-select="true" disabled={busy}
            className="w-full min-w-0 rounded-md border border-border-subtle bg-bg-elevated px-2 py-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-border-focus">
            <option value="">{it ? 'Scegli una voce…' : 'Select a voice…'}</option>
            {candidates.map((entry) => (
              <option key={entry.speaker_cluster} value={entry.speaker_cluster}>
                {entry.display_name || (it ? 'Voce da identificare' : 'Unidentified voice')}
              </option>
            ))}
            {override && <option value="__restore_original__">
              {it ? 'Ripristina attribuzione originale' : 'Restore original attribution'}
            </option>}
          </select>
        </label>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-danger">
        {error} {it ? 'Puoi ricaricare il meeting e riprovare.' : 'Reload the meeting and retry.'}
      </p>}
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button type="button" disabled={busy} onClick={onDismiss}
          className="rounded-md px-3 py-2 text-xs text-text-secondary hover:bg-bg-hover focus-visible:outline-2 focus-visible:outline-border-focus">
          {it ? 'Annulla' : 'Cancel'}
        </button>
        <button type="button" data-turn-save="true" disabled={!valid || busy} onClick={() => void submit()}
          className="rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-border-focus">
          {busy ? (it ? 'Salvataggio…' : 'Saving…') : (it ? 'Salva questa battuta' : 'Save this turn')}
        </button>
      </div>
    </div>
  );
}
