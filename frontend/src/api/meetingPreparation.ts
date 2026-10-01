import type { TranscriptionJob } from './apiClient';

async function requestPreparation(
  path: string,
  init: RequestInit = {},
): Promise<TranscriptionJob> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`.trim();
    try {
      const payload = await response.json();
      detail = String(payload?.detail || detail);
    } catch {
      // Keep the status text when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

export function prepareMeetingNotes(recordingId: string): Promise<TranscriptionJob> {
  return requestPreparation(`/v1/meetings/${recordingId}/prepare`, {
    method: 'POST',
  });
}

export function cancelMeetingPreparation(
  recordingId: string,
  jobId: string,
): Promise<TranscriptionJob> {
  return requestPreparation(`/v1/meetings/${recordingId}/preparation-jobs/${jobId}/cancel`, {
    method: 'POST',
  });
}
