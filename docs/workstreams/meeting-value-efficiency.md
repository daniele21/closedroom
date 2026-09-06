# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-14 integration candidate
Owner: meeting product, canonical job/persistence owners and local runtime
Baseline: dev `90c4e314`, 2026-09-06.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. PRS-11, PRS-12 and PRS-13 are integrated; PRS-14 is the current integration candidate. No production-model performance or memory gain is claimed without representative evidence.

- Meeting is primary; normal recording requires no technical choice.
- `Prepare notes` is explicit after Stop; `Transcript only` is secondary.
- Reuse valid transcript, then existing notes analysis. Ready notes open first; explicit tab selection wins.
- Audio/transcript survive enrichment failure/cancel. Local-first and explicit cloud opt-in remain unchanged.
- Canonical owners stay unchanged: RecordingStore capture, JobStore durable jobs, CatalogStore persisted runs/indexes, HeavyWorkloadArbiter heavy-work scheduling, runtime services managed cleanup.
- Excluded: rewrite, second scheduler/runtime/index owner, implicit cloud, mandatory visuals, unproven audio strategy.

## Work graph

| ID | Observable outcome | Owner paths/contracts | Depends on | State |
| --- | --- | --- | --- | --- |
| PRS-11 | Fast saved Meeting open | MeetingDetailPage, API client, visual hook | — | DONE |
| PRS-12 | One recoverable Prepare notes action | jobs, analysis/transcription services, Meeting UI | PRS-11 | DONE |
| PRS-13 | Consistent notes with less repeated inference | analysis templates/jobs/service/catalog reads | PRS-12 | DONE |
| PRS-14 | Verify/edit actions and decisions | notes schema/catalog, transcript, Meeting UI | PRS-13 | INTEGRATION |
| PRS-15 | Search complete local archive | CatalogStore, workspace/API/UI | — | READY |
| PRS-16 | Record safely while AI is busy | RecordingStore, resource policy/arbiter/runtime | — | READY |
| PRS-17 | Coherent macOS workspace | App/pages/components/design contracts | PRS-12,14,15,16 | BLOCKED |
| PRS-18 | Measured release | current-state, benchmarks, target-Mac evidence | selected increments | BLOCKED |

Default sequence: 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17. PRS-15/16 may advance earlier, but shared schema/service/UI edits remain serialized into coherent outcome PRs.

## PRS-11 — integrated

Saved Meeting core content loads independently from diagnostics and visual services. Accessory errors/retries stay local, stale route responses are ignored and terminal reloads are coalesced. Evidence includes focused tests and `saved-meeting-fast-open` FULL_MEDIA. Target WKWebView/TCC fidelity remains release evidence when material.

## PRS-12 — integrated

`Prepare notes` is a durable `meeting_preparation` JobStore parent that composes the existing transcription and analysis jobs. Durable identity covers recording source, effective ASR options and analysis/template identity; valid transcripts skip ASR. Cancel prevents future stages including admission races, restart interrupts incomplete work and explicit resume starts from the first missing stage. Meeting follows the parent SSE, exposes transcript before notes finish and does not promote output from failed/interrupted/cancelled preparation pipelines. Existing expert transcription/analysis APIs remain compatible. Integration evidence included owner/API/persistence tests plus `meeting-preparation-recovery` FULL_MEDIA and packaged-app smoke.

## PRS-13 — integrated shared structured notes

The default notes path now reduces overlapping inference without degrading the logical note views. `meeting_default` with no explicit `analysis_types` executes one internal `meeting_notes_shared` v2 analysis job instead of four overlapping physical jobs; `meeting_deep`, explicit analysis types and expert single analyses remain unchanged.

The canonical result is `closedroom.meeting_notes` schema v2 with a `generated` boundary containing summary, actions, decisions and risks. Every non-empty generated claim requires a canonical transcript segment reference with timing/speaker metadata when available. One persisted v2 run is projected at read time into stable `meeting_brief`, `action_items`, `decisions` and `risks_blockers` views without synthetic jobs or rows; old persisted v1 runs continue to read unchanged.

Structured cache identity includes transcript segment ids/timing/speaker/text. Short inputs use one extraction; long inputs use bounded source-aware chunks plus bounded aggregation, and oversize input fails explicitly rather than truncating. Source refs cannot escape the chunk/aggregation evidence supplied to the inference. The internal shared template remains hidden from the public template picker and `HeavyWorkloadArbiter` remains the only heavy-work scheduler.

Integration evidence covered schema/projection/cache/long-input/source-boundary tests, existing analysis/preparation suites, frontend deterministic checks, `meeting-preparation-recovery` FULL_MEDIA and selector-owned STRONG/package gates. Production model quality/latency/RSS and target WKWebView/TCC fidelity remain release deltas unless a comparable integration baseline exists.

## PRS-14 — verifiable, editable notes — integration candidate

Goal: let users verify generated actions/decisions against the meeting, correct them without destroying model output, and carry those corrections safely across restart and regeneration.

