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
  const [screenshots, setScreenshots] = useState<RecordingScreenshot[]>([]);
  const [screenshotsState, setScreenshotsState] = useState<ScreenshotsState>('idle');
  const [notes, setNotes] = useState<RecordingNote[]>([]);
  const [notesState, setNotesState] = useState<NotesState>('idle');

  const diagnosticsGenerationRef = useRef(0);
  const visualFramesGenerationRef = useRef(0);
  const screenshotsGenerationRef = useRef(0);
  const notesGenerationRef = useRef(0);

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

  const loadScreenshots = useCallback(async () => {
    if (!recordingId || demoMode) return;
    const generation = ++screenshotsGenerationRef.current;
    setScreenshotsState('loading');
    try {
      const payload = await ApiClient.recordingScreenshots(recordingId);
      if (generation !== screenshotsGenerationRef.current) return;
      setScreenshots(payload.items || []);
      setScreenshotsState('ready');
    } catch {
      if (generation !== screenshotsGenerationRef.current) return;
      setScreenshots([]);
      setScreenshotsState('error');
    }
  }, [demoMode, recordingId]);

  const loadNotes = useCallback(async () => {
    if (!recordingId || demoMode) return;
    const generation = ++notesGenerationRef.current;
    setNotesState('loading');
    try {
      const payload = await ApiClient.recordingNotes(recordingId);
      if (generation !== notesGenerationRef.current) return;
      setNotes(payload.items || []);
      setNotesState('ready');
    } catch {
      if (generation !== notesGenerationRef.current) return;
      setNotes([]);
      setNotesState('error');
    }
  }, [demoMode, recordingId]);

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
    screenshotsGenerationRef.current += 1;
    notesGenerationRef.current += 1;
    setDiagnosticReport(null);
    setDiagnosticsLoading(false);
    setDiagnosticsError(null);
    setVisualFrameCount(0);
    setVisualFramesState('idle');
    setVisualFramesError(null);
    setScreenshots([]);
    setScreenshotsState('idle');
    setNotes([]);
    setNotesState('idle');

    return () => {
      diagnosticsGenerationRef.current += 1;
      visualFramesGenerationRef.current += 1;
      screenshotsGenerationRef.current += 1;
      notesGenerationRef.current += 1;
    };
  }, [demoMode, lang, recordingId]);

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
