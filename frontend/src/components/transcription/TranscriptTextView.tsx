import { useState, useMemo } from 'react';
import { RecordingScreenshot, TranscriptionSegment } from '../../api/apiClient';
import { formatTime } from '../../utils/formatters';
import { Button } from '../ui/Button';
import {
  Search, ChevronUp, ChevronDown, ChevronLeft, ChevronRight,
  Activity, Timer, Gauge, Users, Image as ImageIcon, X,
} from 'lucide-react';

interface TranscriptTextViewProps {
  segments: TranscriptionSegment[];
  speakerMappings: Array<{ speaker_cluster: string; display_name?: string | null }>;
  onTimestampClick?: (time: number) => void;
  currentTime?: number;
  screenshots?: RecordingScreenshot[];
}

const SEGMENTS_PER_PAGE = 25;

// 8 colori armoniosi HSL per gli speaker
const SPEAKER_COLORS = [
  'border-l-4 border-indigo-500 bg-indigo-500/5 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
  'border-l-4 border-emerald-500 bg-emerald-500/5 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  'border-l-4 border-amber-500 bg-amber-500/5 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300',
  'border-l-4 border-rose-500 bg-rose-500/5 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300',
  'border-l-4 border-sky-500 bg-sky-500/5 dark:bg-sky-500/10 text-sky-700 dark:text-sky-300',
  'border-l-4 border-violet-500 bg-violet-500/5 dark:bg-violet-500/10 text-violet-700 dark:text-violet-300',
  'border-l-4 border-teal-500 bg-teal-500/5 dark:bg-teal-500/10 text-teal-700 dark:text-teal-300',
  'border-l-4 border-fuchsia-500 bg-fuchsia-500/5 dark:bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300',
];

