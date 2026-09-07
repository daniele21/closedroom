# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-17 integration candidate
Owner: meeting product, canonical job/persistence owners and local runtime
Baseline: dev `580fe6a7`, 2026-09-07.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. PRS-11 through PRS-16 are integrated; PRS-17 is the current integration candidate. No production performance or memory gain is claimed without representative evidence.

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
| PRS-16 | Record safely while AI is busy | resource policy/arbiter, capture admission, recording UI | — | DONE |
| PRS-17 | Coherent macOS workspace | App/pages/components/design contracts | PRS-12,14,15,16 | INTEGRATION |
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

### PRS-16 — recording while AI is busy

Start meeting now wins the next safe resource boundary without killing useful AI work, losing queued work or pretending capture has started before it has.

- `HeavyWorkloadArbiter` remains the single heavy-work owner and owns one ephemeral capture reservation; no new scheduler, store or model-lifecycle owner;
- reservation is `waiting` while managed heavy work is active and becomes `granted` only after active work reaches normal completion; no thread/process kill;
- while reserved, pending work stays in the existing bounded queue and cannot become active; work submitted during reserved capture queues within existing capacity;
- capacity is enforced against logical pending work even when a worker dequeued an item but holds it behind capture priority;
- legacy/unreserved capture stays fail-safe through `ResourcePolicy(capture_active)`;
- `/v1/capture/reservations` is a loopback/authenticated transient handshake; tokens are not recording persistence or telemetry;
- `useRecorder` reserves before capture, keeps the token through recording, releases on Stop/failure/recovery and ignores duplicate Start during the handshake;
- New Meeting shows truthful preparation while AI finishes, keeps the timer stopped and offers `Annulla`; real recording state starts only after capture does;
- external runtimes remain caller-owned.

PR #41 integrated at `dev@eb92df6d`. The authoritative STRONG preflight on the exact candidate tree passed governance, frontend checks, 406 Python tests, all five declared Meeting browser FULL_MEDIA journeys and packaged-app build/lifecycle smoke. The post-merge preflight reused that tree-equivalent evidence and completed successfully. Physical audio, TCC/WKWebView and representative MLX/Metal/thermal behavior remain release-only REAL_ENVIRONMENT evidence.

## PRS-17 — coherent macOS workspace — integration candidate

Observable outcome: Today, a saved Meeting and Projects now share one stable product hierarchy rather than page-specific chrome. Meeting remains a child of Today, Projects is the second peer destination, New Meeting remains the persistent primary action, and Settings/theme/language/tour/demo/runtime status remain utilities.

Implementation boundary:

- `App.tsx` owns one adaptive workspace shell; desktop uses a stable left rail and compact/narrow windows reflow the same semantic destinations into one sticky top toolbar rather than introducing a second navigation model;
- existing page routing, persistence, preparation, recording, search and runtime owners are unchanged;
- `workspace.css` owns the adaptive shell/layout behavior and reduced-motion accommodation without creating a second token/design source;
- `design/ux-contract.json` records navigation hierarchy and adaptive window rules;
- `test_frontend_workspace_coherence.py` protects shell hierarchy, active-state semantics and compact/narrow CSS contracts;
- `browser_workspace_coherence_e2e.mjs` provides FULL_MEDIA evidence for Today -> Meeting -> Projects, theme continuity and 1440 -> 780 -> 560px resize with no page-wide horizontal overflow;
- `browser_meeting_ui_e2e.mjs` runs the new journey alongside all existing Meeting FULL_MEDIA journeys so integration cannot pass by validating only the new shell in isolation;
- `.engineering/e2e.json` declares `coherent-macos-workspace` with required target-Mac release confirmation for packaged WKWebView/window/focus/reduced-motion/VoiceOver fidelity.

Integration proof is still pending on the exact candidate head/base. Because the E2E contract and material UI integration harness changed, use selector `auto`; STRONG/FULL escalation is authoritative if selected. Physical TCC/audio, real WKWebView window behavior, keyboard/focus/VoiceOver quality and representative MLX/Metal remain release-only REAL_ENVIRONMENT evidence.

## Evidence and release

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates; material UI uses FULL_MEDIA. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE `dev -> main` requires FULL automation plus applicable target-Mac TCC/audio/WKWebView/VoiceOver, representative MLX/resources and PRS-9 audio evidence. Canonical runner: `python3 scripts/real_environment_ui_evidence.py --build`. Numeric budgets require comparable baselines; missing data stays unknown.

Durable owners: `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and `docs/current-state.md`. Complete a slice only when code, consumers, recovery, docs and evidence agree.
