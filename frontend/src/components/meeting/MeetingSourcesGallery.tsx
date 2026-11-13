import { Bookmark, ChevronDown, Images, Loader2 } from 'lucide-react';
import type { RecordingNote, RecordingScreenshot } from '../../api/apiClient';
import type { VisualManualScreenshotGroup } from '../../api/visualIntelligence';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { cn } from '../../utils/cn';

type SourceContext = { excerpt: string; speakers: string[] };
type SourceVisual = { contentType: string | null; title: string | null };

interface MeetingSourcesGalleryProps {
  lang: string;
  notes: RecordingNote[];
  screenshotsState: string;
  savedScreenshotCount: number;
  showAllScreenshots: boolean;
  canExpandScreenshots: boolean;
  hiddenScreenshotCount: number;
  visibleKeyMoments: Array<{shot: RecordingScreenshot; group: VisualManualScreenshotGroup | null}>;
  keyMomentContexts: ReadonlyMap<string, SourceContext>;
  getVisualContext: (shot: RecordingScreenshot) => SourceVisual | null;
  screenshotTimestampLabel: (time: number) => string;
  onOpenScreenshot: (shot: RecordingScreenshot) => void;
  onSeek: (time: number) => void;
  onReloadScreenshots: () => void;
  onToggleShowAll: () => void;
}

