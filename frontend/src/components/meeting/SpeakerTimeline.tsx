import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, Play, ScanSearch } from 'lucide-react';
import {
  ApiClient, type SpeakerClip, type SpeakerTimelineWindow, type Transcription,
} from '../../api/apiClient';

export interface TimelineSpeakerRow {
  cluster: string;
  group: string;
  name: string;
  status: string;
  sourceOnly: boolean;
  count: number; // transcript-linked text turns, not audio intervals
}

interface Props {
  transcription: Transcription;
  recordingId: string;
  durationSeconds: number;
  rows: TimelineSpeakerRow[];
  showHidden: boolean;
  pendingOnly?: boolean;
  selectedGroup: string | null;
  cursorSeconds: number | null;
  children?: ReactNode;
  onSelect: (cluster: string) => void;
  onPlaySample?: (cluster: string) => void;
  sampleAvailable?: (cluster: string) => boolean;
  onPlayInterval: (clip: SpeakerClip) => void;
  onJumpToTranscript?: (time: number) => void;
  lang: string;
}

const COLORS = ['#63A6FF', '#73D5A1', '#CE9AFF', '#FFBC69', '#FF8698', '#71D6E0', '#E9D568', '#B7B4F5'];
const OVERVIEW_BOOTSTRAP_SECONDS = 300;
const ZOOMS = [0, 60, 300, 600] as const;

