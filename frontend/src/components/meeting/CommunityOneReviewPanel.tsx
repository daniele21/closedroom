import { useEffect, useState } from 'react';
import { ApiClient, Transcription } from '../../api/apiClient';
import { Button } from '../ui/Button';

type Preview = Awaited<ReturnType<typeof ApiClient.previewCommunityOneReview>>;
type Job = Awaited<ReturnType<typeof ApiClient.createCommunityOneReview>>;
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);

interface Props {
  transcriptionId: string;
  onUpdated: (transcription: Transcription) => void;
  lang: string;
}

function position(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

export function CommunityOneReviewPanel({ transcriptionId, onUpdated, lang }: Props) {
  const it = lang === 'it';
  const [engine] = useState('fluidaudio-community-1');
  const [expanded, setExpanded] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [undoRevision, setUndoRevision] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setJob(null);
    setPreview(null);
    setUndoRevision(null);
    setError('');
    ApiClient.listCommunityOneReviews(transcriptionId).then((value) => {
      if (!live) return;
      setUndoRevision(value.undo?.revision_id || null);
      setJob(value.items[0] || null);
    }).catch((reason) => {
      if (live) setError(String(reason));
    });
    return () => { live = false; };
  }, [transcriptionId]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    let live = true;
    const check = () => {
      ApiClient.getJob(job.id).then((value) => {
        if (live) setJob((current) => current?.id === value.id ? value : current);
      }).catch((reason) => {
        if (live) setError(String(reason));
      });
    };
    const timer = window.setInterval(check, 1200);
    return () => { live = false; window.clearInterval(timer); };
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!job || job.status !== 'completed' || undoRevision) return;
    let live = true;
    ApiClient.previewCommunityOneReview(transcriptionId, job.id).then((value) => {
      if (live) setPreview(value);
    }).catch((reason) => {
      if (live) { setPreview(null); setError(String(reason)); }
    });
    return () => { live = false; };
  }, [transcriptionId, job?.id, job?.status, undoRevision]);

  const busy = pending || Boolean(job && !TERMINAL.has(job.status));
  const canStart = !busy && !undoRevision;
  const start = async () => {
    if (busy) return;
    setPending(true);
    setError('');
    setPreview(null);
    try {
      const created = await ApiClient.createCommunityOneReview(transcriptionId);
      setJob(created);
      setExpanded(true);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setPending(false);
    }
  };

  const apply = async () => {
    if (!job || !preview || busy) return;
    setPending(true);
    setError('');
    try {
      const result = await ApiClient.applyCommunityOneReview(transcriptionId, job.id);
      setUndoRevision(result.revision_id);
      setPreview(null);
      onUpdated(result.transcription);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setPending(false);
    }
  };

  const undo = async () => {
    if (!undoRevision || busy) return;
    setPending(true);
    setError('');
    try {
      const result = await ApiClient.undoCommunityOneReview(transcriptionId, undoRevision);
      setUndoRevision(null);
      setJob(null);
      setPreview(null);
      onUpdated(result.transcription);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setPending(false);
    }
  };

  const cancel = async () => {
    if (!job || TERMINAL.has(job.status)) return;
    try {
      setJob(await ApiClient.cancelJob(job.id));
    } catch (reason) {
      setError(String(reason));
    }
  };

  return (
    <section className="mt-4 rounded-xl border border-border-subtle bg-bg-glass p-4" data-community-review="true">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            {it ? 'Applica speaker alla trascrizione' : 'Apply speakers to transcript'}
          </h3>
          <p className="mt-1 text-xs text-text-secondary">
            {it
              ? 'Calcola prima un’anteprima con Community-1. Testo e timestamp restano invariati.'
              : 'Preview Community-1 first. Transcript text and timestamps will not change.'}
          </p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => setExpanded((open) => !open)} aria-expanded={expanded}>
          {expanded ? (it ? 'Chiudi' : 'Close') : (it ? 'Scegli motore' : 'Choose engine')}
        </Button>
      </div>

      {undoRevision && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle p-3">
          <span className="text-xs text-text-secondary" role="status">
            {it ? 'Attribuzioni applicate. Puoi ripristinare gli speaker precedenti.' : 'Speakers applied. You can restore the previous assignments.'}
          </span>
          <Button size="sm" variant="secondary" onClick={() => void undo()} disabled={busy} isLoading={pending}>
            {it ? 'Ripristina speaker precedenti' : 'Restore previous speakers'}
          </Button>
        </div>
      )}

      {expanded && (
        <div className="mt-4 space-y-3 rounded-lg border border-border-subtle bg-bg-elevated p-3">
          <label className="flex flex-col gap-1 text-xs text-text-secondary">
            <span>{it ? 'Motore per questo meeting' : 'Engine for this meeting'}</span>
            <select className="rounded-md border border-border-subtle bg-bg-surface px-2 py-2 text-text-primary"
              value={engine} disabled={busy} aria-label={it ? 'Motore per la diarizzazione' : 'Diarization engine'}>
              <option value="fluidaudio-community-1">FluidAudio Community-1 · {it ? 'Locale' : 'Local'}</option>
            </select>
          </label>
          <p className="text-[11px] text-text-muted">
            {it
              ? 'Il motore analizza l’intero meeting solo sul Mac. Il calcolo dell’anteprima non modifica la trascrizione né le impostazioni.'
              : 'The engine analyzes the full meeting on this Mac only. Preview does not modify the transcript or global settings.'}
          </p>
          <Button size="sm" onClick={() => void start()} disabled={!canStart} isLoading={pending}>
            {it ? 'Calcola anteprima' : 'Calculate preview'}
          </Button>
          {job && !TERMINAL.has(job.status) && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary" role="status">
              <span>{it ? 'Elaborazione' : 'Processing'}: {job.current_step || job.status} · {job.progress}%</span>
              <Button size="sm" variant="ghost" onClick={() => void cancel()}>
                {it ? 'Annulla' : 'Cancel'}
              </Button>
            </div>
          )}
          {job?.status === 'failed' && (
            <p role="alert" className="text-xs text-danger">{it ? 'Anteprima non riuscita' : 'Preview failed'}: {job.error}</p>
          )}
          {job?.status === 'cancelled' && (
            <p role="status" className="text-xs text-text-muted">{it ? 'Anteprima annullata' : 'Preview cancelled'}</p>
          )}
          {preview && !undoRevision && (
            <div className="space-y-3" data-community-review-preview="true">
              <div className="text-xs text-text-secondary" role="status">
                {it ? 'Anteprima pronta' : 'Preview ready'} · {preview.cluster_count} cluster · {preview.assigned_segments} {it ? 'segmenti attribuiti' : 'assigned segments'}
              </div>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {preview.examples.map((example, index) => (
                  <div key={index} className="rounded-lg border border-border-subtle bg-bg-surface p-2 text-xs">
                    <p className="text-text-muted">{position(example.start)}–{position(example.end)}</p>
                    <p className="mt-1 text-text-primary">{example.text}</p>
                    <p className="mt-1 text-text-secondary">
                      {example.before} → <strong className="text-text-primary">{example.after}</strong>
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-text-muted">
                {it
                  ? 'Conferma per sostituire le attribuzioni degli speaker in tutta la trascrizione. I nomi precedenti potranno essere ripristinati.'
                  : 'Confirm to replace speaker assignments throughout this transcript. Previous assignments can be restored.'}
              </p>
              <Button size="sm" onClick={() => void apply()} disabled={busy} isLoading={pending}>
                {it ? 'Conferma e applica alla trascrizione' : 'Confirm and apply to transcript'}
              </Button>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-xs text-danger">{error}</p>}
    </section>
  );
}
