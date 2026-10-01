import type { AnalysisRun } from './apiClient';

export type StructuredNoteItemKind = 'action' | 'decision';

export interface StructuredNoteSourceRef {
  segment_id: string | number;
  start?: number | null;
  end?: number | null;
  speaker?: string | null;
}

export interface StructuredNoteItem {
  item_id: string;
  generated_hash: string;
  text: string;
  source_refs: StructuredNoteSourceRef[];
  user_edited?: boolean;
  owner?: string | null;
  due?: string | null;
  status?: string | null;
  rationale?: string | null;
  impact?: string | null;
}

export interface StructuredNoteEdit {
  item_kind: StructuredNoteItemKind;
  item_id: string;
  base_generated_hash: string;
  base_run_id: string;
  base_generated?: StructuredNoteItem | null;
  fields: Record<string, string | null>;
  updated_at: number;
}

export interface StructuredNoteConflict {
  item_kind: StructuredNoteItemKind;
  item_id: string;
  reason: 'generated_changed' | 'item_missing' | string;
  retained_edit: StructuredNoteEdit;
  generated?: StructuredNoteItem | null;
}

export interface StructuredNotesResult {
  schema: { id: string; version: number };
  generated: {
    summary?: { text?: string; source_refs?: StructuredNoteSourceRef[] };
    actions?: StructuredNoteItem[];
    decisions?: StructuredNoteItem[];
    risks?: StructuredNoteItem[];
  };
  effective?: {
    summary?: { text?: string; source_refs?: StructuredNoteSourceRef[] };
    actions?: StructuredNoteItem[];
    decisions?: StructuredNoteItem[];
    risks?: StructuredNoteItem[];
  };
  revision?: { number?: number; run_id?: string; supersedes_run_id?: string | null };
  user_edits?: StructuredNoteEdit[];
  conflicts?: StructuredNoteConflict[];
  markdown?: string;
}

export function isStructuredNotesResult(value: unknown): value is StructuredNotesResult {
  if (!value || typeof value !== 'object') return false;
  const result = value as StructuredNotesResult;
  return result.schema?.id === 'closedroom.meeting_notes'
    && result.schema?.version === 2
    && Boolean(result.generated);
}

export function structuredSourceRunId(run: AnalysisRun): string {
  const sourceRunId = (run as AnalysisRun & { source_run_id?: string }).source_run_id;
  return sourceRunId || run.id.split('::', 1)[0];
}

async function requestStructuredRun(path: string, init: RequestInit): Promise<AnalysisRun> {
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
      detail = typeof payload?.detail === 'string' ? payload.detail : JSON.stringify(payload?.detail || detail);
    } catch {
      // Keep HTTP status text for non-JSON failures.
    }
    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export function editStructuredNoteItem(
  runId: string,
  itemKind: StructuredNoteItemKind,
  itemId: string,
  payload: { base_generated_hash: string; fields: Record<string, string | null> },
): Promise<AnalysisRun> {
  return requestStructuredRun(
    `/v1/analysis-runs/${encodeURIComponent(runId)}/items/${itemKind}/${encodeURIComponent(itemId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export function discardStructuredNoteEdit(
  runId: string,
  itemKind: StructuredNoteItemKind,
  itemId: string,
): Promise<AnalysisRun> {
  return requestStructuredRun(
    `/v1/analysis-runs/${encodeURIComponent(runId)}/items/${itemKind}/${encodeURIComponent(itemId)}/edit`,
    { method: 'DELETE' },
  );
}
