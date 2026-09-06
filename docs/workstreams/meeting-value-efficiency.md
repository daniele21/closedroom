# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-16 integration candidate
Owner: meeting product, canonical job/persistence owners and local runtime
Baseline: dev `3604ffbe`, 2026-09-06.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. PRS-11 through PRS-15 are integrated; PRS-16 is the current integration candidate. No production-model performance or memory gain is claimed without representative evidence.

- Meeting is primary; normal recording requires no technical choice.
- `Prepare notes` is explicit after Stop; `Transcript only` is secondary.
- Reuse valid transcript, then existing notes analysis. Ready notes open first; explicit tab selection wins.
- Audio/transcript survive enrichment failure/cancel. Local-first and explicit cloud opt-in remain unchanged.
- Canonical owners stay unchanged: RecordingStore capture, JobStore durable jobs, CatalogStore persisted runs/indexes, HeavyWorkloadArbiter heavy-work scheduling, runtime services managed cleanup.
- Excluded: rewrite, second scheduler/runtime/index owner, implicit cloud, mandatory visuals, unsafe thread/process kill, unproven audio strategy.

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

## PRS-11 — integrated

Saved Meeting core content loads independently from diagnostics and visual services. Accessory errors/retries stay local, stale route responses are ignored and terminal reloads are coalesced. Evidence includes focused tests and `saved-meeting-fast-open` FULL_MEDIA. Target WKWebView/TCC fidelity remains release evidence when material.

## PRS-12 — integrated

`Prepare notes` is a durable `meeting_preparation` JobStore parent that composes the existing transcription and analysis jobs. Durable identity covers recording source, effective ASR options and analysis/template identity; valid transcripts skip ASR. Cancel prevents future stages including admission races, restart interrupts incomplete work and explicit resume starts from the first missing stage. Meeting follows the parent SSE, exposes transcript before notes finish and does not promote output from failed/interrupted/cancelled preparation pipelines. Existing expert transcription/analysis APIs remain compatible. Integration evidence included owner/API/persistence tests plus `meeting-preparation-recovery` FULL_MEDIA and packaged-app smoke.

## PRS-13 — integrated shared structured notes

The default notes path now reduces overlapping inference without degrading the logical note views. `meeting_default` with no explicit `analysis_types` executes one internal `meeting_notes_shared` v2 analysis job instead of four overlapping physical jobs; `meeting_deep`, explicit analysis types and expert single analyses remain unchanged.

The canonical result is `closedroom.meeting_notes` schema v2 with a `generated` boundary containing summary, actions, decisions and risks. Every non-empty generated claim requires a canonical transcript segment reference with timing/speaker metadata when available. One persisted v2 run is projected at read time into stable `meeting_brief`, `action_items`, `decisions` and `risks_blockers` views without synthetic jobs or rows; old persisted v1 runs continue to read unchanged.

Structured cache identity includes transcript segment ids/timing/speaker/text. Short inputs use one extraction; long inputs use bounded source-aware chunks plus bounded aggregation, and oversize input fails explicitly rather than truncating. Source refs cannot escape the chunk/aggregation evidence supplied to the inference. The internal shared template remains hidden from the public template picker and `HeavyWorkloadArbiter` remains the only heavy-work scheduler.

Integration evidence covered schema/projection/cache/long-input/source-boundary tests, existing analysis/preparation suites, frontend deterministic checks, `meeting-preparation-recovery` FULL_MEDIA and selector-owned STRONG/package gates. Production model quality/latency/RSS and target WKWebView/TCC fidelity remain release deltas unless a comparable integration baseline exists.

## PRS-14 — integrated verifiable, editable notes

Actions and decisions now carry stable source-anchored identity, immutable generated content and a persisted user-edit overlay. Corrections survive restart; regeneration creates a new revision and carries edits only when safe. Changed or removed generated items surface explicit `generated_changed` / `item_missing` conflicts rather than silent remapping. PATCH uses the generated fingerprint for optimistic concurrency, discard is explicit, and source evidence remains reachable from current and retained conflict items.

Integration evidence included domain identity/overlay/revision tests, real CatalogStore reopen persistence, API stale-generation/rebase/discard coverage, frontend contract checks, the `meeting-note-edit-revision` FULL_MEDIA journey and packaged-app validation. Target WKWebView focus/accessibility and production-model behavior remain release confirmation when material.

## PRS-15 — integrated complete bounded archive search

Every persisted Meeting is discoverable from the normal search surface without loading the whole archive or relying on compact preview text in React.

