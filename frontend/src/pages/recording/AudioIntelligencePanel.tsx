import { AudioIntelligence } from '../../api/apiClient';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { useTranslation } from '../../i18n/i18n';
import { formatTime } from '../../utils/formatters';

interface AudioIntelligencePanelProps {
  intelligence: AudioIntelligence | null;
  loading?: boolean;
  hasTranscription: boolean;
  onTranscribe: () => void;
  compact?: boolean;
}

function channelLabel(channel: string, labels: Record<string, string>) {
  return labels[channel] || channel;
}

function formatSeconds(value?: number) {
  if (value == null || !Number.isFinite(value)) return '0.0s';
  return `${value.toFixed(1)}s`;
}

export default function AudioIntelligencePanel({
  intelligence,
  loading = false,
  hasTranscription,
  onTranscribe,
  compact = false,
}: AudioIntelligencePanelProps) {
  const { t } = useTranslation();
  const metrics = intelligence?.conversation_metrics;
  const channelLabels = {
    mic: t('audioIntelligence.channelMic'),
    system: t('audioIntelligence.channelSystem'),
    mixed: t('audioIntelligence.channelMixed'),
  };
  const speakingPct = metrics?.speaking_time_pct || {};
  const speakingSeconds = metrics?.speaking_time_seconds || {};
  const speechRate = metrics?.speech_rate_wpm || {};
  const longPauses = metrics?.long_pauses || [];
  const overlaps = metrics?.overlaps || [];
  const highEnergy = metrics?.high_energy_moments || [];
  const moments = [
    ...longPauses.slice(0, 4).map((item) => ({ type: t('audioIntelligence.longPause'), time: item.start, detail: formatSeconds(item.duration) })),
    ...overlaps.slice(0, 4).map((item) => ({ type: t('audioIntelligence.overlap'), time: item.start, detail: formatSeconds(item.duration) })),
    ...highEnergy.slice(0, 4).map((item) => ({ type: t('audioIntelligence.highEnergy'), time: item.start, detail: item.end ? `${formatTime(item.start)}-${formatTime(item.end)}` : '' })),
  ].sort((a, b) => a.time - b.time).slice(0, 6);

  return (
    <Card className={compact ? 'flex flex-col gap-3 !p-3 shadow-none' : 'md:col-span-3 flex flex-col gap-5'}>
      <div className={compact ? 'flex flex-wrap items-center justify-between gap-2' : 'flex flex-col sm:flex-row sm:items-start justify-between gap-3'}>
        {!compact && <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-text-primary">{t('audioIntelligence.title')}</h3>
            {intelligence?.mock && <Badge variant="info" className="py-0.5 px-2 text-[10px]">{t('audioIntelligence.mockBadge')}</Badge>}
          </div>
          <p className="text-xs text-text-secondary mt-1">{t('audioIntelligence.description')}</p>
        </div>}
        {compact && intelligence?.mock && <Badge variant="info" className="py-0.5 px-2 text-[10px]">{t('audioIntelligence.mockBadge')}</Badge>}
        {intelligence && (
          <span className="text-[10px] text-text-muted font-mono uppercase tracking-wider">
            {intelligence.backend} · {intelligence.mode}
          </span>
        )}
      </div>

      {loading ? (
        <div className="py-8 flex items-center justify-center text-xs text-text-muted">
          {t('common.loading')}
        </div>
      ) : !hasTranscription ? (
        <div className="rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <p className="text-xs text-text-secondary">{t('audioIntelligence.emptyBeforeTranscription')}</p>
          <button className="text-xs font-semibold text-accent hover:text-accent-hover cursor-pointer" onClick={onTranscribe}>
            {t('audioIntelligence.transcribeCta')}
          </button>
        </div>
      ) : !intelligence ? (
        <div className="rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-4 text-xs text-text-secondary">
          {t('audioIntelligence.emptyAfterTranscription')}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {['mic', 'system'].map((channel) => (
              <div key={channel} className="rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-3">
                <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
                  {channelLabel(channel, channelLabels)}
                </span>
                <div className="mt-2 flex items-baseline justify-between gap-2">
                  <strong className="text-xl text-text-primary">{speakingPct[channel] ?? 0}%</strong>
                  <span className="text-[10px] text-text-secondary">{formatSeconds(speakingSeconds[channel])}</span>
                </div>
                <p className="text-[10px] text-text-muted mt-1">
                  {speechRate[channel] ? `${speechRate[channel]} WPM` : t('audioIntelligence.noSpeechRate')}
                </p>
              </div>
            ))}
            <div className="rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-3">
              <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">{t('audioIntelligence.longPauses')}</span>
              <strong className="block mt-2 text-xl text-text-primary">{longPauses.length}</strong>
              <p className="text-[10px] text-text-muted mt-1">{t('audioIntelligence.overThreshold')}</p>
            </div>
            <div className="rounded-lg border border-border-subtle/70 bg-bg-surface/40 p-3">
              <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">{t('audioIntelligence.overlaps')}</span>
              <strong className="block mt-2 text-xl text-text-primary">{overlaps.length}</strong>
              <p className="text-[10px] text-text-muted mt-1">{t('audioIntelligence.channelOverlap')}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
                {t('audioIntelligence.reviewMoments')}
              </span>
              {moments.length ? (
                <div className="flex flex-col divide-y divide-border-subtle/70 rounded-lg border border-border-subtle/70 overflow-hidden">
                  {moments.map((moment, index) => (
                    <div key={`${moment.type}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2 bg-bg-surface/30">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[11px] font-mono text-accent shrink-0">{formatTime(moment.time)}</span>
                        <span className="text-xs text-text-primary truncate">{moment.type}</span>
                      </div>
                      <span className="text-[10px] text-text-muted shrink-0">{moment.detail}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted rounded-lg border border-border-subtle/70 bg-bg-surface/30 p-3">
                  {t('audioIntelligence.noMoments')}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
                {t('audioIntelligence.mockInsights')}
              </span>
              {intelligence.insight_candidates?.length ? (
                <div className="flex flex-col gap-2">
                  {intelligence.insight_candidates.slice(0, 3).map((item, index) => (
                    <div key={`${item.type}-${index}`} className="rounded-lg border border-info/20 bg-info/5 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <strong className="text-xs text-text-primary">{item.title || item.type}</strong>
                        {item.start != null && <span className="text-[10px] font-mono text-info">{formatTime(item.start)}</span>}
                      </div>
                      <p className="text-[10px] text-text-muted mt-1">{t('audioIntelligence.mockDisclaimer')}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted rounded-lg border border-border-subtle/70 bg-bg-surface/30 p-3">
                  {t('audioIntelligence.noMockInsights')}
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
