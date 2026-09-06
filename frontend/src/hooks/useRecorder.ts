import { useState, useEffect, useRef, useCallback } from 'react';
import { ApiClient, Recording } from '../api/apiClient';
import {
  createCaptureReservation,
  getCaptureReservation,
  releaseCaptureReservation,
  releaseCaptureReservationOnUnload,
} from '../api/captureAdmission';
import { RECORDING_CHUNK_INTERVAL_MS } from '../api/config';
import { useTranslation } from '../i18n/i18n';
import { useToast } from '../context/ToastContext';
import { useAudioDevices, AudioDevice, AudioRouteStatus } from './useAudioDevices';
import { drawAudioMeterOnCanvas } from '../utils/audioVisualizer';
import { BrowserUploadBacklog } from '../utils/browserUploadBacklog';

export type { AudioDevice, AudioRouteStatus };

const AUDIO_METER_RENDER_INTERVAL_MS = 80;
const AUDIO_METER_REACT_INTERVAL_MS = 250;
const RECORDING_TIMER_INTERVAL_MS = 1000;
const OVERLAY_STATUS_INTERVAL_MS = 500;
const CAPTURE_RESERVATION_POLL_MS = 200;
const CAPTURE_RESERVATION_STORAGE_KEY = 'closedroom-capture-reservation-id';

export const openBrowserPopup = () => {
  const width = 295;
  const height = 135;
  const left = window.screen.width - width - 40;
  const top = 80;
  
  const popup = window.open(
    `${window.location.origin}/#overlay`,
    'ClosedRoomOverlay',
    `width=${width},height=${height},left=${left},top=${top},status=no,menubar=no,toolbar=no,location=no`
  );
  if (popup) popup.focus();
};

