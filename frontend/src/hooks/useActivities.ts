import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, type ActivitySnapshot } from '../api/apiClient';
import { TERMINAL_JOB_STATUSES } from '../api/jobEvents';

/** Shell-owned discovery uses lightweight summaries; it never starts or retries work. */
export function useActivities(enabled = true) {
  const [snapshot, setSnapshot] = useState<ActivitySnapshot>({ items: [], capture_blocked: false, active_count: 0, queue_depth: 0 });
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(false);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const requestController = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (!mounted.current || inFlight.current) return;
    inFlight.current = true;
    const epoch = generation.current;
    const controller = new AbortController();
    requestController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const next = await ApiClient.listActivities(controller.signal);
      if (mounted.current && generation.current === epoch) { setSnapshot(next); setStale(false); }
    } catch {
      if (mounted.current && generation.current === epoch) setStale(true);
    } finally {
      window.clearTimeout(timeout);
      requestController.current = null;
      inFlight.current = false;
      if (mounted.current && generation.current === epoch) setLoading(false);
    }
  }, []);
  useEffect(() => {
    generation.current += 1;
    mounted.current = enabled;
    if (!enabled) { setSnapshot({ items: [], capture_blocked: false, active_count: 0, queue_depth: 0 }); setLoading(false); return; }
    void refresh();
    // Discovery also sees jobs submitted from another window. No full results or prompts are fetched.
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    const onVisible = () => { if (!document.hidden) void refresh(); };
    window.addEventListener('focus', onVisible);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      generation.current += 1;
      mounted.current = false;
      requestController.current?.abort();
      window.clearInterval(timer);
      window.removeEventListener('focus', onVisible);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled, refresh]);
  const ids = new Set(snapshot.items.map((job) => job.id));
  const jobs = snapshot.items.filter((job) => !job.parent_job_id || !ids.has(job.parent_job_id));
  const activeCount = jobs.filter((job) => !TERMINAL_JOB_STATUSES.has(job.status)).length;
  return { ...snapshot, children: snapshot.items.filter((job) => Boolean(job.parent_job_id)), items: jobs, activeCount, stale, loading, refresh };
}
export type ActivitiesState = ReturnType<typeof useActivities>;
