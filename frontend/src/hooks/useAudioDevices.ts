import { useState, useEffect, useCallback } from 'react';
import { ApiClient, CaptureCapabilities, CapturePermissions } from '../api/apiClient';
import { useTranslation } from '../i18n/i18n';

export interface AudioDevice {
  deviceId: string;
  label: string;
}

// Browser enumeration only covers the opt-in microphone fallback. System
// audio belongs exclusively to macOS ScreenCaptureKit native capture.
export function useAudioDevices() {
  const { t } = useTranslation();
  const [microphones, setMicrophones] = useState<AudioDevice[]>([]);
  const [selectedMicrophone, setSelectedMicrophone] = useState('');
  const [captureCapabilities, setCaptureCapabilities] = useState<CaptureCapabilities | null>(null);
  const [capturePermissions, setCapturePermissions] = useState<CapturePermissions | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);

  const loadDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((device) =>
        device.kind === 'audioinput'
        && !/aggregate|combinat|local asr input/i.test(device.label)
      );
      setMicrophones(inputs.map((device, index) => ({
        deviceId: device.deviceId,
        label: device.label || t('recording.audioInputLabel', { index: index + 1 }),
      })));
    } catch (error) {
      console.warn('Unable to enumerate microphone inputs:', error);
    }
  }, [t]);

  const refreshCaptureCapabilities = useCallback(async () => {
    try { setCaptureCapabilities(await ApiClient.captureCapabilities()); }
    catch { setCaptureCapabilities(null); }
  }, []);

  const refreshCapturePermissions = useCallback(async () => {
    try { setCapturePermissions(await ApiClient.capturePermissions()); }
    catch { setCapturePermissions(null); }
  }, []);

  useEffect(() => {
    void loadDevices();
    void refreshCaptureCapabilities();
    void refreshCapturePermissions();
    const handleDeviceChange = () => {
      void loadDevices();
      void refreshCapturePermissions();
    };
    navigator.mediaDevices?.addEventListener?.('devicechange', handleDeviceChange);
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', handleDeviceChange);
  }, [loadDevices, refreshCaptureCapabilities, refreshCapturePermissions]);

  return {
    microphones,
    selectedMicrophone,
    setSelectedMicrophone,
    captureCapabilities,
    capturePermissions,
    setCapturePermissions,
    isVerifying,
    setIsVerifying,
    loadDevices,
    refreshCaptureCapabilities,
    refreshCapturePermissions,
  };
}
