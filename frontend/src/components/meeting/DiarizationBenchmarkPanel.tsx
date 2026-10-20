import { useEffect, useRef, useState } from 'react';
import { ApiClient, DiarizationBenchmarkEngine, DiarizationBenchmarkResult, TranscriptionJob } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { Button } from '../ui/Button';

const ENGINE_OPTIONS: Array<{ key: DiarizationBenchmarkEngine; title: string }> = [
  { key: 'community-1', title: 'FluidAudio Community-1' },
  { key: 'nemotron3-fast128', title: 'Nemotron 3 · fast128' },
  { key: 'nemotron3-compact', title: 'Nemotron 3 · c128-split-w8a8' },
];
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const BAR_COLORS = ['bg-accent', 'bg-warning', 'bg-success', 'bg-info', 'bg-text-secondary'];

type Scope = 'sample' | 'full';

interface Props {
  recordingId: string;
  readOnly?: boolean;
}

export function DiarizationBenchmarkPanel({ recordingId, readOnly = false }: Props) {
  const { lang } = useTranslation();
  const it = lang === 'it';
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<DiarizationBenchmarkEngine[]>(
    ENGINE_OPTIONS.map((option) => option.key),
  );
  const [scope, setScope] = useState<Scope>('sample');
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [playbackTime, setPlaybackTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let alive = true;
    setJob(null);
    setError('');
    ApiClient.listDiarizationBenchmarks(recordingId).then(({ items }) => {
      if (!alive || !items.length) return;
      setJob(items[0]);
    }).catch(() => {
      if (alive) setError(it ? 'Impossibile recuperare i confronti precedenti.' : 'Could not load previous comparisons.');
    });
    return () => { alive = false; };
  }, [recordingId, it]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    let alive = true;
    const refresh = () => {
      ApiClient.getJob(job.id).then((updated) => {
        if (alive) setJob((current) => current?.id === updated.id ? updated : current);
      }).catch(() => {
        if (alive) setError(it ? 'Impossibile aggiornare lo stato. Riprova aprendo il meeting.' : 'Could not refresh progress. Reopen the meeting to retry.');
      });
    };
    const timer = window.setInterval(refresh, 1200);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.status, it]);

  const busy = submitting || Boolean(job && !TERMINAL.has(job.status));
  const result = (job?.result || null) as DiarizationBenchmarkResult | null;
  const runs = result?.runs || [];
  const previewSeconds = Math.max(1, result?.preview_seconds || 300);
  const detail = job?.progress_detail as { engine?: string; index?: number; total?: number } | null;

  const start = async () => {
    if (selected.length < 2 || busy || readOnly) return;
    setError('');
    setSubmitting(true);
    setPlaybackTime(0);
    try {
      setJob(await ApiClient.createDiarizationBenchmark(recordingId, {
        engines: ENGINE_OPTIONS.map((option) => option.key).filter((key) => selected.includes(key)),
        scope,
      }));
      setExpanded(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!job || TERMINAL.has(job.status)) return;
    try {
      setJob(await ApiClient.cancelJob(job.id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const toggleEngine = (key: DiarizationBenchmarkEngine, checked: boolean) => {
    setSelected((previous) => checked ? [...previous, key] : previous.filter((item) => item !== key));
  };

  return (
    <section className="mt-4 rounded-xl border border-border-subtle bg-bg-glass p-4" data-diarization-benchmark="true">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            {it ? 'Confronta motori di diarizzazione' : 'Compare diarization engines'}
          </h3>
          <p className="mt-1 text-xs text-text-secondary">
            {it
              ? 'Prova più motori sullo stesso audio del meeting. Trascrizione e impostazioni restano invariate.'
              : 'Run multiple engines on the same meeting audio. Your transcript and settings stay unchanged.'}
          </p>
        </div>
        {!readOnly && (
          <Button size="sm" variant="secondary" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded}>
            {expanded ? (it ? 'Nascondi opzioni' : 'Hide options') : (it ? 'Confronta motori' : 'Compare engines')}
          </Button>
        )}
      </div>

      {expanded && !readOnly && (
        <div className="mt-4 space-y-4 rounded-lg border border-border-subtle bg-bg-elevated p-3">
          <fieldset disabled={busy} className="space-y-2">
            <legend className="mb-2 text-xs font-semibold text-text-primary">
              {it ? 'Motori (scegline almeno due)' : 'Engines (select at least two)'}
            </legend>
            {ENGINE_OPTIONS.map((option) => (
              <label key={option.key} className="flex cursor-pointer items-center gap-2 text-xs text-text-secondary">
                <input type="checkbox" checked={selected.includes(option.key)}
                  onChange={(event) => toggleEngine(option.key, event.target.checked)}
                  className="accent-[var(--color-accent)]" />
                {option.title}
              </label>
            ))}
          </fieldset>
          <fieldset disabled={busy} className="space-y-2">
            <legend className="mb-2 text-xs font-semibold text-text-primary">
              {it ? 'Audio da analizzare' : 'Audio to compare'}
            </legend>
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input type="radio" checked={scope === 'sample'} onChange={() => setScope('sample')} />
              {it ? 'Primi 5 minuti · prova rapida (WAV/PCM)' : 'First 5 minutes · quick test (WAV/PCM)'}
            </label>
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input type="radio" checked={scope === 'full'} onChange={() => setScope('full')} />
              {it ? 'Meeting completo' : 'Full meeting'}
            </label>
          </fieldset>
          <p className="text-[11px] text-text-muted">
            {it
              ? 'Su meeting a due tracce viene confrontata la traccia del computer; il microfono locale resta attribuito a te. Il primo avvio di Nemotron può scaricare i pesi pubblici. Nessun audio viene caricato online.'
              : 'For dual-track meetings, the system track is compared; your microphone remains a known speaker. The first Nemotron run may download public weights. No audio is uploaded.'}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void start()} isLoading={submitting} disabled={busy || selected.length < 2}>
              {it ? 'Avvia confronto' : 'Start comparison'}
            </Button>
            {selected.length < 2 && (
              <span className="text-xs text-warning" role="status">
                {it ? 'Seleziona almeno due motori.' : 'Select at least two engines.'}
              </span>
            )}
          </div>
        </div>
      )}

      {job && (
        <div className="mt-4 space-y-3" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary">
            <span>
              {it ? 'Ultimo confronto' : 'Latest comparison'}: <strong className="text-text-primary">{job.status}</strong>
              {busy && detail?.index ? ` · ${detail.index}/${detail.total || '?'} · ${detail.engine || ''}` : ''}
            </span>
            {busy && !readOnly && (
              <Button size="sm" variant="ghost" onClick={() => void cancel()} disabled={job.status === 'cancelling'}>
                {it ? 'Annulla' : 'Cancel'}
              </Button>
            )}
          </div>
          {busy && (
            <div role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}
              aria-label={it ? 'Avanzamento confronto motori' : 'Engine comparison progress'}
              className="h-1.5 overflow-hidden rounded-full bg-bg-hover">
              <div className="h-full bg-accent transition-all" style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} />
            </div>
          )}
          {job.status === 'failed' && <p role="alert" className="text-xs text-danger">{it ? 'Confronto non riuscito: ' : 'Comparison failed: '}{job.error || ''}</p>}
          {job.status === 'cancelled' && <p className="text-xs text-text-muted">{it ? 'Confronto annullato.' : 'Comparison cancelled.'}</p>}
        </div>
      )}

      {result && runs.length > 0 && (
        <div className="mt-4 space-y-3">
          <p className="text-[11px] text-text-muted">
            {it ? 'Confronto completato · ' : 'Comparison finished · '}
            {result.scope === 'sample' ? (it ? 'campione iniziale' : 'opening sample') : (it ? 'meeting completo' : 'full meeting')}
            {' · '}{it ? 'traccia' : 'track'}: {result.track_id}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-text-muted">
                <tr>
                  <th scope="col" className="pb-2 pr-3">{it ? 'Motore' : 'Engine'}</th>
                  <th scope="col" className="pb-2 pr-3">{it ? 'Tempo' : 'Time'}</th>
                  <th scope="col" className="pb-2 pr-3">Speaker</th>
                  <th scope="col" className="pb-2">{it ? 'Velocità' : 'Speed'}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.key} className="border-t border-border-subtle text-text-secondary">
                    <th scope="row" className="py-2 pr-3 font-medium text-text-primary">
                      {ENGINE_OPTIONS.find((item) => item.key === run.key)?.title || run.key}
                      {run.status === 'failed' && <span className="block text-danger">Failed ({run.error_type || 'error'})</span>}
                    </th>
                    <td className="py-2 pr-3">{run.elapsed_seconds == null ? '—' : `${run.elapsed_seconds}s`}</td>
                    <td className="py-2 pr-3">{run.clusters ?? '—'}</td>
                    <td className="py-2">{run.speed_vs_realtime == null ? '—' : `${run.speed_vs_realtime}×`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {runs.some((run) => run.status === 'completed') && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-text-primary">
                {it ? 'Confronto visivo dei parlanti · primi 5 minuti' : 'Speaker timeline comparison · first 5 minutes'}
              </p>
              <audio ref={audioRef} controls preload="none" onTimeUpdate={(event) => setPlaybackTime(event.currentTarget.currentTime)}
                src={`/v1/recordings/${encodeURIComponent(recordingId)}/tracks/${encodeURIComponent(result.track_id)}/audio`}
                aria-label={it ? 'Ascolta traccia confrontata' : 'Play compared track'} className="h-9 w-full" />
              {runs.filter((run) => run.status === 'completed').map((run) => {
                const speakers = [...new Set((run.preview || []).map((segment) => segment.speaker))];
                return (
                  <div key={run.key} className="space-y-1">
                    <p className="text-[11px] font-medium text-text-secondary">
                      {ENGINE_OPTIONS.find((item) => item.key === run.key)?.title}
                    </p>
                    <div className="relative h-12 overflow-hidden rounded-md border border-border-subtle bg-bg-surface"
                      aria-label={it ? 'Segmenti parlanti nel campione' : 'Speaker segments in the sample'}>
                      {(run.preview || []).map((segment, index) => (
                        <span key={index}
                          title={`${segment.speaker}: ${segment.start}s–${segment.end}s`}
                          className={`absolute h-2.5 rounded-sm ${BAR_COLORS[speakers.indexOf(segment.speaker) % BAR_COLORS.length]}`}
                          style={{
                            left: `${Math.min(100, segment.start / previewSeconds * 100)}%`,
                            width: `${Math.max(0.15, (segment.end - segment.start) / previewSeconds * 100)}%`,
                            top: `${4 + (speakers.indexOf(segment.speaker) % 3) * 13}px`,
                          }}
                        />
                      ))}
                      <span className="absolute bottom-0 top-0 w-px bg-text-primary"
                        style={{ left: `${Math.min(100, playbackTime / previewSeconds * 100)}%` }} />
                    </div>
                    <p className="text-[10px] text-text-muted">
                      {speakers.map((speaker) => `● ${speaker}`).join(' · ')}
                      {run.preview_truncated && (it ? ' · Timeline parziale' : ' · Partial timeline')}
                    </p>
                  </div>
                );
              })}
              <p className="text-[11px] text-text-muted">
                {it
                  ? 'Il numero di speaker non misura la precisione. Senza annotazioni umane non è disponibile un DER affidabile. I colori rappresentano cluster indipendenti, non identità corrispondenti fra motori.'
                  : 'Speaker count does not measure accuracy. Reliable DER needs human annotations. Colors indicate independent clusters, not matched identities between engines.'}
              </p>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-xs text-danger">{error}</p>}
    </section>
  );
}
