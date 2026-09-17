import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from 'react';
import {
  BarChart3,
  ChevronDown,
  FolderKanban,
  Languages,
  Mic,
  Moon,
  Palette,
  PlayCircle,
  Settings,
  Sparkles,
  Sun,
} from 'lucide-react';
import { I18nProvider, useTranslation } from './i18n/i18n';
import { ToastProvider, useToast } from './context/ToastContext';
import { ApiClient } from './api/apiClient';
import { HEALTH_CHECK_INTERVAL_MS } from './api/config';
import DashboardPage from './pages/DashboardPage';
import NewRecordingPage from './pages/NewRecordingPage';
import RecordingPage from './pages/RecordingPage';
import TranscriptionPage from './pages/TranscriptionPage';
import ProjectsPage from './pages/ProjectsPage';
import AnalysisPage from './pages/AnalysisPage';
import SettingsPage from './pages/SettingsPage';
import RecordingOverlayPage from './pages/RecordingOverlayPage';
import MeetingDetailPage from './pages/MeetingDetailPage';
import { Badge } from './components/ui/Badge';
import { Button } from './components/ui/Button';
import { DemoBanner } from './components/ui/DemoBanner';
import { TourOverlay } from './features/tour/TourOverlay';
import { TourRecordingMock } from './features/tour/TourRecordingMock';
import { TOUR_STEPS, TourStepId, tourStepIndex } from './features/tour/tourSteps';
import './workspace.css';

