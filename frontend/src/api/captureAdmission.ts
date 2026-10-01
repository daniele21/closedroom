export interface CaptureReservation {
  reservation_id: string;
  status: 'waiting' | 'granted';
  active_workloads: number;
  queued_workloads: number;
  waited_seconds: number;
}

class CaptureReservationRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function reservationRequest(
  url: string,
  options: RequestInit = {},
  retrying = false,
): Promise<Response> {
  const response = await fetch(url, {
    ...options,
    credentials: options.credentials ?? 'same-origin',
  });
  if (response.ok) return response;

  if (response.status === 401 && !retrying) {
    const session = await fetch('/v1/session', { credentials: 'same-origin' });
    if (session.ok) return reservationRequest(url, options, true);
  }

  let detail = `HTTP ${response.status}`;
  try {
    const payload = await response.json();
    detail = payload.detail || detail;
  } catch {
    const text = await response.text();
    if (text) detail = text;
  }
  throw new CaptureReservationRequestError(response.status, detail);
}

export async function createCaptureReservation(): Promise<CaptureReservation> {
  return (await reservationRequest('/v1/capture/reservations', { method: 'POST' })).json();
}

export async function getCaptureReservation(reservationId: string): Promise<CaptureReservation> {
  return (await reservationRequest(`/v1/capture/reservations/${reservationId}`)).json();
}

export async function releaseCaptureReservation(reservationId: string): Promise<void> {
  try {
    await reservationRequest(`/v1/capture/reservations/${reservationId}`, { method: 'DELETE' });
  } catch (error) {
    if (error instanceof CaptureReservationRequestError && error.status === 404) return;
    throw error;
  }
}

export function releaseCaptureReservationOnUnload(reservationId: string): void {
  navigator.sendBeacon?.(`/v1/capture/reservations/${reservationId}/release`, new Blob());
}
