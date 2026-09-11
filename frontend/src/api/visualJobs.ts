import type { TranscriptionJob } from './apiClient';

async function requestVisualJob(
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

export function createVisualIntelligenceJob(recordingId: string): Promise<TranscriptionJob> {
  return requestVisualJob(`/v1/recordings/${recordingId}/visual-intelligence-jobs`, {
    method: 'POST',
  });
}

export function cancelVisualIntelligenceJob(jobId: string): Promise<TranscriptionJob> {
  return requestVisualJob(`/v1/visual-intelligence-jobs/${jobId}/cancel`, {
    method: 'POST',
  });
}