function MainApp() {
  const { t, lang, setLang } = useTranslation();
  const { showToast } = useToast();

  const [activePage, setActivePage] = useState<string>('home');
  const [serverOnline, setServerOnline] = useState(false);
  const [defaultModel, setDefaultModel] = useState('');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [moreOpen, setMoreOpen] = useState(false);
  const [routeDetail, setRouteDetail] = useState<string | null>(null);
  const [tourStep, setTourStep] = useState<TourStepId | null>(null);
  const [tourReturnHash, setTourReturnHash] = useState('');
  const moreTriggerRef = useRef<HTMLButtonElement | null>(null);
  const moreMenuRef = useRef<HTMLDivElement | null>(null);
  const [demoMode, setDemoMode] = useState(() => {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('demo') === 'true' || localStorage.getItem('demoMode') === 'true';
  });
  const isDemoActive = demoMode || Boolean(tourStep);

  const navigateTo = (page: string, detail: string | null = null) => {
    const pageRouteMap: Record<string, string> = {
      home: 'home',
      recording: 'recording',
      transcription: 'transcription',
      projects: 'projects',
      analysis: 'analysis',
      settings: 'settings',
      meeting: 'meeting',
    };
    const route = pageRouteMap[page] || page;
    window.location.hash = detail ? `${route}/${detail}` : route;
    if (tourStep === 'today-to-projects' && route === 'projects') {
      const nextStep = TOUR_STEPS[tourStepIndex(tourStep) + 1];
      if (nextStep?.id === 'project-sidebar') setTourStep(nextStep.id);
    }
  };

  const activateDemo = async () => {
    try {
      await ApiClient.populateMockData(lang);
      setDemoMode(true);
      localStorage.setItem('demoMode', 'true');
      showToast(t('help.mockDataSuccess'), 'success');
      navigateTo('home');
      window.location.reload();
    } catch (err: any) {
      showToast(err.message || 'Error populating mock data', 'error');
    }
  };

  const exitDemo = async () => {
    try {
      await ApiClient.clearMockData();
      setDemoMode(false);
      localStorage.setItem('demoMode', 'false');
      showToast(t('common.exitDemoSuccess'), 'info');
      navigateTo('home');
      window.location.reload();
    } catch (err: any) {
      showToast(err.message || 'Error clearing mock data', 'error');
    }
  };

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '');
      const parts = hash.split('/');
      const pageName = parts[0];
      const detail = parts.slice(1).join('/');
      const pageMap: Record<string, string> = {
        home: 'home',
        record: 'recording',
        recording: 'recording',
        transcribe: 'transcription',
        transcription: 'transcription',
        projects: 'projects',
        analysis: 'analysis',
        settings: 'settings',
        overlay: 'overlay',
        meeting: 'meeting',
      };
      setActivePage(pageMap[pageName] || 'home');
      setRouteDetail(detail || null);
      setMoreOpen(false);
    };

    window.addEventListener('hashchange', handleHashChange);
    if (!window.location.hash) window.location.hash = '#home';
    else handleHashChange();
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const startTour = () => {
    setTourReturnHash(window.location.hash || '#home');
    const firstStep = TOUR_STEPS[0];
    setTourStep(firstStep.id);
    navigateTo(firstStep.route);
  };

  const advanceTour = () => {
    if (!tourStep) return;
    const nextStep = TOUR_STEPS[tourStepIndex(tourStep) + 1];
    if (!nextStep) return;
    setTourStep(nextStep.id);
    navigateTo(nextStep.route);
  };

  const retreatTour = () => {
    if (!tourStep) return;
    const previousStep = TOUR_STEPS[tourStepIndex(tourStep) - 1];
    if (!previousStep) return;
    setTourStep(previousStep.id);
    navigateTo(previousStep.route);
  };

  const closeTour = () => {
    const returnHash = tourReturnHash;
    setTourStep(null);
    setTourReturnHash('');
    if (returnHash) window.location.hash = returnHash;
  };

  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    setTheme(savedTheme as 'dark' | 'light');
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    setTheme(next);
  };

  useEffect(() => {
    const checkHealth = async () => {
      if (isDemoActive) return;
      try {
        const data = await ApiClient.health();
        setServerOnline(true);
        setDefaultModel(data.default_model.split('/').pop() || '');
      } catch {
        setServerOnline(false);
      }
    };

    void checkHealth();
    const interval = setInterval(checkHealth, HEALTH_CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [isDemoActive]);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.more-menu-container')) setMoreOpen(false);
    };
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  useEffect(() => {
    if (!moreOpen) return;
    const frame = window.requestAnimationFrame(() => {
      const selectedLanguage = moreMenuRef.current
        ?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]');
      const firstItem = moreMenuRef.current
        ?.querySelector<HTMLButtonElement>('[role="menuitem"], [role="menuitemradio"]');
      (selectedLanguage || firstItem)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [moreOpen]);

  const handleMoreMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      moreMenuRef.current?.querySelectorAll<HTMLButtonElement>(
        '[role="menuitem"]:not(:disabled), [role="menuitemradio"]:not(:disabled)',
      ) ?? [],
    );
    if (!items.length) return;

    const currentIndex = Math.max(0, items.indexOf(document.activeElement as HTMLButtonElement));
    let nextIndex = currentIndex;
    if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % items.length;
    else if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + items.length) % items.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = items.length - 1;
    else if (event.key === 'Escape') {
      event.preventDefault();
      setMoreOpen(false);
      moreTriggerRef.current?.focus();
      return;
    } else return;

    event.preventDefault();
    items[nextIndex]?.focus();
  };

  const renderPage = () => {
    switch (activePage) {
      case 'home':
        return (
          <DashboardPage
            navigateTo={navigateTo}
            demoMode={isDemoActive}
            onActivateDemo={!isDemoActive ? activateDemo : undefined}
          />
        );
      case 'meeting':
        return <MeetingDetailPage recordingId={routeDetail} navigateTo={navigateTo} demoMode={isDemoActive} />;
      case 'recording':
        if (isDemoActive) return <TourRecordingMock />;
        return routeDetail
          ? <RecordingPage detailId={routeDetail} navigateTo={navigateTo} />
          : <NewRecordingPage navigateTo={navigateTo} />;
      case 'transcription':
        return <TranscriptionPage detailPath={routeDetail} navigateTo={navigateTo} demoMode={isDemoActive} />;
      case 'projects':
        return <ProjectsPage navigateTo={navigateTo} demoMode={isDemoActive} />;
      case 'analysis':
        return <AnalysisPage detailId={routeDetail} navigateTo={navigateTo} demoMode={isDemoActive} />;
      case 'settings':
        return <SettingsPage />;
      default:
        return (
          <DashboardPage
            navigateTo={navigateTo}
            demoMode={isDemoActive}
            onActivateDemo={!isDemoActive ? activateDemo : undefined}
          />
        );
    }
  };

  if (activePage === 'overlay') return <RecordingOverlayPage />;

  const todayActive = activePage === 'home' || activePage === 'meeting';
  const navItems = [
    { id: 'home', label: t('nav.home'), icon: BarChart3, active: todayActive },
    { id: 'projects', label: t('nav.projects'), icon: FolderKanban, active: activePage === 'projects' },
  ];

  return (
    <div className="app-chrome min-h-screen">
      <div className="workspace-shell">
        <aside className="workspace-rail" aria-label={t('header.subtitle')}>
          <button
            type="button"
            onClick={() => navigateTo('home')}
            className="workspace-brand group"
            aria-label="ClosedRoom"
          >
            <span className="brand-mark brand-mark-compact" aria-hidden="true">
              <span className="brand-mark-halo" />
              <img src="/logo-dark.svg" alt="" className="brand-logo brand-logo-dark" />
              <img src="/logo-light.svg" alt="" className="brand-logo brand-logo-light" />
            </span>
            <span className="workspace-brand-copy">
              <strong>ClosedRoom</strong>
              <span>{t('header.subtitle')}</span>
            </span>
          </button>

          <Button
            data-tour="new-meeting-btn"
            onClick={() => navigateTo('recording')}
            size="md"
            disabled={isDemoActive}
            title={isDemoActive ? t('dashboard.demoReadonlyHint') : t('dashboard.btnRecord')}
            className="workspace-new-meeting"
          >
            <Mic className="h-4 w-4" aria-hidden="true" />
            <span>{t('header.newMeeting')}</span>
          </Button>

          <nav className="workspace-primary-nav" aria-label={t('header.subtitle')}>
            {navItems.map((item) => (
              <button
                key={item.id}
                type="button"
                data-tour={`nav-${item.id}`}
                onClick={() => navigateTo(item.id)}
                className={`workspace-nav-item ${item.active ? 'is-active' : ''}`}
                aria-current={item.active ? 'page' : undefined}
              >
                <item.icon className="h-[18px] w-[18px]" aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          <div className="workspace-rail-spacer" />

          {!isDemoActive && (
            <div className="workspace-runtime-status" title={serverOnline ? `${t('header.statusOnline')} · ${defaultModel}` : t('header.statusOffline')}>
              <Badge variant={serverOnline ? 'online' : 'offline'}>
                {serverOnline ? t('header.statusOnline') : t('header.statusOffline')}
              </Badge>
              {serverOnline && defaultModel && <span className="workspace-runtime-model">{defaultModel}</span>}
            </div>
          )}

          <div className="more-menu-container workspace-utility-wrap">
            <button
              ref={moreTriggerRef}
              type="button"
              onClick={() => setMoreOpen((open) => !open)}
              className={`workspace-nav-item workspace-settings-trigger ${activePage === 'settings' ? 'is-active' : ''}`}
              aria-expanded={moreOpen}
              aria-haspopup="menu"
              aria-controls="app-settings-menu"
            >
              <Settings className="h-[18px] w-[18px]" aria-hidden="true" />
              <span>{t('common.settings')}</span>
              <ChevronDown className="workspace-settings-chevron h-3.5 w-3.5" aria-hidden="true" />
            </button>

            {moreOpen && (
              <div
                id="app-settings-menu"
                ref={moreMenuRef}
                role="menu"
                aria-label={t('common.settings')}
                onKeyDown={handleMoreMenuKeyDown}
                className="ui-overlay-surface workspace-settings-menu"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMoreOpen(false);
                    navigateTo('settings');
                  }}
                  className="workspace-menu-item"
                >
                  <Settings className="h-4 w-4 text-text-muted" aria-hidden="true" />
                  {t('common.settings')}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMoreOpen(false);
                    startTour();
                    showToast(t('tour.started'), 'info');
                  }}
                  className="workspace-menu-item"
                >
                  <PlayCircle className="h-4 w-4 text-text-muted" aria-hidden="true" />
                  {t('help.tour')}
                </button>
                {demoMode ? (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMoreOpen(false);
                      void exitDemo();
                    }}
                    className="workspace-menu-item text-danger"
                  >
                    <Sparkles className="h-4 w-4" aria-hidden="true" />
                    {t('demo.bannerExit')}
                  </button>
                ) : (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMoreOpen(false);
                      void activateDemo();
                    }}
                    className="workspace-menu-item"
                  >
                    <Sparkles className="h-4 w-4 text-text-muted" aria-hidden="true" />
                    {t('help.populateMock')}
                  </button>
                )}

                <hr className="my-1 border-border-subtle" />
                <div className="workspace-menu-group" role="group" aria-label={t('common.language')}>
                  <div className="workspace-menu-label" aria-hidden="true">
                    <Languages className="h-3.5 w-3.5" />
                    {t('common.language')}
                  </div>
                  <div className="grid grid-cols-2 gap-1">
                    {[
                      { id: 'it', label: 'IT' },
                      { id: 'en', label: 'EN' },
                    ].map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={lang === item.id}
                        onClick={() => setLang(item.id as 'it' | 'en')}
                        className={`workspace-language-choice ${lang === item.id ? 'is-active' : ''}`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <button type="button" role="menuitem" onClick={toggleTheme} className="workspace-menu-item justify-between">
                  <span className="inline-flex items-center gap-2">
                    <Palette className="h-4 w-4 text-text-muted" aria-hidden="true" />
                    {t('common.theme')}
                  </span>
                  {theme === 'dark' ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
                </button>
              </div>
            )}
          </div>
        </aside>

        <div className="workspace-stage">
          {isDemoActive && !tourStep && (
            <DemoBanner
              onExitDemo={exitDemo}
              onStartTour={() => {
                startTour();
                showToast(t('tour.started'), 'info');
              }}
            />
          )}

          <main className="workspace-content" data-workspace-page={activePage}>
            {renderPage()}
          </main>

          <footer className="workspace-footer select-none">
            <span dangerouslySetInnerHTML={{ __html: t('common.powerBy') }} />
          </footer>
        </div>
      </div>

      {tourStep && (
        <TourOverlay
          step={TOUR_STEPS[tourStepIndex(tourStep)]}
          onNext={advanceTour}
          onBack={retreatTour}
          onClose={closeTour}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <ToastProvider>
        <MainApp />
      </ToastProvider>
    </I18nProvider>
  );
}
