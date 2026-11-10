import type { TranscriptionSegment } from '../api/apiClient';

export interface SpeakerDisplayMapping {
  speaker_cluster: string;
  display_name?: string | null;
  speaker_group?: string;
  status?: string;
}

export interface SpeakerDisplay {
  /** Stable cluster or merged group identity; never the editable display label. */
  key: string | null;
  label: string;
  needsIdentification: boolean;
}

/** Resolve a person's display label without confusing an audio source with a person.
 * Original provider_speaker, word timing and segment attribution remain untouched.
 */
export function speakerDisplay(
  segment: TranscriptionSegment,
  mappings: SpeakerDisplayMapping[],
  sourceTrackLabels: string[] = [],
): SpeakerDisplay {
  const raw = segment.provider_speaker || segment.speaker_group || segment.speaker_label || '';
  const mapping = mappings.find((entry) => entry.speaker_cluster === (segment.provider_speaker || raw));
  const group = segment.speaker_group || mapping?.speaker_group || segment.provider_speaker || null;
  const visible = (mapping?.display_name || segment.speaker_name || segment.speaker_label || '').trim();
  const accepted = mapping?.status === 'accepted';
  const sourceOnly = !accepted && !!visible && (
    sourceTrackLabels.some((source) => source.toLocaleLowerCase() === visible.toLocaleLowerCase())
    || (visible.toLocaleLowerCase() === 'computer' && segment.source === 'system')
  ) && (!segment.provider_speaker || segment.provider_speaker === visible);
  return {
    key: group || (sourceOnly ? null : (raw || null)),
    label: sourceOnly || !visible ? 'Voce da identificare' : visible,
    needsIdentification: sourceOnly || !visible || (!accepted && !segment.provider_speaker && visible === 'Speaker'),
  };
}

/** Group only truly adjacent utterances with a stable shared speaker identity.
 * Never glue overlapped passages or distant turns; preserve all original segments.
 */
export function canJoinConversationTurns(
  previous: TranscriptionSegment,
  next: TranscriptionSegment,
  mappings: SpeakerDisplayMapping[],
  sourceTrackLabels: string[] = [],
): boolean {
  const a = speakerDisplay(previous, mappings, sourceTrackLabels);
  const b = speakerDisplay(next, mappings, sourceTrackLabels);
  return !!a.key && a.key === b.key && !previous.overlap && !next.overlap
    && Number.isFinite(previous.end) && Number.isFinite(next.start)
    && next.start >= previous.start
    && next.start >= previous.end - 0.25
    && next.start - previous.end <= 8;
}
