# Architectural consolidation

Status: ACTIVE

## Outcome

Keep ClosedRoom's current local-first product behavior while reducing structural risk in the fastest-growing owners. The result should make recording, meeting review, transcription, persistence, native capture, and Local AI runtime boundaries easier to extend without introducing parallel state or weakening recovery/privacy/resource invariants.

This work is architectural consolidation, not a product redesign. User-visible behavior must remain equivalent unless a lane explicitly documents a bug fix discovered during extraction.

## Axes

- PRODUCT: PRODUCT_NONE by default; escalate a lane only if behavior materially changes.
- DELIVERY: ITERATION per lane, then INTEGRATION into `dev`.
- VALIDATION: STRONG overall because the work crosses shared contracts, persistence/capture lifecycle, native helpers, and critical UI state; individual UI-only extractions may use SCOPED until integration.
- EXECUTION: AGENT_LOCAL where deterministic source tests are available; REMOTE_AUTOMATED for required macOS/build/browser gates unavailable locally; REAL_ENVIRONMENT remains release-only unless a lane changes target-Mac semantics.

## Durable invariants

- Local-first remains the default; no new implicit cloud path or screenshot/audio transfer.
- `RecordingStore` remains the canonical recording aggregate facade even when implementation delegates internally.
- `HeavyWorkloadArbiter` remains the sole process-wide owner for heavy-work scheduling and capture priority.
- Recording, job, model, screenshot, and native-capture lifecycles remain bounded, cancellable, restart-safe where currently supported, and clean up run-owned resources.
- Filesystem remains the owner of large meeting artifacts; SQLite remains the query/index projection.
- Frontend refactors must not change the settled Meeting-first task model or expose implementation concepts in the golden path.
- Native capture remains behind the existing process/JSON protocol and macOS permission boundary.
- Korgis/local runtime consolidation must not make ClosedRoom depend on new remote services.

## Parallel lanes

### AC-1 — Recorder state machine
Status: ACTIVE

Observable outcome: recording orchestration uses one explicit typed transition model instead of independent booleans/refs for mutually exclusive lifecycle states.

Write boundary:
- `frontend/src/hooks/useRecorder.ts`
- new recorder state/transition module(s)
- focused frontend contract tests

Acceptance:
- impossible combinations such as recording + preparing/stopping are unrepresentable or normalized;
- existing browser/native fallback, cancellation, capture reservation and cleanup behavior stays intact;
- existing recording UI API remains compatible during the first extraction.

### AC-2 — Meeting and overlay UI decomposition
Status: ACTIVE

Observable outcome: `MeetingDetailPage` and `RecordingOverlayPage` coordinate feature hooks/components rather than owning accessory fetching, screenshot/display orchestration, and analysis actions directly.

Write boundary:
- `frontend/src/pages/MeetingDetailPage.tsx`
- `frontend/src/pages/RecordingOverlayPage.tsx`
- new page-scoped hooks/components
- focused frontend contract tests

Acceptance:
- no task-flow redesign;
- screenshot/display selection and saved-meeting evidence behavior remain unchanged;
- page-level state/effect counts materially decrease.

### AC-3 — Transcription application boundary
Status: ACTIVE

Observable outcome: upload/path/recording transcription routes adapt HTTP inputs to shared application use cases; provider/cache/diarization/persistence policy no longer lives in a 300-line route handler.

Write boundary:
- `src/local_asr_server/routers/transcriptions.py`
- `src/local_asr_server/services/transcription_service.py` or a new transcription application module
- direct transcription API/service tests

Acceptance:
- one canonical orchestration path for equivalent ASR work;
- streaming remains an adapter concern while transcription result construction/persistence is shared;
- public API responses and cache identities stay compatible.

### AC-4 — RecordingStore internal decomposition
Status: ACTIVE

Observable outcome: `RecordingStore` remains the canonical facade but delegates screenshot/visual artifact persistence to cohesive internal collaborators.

Write boundary:
- `src/local_asr_server/recordings.py`
- new recording persistence modules
- recording/store tests

Acceptance:
- no second public owner for recording state;
- screenshot idempotency, manifest reconciliation, visual-source validity, atomic writes, finalize/recovery and catalog sync remain unchanged;
- `RecordingStore` line/method responsibility decreases without consumer churn.

### AC-5 — Native capture internal decomposition
Status: ACTIVE

Observable outcome: the native helper remains one executable/protocol but Swift implementation separates audio, displays/screenshots, permissions/diagnostics, and run lifecycle.

Write boundary:
- `src/local_asr_server/native_capture_helper/*.swift`
- package/build metadata only if required
- native capture contract tests

Acceptance:
- JSON protocol and Python `NativeCaptureManager` contract stay stable;
- screenshot worker, display refresh, overlay exclusion, audio capture and stop semantics remain behaviorally equivalent;
- no TCC/signing identity change.

### AC-6 — Local AI runtime port
Status: READY

Start after AC-3/AC-4 establish stable application boundaries.

Observable outcome: ClosedRoom application code depends on a small Local AI runtime port; the current `local-llm-server`/Korgis-compatible implementation sits behind the adapter.

Acceptance:
- product workflows no longer import runtime-client implementation details directly;
- model readiness/status/release semantics remain truthful;
- no cloud fallback is introduced.

### AC-7 — Follow-up hardening
Status: READY

After the structural lanes converge:
- remove global `ModelRuntimeLeaseManager` service injection;
- replace the `AppServices(... analysis_jobs=None ...)` construction cycle;
- introduce versioned SQLite migration ownership;
- move cloud credentials toward macOS Keychain;
- introduce typed settings;
- generate frontend API contracts from FastAPI OpenAPI;
- reduce committed/generated frontend ambiguity;
- defer broad `local-asr-server` naming migration until it has independent value.

## Convergence order

1. AC-1, AC-2, AC-3, AC-4, AC-5 proceed in parallel with disjoint primary write boundaries.
2. Integrate the smallest validated lanes first; rebase remaining lanes on the new `dev` before integration validation.
3. AC-6 begins only after transcription and recording persistence boundaries are stable.
4. AC-7 follows as separate small changes; do not bundle security, DB migration, generated contracts and package renames into one PR.

## Validation

Each lane uses the repository selector against current `dev`. Focused tests come first. Before integration:
- inspect full lane diff;
- run required selected gates;
- run affected automated critical E2E;
- material UI changes require FULL_MEDIA evidence;
- native/TCC/physical-audio/representative MLX gaps remain explicitly DEFERRED_TO_RELEASE unless behavior changed enough to require earlier evidence.

No lane may weaken existing tests simply to preserve behavior after extraction.

## Resume checkpoint

Source identity at creation:
- base branch: `dev`
- base HEAD: `ae3775a0510b51c45b31373bcba344aa1d1ee7e1`

Confirmed facts:
- no open PRs targeting `dev` at workstream start;
- `RecordingStore`, native capture, transcription router, `MeetingDetailPage`, `RecordingOverlayPage`, and `useRecorder` are current structural hotspots;
- macro architecture, local-first boundary, HeavyWorkloadArbiter ownership, filesystem/SQLite split, and validation fidelity model are preserved.

Next action:
- create lane branches from the same base, implement focused extractions with non-conflicting ownership, validate independently, then converge in the order above.
