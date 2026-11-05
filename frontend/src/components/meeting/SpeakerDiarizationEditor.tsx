import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle, CheckCircle2, ChevronDown, GitMerge, Headphones,
  MoreHorizontal, Pause, Play, RotateCcw, SkipBack, SkipForward, Volume2,
} from 'lucide-react';
import {
  ApiClient, type SpeakerClip, type SpeakerReviewAction,
  type SpeakerReviewInfo, type SpeakerReviewSamples, type Transcription,
} from '../../api/apiClient';
import { useSpeakerReviewPlayback, type SpeakerTurn } from '../../hooks/useSpeakerReviewPlayback';
import { SpeakerTimeline } from './SpeakerTimeline';
import { useToast } from '../../context/ToastContext';
import { useTranslation } from '../../i18n/i18n';
import { Button } from '../ui/Button';

interface Props {
  transcription: Transcription;
  recordingId?: string;
  onUpdated: (transcription: Transcription) => void;
  onPlaybackStart?: () => void;
  onJumpToTranscript?: (time: number) => void;
  readOnly?: boolean;
  durationSeconds?: number;
}

type SpeakerRow = {
  cluster: string;
  group: string;
  name: string;
  status: string;
  count: number;
  sourceOnly: boolean;
};

function clock(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  return String(Math.floor(total / 60)).padStart(2, '0') + ':' +
    String(total % 60).padStart(2, '0');
}