// Presentational projection of the canonical Meeting's existing local notes/screenshots.
// Never fetches media, changes persistence, infers visual evidence or owns playback.
export function MeetingSourcesGallery({
  lang, notes, screenshotsState, savedScreenshotCount, showAllScreenshots,
  canExpandScreenshots, hiddenScreenshotCount, visibleKeyMoments,
  keyMomentContexts, getVisualContext, screenshotTimestampLabel,
  onOpenScreenshot, onSeek, onToggleShowAll, onReloadScreenshots,
}: MeetingSourcesGalleryProps) {
  const loadScreenshots = onReloadScreenshots;
  return (
    <section data-meeting-notes-sources="true" aria-labelledby="meeting-sources-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="meeting-sources-heading" className="text-sm font-semibold text-text-primary">
          {lang === 'it' ? 'Note e fonti' : 'Notes and sources'}
        </h2>
        <span className="text-xs text-text-muted">
          {notes.length} {lang === 'it' ? 'note' : 'notes'} · {savedScreenshotCount} screenshot
        </span>
      </div>
      <div className="grid min-w-0 grid-cols-1 items-start gap-3 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">

        <section aria-label={lang === 'it' ? 'Note del meeting' : 'Meeting notes'} className="min-w-0 rounded-xl border border-border-subtle bg-bg-elevated p-4" data-meeting-user-notes="true">
          <h3 className="text-sm font-semibold text-text-primary">{lang === 'it' ? 'Note prese durante il meeting' : 'Notes captured during the meeting'} <span className="text-text-muted">({notes.length})</span></h3>
          {notes.length === 0 ? (
            <p className="mt-3 text-xs text-text-muted">
              {lang === 'it' ? 'Nessuna nota manuale. Gli screenshot restano disponibili anche senza trascrizione.' : 'No manual notes. Screenshots remain available without a transcript.'}
            </p>
          ) : (
            <div className="mt-3 max-h-72 space-y-2 overflow-auto">
              {[...notes].sort((left, right) => left.timestamp - right.timestamp).map((note) => (
                <button
                  key={note.note_id}
                  type="button"
                  onClick={() => onSeek(note.timestamp)}
                  className="flex w-full gap-3 rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-left text-xs text-text-secondary hover:border-border-focus focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                  aria-label={`${lang === 'it' ? 'Vai alla nota' : 'Seek note'} ${screenshotTimestampLabel(note.timestamp)}`}
                  data-meeting-user-note-id={note.note_id}
                >
                  <span className="shrink-0 font-mono text-accent">{screenshotTimestampLabel(note.timestamp)}</span>
                  <span className="min-w-0 whitespace-pre-wrap break-words">{note.text}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <div className="min-w-0">
        {screenshotsState === 'loading' && (
          <section
            className="rounded-xl border border-border-subtle bg-bg-surface/40 px-4 py-4"
            aria-label={lang === 'it' ? 'Screenshot del meeting' : 'Meeting screenshots'}
            aria-busy="true"
          >
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              <span>{lang === 'it' ? 'Caricamento screenshot…' : 'Loading screenshots…'}</span>
            </div>
          </section>
        )}

        {screenshotsState === 'error' && (
          <section className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-start gap-2">
                <Images className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                <div>
                  <p className="text-xs font-semibold text-text-primary">
                    {lang === 'it' ? 'Screenshot non disponibili' : 'Screenshots unavailable'}
                  </p>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {lang === 'it'
                      ? 'ClosedRoom non è riuscito a caricare le immagini salvate per questo meeting.'
                      : 'ClosedRoom could not load the images saved for this meeting.'}
                  </p>
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={loadScreenshots}>
                {lang === 'it' ? 'Riprova' : 'Retry'}
              </Button>
            </div>
          </section>
        )}

        {screenshotsState === 'ready' && savedScreenshotCount > 0 && (
          <section
            data-meeting-screenshot-gallery="true"
            data-key-moments="true"
            className="rounded-xl border border-border-subtle bg-bg-elevated p-4"
            aria-labelledby="meeting-screenshots-title"
          >
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <Bookmark className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 id="meeting-screenshots-title" className="text-xs font-semibold text-text-primary">
                      {lang === 'it' ? 'Momenti chiave' : 'Key moments'}
                    </h3>
                    <Badge variant="idle">{savedScreenshotCount}</Badge>
                  </div>
                  <p className="mt-0.5 max-w-2xl text-[11px] leading-relaxed text-text-muted">
                    {lang === 'it'
                      ? 'Momenti che hai segnato durante il meeting. ClosedRoom li collega al transcript e all’audio senza registrare lo schermo in continuo.'
                      : 'Moments you marked during the meeting. ClosedRoom connects them to the transcript and audio without continuous screen recording.'}
                  </p>
                </div>
              </div>
              {canExpandScreenshots && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={onToggleShowAll}
                  aria-expanded={showAllScreenshots}
                  className="shrink-0"
                >
                  {showAllScreenshots
                    ? (lang === 'it' ? 'Raggruppa simili' : 'Group similar')
                    : (lang === 'it' ? `Mostra tutti gli scatti (${savedScreenshotCount})` : `Show all captures (${savedScreenshotCount})`)}
                  <ChevronDown
                    className={cn('h-3.5 w-3.5 transition-transform', showAllScreenshots && 'rotate-180')}
                    aria-hidden="true"
                  />
                </Button>
              )}
            </div>

            <div className="flex flex-col gap-2.5">
              {visibleKeyMoments.map(({ shot, group }) => {
                const context = keyMomentContexts.get(shot.screenshot_id);
                const visualContext = getVisualContext(shot);
                return (
                  <button
                    key={group?.group_id || shot.screenshot_id}
                    type="button"
                    onClick={() => onOpenScreenshot(shot)}
                    className="group grid min-h-[124px] w-full max-w-3xl grid-cols-[128px_minmax(0,1fr)] overflow-hidden rounded-xl border border-border-subtle bg-bg-surface text-left transition hover:border-border-focus hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus sm:grid-cols-[190px_minmax(0,1fr)]"
                    aria-label={
                      lang === 'it'
                        ? `Apri momento chiave a ${screenshotTimestampLabel(shot.timestamp)}`
                        : `Open key moment at ${screenshotTimestampLabel(shot.timestamp)}`
                    }
                    title={shot.display_title || undefined}
                    data-key-moment-id={shot.screenshot_id}
                    data-key-moment-group={group?.group_id || undefined}
                  >
                    <div className="flex h-full min-h-[124px] items-center justify-center overflow-hidden bg-black/5 p-1.5">
                      {shot.available && shot.thumbnail_available ? (
                        <img
                          src={shot.thumbnail_url}
                          alt=""
                          loading="lazy"
                          className="max-h-[120px] w-full object-contain transition-transform duration-200 group-hover:scale-[1.01]"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center px-3 text-center text-[10px] text-text-muted">
                          {lang === 'it' ? 'Immagine non disponibile' : 'Image unavailable'}
                        </div>
                      )}
                    </div>
                    <div className="flex min-w-0 flex-col justify-between gap-2 p-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] font-semibold tabular-nums text-text-primary">
                            {group
                              ? `${screenshotTimestampLabel(group.start)}–${screenshotTimestampLabel(group.end)}`
                              : screenshotTimestampLabel(shot.timestamp)}
                          </span>
                          <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[9px] font-semibold text-accent">
                            {lang === 'it' ? 'Segnato da te' : 'Marked by you'}
                          </span>
                          {group && (
                            <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[9px] font-semibold text-text-muted">
                              {lang === 'it'
                                ? `${group.screenshot_ids.length} scatti simili`
                                : `${group.screenshot_ids.length} similar captures`}
                            </span>
                          )}
                          {visualContext?.contentType && (
                            <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[9px] font-medium capitalize text-text-muted">
                              {visualContext.contentType}
                            </span>
                          )}
                        </div>
                        {visualContext?.title && (
                          <p className="mt-1.5 truncate text-xs font-semibold text-text-primary" title={visualContext.title}>
                            {visualContext.title}
                          </p>
                        )}
                        <p className="mt-2 max-h-14 overflow-hidden text-xs leading-relaxed text-text-secondary">
                          {context?.excerpt || (
                            lang === 'it'
                              ? 'Nessun parlato vicino a questo momento. L’immagine e il riferimento temporale restano disponibili.'
                              : 'No nearby speech for this moment. The image and timestamp remain available.'
                          )}
                        </p>
                      </div>
                      <div className="flex min-w-0 items-center justify-between gap-2 text-[10px] text-text-muted">
                        <span className="truncate">
                          {context?.speakers?.length
                            ? context.speakers.join(' · ')
                            : (shot.display_title || (lang === 'it' ? 'Contesto visuale' : 'Visual context'))}
                        </span>
                        <span className="shrink-0 font-medium text-accent">
                          {lang === 'it' ? 'Apri momento' : 'Open moment'}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {!showAllScreenshots && hiddenScreenshotCount > 0 && (
              <p className="mt-2.5 text-right text-[10px] text-text-muted">
                {lang === 'it'
                  ? `+${hiddenScreenshotCount} scatti raccolti negli stack`
                  : `+${hiddenScreenshotCount} captures grouped into stacks`}
              </p>
            )}
          </section>
        )}


          {screenshotsState === 'ready' && savedScreenshotCount === 0 && (
            <div className="rounded-xl border border-border-subtle bg-bg-surface p-4 text-xs text-text-muted" data-meeting-screenshots-empty="true">
              {lang === 'it'
                ? 'Nessuno screenshot catturato durante il meeting. Gli scatti manuali compariranno qui, senza avviare l’AI.'
                : 'No screenshots were captured during the meeting. Manual captures will appear here without starting AI.'}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
