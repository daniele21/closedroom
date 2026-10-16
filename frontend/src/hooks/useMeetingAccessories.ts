import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, MeetingDiagnostics, RecordingNote, RecordingScreenshot } from '../api/apiClient';

export type VisualFramesState = 'idle' | 'loading' | 'ready' | 'error';
export type ScreenshotsState = 'idle' | 'loading' | 'ready' | 'error';
export type NotesState = 'idle' | 'loading' | 'ready' | 'error';

interface MeetingAccessoriesOptions {
  recordingId: string | null;
  demoMode: boolean;
  lang: string;
}

// Notes and screenshots share the same list-loading contract. Each call owns
// independent data, status and generation so their refreshes cannot race.
function useMeetingItemList<T>(
  recordingId: string | null,
  demoMode: boolean,
  fetchItems: (id: string) => Promise<{ items: T[] }>,
) {
  const [items, setItems] = useState<T[]>([]);
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const generationRef = useRef(0);

  const load = useCallback(async () => {
    if (!recordingId || demoMode) return;
    const generation = ++generationRef.current;
    setState('loading');
    try {
      const payload = await fetchItems(recordingId);
      if (generation !== generationRef.current) return;
      setItems(payload.items || []);
      setState('ready');
    } catch {
      if (generation !== generationRef.current) return;
      setItems([]);
      setState('error');
    }
  }, [demoMode, fetchItems, recordingId]);

  const reset = useCallback(() => {
    generationRef.current += 1;
    setItems([]);
    setState('idle');
  }, []);

  const invalidate = useCallback(() => {
    generationRef.current += 1;
  }, []);

  return { items, state, load, reset, invalidate };
}

export function useMeetingAccessories({
  recordingId,
  demoMode,
  lang,
}: MeetingAccessoriesOptions) {
  const [diagnosticReport, setDiagnosticReport] = useState<MeetingDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [visualFrameCount, setVisualFrameCount] = useState(0);
  const [visualFramesState, setVisualFramesState] = useState<VisualFramesState>('idle');
  const [visualFramesError, setVisualFramesError] = useState<string | null>(null);
  const {
    items: screenshots,
    state: screenshotsState,
    load: loadScreenshots,
    reset: resetScreenshots,
    invalidate: invalidateScreenshots,
  } = useMeetingItemList<RecordingScreenshot>(recordingId, demoMode, ApiClient.recordingScreenshots);
  const {
    items: notes,
    state: notesState,
    load: loadNotes,
    reset: resetNotes,
    invalidate: invalidateNotes,
  } = useMeetingItemList<RecordingNote>(recordingId, demoMode, ApiClient.recordingNotes);

  const diagnosticsGenerationRef = useRef(0);
  const visualFramesGenerationRef = useRef(0);

  const loadDiagnostics = useCallback(async () => {
    if (!recordingId || demoMode) return;
    const generation = ++diagnosticsGenerationRef.current;
    setDiagnosticsLoading(true);
    setDiagnosticsError(null);
    try {
      const report = await ApiClient.getMeetingDiagnostics(recordingId);
      if (generation !== diagnosticsGenerationRef.current) return;
      setDiagnosticReport(report);
    } catch (err: any) {
      if (generation !== diagnosticsGenerationRef.current) return;
      setDiagnosticsError(
        err?.message || (lang === 'it' ? 'Diagnostica dettagliata non disponibile' : 'Detailed diagnostics unavailable'),
      );
    } finally {
      if (generation === diagnosticsGenerationRef.current) {
        setDiagnosticsLoading(false);
      }
    }
  }, [demoMode, lang, recordingId]);

  const loadVisualFrames = useCallback(async () => {
    if (!recordingId || demoMode) return;
    const generation = ++visualFramesGenerationRef.current;
    setVisualFramesState('loading');
    setVisualFramesError(null);
    try {
      const visualFrames = await ApiClient.recordingVisualFrames(recordingId);
      if (generation !== visualFramesGenerationRef.current) return;
      setVisualFrameCount(visualFrames.total || 0);
      setVisualFramesState('ready');
    } catch (err: any) {
      if (generation !== visualFramesGenerationRef.current) return;
      setVisualFramesError(
        err?.message || (lang === 'it' ? 'Contesto schermo non disponibile' : 'Screen context unavailable'),
      );
      setVisualFramesState('error');
    }
  }, [demoMode, lang, recordingId]);

  useEffect(() => {
    diagnosticsGenerationRef.current += 1;
    visualFramesGenerationRef.current += 1;
    setDiagnosticReport(null);
    setDiagnosticsLoading(false);
    setDiagnosticsError(null);
    setVisualFrameCount(0);
    setVisualFramesState('idle');
    setVisualFramesError(null);
    resetScreenshots();
    resetNotes();

    return () => {
      diagnosticsGenerationRef.current += 1;
      visualFramesGenerationRef.current += 1;
      invalidateScreenshots();
      invalidateNotes();
    };
  }, [demoMode, invalidateNotes, invalidateScreenshots, lang, recordingId, resetNotes, resetScreenshots]);

  return {
    diagnosticReport,
    diagnosticsLoading,
    diagnosticsError,
    loadDiagnostics,
    visualFrameCount,
    visualFramesState,
    visualFramesError,
    loadVisualFrames,
    screenshots,
    screenshotsState,
    loadScreenshots,
    notes,
    notesState,
    loadNotes,
  };
}
