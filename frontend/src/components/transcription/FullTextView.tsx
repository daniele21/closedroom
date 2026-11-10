import { useState, useMemo, useCallback } from 'react';
import { Button } from '../ui/Button';
import { Search, ChevronUp, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { TranscriptionSegment } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { speakerDisplay } from '../../utils/speakerPresentation';

interface FullTextViewProps {
  segments: TranscriptionSegment[];
  speakerMappings: Array<{ speaker_cluster: string; display_name?: string | null }>;
}

interface Paragraph {
  speakerLabel: string;
  speakerName: string;
  text: string;
  segmentIds: number[];
}

// 8 differenti colori di testo/sfondo per identificare gli speaker nel testo
const SPEAKER_TEXT_COLORS = [
  'text-indigo-600 dark:text-indigo-400 bg-indigo-500/5 px-1 py-0.5 rounded',
  'text-emerald-600 dark:text-emerald-400 bg-emerald-500/5 px-1 py-0.5 rounded',
  'text-amber-600 dark:text-amber-400 bg-amber-500/5 px-1 py-0.5 rounded',
  'text-rose-600 dark:text-rose-400 bg-rose-500/5 px-1 py-0.5 rounded',
  'text-sky-600 dark:text-sky-400 bg-sky-500/5 px-1 py-0.5 rounded',
  'text-violet-600 dark:text-violet-400 bg-violet-500/5 px-1 py-0.5 rounded',
  'text-teal-600 dark:text-teal-400 bg-teal-500/5 px-1 py-0.5 rounded',
  'text-fuchsia-600 dark:text-fuchsia-400 bg-fuchsia-500/5 px-1 py-0.5 rounded',
];

const PARAGRAPHS_PER_PAGE = 12;

export default function FullTextView({ segments, speakerMappings }: FullTextViewProps) {
  const { lang } = useTranslation();
  const [currentPage, setCurrentPage] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

  // Mappa gli speaker cluster a uno specifico indice di colore
  const speakerColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    let colorIndex = 0;
    segments.forEach((seg) => {
      const spk = seg.speaker_group || seg.provider_speaker || seg.speaker_label || 'unknown';
      if (!map[spk]) {
        map[spk] = SPEAKER_TEXT_COLORS[colorIndex % SPEAKER_TEXT_COLORS.length];
        colorIndex++;
      }
    });
    return map;
  }, [segments]);

  // Raggruppa i segmenti consecutivi dello stesso speaker in paragrafi uniti
  const paragraphs = useMemo(() => {
    if (!segments || segments.length === 0) return [];
    const list: Paragraph[] = [];
    let currentPar: Paragraph | null = null;

    segments.forEach((seg) => {
      const speaker = speakerDisplay(seg, speakerMappings, [], lang === 'it' ? 'it' : 'en');
      const speakerName = speaker.label;
      const label = speaker.key || `unknown-${seg.id}`;

      if (currentPar && currentPar.speakerLabel === label) {
        currentPar.text += ' ' + seg.text;
        currentPar.segmentIds.push(seg.id);
      } else {
        if (currentPar) {
          list.push(currentPar);
        }
        currentPar = {
          speakerLabel: label,
          speakerName,
          text: seg.text,
          segmentIds: [seg.id],
        };
      }
    });

    if (currentPar) {
      list.push(currentPar);
    }
    return list;
  }, [segments, speakerMappings, lang]);

  const totalPages = Math.max(1, Math.ceil(paragraphs.length / PARAGRAPHS_PER_PAGE));

  const wordCount = useMemo(() => {
    return segments.reduce((acc, seg) => acc + seg.text.split(/\s+/).filter(Boolean).length, 0);
  }, [segments]);

  // Trova tutti i match per la ricerca all'interno dei paragrafi
  const matches = useMemo(() => {
    if (!searchTerm.trim()) return [];
    const query = searchTerm.toLowerCase();
    const list: Array<{ paragraphIndex: number; matchOffset: number }> = [];

    paragraphs.forEach((par, paragraphIndex) => {
      let idx = par.text.toLowerCase().indexOf(query);
      while (idx !== -1) {
        list.push({ paragraphIndex, matchOffset: idx });
        idx = par.text.toLowerCase().indexOf(query, idx + 1);
      }
    });
    return list;
  }, [searchTerm, paragraphs]);

  const jumpToMatch = useCallback(
    (matchIdx: number) => {
      if (matches.length === 0) return;
      const safeIdx = ((matchIdx % matches.length) + matches.length) % matches.length;
      setCurrentMatchIndex(safeIdx);
      const parIdx = matches[safeIdx].paragraphIndex;
      setCurrentPage(Math.floor(parIdx / PARAGRAPHS_PER_PAGE));
    },
    [matches],
  );

  const handlePrevMatch = () => jumpToMatch(currentMatchIndex - 1);
  const handleNextMatch = () => jumpToMatch(currentMatchIndex + 1);

  // Pagina corrente di paragrafi
  const visibleParagraphs = useMemo(() => {
    const start = currentPage * PARAGRAPHS_PER_PAGE;
    return paragraphs.slice(start, start + PARAGRAPHS_PER_PAGE);
  }, [paragraphs, currentPage]);

  const renderHighlightedText = (text: string, paragraphIndex: number) => {
    if (!searchTerm.trim()) return text;
    const escaped = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
    let matchCounter = 0;

    return (
      <>
        {parts.map((part, i) => {
          if (part.toLowerCase() === searchTerm.toLowerCase()) {
            const parMatches = matches.filter((m) => m.paragraphIndex === paragraphIndex);
            const globalIdx = parMatches.length > matchCounter
              ? matches.indexOf(parMatches[matchCounter])
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

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar: search + stats */}
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
          <span>{wordCount.toLocaleString()} parole</span>

          {searchTerm.trim() && (
            <div className="flex items-center gap-1 text-text-secondary">
              <span>
                {matches.length > 0
                  ? `${currentMatchIndex + 1}/${matches.length}`
                  : 'Nessun risultato'}
              </span>
              <Button size="sm" variant="ghost" onClick={handlePrevMatch} disabled={matches.length === 0} className="h-7 w-7 p-0 flex items-center justify-center">
                <ChevronUp className="w-4 h-4" />
              </Button>
              <Button size="sm" variant="ghost" onClick={handleNextMatch} disabled={matches.length === 0} className="h-7 w-7 p-0 flex items-center justify-center">
                <ChevronDown className="w-4 h-4" />
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Paragrafi uniti con distinzione speaker */}
      <div className="flex flex-col gap-1.5 select-text leading-relaxed text-text-primary text-sm max-h-[60vh] overflow-y-auto pr-1">
        {visibleParagraphs.map((par, index) => {
          const globalParagraphIndex = currentPage * PARAGRAPHS_PER_PAGE + index;
          const colorClass = speakerColorMap[par.speakerLabel] || 'text-text-muted';

          return (
            <div key={index} className="py-1 px-1.5 rounded hover:bg-bg-elevated/20 transition-colors flex items-start gap-2">
              <span className={`text-xs font-extrabold ${colorClass} shrink-0 w-28 truncate text-right border-r border-border-subtle/30 pr-2`} title={par.speakerName}>
                {par.speakerName}
              </span>
              <p className="text-text-secondary flex-1 text-xs sm:text-sm">
                {renderHighlightedText(par.text, globalParagraphIndex)}
              </p>
            </div>
          );
        })}
      </div>

      {/* Pagination bar */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle pt-3">
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
      )}
    </div>
  );
}
