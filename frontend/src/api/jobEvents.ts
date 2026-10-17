import { ApiClient, type TranscriptionJob } from './apiClient';

export const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const RECOVERY_RECONNECT_DELAY_MS = 5000;

export interface JobEventSnapshot extends Partial<TranscriptionJob> {
  id: string;
  status: string;
  current_step: string;
  progress: number;
  updated_at: number;
  sequence?: number;
}

interface JobEventWire extends Partial<TranscriptionJob> {
  // The persisted SSE event uses job_id, and its id is an event id.
  job_id?: string;
  sequence?: number;
  payload?: Record<string, unknown> | null;
  event_payload?: Record<string, unknown> | null;
  event_created_at?: number;
}

export interface JobEventFollowerOptions {
  onUpdate: (job: JobEventSnapshot) => void;
  onTerminal?: (job: JobEventSnapshot) => void;
  onRecoveryError?: (error: unknown) => void;
}

/**
 * Follow one persisted job through the canonical SSE event stream.
 *
 * The stream is the normal path. A GET snapshot is used only after a stream
 * failure so reconnect/recovery can reconcile terminal state without turning
 * normal progress back into polling.
 */
function runJobEventStream(jobId: string, options: JobEventFollowerOptions): () => void {
  let source: EventSource | null = null;
  let reconnectTimer: number | null = null;
  let stopped = false;
  let lastSequence = 0;

  const closeSource = () => {
    source?.close();
    source = null;
  };

  const clearReconnect = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const stop = () => {
    stopped = true;
    clearReconnect();
    closeSource();
  };

  const publish = (wire: JobEventWire) => {
    if (stopped) return;
    const sequence = Number(wire.sequence || 0);
    if (sequence > 0 && sequence <= lastSequence) return;
    if (sequence > 0) lastSequence = sequence;

    // SSE event rows and GET job snapshots are different wire contracts.
    // Never replace the canonical job ID with the SQLite event-row ID.
    const normalized: JobEventSnapshot = {
      id: jobId,
      status: wire.status || 'running',
      current_step: wire.current_step || wire.status || 'running',
      progress: Number(wire.progress || 0),
      updated_at: wire.updated_at ?? wire.event_created_at ?? wire.created_at ?? 0,
      // GET snapshots contain the original request payload (potentially a
      // sensitive prompt), whereas SSE rows use payload for progress only.
      progress_detail: wire.job_id
        ? wire.event_payload ?? wire.payload ?? wire.progress_detail
        : wire.event_payload ?? wire.progress_detail,
      sequence: wire.sequence,
    };
    options.onUpdate(normalized);
    if (TERMINAL_JOB_STATUSES.has(normalized.status)) {
      options.onTerminal?.(normalized);
      stop();
    }
  };

  const scheduleReconnect = () => {
    if (stopped || reconnectTimer !== null) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECOVERY_RECONNECT_DELAY_MS);
  };

  const recover = async () => {
    try {
      const snapshot = await ApiClient.getJob(jobId);
      if (stopped) return;
      publish(snapshot);
      if (!stopped) scheduleReconnect();
    } catch (error) {
      if (stopped) return;
      options.onRecoveryError?.(error);
      scheduleReconnect();
    }
  };

  const connect = () => {
    if (stopped) return;
    closeSource();
    source = new EventSource(`/v1/jobs/${encodeURIComponent(jobId)}/events`);
    source.onmessage = (message) => {
      try {
        publish(JSON.parse(message.data) as JobEventWire);
      } catch (error) {
        options.onRecoveryError?.(error);
      }
    };
    source.onerror = () => {
      if (stopped) return;
      closeSource();
      void recover();
    };
  };

  connect();
  return stop;
}

/**
 * Multiplex one SSE stream per persisted job across Activities and Meeting.
 * A page only removes its own listener; another subscriber keeps the same
 * stream alive. No polling worker, job state or payload is persisted here.
 */
interface SharedJobStream {
  listeners: Set<JobEventFollowerOptions>;
  stop: () => void;
}
const sharedJobStreams = new Map<string, SharedJobStream>();

export function followJobEvents(jobId: string, options: JobEventFollowerOptions): () => void {
  let shared = sharedJobStreams.get(jobId);
  if (!shared) {
    const entry: SharedJobStream = { listeners: new Set(), stop: () => {} };
    sharedJobStreams.set(jobId, entry);
    entry.listeners.add(options);
    entry.stop = runJobEventStream(jobId, {
      onUpdate: (job) => {
        for (const listener of Array.from(entry.listeners)) listener.onUpdate(job);
      },
      onTerminal: (job) => {
        // A newly started retry/follower must get a new stream, not the
        // already-terminated connection.
        if (sharedJobStreams.get(jobId) === entry) sharedJobStreams.delete(jobId);
        for (const listener of Array.from(entry.listeners)) listener.onTerminal?.(job);
      },
      onRecoveryError: (error) => {
        for (const listener of Array.from(entry.listeners)) listener.onRecoveryError?.(error);
      },
    });
    shared = entry;
  } else {
    shared.listeners.add(options);
  }

  const instance = shared;
  return () => {
    instance.listeners.delete(options);
    if (instance.listeners.size === 0) {
      instance.stop();
      if (sharedJobStreams.get(jobId) === instance) sharedJobStreams.delete(jobId);
    }
  };
}
