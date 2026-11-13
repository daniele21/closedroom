import type { RefObject } from 'react';
import { X } from 'lucide-react';

interface Props {
  lang: string;
  anchor: number;
  draft: string;
  saving: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void;
}

// Only presentation and keyboard behavior. RecordingOverlayPage still owns
// timestamp admission, local persistence, recovery and the original draft.
export function RecordingOverlayNoteComposer({
  lang, anchor, draft, saving, inputRef, onChange, onClose, onSave,
}: Props) {
  const it = lang === 'it';
  const timestamp = `${Math.floor(anchor / 60)}:${String(Math.floor(anchor % 60)).padStart(2, '0')}`;
  return (
    <section id="overlay-note-composer" className="mt-2 rounded-xl border border-amber-200/20 bg-amber-100/[0.07] p-2"
      data-note-composer="true" aria-label={it ? 'Nota del meeting' : 'Meeting note'}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] font-semibold tabular-nums text-amber-100/85"
          title={it ? 'Momento della registrazione' : 'Recording timestamp'}>
          {timestamp}
        </span>
        <button type="button" onClick={onClose} disabled={saving}
          className="inline-flex min-h-8 items-center gap-1 rounded px-2 text-[11px] text-white/70 hover:bg-white/10 hover:text-white disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-amber-200"
          aria-label="Close note editor" data-note-close="true">
          <X className="h-3 w-3" aria-hidden="true" />
          {it ? 'Chiudi' : 'Close'}
        </button>
      </div>
      <textarea
        ref={inputRef}
        value={draft}
        maxLength={4000}
        rows={2}
        placeholder={it ? 'Scrivi una nota su questo momento…' : 'Add a note about this moment…'}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
          } else if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            onSave();
          }
        }}
        className="w-full select-text resize-none rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 text-[12px] leading-relaxed text-white/90 outline-none placeholder:text-white/40 focus:border-amber-200/50"
        aria-label={it ? 'Testo della nota' : 'Note text'}
      />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[10px] text-white/60">
          {it ? 'Invio: salva · Maiusc+Invio: nuova riga' : 'Enter: save · Shift+Enter: new line'}
        </span>
        <div className="flex gap-1.5">
          <button type="button" onClick={onClose} disabled={saving}
            className="min-h-8 rounded-md px-2 text-[11px] text-white/75 hover:bg-white/10 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-amber-200">
            {it ? 'Chiudi' : 'Close'}
          </button>
          <button type="button" onClick={onSave} disabled={!draft.trim() || saving}
            className="min-h-8 rounded-md bg-amber-200/20 px-2.5 text-[11px] font-semibold text-amber-100 hover:bg-amber-200/30 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-amber-200"
            data-note-save="true">
            {saving ? (it ? 'Salvataggio…' : 'Saving…') : (it ? 'Salva nota' : 'Save note')}
          </button>
        </div>
      </div>
      {draft.length >= 3600 && (
        <div className="mt-1 text-right text-[10px] text-white/60">{draft.length}/4000</div>
      )}
    </section>
  );
}
