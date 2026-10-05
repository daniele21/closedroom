import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, CaptureDisplay } from '../api/apiClient';
import { useTranslation } from '../i18n/i18n';

type OverlayLog = (
  level: 'info' | 'warn' | 'error',
  message: string,
  data?: any,
) => void;

interface OverlayDisplaySelectionOptions {
  recordingId: string | null;
  captureBackend: 'browser' | 'native';
  isRecording: boolean;
  isExpanded: boolean;
  logOverlay: OverlayLog;
  onError: (message: string | null) => void;
}

export async function resizeRecordingOverlay(
  expanded: boolean,
  displayPickerOpen: boolean,
) {
  const width = 420;
  const height = displayPickerOpen ? 300 : expanded ? 238 : 118;
  if (window.name === 'ClosedRoomOverlay') {
    window.resizeTo(width, height + 52);
    return;
  }
  try {
    await ApiClient.resizeOverlay(width, height);
  } catch (err) {
    console.warn('Resize overlay window failed:', err);
  }
}

export function useOverlayDisplaySelection({
  recordingId,
  captureBackend,
  isRecording,
  isExpanded,
  logOverlay,
  onError,
}: OverlayDisplaySelectionOptions) {
  const { t } = useTranslation();
  const [displays, setDisplays] = useState<CaptureDisplay[]>([]);
  const [selectedDisplayId, setSelectedDisplayId] = useState<number | null>(null);
  const [isDisplayPickerOpen, setIsDisplayPickerOpen] = useState(false);
  const [pendingDisplayId, setPendingDisplayId] = useState<number | null>(null);
  const [isSelectingDisplay, setIsSelectingDisplay] = useState(false);
  const selectedDisplayIdRef = useRef<number | null>(null);
  const pendingDisplayIdRef = useRef<number | null>(null);
  const displayPickerRef = useRef<HTMLDivElement | null>(null);

  const setSelected = useCallback((displayId: number | null) => {
    selectedDisplayIdRef.current = displayId;
    setSelectedDisplayId(displayId);
  }, []);

  const setPending = useCallback((displayId: number | null) => {
    pendingDisplayIdRef.current = displayId;
    setPendingDisplayId(displayId);
  }, []);

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
        : (
            selectedDisplayIdRef.current
            ?? (
              storedId && available.some((display) => display.display_id === storedId)
                ? storedId
                : null
            )
          );

      if (preferred && available.some((display) => display.display_id === preferred)) {
        setSelected(preferred);
      } else if (available.length > 0) {
        setSelected(available[0].display_id);
      } else {
        setSelected(null);
      }
    } catch (err) {
      console.warn('Unable to load screenshot displays:', err);
      setDisplays([]);
      setSelected(null);
    }
  }, [setSelected]);

  const reconcileBackendDisplayId = useCallback((backendDisplayId: number | null) => {
    const pendingSelection = pendingDisplayIdRef.current;
    if (
      backendDisplayId !== null
      && (pendingSelection === null || backendDisplayId === pendingSelection)
    ) {
      setSelected(backendDisplayId);
      if (pendingSelection === backendDisplayId) {
        setPending(null);
      }
    }
    return pendingSelection ?? backendDisplayId ?? selectedDisplayIdRef.current;
  }, [setPending, setSelected]);

  const applyCapturedDisplay = useCallback((displayId: number | null | undefined) => {
    if (displayId) setSelected(displayId);
  }, [setSelected]);

  const ensureSelectedDisplay = useCallback(async () => {
    if (selectedDisplayIdRef.current === null) {
      await loadDisplays();
    }
    return selectedDisplayIdRef.current;
  }, [loadDisplays]);

  const openDisplayPicker = useCallback(async () => {
    if (!isRecording || captureBackend !== 'native') return;
    if (displays.length === 0) {
      await loadDisplays(undefined, false);
    }
    setIsDisplayPickerOpen(true);
    await resizeRecordingOverlay(isExpanded, true);
  }, [captureBackend, displays.length, isExpanded, isRecording, loadDisplays]);

  const closeDisplayPicker = useCallback(async (resize = true) => {
    setIsDisplayPickerOpen(false);
    if (resize) {
      await resizeRecordingOverlay(isExpanded, false);
    }
  }, [isExpanded]);

  const toggleDisplayPicker = useCallback(async () => {
    if (!isRecording || captureBackend !== 'native') return;
    if (isDisplayPickerOpen) {
      await closeDisplayPicker();
      return;
    }
    await openDisplayPicker();
  }, [
    captureBackend,
    closeDisplayPicker,
    isDisplayPickerOpen,
    isRecording,
    openDisplayPicker,
  ]);

  const handleSelectDisplay = useCallback(async (displayId: number) => {
    if (!recordingId || captureBackend !== 'native') return;

    const previousDisplayId = selectedDisplayIdRef.current;
    setPending(displayId);
    setSelected(displayId);
    setIsSelectingDisplay(true);
    onError(null);

    try {
      const result = await ApiClient.selectScreenshotDisplay(recordingId, displayId);
      setSelected(result.display_id);
      setPending(null);
      try {
        localStorage.setItem(
          'asr-overlay-preferred-display-id',
          String(result.display_id),
        );
      } catch {}
      logOverlay('info', 'Screenshot display changed', {
        recordingId,
        displayId: result.display_id,
      });
      await closeDisplayPicker();
    } catch (err: any) {
      setPending(null);
      setSelected(previousDisplayId);
      const message = String(
        err?.message || t('recording.screenshotDisplayUnavailable'),
      );
      onError(message);
      logOverlay('error', 'Screenshot display change failed', {
        recordingId,
        requestedDisplayId: displayId,
        error: message,
      });
    } finally {
      setIsSelectingDisplay(false);
    }
  }, [
    captureBackend,
    closeDisplayPicker,
    logOverlay,
    onError,
    recordingId,
    setPending,
    setSelected,
    t,
  ]);

  useEffect(() => {
    if (!isDisplayPickerOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (displayPickerRef.current && !displayPickerRef.current.contains(target)) {
        void closeDisplayPicker();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [closeDisplayPicker, isDisplayPickerOpen]);

  return {
    displays,
    selectedDisplayId,
    pendingDisplayId,
    isDisplayPickerOpen,
    isSelectingDisplay,
    displayPickerRef,
    loadDisplays,
    reconcileBackendDisplayId,
    applyCapturedDisplay,
    ensureSelectedDisplay,
    openDisplayPicker,
    closeDisplayPicker,
    toggleDisplayPicker,
    handleSelectDisplay,
  };
}
