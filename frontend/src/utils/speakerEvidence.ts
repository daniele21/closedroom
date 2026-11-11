import type { TranscriptionSegment } from '../api/apiClient';

export interface SpeakerGroupMapping {
  speaker_cluster: string;
  speaker_group?: string;
}

/**
 * Count only transcript turns with actual text, by effective speaker group.
 * Native diarization intervals are a separate evidence source and must never
 * be presented as transcript turns. Review metadata counts raw clusters, so
 * it is not a substitute for the current per-turn assignment projection.
 */
export function linkedTranscriptTurns(
  segments: Pick<TranscriptionSegment, 'text' | 'provider_speaker' | 'speaker_label' | 'speaker_group'>[],
  mappings: SpeakerGroupMapping[],
): Map<string, number> {
  const groupByCluster = new Map(mappings.map((item) => [
    item.speaker_cluster, item.speaker_group || item.speaker_cluster,
  ]));
  const counts = new Map<string, number>();
  for (const segment of segments) {
    if (!segment.text?.trim()) continue;
    const raw = segment.provider_speaker || segment.speaker_label || '';
    const group = segment.speaker_group || groupByCluster.get(raw) || raw;
    if (!group) continue;
    counts.set(group, (counts.get(group) || 0) + 1);
  }
  return counts;
}
