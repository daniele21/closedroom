import { useMemo, useState } from 'react';
import { AlertTriangle, Check, Clock3, Pencil, RotateCcw, Save, X } from 'lucide-react';

import type { AnalysisRun } from '../../api/apiClient';
import {
  discardStructuredNoteEdit,
  editStructuredNoteItem,
  isStructuredNotesResult,
  structuredSourceRunId,
  type StructuredNoteConflict,
  type StructuredNoteItem,
  type StructuredNoteItemKind,
  type StructuredNoteSourceRef,
} from '../../api/structuredNotes';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

interface StructuredNotesEditorProps {
  run: AnalysisRun;
  analysisType: string;
  lang: string;
  onSeek: (seconds: number) => void;
  onChanged: () => Promise<void> | void;
  readOnly?: boolean;
}

interface EditingState {
  kind: StructuredNoteItemKind;
  itemId: string;
  fields: Record<string, string>;
}

const fieldLabels: Record<StructuredNoteItemKind, Record<string, { it: string; en: string }>> = {
  action: {
    text: { it: 'Azione', en: 'Action' },
    owner: { it: 'Responsabile', en: 'Owner' },
    due: { it: 'Scadenza', en: 'Due' },
    status: { it: 'Stato', en: 'Status' },
  },
  decision: {
    text: { it: 'Decisione', en: 'Decision' },
    rationale: { it: 'Motivazione', en: 'Rationale' },
    impact: { it: 'Impatto', en: 'Impact' },
  },
};

