# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-16 integration candidate
Owner: meeting product, canonical job/persistence owners and local runtime
Baseline: dev `b0922314`, 2026-09-06.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. PRS-11 through PRS-15 are integrated; PRS-16 is the current candidate. No production performance or memory gain is claimed without representative evidence.

- Meeting is primary; normal recording requires no technical choice.
- `Prepare notes` is explicit after Stop; `Transcript only` is secondary.
- Reuse valid transcript and notes; ready notes open first unless the user selects another tab.
- Audio/transcript survive enrichment failure/cancel; local-first and explicit cloud opt-in remain unchanged.
- Canonical owners remain RecordingStore, JobStore, CatalogStore, HeavyWorkloadArbiter and runtime services.
- Excluded: rewrite, second scheduler/runtime/index owner, implicit cloud, mandatory visuals, unsafe kill, unproven audio strategy.

## Work graph

| ID | Observable outcome | Owner paths/contracts | Depends on | State |
| --- | --- | --- | --- | --- |
| PRS-11 | Fast saved Meeting open | MeetingDetailPage, API client, visual hook | — | DONE |
| PRS-12 | One recoverable Prepare notes action | jobs, analysis/transcription services, Meeting UI | PRS-11 | DONE |
| PRS-13 | Consistent notes with less repeated inference | analysis templates/jobs/service/catalog reads | PRS-12 | DONE |
| PRS-14 | Verify/edit actions and decisions | notes schema/catalog, transcript, Meeting UI | PRS-13 | DONE |
| PRS-15 | Search complete local archive | CatalogStore, workspace/API/UI | — | DONE |
| PRS-16 | Record safely while AI is busy | resource policy/arbiter, capture admission, recording UI | — | INTEGRATION |
| PRS-17 | Coherent macOS workspace | App/pages/components/design contracts | PRS-12,14,15,16 | BLOCKED |
| PRS-18 | Measured release | current-state, benchmarks, target-Mac evidence | selected increments | BLOCKED |

Default sequence: 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17. Shared schema/service/UI edits remain serialized into coherent outcome PRs.

## Integrated slices

### PRS-11 — fast saved Meeting open

Core transcript content loads independently from diagnostics/visual routes; accessory failures stay local, stale responses are ignored and reloads are bounded. Evidence: focused tests plus `saved-meeting-fast-open` FULL_MEDIA.

### PRS-12 — one recoverable Prepare notes action

A durable `meeting_preparation` parent composes existing transcription and analysis jobs. Valid transcript reuse, cancel/restart/resume semantics and parent SSE preserve completed work and keep expert APIs compatible. Evidence includes `meeting-preparation-recovery` FULL_MEDIA and packaged smoke.

### PRS-13 — shared structured notes

Implicit `meeting_default` runs one internal `meeting_notes_shared` v2 analysis instead of four overlapping jobs. Summary/actions/decisions/risks carry source refs, long input is bounded and legacy projections remain compatible. `HeavyWorkloadArbiter` stays the only scheduler. Evidence covered schema/cache/source-boundary tests, FULL_MEDIA and STRONG/package gates.

### PRS-14 — verifiable editable notes

Actions/decisions have stable source-anchored identity, immutable generated content and persisted user overlays. Regeneration creates revisions; changed/missing items surface explicit conflicts instead of silent remapping. Evidence includes persistence/API/frontend tests, `meeting-note-edit-revision` FULL_MEDIA and packaged validation.

### PRS-15 — complete bounded archive search

Every persisted Meeting is discoverable without loading the whole archive into React. `CatalogStore` owns an FTS5 projection inside `closedroom.db`; canonical mutations mark affected ids dirty and search refreshes them incrementally. `GET /v1/meetings?q=...` provides bounded paging/exact project filtering; `⌘K` owns global archive search. FTS5 absence fails explicitly. PR #39 integrated source/frontend tests, `meeting-archive-search` FULL_MEDIA and packaged FTS5 smoke at `dev@3604ffbe`.

## PRS-16 — recording while AI is busy — integration candidate

Goal: make Start meeting win the next safe resource boundary without killing useful AI work, losing queued work or pretending capture has started before it has.

Implementation candidate:
- `HeavyWorkloadArbiter` remains the single heavy-work owner and owns one ephemeral capture reservation; no new scheduler, store or model-lifecycle owner;
- reservation is `waiting` while managed heavy work is active and becomes `granted` only after active work reaches normal completion; no thread/process kill;
- while reserved, pending work stays in the existing bounded queue and cannot become active; work submitted during reserved capture queues within existing capacity;
- capacity is enforced against logical pending work even when a worker dequeued an item but holds it behind capture priority;
- legacy/unreserved capture stays fail-safe through `ResourcePolicy(capture_active)`;
- `/v1/capture/reservations` is a loopback/authenticated transient handshake; tokens are not recording persistence or telemetry;
- `useRecorder` reserves before capture, keeps the token through recording, releases on Stop/failure/recovery and ignores duplicate Start during the handshake;
- New Meeting shows truthful preparation while AI finishes, keeps the timer stopped and offers `Annulla`; real recording state starts only after capture does;
- external runtimes remain caller-owned.

Acceptance before merge:
- AI-active -> Start cannot let queued heavy work overtake capture or force-kill active work;
- capture-active -> new managed heavy work remains bounded and resumes after release;
- reservation/cancellation races preserve queue and cancellation semantics;
- duplicate reservation is rejected; stale/missing client release is safe;
- UI distinguishes preparing/waiting from recording and provides cancellation without false instant-start;
- `record-while-ai-busy` FULL_MEDIA proves Ready -> waiting/cancel -> recording -> Stop -> release/resume with synthetic data;
- source-contract tests independently prove scheduler ordering.

Checks: workload-arbiter/capture-admission tests, frontend contract/lint/typecheck, affected Meeting browser FULL_MEDIA including `record-while-ai-busy`, packaged-app lifecycle and selector-owned STRONG validation. Physical audio, TCC/WKWebView and representative MLX/Metal/thermal behavior remain release-only REAL_ENVIRONMENT evidence.

## PRS-17 — coherent macOS workspace

Unify hierarchy across Today, Meeting, Projects, themes and supported window sizes. Keep one dominant action per state, advanced tools discoverable, async navigation stable and focus/keyboard/reduced-motion semantics intact. Component/routing checks plus complete journey FULL_MEDIA; SCOPED expected unless contracts expand.

## Evidence and release

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates; material UI uses FULL_MEDIA. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE `dev -> main` requires FULL automation plus applicable target-Mac TCC/audio/WKWebView/VoiceOver, representative MLX/resources and PRS-9 audio evidence. Canonical runner: `python3 scripts/real_environment_ui_evidence.py --build`. Numeric budgets require comparable baselines; missing data stays unknown.

Durable owners: `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and `docs/current-state.md`. Complete a slice only when code, consumers, recovery, docs and evidence agree.