export function SpeakerDiarizationEditor({
  transcription, recordingId, onUpdated, onPlaybackStart, onJumpToTranscript, readOnly = false,
  durationSeconds = 0,
}: Props) {
  const { lang } = useTranslation();
  const tr = (it: string, en: string) => lang === 'it' ? it : en;
  const { showToast } = useToast();
  const id = transcription.id || transcription.saved_id || '';
  const meetingId = recordingId || transcription.recording_id || '';
  const [review, setReview] = useState<SpeakerReviewInfo | null>(null);
  const [samples, setSamples] = useState<SpeakerReviewSamples | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selectedCluster, setSelectedCluster] = useState('');
  const [editedName, setEditedName] = useState('');
  const skipBlurSaveRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [mutationError, setMutationError] = useState('');
  const [sampleIndex, setSampleIndex] = useState(0);
  const [filter, setFilter] = useState<'all' | 'pending'>('all');
  const [showHidden, setShowHidden] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [action, setAction] = useState<'none' | 'merge' | 'exclude'>('none');
  const [mergeTarget, setMergeTarget] = useState('');
  const [showActions, setShowActions] = useState(false);
  const [listenError, setListenError] = useState('');
  const playback = useSpeakerReviewPlayback(meetingId, onPlaybackStart);
  const activeListenRequest = useRef<AbortController | null>(null);
  const selectedGroupRef = useRef<string | null>(null);
  const [timelineCursor, setTimelineCursor] = useState<number | null>(null);

  const mappings = transcription.stats?.speaker_attribution?.mappings || [];
  const rows = useMemo<SpeakerRow[]>(() => {
    const fromMetadata: Array<{
      speaker_cluster: string; display_name?: string | null; status: string;
      speaker_group?: string; transcript_segment_count?: number;
    }> = mappings.length ? mappings : Array.from(
      new Set((transcription.segments || []).map((s) => s.provider_speaker || s.speaker_label).filter(Boolean)),
    ).map((cluster) => ({
      speaker_cluster: cluster as string, display_name: cluster as string, status: 'unassigned',
    }));
    const groupCounts = new Map<string, number>();
    for (const segment of transcription.segments || []) {
      const group = segment.speaker_group || segment.provider_speaker || segment.speaker_label || '';
      groupCounts.set(group, (groupCounts.get(group) || 0) + 1);
    }
    const sourceLabels = new Set((transcription.source_tracks || []).map((track) => track.label));
    return fromMetadata.map((item) => {
      const cluster = item.speaker_cluster;
      const group = item.speaker_group || cluster;
      const sourceOnly = !cluster.includes(':') && sourceLabels.has(cluster) &&
        item.status !== 'accepted';
      return {
        cluster, group, name: item.display_name || cluster || 'Speaker',
        status: item.status, count: groupCounts.get(group) || 0, sourceOnly,
      };
    });
  }, [mappings, transcription.segments, transcription.source_tracks]);

  const visible = rows.filter((r) =>
    !r.sourceOnly &&
    (showHidden || (r.status !== 'merged' && r.status !== 'excluded')) &&
    (filter === 'all' || r.status !== 'accepted'),
  );
  const selected = visible.find((r) => r.cluster === selectedCluster) || visible[0] || null;
  const active = rows.filter((r) => r.status !== 'merged' && r.status !== 'excluded' && !r.sourceOnly);
  const confirmed = active.filter((r) => r.status === 'accepted').length;
  const pending = active.length - confirmed;

  selectedGroupRef.current = selected?.group || null;
  useEffect(() => () => activeListenRequest.current?.abort(), [meetingId]);
  const sampleList = useMemo(() => (
    samples?.speakers.find((item) => item.speaker_cluster === selected?.cluster)?.samples || []
  ), [samples, selected?.cluster]);

  // Never fetch voice media eagerly; metadata is bounded, audio loads on Play.
  useEffect(() => {
    let cancelled = false;
    setReview(null);
    setSamples(null);
    setLoadError('');
    if (!id || !meetingId || readOnly || transcription.merged_sources?.length) return;
    void ApiClient.getSpeakerReview(id).then((data) => {
      if (!cancelled) setReview(data);
    }).catch((e: Error) => {
      if (!cancelled) setLoadError(e.message);
    });
    void ApiClient.getSpeakerReviewSamples(id).then((data) => {
      if (!cancelled && data.recording_id === meetingId && data.transcription_id === id) {
        setSamples(data);
      }
    }).catch((e: Error) => {
      if (!cancelled) setLoadError(e.message);
    });
    return () => { cancelled = true; };
  }, [id, meetingId, readOnly, transcription]);

  useEffect(() => {
    if (!visible.length) { setSelectedCluster(''); return; }
    if (!selectedCluster || !visible.some((r) => r.cluster === selectedCluster)) {
      setSelectedCluster(visible[0].cluster);
    }
  }, [selectedCluster, visible.map((r) => r.cluster).join('|')]);

  useEffect(() => {
    setEditedName(selected?.name || '');
    setSampleIndex(0);
    setAction('none');
    setShowActions(false);
    setMergeTarget('');
  }, [selected?.cluster, transcription.id]);

  useEffect(() => {
    // Reprojecting a saved edit must update the displayed text of the selected row.
    setEditedName(selected?.name || '');
  }, [selected?.name]);

  const selectable = rows.filter((r) =>
    r.cluster !== selected?.cluster && r.status !== 'excluded' && r.status !== 'merged' &&
    r.group !== selected?.group,
  );

  const commit = async (
    kind: SpeakerReviewAction['action'], cluster: string, options: { target?: string; name?: string } = {},
  ) => {
    if (!review || !id || readOnly || saving) return;
    setSaving(true);
    setMutationError('');
    setListenError('');
    activeListenRequest.current?.abort();
    playback.stop();
    try {
      const response = await ApiClient.commitSpeakerReview(id, {
        action: kind, cluster, ...options, expected_fingerprint: review.fingerprint,
      });
      if (kind === 'merge' && options.target) setSelectedCluster(options.target);
      setAction('none');
      setReview(null); // new fingerprint is read from the canonical persisted owner
      onUpdated(response.transcription);
      if (kind !== 'rename') showToast(tr('Modifica speaker salvata', 'Speaker correction saved'), 'success');
    } catch (error: any) {
      setMutationError(error?.message || tr('Modifica non salvata', 'Change not saved'));
    } finally {
      setSaving(false);
    }
  };

  const saveName = () => {
    if (!selected || saving || readOnly) return;
    const next = editedName.trim();
    if (next && next !== selected.name && selected.status !== 'merged' && selected.status !== 'excluded') {
      void commit('rename', selected.cluster, { name: next });
    }
  };

  const undo = async () => {
    if (!review?.undo || saving || !id) return;
    setSaving(true);
    setMutationError('');
    playback.stop();
    try {
      const result = await ApiClient.undoSpeakerReview(id, review.undo.revision_id);
      setReview(null);
      onUpdated(result.transcription);
      showToast(tr('Ultima modifica annullata', 'Last correction undone'), 'success');
    } catch (error: any) {
      setMutationError(error?.message || tr('Impossibile annullare', 'Undo unavailable'));
    } finally {
      setSaving(false);
    }
  };

  const reload = async () => {
    if (!id) return;
    try {
      onUpdated(await ApiClient.getTranscription(id));
      setMutationError('');
    } catch (error: any) {
      setMutationError(error?.message || tr('Ricaricamento non riuscito', 'Reload failed'));
    }
  };

  const playClip = (clip: SpeakerClip) => {
    playback.playSample(clip);
  };

  const playSelectedTurns = async () => {
    if (!selected || !id || saving) return;
    setListenError('');
    const group = selected.group;
    activeListenRequest.current?.abort();
    const abort = new AbortController();
    activeListenRequest.current = abort;
    try {
      const maxSampleEnd = (samples?.speakers || []).reduce((last, item) =>
        Math.max(last, ...item.samples.map((clip) => clip.end), 0), 0);
      const lastAsr = (transcription.segments || []).reduce((last, segment) =>
        Math.max(last, Number(segment.end) || 0), 0);
      const end = Math.min(28800, Math.max(300, durationSeconds, maxSampleEnd, lastAsr));
      const response = await ApiClient.getSpeakerTimeline(id, 0, end, abort.signal);
      if (abort.signal.aborted || selectedGroupRef.current !== group) return;
      if (response.truncated) {
        setListenError(tr('Troppi intervalli: ascolta una finestra temporale dalla timeline.',
          'Too many intervals: play a shorter timeline window.'));
        return;
      }
      const groups = new Map(rows.map((row) => [row.cluster, row.group]));
      const turns: SpeakerTurn[] = response.intervals
        .filter((item) => groups.get(item.cluster) === group && item.playable)
        .map((item) => ({
          track_id: item.track_id, start: item.start, end: item.end,
          kind: item.origin === 'diarization' ? 'diarization' : 'transcript',
          overlap: item.overlap,
        }));
      if (turns.length) {
        setTimelineCursor(turns[0].start);
        playback.playTurns(turns);
        return;
      }
      setListenError(tr('Nessun intervallo audio disponibile per questa voce.',
        'No playable audio intervals for this voice.'));
    } catch (reason) {
      if (!abort.signal.aborted) setListenError(String(reason));
    } finally {
      if (activeListenRequest.current === abort) activeListenRequest.current = null;
    }
  };

  const currentSample = sampleList[sampleIndex % Math.max(1, sampleList.length)];
  const canEdit = !readOnly && !!review && !saving && !transcription.merged_sources?.length;
  const showTurnPlayer = playback.state.mode === 'turns';

  return (
    <section className="rounded-xl border border-border-subtle bg-bg-glass p-4 sm:p-5" data-speaker-review-workspace="true">
      <audio
        ref={playback.audioRef} preload="metadata"
        onTimeUpdate={() => {
          setTimelineCursor(playback.audioRef.current?.currentTime ?? null);
          playback.onTimeUpdate();
        }} onEnded={playback.onEnded}
        onPlay={playback.onPlay} onPause={playback.onPause} onError={playback.onError}
        aria-label={tr('Riproduzione campioni speaker', 'Speaker sample playback')}
      />
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-text-primary">{tr('Voci', 'Voices')}</h3>
          <p className="mt-1 text-sm text-text-secondary">
            {tr('Ascolta e identifica le persone del meeting.', 'Listen and identify the people in the meeting.')}
          </p>
          <p className="mt-2 text-xs text-text-muted" aria-live="polite">
            {confirmed} / {active.length} {tr('voci confermate', 'voices confirmed')}
            {pending > 0 && ' · ' + pending + tr(' da identificare', ' to identify')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {review?.undo && !readOnly && (
            <Button type="button" variant="secondary" size="sm" disabled={saving} onClick={() => void undo()}>
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              {tr('Annulla ultima modifica', 'Undo last correction')}
            </Button>
          )}
        </div>
      </header>

      {loadError && <div role="alert" className="mb-3 flex items-center gap-2 rounded-lg border border-warning/30 p-3 text-sm text-text-secondary">
        <AlertCircle className="h-4 w-4 text-warning" aria-hidden="true" />
        {tr('Alcuni dati audio non sono disponibili: ', 'Some audio data is unavailable: ')}{loadError}
      </div>}
      {mutationError && (
        <div role="alert" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm text-text-primary">
          <AlertCircle className="h-4 w-4 text-danger" aria-hidden="true" />
          <span className="flex-1">{mutationError}</span>
          <Button variant="secondary" size="sm" onClick={() => void reload()}>{tr('Ricarica', 'Reload')}</Button>
        </div>
      )}

      {!rows.length ? (
        <p className="rounded-lg bg-bg-surface p-4 text-sm text-text-muted">
          {tr('Nessuna voce rilevata. Puoi migliorarne il riconoscimento nelle opzioni.', 'No voices found. Improve voice recognition in options.')}
        </p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-1">
            <button type="button" onClick={() => setFilter('all')} aria-pressed={filter === 'all'}
              className={'min-h-9 rounded-lg px-3 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-border-focus ' +
                (filter === 'all' ? 'bg-accent/15 font-semibold text-text-primary' : 'text-text-secondary hover:bg-bg-elevated')}>
              {tr('Tutte le voci', 'All voices')}
            </button>
            <button type="button" onClick={() => setFilter('pending')} aria-pressed={filter === 'pending'}
              className={'min-h-9 rounded-lg px-3 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-border-focus ' +
                (filter === 'pending' ? 'bg-accent/15 font-semibold text-text-primary' : 'text-text-secondary hover:bg-bg-elevated')}>
              {tr('Da identificare', 'To identify')}{pending > 0 ? ` · ${pending}` : ''}
            </button>
          </div>
          <SpeakerTimeline
            transcription={transcription}
            recordingId={meetingId}
            durationSeconds={durationSeconds}
            rows={rows}
            showHidden={showHidden}
            pendingOnly={filter === 'pending'}
            selectedGroup={selected?.group || null}
            cursorSeconds={timelineCursor}
            lang={lang}
            onSelect={(cluster) => { activeListenRequest.current?.abort(); playback.stop(); setTimelineCursor(null); setSelectedCluster(cluster); }}
            sampleAvailable={(cluster) => Boolean(samples?.speakers.find((s) => s.speaker_cluster === cluster)?.samples.length)}
            onPlaySample={(cluster) => {
              const clip = samples?.speakers.find((s) => s.speaker_cluster === cluster)?.samples[0];
              if (!clip) return;
              activeListenRequest.current?.abort();
              setSelectedCluster(cluster);
              setSampleIndex(0);
              setTimelineCursor(clip.start);
              playback.playSample(clip);
            }}
            onPlayInterval={(clip) => { activeListenRequest.current?.abort(); setTimelineCursor(clip.start); playback.playTurns([clip]); }}
            onJumpToTranscript={onJumpToTranscript}
          >
          {selected && (
            <div className="min-w-0">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h4 className="truncate text-base font-semibold text-text-primary">{selected.name}</h4>
                  <p className="mt-1 text-xs text-text-muted">
                    {selected.status === 'accepted' ? tr('Identità confermata', 'Confirmed identity') :
                      selected.status === 'excluded' ? tr('Esclusa (ripristinabile)', 'Excluded (restorable)') :
                      selected.status === 'merged' ? tr('Unita a un’altra voce', 'Merged into another voice') :
                      tr('Da identificare', 'Not yet identified')}
                  </p>
                </div>
                {canEdit && selected.status !== 'excluded' && selected.status !== 'merged' && (
                  <Button variant="ghost" size="sm" onClick={() => setShowActions((value) => !value)}
                    aria-label={tr('Gestisci questa voce', 'Manage this voice')}>
                    <MoreHorizontal className="h-5 w-5" />
                  </Button>
                )}
              </div>

              <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="primary" disabled={!currentSample} onClick={() => {
                    if (!currentSample) return;
                    if (playback.state.mode === 'sample' && playback.state.current?.start === currentSample.start &&
                      playback.state.current?.track_id === currentSample.track_id) playback.toggle();
                    else playClip(currentSample);
                  }}>
                    {playback.state.playing && playback.state.mode === 'sample'
                      ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                    {tr('Ascolta campione', 'Play sample')}
                    {currentSample && ' · ' + Math.round(currentSample.end - currentSample.start) + 's'}
                  </Button>
                  {sampleList.length > 1 && (
                    <Button variant="ghost" size="sm" onClick={() => { playback.stop(); setSampleIndex((value) => (value + 1) % sampleList.length); }}>
                      {tr('Altro campione', 'Another sample')} ({sampleIndex % sampleList.length + 1}/{sampleList.length})
                    </Button>
                  )}
                </div>
                <p className="mt-2 text-xs text-text-muted">
                  {currentSample
                    ? clock(currentSample.start) + '–' + clock(currentSample.end) + ' · ' +
                      (currentSample.kind === 'diarization'
                        ? tr('Voce rilevata nell’audio, senza testo collegato', 'Voice detected in audio, without linked text')
                        : tr('Estratto della trascrizione', 'Transcript excerpt'))
                    : tr('Campione non disponibile: nessun intervallo audio verificabile.', 'Sample unavailable: no verifiable audio interval.')}
                </p>
                {currentSample?.overlap && <p className="mt-1 text-xs text-warning">
                  {tr('Questo intervallo può contenere voci sovrapposte.', 'This interval may contain overlapping voices.')}
                </p>}
              </div>

              <div className="mt-4">
                <label className="mb-1 block text-xs font-medium text-text-secondary" htmlFor="speaker-review-name">
                  {tr('Nome della persona', 'Person name')}
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <input id="speaker-review-name" className="min-w-0 flex-1 rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-sm text-text-primary focus:outline-2 focus:outline-border-focus disabled:opacity-60"
                    value={editedName} maxLength={120}
                    disabled={!canEdit || selected.status === 'excluded' || selected.status === 'merged'}
                    onChange={(event) => setEditedName(event.target.value)}
                    onBlur={() => {
                      if (skipBlurSaveRef.current) {
                        skipBlurSaveRef.current = false;
                        return;
                      }
                      saveName();
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') { event.preventDefault(); event.currentTarget.blur(); }
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        skipBlurSaveRef.current = true;
                        setEditedName(selected.name);
                        event.currentTarget.blur();
                      }
                    }}
                  />
                  <span role="status" aria-live="polite" className="text-xs text-text-muted">
                    {saving ? tr('Salvataggio…', 'Saving…') : review && editedName === selected.name
                      ? tr('Salvato', 'Saved') : ''}
                  </span>
                </div>
              </div>

              <div className="mt-4 border-t border-border-subtle pt-4">
                <Button variant="secondary" onClick={() => void playSelectedTurns()}
                  disabled={!selected || selected.sourceOnly || selected.status === 'excluded' || selected.status === 'merged'}>
                  <Headphones className="h-4 w-4" aria-hidden="true" />
                  {tr('Ascolta i suoi interventi', 'Listen to this speaker’s turns')}
                </Button>
                <p className="mt-2 text-xs text-text-muted">
                  {tr('Riproduce gli intervalli attribuiti a questa voce, saltando gli altri. Le sovrapposizioni restano udibili.', 'Plays attributed intervals and skips other turns. Overlapping voices can still be heard.')}
                </p>
                {showTurnPlayer && playback.state.current && (
                  <div className="mt-3 rounded-lg border border-border-subtle bg-bg-surface p-3">
                    <p className="mb-2 text-xs text-text-secondary" aria-live="polite">
                      {tr('Intervento', 'Turn')} {playback.state.index + 1}/{playback.state.total} · {clock(playback.state.current.start)}
                    </p>
                    <p className="mb-2 line-clamp-2 text-sm text-text-primary">{playback.state.current.text}</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="ghost" size="sm" disabled={playback.state.index === 0} onClick={playback.previous}
                        aria-label={tr('Intervento precedente', 'Previous turn')}><SkipBack className="h-4 w-4" /></Button>
                      <Button variant="secondary" size="sm" onClick={playback.toggle}>
                        {playback.state.playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                        {playback.state.playing ? tr('Pausa', 'Pause') : tr('Riprendi', 'Resume')}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={playback.next}
                        disabled={playback.state.index + 1 >= playback.state.total}
                        aria-label={tr('Intervento successivo', 'Next turn')}><SkipForward className="h-4 w-4" /></Button>
                      {onJumpToTranscript && (
                        <Button variant="ghost" size="sm" onClick={() => onJumpToTranscript(playback.state.current!.start)}>
                          {tr('Vai al testo', 'Go to transcript')}
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" onClick={playback.stop}>
                        {tr('Termina ascolto', 'Stop listening')}
                      </Button>
                    </div>
                  </div>
                )}
                {listenError && <p role="alert" className="mt-2 text-xs text-warning">{listenError}</p>}
                {playback.state.error && <p role="alert" className="mt-2 text-xs text-danger">{playback.state.error}</p>}
              </div>

              {action !== 'none' && selected.status !== 'excluded' && selected.status !== 'merged' && (
                <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface p-3">
                  {action === 'merge' ? (
                    <>
                      <h5 className="text-sm font-semibold">{tr('Unisci con un’altra voce', 'Merge with another voice')}</h5>
                      <p className="mt-1 text-xs text-text-secondary">
                        {tr('Le etichette verranno unite; audio e testo originali rimarranno invariati.', 'The labels will be grouped; original audio and text remain unchanged.')}
                      </p>
                      <select className="my-3 w-full rounded-lg border border-border-subtle bg-bg-elevated p-2 text-sm"
                        aria-label={tr('Voce di destinazione', 'Target voice')} value={mergeTarget}
                        onChange={(event) => setMergeTarget(event.target.value)}>
                        <option value="">{tr('Scegli una voce', 'Select a voice')}</option>
                        {selectable.map((r) => <option key={r.cluster} value={r.cluster}>{r.name}</option>)}
                      </select>
                      {mergeTarget && <p className="mb-3 text-xs text-text-secondary">
                        {selected.count} + {rows.find((r) => r.cluster === mergeTarget)?.count || 0} {tr('interventi (nessuno cancellato)', 'turns (none deleted)')}
                      </p>}
                      {mergeTarget && samples?.speakers.find((s) => s.speaker_cluster === mergeTarget)?.samples[0] && (
                        <Button variant="ghost" size="sm" onClick={() => {
                          const clip = samples?.speakers.find((s) => s.speaker_cluster === mergeTarget)?.samples[0];
                          if (clip) playClip(clip);
                        }}>{tr('Ascolta voce di destinazione', 'Play target voice')}</Button>
                      )}
                      <div className="mt-3 flex gap-2">
                        <Button disabled={!canEdit || !mergeTarget} size="sm"
                          onClick={() => void commit('merge', selected.cluster, { target: mergeTarget })}>
                          <GitMerge className="h-4 w-4" aria-hidden="true" />{tr('Conferma unione', 'Confirm merge')}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setAction('none')}>{tr('Annulla', 'Cancel')}</Button>
                      </div>
                    </>
                  ) : (
                    <>
                      <h5 className="text-sm font-semibold">{tr('Escludere questa voce?', 'Exclude this voice?')}</h5>
                      <p className="mt-1 text-xs text-text-secondary">
                        {selected.count === 0
                          ? tr('Nessun intervento collegato: la voce sarà nascosta, ma recuperabile.', 'No linked turns: this voice will be hidden but recoverable.')
                          : tr('Gli interventi resteranno nel testo come “Non identificato”. Nessun contenuto sarà eliminato.', 'Turns will remain as “Unidentified”. No content will be deleted.')}
                      </p>
                      <div className="mt-3 flex gap-2">
                        <Button variant="warning" size="sm" disabled={!canEdit}
                          onClick={() => void commit('exclude', selected.cluster)}>
                          {tr('Conferma esclusione', 'Confirm exclusion')}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setAction('none')}>{tr('Annulla', 'Cancel')}</Button>
                      </div>
                    </>
                  )}
                </div>
              )}
              {canEdit && showActions && action === 'none' && selected.status !== 'merged' && selected.status !== 'excluded' && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setAction('merge')}>
                    <GitMerge className="h-4 w-4" aria-hidden="true" />{tr('Unisci voce', 'Merge voice')}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setAction('exclude')}>
                    {tr('Escludi voce', 'Exclude voice')}
                  </Button>
                </div>
              )}
              {canEdit && (selected.status === 'merged' || selected.status === 'excluded') && (
                <Button variant="secondary" size="sm" className="mt-3"
                  onClick={() => void commit('restore', selected.cluster)}>
                  <RotateCcw className="h-4 w-4" aria-hidden="true" />
                  {tr('Ripristina voce', 'Restore voice')}
                </Button>
              )}
              <div className="mt-3 border-t border-border-subtle pt-2">
                <button type="button" className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-text-primary"
                  aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                  {tr('Dettagli tecnici', 'Technical details')}
                </button>
                {advanced && <div className="mt-2 text-xs text-text-muted">
                  <p>{tr('Identificatore originale: ', 'Original cluster: ')}<code>{selected.cluster}</code></p>
                  <p>{tr('Gruppo attuale: ', 'Current group: ')}<code>{selected.group}</code></p>
                  <p>{tr('Origine: ', 'Source: ')}<code>{transcription.stats?.speaker_diarization?.provider || 'local'}</code></p>
                </div>}
              </div>
            </div>
          )}
          </SpeakerTimeline>
          {rows.some((r) => r.status === 'merged' || r.status === 'excluded') && (
            <button type="button" aria-expanded={showHidden}
              onClick={() => { setShowHidden((value) => !value); setFilter('all'); }}
              className="mt-3 inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-xs text-text-secondary hover:bg-bg-elevated focus-visible:outline-2 focus-visible:outline-border-focus">
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
              {showHidden ? tr('Nascondi voci unite ed escluse', 'Hide merged and excluded voices') :
                tr('Mostra voci unite ed escluse', 'Show merged and excluded voices')}
            </button>
          )}
        </>
      )}
    </section>
  );
}
