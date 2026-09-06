# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.9.2** at maturity **L2** with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. PRs into `dev` require selector-owned deterministic/E2E evidence, while applicable target-Mac `REAL_ENVIRONMENT` evidence is `DEFERRED_TO_RELEASE`.

## Integrated baseline

- Exact-head/tree-equivalent remote preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- Product/runtime PRS-5..8 are integrated: Meeting-first defaults, visual intelligence on demand, bounded managed model residency and persisted SSE job progress with 512-event/job retention.
- PRS-9 benchmark tooling is integrated; dual-track audio remains canonical until representative release evidence supports a change.
- PRS-11 / PR #35: saved Meeting core content opens independently from diagnostics/visual routes, with local accessory recovery and browser FULL_MEDIA evidence.
- PRS-12 / PR #36: `Prepare notes` is one durable Meeting workflow backed by a persisted `meeting_preparation` parent, reuse/cancel/restart/resume contracts and `meeting-preparation-recovery` FULL_MEDIA. Existing transcription/analysis managers and `HeavyWorkloadArbiter` remain execution owners.
- PRS-13 / PR #37: implicit default notes use one shared structured v2 analysis instead of four overlapping physical jobs, with source-aware bounded extraction, virtual legacy projections and exact cache identity.
- PRS-14 / PR #38 merged to `dev` at `a3902f3cd5620ace3550ec6d4e48aab1ab620a2f`: actions/decisions are source-verifiable and editable through a persisted overlay/revision model; regeneration conflicts are explicit and the `meeting-note-edit-revision` FULL_MEDIA journey is integrated.
- PRS-15 / PR #39 merged to `dev` at `3604ffbe1323d6334611d19b65fd0fa8d228b1d6`: complete local Meeting archive search is server-side, bounded and FTS5-backed inside the canonical catalog; `⌘K` uses paged search and `meeting-archive-search` FULL_MEDIA plus packaged FTS5 smoke are integrated.
- Canonical target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`. Production signing/notarization, subjective VoiceOver usability and representative MLX/Metal performance remain release claims.

## Current integration candidate

PRS-16 is implemented on `feat/prs-16-record-while-ai-busy` from `dev@3604ffbe`. It closes the race where a user starts a meeting while a managed transcription/analysis/visual workload is already active, without introducing unsafe thread kill, a second scheduler or a false instant-recording state.

`HeavyWorkloadArbiter` remains the single ClosedRoom heavy-work owner. It now owns one ephemeral capture reservation: the reservation waits while an already-active managed workload reaches its normal safe completion boundary, becomes granted only when no heavy workload is active, then prevents queued heavy work from starting for the lifetime of the recording. Work submitted while a reserved/active capture exists remains in the same bounded queue and resumes after reservation release. The configured capacity is enforced against the logical pending set even when a worker has dequeued an item but is holding it behind capture priority.

The existing `ResourcePolicy(capture_active)` stays as the fail-safe for legacy/unreserved capture. Recording persistence remains exclusively in `RecordingStore`; reservation ids are transient capability tokens and are neither persisted in the recording model nor exposed through resource telemetry. External runtimes remain caller-owned.

The frontend acquires the reservation before creating/starting capture and retains it locally through Stop. New Meeting distinguishes Ready, safe-boundary preparation, source startup, real recording and finalization. If AI is already active it explicitly says ClosedRoom is waiting for that activity to finish safely; the recording timer has not started and the user can cancel the waiting handshake. Stop/failure/recovery releases the reservation so queued managed work may continue.

Automated evidence is split by claim: Python source-contract tests cover both admission orderings, queue bounds, cancellation and resume; `record-while-ai-busy` browser FULL_MEDIA covers Ready -> waiting/cancel affordance -> granted capture -> Stop -> reservation release using synthetic content. Physical microphone/system-audio capture, TCC/WKWebView behavior, representative MLX/Metal contention and thermal response remain target-Mac release evidence.

Expected integration depth is **STRONG** because PRS-16 changes shared runtime/concurrency/lifecycle behavior and a material recording UI journey. Required automated evidence includes repository guards, frontend lint/typecheck, full Python unit/integration coverage, all affected Meeting browser FULL_MEDIA journeys including `record-while-ai-busy`, packaged-app lifecycle and repository validation on the exact HEAD/base selected by the repo.

## Release evidence still pending

Representative CPU/RSS/Metal/thermal evidence, target-Mac UX/TCC/native-audio confirmation, PRS-9 representative audio comparison and any material production ASR/LLM quality/latency claim remain release work. PRS-16 does not claim that an active model can always be pre-empted instantly; it claims safe capture priority at the next supported managed-work boundary and bounded resume semantics after Stop.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..15 integrated; PRS-16 integration candidate; PRS-17 blocked on PRS-16 integration.
- [`product-runtime-simplification.md`](workstreams/product-runtime-simplification.md): PRS-10 convergence remains open.
- [`ux-simplification.md`](workstreams/ux-simplification.md): deterministic work integrated; target-Mac confirmation remains a release gate.

## Next highest-value work

1. Complete exact-head INTEGRATION validation for PRS-16; merge only if selector-required source/FULL_MEDIA/package gates agree.
2. Once PRS-16 is integrated, advance PRS-17 coherent macOS workspace on the fresh `dev` base.
3. Then collect representative resource/audio/target-Mac evidence for PRS-18 / `dev -> main` release acceptance.
