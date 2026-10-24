import { useEffect, useRef, useState } from 'react';
import { ApiClient, DiarizationBenchmarkEngine, DiarizationBenchmarkResult, DiarizationTimelineWindow, TranscriptionJob } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { Button } from '../ui/Button';

const ENGINE_OPTIONS: Array<{ key: DiarizationBenchmarkEngine; title: string }> = [
  { key: 'community-1', title: 'FluidAudio Community-1' },
  { key: 'nemotron3-fast128', title: 'Nemotron 3 · fast128' },
  { key: 'nemotron3-compact', title: 'Nemotron 3 · c128-split-w8a8' },
];
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const BAR_COLORS = ['bg-accent', 'bg-warning', 'bg-success', 'bg-info', 'bg-text-secondary'];

type Scope = 'sample' | 'range' | 'full';

function timeLabel(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const h = Math.floor(value / 3600);
  const m = Math.floor(value / 60) % 60;
  const s = value % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function parseTime(value: string): number | null {
  const parts = value.trim().split(':');
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const digits = parts.map(Number);
  if (digits.slice(1).some((part) => part >= 60)) return null;
  return digits.reduce((acc, digit) => acc * 60 + digit, 0);
}

function speakerColor(speaker: string): number {
  let hash = 0;
  for (const char of speaker) hash = ((hash * 31) + char.charCodeAt(0)) >>> 0;
  return hash % BAR_COLORS.length;
}

interface Props {
  recordingId: string;
  durationSeconds?: number;
  readOnly?: boolean;
}

export function DiarizationBenchmarkPanel({ recordingId, durationSeconds, readOnly = false }: Props) {
  const { lang } = useTranslation();
  const it = lang === 'it';
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<DiarizationBenchmarkEngine[]>(
    ENGINE_OPTIONS.map((option) => option.key),
  );
  const [scope, setScope] = useState<Scope>('sample');
  const [rangeStart, setRangeStart] = useState('15:00');
  const [rangeEnd, setRangeEnd] = useState('25:00');
  const [windowStart, setWindowStart] = useState(0);
  const [windowMinutes, setWindowMinutes] = useState(5);
  const [timeline, setTimeline] = useState<DiarizationTimelineWindow | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState('');
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [playbackTime, setPlaybackTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let alive = true;
    setJob(null);
    setTimeline(null);
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
  const rangeFrom = result?.range_start_seconds ?? 0;
  const rangeTo = result?.range_end_seconds ?? ((result?.scope === 'sample' ? result?.preview_seconds : result?.audio_seconds) || 300);
  const viewedSeconds = Math.max(1, Math.min(windowMinutes * 60, rangeTo - rangeFrom));
  const maxWindowStart = Math.max(rangeFrom, rangeTo - viewedSeconds);
  const viewedStart = Math.max(rangeFrom, Math.min(maxWindowStart, windowStart));
  const viewedEnd = Math.min(rangeTo, viewedStart + viewedSeconds);
  const parsedStart = parseTime(rangeStart);
  const parsedEnd = parseTime(rangeEnd);
  const rangeValid = parsedStart !== null && parsedEnd !== null && parsedStart >= 0 && parsedEnd > parsedStart
    && (!durationSeconds || parsedEnd <= durationSeconds + 0.01);
  const detail = job?.progress_detail as { engine?: string; index?: number; total?: number } | null;

  useEffect(() => {
    if (job?.status === 'completed' && result) {
      setWindowStart(result.range_start_seconds ?? 0);
      setTimeline(null);
    }
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!job || job.status !== 'completed' || !result || viewedEnd <= viewedStart) return;
    let alive = true;
    setTimeline(null);
    setTimelineLoading(true);
    setTimelineError('');
    ApiClient.getDiarizationBenchmarkTimeline(recordingId, job.id, viewedStart, viewedEnd)
      .then((value) => { if (alive) setTimeline(value); })
      .catch((exc) => { if (alive) { setTimeline(null); setTimelineError(String(exc)); } })
      .finally(() => { if (alive) setTimelineLoading(false); });
    return () => { alive = false; };
  }, [recordingId, job?.id, job?.status, viewedStart, viewedEnd]);

  const start = async () => {
    if (selected.length < 2 || busy || readOnly || (scope === 'range' && !rangeValid)) return;
    setError('');
    setSubmitting(true);
    setPlaybackTime(0);
    try {
      setJob(await ApiClient.createDiarizationBenchmark(recordingId, {
        engines: ENGINE_OPTIONS.map((option) => option.key).filter((key) => selected.includes(key)),
        scope,
        ...(scope === 'range' ? { start_seconds: parsedStart!, end_seconds: parsedEnd! } : {}),
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
              {it ? 'Primi 5 minuti · prova rapida' : 'First 5 minutes · quick test'}
            </label>
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input type="radio" checked={scope === 'range'} onChange={() => {
                if (durationSeconds && durationSeconds < 1500) {
                  setRangeStart('0:00');
                  setRangeEnd(timeLabel(Math.min(300, Math.floor(durationSeconds))));
                }
                setScope('range');
              }} />
              {it ? 'Intervallo personalizzato' : 'Custom time range'}
            </label>
            {scope === 'range' && (
              <div className="grid grid-cols-1 gap-3 rounded-lg border border-border-subtle p-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-xs text-text-secondary">
                  {it ? 'Da (mm:ss o hh:mm:ss)' : 'From (mm:ss or hh:mm:ss)'}
                  <input type="text" value={rangeStart} onChange={(event) => setRangeStart(event.target.value)}
                    aria-label={it ? 'Inizio intervallo' : 'Range start'}
                    className="rounded-md border border-border-subtle bg-bg-elevated px-3 py-2 text-text-primary" />
                </label>
                <label className="flex flex-col gap-1 text-xs text-text-secondary">
                  {it ? 'A (mm:ss o hh:mm:ss)' : 'To (mm:ss or hh:mm:ss)'}
                  <input type="text" value={rangeEnd} onChange={(event) => setRangeEnd(event.target.value)}
                    aria-label={it ? 'Fine intervallo' : 'Range end'}
                    className="rounded-md border border-border-subtle bg-bg-elevated px-3 py-2 text-text-primary" />
                </label>
                {!rangeValid && <p role="alert" className="text-xs text-warning sm:col-span-2">
                  {it ? 'Inserisci un intervallo valido entro la durata del meeting.' : 'Enter a valid range within the meeting duration.'}
                </p>}
                {durationSeconds ? <p className="text-xs text-text-muted sm:col-span-2">
                  {it ? 'Durata meeting: ' : 'Meeting duration: '}{timeLabel(durationSeconds)}
                </p> : null}
              </div>
            )}
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
            <Button size="sm" onClick={() => void start()} isLoading={submitting} disabled={busy || selected.length < 2 || (scope === 'range' && !rangeValid)}>
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
            {result.scope === 'sample' ? (it ? 'campione iniziale' : 'opening sample')
              : result.scope === 'range' ? (it ? 'intervallo selezionato' : 'selected range')
              : (it ? 'meeting completo' : 'full meeting')}
            {' · '}{timeLabel(rangeFrom)}–{timeLabel(rangeTo)}
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
                {it ? 'Timeline speaker navigabile' : 'Navigable speaker timeline'}
                {' · '}{timeLabel(viewedStart)}–{timeLabel(viewedEnd)}
              </p>
              <audio ref={audioRef} controls preload="metadata"
                onLoadedMetadata={(event) => {
                  if (rangeFrom > 0 && event.currentTarget.currentTime === 0) event.currentTarget.currentTime = rangeFrom;
                }}
                onTimeUpdate={(event) => {
                  const time = event.currentTarget.currentTime;
                  setPlaybackTime(time);
                  if (time >= rangeFrom && time < rangeTo && (time < viewedStart || time >= viewedEnd)) {
                    setWindowStart(Math.min(maxWindowStart, rangeFrom +
                      Math.floor((time - rangeFrom) / (windowMinutes * 60)) * windowMinutes * 60));
                  }
                }}
                src={`/v1/recordings/${encodeURIComponent(recordingId)}/tracks/${encodeURIComponent(result.track_id)}/audio`}
                aria-label={it ? 'Ascolta traccia confrontata' : 'Play compared track'} className="h-9 w-full" />
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" variant="secondary" disabled={viewedStart <= rangeFrom}
                  onClick={() => setWindowStart(Math.max(rangeFrom, viewedStart - viewedSeconds))}>
                  {it ? 'Precedente' : 'Previous'}
                </Button>
                <label className="flex items-center gap-2 text-xs text-text-secondary">
                  {it ? 'Zoom' : 'Zoom'}
                  <select value={windowMinutes} onChange={(event) => setWindowMinutes(Number(event.target.value))}
                    aria-label={it ? 'Ampiezza della finestra temporale' : 'Timeline window duration'}
                    className="rounded-md border border-border-subtle bg-bg-elevated px-2 py-1 text-text-primary">
                    {[1, 5, 10, 30].map((minutes) => <option key={minutes} value={minutes}>{minutes} min</option>)}
                  </select>
                </label>
                <Button size="sm" variant="secondary" disabled={viewedEnd >= rangeTo}
                  onClick={() => setWindowStart(Math.min(maxWindowStart, viewedStart + viewedSeconds))}>
                  {it ? 'Successiva' : 'Next'}
                </Button>
              </div>
              <label className="flex flex-col gap-1 text-xs text-text-secondary">
                {it ? 'Sposta la finestra nel meeting' : 'Navigate the meeting'}
                <input type="range" min={rangeFrom} max={maxWindowStart} step="1" value={viewedStart}
                  onChange={(event) => setWindowStart(Number(event.target.value))}
                  aria-label={it ? 'Posizione della timeline' : 'Timeline position'}
                  disabled={maxWindowStart <= rangeFrom} />
              </label>
              {timelineLoading && <p role="status" className="text-xs text-text-muted">{it ? 'Caricamento segmenti…' : 'Loading segments…'}</p>}
              {timelineError && <p role="alert" className="text-xs text-warning">{timelineError}</p>}
              {timeline?.runs.filter((run) => run.status === 'completed').map((run) => {
                const speakers = [...new Set(run.segments.map((segment) => segment.speaker))];
                return (
                  <div key={run.key} className="space-y-1">
                    <p className="text-[11px] font-medium text-text-secondary">
                      {ENGINE_OPTIONS.find((item) => item.key === run.key)?.title}
                    </p>
                    <div className="relative h-12 overflow-hidden rounded-md border border-border-subtle bg-bg-surface"
                      aria-label={it ? 'Speaker nella finestra temporale' : 'Speakers in time window'}>
                      {run.segments.map((segment, index) => {
                        const start = Math.max(segment.start, viewedStart);
                        const end = Math.min(segment.end, viewedEnd);
                        const color = speakerColor(segment.speaker);
                        return (
                          <span key={index}
                            title={`${segment.speaker}: ${timeLabel(segment.start)}–${timeLabel(segment.end)}`}
                            className={`absolute h-2.5 rounded-sm ${BAR_COLORS[color]}`}
                            style={{
                              left: `${(start - viewedStart) / viewedSeconds * 100}%`,
                              width: `${Math.max(0.15, (end - start) / viewedSeconds * 100)}%`,
                              top: `${4 + color % 3 * 13}px`,
                            }}
                          />
                        );
                      })}
                      {playbackTime >= viewedStart && playbackTime <= viewedEnd && (
                        <span className="absolute bottom-0 top-0 w-px bg-text-primary"
                          style={{ left: `${(playbackTime - viewedStart) / viewedSeconds * 100}%` }} />
                      )}
                    </div>
                    <p className="text-[10px] text-text-muted">
                      {speakers.length ? speakers.map((speaker) => `● ${speaker}`).join(' · ')
                        : (it ? 'Nessun intervento in questa finestra' : 'No detected speech in this window')}
                      {run.partial && (it ? ' · Confronto precedente: disponibili solo i primi 5 minuti' : ' · Older run: only first 5 minutes saved')}
                    </p>
                  </div>
                );
              })}
              <p className="text-[11px] text-text-muted">
                {it
                  ? 'I colori indicano cluster indipendenti e non identità corrispondenti tra motori. Il numero di speaker non misura la precisione.'
                  : 'Colors are independent speaker clusters, not aligned identities across engines. Speaker count is not an accuracy metric.'}
              </p>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-xs text-danger">{error}</p>}
    </section>
  );
}