`CatalogStore` remains the canonical persistence owner. `CatalogMeetingSearch` uses a derived FTS5 projection inside the same `closedroom.db`; canonical recording/transcription/analysis mutations mark affected recording ids dirty through SQLite triggers and search refreshes only those rows transactionally. First search backfills existing data once, with schema metadata and row-count healing for restored/copied databases.

`GET /v1/meetings` stays backward-compatible without `q`; a supplied query uses bounded paged archive search with exact project filtering. Today no longer owns global-search state; `⌘K` opens a dedicated archive dialog with bounded server pages, stale-request cancellation, loading/error/empty/load-more states and query restoration across source navigation. FTS5 absence fails explicitly instead of falling back to an unbounded scan.

Integration evidence covered catalog/API/frontend tests, `meeting-archive-search` FULL_MEDIA, bundled FTS5 capability in packaged lifecycle smoke and selector-owned STRONG validation before PR #39 was squash-merged to `dev@3604ffbe`.

## PRS-16 — recording while AI is busy — integration candidate

Goal: make Start meeting win the next safe resource boundary without killing useful AI work, losing queued work or pretending capture has started before it really has.

Implementation candidate:
- `HeavyWorkloadArbiter` remains the single process-wide owner for heavy-work scheduling and now owns one ephemeral capture reservation; no new scheduler, persistence store or model-lifecycle owner is introduced;
- a reservation is `waiting` while a managed heavy workload is active and becomes `granted` only after active work reaches its normal completion/safe boundary. Active work is never thread-killed or force-stopped;
- while a reservation exists, pending work remains in the same bounded queue and no queued item becomes active. Work submitted during reserved/active capture is queued within the existing capacity rather than being failed only because capture is active;
- the queue cap is enforced against the logical pending set as well as the physical `queue.Queue`, including the case where a worker already dequeued an item but is holding it behind capture priority;
- legacy/unreserved capture remains fail-safe through the existing `ResourcePolicy(capture_active)` admission guard;
- `/v1/capture/reservations` exposes a loopback/authenticated transient handshake. Reservation ids are ephemeral capability tokens, never persisted in RecordingStore or emitted through resource telemetry;
- `useRecorder` obtains the reservation before creating/starting capture, keeps the token locally through the recording, releases it after Stop/failure/recovery and ignores duplicate Start while a handshake is already running;
- New Meeting shows `Preparazione registrazione` while an active AI phase finishes, explicitly says that recording has not started yet, keeps the timer stopped and offers `Annulla` while waiting. Once granted it moves through source setup to the existing real recording state;
- external runtimes remain caller-owned. The reservation coordinates ClosedRoom managed heavy work only and does not claim authority to suspend arbitrary external services.

Acceptance before merge:
- AI-active -> Start cannot allow a queued heavy job to overtake capture and cannot force-kill the active job;
- capture-active -> new managed heavy work stays bounded and resumes after Stop/release;
- reservation and pending cancellation races preserve the existing bounded queue and cancellation semantics;
- duplicate capture reservation is rejected deterministically and stale/missing release is safe at the client boundary;
- the UI distinguishes ready / preparing / waiting / recording / finalizing and exposes cancellation while waiting without a false instant-start promise;
- `record-while-ai-busy` FULL_MEDIA proves Ready -> Start -> truthful waiting/cancel -> granted recording -> Stop -> reservation release/AI resume with synthetic content only;
- source-contract tests prove the actual scheduler ordering independently of the browser fixture.

Checks: workload-arbiter/capture-admission tests, recording/frontend contract tests, frontend lint/typecheck, all affected Meeting browser FULL_MEDIA journeys including `record-while-ai-busy`, packaged-app lifecycle and selector-owned STRONG validation. Physical microphone/system-audio, TCC/WKWebView, representative MLX/Metal contention and thermal behavior remain release-only REAL_ENVIRONMENT evidence.

## PRS-17 — coherent macOS workspace

Unify hierarchy across Today, Meeting, Projects, themes and supported window sizes. Keep one dominant action per state, advanced tools discoverable, async navigation stable and focus/keyboard/reduced-motion semantics intact. Component/routing checks plus complete journey FULL_MEDIA; SCOPED expected unless contracts expand.

## Evidence and release

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates; material UI uses FULL_MEDIA. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE `dev -> main` requires FULL automation plus applicable target-Mac TCC/audio/WKWebView/VoiceOver, representative MLX/resources and PRS-9 audio evidence. Use `python3 scripts/real_environment_ui_evidence.py --build`. Numeric budgets come from comparable baseline measurements; missing data stays unknown.

Durable owners: `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and `docs/current-state.md`. Complete a slice only when code, consumers, recovery, docs and evidence agree.
