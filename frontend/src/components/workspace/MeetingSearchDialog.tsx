import { useEffect, useRef, useState } from 'react';
import { ChevronRight, LoaderCircle, Search, X } from 'lucide-react';

import type { Meeting } from '../../api/apiClient';
import { searchMeetingArchive } from '../../api/meetingSearchApi';
import { meetingTitle } from '../../utils/meetingInsights';
import { Button } from '../ui/Button';
import { Dialog, DialogBody, DialogContent, DialogHeader } from '../ui/Dialog';

const PAGE_SIZE = 25;
const QUERY_STORAGE_KEY = 'closedroom.meeting-search.query';

interface MeetingSearchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenMeeting: (id: string) => void;
  lang: string;
  demoMeetings?: Meeting[];
}

export function MeetingSearchDialog({
  open,
  onOpenChange,
  onOpenMeeting,
  lang,
  demoMeetings,
}: MeetingSearchDialogProps) {
  const [query, setQuery] = useState(() => sessionStorage.getItem(QUERY_STORAGE_KEY) || '');
  const [items, setItems] = useState<Meeting[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  useEffect(() => {
    sessionStorage.setItem(QUERY_STORAGE_KEY, query);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const generation = ++generationRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        if (demoMeetings) {
          const needle = query.trim().toLocaleLowerCase(lang);
          const filtered = needle
            ? demoMeetings.filter((meeting) =>
                [meetingTitle(meeting), meeting.project_name, meeting.transcription?.text || '']
                  .join(' ')
                  .toLocaleLowerCase(lang)
                  .includes(needle),
              )
            : demoMeetings;
          if (generation !== generationRef.current) return;
          setItems(filtered.slice(0, PAGE_SIZE));
          setTotal(filtered.length);
          setPage(1);
          setHasMore(filtered.length > PAGE_SIZE);
          return;
        }

        const response = await searchMeetingArchive(query, 1, PAGE_SIZE, controller.signal);
        if (generation !== generationRef.current) return;
        setItems(response.items);
        setTotal(response.total);
        setPage(response.page);
        setHasMore(response.has_more);
      } catch (err) {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setItems([]);
        setTotal(0);
        setHasMore(false);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (generation === generationRef.current) setLoading(false);
      }
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, query, demoMeetings, lang]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    if (demoMeetings) {
      const needle = query.trim().toLocaleLowerCase(lang);
      const filtered = needle
        ? demoMeetings.filter((meeting) =>
            [meetingTitle(meeting), meeting.project_name, meeting.transcription?.text || '']
              .join(' ')
              .toLocaleLowerCase(lang)
              .includes(needle),
          )
        : demoMeetings;
      const nextPage = page + 1;
      setItems(filtered.slice(0, nextPage * PAGE_SIZE));
      setPage(nextPage);
      setHasMore(filtered.length > nextPage * PAGE_SIZE);
      return;
    }

    const generation = generationRef.current;
    setLoadingMore(true);
    setError(null);
    try {
      const response = await searchMeetingArchive(query, page + 1, PAGE_SIZE);
      if (generation !== generationRef.current) return;
      setItems((current) => {
        const known = new Set(current.map((meeting) => meeting.id));
        return [...current, ...response.items.filter((meeting) => !known.has(meeting.id))];
      });
      setTotal(response.total);
      setPage(response.page);
      setHasMore(response.has_more);
    } catch (err) {
      if (generation === generationRef.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (generation === generationRef.current) setLoadingMore(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" dataTour="dashboard-search-dialog-content" className="max-h-[78vh]">
        <DialogHeader
          title={lang === 'it' ? 'Cerca in tutti i meeting' : 'Search all meetings'}
          description={
            lang === 'it'
              ? 'Titolo, progetto, trascrizione e note. La ricerca resta locale sul Mac.'
              : 'Title, project, transcript and notes. Search stays local on your Mac.'
          }
        />
        <div className="flex items-center gap-3 border-b border-border-subtle bg-bg-elevated px-4 py-3 pr-12">
          <Search className="h-5 w-5 shrink-0 text-text-muted" aria-hidden="true" />
          <label htmlFor="dashboard-meeting-search" className="sr-only">
            {lang === 'it' ? 'Cerca meeting' : 'Search meetings'}
          </label>
          <input
            id="dashboard-meeting-search"
            autoFocus
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={lang === 'it' ? 'Cerca meeting…' : 'Search meetings…'}
            className="w-full bg-transparent text-base text-text-primary outline-none placeholder:text-text-muted"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label={lang === 'it' ? 'Azzera ricerca' : 'Clear search'}
              className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
        <DialogBody noScroll className="max-h-[58vh] overflow-y-auto p-2">
          <div aria-live="polite" className="sr-only">
            {loading
              ? (lang === 'it' ? 'Ricerca in corso' : 'Searching')
              : `${total} ${lang === 'it' ? 'risultati' : 'results'}`}
          </div>

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-text-muted">
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              {lang === 'it' ? 'Ricerca nell’archivio locale…' : 'Searching the local archive…'}
            </div>
          ) : error ? (
            <div className="mx-2 my-4 rounded-xl border border-danger/30 bg-danger/5 p-4 text-sm text-text-secondary">
              <p className="font-semibold text-text-primary">
                {lang === 'it' ? 'Ricerca non disponibile' : 'Search unavailable'}
              </p>
              <p className="mt-1 text-xs text-text-muted">{error}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="py-8 text-center text-sm text-text-muted">
              {lang === 'it' ? 'Nessun meeting trovato' : 'No meetings found'}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <div className="px-3 py-1.5 text-xs font-semibold uppercase text-text-muted">
                {lang === 'it' ? 'Risultati' : 'Results'} ({total})
              </div>
              {items.map((meeting) => (
                <button
                  key={meeting.id}
                  type="button"
                  onClick={() => {
                    onOpenMeeting(meeting.id);
                    onOpenChange(false);
                  }}
                  className="group flex w-full items-center justify-between rounded-xl border border-transparent p-3 text-left transition-colors hover:border-border-focus hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-text-primary transition-colors group-hover:text-accent">
                      {meetingTitle(meeting)}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-text-muted">
                      {meeting.project_name || (lang === 'it' ? 'Nessun progetto' : 'No project')}
                    </div>
                  </div>
                  <div className="ml-4 flex shrink-0 items-center gap-2 text-xs text-text-muted">
                    <span>{new Date(meeting.created_at).toLocaleDateString(lang)}</span>
                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  </div>
                </button>
              ))}
              {hasMore && (
                <div className="flex justify-center p-3">
                  <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
                    {lang === 'it' ? 'Mostra altri' : 'Load more'}
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
