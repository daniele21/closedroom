# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. PRs into `dev` require selector-owned deterministic/E2E evidence; applicable target-Mac `REAL_ENVIRONMENT` evidence is deferred to release.

## Integrated baseline

- Exact-head/tree-equivalent remote preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 are integrated: Meeting-first defaults, on-demand visual intelligence, bounded managed-model residency, persisted SSE job progress and audio-strategy benchmark tooling; dual-track audio stays canonical pending representative release evidence.
- PRS-11 / #35: saved Meeting core content opens independently from diagnostics/visual routes.
- PRS-12 / #36: `Prepare notes` is one durable recoverable Meeting workflow; existing execution owners remain canonical.
- PRS-13 / #37: implicit default notes use one source-aware structured v2 analysis instead of four overlapping physical jobs.
- PRS-14 / #38: source-verifiable editable actions/decisions persist through explicit revision/conflict semantics.
- PRS-15 / #39 merged at `dev@3604ffbe`: complete local Meeting archive search is bounded, server-side and FTS5-backed; `meeting-archive-search` FULL_MEDIA and packaged FTS5 smoke are integrated.
- Repository governance baseline 0.10.0 / #40 is integrated at `dev@b0922314` with bounded agent reporting, schema-2 context routes and refreshed preflight/validation skills.
- PRS-16 / #41 merged at `dev@eb92df6d`: capture receives atomic priority at the next safe managed-work boundary without force-killing active AI, losing bounded queued work or presenting recording before capture is real. Exact-tree STRONG evidence covered 406 source tests, all then-declared Meeting browser FULL_MEDIA journeys and packaged-app build/lifecycle smoke.
- PRS-17 / #43 merged at `dev@19b15b0f`: Today, saved Meeting and Projects share one adaptive macOS workspace hierarchy. Exact candidate `c1c79f31` passed FULL remote preflight #306: repository/contract guards, frontend deterministic checks, 411 Python tests, all declared Meeting browser FULL_MEDIA journeys, packaged-app build/lifecycle smoke, repository validation and reusable evidence publication.
- The MIT `LICENSE` present on stable `main` was restored to the release line through PR #46 before promotion work.
- Product/runtime convergence and UX simplification are complete for development integration; their remaining target-Mac obligations are consolidated below under PRS-18.
- Canonical target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner: one ephemeral capture reservation waits for already-active managed work to finish normally, then prevents queued heavy work from starting for the recording lifetime. Work submitted during reserved capture stays in the same bounded queue and resumes after release; capacity is enforced against logical pending work even when a worker has dequeued an item behind capture priority.

`ResourcePolicy(capture_active)` remains the fail-safe for legacy/unreserved capture. `RecordingStore` remains the only recording persistence owner; reservation ids are transient and external runtimes remain caller-owned. The frontend reserves capture before start, shows a truthful cancellable preparation state while AI finishes, starts the timer only with real capture, and releases priority on Stop/failure/recovery.

`App.tsx` owns one adaptive workspace shell: desktop uses one stable left rail, compact/narrow windows reflow the same Today/Projects hierarchy and persistent New Meeting action into one bounded sticky toolbar, and a saved Meeting remains a child of Today rather than a third peer destination. Settings/theme/language/tour/demo/runtime status remain utilities. `workspace.css` owns responsive shell behavior while routing, persistence, capture, preparation and runtime owners remain unchanged.

## Release evidence still pending

PRS-18 is the only active release workstream. Stable promotion remains blocked until FULL release automation and every applicable target-environment confirmation agree on the exact release candidate.

Blocking/explicit release evidence currently includes:

- target-Mac packaged WKWebView/window/accessibility-tree/keyboard-focus behavior and FULL_MEDIA for the recording journey;
- TCC-backed native `both` capture with non-empty microphone + system-audio persistence and clean lifecycle;
- representative CPU/RSS/Metal/thermal behavior under capture and managed AI work;
- PRS-9 representative dual-track vs mixed-track audio benchmark; dual-track remains canonical unless evidence justifies a separately validated ownership change;
- production signing/notarization before distributing a production artifact;
- subjective VoiceOver/usability observation where materially required;
- material production ASR/LLM quality or latency claims only when backed by representative evidence.

PRS-16 claims safe priority at the next supported managed-work boundary, not instant model pre-emption. PRS-17 browser evidence does not claim headless Chrome proves packaged WKWebView/window chrome or subjective accessibility quality.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release is active.

## Next highest-value work

1. Prepare the exact PRS-18 `dev -> main` release candidate and run selector-owned **RELEASE / FULL** automation against the live `main` base.
2. Collect the blocking `target-macos-real` recording/UI/TCC evidence, representative resource/thermal evidence and PRS-9 audio comparison without relabeling hosted CI as target-Mac proof.
3. Produce and verify the production-signed/notarized release artifact before stable promotion; keep `main` unmodified while any required release evidence is missing.
