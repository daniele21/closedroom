import { ChevronDown, Headphones } from 'lucide-react';
import type { Recording } from '../../api/apiClient';
import { useTranslation } from '../../i18n/i18n';
import { formatBytes } from '../../utils/formatters';

/** Read-only projection of canonical recording metadata; no audio or API preload. */
export function MeetingRecordingDetails({ recording }: { recording: Recording }) {
  const { t, lang } = useTranslation();
  const additionalTracks = (recording.audio_tracks || []).filter((track) => !track.primary);
  const warnings = (recording.warnings || [])
    .filter((warning) => !/^track_.*_invalid$/.test(warning)
      && !warning.startsWith('Visual') && !warning.includes('ScreenCaptureKit'))
    .map((warning) => {
      const labels: Record<string, string> = {
        track_mic_empty: t('recording.qualityMicEmpty'),
        track_system_empty: t('recording.qualitySystemEmpty'),
        track_mixed_empty: t('recording.qualityMixedEmpty'),
        sync_duration_warning: t('recording.qualitySyncWarning'),
        sync_duration_serious_warning: t('recording.qualitySyncSeriousWarning'),
        sync_duration_unreliable: t('recording.qualitySyncUnreliable'),
      };
      return labels[warning] || warning;
    });
  const probeUnavailable = (recording.warnings || []).some((warning) => /^track_.*_invalid$/.test(warning));
  const hasQuality = Boolean(recording.quality_report) || warnings.length > 0 || probeUnavailable;
  if (!additionalTracks.length && !hasQuality) return null;

  return (
    <details className="surface-advanced group rounded-xl overflow-hidden" data-meeting-recording-details="true">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus">
        <span className="flex items-center gap-2">
          <Headphones className="h-4 w-4 text-accent" aria-hidden="true" />
          {lang === 'it' ? 'Tracce e qualità audio' : 'Audio tracks and quality'}
        </span>
        <ChevronDown className="h-4 w-4 text-text-muted group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="space-y-3 border-t border-border-subtle p-4">
        {additionalTracks.map((track) => (
          <div key={track.id} className="rounded-lg border border-border-subtle bg-bg-surface p-3">
            <div className="mb-2 flex items-center justify-between gap-3 text-xs">
              <span className="font-medium text-text-primary">{track.label}</span>
              <span className="text-text-muted">{formatBytes(track.bytes_written)}</span>
            </div>
            <audio
              controls
              preload="none"
              className="h-9 w-full"
              src={`/v1/recordings/${encodeURIComponent(recording.id)}/tracks/${encodeURIComponent(track.id)}/audio`}
              aria-label={`${lang === 'it' ? 'Traccia audio' : 'Audio track'}: ${track.label}`}
            />
          </div>
        ))}
        {hasQuality && (
          <div className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-xs text-text-secondary">
            <h4 className="font-semibold text-text-primary">{t('recording.qualityTitle')}</h4>
            {recording.quality_report?.sync?.duration_delta_ms != null && (
              <p className="mt-2">{t('recording.qualitySyncLabel')}: {recording.quality_report.sync.duration_delta_ms} ms</p>
            )}
            {warnings.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-warning">
                {warnings.map((warning, index) => <li key={index}>{warning}</li>)}
              </ul>
            ) : probeUnavailable ? (
              <p className="mt-2 text-text-muted">{t('recording.qualityProbeUnavailable')}</p>
            ) : (
              <p className="mt-2 text-text-muted">{t('recording.qualityOk')}</p>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
