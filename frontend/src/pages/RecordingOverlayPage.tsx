import { useState, useEffect, useRef } from 'react';
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

  // Formatter helpers
  const formatBytes = (bytes: number) => {
    if (bytes <= 0) return '0 KB';
    if (bytes > 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
    return `${Math.round(bytes / 1024)} KB`;
  };

  const getPercentage = (dbVal: number) => {
    const minDb = -48;
    const maxDb = 0;
    return Math.min(100, Math.max(0, ((dbVal - minDb) / (maxDb - minDb)) * 100));
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

  const loadDisplays = async (preferredDisplayId?: number | null) => {
    try {
      const payload = await ApiClient.captureDisplays();
      const available = payload.displays || [];
      setDisplays(available);
      const preferred = preferredDisplayId ?? selectedDisplayId;
      if (preferred && available.some((display) => display.display_id === preferred)) {
        setSelectedDisplayId(preferred);
      } else if (available.length === 1) {
        setSelectedDisplayId(available[0].display_id);
      } else {
        setSelectedDisplayId(null);
      }
    } catch (err) {
      console.warn('Unable to load screenshot displays:', err);
      setDisplays([]);
      setSelectedDisplayId(null);
    }
  };

  // Poll/Check state on mount and connect SSE/BroadcastChannel
  useEffect(() => {
    const bc = new BroadcastChannel('closedroom-recording');

    const handleBroadcastMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data) return;

      if (data.type === 'status') {
        // If we get status, update state (useful for browser capture where SSE is not active,
        // or as local fast sync for signal levels)
        setIsRecording(data.isRecording);
        setTimer(data.timer);
        setSignalLevelMic(data.signalLevelMic || '-∞ dB');
        setSignalLevelSystem(data.signalLevelSystem || '-∞ dB');
        setVisualCaptureLabel(data.visualCaptureLabel || '');

        // Auto-close browser popup after a short delay when recording completes
        if (!data.isRecording && window.name === 'ClosedRoomOverlay') {
          setTimeout(() => {
            window.close();
          }, 1500);
        }
      } else if (data.type === 'ack' && data.action === 'stop') {
        // ACK only means the stop command was received. Persisted backend state
        // remains authoritative for completion; do not show a saved state yet.
        void ApiClient.getActiveRecording()
          .then((active) => {
            if (!active.active) setIsStopping(false);
          })
          .catch(() => {});
      }
    };

    bc.addEventListener('message', handleBroadcastMessage);

    // Initial check of active recording via backend
    const checkActiveRecording = async () => {
      try {
        const activeData = await ApiClient.getActiveRecording();
        if (activeData.active && activeData.recording_id) {
          setRecordingId(activeData.recording_id);
          setIsRecording(true);
          setTitle(activeData.title || 'Registrazione');
          setCaptureBackend(activeData.capture_backend || 'browser');
          setCaptureMode(activeData.capture_mode || 'both');
          setBytesWritten(activeData.bytes_written || 0);
          setWarnings(activeData.warnings || []);
          setScreenshotCount(activeData.screenshot_count || 0);
          setSelectedDisplayId(activeData.screenshot_display_id || null);
          if ((activeData.capture_backend || 'browser') === 'native') {
            void loadDisplays(activeData.screenshot_display_id || null);
          }
          
          const startedAtMs = recordingStartedAtMs(activeData.started_at);
          if (startedAtMs) {
            startedAtRef.current = startedAtMs;
            // Setup local smooth timer
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

          // Connect SSE event stream for native capture (or unified active stream)
          connectSSE(activeData.recording_id);
        } else {
          setIsRecording(false);
          setTimer('00:00');
          // Request status via BC in case it's a browser capture and server is out of sync
          bc.postMessage({ type: 'request-status' });
        }
      } catch (err) {
        console.error('Failed to get active recording from backend, falling back to BroadcastChannel:', err);
        bc.postMessage({ type: 'request-status' });
      }
    };

    const connectSSE = (recId: string) => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      
      const sse = new EventSource(`/v1/recordings/${recId}/overlay/events`);
      eventSourceRef.current = sse;

      sse.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (!data.active) {
            setIsRecording(false);
            setIsStopping(false);
            if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
            setTimer('00:00');
            sse.close();
            
            // Auto close if popup window
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
          if (data.screenshot_display_id) setSelectedDisplayId(data.screenshot_display_id);

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
      };
    };

    checkActiveRecording();

    return () => {
      bc.removeEventListener('message', handleBroadcastMessage);
      bc.close();
      if (eventSourceRef.current) eventSourceRef.current.close();
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
    };
  }, []);

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
    if (!recordingId || captureBackend !== 'native' || !isRecording || isStopping || isCapturingScreenshot) return;
    if (displays.length > 1 && selectedDisplayId === null) {
      setErrorMsg(t('recording.screenshotChooseMonitorError'));
      setIsExpanded(true);
      void ApiClient.resizeOverlay(320, 300);
      return;
    }

    setIsCapturingScreenshot(true);
    setErrorMsg(null);
    const requestId = `overlay-${recordingId}-${crypto.randomUUID()}`;
    try {
      const saved = await ApiClient.captureScreenshot(
        recordingId,
        requestId,
        selectedDisplayId ?? undefined,
      );
      setScreenshotCount((count) => Math.max(count + 1, saved.sequence + 1));
      setLastScreenshotAt(saved.timestamp);
      if (saved.display_id) setSelectedDisplayId(saved.display_id);
    } catch (err: any) {
      const message = String(err?.message || t('recording.screenshotFailed'));
      if (message.includes('selected_display_unavailable')) {
        setErrorMsg(t('recording.screenshotDisplayUnavailable'));
        await loadDisplays(null);
        setIsExpanded(true);
        void ApiClient.resizeOverlay(320, 300);
      } else if (message.includes('display_selection_required')) {
        setErrorMsg(t('recording.screenshotChooseMonitorError'));
        await loadDisplays(null);
        setIsExpanded(true);
        void ApiClient.resizeOverlay(320, 300);
      } else {
        setErrorMsg(message);
      }
    } finally {
      setIsCapturingScreenshot(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey && event.shiftKey && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void handleCaptureScreenshot();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

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
    const targetW = nextState ? 320 : 300;
    const targetH = nextState ? 300 : 150;
    
    // Call Native Resize API
    try {
      await ApiClient.resizeOverlay(targetW, targetH);
    } catch (err) {
      console.warn('Resize overlay window failed:', err);
    }
  };

  // Convert dB levels to percentages
  const micVal = parseFloat(signalLevelMic.replace(' dB', ''));
  const sysVal = parseFloat(signalLevelSystem.replace(' dB', ''));
  const micPercentage = getPercentage(isNaN(micVal) ? -120 : micVal);
  const systemPercentage = getPercentage(isNaN(sysVal) ? -120 : sysVal);

  // Device health status check
  const getDeviceHealth = (dbStr: string) => {
    const val = parseFloat(dbStr.replace(' dB', ''));
    if (isNaN(val) || val <= -100) return { label: t('recording.healthAbsent') || 'Assente/Muto', color: 'text-red-400 font-semibold' };
    if (val <= -45) return { label: t('recording.healthSilent') || 'Silente', color: 'text-yellow-400 font-semibold' };
    return { label: t('recording.healthActive') || 'Attivo', color: 'text-green-400 font-semibold' };
  };

  const micHealth = getDeviceHealth(signalLevelMic);
  const systemHealth = getDeviceHealth(signalLevelSystem);

  return (
    <div className="overlay-shell p-3 select-none flex flex-col justify-between" data-testid="recording-overlay">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              isStopping
                ? 'bg-yellow-500 animate-ping'
                : isRecording
                ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)] animate-pulse'
                : 'bg-gray-500'
            }`}
          ></span>
          <span className="text-[10px] uppercase font-bold tracking-wider text-white/60">
            ClosedRoom
          </span>
        </div>
        
        {/* Monospace Timer */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-bold bg-white/5 px-2 py-0.5 rounded border border-white/10 text-white/90">
            {timer}
          </span>
          {/* Toggle Expand/Collapse */}
          <button
            onClick={toggleExpand}
            className="text-[10px] text-white/60 hover:text-white transition-colors cursor-pointer w-5 h-5 flex items-center justify-center bg-white/5 hover:bg-white/10 rounded"
            title={isExpanded ? 'Riduci' : 'Dettagli'}
          >
            {isExpanded ? '▲' : '▼'}
          </button>
        </div>
        
        {/* Close Button */}
        <button
          onClick={handleCloseOverlay}
          className="text-white/40 hover:text-white transition-colors cursor-pointer w-5 h-5 flex items-center justify-center text-[10px] font-bold bg-white/5 hover:bg-white/10 rounded-full"
          title="Nascondi"
        >
          ✕
        </button>
      </div>

      {/* Main content viewport */}
      <div className="flex-1 flex flex-col justify-center my-1.5 overflow-hidden">
        {isExpanded ? (
          // Expanded view
          <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 text-[10px] text-white/70 animate-fadeIn">
            <div className="col-span-2 font-medium truncate text-white border-b border-white/5 pb-1 mb-1">
              🎙️ {title || t('recording.noActiveRecording') || 'Nessuna registrazione attiva'}
            </div>
            <div className="col-span-2 flex items-center gap-2">
              <span className="opacity-50 shrink-0">{t('recording.screenshotMonitor')}:</span>
              {captureBackend === 'native' && displays.length > 0 ? (
                <select
                  value={selectedDisplayId ?? ''}
                  onChange={(event) => setSelectedDisplayId(event.target.value ? Number(event.target.value) : null)}
                  className="min-w-0 flex-1 rounded border border-white/10 bg-black/20 px-1.5 py-1 text-[10px] text-white"
                  aria-label="Monitor per screenshot"
                >
                  {displays.length > 1 && <option value="">{t('recording.screenshotChooseMonitor')}</option>}
                  {displays.map((display) => (
                    <option key={display.display_id} value={display.display_id}>
                      {display.title}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="truncate text-white/80">
                  {captureBackend === 'native' ? t('recording.screenshotNoMonitor') : t('recording.screenshotNativeOnly')}
                </span>
              )}
            </div>
            <div>
              <span className="opacity-50">{t('recording.screenshotCount')}:</span>{' '}
              <span className="font-semibold text-white/90">{screenshotCount}</span>
            </div>
            <div>
              <span className="opacity-50">{t('recording.screenshotLast')}:</span>{' '}
              <span className="font-semibold text-white/90">
                {lastScreenshotAt === null ? '—' : `${Math.floor(lastScreenshotAt / 60)}:${String(Math.floor(lastScreenshotAt % 60)).padStart(2, '0')}`}
              </span>
            </div>
            {visualCaptureLabel && (
              <div
                className="col-span-2 flex items-center gap-1.5 rounded-md border border-cyan-300/25 bg-cyan-300/10 px-2 py-1 text-cyan-100"
                title={visualCaptureLabel}
              >
                <span aria-hidden="true">◉</span>
                <span className="shrink-0 font-semibold">{t('recording.visualCaptureActive')}:</span>
                <span className="truncate">{visualCaptureLabel}</span>
              </div>
            )}
            <div>
              <span className="opacity-50">Backend:</span> <span className="font-semibold text-white/90 capitalize">{captureBackend}</span>
            </div>
            <div>
              <span className="opacity-50">Files:</span> <span className="font-semibold text-white/90">{formatBytes(bytesWritten)}</span>
            </div>
            <div>
              <span className="opacity-50">Mic:</span> <span className={micHealth.color}>{micHealth.label}</span>
            </div>
            <div>
              <span className="opacity-50">System:</span> <span className={systemHealth.color}>{systemHealth.label}</span>
            </div>
            {warnings.length > 0 && (
              <div className="col-span-2 text-yellow-400 truncate text-[9px] mt-0.5">
                ⚠️ {warnings[warnings.length - 1]}
              </div>
            )}
            {errorMsg && (
              <div className="col-span-2 text-red-400 text-[9px] mt-0.5 leading-snug">
                {errorMsg}
              </div>
            )}
          </div>
        ) : (
          // Compact view
          <div className="flex min-w-0 flex-col gap-1 text-[11px] font-medium text-white/80">
            <div className="flex min-w-0 items-center justify-between">
              <span className="truncate pr-2">
                {isStopping
                  ? t('recording.finalizing') || 'Terminazione...'
                  : isRecording
                  ? `${t('recording.statusRecording').replace('...', '')}: ${title || t('recording.noActiveRecording')}`
                  : t('recording.statusReady') || 'In attesa...'}
              </span>
              {errorMsg && <span className="text-red-400 text-[9px] shrink-0 font-semibold">⚠️ Errore</span>}
            </div>
            {visualCaptureLabel && (
              <div
                className="flex min-w-0 items-center gap-1 rounded border border-cyan-300/20 bg-cyan-300/10 px-1.5 py-0.5 text-[9px] text-cyan-100"
                title={visualCaptureLabel}
              >
                <span className="shrink-0" aria-hidden="true">◉</span>
                <span className="shrink-0 font-semibold">{t('recording.visualCaptureActive')}:</span>
                <span className="truncate">{visualCaptureLabel}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bottom Bar: dB Signal Level + Screenshot + Stop */}
      <div className="flex items-center gap-2">
        {/* dB Signal Level Visualizer */}
        <div className="flex-1 flex flex-col gap-1.5">
          {/* Mic level */}
          {captureMode !== 'pc_only' && (
            <div className="flex items-center gap-1.5">
              <span className="text-[8px] opacity-70" title="Microfono">🎙️</span>
              <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden border border-white/5 relative">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-75 rounded-full"
                  style={{ width: `${micPercentage}%` }}
                ></div>
              </div>
              <span className="text-[8px] font-mono font-bold text-white/60 min-w-[64px] text-right">{displaySignalLevel(signalLevelMic)}</span>
            </div>
          )}

          {/* System level */}
          {captureMode !== 'mic_only' && (
            <div className="flex items-center gap-1.5">
              <span className="text-[8px] opacity-70" title="Audio di Sistema">🖥️</span>
              <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden border border-white/5 relative">
                <div
                  className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all duration-75 rounded-full"
                  style={{ width: `${systemPercentage}%` }}
                ></div>
              </div>
              <span className="text-[8px] font-mono font-bold text-white/60 min-w-[64px] text-right">{displaySignalLevel(signalLevelSystem)}</span>
            </div>
          )}
        </div>

        <button
          onClick={handleCaptureScreenshot}
          disabled={
            captureBackend !== 'native'
            || !isRecording
            || isStopping
            || isCapturingScreenshot
            || (displays.length > 1 && selectedDisplayId === null)
          }
          className="h-9 min-w-9 rounded-lg border border-white/10 bg-white/10 px-2 text-[10px] font-semibold text-white/90 transition hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-40"
          title={captureBackend === 'native' ? t('recording.screenshotShortcut') : t('recording.screenshotNativeOnly')}
          aria-label={t('recording.screenshotAction')}
        >
          {isCapturingScreenshot ? '…' : `▣ ${screenshotCount}`}
        </button>

        {/* Circular Stop Button */}
        <button
          onClick={handleStop}
          disabled={isStopping || !isRecording}
          className={`w-9 h-9 rounded-full transition-all flex items-center justify-center shadow-lg cursor-pointer ${
            isStopping 
              ? 'bg-yellow-600 cursor-not-allowed opacity-60' 
              : !isRecording 
              ? 'bg-gray-700 cursor-not-allowed opacity-40' 
              : 'bg-red-500 hover:bg-red-600 active:scale-90 hover:shadow-red-500/20'
          }`}
          title="Ferma Registrazione"
        >
          {isStopping ? (
            <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
          ) : (
            <div className="w-3 h-3 bg-white rounded-sm"></div>
          )}
        </button>
      </div>
    </div>
  );
}
