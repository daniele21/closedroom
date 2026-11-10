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
  language: 'it' | 'en' = 'it',
): SpeakerDisplay {
  const raw = segment.provider_speaker || segment.speaker_group || segment.speaker_label || '';
  const mapping = mappings.find((entry) => entry.speaker_cluster === (segment.provider_speaker || raw));
  const group = segment.speaker_group || mapping?.speaker_group || segment.provider_speaker || null;
  const visible = (mapping?.display_name || segment.speaker_name || segment.speaker_label || '').trim();
  const accepted = mapping?.status === 'accepted';
  const sourceLabels = sourceTrackLabels.map((source) => source.toLocaleLowerCase());
  const isSourceName = (name: string) =>
    sourceLabels.includes(name.toLocaleLowerCase())
    || (name.toLocaleLowerCase() === 'computer' && segment.source === 'system');
  const sourceOnly = !accepted && !!visible && isSourceName(visible);
  // Legacy transcripts sometimes persisted "Computer" itself as a speaker ID.
  // That is not a detected person and must not become a newly inferred cluster.
  const hasRealCluster = !!segment.provider_speaker && !isSourceName(segment.provider_speaker);
  const sourceUnattributed = sourceOnly && !hasRealCluster;
  return {
    key: sourceUnattributed ? null : (group || raw || null),
    label: sourceUnattributed
      ? (language === 'it' ? 'Audio non attribuito' : 'Unattributed audio')
      : sourceOnly || !visible
        ? (language === 'it' ? 'Voce da identificare' : 'Unidentified voice')
        : visible,
    needsIdentification: !sourceUnattributed && (!accepted || !visible),
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
