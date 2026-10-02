import { ChevronDown, Eye, MonitorUp, UserCheck, UserRoundSearch } from 'lucide-react';
import { VisualIntelligenceResponseV2 } from '../../api/visualIntelligence';
import { Badge } from '../ui/Badge';
import { useTranslation } from '../../i18n/i18n';

interface SpeakerMapping {
  speaker_cluster: string;
  display_name?: string | null;
  status: string;
  observation_count?: number;
  distinct_turn_count?: number;
  temporal_support_seconds?: number;
}

interface Props {
  data: VisualIntelligenceResponseV2 | null;
  mappings: SpeakerMapping[];
  loading: boolean;
  error: string | null;
}

function timestamp(value: number): string {
  const seconds = Math.max(0, Math.round(value));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

export function VisualIntelligencePanel({ data, mappings, loading, error }: Props) {
  const { t } = useTranslation();
  if (loading) {
    return <div className="h-28 animate-pulse rounded-xl bg-bg-surface" aria-label={t('meeting.visualTimelineLoading')} />;
  }
  if (error) {
    return (
      <section className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3" role="status">
        <p className="text-sm font-semibold text-text-primary">{t('meeting.visualTimelineTitle')}</p>
        <p className="mt-1 text-xs text-warning">{t('meeting.visualTimelineUnavailable')}</p>
      </section>
    );
  }
  if (!data) return null;

  const { document } = data;
  const events = document.meeting_state_events || [];
  const shares = document.share_sessions || [];
  const accepted = mappings.filter((item) => item.status === 'accepted' && item.display_name);
  const review = mappings.filter((item) => item.status !== 'accepted');

  return (
    <section className="surface-supporting overflow-hidden rounded-xl border border-border-subtle shadow-soft" aria-labelledby="visual-intelligence-title">
      <div className="flex flex-col gap-3 border-b border-border-subtle bg-bg-surface/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-accent" aria-hidden="true" />
          <div>
            <h3 id="visual-intelligence-title" className="text-sm font-semibold text-text-primary">{t('meeting.visualTimelineTitle')}</h3>
            <p className="text-[11px] text-text-muted">{t('meeting.visualTimelineDesc')}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="idle">{events.length} {t('meeting.visualEvents')}</Badge>
          <Badge variant="idle">{shares.length} {t('meeting.visualShares')}</Badge>
        </div>
      </div>

      {data.source_validity?.status === 'stale' && (
        <div className="border-b border-warning/30 bg-warning/5 px-4 py-3 text-xs text-warning" role="status">
          <p className="font-semibold">{t('meeting.visualSourcesStaleTitle')}</p>
          <p className="mt-0.5 text-text-secondary">{t('meeting.visualSourcesStaleDesc')}</p>
        </div>
      )}

      <div className="grid gap-0 lg:grid-cols-[minmax(220px,0.75fr)_minmax(0,1.5fr)]">
        <div className="border-b border-border-subtle p-4 lg:border-b-0 lg:border-r">
          <div className="mb-3 flex items-center gap-2">
            <UserCheck className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-text-muted">{t('meeting.speakerAttributionLabel')}</h4>
          </div>
          {accepted.map((mapping) => (
            <div key={mapping.speaker_cluster} className="flex items-center justify-between gap-3 border-b border-border-subtle py-2 text-xs last:border-0">
              <span className="font-mono text-text-muted">{mapping.speaker_cluster}</span>
              <span className="font-semibold text-text-primary">{mapping.display_name}</span>
            </div>
          ))}
          {review.map((mapping) => (
            <div key={mapping.speaker_cluster} className="flex items-center justify-between gap-3 border-b border-border-subtle py-2 text-xs last:border-0">
              <span className="font-mono text-text-muted">{mapping.speaker_cluster}</span>
              <Badge variant="warning">{t('meeting.speakerNeedsReview')}</Badge>
            </div>
          ))}
          {mappings.length === 0 && (
            <div className="flex items-start gap-2 text-xs text-text-muted">
              <UserRoundSearch className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>{t('meeting.visualAbstained')}</p>
            </div>
          )}
        </div>

        <div className="p-4">
          <h4 className="mb-3 text-[10px] font-bold uppercase tracking-wider text-text-muted">{t('meeting.visualObservedTimeline')}</h4>
          {events.length === 0 && shares.length === 0 ? (
            <p className="text-xs text-text-muted">{t('meeting.visualTimelineEmpty')}</p>
          ) : (
            <div className="relative ml-1 border-l border-border-subtle pl-4">
              {events.map((event, index) => (
                <div key={`${event.type}-${event.timestamp}-${index}`} className="relative pb-3 last:pb-0">
                  <span className="absolute -left-[19px] top-1.5 h-2 w-2 rounded-full bg-accent ring-4 ring-bg-elevated" />
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <time className="font-mono text-[10px] text-text-muted">{timestamp(event.timestamp)}</time>
                    <span className="text-xs font-semibold text-text-primary">{t(`meeting.visualEvent_${event.type}`)}</span>
                    {event.layout && <span className="text-[11px] text-text-secondary">{event.layout}</span>}
                  </div>
                </div>
              ))}
              {shares.map((session) => (
                <details key={session.id} className="group relative pb-3 last:pb-0">
                  <span className="absolute -left-[19px] top-1.5 h-2 w-2 rounded-full bg-warning ring-4 ring-bg-elevated" />
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded">
                    <time className="font-mono text-[10px] font-normal text-text-muted">{timestamp(session.start)}</time>
                    <MonitorUp className="h-3.5 w-3.5 text-warning" aria-hidden="true" />
                    {t('meeting.visualSharedContent')}
                    <span className="text-[11px] font-normal text-text-muted">{session.keyframes.length} {t('meeting.visualKeyframes')}</span>
                    <ChevronDown className="ml-auto h-3.5 w-3.5 text-text-muted transition-transform group-open:rotate-180" aria-hidden="true" />
                  </summary>
                  <div className="mt-2 space-y-2 pl-16">
                    {session.keyframes.map((keyframe, index) => (
                      <div key={`${keyframe.observation_id || index}`} className="border-l border-border-subtle pl-3 text-[11px]">
                        <p className="font-semibold text-text-primary">{keyframe.title || keyframe.content_type}</p>
                        <p className="text-text-muted">{timestamp(keyframe.timestamp)} · {keyframe.content_type}</p>
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
