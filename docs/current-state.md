# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.9.2**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. PRs into `dev` require selector-owned deterministic/E2E evidence; applicable target-Mac `REAL_ENVIRONMENT` evidence is deferred to release.

## Integrated baseline

- Exact-head/tree-equivalent remote preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 are integrated: Meeting-first defaults, on-demand visual intelligence, bounded managed-model residency, persisted SSE job progress and audio-strategy benchmark tooling; dual-track audio stays canonical pending representative release evidence.
- PRS-11 / #35: saved Meeting core content opens independently from diagnostics/visual routes.
- PRS-12 / #36: `Prepare notes` is one durable recoverable Meeting workflow; existing execution owners remain canonical.
- PRS-13 / #37: implicit default notes use one source-aware structured v2 analysis instead of four overlapping physical jobs.
- PRS-14 / #38: source-verifiable editable actions/decisions persist through explicit revision/conflict semantics.
- PRS-15 / #39 merged at `dev@3604ffbe`: complete local Meeting archive search is bounded, server-side and FTS5-backed; `meeting-archive-search` FULL_MEDIA and packaged FTS5 smoke are integrated.
- Canonical target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`.

## Current integration candidate

PRS-16 on `feat/prs-16-record-while-ai-busy` closes the race between starting a meeting and managed heavy AI work without unsafe kill, a second scheduler or false instant-recording state.

`HeavyWorkloadArbiter` remains the sole heavy-work owner. One ephemeral capture reservation waits for already-active managed work to finish normally, then prevents queued heavy work from starting for the recording lifetime. Work submitted during reserved capture stays in the same bounded queue and resumes after release; capacity is enforced against logical pending work even when a worker has dequeued an item behind capture priority.

`ResourcePolicy(capture_active)` remains the fail-safe for legacy/unreserved capture. `RecordingStore` remains the only recording persistence owner; reservation ids are transient and external runtimes remain caller-owned.

The frontend reserves capture before start, shows a truthful cancellable preparation state while AI finishes, starts the timer only with real capture, and releases priority on Stop/failure/recovery. Python tests cover ordering, bounds, cancellation and resume; `record-while-ai-busy` FULL_MEDIA covers the visible Ready -> waiting -> recording -> Stop -> resume sequence with synthetic data.

Expected integration depth is **STRONG**: governance, source tests, affected browser FULL_MEDIA and packaged-app validation must pass on exact HEAD/base. Physical audio/TCC/WKWebView behavior and representative MLX/Metal/thermal contention remain release evidence.

## Release evidence still pending

Target-Mac UX/TCC/native audio, CPU/RSS/Metal/thermal evidence, PRS-9 representative audio comparison, production signing/notarization, subjective VoiceOver usability and material production ASR/LLM quality/latency claims remain release work. PRS-16 claims safe priority at the next supported managed-work boundary, not instant model pre-emption.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..15 integrated; PRS-16 integration candidate; PRS-17 blocked on PRS-16.
- [`product-runtime-simplification.md`](workstreams/product-runtime-simplification.md): PRS-10 convergence remains open.
- [`ux-simplification.md`](workstreams/ux-simplification.md): deterministic work integrated; target-Mac confirmation remains a release gate.

## Next highest-value work

1. Complete exact-head STRONG validation and integrate PRS-16 only if required gates agree.
2. Advance PRS-17 coherent macOS workspace from fresh `dev`.
3. Collect release evidence for PRS-18 / `dev -> main`.
