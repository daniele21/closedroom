import type { CaptureDiagnostics } from '../api/apiClient';

// Pure UI copy policy shared by the two recording setup screens. The actual
// permission request, selected capture mode and refresh stay screen-owned.
type Translate = (key: string) => string;

export function nativeCaptureUnavailableMessage(reason: string, t: Translate): string {
  if (reason === 'screen_capture_stream_pending') return t('recording.nativeCapturePendingReason');
  if (reason === 'helper_missing') return t('recording.nativeCaptureHelperMissingReason');
  if (reason === 'macos_required' || reason === 'macos_14_required') {
    return t('recording.nativeCaptureMacosRequiredReason');
  }
  if (reason === 'screen_recording_permission_required') return t('recording.nativeCaptureScreenPermissionReason');
  if (reason === 'microphone_permission_required') return t('recording.nativeCaptureMicPermissionReason');
  return reason || t('recording.nativeCaptureUnavailableUnknown');
}

export function capturePermissionFailureMessage(
  diagnostics: Pick<CaptureDiagnostics, 'code_signature' | 'bundle_identifier'> | null | undefined,
  t: Translate,
): string {
  if (diagnostics?.code_signature && diagnostics.code_signature !== 'signed') {
    return t('recording.permissionsUnsignedHelper');
  }
  if (diagnostics?.bundle_identifier && diagnostics.bundle_identifier !== 'com.closedroom.nativecapture') {
    return t('recording.permissionsInvalidHelper');
  }
  return t('recording.permissionsRequired');
}
