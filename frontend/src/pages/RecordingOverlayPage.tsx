import { useState, useEffect, useRef, useCallback } from 'react';
import {
  AlertTriangle,
  Camera,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Mic,
  Monitor,
  PencilLine,
  Square,
  Volume2,
  X,
} from 'lucide-react';
import { ApiClient, CaptureDisplay } from '../api/apiClient';
import { useTranslation } from '../i18n/i18n';

export default function RecordingOverlayPage() {
  const { t } = useTranslation();
  const [timer, setTimer] = useState('00:00');
  const [signalLevelMic, setSignalLevelMic] = useState('-∞ dB');
  const [signalLevelSystem, setSignalLevelSystem] = useState('-∞ dB');
  const [isRecording, setIsRecording] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [recordingId, setRecordingId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [captureBackend, setCaptureBackend] = useState<'browser' | 'native'>('browser');
  const [captureMode, setCaptureMode] = useState<string>('both');
  const [visualCaptureLabel, setVisualCaptureLabel] = useState('');
  const [bytesWritten, setBytesWritten] = useState(0);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [displays, setDisplays] = useState<CaptureDisplay[]>([]);
  const [selectedDisplayId, setSelectedDisplayId] = useState<number | null>(null);
  const [screenshotCount, setScreenshotCount] = useState(0);
  const [isCapturingScreenshot, setIsCapturingScreenshot] = useState(false);
  const [lastScreenshotAt, setLastScreenshotAt] = useState<number | null>(null);
  const [isDisplayPickerOpen, setIsDisplayPickerOpen] = useState(false);
  const [pendingDisplayId, setPendingDisplayId] = useState<number | null>(null);
  const [isSelectingDisplay, setIsSelectingDisplay] = useState(false);
  const [screenshotFeedback, setScreenshotFeedback] = useState<'idle' | 'saved'>('idle');
  const [lastSavedScreenshotId, setLastSavedScreenshotId] = useState<string | null>(null);
  const [isUndoingScreenshot, setIsUndoingScreenshot] = useState(false);
  const [noteCount, setNoteCount] = useState(0);
  const [noteComposerOpen, setNoteComposerOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState('');
  const [noteAnchor, setNoteAnchor] = useState<number | null>(null);
  const [isAnchoringNote, setIsAnchoringNote] = useState(false);
  const [isSavingNote, setIsSavingNote] = useState(false);
  const [isUndoingNote, setIsUndoingNote] = useState(false);
  const [noteFeedback, setNoteFeedback] = useState<'idle' | 'saved'>('idle');
  const [lastSavedNoteId, setLastSavedNoteId] = useState<string | null>(null);

  const logOverlay = useCallback((level: 'info' | 'warn' | 'error', message: string, data?: any) => {
    console[level === 'warn' ? 'warn' : level === 'error' ? 'error' : 'log'](`[Overlay] ${message}`, data || '');
    ApiClient.logClientEvent(level, 'overlay', message, data).catch(() => {});
  }, []);

  useEffect(() => {
    logOverlay('info', 'Overlay view mounted', {
      hash: window.location.hash,
      name: window.name,
    });
  }, [logOverlay]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = 'ClosedRoom Recording Overlay';
    return () => {
      document.title = previousTitle;
    };
  }, []);

  // Dynamic body class for transparency
  useEffect(() => {
    document.documentElement.classList.add('overlay-active');
    document.body.classList.add('overlay-active');
    return () => {
      document.documentElement.classList.remove('overlay-active');
      document.body.classList.remove('overlay-active');
    };
  }, []);

  const displaySignalLevel = (dbStr: string) => {
    if (dbStr === '-∞ dB' || dbStr === '-inf dB') {
      return t('recording.waitingForSignal') || 'In attesa...';
    }
    return dbStr;
  };

  const eventSourceRef = useRef<EventSource | null>(null);
  const timerIntervalRef = useRef<any>(null);
  const startedAtRef = useRef<number | null>(null);
  const selectedDisplayIdRef = useRef<number | null>(null);
  const pendingDisplayIdRef = useRef<number | null>(null);
  const displayPickerRef = useRef<HTMLDivElement | null>(null);
  const noteInputRef = useRef<HTMLTextAreaElement | null>(null);
  const screenshotFeedbackTimerRef = useRef<number | null>(null);
  const noteFeedbackTimerRef = useRef<number | null>(null);

  useEffect(() => {
    selectedDisplayIdRef.current = selectedDisplayId;
  }, [selectedDisplayId]);

  // Formatter helpers
  const formatBytes = (bytes: number) => {
    if (bytes <= 0) return '0 KB';
    if (bytes > 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
    return `${Math.round(bytes / 1024)} KB`;
  };

  const formatDb = (db: number) => {
    return db <= -47.5 ? '-∞ dB' : `${db.toFixed(1)} dB`;
  };

  const recordingStartedAtMs = (value: number | string | undefined) => {
    if (typeof value === 'number') return value > 10_000_000_000 ? value : value * 1000;
    if (typeof value === 'string') {
      const parsed = Date.parse(value);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  };

  const loadDisplays = useCallback(async (
    preferredDisplayId?: number | null,
    _autoSelectSingle = true,
  ) => {
    try {
      const payload = await ApiClient.captureDisplays();
      const available = payload.displays || [];
      setDisplays(available);

      let storedId: number | null = null;
      try {
        const stored = localStorage.getItem('asr-overlay-preferred-display-id');
        storedId = stored ? parseInt(stored, 10) : null;
      } catch {}

      const preferred = preferredDisplayId !== undefined
        ? preferredDisplayId
        : (selectedDisplayIdRef.current ?? (storedId && available.some(d => d.display_id === storedId) ? storedId : null));

      if (preferred && available.some((display) => display.display_id === preferred)) {
        selectedDisplayIdRef.current = preferred;
        setSelectedDisplayId(preferred);
      } else if (available.length > 0) {
        selectedDisplayIdRef.current = available[0].display_id;
        setSelectedDisplayId(available[0].display_id);
      } else {
        selectedDisplayIdRef.current = null;
        setSelectedDisplayId(null);
      }
    } catch (err) {
      console.warn('Unable to load screenshot displays:', err);
      setDisplays([]);
      setSelectedDisplayId(null);
    }
  }, []);

  const connectSSE = useCallback((recId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    
    const sse = new EventSource(`/v1/recordings/${recId}/overlay/events`);
    eventSourceRef.current = sse;

    sse.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (!data.active) {
          setIsRecording(false);
          setIsStopping(false);
          setRecordingId(null);
          setScreenshotCount(0);
          setNoteCount(0);
          setNoteComposerOpen(false);
          setNoteDraft('');
          setNoteAnchor(null);
          setLastScreenshotAt(null);
          setLastSavedScreenshotId(null);
          if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
          setTimer('00:00');
          sse.close();
          eventSourceRef.current = null;
          
          if (window.name === 'ClosedRoomOverlay') {
            setTimeout(() => window.close(), 1000);
          }
          return;
        }

        setIsRecording(true);
        setBytesWritten(data.bytes_written || 0);
        setSignalLevelMic(formatDb(data.mic_db));
        setSignalLevelSystem(formatDb(data.system_db));
        setWarnings(data.warnings || []);
        setScreenshotCount(data.screenshot_count || 0);
        setNoteCount(data.note_count || 0);
        const backendDisplayId = data.screenshot_display_id ? Number(data.screenshot_display_id) : null;
        const pendingSelection = pendingDisplayIdRef.current;
        if (
          backendDisplayId !== null
          && (pendingSelection === null || backendDisplayId === pendingSelection)
        ) {
          selectedDisplayIdRef.current = backendDisplayId;
          setSelectedDisplayId(backendDisplayId);
          if (pendingSelection === backendDisplayId) {
            pendingDisplayIdRef.current = null;
            setPendingDisplayId(null);
          }
        }

        if (data.started_at && !startedAtRef.current) {
          startedAtRef.current = recordingStartedAtMs(data.started_at);
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    sse.onerror = (err) => {
      console.warn('SSE event stream error, falling back:', err);
      sse.close();
      eventSourceRef.current = null;
    };
  }, []);

  const checkActiveRecording = useCallback(async () => {
    try {
      const activeData = await ApiClient.getActiveRecording();
      logOverlay('info', 'Checked active recording from backend', {
        active: activeData.active,
        recordingId: activeData.recording_id,
        captureBackend: activeData.capture_backend,
        screenshotCount: activeData.screenshot_count,
        noteCount: activeData.note_count,
        selectedDisplayId: activeData.screenshot_display_id,
      });
      if (activeData.active && activeData.recording_id) {
        setRecordingId(activeData.recording_id);
        setIsRecording(true);
        setTitle(activeData.title || 'Registrazione');
        setCaptureBackend(activeData.capture_backend || 'browser');
        setCaptureMode(activeData.capture_mode || 'both');
        setBytesWritten(activeData.bytes_written || 0);
        setWarnings(activeData.warnings || []);
        setScreenshotCount(activeData.screenshot_count || 0);
        setNoteCount(activeData.note_count || 0);
        const backendDisplayId = activeData.screenshot_display_id ?? null;
        const pendingSelection = pendingDisplayIdRef.current;
        if (
          backendDisplayId !== null
          && (pendingSelection === null || backendDisplayId === pendingSelection)
        ) {
          selectedDisplayIdRef.current = backendDisplayId;
          setSelectedDisplayId(backendDisplayId);
          if (pendingSelection === backendDisplayId) {
            pendingDisplayIdRef.current = null;
            setPendingDisplayId(null);
          }
        }
        if ((activeData.capture_backend || 'browser') === 'native') {
          const preferredDisplayId = pendingSelection ?? backendDisplayId ?? selectedDisplayIdRef.current;
          void loadDisplays(preferredDisplayId ?? undefined);
        }
        
        const startedAtMs = recordingStartedAtMs(activeData.started_at);
        if (startedAtMs) {
          startedAtRef.current = startedAtMs;
          if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
          timerIntervalRef.current = setInterval(() => {
            if (startedAtRef.current) {
              const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000);
              const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
              const secs = (elapsed % 60).toString().padStart(2, '0');
              setTimer(`${mins}:${secs}`);
            }
          }, 500);
        }

        connectSSE(activeData.recording_id);
      } else {
        setIsRecording(false);
        setRecordingId(null);
        setScreenshotCount(0);
        setLastScreenshotAt(null);
        setLastSavedScreenshotId(null);
        setTimer('00:00');
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        const bc = new BroadcastChannel('closedroom-recording');
        bc.postMessage({ type: 'request-status' });
        bc.close();
      }
    } catch (err) {
      console.error('Failed to get active recording from backend, falling back to BroadcastChannel:', err);
      const bc = new BroadcastChannel('closedroom-recording');
      bc.postMessage({ type: 'request-status' });
      bc.close();
    }
  }, [connectSSE, loadDisplays, logOverlay]);

  // Poll/Check state on mount and connect SSE/BroadcastChannel
  useEffect(() => {
    const bc = new BroadcastChannel('closedroom-recording');

    const handleBroadcastMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data) return;

      if (data.type === 'status') {
        setIsRecording(data.isRecording);
        setTimer(data.timer);
        setSignalLevelMic(data.signalLevelMic || '-∞ dB');
        setSignalLevelSystem(data.signalLevelSystem || '-∞ dB');
        setVisualCaptureLabel(data.visualCaptureLabel || '');

        if (data.isRecording) {
          if (data.captureBackend) {
            setCaptureBackend(data.captureBackend);
          }
          if (data.recordingId) {
            setRecordingId((prevId) => {
              if (prevId !== data.recordingId) {
                setScreenshotCount(0);
                setLastScreenshotAt(null);
                setLastSavedScreenshotId(null);
                setErrorMsg(null);
                connectSSE(data.recordingId);
                if (data.captureBackend === 'native') {
                  void loadDisplays();
                }
              }
              return data.recordingId;
            });
          } else {
            void checkActiveRecording();
          }
        } else {
          setRecordingId(null);
          setScreenshotCount(0);
          setLastScreenshotAt(null);
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
          }
          if (window.name === 'ClosedRoomOverlay') {
            setTimeout(() => {
              window.close();
            }, 1500);
          }
        }
      } else if (data.type === 'ack' && data.action === 'stop') {
        void ApiClient.getActiveRecording()
          .then((active) => {
            if (!active.active) setIsStopping(false);
          })
          .catch(() => {});
      }
    };

    const handleOverlayShown = () => {
      logOverlay('info', 'overlay-shown event fired');
      void checkActiveRecording();
    };

    bc.addEventListener('message', handleBroadcastMessage);
    window.addEventListener('overlay-shown', handleOverlayShown);

    void checkActiveRecording();

    return () => {
      bc.removeEventListener('message', handleBroadcastMessage);
      window.removeEventListener('overlay-shown', handleOverlayShown);
      bc.close();
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
      if (screenshotFeedbackTimerRef.current) window.clearTimeout(screenshotFeedbackTimerRef.current);
      if (noteFeedbackTimerRef.current) window.clearTimeout(noteFeedbackTimerRef.current);
    };
  }, [checkActiveRecording, connectSSE, loadDisplays]);

  const handleStop = async () => {
    setIsStopping(true);
    setErrorMsg(null);

    // 1. Post command via BroadcastChannel (for browser UI fallback)
    const bc = new BroadcastChannel('closedroom-recording');
    bc.postMessage({ type: 'command', action: 'stop' });
    bc.close();

    // 2. Call direct backend endpoint
    if (recordingId) {
      try {
        await ApiClient.stopRecordingControl(recordingId);
        setIsRecording(false);
        setIsStopping(false);
        const opened = await ApiClient.openMeetingWindow(recordingId);
        if (!opened.success && window.opener) {
          window.opener.location.hash = `#meeting/${recordingId}`;
          window.opener.focus();
        } else if (!opened.success) {
          window.location.hash = `#meeting/${recordingId}`;
        }
      } catch (err: any) {
        console.error('Stop control endpoint failed:', err);
        // Fallback: wait for BroadcastChannel timeout
        setTimeout(() => {
          setIsStopping((stillStopping) => {
            if (stillStopping) {
              setErrorMsg(t('recording.stopBackendTimeout'));
              return false;
            }
            return stillStopping;
          });
        }, 2500);
      }
    } else {
      // If no recording ID found on backend, wait 1.5s for browser ACK
      setTimeout(() => {
        setIsStopping((stillStopping) => {
          if (stillStopping) {
            setErrorMsg(t('recording.browserStopUnconfirmed'));
            return false;
          }
          return stillStopping;
        });
      }, 1500);
    }
  };

  const handleCaptureScreenshot = async () => {
    logOverlay('info', 'Screenshot action invoked (button click or ⌘⇧9)', {
      recordingId,
      captureBackend,
      isRecording,
      isStopping,
      isCapturingScreenshot,
      selectedDisplayId,
      displayCount: displays.length,
    });

    if (isStopping) {
      logOverlay('warn', 'Screenshot ignored: recording is stopping');
      return;
    }
    if (isCapturingScreenshot) {
      logOverlay('warn', 'Screenshot ignored: capture already in flight');
      return;
    }
    if (isUndoingScreenshot) {
      logOverlay('warn', 'Screenshot ignored: undo already in flight');
      return;
    }
    if (!isRecording) {
      const msg = 'Nessuna registrazione attiva. Avvia prima una registrazione per scattare screenshot.';
      setErrorMsg(msg);
      logOverlay('warn', 'Screenshot blocked: not currently recording');
      return;
    }
    if (captureBackend !== 'native') {
      const msg = `Screenshot non supportato: backend attivo è "${captureBackend}". Richiede acquisizione nativa.`;
      setErrorMsg(msg);
      logOverlay('warn', 'Screenshot blocked: captureBackend is not native', { captureBackend });
      return;
    }
    if (!recordingId) {
      const msg = 'ID sessione non trovato. Ricontrollo stato registrazione...';
      setErrorMsg(msg);
      logOverlay('warn', 'Screenshot blocked: missing recordingId');
      void checkActiveRecording();
      return;
    }
    let targetDisplayId = selectedDisplayId;
    if (targetDisplayId === null) {
      if (displays.length > 0) {
        targetDisplayId = displays[0].display_id;
        setSelectedDisplayId(targetDisplayId);
      } else {
        const msg = t('recording.screenshotChooseMonitorError') || 'Nessun monitor disponibile per lo screenshot.';
        setErrorMsg(msg);
        logOverlay('warn', 'Screenshot blocked: no displays available');
        return;
      }
    }

    setIsCapturingScreenshot(true);
    setErrorMsg(null);
    const requestId = `overlay-${recordingId}-${crypto.randomUUID()}`;
    logOverlay('info', 'Sending captureScreenshot API request', { recordingId, requestId, selectedDisplayId: targetDisplayId });
    try {
      const saved = await ApiClient.captureScreenshot(
        recordingId,
        requestId,
        targetDisplayId,
      );
      const nextSeq = typeof saved.sequence === 'number' ? saved.sequence + 1 : screenshotCount + 1;
      setScreenshotCount(nextSeq);
      if (typeof saved.timestamp === 'number') {
        setLastScreenshotAt(saved.timestamp);
      }
      if (saved.display_id) {
        selectedDisplayIdRef.current = saved.display_id;
        setSelectedDisplayId(saved.display_id);
      }
      setScreenshotFeedback('saved');
      setLastSavedScreenshotId(saved.screenshot_id);
      if (screenshotFeedbackTimerRef.current) window.clearTimeout(screenshotFeedbackTimerRef.current);
      screenshotFeedbackTimerRef.current = window.setTimeout(() => {
        setScreenshotFeedback('idle');
        setLastSavedScreenshotId(null);
      }, 4500);
      logOverlay('info', 'Screenshot captured and stored successfully', {
        screenshot_id: saved.screenshot_id,
        sequence: saved.sequence,
        timestamp: saved.timestamp,
        displayId: saved.display_id,
      });
    } catch (err: any) {
      const message = String(err?.message || t('recording.screenshotFailed'));
      logOverlay('error', 'Screenshot capture failed with error', { error: message });
      if (message.includes('selected_display_unavailable')) {
        setErrorMsg(t('recording.screenshotDisplayUnavailable'));
        await loadDisplays(undefined, false);
        setIsDisplayPickerOpen(true);
        void resizeOverlayForState(isExpanded, true);
      } else if (message.includes('display_selection_required')) {
        setErrorMsg(t('recording.screenshotChooseMonitorError'));
        await loadDisplays(undefined, false);
        setIsDisplayPickerOpen(true);
        void resizeOverlayForState(isExpanded, true);
      } else {
        setErrorMsg(message);
      }
    } finally {
      setIsCapturingScreenshot(false);
    }
  };

  const handleUndoScreenshot = async () => {
    if (!recordingId || !lastSavedScreenshotId || isUndoingScreenshot || isStopping) return;
    setIsUndoingScreenshot(true);
    setErrorMsg(null);
    try {
      await ApiClient.deleteScreenshot(recordingId, lastSavedScreenshotId);
      setLastSavedScreenshotId(null);
      setScreenshotFeedback('idle');
      setScreenshotCount((current) => Math.max(0, current - 1));
      setLastScreenshotAt(null);
      if (screenshotFeedbackTimerRef.current) {
        window.clearTimeout(screenshotFeedbackTimerRef.current);
        screenshotFeedbackTimerRef.current = null;
      }
      logOverlay('info', 'Last screenshot removed with undo', { recordingId });

      try {
        const remaining = await ApiClient.recordingScreenshots(recordingId);
        setScreenshotCount(remaining.total || 0);
        const latest = remaining.items?.[remaining.items.length - 1];
        setLastScreenshotAt(typeof latest?.timestamp === 'number' ? latest.timestamp : null);
      } catch (refreshErr: any) {
        logOverlay('warn', 'Screenshot undo committed but list refresh failed', {
          recordingId,
          error: String(refreshErr?.message || refreshErr),
        });
      }
    } catch (err: any) {
      const message = String(err?.message || (t('recording.screenshotFailed') || 'Unable to remove screenshot.'));
      setErrorMsg(message);
      logOverlay('error', 'Screenshot undo failed', { recordingId, error: message });
    } finally {
      setIsUndoingScreenshot(false);
    }
  };

  const closeNoteComposer = useCallback(() => {
    setNoteComposerOpen(false);
    setNoteDraft('');
    setNoteAnchor(null);
  }, []);

  const handleOpenNote = async () => {
    if (!recordingId || !isRecording || isStopping || isAnchoringNote || isSavingNote) return;
    setIsAnchoringNote(true);
    setErrorMsg(null);
    try {
      const anchor = await ApiClient.recordingNoteAnchor(recordingId);
      setNoteAnchor(anchor.timestamp);
      setNoteComposerOpen(true);
      setIsDisplayPickerOpen(false);
      window.requestAnimationFrame(() => noteInputRef.current?.focus());
    } catch (err: any) {
      const message = String(err?.message || 'Could not start a note for this moment.');
      setErrorMsg(message);
      logOverlay('error', 'Note anchor failed', { recordingId, error: message });
    } finally {
      setIsAnchoringNote(false);
    }
  };

  const handleSaveNote = async () => {
    if (!recordingId || noteAnchor === null || isSavingNote || isStopping) return;
    const text = noteDraft.trim();
    if (!text) return;
    setIsSavingNote(true);
    setErrorMsg(null);
    try {
      const saved = await ApiClient.createRecordingNote(recordingId, {
        request_id: `overlay-note-${recordingId}-${crypto.randomUUID()}`,
        timestamp: noteAnchor,
        text,
      });
      setNoteCount((current) => Math.max(current + 1, saved.sequence + 1));
      setLastSavedNoteId(saved.note_id);
      setNoteFeedback('saved');
      closeNoteComposer();
      if (noteFeedbackTimerRef.current) window.clearTimeout(noteFeedbackTimerRef.current);
      noteFeedbackTimerRef.current = window.setTimeout(() => {
        setNoteFeedback('idle');
        setLastSavedNoteId(null);
      }, 4500);
      logOverlay('info', 'User note committed', {
        note_id: saved.note_id,
        timestamp: saved.timestamp,
        sequence: saved.sequence,
      });
    } catch (err: any) {
      const message = String(err?.message || 'Unable to save note.');
      setErrorMsg(message);
      logOverlay('error', 'User note save failed', { recordingId, error: message });
    } finally {
      setIsSavingNote(false);
    }
  };

  const handleUndoNote = async () => {
    if (!recordingId || !lastSavedNoteId || isUndoingNote || isStopping) return;
    setIsUndoingNote(true);
    setErrorMsg(null);
    try {
      await ApiClient.deleteRecordingNote(recordingId, lastSavedNoteId);
      setNoteCount((current) => Math.max(0, current - 1));
      setLastSavedNoteId(null);
      setNoteFeedback('idle');
      if (noteFeedbackTimerRef.current) {
        window.clearTimeout(noteFeedbackTimerRef.current);
        noteFeedbackTimerRef.current = null;
      }
    } catch (err: any) {
      const message = String(err?.message || 'Unable to undo note.');
      setErrorMsg(message);
    } finally {
      setIsUndoingNote(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey && event.shiftKey && event.key === '9') {
        event.preventDefault();
        void handleCaptureScreenshot();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  const resizeOverlayForState = useCallback(async (
    expanded: boolean,
    displayPickerOpen: boolean,
    noteOpen = false,
  ) => {
    const width = 420;
    const height = displayPickerOpen ? 300 : noteOpen ? (expanded ? 330 : 222) : expanded ? 238 : 118;
    if (window.name === 'ClosedRoomOverlay') {
      window.resizeTo(width, height + 52);
      return;
    }
    try {
      await ApiClient.resizeOverlay(width, height);
    } catch (err) {
      console.warn('Resize overlay window failed:', err);
    }
  }, []);

  const handleSelectDisplay = async (displayId: number) => {
    if (!recordingId || captureBackend !== 'native') return;

    const previousDisplayId = selectedDisplayIdRef.current;
    pendingDisplayIdRef.current = displayId;
    setPendingDisplayId(displayId);
    selectedDisplayIdRef.current = displayId;
    setSelectedDisplayId(displayId);
    setIsSelectingDisplay(true);
    setErrorMsg(null);

    try {
      const result = await ApiClient.selectScreenshotDisplay(recordingId, displayId);
      selectedDisplayIdRef.current = result.display_id;
      setSelectedDisplayId(result.display_id);
      pendingDisplayIdRef.current = null;
      setPendingDisplayId(null);
      try {
        localStorage.setItem('asr-overlay-preferred-display-id', String(result.display_id));
      } catch {}
      logOverlay('info', 'Screenshot display changed', {
        recordingId,
        displayId: result.display_id,
      });
      setIsDisplayPickerOpen(false);
      await resizeOverlayForState(isExpanded, false);
    } catch (err: any) {
      pendingDisplayIdRef.current = null;
      setPendingDisplayId(null);
      selectedDisplayIdRef.current = previousDisplayId;
      setSelectedDisplayId(previousDisplayId);
      const message = String(err?.message || t('recording.screenshotDisplayUnavailable'));
      setErrorMsg(message);
      logOverlay('error', 'Screenshot display change failed', {
        recordingId,
        requestedDisplayId: displayId,
        error: message,
      });
    } finally {
      setIsSelectingDisplay(false);
    }
  };

  const toggleDisplayPicker = async () => {
    if (!isRecording || captureBackend !== 'native') return;
    if (displays.length === 0) {
      await loadDisplays();
    }
    const next = !isDisplayPickerOpen;
    setIsDisplayPickerOpen(next);
    await resizeOverlayForState(isExpanded, next);
  };

  const handleCloseOverlay = async () => {
    if (window.name === 'ClosedRoomOverlay') {
      window.close();
    } else {
      await ApiClient.toggleOverlay(false);
    }
  };

  const toggleExpand = async () => {
    const nextState = !isExpanded;
    setIsExpanded(nextState);
    setIsDisplayPickerOpen(false);
    await resizeOverlayForState(nextState, false);
  };

  useEffect(() => {
    void resizeOverlayForState(isExpanded, isDisplayPickerOpen, noteComposerOpen);
  }, [isDisplayPickerOpen, isExpanded, noteComposerOpen, resizeOverlayForState]);

  useEffect(() => {
    if (!isDisplayPickerOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (displayPickerRef.current && !displayPickerRef.current.contains(target)) {
        setIsDisplayPickerOpen(false);
        void resizeOverlayForState(isExpanded, false);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [isDisplayPickerOpen, isExpanded, resizeOverlayForState]);

  const getDeviceHealth = (dbStr: string) => {
    const val = parseFloat(dbStr.replace(' dB', ''));
    if (isNaN(val) || val <= -100) {
      return {
        label: t('recording.healthAbsent') || 'Unavailable',
        dot: 'bg-red-400',
        text: 'text-red-200',
      };
    }
    if (val <= -45) {
      return {
        label: t('recording.healthSilent') || 'Quiet',
        dot: 'bg-amber-400',
        text: 'text-amber-200',
      };
    }
    return {
      label: t('recording.healthActive') || 'Active',
      dot: 'bg-emerald-400',
      text: 'text-emerald-200',
    };
  };

  const displayName = (display: CaptureDisplay, index: number) => {
    const title = String(display.title || '').trim();
    const looksGeneric = /^(screen|display)\s+\d+$/i.test(title);
    if (title && !looksGeneric) return title;
    if (display.is_main) return 'Main display';
    const externalIndex = displays
      .slice(0, index + 1)
      .filter((item) => !item.is_main).length;
    return display.is_main ? 'Main display' : `External display ${Math.max(1, externalIndex)}`;
  };

  const selectedDisplayIndex = displays.findIndex(
    (display) => display.display_id === selectedDisplayId,
  );
  const selectedDisplay = selectedDisplayIndex >= 0 ? displays[selectedDisplayIndex] : null;
  const selectedDisplayName = selectedDisplay
    ? displayName(selectedDisplay, selectedDisplayIndex)
    : (displays.length > 0 ? 'Choose screen' : 'Screen unavailable');

  const micHealth = getDeviceHealth(signalLevelMic);
  const systemHealth = getDeviceHealth(signalLevelSystem);

  return (
    <div
      className="overlay-shell relative flex select-none flex-col p-2.5"
      data-testid="recording-overlay"
      data-overlay-control-center="true"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${
              isStopping
                ? 'bg-amber-400 animate-pulse'
                : isRecording
                ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.72)]'
                : 'bg-white/30'
            }`}
            aria-hidden="true"
          />
          <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-white/60">
            {isStopping ? 'Finalizing' : isRecording ? 'REC' : 'Ready'}
          </span>
          {isExpanded && (
            <span className="max-w-[150px] truncate text-[10px] text-white/55" title={title}>
              {title || t('recording.noActiveRecording')}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="rounded-md border border-white/10 bg-white/[0.06] px-2 py-0.5 font-mono text-[12px] font-semibold tabular-nums text-white/90">
            {timer}
          </span>
          <button
            type="button"
            onClick={toggleExpand}
            className="flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-white/45 transition hover:border-white/10 hover:bg-white/[0.07] hover:text-white"
            title={isExpanded ? 'Hide details' : 'Details'}
            aria-label={isExpanded ? 'Hide details' : 'Show details'}
            aria-expanded={isExpanded}
          >
            {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={handleCloseOverlay}
            className="flex h-7 w-7 items-center justify-center rounded-md text-white/35 transition hover:bg-white/[0.07] hover:text-white"
            title="Hide overlay"
            aria-label="Hide overlay"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {(errorMsg || warnings.length > 0) && (
        <div
          className={`mt-1.5 flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[9px] ${
            errorMsg
              ? 'border-red-400/25 bg-red-400/10 text-red-100'
              : 'border-amber-300/20 bg-amber-300/10 text-amber-100'
          }`}
        >
          <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">
            {errorMsg || warnings[warnings.length - 1]}
          </span>
          {errorMsg && (
            <button
              type="button"
              onClick={() => setErrorMsg(null)}
              className="shrink-0 text-white/45 hover:text-white"
              aria-label="Dismiss error"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {noteComposerOpen && (
        <div
          className="mt-2 rounded-xl border border-amber-200/20 bg-amber-100/[0.07] p-2"
          data-note-composer="true"
        >
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="font-mono text-[10px] font-semibold tabular-nums text-amber-100/85">
              {noteAnchor === null
                ? '—'
                : `${Math.floor(noteAnchor / 60)}:${String(Math.floor(noteAnchor % 60)).padStart(2, '0')}`}
            </span>
            <span className="text-[9px] text-white/35">Enter to save · Esc to cancel</span>
          </div>
          <textarea
            ref={noteInputRef}
            value={noteDraft}
            maxLength={4000}
            rows={2}
            placeholder="Add a note about this moment…"
            onChange={(event) => setNoteDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                closeNoteComposer();
                return;
              }
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void handleSaveNote();
              }
            }}
            className="w-full resize-none rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 text-[11px] leading-relaxed text-white/90 outline-none placeholder:text-white/30 focus:border-amber-200/35"
            aria-label="Note about this meeting moment"
          />
          {noteDraft.length >= 3600 && (
            <div className="mt-1 text-right text-[8px] text-white/35">{noteDraft.length}/4000</div>
          )}
        </div>
      )}

      <div className="mt-2 flex items-center gap-1.5">
        {captureMode !== 'pc_only' && (
          <div
            className="flex h-9 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2"
            title={`Microphone · ${micHealth.label} · ${displaySignalLevel(signalLevelMic)}`}
          >
            <Mic className="h-3.5 w-3.5 text-white/70" aria-hidden="true" />
            <span className={`h-1.5 w-1.5 rounded-full ${micHealth.dot}`} aria-hidden="true" />
          </div>
        )}

        {captureMode !== 'mic_only' && (
          <div
            className="flex h-9 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2"
            title={`Computer audio · ${systemHealth.label} · ${displaySignalLevel(signalLevelSystem)}`}
          >
            <Volume2 className="h-3.5 w-3.5 text-white/70" aria-hidden="true" />
            <span className={`h-1.5 w-1.5 rounded-full ${systemHealth.dot}`} aria-hidden="true" />
          </div>
        )}

        <div ref={displayPickerRef} className="relative min-w-0 flex-1">
          <button
            type="button"
            onClick={() => void toggleDisplayPicker()}
            disabled={!isRecording || captureBackend !== 'native'}
            className={`flex h-9 w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 text-left transition ${
              isDisplayPickerOpen
                ? 'border-cyan-300/35 bg-cyan-300/10 text-white'
                : 'border-white/10 bg-white/[0.05] text-white/80 hover:bg-white/[0.08]'
            } disabled:cursor-not-allowed disabled:opacity-35`}
            aria-expanded={isDisplayPickerOpen}
            aria-haspopup="listbox"
            data-display-selector="true"
            title="Screen used for the next screenshot"
          >
            <Monitor className="h-3.5 w-3.5 shrink-0 text-cyan-200/85" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate text-[10px] font-medium">
              {selectedDisplayName}
            </span>
            {isSelectingDisplay ? (
              <Loader2 className="h-3 w-3 shrink-0 animate-spin text-white/50" aria-hidden="true" />
            ) : (
              <ChevronDown className={`h-3 w-3 shrink-0 text-white/35 transition-transform ${isDisplayPickerOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
            )}
          </button>

          {isDisplayPickerOpen && (
            <div
              className="absolute left-0 top-11 z-50 w-[268px] overflow-hidden rounded-xl border border-white/12 bg-[#111827]/98 p-1.5 shadow-2xl backdrop-blur-xl"
              role="listbox"
              aria-label="Screen for screenshots"
              data-display-picker="true"
            >
              <div className="px-2 pb-1.5 pt-1">
                <div className="text-[10px] font-semibold text-white/85">Screenshot screen</div>
                <div className="mt-0.5 text-[9px] leading-snug text-white/40">
                  The next screenshots use this display until you change it.
                </div>
              </div>
              <div className="space-y-1">
                {displays.map((display, index) => {
                  const selected = display.display_id === selectedDisplayId;
                  const pending = display.display_id === pendingDisplayId;
                  return (
                    <button
                      key={display.display_id}
                      type="button"
                      onClick={() => void handleSelectDisplay(display.display_id)}
                      disabled={isSelectingDisplay && !pending}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition ${
                        selected
                          ? 'bg-cyan-300/10 text-white'
                          : 'text-white/75 hover:bg-white/[0.06] hover:text-white'
                      } disabled:opacity-40`}
                      role="option"
                      aria-selected={selected}
                    >
                      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md border ${
                        selected ? 'border-cyan-300/30 bg-cyan-300/10' : 'border-white/10 bg-white/[0.04]'
                      }`}>
                        <Monitor className="h-3.5 w-3.5" aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-[10px] font-medium">
                            {displayName(display, index)}
                          </span>
                          {display.is_main && (
                            <span className="rounded bg-white/[0.07] px-1 py-0.5 text-[7px] font-semibold uppercase tracking-wide text-white/45">
                              Main
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 text-[8px] text-white/35">
                          {display.width} × {display.height}
                        </div>
                      </div>
                      {pending ? (
                        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-cyan-200" aria-hidden="true" />
                      ) : selected ? (
                        <Check className="h-3.5 w-3.5 shrink-0 text-cyan-200" aria-hidden="true" />
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className={`flex h-9 shrink-0 overflow-hidden rounded-lg border ${
          noteFeedback === 'saved'
            ? 'border-amber-200/30 bg-amber-200/10'
            : 'border-white/10 bg-white/[0.08]'
        }`}>
          <button
            type="button"
            onClick={() => void handleOpenNote()}
            disabled={isStopping || isAnchoringNote || isSavingNote || isUndoingNote || !isRecording}
            className="flex h-full items-center gap-1.5 px-2.5 text-[10px] font-semibold text-white/90 transition hover:bg-white/[0.05] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-35"
            aria-label="Add note"
            title="Add note about this moment"
            data-note-action="true"
          >
            {isAnchoringNote || isSavingNote ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : noteFeedback === 'saved' ? (
              <Check className="h-3.5 w-3.5 text-amber-100" aria-hidden="true" />
            ) : (
              <PencilLine className="h-3.5 w-3.5 text-amber-100/85" aria-hidden="true" />
            )}
            <span>{noteFeedback === 'saved' ? 'Saved' : noteCount}</span>
          </button>
          {lastSavedNoteId && (
            <button
              type="button"
              onClick={() => void handleUndoNote()}
              disabled={isUndoingNote || isStopping}
              className="flex h-full items-center border-l border-amber-100/15 px-2 text-[9px] font-semibold text-amber-100/75 transition hover:bg-amber-100/10 disabled:opacity-35"
              data-note-undo="true"
            >
              {isUndoingNote ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : 'Undo'}
            </button>
          )}
        </div>

        <div className={`flex h-9 shrink-0 overflow-hidden rounded-lg border ${
          screenshotFeedback === 'saved'
            ? 'border-emerald-300/30 bg-emerald-300/12'
            : 'border-white/10 bg-white/[0.08]'
        }`}>
          <button
            type="button"
            onClick={handleCaptureScreenshot}
            disabled={isStopping || isCapturingScreenshot || isUndoingScreenshot || !isRecording || captureBackend !== 'native' || selectedDisplayId === null}
            className={`flex h-full items-center gap-1.5 px-2.5 text-[10px] font-semibold transition active:scale-[0.97] ${
              screenshotFeedback === 'saved'
                ? 'text-emerald-100'
                : 'text-white/90 hover:bg-white/[0.05]'
            } disabled:cursor-not-allowed disabled:opacity-35`}
            title={selectedDisplayId === null ? 'Choose a screen first' : t('recording.screenshotShortcut')}
            aria-label={t('recording.screenshotAction')}
            data-screenshot-action="true"
          >
            {isCapturingScreenshot ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : screenshotFeedback === 'saved' ? (
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Camera className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            <span>{screenshotFeedback === 'saved' ? 'Saved' : screenshotCount}</span>
          </button>

          {lastSavedScreenshotId && (
            <button
              type="button"
              onClick={() => void handleUndoScreenshot()}
              disabled={isUndoingScreenshot || isStopping}
              className="flex h-full items-center border-l border-emerald-200/20 px-2 text-[9px] font-semibold text-emerald-100/75 transition hover:bg-emerald-200/10 hover:text-emerald-50 disabled:cursor-not-allowed disabled:opacity-35"
              aria-label="Undo last screenshot"
              title="Undo last screenshot"
              data-screenshot-undo="true"
            >
              {isUndoingScreenshot ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : 'Undo'}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={handleStop}
          disabled={isStopping || !isRecording}
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition active:scale-90 ${
            isStopping
              ? 'bg-amber-500/70 text-white'
              : !isRecording
              ? 'bg-white/10 text-white/30'
              : 'bg-red-500 text-white shadow-[0_0_18px_rgba(239,68,68,0.18)] hover:bg-red-400'
          } disabled:cursor-not-allowed`}
          title="Stop recording"
          aria-label="Stop recording"
        >
          {isStopping ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
          )}
        </button>
      </div>

      {isExpanded && (
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 rounded-lg border border-white/[0.07] bg-black/15 px-2.5 py-2 text-[9px] text-white/45">
          <div className="col-span-2 min-w-0">
            <div className="text-[8px] uppercase tracking-[0.14em] text-white/30">Meeting</div>
            <div className="mt-0.5 truncate text-[10px] font-medium text-white/80">
              {title || t('recording.noActiveRecording')}
            </div>
          </div>
          {captureMode !== 'pc_only' && (
            <div>
              <span>Mic </span>
              <span className={micHealth.text}>{micHealth.label}</span>
              <span className="ml-1 font-mono text-white/30">{displaySignalLevel(signalLevelMic)}</span>
            </div>
          )}
          {captureMode !== 'mic_only' && (
            <div>
              <span>Computer </span>
              <span className={systemHealth.text}>{systemHealth.label}</span>
              <span className="ml-1 font-mono text-white/30">{displaySignalLevel(signalLevelSystem)}</span>
            </div>
          )}
          <div>
            Screenshots <span className="font-semibold text-white/75">{screenshotCount}</span>
          </div>
          <div>
            Notes <span className="font-semibold text-white/75">{noteCount}</span>
          </div>
          <div>
            Last <span className="font-mono text-white/65">
              {lastScreenshotAt === null
                ? '—'
                : `${Math.floor(lastScreenshotAt / 60)}:${String(Math.floor(lastScreenshotAt % 60)).padStart(2, '0')}`}
            </span>
          </div>
          <div className="col-span-2 flex items-center justify-between border-t border-white/[0.06] pt-1.5 text-[8px]">
            <span>⌘⇧9 · Screenshot</span>
            <span>{captureBackend} · {formatBytes(bytesWritten)}</span>
          </div>
          {visualCaptureLabel && (
            <div className="col-span-2 truncate rounded bg-cyan-300/8 px-2 py-1 text-cyan-100/75" title={visualCaptureLabel}>
              {t('recording.visualCaptureActive')}: {visualCaptureLabel}
            </div>
          )}
        </div>
      )}
    </div>
  );
}