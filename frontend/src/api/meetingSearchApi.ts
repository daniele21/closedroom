import type { Meeting } from './apiClient';

export interface MeetingArchiveSearchResponse {
  items: Meeting[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

let sessionPromise: Promise<void> | null = null;

async function ensureSession(): Promise<void> {
  if (!sessionPromise) {
    sessionPromise = fetch('/v1/session', { credentials: 'same-origin' }).then((response) => {
      if (!response.ok) throw new Error(`Session bootstrap failed: HTTP ${response.status}`);
    });
  }
  return sessionPromise;
}

async function requestArchive(url: string, signal?: AbortSignal, retrying = false): Promise<Response> {
  await ensureSession();
  const response = await fetch(url, { credentials: 'same-origin', signal });
  if (response.ok) return response;
  if (response.status === 401 && !retrying) {
    sessionPromise = null;
    return requestArchive(url, signal, true);
  }

  let detail = `HTTP ${response.status}`;
  try {
    const payload = await response.json();
    detail = payload.detail || detail;
  } catch {
    // Preserve the HTTP status when the server did not return a JSON error payload.
  }
  throw new Error(detail);
}

export async function searchMeetingArchive(
  query: string,
  page = 1,
  limit = 25,
  signal?: AbortSignal,
): Promise<MeetingArchiveSearchResponse> {
  const params = new URLSearchParams({
    q: query,
    page: String(Math.max(1, page)),
    limit: String(Math.max(1, Math.min(limit, 50))),
  });
  return (await requestArchive(`/v1/meetings?${params.toString()}`, signal)).json();
}
