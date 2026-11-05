import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, ScanSearch } from 'lucide-react';
import { ApiClient, type SpeakerClip, type SpeakerTimelineWindow, type Transcription } from '../../api/apiClient';

export interface TimelineSpeakerRow {
  cluster: string;
  group: string;
  name: string;
  status: string;
  sourceOnly: boolean;
}

interface Props {
  transcription: Transcription;
  recordingId: string;
  durationSeconds: number;
  rows: TimelineSpeakerRow[];
  showHidden: boolean;
  selectedGroup: string | null;
  cursorSeconds: number | null;
  onSelect: (cluster: string) => void;
  onPlayInterval: (clip: SpeakerClip) => void;
  onJumpToTranscript?: (time: number) => void;
  lang: string;
}

const COLORS = ['#63A6FF', '#73D5A1', '#CE9AFF', '#FFBC69', '#FF8698', '#71D6E0', '#E9D568', '#B7B4F5'];
const MAX_DURATION = 28800;
const ZOOMS = [0, 60, 300, 600] as const;

function clock(value: number): string {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

function intervalClip(item: SpeakerTimelineWindow['intervals'][number]): SpeakerClip {
  return {
    track_id: item.track_id, start: item.start, end: item.end,
    kind: item.origin === 'diarization' ? 'diarization' : 'transcript',
    overlap: item.overlap,
  };
}

/** One common clock for all voices; source track is never silently a person. */
export function SpeakerTimeline({
  transcription, recordingId, durationSeconds, rows, showHidden, selectedGroup,
  cursorSeconds, onSelect, onPlayInterval, onJumpToTranscript, lang,
}: Props) {
  const it = lang === 'it';
  const transcriptionId = transcription.id || transcription.saved_id || '';
  const [recordingDuration, setRecordingDuration] = useState(0);
  useEffect(() => {
    let current = true;
    setRecordingDuration(0);
    if (recordingId) {
      void ApiClient.getRecording(recordingId).then((recording) => {
        if (current) setRecordingDuration(Number(recording.duration_seconds || recording.duration || recording.metadata?.duration_seconds || 0));
      }).catch(() => { /* The transcription still provides a safe duration fallback. */ });
    }
    return () => { current = false; };
  }, [recordingId]);
  const lastSegment = (transcription.segments || []).reduce((last, segment) => Math.max(last, Number(segment.end) || 0), 0);
  const duration = Math.min(MAX_DURATION, Math.max(1, Math.ceil(durationSeconds || 0), Math.ceil(recordingDuration || 0), Math.ceil(lastSegment)));
  const [zoom, setZoom] = useState<number>(0);
  const [requestedStart, setRequestedStart] = useState(0);
  const [timeline, setTimeline] = useState<SpeakerTimelineWindow | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const windowSize = zoom === 0 ? duration : Math.min(zoom, duration);
  const maxStart = Math.max(0, duration - windowSize);
  const start = Math.min(maxStart, Math.max(0, requestedStart));
  const end = start + windowSize;

  useEffect(() => {
    if (!transcriptionId) return;
    const abort = new AbortController();
    setLoading(true);
    setError('');
    setTimeline(null);
    void ApiClient.getSpeakerTimeline(transcriptionId, start, end, abort.signal)
      .then((value) => { if (!abort.signal.aborted) setTimeline(value); })
      .catch((exc: Error) => {
        if (!abort.signal.aborted) setError(exc.message || 'Timeline unavailable');
      })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [transcriptionId, transcription, start, end]);

  const groups = useMemo(() => {
    const roots = rows.filter((r) => r.status !== 'merged' && !r.sourceOnly &&
      (showHidden || r.status !== 'excluded'));
    const rootsByGroup = new Map(roots.map((r) => [r.group, r]));
    const sourceByCluster = new Map(rows.map((r) => [r.cluster, r]));
    const lanes = roots.map((row, index) => ({
      row, color: COLORS[index % COLORS.length],
      intervals: [] as SpeakerTimelineWindow['intervals'],
    }));
    const byGroup = new Map(lanes.map((lane) => [lane.row.group, lane]));
    const overview: Array<{ item: SpeakerTimelineWindow['intervals'][number]; color: string; name: string; lane: number }> = [];
    for (const item of timeline?.intervals || []) {
      const originRow = sourceByCluster.get(item.cluster);
      const target = originRow && rootsByGroup.get(originRow.group);
      const lane = target ? byGroup.get(target.group) : undefined;
      // Unmapped source tracks and excluded voices have no invented person.
      const color = lane?.color || '#88919C';
      const name = lane?.row.name || (it ? 'Voce non attribuita' : 'Unattributed voice');
      if (lane) lane.intervals.push(item);
      overview.push({ item, color, name, lane: lane ? lanes.indexOf(lane) : -1 });
    }
    return { lanes, overview };
  }, [rows, showHidden, timeline, it]);

  const hasIntervals = (timeline?.intervals.length || 0) > 0;
  const pct = (time: number) => `${Math.max(0, Math.min(100, (time - start) / windowSize * 100))}%`;
  const width = (a: number, b: number) => `${Math.max(0.2, (b - a) / windowSize * 100)}%`;
  const jump = (item: SpeakerTimelineWindow['intervals'][number]) => {
    if (!item.playable) return;
    // Playing an interval must not change speaker selection: the editor's
    // selection effect resets the shared audio player. Lane labels separately
    // own selecting a person, preserving a single predictable playback owner.
    onPlayInterval(intervalClip(item));
  };

  return (
    <section data-speaker-review-timeline="true" aria-label={it ? 'Timeline delle voci' : 'Speaker timeline'}
      className="mb-4 rounded-xl border border-border-subtle bg-bg-surface px-3 py-4 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">
            {it ? 'Chi parla, quando' : 'Who speaks, and when'}
          </h4>
          <p className="mt-0.5 text-xs text-text-secondary">
            {it ? 'Tutte le voci sulla stessa scala temporale. Seleziona un intervallo per ascoltarlo.' :
              'All voices on the same clock. Select an interval to hear it.'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1" aria-label={it ? 'Zoom timeline' : 'Timeline zoom'}>
          {ZOOMS.map((value) => (
            <button key={value} type="button" aria-pressed={zoom === value}
              onClick={() => { setZoom(value); setRequestedStart(0); }}
              className={`min-h-9 rounded-md px-2.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-border-focus ${zoom === value ? 'bg-accent/15 text-text-primary ring-1 ring-accent/40' : 'text-text-secondary hover:bg-bg-elevated'}`}>
              {value === 0 ? (it ? 'Tutto' : 'All') : `${value / 60} min`}
            </button>
          ))}
        </div>
      </div>
      {zoom !== 0 && (
        <div className="mb-2 flex items-center justify-between gap-2 text-xs text-text-secondary">
          <button type="button" disabled={start <= 0}
            onClick={() => setRequestedStart(Math.max(0, start - windowSize))}
            className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 hover:bg-bg-elevated disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-border-focus">
            <ChevronLeft className="h-4 w-4" />{it ? 'Prima' : 'Previous'}
          </button>
          <span className="font-mono text-text-primary" aria-live="polite">{clock(start)}–{clock(end)}</span>
          <button type="button" disabled={start >= maxStart}
            onClick={() => setRequestedStart(Math.min(maxStart, start + windowSize))}
            className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 hover:bg-bg-elevated disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-border-focus">
            {it ? 'Dopo' : 'Next'}<ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
      <div className="mb-2 flex justify-between pl-[84px] font-mono text-[11px] text-text-muted">
        {[0, 0.25, 0.5, 0.75, 1].map((portion) => (
          <span key={portion}>{clock(start + portion * windowSize)}</span>
        ))}
      </div>
      {loading && <p role="status" className="py-4 text-xs text-text-muted">{it ? 'Caricamento interventi…' : 'Loading turns…'}</p>}
      {error && <div className="rounded-md border border-warning/40 p-3 text-xs text-warning" role="alert">
        {it ? 'Timeline non disponibile: ' : 'Timeline unavailable: '}{error}
      </div>}
      {!loading && !error && !hasIntervals && (
        <p className="py-4 text-xs text-text-secondary" role="status">
          {it ? 'Nessun intervallo attribuito in questa parte del meeting.' :
            'No attributed speech intervals in this part of the meeting.'}
        </p>
      )}
      {!loading && !error && hasIntervals && (
        <div className="space-y-2">
          <div className="flex min-h-10 items-center gap-2" data-speaker-overview="true">
            <span className="w-[76px] shrink-0 text-xs font-semibold text-text-primary">{it ? 'Tutti' : 'Everyone'}</span>
            <div className="relative h-9 min-w-0 flex-1 overflow-hidden rounded-md border border-border-subtle bg-bg-elevated"
              aria-label={it ? 'Interventi complessivi' : 'All speaker turns'}>
              {groups.overview.map(({ item, color, name, lane }, index) => (
                <button key={index} type="button" disabled={!item.playable}
                  title={`${name}: ${clock(item.start)}–${clock(item.end)}`}
                  aria-label={`${item.playable ? it ? 'Ascolta' : 'Play' : it ? 'Audio non disponibile' : 'Audio unavailable'} ${name}, ${clock(item.start)}–${clock(item.end)}`}
                  onClick={() => jump(item)}
                  className="absolute rounded-sm focus-visible:z-20 focus-visible:outline-2 focus-visible:outline-border-focus disabled:cursor-default"
                  style={{ left: pct(item.start), width: width(item.start, item.end), top: `${5 + (lane < 0 ? 3 : lane % 3) * 9}px`,
                    height: '7px', backgroundColor: color, opacity: selectedGroup && rows.find((r) => r.cluster === item.cluster)?.group !== selectedGroup ? 0.35 : 1 }} />
              ))}
              {cursorSeconds !== null && cursorSeconds >= start && cursorSeconds <= end && (
                <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-10 w-px bg-text-primary"
                  style={{ left: pct(cursorSeconds) }} />
              )}
            </div>
          </div>
          {groups.lanes.map(({ row, color, intervals }) => (
            <div key={row.group} className="flex min-h-9 items-center gap-2" data-speaker-lane={row.group}>
              <button type="button" onClick={() => onSelect(row.cluster)} aria-current={selectedGroup === row.group ? 'true' : undefined}
                title={row.name} className={`w-[76px] shrink-0 truncate rounded px-1 py-2 text-left text-xs focus-visible:outline-2 focus-visible:outline-border-focus ${selectedGroup === row.group ? 'bg-accent/15 font-semibold text-text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
                <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
                {row.name}
              </button>
              <div className="relative h-7 min-w-0 flex-1 overflow-hidden rounded-md bg-bg-elevated"
                aria-label={`${row.name} — ${intervals.length} ${it ? 'interventi visibili' : 'visible intervals'}`}>
                {intervals.map((item, index) => (
                  <button key={index} type="button" disabled={!item.playable}
                    title={`${row.name}: ${clock(item.start)}–${clock(item.end)}`}
                    aria-label={`${item.playable ? it ? 'Ascolta' : 'Play' : it ? 'Audio non disponibile' : 'Audio unavailable'} ${row.name}, ${clock(item.start)}–${clock(item.end)}`}
                    data-speaker-interval={row.group} data-interval-origin={item.origin}
                    onClick={() => jump(item)}
                    className="absolute inset-y-1.5 rounded-sm focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-border-focus disabled:cursor-default"
                    style={{ left: pct(item.start), width: width(item.start, item.end), backgroundColor: color }} />
                ))}
                {cursorSeconds !== null && cursorSeconds >= start && cursorSeconds <= end && (
                  <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-10 w-px bg-text-primary"
                    style={{ left: pct(cursorSeconds) }} />
                )}
              </div>
            </div>
          ))}
          {groups.overview.some((item) => item.lane < 0) && (
            <p className="text-xs text-text-muted">
              {it ? 'I segmenti grigi non sono attribuiti a una persona confermata.' :
                'Grey intervals are not assigned to a confirmed person.'}
            </p>
          )}
        </div>
      )}
      {!loading && !error && timeline && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3 text-xs text-text-muted">
          <span data-timeline-coverage={timeline.coverage}>
            {timeline.coverage === 'diarization'
              ? (it ? 'Intervalli rilevati dall’audio' : 'Audio-detected intervals')
              : timeline.coverage === 'mixed'
                ? (it ? 'Audio e trascrizione: copertura mista' : 'Audio and transcript: mixed coverage')
                : (it ? 'Intervalli attribuiti alla trascrizione (non tutte le voci rilevate)' :
                  'Transcript-attributed intervals (not all detected voices)')}
          </span>
          {timeline.truncated && (
            <span className="text-warning" role="status">
              {it ? 'Troppi intervalli: usa lo zoom per vedere tutti i dettagli.' :
                'Many intervals: zoom in to view all details.'}
            </span>
          )}
          {!timeline.has_audio && (
            <span className="text-warning">{it ? 'Audio locale non disponibile' : 'Local audio unavailable'}</span>
          )}
          {onJumpToTranscript && cursorSeconds !== null && (
            <button type="button" onClick={() => onJumpToTranscript(cursorSeconds)}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-text-secondary hover:bg-bg-elevated hover:text-text-primary focus-visible:outline-2 focus-visible:outline-border-focus">
              <ScanSearch className="h-3.5 w-3.5" />{it ? 'Vai al testo' : 'Go to transcript'} · {clock(cursorSeconds)}
            </button>
          )}
        </div>
      )}
      <span className="sr-only">{it ? 'Ogni rettangolo rappresenta un intervallo di parlato, non una traccia vocale isolata. Le sovrapposizioni possono contenere più voci.' :
        'Each rectangle is a speech interval, not an isolated voice track. Overlaps can contain multiple voices.'}</span>
    </section>
  );
}