function formatTimestamp(seconds: number): string {
  const rounded = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(rounded / 60);
  const secs = rounded % 60;
  return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function EvidenceRefs({ refs, onSeek }: { refs?: StructuredNoteSourceRef[]; onSeek: (seconds: number) => void }) {
  if (!refs?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Source evidence">
      {refs.map((ref, index) => {
        const label = typeof ref.start === 'number'
          ? `${formatTimestamp(ref.start)}${ref.speaker ? ` · ${ref.speaker}` : ''}`
          : `S${ref.segment_id}`;
        if (typeof ref.start !== 'number') {
          return (
            <span
              key={`${ref.segment_id}-${index}`}
              className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-bg-surface px-2 py-1 text-[10px] font-medium text-text-muted"
            >
              <Clock3 className="h-3 w-3" aria-hidden="true" />
              {label}
            </span>
          );
        }
        return (
          <button
            key={`${ref.segment_id}-${index}`}
            type="button"
            onClick={() => onSeek(ref.start as number)}
            className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-bg-surface px-2 py-1 text-[10px] font-medium text-accent transition-colors hover:bg-bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            title="Play source evidence"
          >
            <Clock3 className="h-3 w-3" aria-hidden="true" />
            {label}
          </button>
        );
      })}
    </div>
  );
}

function itemFields(kind: StructuredNoteItemKind, item: StructuredNoteItem): Record<string, string> {
  if (kind === 'action') {
    return {
      text: item.text || '',
      owner: item.owner || '',
      due: item.due || '',
      status: item.status || '',
    };
  }
  return {
    text: item.text || '',
    rationale: item.rationale || '',
    impact: item.impact || '',
  };
}

function conflictForItem(conflicts: StructuredNoteConflict[], kind: StructuredNoteItemKind, itemId: string) {
  return conflicts.find((conflict) => conflict.item_kind === kind && conflict.item_id === itemId);
}

export function StructuredNotesEditor({
  run,
  analysisType,
  lang,
  onSeek,
  onChanged,
  readOnly = false,
}: StructuredNotesEditorProps) {
  const result = isStructuredNotesResult(run.result) ? run.result : null;
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sourceRunId = structuredSourceRunId(run);

  const generated = result?.generated || {};
  const effective = result?.effective || generated;
  const conflicts = result?.conflicts || [];
  const generatedById = useMemo(() => {
    const index = new Map<string, StructuredNoteItem>();
    for (const item of [...(generated.actions || []), ...(generated.decisions || [])]) {
      if (item?.item_id) index.set(item.item_id, item);
    }
    return index;
  }, [generated.actions, generated.decisions]);

  if (!result) return null;

  const startEdit = (kind: StructuredNoteItemKind, item: StructuredNoteItem) => {
    setError(null);
    setEditing({ kind, itemId: item.item_id, fields: itemFields(kind, item) });
  };

  const saveEdit = async () => {
    if (!editing) return;
    const sourceItem = generatedById.get(editing.itemId);
    if (!sourceItem?.generated_hash) {
      setError(lang === 'it' ? 'La nota è cambiata. Ricarica il meeting.' : 'The note changed. Reload the meeting.');
      return;
    }
    const key = `${editing.kind}:${editing.itemId}:save`;
    setBusyKey(key);
    setError(null);
    try {
      await editStructuredNoteItem(sourceRunId, editing.kind, editing.itemId, {
        base_generated_hash: sourceItem.generated_hash,
        fields: Object.fromEntries(Object.entries(editing.fields).map(([field, value]) => [field, value || null])),
      });
      setEditing(null);
      await onChanged();
    } catch (err: any) {
      setError(err?.status === 409
        ? (lang === 'it' ? 'La nota è stata rigenerata. Ricarica e scegli quale versione mantenere.' : 'The note was regenerated. Reload and choose which version to keep.')
        : (err?.message || (lang === 'it' ? 'Impossibile salvare la modifica.' : 'Could not save the edit.')));
      if (err?.status === 409) await onChanged();
    } finally {
      setBusyKey(null);
    }
  };

  const resolveConflict = async (conflict: StructuredNoteConflict, keepEdit: boolean) => {
    const key = `${conflict.item_kind}:${conflict.item_id}:${keepEdit ? 'keep' : 'discard'}`;
    setBusyKey(key);
    setError(null);
    try {
      if (keepEdit && conflict.generated?.generated_hash) {
        await editStructuredNoteItem(sourceRunId, conflict.item_kind, conflict.item_id, {
          base_generated_hash: conflict.generated.generated_hash,
          fields: conflict.retained_edit.fields,
        });
      } else {
        await discardStructuredNoteEdit(sourceRunId, conflict.item_kind, conflict.item_id);
      }
      await onChanged();
    } catch (err: any) {
      setError(err?.message || (lang === 'it' ? 'Impossibile risolvere il conflitto.' : 'Could not resolve the conflict.'));
      if (err?.status === 409) await onChanged();
    } finally {
      setBusyKey(null);
    }
  };

  const renderItem = (kind: StructuredNoteItemKind, item: StructuredNoteItem) => {
    const sourceItem = generatedById.get(item.item_id) || item;
    const conflict = conflictForItem(conflicts, kind, item.item_id);
    const isEditing = editing?.kind === kind && editing.itemId === item.item_id;
    const labels = fieldLabels[kind];
    const editableFields = kind === 'action'
      ? ['text', 'owner', 'due', 'status']
      : ['text', 'rationale', 'impact'];

    return (
      <div key={item.item_id} className="rounded-xl border border-border-subtle bg-bg-surface/50 p-4">
        {conflict && (
          <div className="mb-3 rounded-lg border border-warning/40 bg-warning/10 p-3" role="status">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-text-primary">
                  {lang === 'it' ? 'La rigenerazione ha cambiato questa voce' : 'Regeneration changed this item'}
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-text-secondary">
                  {lang === 'it'
                    ? 'La tua correzione non è stata applicata automaticamente. Confrontala con la nuova versione e scegli esplicitamente.'
                    : 'Your correction was not applied automatically. Compare it with the new version and choose explicitly.'}
                </p>
                {conflict.retained_edit?.fields?.text && (
                  <div className="mt-2 rounded-md bg-bg-elevated px-2.5 py-2 text-[11px] text-text-secondary">
                    <span className="font-semibold text-text-primary">{lang === 'it' ? 'Tua modifica: ' : 'Your edit: '}</span>
                    {conflict.retained_edit.fields.text}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap gap-2">
                  {conflict.generated?.generated_hash && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={readOnly || busyKey !== null}
                      onClick={() => resolveConflict(conflict, true)}
                      isLoading={busyKey === `${conflict.item_kind}:${conflict.item_id}:keep`}
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden="true" />
                      {lang === 'it' ? 'Mantieni la mia modifica' : 'Keep my edit'}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={readOnly || busyKey !== null}
                    onClick={() => resolveConflict(conflict, false)}
                    isLoading={busyKey === `${conflict.item_kind}:${conflict.item_id}:discard`}
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    {lang === 'it' ? 'Usa la nuova versione' : 'Use regenerated'}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        {isEditing ? (
          <div className="flex flex-col gap-3">
            {editableFields.map((field) => (
              <label key={field} className="flex flex-col gap-1.5 text-[11px] font-semibold text-text-secondary">
                <span>{labels[field]?.[lang === 'it' ? 'it' : 'en'] || field}</span>
                {field === 'text' ? (
                  <textarea
                    rows={3}
                    value={editing.fields[field] || ''}
                    onChange={(event) => setEditing((current) => current ? {
                      ...current,
                      fields: { ...current.fields, [field]: event.target.value },
                    } : current)}
                    className="w-full resize-y rounded-lg border border-border-subtle bg-bg-elevated px-3 py-2 text-sm font-normal text-text-primary outline-none transition focus:border-border-focus focus:ring-2 focus:ring-border-focus/30"
                    autoFocus
                  />
                ) : (
                  <input
                    value={editing.fields[field] || ''}
                    onChange={(event) => setEditing((current) => current ? {
                      ...current,
                      fields: { ...current.fields, [field]: event.target.value },
                    } : current)}
                    className="w-full rounded-lg border border-border-subtle bg-bg-elevated px-3 py-2 text-sm font-normal text-text-primary outline-none transition focus:border-border-focus focus:ring-2 focus:ring-border-focus/30"
                  />
                )}
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" disabled={busyKey !== null} onClick={() => setEditing(null)}>
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                {lang === 'it' ? 'Annulla' : 'Cancel'}
              </Button>
              <Button
                size="sm"
                disabled={!editing.fields.text?.trim() || busyKey !== null}
                onClick={saveEdit}
                isLoading={busyKey === `${kind}:${item.item_id}:save`}
              >
                <Save className="h-3.5 w-3.5" aria-hidden="true" />
                {lang === 'it' ? 'Salva' : 'Save'}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-relaxed text-text-primary">{item.text}</p>
                {kind === 'action' && (item.owner || item.due || item.status) && (
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-text-muted">
                    {item.owner && <span><strong className="text-text-secondary">{lang === 'it' ? 'Responsabile' : 'Owner'}:</strong> {item.owner}</span>}
                    {item.due && <span><strong className="text-text-secondary">{lang === 'it' ? 'Scadenza' : 'Due'}:</strong> {item.due}</span>}
                    {item.status && <span><strong className="text-text-secondary">{lang === 'it' ? 'Stato' : 'Status'}:</strong> {item.status}</span>}
                  </div>
                )}
                {kind === 'decision' && (item.rationale || item.impact) && (
                  <div className="mt-2 space-y-1 text-[11px] text-text-muted">
                    {item.rationale && <p><strong className="text-text-secondary">{lang === 'it' ? 'Motivazione' : 'Rationale'}:</strong> {item.rationale}</p>}
                    {item.impact && <p><strong className="text-text-secondary">{lang === 'it' ? 'Impatto' : 'Impact'}:</strong> {item.impact}</p>}
                  </div>
                )}
                <EvidenceRefs refs={sourceItem.source_refs || item.source_refs} onSeek={onSeek} />
              </div>
              {!readOnly && !conflict && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => startEdit(kind, item)}
                  disabled={busyKey !== null}
                  className="shrink-0"
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  {lang === 'it' ? 'Modifica' : 'Edit'}
                </Button>
              )}
            </div>
            {item.user_edited && !conflict && (
              <div className="mt-2">
                <Badge variant="idle">{lang === 'it' ? 'Modificato da te' : 'Edited by you'}</Badge>
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  const actions = effective.actions || generated.actions || [];
  const decisions = effective.decisions || generated.decisions || [];
  const risks = effective.risks || generated.risks || [];
  const showSummary = analysisType === 'meeting_brief';
  const showActions = analysisType === 'meeting_brief' || analysisType === 'action_items';
  const showDecisions = analysisType === 'meeting_brief' || analysisType === 'decisions';
  const showRisks = analysisType === 'meeting_brief' || analysisType === 'risks_blockers';
  const missingConflicts = conflicts.filter((conflict) => (
    conflict.reason === 'item_missing'
    && ((conflict.item_kind === 'action' && showActions) || (conflict.item_kind === 'decision' && showDecisions))
  ));

  return (
    <div className="flex flex-col gap-5" data-structured-notes="v2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
        {typeof result.revision?.number === 'number' && (
          <Badge variant="idle">{lang === 'it' ? `Revisione ${result.revision.number}` : `Revision ${result.revision.number}`}</Badge>
        )}
        {conflicts.length > 0 && (
          <Badge variant="warning">
            {lang === 'it' ? `${conflicts.length} conflitto${conflicts.length === 1 ? '' : 'i'}` : `${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}`}
          </Badge>
        )}
        <span>{lang === 'it' ? 'Le fonti aprono il punto esatto della registrazione.' : 'Evidence opens the exact point in the recording.'}</span>
      </div>

      {error && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger" role="alert">
          {error}
        </div>
      )}

      {showSummary && generated.summary?.text && (
        <section>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-muted">
            {lang === 'it' ? 'Sintesi' : 'Summary'}
          </h4>
          <div className="rounded-xl border border-border-subtle bg-bg-surface/50 p-4">
            <p className="text-sm leading-relaxed text-text-primary">{generated.summary.text}</p>
            <EvidenceRefs refs={generated.summary.source_refs} onSeek={onSeek} />
          </div>
        </section>
      )}

      {showActions && (
        <section>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-muted">
            {lang === 'it' ? 'Azioni' : 'Actions'}
          </h4>
          <div className="flex flex-col gap-2">
            {actions.length ? actions.map((item) => renderItem('action', item)) : (
              <p className="rounded-xl border border-border-subtle bg-bg-surface/30 px-4 py-3 text-xs text-text-muted">
                {lang === 'it' ? 'Nessuna azione identificata.' : 'No actions identified.'}
              </p>
            )}
          </div>
        </section>
      )}

      {showDecisions && (
        <section>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-muted">
            {lang === 'it' ? 'Decisioni' : 'Decisions'}
          </h4>
          <div className="flex flex-col gap-2">
            {decisions.length ? decisions.map((item) => renderItem('decision', item)) : (
              <p className="rounded-xl border border-border-subtle bg-bg-surface/30 px-4 py-3 text-xs text-text-muted">
                {lang === 'it' ? 'Nessuna decisione identificata.' : 'No decisions identified.'}
              </p>
            )}
          </div>
        </section>
      )}

      {missingConflicts.length > 0 && (
        <section data-note-conflict="item-missing">
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-warning">
            {lang === 'it' ? 'Correzioni da verificare' : 'Edits to review'}
          </h4>
          <div className="flex flex-col gap-2">
            {missingConflicts.map((conflict) => {
              const sourceItem = conflict.retained_edit.base_generated;
              const editedText = conflict.retained_edit.fields?.text;
              const key = `${conflict.item_kind}:${conflict.item_id}:discard`;
              return (
                <div
                  key={`${conflict.item_kind}:${conflict.item_id}`}
                  className="rounded-xl border border-warning/40 bg-warning/10 p-4"
                  role="status"
                >
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-text-primary">
                        {lang === 'it' ? 'Voce rimossa dalla rigenerazione' : 'Item removed by regeneration'}
                      </p>
                      <p className="mt-1 text-[11px] leading-relaxed text-text-secondary">
                        {lang === 'it'
                          ? 'La nuova revisione non contiene più questa voce. ClosedRoom conserva la tua correzione e la fonte, ma non ricrea automaticamente contenuto che il modello ha rimosso.'
                          : 'The new revision no longer contains this item. ClosedRoom retains your edit and its evidence, but does not automatically recreate content the model removed.'}
                      </p>
                      {sourceItem?.text && (
                        <div className="mt-2 rounded-md bg-bg-elevated px-2.5 py-2 text-[11px] text-text-secondary">
                          <span className="font-semibold text-text-primary">{lang === 'it' ? 'Versione precedente: ' : 'Previous generated: '}</span>
                          {sourceItem.text}
                        </div>
                      )}
                      {editedText && (
                        <div className="mt-2 rounded-md bg-bg-elevated px-2.5 py-2 text-[11px] text-text-secondary">
                          <span className="font-semibold text-text-primary">{lang === 'it' ? 'Tua modifica: ' : 'Your edit: '}</span>
                          {editedText}
                        </div>
                      )}
                      <EvidenceRefs refs={sourceItem?.source_refs} onSeek={onSeek} />
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={readOnly || busyKey !== null}
                          onClick={() => resolveConflict(conflict, false)}
                          isLoading={busyKey === key}
                        >
                          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                          {lang === 'it' ? 'Scarta la correzione' : 'Discard edit'}
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {showRisks && (
        <section>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-muted">
            {lang === 'it' ? 'Rischi e blocchi' : 'Risks and blockers'}
          </h4>
          <div className="flex flex-col gap-2">
            {risks.length ? risks.map((item) => (
              <div key={item.item_id} className="rounded-xl border border-border-subtle bg-bg-surface/50 p-4">
                <p className="text-sm leading-relaxed text-text-primary">{item.text}</p>
                {item.impact && <p className="mt-1 text-[11px] text-text-muted">{item.impact}</p>}
                <EvidenceRefs refs={item.source_refs} onSeek={onSeek} />
              </div>
            )) : (
              <p className="rounded-xl border border-border-subtle bg-bg-surface/30 px-4 py-3 text-xs text-text-muted">
                {lang === 'it' ? 'Nessun rischio identificato.' : 'No risks identified.'}
              </p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}