/** Mappa energy string in label + colore badge */
function energyBadge(energy: string | null | undefined) {
  if (!energy) return null;
  const map: Record<string, { label: string; className: string }> = {
    high: { label: 'Alta', className: 'bg-red-500/15 text-red-600 dark:text-red-400' },
    medium: { label: 'Media', className: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
    medium_low: { label: 'Medio-Bassa', className: 'bg-sky-500/15 text-sky-600 dark:text-sky-400' },
    low: { label: 'Bassa', className: 'bg-slate-500/15 text-slate-600 dark:text-slate-400' },
  };
  return map[energy] || { label: energy, className: 'bg-slate-500/10 text-text-muted' };
}

/**
 * TranscriptTextView – Segment-based transcript viewer with:
 * - True page-based pagination (not "load more")
 * - Inline search with result navigation
 * - Per-segment audio analysis badges (energy, WPM, pause, overlap)
 * - Speaker coloring and click-to-seek timestamps
 */
export default function TranscriptTextView({
  segments,
  speakerMappings,
  onTimestampClick,
  currentTime = 0,
  screenshots = [],
}: TranscriptTextViewProps) {
  const [currentPage, setCurrentPage] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [showAudioDetails, setShowAudioDetails] = useState(true);
  const [selectedScreenshot, setSelectedScreenshot] = useState<RecordingScreenshot | null>(null);

  const totalPages = Math.max(1, Math.ceil(segments.length / SEGMENTS_PER_PAGE));

  // Color map for speakers
  const speakerColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    let colorIndex = 0;
    segments.forEach((seg) => {
      const spk = seg.speaker_label || 'unknown';
      if (!map[spk]) {
        map[spk] = SPEAKER_COLORS[colorIndex % SPEAKER_COLORS.length];
        colorIndex++;
      }
    });
    return map;
  }, [segments]);

  // Check if any segment has audio analysis data
  const hasAudioData = useMemo(
    () => segments.some((s) => s.energy || s.speech_rate_wpm || s.pause_before || s.overlap),
    [segments],
  );

  // Search matches across ALL segments (not just visible page)
  const matches = useMemo(() => {
    if (!searchTerm.trim()) return [];
    const query = searchTerm.toLowerCase();
    const list: Array<{ segmentIndex: number; segmentId: number }> = [];
    segments.forEach((seg, idx) => {
      let pos = seg.text.toLowerCase().indexOf(query);
      while (pos !== -1) {
        list.push({ segmentIndex: idx, segmentId: seg.id });
        pos = seg.text.toLowerCase().indexOf(query, pos + 1);
      }
    });
    return list;
  }, [searchTerm, segments]);

  const jumpToMatch = (matchIdx: number) => {
    if (matches.length === 0) return;
    const safeIdx = ((matchIdx % matches.length) + matches.length) % matches.length;
    setCurrentMatchIndex(safeIdx);
    // Jump to the page containing this match
    const segIdx = matches[safeIdx].segmentIndex;
    setCurrentPage(Math.floor(segIdx / SEGMENTS_PER_PAGE));
  };

  // Paginated segments
  const pageSegments = useMemo(() => {
    const start = currentPage * SEGMENTS_PER_PAGE;
    return segments.slice(start, start + SEGMENTS_PER_PAGE);
  }, [segments, currentPage]);

  const timelineItems = useMemo(() => {
    const pageStartIndex = currentPage * SEGMENTS_PER_PAGE;
    const nextPageStart = segments[pageStartIndex + SEGMENTS_PER_PAGE]?.start;
    const lowerBound = currentPage === 0 ? Number.NEGATIVE_INFINITY : (segments[pageStartIndex]?.start ?? Number.POSITIVE_INFINITY);
    const upperBound = nextPageStart ?? Number.POSITIVE_INFINITY;

    const screenshotItems = screenshots
      .filter((shot) => shot.timestamp >= lowerBound && shot.timestamp < upperBound)
      .map((shot) => ({ kind: 'screenshot' as const, timestamp: shot.timestamp, sequence: shot.sequence, screenshot: shot }));
    const segmentItems = pageSegments.map((segment) => ({
      kind: 'segment' as const,
      timestamp: segment.start,
      sequence: segment.id,
      segment,
    }));
    return [...screenshotItems, ...segmentItems].sort((a, b) => (
      a.timestamp - b.timestamp
      || (a.kind === b.kind ? a.sequence - b.sequence : (a.kind === 'screenshot' ? -1 : 1))
    ));
  }, [currentPage, pageSegments, screenshots, segments]);

  /** Render text with search highlights */
  const renderHighlightedText = (text: string, segmentId: number) => {
    if (!searchTerm.trim()) return text;
    const escaped = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
    let matchCounter = 0;

    return (
      <>
        {parts.map((part, i) => {
          if (part.toLowerCase() === searchTerm.toLowerCase()) {
            const segMatches = matches.filter((m) => m.segmentId === segmentId);
            const globalIdx = segMatches.length > matchCounter
              ? matches.indexOf(segMatches[matchCounter])
              : -1;
            const isCurrent = globalIdx === currentMatchIndex;
            matchCounter++;
            return (
              <mark
                key={i}
                className={`px-0.5 rounded transition-colors ${
                  isCurrent
                    ? 'bg-amber-400 dark:bg-amber-500 text-black font-semibold ring-2 ring-amber-600'
                    : 'bg-yellow-200 dark:bg-yellow-800/60 text-text-primary'
                }`}
              >
                {part}
              </mark>
            );
          }
          return part;
        })}
      </>
    );
  };

  /** Render pagination controls */
  const renderPagination = () => {
    if (totalPages <= 1) return null;
    return (
      <div className="flex items-center justify-between border-t border-border-subtle pt-3 mt-1">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
          disabled={currentPage === 0}
          className="flex items-center gap-1 text-xs"
        >
          <ChevronLeft className="w-4 h-4" /> Precedente
        </Button>

        <div className="flex items-center gap-1">
          {Array.from({ length: totalPages }, (_, i) => {
            const showDots = totalPages > 7;
            if (showDots) {
              const show = i === 0 || i === totalPages - 1 || Math.abs(i - currentPage) <= 1;
              const showEllipsisBefore = i === currentPage - 2 && currentPage > 3;
              const showEllipsisAfter = i === currentPage + 2 && currentPage < totalPages - 4;
              if (showEllipsisBefore || showEllipsisAfter) {
                return <span key={i} className="text-xs text-text-muted px-1">…</span>;
              }
              if (!show) return null;
            }
            return (
              <button
                key={i}
                onClick={() => setCurrentPage(i)}
                className={`min-w-[28px] h-7 rounded-md text-xs font-medium transition-colors cursor-pointer border-none ${
                  i === currentPage
                    ? 'bg-accent text-white'
                    : 'bg-transparent text-text-secondary hover:bg-bg-elevated hover:text-text-primary'
                }`}
              >
                {i + 1}
              </button>
            );
          })}
        </div>

        <Button
          size="sm"
          variant="ghost"
          onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
          disabled={currentPage === totalPages - 1}
          className="flex items-center gap-1 text-xs"
        >
          Successivo <ChevronRight className="w-4 h-4" />
        </Button>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-3 bg-bg-surface border border-border-subtle rounded-xl">
        <div className="relative w-full sm:w-80">
          <span className="absolute inset-y-0 left-3 flex items-center text-text-muted pointer-events-none">
            <Search className="w-4 h-4" />
          </span>
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setCurrentMatchIndex(0);
            }}
            placeholder="Cerca nel testo..."
            className="w-full pl-9 pr-4 py-1.5 rounded-lg border border-border-subtle bg-bg-elevated text-sm text-text-primary outline-none transition-colors focus:border-border-focus"
          />
        </div>

        <div className="flex items-center gap-3 text-xs text-text-muted shrink-0">
          <span>{segments.length} segmenti</span>

          {hasAudioData && (
            <button
              onClick={() => setShowAudioDetails((v) => !v)}
              className={`flex items-center gap-1 px-2 py-1 rounded-md border border-border-subtle text-[10px] font-medium transition-colors cursor-pointer ${
                showAudioDetails
                  ? 'bg-accent/10 text-accent border-accent/30'
                  : 'bg-transparent text-text-muted hover:bg-bg-elevated'
              }`}
              title="Mostra/nascondi dettagli analisi audio"
            >
              <Activity className="w-3 h-3" />
              Audio
            </button>
          )}

          {searchTerm.trim() && (
            <div className="flex items-center gap-1 text-text-secondary">
              <span>
                {matches.length > 0
                  ? `${currentMatchIndex + 1}/${matches.length}`
                  : 'Nessun risultato'}
              </span>
              <Button size="sm" variant="ghost" onClick={() => jumpToMatch(currentMatchIndex - 1)} disabled={matches.length === 0} className="h-7 w-7 p-0 flex items-center justify-center">
                <ChevronUp className="w-4 h-4" />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => jumpToMatch(currentMatchIndex + 1)} disabled={matches.length === 0} className="h-7 w-7 p-0 flex items-center justify-center">
                <ChevronDown className="w-4 h-4" />
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Segment cards */}
      <div className="flex flex-col gap-3">
        {timelineItems.map((item) => {
          if (item.kind === 'screenshot') {
            const shot = item.screenshot;
            return (
              <button
                key={`screenshot-${shot.screenshot_id}`}
                type="button"
                onClick={() => setSelectedScreenshot(shot)}
                className="group flex w-full items-center gap-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-left transition-colors hover:border-cyan-500/40 hover:bg-cyan-500/10"
                aria-label={`Apri screenshot a ${formatTime(shot.timestamp)}`}
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-300">
                  <ImageIcon className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[10px] font-bold uppercase tracking-wider text-cyan-700 dark:text-cyan-300">
                    Screenshot · {formatTime(shot.timestamp)}
                  </span>
                  <span className="block truncate text-xs text-text-secondary">
                    {shot.available ? (shot.display_title || 'Schermo acquisito') : 'Immagine originale non disponibile'}
                  </span>
                </span>
                {shot.thumbnail_available && (
                  <img
                    src={shot.thumbnail_url}
                    alt=""
                    loading="lazy"
                    className="h-10 w-16 shrink-0 rounded-md border border-border-subtle object-cover"
                  />
                )}
              </button>
            );
          }

          const seg = item.segment;
          const mapping = speakerMappings.find((m) => m.speaker_cluster === seg.speaker_label);
          const speakerName = mapping?.display_name || seg.speaker_name || seg.speaker_label || 'Speaker';
          const colorClass = speakerColorMap[seg.speaker_label || 'unknown'] || 'border-l-4 border-border-subtle';
          const isPlaying = currentTime >= seg.start && currentTime <= seg.end;
          const eBadge = energyBadge(seg.energy);

          return (
            <div
              key={seg.id}
              className={`p-3 rounded-xl border border-border-subtle/70 transition-all duration-200 flex flex-col gap-1.5 ${colorClass} ${
                isPlaying ? 'ring-2 ring-accent bg-accent/5' : 'bg-bg-surface/30'
              }`}
            >
              {/* Header: timestamp + speaker + audio analysis badges inline on the right */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle/30 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => onTimestampClick?.(seg.start)}
                    className="hover:text-accent hover:underline cursor-pointer flex items-center gap-1 transition-colors bg-transparent border-none p-0"
                    title="Fai clic per riprodurre da questo punto"
                  >
                    ⏱️ {formatTime(seg.start)} → {formatTime(seg.end)}
                  </button>
                  <span className="font-semibold text-text-secondary flex items-center gap-1">
                    <Users className="w-3 h-3" />
                    {speakerName}
                  </span>
                </div>

                {/* Audio analysis badges aligned right */}
                {showAudioDetails && hasAudioData && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {eBadge && (
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold ${eBadge.className}`}>
                        <Activity className="w-2.5 h-2.5" />
                        {eBadge.label}
                      </span>
                    )}
                    {typeof seg.speech_rate_wpm === 'number' && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-500/10 text-blue-600 dark:text-blue-400">
                        <Gauge className="w-2.5 h-2.5" />
                        {seg.speech_rate_wpm} WPM
                      </span>
                    )}
                    {typeof seg.pause_before === 'number' && seg.pause_before > 0.5 && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-violet-500/10 text-violet-600 dark:text-violet-400">
                        <Timer className="w-2.5 h-2.5" />
                        Pausa: {seg.pause_before.toFixed(1)}s
                      </span>
                    )}
                    {seg.overlap && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-orange-500/15 text-orange-600 dark:text-orange-400">
                        <Users className="w-2.5 h-2.5" />
                        Overlap
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Transcript text */}
              <p className="text-text-primary text-sm leading-relaxed font-medium">
                {renderHighlightedText(seg.text, seg.id)}
              </p>
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      {renderPagination()}

      {selectedScreenshot && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Screenshot della riunione"
          onClick={() => setSelectedScreenshot(null)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border-subtle bg-bg-elevated shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-border-subtle px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-text-primary">Screenshot · {formatTime(selectedScreenshot.timestamp)}</p>
                <p className="truncate text-xs text-text-muted">{selectedScreenshot.display_title || 'Schermo acquisito'}</p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" onClick={() => onTimestampClick?.(selectedScreenshot.timestamp)}>
                  Vai all'audio
                </Button>
                <button
                  type="button"
                  onClick={() => setSelectedScreenshot(null)}
                  className="rounded-lg p-2 text-text-muted hover:bg-bg-surface hover:text-text-primary"
                  aria-label="Chiudi screenshot"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="min-h-0 overflow-auto bg-black/5 p-3">
              {selectedScreenshot.available ? (
                <img
                  src={selectedScreenshot.original_url}
                  alt={`Screenshot a ${formatTime(selectedScreenshot.timestamp)}`}
                  className="mx-auto max-h-[76vh] max-w-full rounded-lg object-contain"
                />
              ) : (
                <div className="rounded-xl border border-warning/30 bg-warning/5 p-6 text-center text-sm text-text-secondary">
                  L'immagine non è più disponibile. Il riferimento temporale resta nella timeline.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