function clock(value: number): string {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

function validPositive(value: number | null | undefined): number | null {
  return value != null && Number.isFinite(value) && value > 0 ? value : null;
}

function clipFor(item: SpeakerTimelineWindow['intervals'][number]): SpeakerClip {
  return {
    track_id: item.track_id, start: item.start, end: item.end,
    kind: item.origin === 'diarization' ? 'diarization' : 'transcript',
    overlap: item.overlap,
  };
}

/** One per-person row on one truthful recording clock; voice != audio source. */
export function SpeakerTimeline({
  transcription, recordingId, durationSeconds, rows, showHidden, pendingOnly = false,
  selectedGroup, cursorSeconds, children, onSelect, onPlaySample, sampleAvailable,
  onPlayInterval, onJumpToTranscript, lang,
}: Props) {
  const it = lang === 'it';
  const transcriptionId = transcription.id || transcription.saved_id || '';
  const [recordingDuration, setRecordingDuration] = useState<number | null>(null);
  const [zoom, setZoom] = useState<number>(0);
  const [requestedStart, setRequestedStart] = useState(0);
  const [timeline, setTimeline] = useState<SpeakerTimelineWindow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Canonical Meeting metadata is preferred. Never manufacture a one-second
  // recording, and do not start eager media requests to learn its duration.
  useEffect(() => {
    let live = true;
    setRecordingDuration(null);
    if (recordingId) {
      void ApiClient.getRecording(recordingId).then((recording) => {
        if (!live) return;
        const started = Date.parse(recording.created_at || '');
        const stopped = Date.parse(recording.stopped_at || '');
        const clockDuration = Number.isFinite(started) && Number.isFinite(stopped) && stopped > started
          ? (stopped - started) / 1000 : 0;
        setRecordingDuration(
          validPositive(recording.duration_seconds)
          || validPositive(recording.duration)
          || validPositive(recording.metadata?.duration_seconds)
          || validPositive(clockDuration),
        );
      }).catch(() => {
        // The server's evidence summary may still determine the clock.
      });
    }
    return () => { live = false; };
  }, [recordingId]);

  const asrLastEnd = (transcription.segments || []).reduce((max, segment) =>
    Math.max(max, Number.isFinite(Number(segment.end)) ? Number(segment.end) : 0), 0);
  const possibleDurations = [
    timeline?.duration_seconds, timeline?.max_evidence_end_seconds,
    durationSeconds, recordingDuration, asrLastEnd,
  ].map(validPositive).filter((value): value is number => value !== null);
  const duration = possibleDurations.length ? Math.max(...possibleDurations) : null;
  const maxStart = duration ? Math.max(0, duration - Math.min(zoom || duration, duration)) : 0;
  const windowSize = duration ? Math.min(zoom || duration, duration) : null;
  const viewedStart = Math.min(Math.max(0, requestedStart), maxStart);
  const viewedEnd = viewedStart + (windowSize || 0);

  // Full-meeting view always uses the bounded overview sent by the server;
  // detailed raw intervals are requested only for a selected 1/5/10-minute
  // window, so hundreds of turns never produce unreadable thousands of nodes.
  const queryStart = zoom === 0 ? 0 : viewedStart;
  const queryEnd = zoom === 0
    ? OVERVIEW_BOOTSTRAP_SECONDS
    : queryStart + (windowSize || zoom);
  useEffect(() => {
    if (!transcriptionId) return;
    const abort = new AbortController();
    setTimeline(null);
    setLoading(true);
    setError('');
    void ApiClient.getSpeakerTimeline(transcriptionId, queryStart, queryEnd, abort.signal)
      .then((result) => { if (!abort.signal.aborted) setTimeline(result); })
      .catch((err: Error) => { if (!abort.signal.aborted) setError(err.message || 'Timeline unavailable'); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [transcriptionId, transcription, queryStart, queryEnd]);

  const lanes = useMemo(() => {
    const visible = rows.filter((row) =>
      row.status !== 'merged' && !row.sourceOnly
      && (showHidden || row.status !== 'excluded')
      && (!pendingOnly || row.status !== 'accepted'));
    const source = new Map(rows.map((row) => [row.cluster, row]));
    return visible.map((row, index) => ({
      row, color: COLORS[index % COLORS.length],
      summary: timeline?.overview?.filter((entry) => source.get(entry.cluster)?.group === row.group) || [],
      intervals: (timeline?.intervals || []).filter((item) => source.get(item.cluster)?.group === row.group),
    }));
  }, [rows, showHidden, pendingOnly, timeline]);

  const allIntervals = timeline?.intervals || [];
  const overviewData = timeline?.overview || [];
  const knownBuckets = timeline?.overview_bucket_count || 0;
  const overviewBins = useMemo(() => {
    const bins = new Set<number>();
    for (const entry of overviewData) for (const bin of entry.bins) bins.add(bin);
    return [...bins].sort((a, b) => a - b);
  }, [overviewData]);
  const position = (time: number) =>
    `${Math.max(0, Math.min(100, (time - viewedStart) / (windowSize || 1) * 100))}%`;
  // Intervals can cross the selected zoom window. Clip their *visual* span
  // without changing the canonical timestamps used for local playback.
  const visibleIntervalStyle = (start: number, end: number) => {
    if (!windowSize || !Number.isFinite(start) || !Number.isFinite(end)) return null;
    const visibleStart = Math.max(start, viewedStart);
    const visibleEnd = Math.min(end, viewedEnd);
    if (visibleEnd <= visibleStart) return null;
    const left = (visibleStart - viewedStart) / windowSize * 100;
    const width = (visibleEnd - visibleStart) / windowSize * 100;
    return {
      left: `${left}%`,
      width: `${Math.min(100 - left, Math.max(0.3, width))}%`,
    };
  };

  const jumpToBucket = (bin: number) => {
    if (!duration || !knownBuckets) return;
    const anchor = (bin + 0.5) / knownBuckets * duration;
    const next = Math.min(300, duration);
    setZoom(next);
    setRequestedStart(Math.max(0, Math.min(duration - next, anchor - next / 2)));
  };

  function paintBins(
    bins: number[], color: string, label: string, key: string,
  ) {
    if (!duration || !knownBuckets) return null;
    const sorted = [...new Set(bins)].sort((a, b) => a - b);
    // Merge adjacent occupied buckets into a bounded number of DOM nodes.
    const runs: Array<{ first: number; last: number }> = [];
    for (const bin of sorted) {
      const tail = runs[runs.length - 1];
      if (tail && bin === tail.last + 1) tail.last = bin;
      else runs.push({ first: bin, last: bin });
    }
    return runs.map(({ first, last }) => (
      <button type="button" key={`${key}-${first}`}
        title={`${label} · ${clock(first / knownBuckets * duration)}`}
        aria-label={it
          ? `Esplora ${label} attorno a ${clock(first / knownBuckets * duration)}`
          : `Explore ${label} around ${clock(first / knownBuckets * duration)}`}
        onClick={() => jumpToBucket(first)}
        className="absolute inset-y-1.5 rounded-sm opacity-85 hover:opacity-100 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-border-focus"
        style={{ left: `${first / knownBuckets * 100}%`,
          width: `${(last - first + 1) / knownBuckets * 100}%`,
          backgroundColor: color }} />
    ));
  }

  function paintIntervals(items: SpeakerTimelineWindow['intervals'], color: string, label: string, lane: string) {
    return items.map((item, index) => {
      const style = visibleIntervalStyle(item.start, item.end);
      if (!style) return null;
      return (
      <button key={`${lane}-${item.track_id}-${item.start}-${index}`} type="button"
        disabled={!item.playable}
        data-speaker-interval={lane}
        data-interval-origin={item.origin}
        title={`${label}: ${clock(item.start)}–${clock(item.end)}`}
        aria-label={item.playable
          ? `${it ? 'Ascolta' : 'Play'} ${label}, ${clock(item.start)}–${clock(item.end)}`
          : `${it ? 'Audio non disponibile' : 'Audio unavailable'}: ${label}, ${clock(item.start)}–${clock(item.end)}`}
        onClick={() => onPlayInterval(clipFor(item))}
        className="absolute inset-y-1.5 rounded-sm focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-border-focus disabled:cursor-default disabled:opacity-50"
        style={{ ...style, backgroundColor: color }} />
      );
    });
  }

  const timeTicks = duration && windowSize
    ? [0, 0.25, 0.5, 0.75, 1].map((part) => clock((zoom ? viewedStart : 0) + (zoom ? windowSize : duration) * part))
    : [];
  const hasTranscriptAtCursor = cursorSeconds !== null && (transcription.segments || []).some(
    (segment) => Number(segment.start) <= cursorSeconds && Number(segment.end) >= cursorSeconds,
  );

  return (
    <section data-speaker-review-timeline="true"
      aria-label={it ? 'Voci del meeting' : 'Meeting speakers'}
      className="rounded-xl border border-border-subtle bg-bg-surface px-3 py-4 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">{it ? 'Chi ha parlato' : 'Who spoke'}</h4>
          <p className="mt-0.5 text-xs text-text-muted">
            {duration ? `${it ? 'Meeting' : 'Meeting'} · ${clock(duration)}`
              : (it ? 'Durata del meeting non verificata' : 'Meeting duration unavailable')}
          </p>
        </div>
        <div className="flex items-center gap-1" aria-label={it ? 'Zoom della timeline' : 'Timeline zoom'}>
          {ZOOMS.map((value) => (
            <button key={value} type="button" aria-pressed={zoom === value}
              disabled={!duration}
              onClick={() => { setZoom(value); setRequestedStart(0); }}
              className={`min-h-9 rounded-md px-2.5 text-xs focus-visible:outline-2 focus-visible:outline-border-focus disabled:opacity-40 ${zoom === value
                ? 'bg-accent/15 font-semibold text-text-primary ring-1 ring-accent/40'
                : 'text-text-secondary hover:bg-bg-elevated'}`}>
              {value === 0 ? (it ? 'Tutto' : 'All') : `${value / 60} min`}
            </button>
          ))}
        </div>
      </div>

      {zoom !== 0 && duration && windowSize && (
        <div className="mb-2 flex items-center justify-between text-xs text-text-secondary">
          <button type="button" disabled={viewedStart === 0}
            onClick={() => setRequestedStart(Math.max(0, viewedStart - windowSize))}
            className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 disabled:opacity-40">
            <ChevronLeft className="h-4 w-4" />{it ? 'Prima' : 'Previous'}
          </button>
          <span className="font-mono text-text-primary" aria-live="polite">{clock(viewedStart)}–{clock(viewedEnd)}</span>
          <button type="button" disabled={viewedStart >= maxStart}
            onClick={() => setRequestedStart(Math.min(maxStart, viewedStart + windowSize))}
            className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 disabled:opacity-40">
            {it ? 'Dopo' : 'Next'}<ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {duration && <div className="mb-2 grid grid-cols-[104px_minmax(0,1fr)] items-center gap-2">
        <span />
        <div className="flex justify-between font-mono text-[11px] text-text-muted">
          {timeTicks.map((tick, index) => <span key={index}>{tick}</span>)}
        </div>
      </div>}
      {loading && <p className="mb-2 text-xs text-text-muted" role="status">
        {it ? 'Caricamento intervalli…' : 'Loading intervals…'}
      </p>}
      {error && <p role="alert" className="mb-3 text-xs text-warning">
        {it ? 'Timeline non disponibile: ' : 'Timeline unavailable: '}{error}
      </p>}
      {!loading && !error && !duration && (
        <p role="status" className="py-3 text-xs text-text-secondary">
          {it ? 'Nessuna durata o attività vocale verificabile per questo meeting.' :
            'No verified meeting duration or voice activity is available.'}
        </p>
      )}

      {duration && (
        <div className="space-y-1.5">
          <div data-speaker-overview="true"
            className="grid min-h-9 grid-cols-[104px_minmax(0,1fr)] items-center gap-2">
            <span className="text-xs font-medium text-text-secondary">{it ? 'Tutti' : 'Everyone'}</span>
            <div className="relative h-7 min-w-0 overflow-hidden rounded-md bg-bg-elevated"
              aria-label={it ? 'Panoramica temporale di tutte le voci' : 'All-speaker timeline overview'}>
              {zoom === 0 && knownBuckets
                ? paintBins(overviewBins, '#94A3B8', it ? 'Tutte le voci' : 'All voices', 'everyone')
                : paintIntervals(allIntervals, '#94A3B8', it ? 'Tutte le voci' : 'All voices', 'overview')}
              {cursorSeconds !== null && cursorSeconds >= viewedStart && cursorSeconds <= viewedEnd && (
                <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-10 w-px bg-text-primary"
                  style={{ left: position(cursorSeconds) }} />
              )}
            </div>
          </div>
          {lanes.map(({ row, color, summary, intervals }) => (
            <Fragment key={row.group}>
              <div className="grid min-h-10 grid-cols-[104px_minmax(0,1fr)] items-center gap-2"
                data-speaker-lane={row.group}>
                <div className="flex min-w-0 items-center gap-1">
                  <button type="button"
                    disabled={!onPlaySample || (sampleAvailable && !sampleAvailable(row.cluster))}
                    onClick={() => onPlaySample?.(row.cluster)}
                    aria-label={it ? `Ascolta un campione di ${row.name}` : `Play a sample of ${row.name}`}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-text-secondary hover:bg-bg-elevated focus-visible:outline-2 focus-visible:outline-border-focus disabled:opacity-40">
                    <Play className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" onClick={() => onSelect(row.cluster)}
                    aria-current={selectedGroup === row.group ? 'true' : undefined}
                    title={row.name}
                    className={`min-w-0 flex-1 truncate rounded-md px-1 py-2 text-left text-xs focus-visible:outline-2 focus-visible:outline-border-focus ${selectedGroup === row.group
                      ? 'bg-accent/15 font-semibold text-text-primary'
                      : 'text-text-secondary hover:bg-bg-elevated hover:text-text-primary'}`}>
                    <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
                    {row.name}
                  </button>
                </div>
                <div className="relative h-7 min-w-0 overflow-hidden rounded-md bg-bg-elevated"
                  aria-label={`${row.name}: ${zoom === 0 ? summary.reduce((n, item) => n + item.interval_count, 0)
                    : intervals.length} ${it ? 'intervalli' : 'intervals'}`}>
                  {zoom === 0 && knownBuckets
                    ? paintBins(summary.flatMap((entry) => entry.bins), color, row.name, row.group)
                    : paintIntervals(intervals, color, row.name, row.group)}
                  {cursorSeconds !== null && cursorSeconds >= viewedStart && cursorSeconds <= viewedEnd && (
                    <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-10 w-px bg-text-primary"
                      style={{ left: position(cursorSeconds) }} />
                  )}
                </div>
              </div>
              {selectedGroup === row.group && timeline && !loading && !error && (
                <p data-speaker-evidence={row.group} role="status" aria-live="polite"
                  className="ml-0 px-1 py-1 text-xs text-text-secondary sm:ml-[112px]">
                  {summary.reduce((total, entry) => total + entry.interval_count, 0) > 0
                    ? `${summary.reduce((total, entry) => total + entry.interval_count, 0)} ` +
                      (it ? 'intervalli nella timeline' : 'intervals on timeline')
                    : (it ? 'Nessun intervallo vocale verificabile' : 'No verifiable voice intervals')}
                  {' · '}
                  {row.count > 0
                    ? `${row.count} ` + (it ? 'interventi collegati al testo' : 'transcript-linked turns')
                    : (it ? 'Testo non collegato a questa voce' : 'No transcript text linked to this voice')}
                </p>
              )}
              {selectedGroup === row.group && children && (
                <div data-speaker-inline-editor={row.group} className="ml-0 rounded-lg border border-border-subtle bg-bg-elevated p-3 sm:ml-[112px] sm:p-4">
                  {children}
                </div>
              )}
            </Fragment>
          ))}
        </div>
      )}

      {timeline && !error && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3 text-xs text-text-muted">
          <span data-timeline-coverage={timeline.coverage}>
            {timeline.coverage === 'diarization'
              ? (it ? 'Intervalli rilevati dall’audio' : 'Audio-detected intervals')
              : timeline.coverage === 'mixed'
                ? (it ? 'Audio e trascrizione · copertura mista' : 'Audio and transcript · mixed coverage')
                : timeline.coverage === 'transcript'
                  ? (it ? 'Solo intervalli attribuiti al testo · copertura parziale' :
                      'Transcript-attributed intervals only · partial coverage')
                  : (it ? 'Nessun intervallo vocale verificabile' : 'No verified speech intervals')}
          </span>
          {timeline.truncated && <span className="text-warning" role="status">
            {it ? 'Troppi intervalli: scegli 1 o 5 minuti.' : 'Too many intervals: choose 1 or 5 minutes.'}
          </span>}
          {!timeline.has_audio && <span className="text-warning">
            {it ? 'Audio locale non disponibile' : 'Local audio unavailable'}
          </span>}
          {zoom === 0 && knownBuckets > 0 && overviewBins.length > 0 && <span>
            {it ? 'Seleziona un blocco per ingrandire' : 'Choose a block to zoom in'}
          </span>}
          {onJumpToTranscript && hasTranscriptAtCursor && cursorSeconds !== null && (
            <button type="button" onClick={() => onJumpToTranscript(cursorSeconds)}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 hover:bg-bg-elevated focus-visible:outline-2 focus-visible:outline-border-focus">
              <ScanSearch className="h-3.5 w-3.5" />{it ? 'Vai al testo' : 'Go to transcript'} · {clock(cursorSeconds)}
            </button>
          )}
        </div>
      )}
      <p className="sr-only">{it
        ? 'I blocchi della panoramica rappresentano intervalli aggregati: selezionali per ingrandire. Le tracce audio non isolano le singole voci.'
        : 'Overview blocks are aggregated navigation bins: zoom in to hear exact intervals. Audio does not isolate individual voices.'}
      </p>
    </section>
  );
}