Implementation candidate:
- actions, decisions and risks receive deterministic item identity derived from kind + canonical source anchors + occurrence; identity is independent from generated wording, while each generated item also carries a content/source fingerprint;
- actions and decisions are editable in place in Meeting Analysis. Generated content remains immutable under `generated`; user corrections are stored as a distinct `user_edits` overlay and exposed through `effective` reads;
- each edit retains the generated item snapshot it was based on, including source refs, so an item removed by regeneration still has verifiable prior evidence rather than becoming an unanchored text fragment;
- `CatalogStore` analysis runs remain the only persistence owner. Overlay, revision metadata and conflict state live inside the canonical run result JSON; no second notes store or SQLite migration is introduced;
- analysis-run history is the revision chain. A later structured run inherits prior edits only when that revision has no explicit overlay state. An explicit empty `user_edits` set therefore prevents discarded corrections from being re-inherited;
- unchanged generated items safely reapply the prior correction. If wording/metadata changed, the generated value wins by default and the retained edit becomes `generated_changed`; if the item disappeared, it becomes `item_missing`. Neither case is silently remapped;
- for `generated_changed`, the user can explicitly rebase the retained edit onto the new generated fingerprint or use the regenerated version. For `item_missing`, ClosedRoom shows the previous generated text, retained correction and source timestamp but does not recreate removed content automatically; the safe recovery is explicit discard or a later regeneration;
- PATCH `/v1/analysis-runs/{run}/items/{action|decision}/{item}` requires the current generated fingerprint and returns 409 after a stale regeneration. DELETE of the item edit resolves/discards the overlay on the current revision;
- v2 Meeting views use `StructuredNotesEditor`; legacy/non-v2 analysis remains markdown. Evidence chips seek the saved recording to the referenced timestamp. Transcript, speakers, custom/deep analysis and runtime scheduling are unchanged.

Acceptance before merge:
- user edits never mutate `generated`, survive CatalogStore reopen and appear in the logical action/decision projections;
- generated/source changes create a new revision and an explicit conflict rather than applying the old correction silently;
- a removed generated item retains the prior correction plus source snapshot until explicit discard, without being synthetically re-created;
- stale PATCH after regeneration returns 409; explicit rebase/discard updates only the current canonical run;
- after discard on a later revision, reload does not inherit the old edit again;
- source evidence remains directly reachable from generated and retained-conflict items;
- old v2 runs without edit metadata upgrade read-time without migration and v1 runs remain unchanged;
- the automated `meeting-note-edit-revision` FULL_MEDIA journey proves evidence -> edit -> reload -> regenerate changed-item conflict -> explicit rebase recovery; deterministic domain/API/frontend tests separately cover the removed-item conflict because synthetic recreation is intentionally forbidden.

Checks: `test_structured_note_edits.py`, `test_structured_note_projection_edits.py`, `test_structured_note_catalog_persistence.py`, `test_structured_note_api.py`, `test_frontend_structured_notes_editor.py`, existing shared-notes/preparation suites, frontend lint/typecheck, browser FULL_MEDIA `meeting-note-edit-revision` plus existing Meeting journeys, and selector-owned STRONG packaged-app validation. Packaged WKWebView focus/accessibility and production-model behavior remain release confirmation when material.

## PRS-15 — complete search, bounded archive

Extend CatalogStore projection with bounded server-side search/pagination after verifying bundled SQLite full-text support. Search must reach content beyond preview/page limits, maintain stable paging/filtering, preserve index freshness across mutations and avoid whole-archive React extraction. Synthetic large-archive tests plus search -> source -> back FULL_MEDIA; STRONG expected.

## PRS-16 — recording while AI is busy

Resolve atomic capture/heavy-work admission for both orderings. Managed work may yield/cancel only at safe supported boundaries; no unsafe thread kill or false instant-start promise. Preserve data on wait/cancel/retry and keep external services caller-owned. Controlled worker/lifecycle races plus busy-AI -> record/stop -> resume FULL_MEDIA; physical capture/thermal evidence is release-only. STRONG expected.

## PRS-17 — coherent macOS workspace

Unify hierarchy across Today, Meeting, Projects, themes and supported window sizes. Keep one dominant action per state, advanced tools discoverable, async navigation stable and focus/keyboard/reduced-motion semantics intact. Component/routing checks plus complete journey FULL_MEDIA; SCOPED expected unless contracts expand.

## Evidence and release

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates; material UI uses FULL_MEDIA. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE `dev -> main` requires FULL automation plus applicable target-Mac TCC/audio/WKWebView/VoiceOver, representative MLX/resources and PRS-9 audio evidence. Use `python3 scripts/real_environment_ui_evidence.py --build`. Numeric budgets come from comparable baseline measurements; missing data stays unknown.

Durable owners: `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and `docs/current-state.md`. Complete a slice only when code, consumers, recovery, docs and evidence agree.
