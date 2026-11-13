import { FolderKanban, Search } from 'lucide-react';
import { MeetingArchiveExplorer } from '../components/workspace/MeetingSearchDialog';
import { getDemoMeetings } from '../features/demo/demoData';
import { useTranslation } from '../i18n/i18n';

interface MeetingsPageProps {
  navigateTo: (page: string, detail?: string | null) => void;
  demoMode?: boolean;
}

/** Full meeting library: same local paged search used by Cmd+K, not a second archive owner. */
export default function MeetingsPage({ navigateTo, demoMode = false }: MeetingsPageProps) {
  const { t, lang } = useTranslation();
  return (
    <div className="mx-auto w-full max-w-5xl space-y-5" data-meetings-page="true">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold text-text-primary">
              <FolderKanban className="h-5 w-5 text-accent" aria-hidden="true" />
              {t('nav.meetings')}
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              {lang === 'it'
                ? 'Trova e riapri qualsiasi meeting, con ricerca locale e archivio.'
                : 'Find and reopen any meeting with local search and archive.'}
            </p>
          </div>
          <span className="inline-flex items-center gap-2 text-xs text-text-muted">
            <Search className="h-4 w-4" aria-hidden="true" />
            {lang === 'it' ? 'Ricerca sul dispositivo' : 'On-device search'}
          </span>
        </div>
        <nav aria-label={t('nav.meetings')} className="flex items-center gap-2" data-meetings-view-tabs="true">
          <button
            type="button"
            onClick={() => navigateTo('home')}
            className="rounded-lg border border-border-subtle px-3 py-2 text-xs font-semibold text-text-secondary hover:bg-bg-hover"
          >
            {t('nav.home')}
          </button>
          <span aria-current="page" className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs font-semibold text-text-primary">
            {lang === 'it' ? 'Tutte' : 'All meetings'}
          </span>
        </nav>
      </header>
      <section className="surface-primary overflow-hidden rounded-2xl border border-border-subtle" aria-label={t('nav.meetings')}>
        <MeetingArchiveExplorer
          fullPage
          open
          lang={lang}
          onOpenMeeting={(id) => navigateTo('meeting', id)}
          demoMeetings={demoMode ? getDemoMeetings(lang) : undefined}
        />
      </section>
    </div>
  );
}
