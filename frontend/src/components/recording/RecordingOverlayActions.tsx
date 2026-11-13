import { Camera, Check, Loader2, PencilLine, Square } from 'lucide-react';

// Pure recording controls: the overlay page remains the sole owner of capture,
// persistence, admission/stop lifecycle and every version-aware Undo.
interface RecordingOverlayActionsProps {
  lang: string;
  noteComposerOpen: boolean;
  noteCount: number;
  screenshotCount: number;
  isRecording: boolean;
  isStopping: boolean;
  isAnchoringNote: boolean;
  isSavingNote: boolean;
  isUndoingNote: boolean;
  isCapturingScreenshot: boolean;
  isUndoingScreenshot: boolean;
  lastSavedNoteId: string | null;
  lastSavedScreenshotId: string | null;
  captureBackend: 'native' | 'browser';
  selectedDisplayId: number | null;
  screenshotShortcut: string;
  screenshotLabel: string;
  onOpenNote: () => void;
  onUndoNote: () => void;
  onCaptureScreenshot: () => void;
  onUndoScreenshot: () => void;
  onStop: () => void;
}

export function RecordingOverlayActions({
  lang,
  noteComposerOpen,
  noteCount,
  screenshotCount,
  isRecording,
  isStopping,
  isAnchoringNote,
  isSavingNote,
  isUndoingNote,
  isCapturingScreenshot,
  isUndoingScreenshot,
  lastSavedNoteId,
  lastSavedScreenshotId,
  captureBackend,
  selectedDisplayId,
  screenshotShortcut,
  screenshotLabel,
  onOpenNote,
  onUndoNote,
  onCaptureScreenshot,
  onUndoScreenshot,
  onStop,
}: RecordingOverlayActionsProps) {
  return (
    <>
        <div className={`flex h-9 shrink-0 overflow-hidden rounded-lg border ${
          lastSavedNoteId !== null
            ? 'border-amber-200/30 bg-amber-200/10'
            : 'border-white/10 bg-white/[0.08]'
        }`}>
          <button
            type="button"
            onClick={onOpenNote}
            disabled={isStopping || isAnchoringNote || isSavingNote || isUndoingNote || !isRecording}
            className="flex h-full items-center gap-1.5 px-2.5 text-[10px] font-semibold text-white/90 transition hover:bg-white/[0.05] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-35"
            aria-label={noteComposerOpen ? 'Close note' : 'Add note'}
            aria-expanded={noteComposerOpen}
            title={noteComposerOpen ? 'Close note editor' : 'Add note about this moment'}
            data-note-action="true"
          >
            {isAnchoringNote || isSavingNote ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : lastSavedNoteId !== null ? (
              <Check className="h-3.5 w-3.5 text-amber-100" aria-hidden="true" />
            ) : (
              <PencilLine className="h-3.5 w-3.5 text-amber-100/85" aria-hidden="true" />
            )}
            <span>{lastSavedNoteId !== null ? (lang === 'it' ? 'Salvata' : 'Saved') : `${lang === 'it' ? 'Note' : 'Notes'} ${noteCount}`}</span>
          </button>
          {lastSavedNoteId && (
            <button
              type="button"
              onClick={onUndoNote}
              disabled={isUndoingNote || isStopping}
              className="flex h-full items-center border-l border-amber-100/15 px-2 text-[9px] font-semibold text-amber-100/75 transition hover:bg-amber-100/10 disabled:opacity-35"
              data-note-undo="true"
            >
              {isUndoingNote ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : 'Undo'}
            </button>
          )}
        </div>

        <div className={`flex h-9 shrink-0 overflow-hidden rounded-lg border ${
          lastSavedScreenshotId !== null
            ? 'border-emerald-300/30 bg-emerald-300/12'
            : 'border-white/10 bg-white/[0.08]'
        }`}>
          <button
            type="button"
            onClick={onCaptureScreenshot}
            disabled={isStopping || isCapturingScreenshot || isUndoingScreenshot || !isRecording || captureBackend !== 'native' || selectedDisplayId === null}
            className={`flex h-full items-center gap-1.5 px-2.5 text-[10px] font-semibold transition active:scale-[0.97] ${
              lastSavedScreenshotId !== null
                ? 'text-emerald-100'
                : 'text-white/90 hover:bg-white/[0.05]'
            } disabled:cursor-not-allowed disabled:opacity-35`}
            title={selectedDisplayId === null ? 'Choose a screen first' : screenshotShortcut}
            aria-label={screenshotLabel}
            data-screenshot-action="true"
          >
            {isCapturingScreenshot ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : lastSavedScreenshotId !== null ? (
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Camera className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            <span>{lastSavedScreenshotId !== null ? (lang === 'it' ? 'Salvato' : 'Saved') : `${lang === 'it' ? 'Scatti' : 'Shots'} ${screenshotCount}`}</span>
          </button>

          {lastSavedScreenshotId && (
            <button
              type="button"
              onClick={onUndoScreenshot}
              disabled={isUndoingScreenshot || isStopping}
              className="flex h-full items-center border-l border-emerald-200/20 px-2 text-[9px] font-semibold text-emerald-100/75 transition hover:bg-emerald-200/10 hover:text-emerald-50 disabled:cursor-not-allowed disabled:opacity-35"
              aria-label="Undo last screenshot"
              title="Undo last screenshot"
              data-screenshot-undo="true"
            >
              {isUndoingScreenshot ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : 'Undo'}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={onStop}
          disabled={isStopping || !isRecording}
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition active:scale-90 ${
            isStopping
              ? 'bg-amber-500/70 text-white'
              : !isRecording
              ? 'bg-white/10 text-white/30'
              : 'bg-red-500 text-white shadow-[0_0_18px_rgba(239,68,68,0.18)] hover:bg-red-400'
          } disabled:cursor-not-allowed`}
          title="Stop recording"
          aria-label="Stop recording"
        >
          {isStopping ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
          )}
        </button>
    </>
  );
}