export function useRecorder(onSaved?: (recording: Recording) => void) {
  const { t } = useTranslation();
  const { showToast } = useToast();

  const [isRecording, setIsRecording] = useState(false);
  const [isPreparingRecording, setIsPreparingRecording] = useState(false);
  const [isWaitingForAi, setIsWaitingForAi] = useState(false);
  const [timer, setTimer] = useState('00:00');
  const [signalLevel, setSignalLevel] = useState('-∞ dB');
  const [signalLevelMic, setSignalLevelMic] = useState('-∞ dB');
  const [signalLevelSystem, setSignalLevelSystem] = useState('-∞ dB');
  const [progressText, setProgressText] = useState(t('recording.progressNone'));
  const [statusText, setStatusText] = useState(t('recording.statusReady'));
  const [statusState, setStatusState] = useState<'ready' | 'recording' | 'paused' | 'working' | 'error' | 'success'>('ready');
  const [fallbackNotice, setFallbackNotice] = useState<string | null>(null);
  
  // Audio devices and routing state managed by custom hook
  const {
    microphones,
    systemDevices,
    selectedMicrophone,
    setSelectedMicrophone,
    selectedSystemDevice,
    setSelectedSystemDevice,
    audioRouteStatus,
    captureCapabilities,
    capturePermissions,
    setCapturePermissions,
    isTestRouted,
    setIsTestRouted,
    isVerifying,
    setIsVerifying,
    loadDevices,
    refreshAudioStatus,
    refreshCaptureCapabilities,
    refreshCapturePermissions
  } = useAudioDevices();

  const [permissionsErrorDetails, setPermissionsErrorDetails] = useState<{
    missing_permissions: string[];
    microphone: string;
    screen_capture: string;
    executable_path: string;
    bundle_identifier: string;
    code_signature: string;
    team_id: string;
    identifier: string;
  } | null>(null);

  // Audio Context Ref
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const systemAnalyserRef = useRef<AnalyserNode | null>(null);
  const mediaRecordersRef = useRef<Map<string, MediaRecorder>>(new Map());
  const sourceStreamsRef = useRef<MediaStream[]>([]);
  const mixDestinationRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const timerIntervalRef = useRef<any>(null);
  
  // Session State
  const sessionIdRef = useRef<string | null>(null);
  const sequenceRef = useRef<Map<string, number>>(new Map());
  const uploadChainsRef = useRef<Map<string, Promise<any>>>(new Map());
  const browserUploadBacklogRef = useRef(new BrowserUploadBacklog());
  const browserBackpressureTriggeredRef = useRef(false);
  const startedAtRef = useRef(0);
  const routeActivatedRef = useRef(false);
  const captureBackendRef = useRef<'browser' | 'native'>('browser');
  const captureReservationIdRef = useRef<string | null>(null);
  const captureLeaseCommittedRef = useRef(false);
  const startInFlightRef = useRef(false);
  const cancelStartRequestedRef = useRef(false);
  const broadcastIntervalRef = useRef<any>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const currentMicDbRef = useRef<number>(-120);
  const currentSysDbRef = useRef<number>(-120);
  const bcRef = useRef<BroadcastChannel | null>(null);
  const visualCaptureLabelRef = useRef('');
  const lastMeterRenderAtRef = useRef(0);
  const lastMeterReactAtRef = useRef(0);

  // Canvas Ref
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const timerRef = useRef('00:00');
  const signalLevelRef = useRef('-∞ dB');
  const signalLevelMicRef = useRef('-∞ dB');
  const signalLevelSystemRef = useRef('-∞ dB');
  const progressTextRef = useRef('');
  const isRecordingRef = useRef(false);

  useEffect(() => { timerRef.current = timer; }, [timer]);
  useEffect(() => { signalLevelRef.current = signalLevel; }, [signalLevel]);
  useEffect(() => { signalLevelMicRef.current = signalLevelMic; }, [signalLevelMic]);
  useEffect(() => { signalLevelSystemRef.current = signalLevelSystem; }, [signalLevelSystem]);
  useEffect(() => { progressTextRef.current = progressText; }, [progressText]);
  useEffect(() => { isRecordingRef.current = isRecording; }, [isRecording]);

  const isAggregateInput = (label: string) => {
    const normalized = label.toLowerCase();
    return normalized.includes('aggregate') || normalized.includes('combinat') || normalized.includes('local asr input');
  };

  const releaseCaptureLease = useCallback(async () => {
    const reservationId = captureReservationIdRef.current
      || localStorage.getItem(CAPTURE_RESERVATION_STORAGE_KEY);
    if (!reservationId) return;
    try {
      await releaseCaptureReservation(reservationId);
      captureReservationIdRef.current = null;
      captureLeaseCommittedRef.current = false;
      localStorage.removeItem(CAPTURE_RESERVATION_STORAGE_KEY);
    } catch (error) {
      // Keep the token locally so a later recovery/mount can retry cleanup.
      console.warn('Unable to release capture reservation:', error);
      throw error;
    }
  }, []);

  // Interrupted recording session cleanup & recovery check
  useEffect(() => {
    const storedId = localStorage.getItem('asr-active-recording-id');
    const storedReservationId = localStorage.getItem(CAPTURE_RESERVATION_STORAGE_KEY);
    if (storedReservationId) captureReservationIdRef.current = storedReservationId;

    const releaseRecoveredLease = () => {
      if (!storedReservationId) return;
      void releaseCaptureLease().catch(() => {});
    };

    if (storedId) {
      ApiClient.getRecording(storedId).then(async (recording: Recording) => {
        if (['recording', 'finalizing', 'recoverable'].includes(recording.status)) {
          await ApiClient.recoverRecording(storedId);
          setStatusText(t('recording.sessionInterrupted'));
          setProgressText(t('recording.pageClosedWarning'));
        } else if (recording.stopped_at === null || recording.duration_seconds === null) {
          setStatusText(t('recording.sessionInterrupted'));
          setProgressText(t('recording.pageClosedWarning'));
        }
        localStorage.removeItem('asr-active-recording-id');
      }).catch(() => {
        localStorage.removeItem('asr-active-recording-id');
      }).finally(releaseRecoveredLease);
    } else {
      releaseRecoveredLease();
    }
  }, [t, releaseCaptureLease]);


  const stopAudioMeter = useCallback((closeContext = true) => {
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
    lastMeterRenderAtRef.current = 0;
    lastMeterReactAtRef.current = 0;
    analyserRef.current = null;
    micAnalyserRef.current = null;
    systemAnalyserRef.current = null;

    if (closeContext && audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }

    if (canvasRef.current) {
      const context = canvasRef.current.getContext('2d');
      context?.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    }
    signalLevelRef.current = '-∞ dB';
    signalLevelMicRef.current = '-∞ dB';
    signalLevelSystemRef.current = '-∞ dB';
    setSignalLevel('-∞ dB');
    setSignalLevelMic('-∞ dB');
    setSignalLevelSystem('-∞ dB');
  }, []);

  const drawAudioMeter = useCallback((timestamp = performance.now()) => {
    animationFrameRef.current = requestAnimationFrame(drawAudioMeter);
    if (document.hidden || timestamp - lastMeterRenderAtRef.current < AUDIO_METER_RENDER_INTERVAL_MS) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    lastMeterRenderAtRef.current = timestamp;

    const levels = drawAudioMeterOnCanvas(
      canvas,
      micAnalyserRef.current,
      systemAnalyserRef.current,
      captureBackendRef.current === 'native',
      currentMicDbRef.current,
      currentSysDbRef.current
    );

    if (timestamp - lastMeterReactAtRef.current < AUDIO_METER_REACT_INTERVAL_MS) return;
    lastMeterReactAtRef.current = timestamp;

    const levelMic = levels.dbMic <= -47.5 ? '-∞ dB' : `${levels.dbMic.toFixed(1)} dB`;
    if (levelMic !== signalLevelMicRef.current) {
      signalLevelMicRef.current = levelMic;
      setSignalLevelMic(levelMic);
    }

    const levelSys = levels.dbSys <= -47.5 ? '-∞ dB' : `${levels.dbSys.toFixed(1)} dB`;
    if (levelSys !== signalLevelSystemRef.current) {
      signalLevelSystemRef.current = levelSys;
      setSignalLevelSystem(levelSys);
    }

    const levelCombined = levels.dbCombined <= -47.5 ? '-∞ dB' : `${levels.dbCombined.toFixed(1)} dB`;
    if (levelCombined !== signalLevelRef.current) {
      signalLevelRef.current = levelCombined;
      setSignalLevel(levelCombined);
    }
  }, []);

  const releaseMedia = useCallback(() => {
    stopAudioMeter();
    sourceStreamsRef.current.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
    sourceStreamsRef.current = [];
    mediaRecordersRef.current.clear();
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, [stopAudioMeter]);

  const restoreAudioRoute = useCallback(async () => {
    if (!routeActivatedRef.current) return;
    try {
      await ApiClient.testAudioRestore();
    } catch (error) {
      console.warn('Unable to restore the original audio route:', error);
    } finally {
      routeActivatedRef.current = false;
      setIsTestRouted(false);
      refreshAudioStatus();
    }
  }, [refreshAudioStatus]);

  const stopRecording = useCallback(async () => {
    const mediaRecorders = Array.from(mediaRecordersRef.current.values());
    if (
      captureBackendRef.current !== 'native'
      && (mediaRecorders.length === 0 || mediaRecorders.every((recorder) => recorder.state === 'inactive'))
    ) return;

    setStatusText(t('recording.finalizing'));
    setStatusState('working');

    if (captureBackendRef.current !== 'native') {
      mediaRecorders.forEach((recorder) => {
        if (recorder.state === 'recording') {
          try {
            recorder.requestData();
          } catch { /* ignore */ }
        }
      });
      // Brief delay to flush chunks
      await new Promise((r) => setTimeout(r, 150));

      await Promise.all(mediaRecorders.map((recorder) => new Promise<void>((resolve) => {
        if (recorder.state === 'inactive') {
          resolve();
          return;
        }
        recorder.addEventListener('stop', () => resolve(), { once: true });
        recorder.stop();
      })));
    }

    if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
    if (broadcastIntervalRef.current) {
      clearInterval(broadcastIntervalRef.current);
      broadcastIntervalRef.current = null;
    }
    
    // Broadcast final offline status to overlay
    bcRef.current?.postMessage({
      type: 'status',
      isRecording: false,
      timer: '00:00',
      signalLevel: '-∞ dB',
      signalLevelMic: '-∞ dB',
      signalLevelSystem: '-∞ dB',
      progressText: t('recording.progressNone'),
      visualCaptureLabel: ''
    });
    visualCaptureLabelRef.current = '';

    // Hide native overlay
    ApiClient.toggleOverlay(false).catch(() => {});

    releaseMedia();

    const sessionId = sessionIdRef.current;
    try {
      await Promise.all(Array.from(uploadChainsRef.current.values()));
      if (sessionId) {
        const recording = captureBackendRef.current === 'native'
          ? (await ApiClient.stopNativeCapture(sessionId)).recording
          : await ApiClient.stopRecording(sessionId);
        localStorage.removeItem('asr-active-recording-id');
        sessionIdRef.current = null;
        captureBackendRef.current = 'browser';

        const warnings = recording.warnings || [];
        const isMicEmpty = warnings.includes('track_mic_empty');
        const isSystemEmpty = warnings.includes('track_system_empty');
        const mode = recording.capture_mode;

        const isFullyEmpty = recording.bytes_written === 0 || (
          mode === 'both' ? (isMicEmpty && isSystemEmpty) :
          mode === 'mic_only' ? isMicEmpty :
          mode === 'pc_only' ? isSystemEmpty : false
        );

        if (isFullyEmpty) {
          setStatusText(t('recording.emptyRecordingWarning'));
          setStatusState('error');
          setProgressText(t('recording.emptyRecordingWarning'));
          showToast(t('recording.emptyRecordingWarning'), 'error');
        } else if (browserBackpressureTriggeredRef.current) {
          const message = t('recording.uploadBackpressure');
          setStatusText(t('common.error'));
          setStatusState('error');
          setProgressText(message);
        } else {
          setStatusText(t('recording.saved'));
          setStatusState('success');
          setProgressText(t('recording.audioCompleteSaved'));
        }
        setIsRecording(false);
        await releaseCaptureLease().catch(() => {});
        if (onSaved) onSaved(recording);
      }
    } catch (error: any) {
      setStatusText(t('common.error'));
      setStatusState('error');
      showToast(t('recording.finalizationFailed', { error: error.message }), 'error');
    } finally {
      browserUploadBacklogRef.current.reset();
      browserBackpressureTriggeredRef.current = false;
      captureLeaseCommittedRef.current = false;
      await restoreAudioRoute();
      await releaseCaptureLease().catch(() => {});
    }
  }, [t, onSaved, releaseMedia, restoreAudioRoute, showToast, releaseCaptureLease]);

  // Listen for remote overlay command and status requests and hold persistent BroadcastChannel
  useEffect(() => {
    const bc = new BroadcastChannel('closedroom-recording');
    bcRef.current = bc;
    
    const handleMessage = (e: MessageEvent) => {
      const data = e.data;
      if (!data) return;
      
      if (data.type === 'command' && data.action === 'stop') {
        bc.postMessage({ type: 'ack', action: 'stop' });
        stopRecording();
      } else if (data.type === 'request-status') {
        bc.postMessage({
          type: 'status',
          isRecording: isRecordingRef.current,
          timer: timerRef.current,
          signalLevel: signalLevelRef.current,
          signalLevelMic: signalLevelMicRef.current,
          signalLevelSystem: signalLevelSystemRef.current,
          progressText: progressTextRef.current,
          visualCaptureLabel: visualCaptureLabelRef.current
        });
      }
    };
    
    bc.addEventListener('message', handleMessage);
    
    return () => {
      bc.removeEventListener('message', handleMessage);
      bc.close();
      bcRef.current = null;
    };
  }, [stopRecording]);

  const getAudioStream = async (deviceId: string, voiceProcessing: boolean) => {
    if (!deviceId && !voiceProcessing) {
      throw new Error(t('recording.blackholeInputRequiredError'));
    }
    const constraints: MediaTrackConstraints = {
      echoCancellation: voiceProcessing,
      noiseSuppression: voiceProcessing,
      autoGainControl: voiceProcessing,
    };
    if (deviceId) constraints.deviceId = { exact: deviceId };
    return navigator.mediaDevices.getUserMedia({ audio: constraints });
  };

  const uploadChunk = async (trackId: string, blob: Blob, chunkSequence: number) => {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    const maxAttempts = 5;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const metadata = await ApiClient.appendRecordingTrackChunk(sessionId, trackId, chunkSequence, blob);
        const sizeStr = metadata.bytes_written > 1024 * 1024
          ? `${(metadata.bytes_written / (1024 * 1024)).toFixed(1)} MB`
          : `${Math.round(metadata.bytes_written / 1024)} KB`;
        setProgressText(t('recording.chunksSaved', { count: metadata.chunk_count, size: sizeStr }));
        return;
      } catch (error: any) {
        if (attempt >= maxAttempts) {
          try {
            await ApiClient.expectedRecordingTrackSequence(sessionId, trackId);
          } catch {
            // Preserve the original upload error for the UI.
          }
          throw new Error(error.message);
        }
        await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
      }
    }
  };

  const cancelPendingStart = useCallback(async () => {
    if (!isPreparingRecording || captureLeaseCommittedRef.current) return;
    cancelStartRequestedRef.current = true;
    setIsWaitingForAi(false);
    setIsPreparingRecording(false);
    setIsVerifying(false);
    await releaseCaptureLease().catch(() => {});
    setStatusText(t('recording.statusReady'));
    setStatusState('ready');
    setProgressText(t('recording.progressNone'));
  }, [isPreparingRecording, releaseCaptureLease, setIsVerifying, t]);

  const startRecording = useCallback(async (
    title: string,
    projectName = '',
    language = '',
    mode: 'both' | 'mic_only' | 'pc_only' = 'both',
    visualWindowId?: number,
    visualCaptureLabel = '',
  ) => {
    if (startInFlightRef.current || isRecordingRef.current) return;
    if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
      showToast(t('recording.unsupportedBrowser'), 'error');
      return;
    }

    startInFlightRef.current = true;
    cancelStartRequestedRef.current = false;
    captureLeaseCommittedRef.current = false;
    setIsPreparingRecording(true);
    setIsWaitingForAi(false);
    setIsVerifying(true);
    setPermissionsErrorDetails(null);
    setFallbackNotice(null);
    setStatusText(t('recording.audioSetupTitle'));
    setStatusState('working');
    setProgressText(t('recording.audioSetupStatus'));
    visualCaptureLabelRef.current = visualWindowId !== undefined ? visualCaptureLabel : '';

    const cancelled = () => cancelStartRequestedRef.current;

    try {
      let capabilityCheckFailed = false;
      const capabilities = captureCapabilities || await ApiClient.captureCapabilities().catch(() => {
        capabilityCheckFailed = true;
        return null;
      });

      const initialReservation = await createCaptureReservation();
      captureReservationIdRef.current = initialReservation.reservation_id;
      localStorage.setItem(CAPTURE_RESERVATION_STORAGE_KEY, initialReservation.reservation_id);
      let reservation = initialReservation;
      if (reservation.status === 'waiting') {
        setIsWaitingForAi(true);
      }
      while (reservation.status === 'waiting') {
        await new Promise((resolve) => setTimeout(resolve, CAPTURE_RESERVATION_POLL_MS));
        if (cancelled()) {
          await releaseCaptureLease().catch(() => {});
          startInFlightRef.current = false;
          return;
        }
        reservation = await getCaptureReservation(reservation.reservation_id);
      }
      setIsWaitingForAi(false);
      if (cancelled()) {
        await releaseCaptureLease().catch(() => {});
        startInFlightRef.current = false;
        return;
      }

      if (capabilities?.default_backend === 'native' && capabilities.native.available) {
        const permissionMode = visualWindowId !== undefined && mode === 'mic_only' ? 'both' : mode;
        const permissionResult = await ApiClient.ensureCapturePermissions(permissionMode);
        setCapturePermissions(permissionResult.permissions);

        if (!permissionResult.ok) {
          const diagnostics = permissionResult.diagnostics || {};
          setPermissionsErrorDetails({
            missing_permissions: [],
            microphone: permissionResult.permissions?.microphone || diagnostics.microphone || 'unknown',
            screen_capture: permissionResult.permissions?.screen_capture || diagnostics.screen_capture || 'required',
            executable_path: diagnostics.executable_path || '',
            bundle_identifier: diagnostics.bundle_identifier || '',
            code_signature: diagnostics.code_signature || 'unknown',
            team_id: diagnostics.team_id || '',
            identifier: diagnostics.identifier || '',
          });

          let errorMsg = t('recording.permissionsRequired') || 'Native capture permissions are required.';
          if (diagnostics.bundle_identifier && diagnostics.bundle_identifier !== 'com.closedroom.nativecapture') {
            errorMsg = t('recording.permissionsInvalidHelper') || 'The native recording component is installed incorrectly.';
          } else if (diagnostics.code_signature && diagnostics.code_signature !== 'signed') {
            errorMsg = t('recording.permissionsUnsignedHelper') || 'The native recording component is not signed correctly. Reinstall or rebuild ClosedRoom.';
          } else if (mode !== 'pc_only' && permissionResult.permissions?.microphone === 'notDetermined') {
            errorMsg = t('recording.permissionsMicNotDetermined') || 'Microphone permission has not been requested yet.';
          } else if (mode !== 'pc_only' && permissionResult.permissions?.microphone === 'denied') {
            errorMsg = t('recording.permissionsMissingMic') || 'Microphone permission is missing.';
          } else if (mode !== 'mic_only' && permissionResult.permissions?.screen_capture === 'required') {
            errorMsg = t('recording.permissionsMissingSystem') || 'Screen Recording permission is missing.';
          }
          throw new Error(errorMsg);
        }

        const session = await ApiClient.createRecording({
          title: title || t('recording.untitledRecording'),
          project_name: projectName,
          mime_type: 'audio/wav',
          language: language || undefined,
          capture_mode: mode,
          capture_backend: 'native',
        });
        captureBackendRef.current = 'native';
        sessionIdRef.current = session.id;
        localStorage.setItem('asr-active-recording-id', session.id);
        
        await ApiClient.startNativeCapture(session.id, mode, visualWindowId);
        captureLeaseCommittedRef.current = true;
        
        // Connect EventSource to receive real-time levels and capture status
        currentMicDbRef.current = -120;
        currentSysDbRef.current = -120;
        const eventSource = new EventSource(`/v1/recordings/${session.id}/capture/events`);
        eventSourceRef.current = eventSource;
        
        eventSource.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.type === 'ready') {
              // Capture helper is ready, we can start the timers and show the overlay now!
              startedAtRef.current = Date.now();
              
              timerIntervalRef.current = setInterval(() => {
                const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000);
                const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
                const secs = (elapsed % 60).toString().padStart(2, '0');
                setTimer(`${mins}:${secs}`);
              }, RECORDING_TIMER_INTERVAL_MS);

              // The overlay needs human-scale status updates, not display-rate telemetry.
              broadcastIntervalRef.current = setInterval(() => {
                bcRef.current?.postMessage({
                  type: 'status',
                  isRecording: true,
                  timer: timerRef.current,
                  signalLevel: signalLevelRef.current,
                  signalLevelMic: signalLevelMicRef.current,
                  signalLevelSystem: signalLevelSystemRef.current,
                  progressText: progressTextRef.current,
                  visualCaptureLabel: visualCaptureLabelRef.current
                });
              }, OVERLAY_STATUS_INTERVAL_MS);

              // Request showing the native overlay panel
              ApiClient.toggleOverlay(true).then((res) => {
                if (!res || !res.success) {
                  setFallbackNotice(t('recording.overlayFallbackNotice'));
                  showToast(t('recording.overlayFallbackNotice'), 'warning');
                  openBrowserPopup();
                }
              }).catch(() => {
                setFallbackNotice(t('recording.overlayFallbackNotice'));
                showToast(t('recording.overlayFallbackNotice'), 'warning');
                openBrowserPopup();
              });

              setIsPreparingRecording(false);
              setIsVerifying(false);
              setIsRecording(true);
              setStatusState('recording');
              setStatusText(t('recording.statusRecording'));
              setProgressText(t('recording.progressSaving') || 'Salvataggio in corso...');
            } else if (data.type === 'volume') {
              const dbVal = Number(data.db) || -120;
              if (data.source === 'mic') {
                currentMicDbRef.current = dbVal;
              } else if (data.source === 'system') {
                currentSysDbRef.current = dbVal;
              }
            } else if (data.type === 'error') {
              eventSource.close();
              releaseMedia();
              ApiClient.cancelNativeCapture(session.id).catch(() => {});
              localStorage.removeItem('asr-active-recording-id');
              sessionIdRef.current = null;
              captureLeaseCommittedRef.current = false;
              setIsPreparingRecording(false);
              setIsWaitingForAi(false);
              setIsVerifying(false);
              setStatusState('error');
              setIsRecording(false);
              void releaseCaptureLease().catch(() => {});

              if (data.reason === 'permissions_missing') {
                setPermissionsErrorDetails({
                  missing_permissions: data.missing_permissions || [],
                  microphone: data.microphone || 'unknown',
                  screen_capture: data.screen_capture || 'required',
                  executable_path: data.executable_path || '',
                  bundle_identifier: data.bundle_identifier || '',
                  code_signature: data.code_signature || 'unknown',
                  team_id: data.team_id || '',
                  identifier: data.identifier || '',
                });
                const missingPerms = data.missing_permissions || [];
                let errorMsg = '';
                if (data.code_signature === 'unsigned') {
                  errorMsg = t('recording.permissionsUnsignedHelper') || 'The native recording component is not signed correctly. Reinstall or rebuild ClosedRoom.';
                } else if (missingPerms.includes('microphone') && missingPerms.includes('screen_capture')) {
                  errorMsg = t('recording.permissionsMissingBoth') || 'Mancano i permessi per il Microfono e la Registrazione dello schermo.';
                } else if (missingPerms.includes('microphone')) {
                  errorMsg = t('recording.permissionsMissingMic') || 'Manca il permesso per il Microfono. Apri Impostazioni di Sistema -> Privacy e Sicurezza -> Microfono e abilita ClosedRoom.';
                } else if (missingPerms.includes('screen_capture')) {
                  errorMsg = t('recording.permissionsMissingSystem') || 'Manca il permesso per la Registrazione dello schermo. Apri Impostazioni di Sistema -> Privacy e Sicurezza -> Registrazione schermo e abilita ClosedRoom.';
                } else {
                  errorMsg = data.message || t('recording.permissionsRequired') || 'Permessi richiesti per microfono e audio di sistema.';
                }
                setStatusText(errorMsg);
                showToast(errorMsg, 'error');
              } else {
                const errorMsg = data.message || t('recording.startFailed');
                setStatusText(errorMsg);
                showToast(errorMsg, 'error');
              }
            } else if (data.type === 'stopped') {
              eventSource.close();
            }
          } catch (err) {
            console.error('Failed to parse capture event:', err);
          }
        };

        eventSource.onerror = (err) => {
          console.error('EventSource error:', err);
          eventSource.close();
          // If we haven't successfully started recording yet, handle it as start failure
          if (!isRecordingRef.current) {
            releaseMedia();
            ApiClient.cancelNativeCapture(session.id).catch(() => {});
            localStorage.removeItem('asr-active-recording-id');
            sessionIdRef.current = null;
            captureLeaseCommittedRef.current = false;
            setIsPreparingRecording(false);
            setIsWaitingForAi(false);
            setIsVerifying(false);
            setStatusState('error');
            setStatusText(t('recording.startFailed'));
            showToast(t('recording.startFailed'), 'error');
            void releaseCaptureLease().catch(() => {});
          }
        };

        stopAudioMeter(false);
        drawAudioMeter();
        startInFlightRef.current = false;
        return;
      }

      const captureFallbackMessage = capabilityCheckFailed
        ? t('recording.captureCapabilityFallbackNotice')
        : t('recording.captureBrowserFallbackNotice');
      setFallbackNotice(captureFallbackMessage);
      showToast(captureFallbackMessage, 'warning');

      // 1. Audio Routing
      if (mode !== 'mic_only') {
        const routing = await ApiClient.testAudioRoute();
        if (routing.success) {
          await new Promise((r) => setTimeout(r, 500));
          await loadDevices();
          routeActivatedRef.current = true;
        } else {
          throw new Error(t('recording.setupAudioError'));
        }
      }

      // 2. Audio Streams setup
      setStatusText(t('recording.accessingSources'));
      sourceStreamsRef.current = [];
      let micStream = null;

      if (mode !== 'pc_only') {
        micStream = await getAudioStream(selectedMicrophone, true);
        sourceStreamsRef.current.push(micStream);
        const track = micStream.getAudioTracks()[0];
        if (track && isAggregateInput(track.label || '')) {
          throw new Error(t('recording.aggregateDeviceError'));
        }
        await loadDevices();
      } else if (!selectedSystemDevice) {
        // Unlock permissions
        const permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        permissionStream.getTracks().forEach((track) => track.stop());
        await loadDevices();
      }

      const systemStream = mode !== 'mic_only' ? await getAudioStream(selectedSystemDevice, false) : null;
      if (systemStream) sourceStreamsRef.current.push(systemStream);

      // 3. Audio graph mixing
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      const actx = new AudioContextClass();
      audioContextRef.current = actx;
      if (actx.state === 'suspended') {
        await actx.resume();
      }

      const destNode = actx.createMediaStreamDestination();
      destNode.channelCount = 2;
      mixDestinationRef.current = destNode;
      const trackDestinations = new Map<string, MediaStreamAudioDestinationNode>();

      const mixBus = actx.createGain();
      mixBus.gain.value = 1;

      const silenceSource = actx.createConstantSource();
      silenceSource.offset.value = 0;
      const keepDestinationClocked = (destination: MediaStreamAudioDestinationNode) => {
        const silentGain = actx.createGain();
        silentGain.gain.value = 0;
        silenceSource.connect(silentGain);
        silentGain.connect(destination);
      };

      const connectSourceTrack = (trackId: 'mic' | 'system', stream: MediaStream | null) => {
        if (!stream) return null;
        const sourceNode = actx.createMediaStreamSource(stream);
        sourceNode.connect(mixBus);

        const trackDest = actx.createMediaStreamDestination();
        trackDest.channelCount = 1;
        sourceNode.connect(trackDest);
        keepDestinationClocked(trackDest);
        trackDestinations.set(trackId, trackDest);
        return sourceNode;
      };

      const micNode = connectSourceTrack('mic', micStream);
      const systemNode = connectSourceTrack('system', systemStream);
      mixBus.connect(destNode);
      keepDestinationClocked(destNode);
      silenceSource.start();

      // Chrome Workaround for active graph
      const silentGain = actx.createGain();
      silentGain.gain.value = 0.0;
      mixBus.connect(silentGain);
      silentGain.connect(actx.destination);

      stopAudioMeter(false);
      if (micNode) {
        micAnalyserRef.current = actx.createAnalyser();
        micAnalyserRef.current.fftSize = 512;
        micAnalyserRef.current.smoothingTimeConstant = 0.78;
        micNode.connect(micAnalyserRef.current);
      } else {
        micAnalyserRef.current = null;
      }

      if (systemNode) {
        systemAnalyserRef.current = actx.createAnalyser();
        systemAnalyserRef.current.fftSize = 512;
        systemAnalyserRef.current.smoothingTimeConstant = 0.78;
        systemNode.connect(systemAnalyserRef.current);
      } else {
        systemAnalyserRef.current = null;
      }

      drawAudioMeter();

      // 4. Create Backend Recording
      const mimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
      const mimeType = mimeTypes.find((type) => MediaRecorder.isTypeSupported(type)) || '';

      const session = await ApiClient.createRecording({
        title: title || t('recording.untitledRecording'),
        project_name: projectName,
        mime_type: mimeType,
        language: language || undefined,
        capture_mode: mode,
        capture_backend: 'browser',
      });
      captureBackendRef.current = 'browser';

      sessionIdRef.current = session.id;
      localStorage.setItem('asr-active-recording-id', session.id);
      sequenceRef.current = new Map();
      uploadChainsRef.current = new Map();
      browserUploadBacklogRef.current.reset();
      browserBackpressureTriggeredRef.current = false;

      // 5. Start MediaRecorder
      const recorderInputs: Array<{ trackId: string; stream: MediaStream }> = [];
      if (mode === 'both') {
        const micDest = trackDestinations.get('mic');
        const systemDest = trackDestinations.get('system');
        if (micDest) recorderInputs.push({ trackId: 'mic', stream: micDest.stream });
        if (systemDest) recorderInputs.push({ trackId: 'system', stream: systemDest.stream });
        recorderInputs.push({ trackId: 'mixed', stream: destNode.stream });
      } else if (mode === 'mic_only') {
        const micDest = trackDestinations.get('mic');
        if (micDest) recorderInputs.push({ trackId: 'mic', stream: micDest.stream });
      } else if (mode === 'pc_only') {
        const systemDest = trackDestinations.get('system');
        if (systemDest) recorderInputs.push({ trackId: 'system', stream: systemDest.stream });
      }

      const startTrackRecorder = (trackId: string, stream: MediaStream) => {
        const recorder = mimeType
          ? new MediaRecorder(stream, { mimeType })
          : new MediaRecorder(stream);
        mediaRecordersRef.current.set(trackId, recorder);
        sequenceRef.current.set(trackId, 0);
        uploadChainsRef.current.set(trackId, Promise.resolve());

        recorder.addEventListener('dataavailable', (event) => {
          if (!event.data || event.data.size === 0 || !sessionIdRef.current) return;
          const blob = event.data;
          const backlogSnapshot = browserUploadBacklogRef.current.accept(blob.size);
          const currentSequence = sequenceRef.current.get(trackId) || 0;
          sequenceRef.current.set(trackId, currentSequence + 1);
          const currentChain = uploadChainsRef.current.get(trackId) || Promise.resolve();
          const nextChain = currentChain
            .then(() => uploadChunk(trackId, blob, currentSequence))
            .finally(() => {
              browserUploadBacklogRef.current.release(blob.size);
            });
          uploadChainsRef.current.set(trackId, nextChain);
          nextChain.catch((error) => {
            setStatusText(t('common.error'));
            setStatusState('error');
            showToast(t('recording.chunkSaveFailed', { error: error.message }), 'error');
          });

          if (backlogSnapshot.saturated && !browserBackpressureTriggeredRef.current) {
            browserBackpressureTriggeredRef.current = true;
            const message = t('recording.uploadBackpressure');
            setStatusText(t('recording.finalizing'));
            setStatusState('working');
            setProgressText(message);
            showToast(message, 'error');
            queueMicrotask(() => {
              void stopRecording();
            });
          }
        });

        recorder.addEventListener('error', (event: any) => {
          showToast(t('recording.error', { error: event.error?.message || 'unknown' }), 'error');
        });

        recorder.start(RECORDING_CHUNK_INTERVAL_MS);
      };

      recorderInputs.forEach(({ trackId, stream }) => startTrackRecorder(trackId, stream));
      captureLeaseCommittedRef.current = true;

      // 6. Timer and state
      startedAtRef.current = Date.now();
      timerIntervalRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000);
        const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const secs = (elapsed % 60).toString().padStart(2, '0');
        setTimer(`${mins}:${secs}`);
      }, RECORDING_TIMER_INTERVAL_MS);

      // The overlay needs human-scale status updates, not display-rate telemetry.
      broadcastIntervalRef.current = setInterval(() => {
        bcRef.current?.postMessage({
          type: 'status',
          isRecording: true,
          timer: timerRef.current,
          signalLevel: signalLevelRef.current,
          signalLevelMic: signalLevelMicRef.current,
          signalLevelSystem: signalLevelSystemRef.current,
          progressText: progressTextRef.current,
          visualCaptureLabel: visualCaptureLabelRef.current
        });
      }, OVERLAY_STATUS_INTERVAL_MS);

      // Request showing the native overlay panel, fallback to browser window.open if unavailable
      ApiClient.toggleOverlay(true).then((res) => {
        if (!res || !res.success) {
          setFallbackNotice(t('recording.overlayFallbackNotice'));
          showToast(t('recording.overlayFallbackNotice'), 'warning');
          openBrowserPopup();
        }
      }).catch(() => {
        setFallbackNotice(t('recording.overlayFallbackNotice'));
        showToast(t('recording.overlayFallbackNotice'), 'warning');
        openBrowserPopup();
      });

      setIsPreparingRecording(false);
      setIsWaitingForAi(false);
      setIsVerifying(false);
      setIsRecording(true);
      setStatusText(t('recording.statusRecording'));
      setStatusState('recording');
      setProgressText(t('recording.progressSaving'));
      startInFlightRef.current = false;

    } catch (error: any) {
      startInFlightRef.current = false;
      setIsPreparingRecording(false);
      setIsWaitingForAi(false);
      setIsVerifying(false);
      if (!captureLeaseCommittedRef.current) {
        await releaseCaptureLease().catch(() => {});
      }
      if (cancelled()) {
        setStatusText(t('recording.statusReady'));
        setStatusState('ready');
        setProgressText(t('recording.progressNone'));
        return;
      }
      visualCaptureLabelRef.current = '';
      releaseMedia();
      await restoreAudioRoute();
      setStatusText(t('common.error'));
      setStatusState('error');
      showToast(t('recording.startFailed', { error: error.message }), 'error');
    }
  }, [t, selectedMicrophone, selectedSystemDevice, captureCapabilities, setCapturePermissions, loadDevices, releaseMedia, restoreAudioRoute, showToast, stopRecording, drawAudioMeter, stopAudioMeter, releaseCaptureLease, setIsVerifying]);

  const toggleTestAudioRoute = async () => {
    setIsVerifying(true);
    try {
      if (!isTestRouted) {
        const data = await ApiClient.testAudioRoute();
        if (data.success) {
          setIsTestRouted(true);
          routeActivatedRef.current = true;
          showToast(t('recording.routingActive', { devices: `${data.output_device} / ${data.input_device}` }), 'success');
        } else {
          showToast(t('recording.routingActiveFailed'), 'error');
        }
      } else {
        const data = await ApiClient.testAudioRestore();
        if (data.success) {
          setIsTestRouted(false);
          routeActivatedRef.current = false;
          showToast(t('recording.routingRestoreSuccess'), 'success');
        } else {
          showToast(t('recording.routingRestoreFailed'), 'error');
        }
      }
      refreshAudioStatus();
    } catch (error: any) {
      showToast(t('recording.routingTestError', { error: error.message }), 'error');
    } finally {
      setIsVerifying(false);
    }
  };

  const verifyAudioSetup = async () => {
    setIsVerifying(true);
    await loadDevices();
    await refreshAudioStatus();
    await refreshCaptureCapabilities();
    setIsVerifying(false);
  };

  // Cleanups on unload
  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (isRecording) {
        event.preventDefault();
        event.returnValue = '';
      }
    };

    const handlePageHide = () => {
      if (routeActivatedRef.current) {
        navigator.sendBeacon?.('/v1/system/audio/restore');
      }
      const reservationId = captureReservationIdRef.current;
      if (reservationId && !captureLeaseCommittedRef.current) {
        releaseCaptureReservationOnUnload(reservationId);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('pagehide', handlePageHide);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('pagehide', handlePageHide);
    };
  }, [isRecording]);

  return {
    isRecording,
    isPreparingRecording,
    isWaitingForAi,
    timer,
    signalLevel,
    signalLevelMic,
    signalLevelSystem,
    progressText,
    captureCapabilities,
    capturePermissions,
    refreshCapturePermissions,
    permissionsErrorDetails,
    fallbackNotice,
    statusText,
    statusState,
    microphones,
    systemDevices,
    selectedMicrophone,
    selectedSystemDevice,
    audioRouteStatus,
    isTestRouted,
    isVerifying,
    canvasRef,
    setSelectedMicrophone,
    setSelectedSystemDevice,
    startRecording,
    cancelPendingStart,
    stopRecording,
    toggleTestAudioRoute,
    verifyAudioSetup,
    refreshAudioStatus,
  };
}
