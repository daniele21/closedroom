import { useCallback, useEffect, useRef, useState } from 'react';
import type { SpeakerClip } from '../api/apiClient';

export interface SpeakerTurn extends SpeakerClip {
  text?: string;
}

interface PlaybackState {
  mode: 'idle' | 'sample' | 'turns';
  playing: boolean;
  current: SpeakerTurn | null;
  index: number;
  total: number;
  error: string | null;
}

const initialState: PlaybackState = {
  mode: 'idle', playing: false, current: null, index: 0, total: 0, error: null,
};

/** One bounded audio element; all clips reference local recording tracks. */
export function useSpeakerReviewPlayback(recordingId: string, onStart?: () => void) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const activeRef = useRef<SpeakerTurn | null>(null);
  const queueRef = useRef<SpeakerTurn[]>([]);
  const indexRef = useRef(0);
  const [state, setState] = useState<PlaybackState>(initialState);

  const stop = useCallback(() => {
    activeRef.current = null;
    queueRef.current = [];
    indexRef.current = 0;
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.onloadedmetadata = null;
      audio.removeAttribute('src');
      audio.load();
    }
    setState(initialState);
  }, []);

  const playEntry = useCallback((clip: SpeakerTurn, index: number, mode: 'sample' | 'turns') => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(clip.start) || !Number.isFinite(clip.end) || clip.end <= clip.start) {
      setState((current) => ({ ...current, playing: false, error: 'Intervallo audio non valido.' }));
      return;
    }
    activeRef.current = clip;
    indexRef.current = index;
    const url = `/v1/recordings/${encodeURIComponent(recordingId)}/tracks/${encodeURIComponent(clip.track_id)}/audio`;
    const attemptPlay = () => {
      if (activeRef.current !== clip) return;
      try {
        audio.currentTime = clip.start;
        void audio.play().then(() => {
          if (activeRef.current === clip) {
            setState((current) => ({ ...current, playing: true, error: null }));
          }
        }).catch(() => {
          if (activeRef.current === clip) {
            setState((current) => ({ ...current, playing: false, error: 'Audio non riproducibile su questo dispositivo.' }));
          }
        });
      } catch {
        setState((current) => ({ ...current, playing: false, error: 'Impossibile raggiungere questo punto dell’audio.' }));
      }
    };
    audio.pause();
    setState({
      mode, playing: false, current: clip, index,
      total: mode === 'turns' ? queueRef.current.length : 1, error: null,
    });
    if (audio.getAttribute('src') !== url) {
      audio.onloadedmetadata = attemptPlay;
      audio.setAttribute('src', url);
      audio.load();
    } else if (audio.readyState >= 1) {
      audio.onloadedmetadata = null;
      attemptPlay();
    } else {
      audio.onloadedmetadata = attemptPlay;
    }
  }, [recordingId]);

  const playSample = useCallback((clip: SpeakerClip) => {
    onStart?.();
    queueRef.current = [];
    playEntry(clip, 0, 'sample');
  }, [onStart, playEntry]);

  const playTurns = useCallback((turns: SpeakerTurn[]) => {
    const valid = turns
      .filter((s) => s.track_id && Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)
      .sort((a, b) => a.start - b.start || a.end - b.end);
    if (!valid.length) {
      setState({ ...initialState, error: 'Nessun intervento audio disponibile per questa voce.' });
      return;
    }
    onStart?.();
    queueRef.current = valid;
    playEntry(valid[0], 0, 'turns');
  }, [onStart, playEntry]);

  const advance = useCallback((offset: number) => {
    const queue = queueRef.current;
    const nextIndex = indexRef.current + offset;
    if (queue.length && nextIndex >= 0 && nextIndex < queue.length) {
      playEntry(queue[nextIndex], nextIndex, 'turns');
    } else {
      stop();
    }
  }, [playEntry, stop]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !activeRef.current) return;
    if (audio.paused) {
      void audio.play().catch(() => {
        setState((current) => ({ ...current, error: 'Riproduzione audio non disponibile.' }));
      });
    } else {
      audio.pause();
    }
  }, []);

  const onTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    const current = activeRef.current;
    if (!audio || !current || !Number.isFinite(audio.currentTime)) return;
    if (audio.currentTime >= current.end - 0.04) {
      if (queueRef.current.length) advance(1);
      else stop();
    }
  }, [advance, stop]);

  useEffect(() => () => stop(), [recordingId, stop]);

  return {
    audioRef, state, stop, playSample, playTurns, next: () => advance(1),
    previous: () => advance(-1), toggle, onTimeUpdate,
    onPause: () => setState((current) => ({ ...current, playing: false })),
    onPlay: () => setState((current) => ({ ...current, playing: true })),
    onEnded: () => { if (queueRef.current.length) advance(1); else stop(); },
    onError: () => {
      if (activeRef.current) {
        setState((current) => ({ ...current, playing: false, error: 'Traccia locale non disponibile. Verifica che l’audio sia ancora presente.' }));
      }
    },
  };
}
