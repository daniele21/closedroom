import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, type Recording, type TranscriptionJob } from '../api/apiClient';

type TranscriptionOptions = Parameters<typeof ApiClient.createTranscriptionJob>[1];

export interface AudioImportTask {
  id: string;
  name: string;
  phase: 'uploading' | 'submitting' | 'submitted' | 'cancelling' | 'cancelled' | 'failed';
  recordingId?: string;
  jobId?: string;
  error?: string;
}

/**
 * MainApp owns both the file and the upload->job handoff. Navigating away
 * unmounts only a page; the submit request and its in-memory key survive.
 * The backend retains the resulting source and job, not this UI state.
 */
export function useAudioImports(enabled = true) {
  const [items, setItems] = useState<AudioImportTask[]>([]);
  const mounted = useRef(true);
  const cancels = useRef(new Set<string>());
  const uploadControllers = useRef(new Map<string, AbortController>());
  const update = useCallback((id: string, next: Partial<AudioImportTask>) => {
    if (!mounted.current) return;
    setItems((current) => current.map((item) => item.id === id ? { ...item, ...next } : item));
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const startTranscription = useCallback((
    file: File,
    options: TranscriptionOptions,
  ): string => {
    if (!enabled) throw new Error('Audio import is unavailable');
    const id = crypto.randomUUID();
    setItems((current) => [{ id, name: file.name, phase: 'uploading' as const }, ...current].slice(0, 20));

    const run = async () => {
      let source: Recording | undefined;
      const controller = new AbortController();
      uploadControllers.current.set(id, controller);
      try {
        source = await ApiClient.importRecordingAudio(
          file, { title: file.name.replace(/\.[^.]+$/, ''), language: options.language },
          id, controller.signal,
        );
        update(id, { recordingId: source.id });
        if (cancels.current.has(id)) {
          update(id, { phase: 'cancelled' });
          return;
        }
        update(id, { phase: 'submitting' });
        const job: TranscriptionJob = await ApiClient.createTranscriptionJob(source.id, options, id);
        update(id, { phase: 'submitted', jobId: job.id });
      } catch (error) {
        update(id, {
          phase: cancels.current.has(id) ? 'cancelled' : 'failed',
          recordingId: source?.id,
          error: error instanceof Error ? error.message : String(error),
        });
      } finally {
        uploadControllers.current.delete(id);
        cancels.current.delete(id);
      }
    };
    void run();
    return id;
  }, [enabled, update]);

  const cancel = useCallback(async (id: string) => {
    const task = items.find((item) => item.id === id);
    if (!task || !['uploading', 'submitting'].includes(task.phase)) return;
    if (task.phase === 'submitting') {
      // A POST may already have been admitted. Never pretend a submission
      // was cancelled by cancelling only the preceding transfer.
      return;
    }
    cancels.current.add(id);
    update(id, { phase: 'cancelling' });
    try {
      const result = await ApiClient.cancelRecordingAudioImport(id);
      if (result.cancel_requested) uploadControllers.current.get(id)?.abort();
      if (!result.cancel_requested) {
        // The source was committed just before cancellation. The upload
        // handoff will not submit AI because cancels.current is set.
        update(id, { phase: 'cancelled' });
      }
    } catch (error) {
      cancels.current.delete(id);
      update(id, { phase: 'uploading', error: error instanceof Error ? error.message : String(error) });
    }
  }, [items, update]);

  return { items, startTranscription, cancel };
}

export type AudioImportsState = ReturnType<typeof useAudioImports>;
