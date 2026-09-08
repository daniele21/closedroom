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
- PRS-16 / #41 merged at `dev@eb92df6d`: capture now receives atomic priority at the next safe managed-work boundary without force-killing active AI, losing bounded queued work or presenting recording before capture is real. Exact-tree STRONG evidence covered 406 source tests, all declared Meeting browser FULL_MEDIA journeys and packaged-app build/lifecycle smoke.
- PRS-17 / #43 merged at `dev@19b15b0f`: Today, saved Meeting and Projects now share one adaptive macOS workspace hierarchy. The exact candidate `c1c79f31` passed FULL remote preflight #306: repository/contract guards, frontend deterministic checks, 411 Python tests, all declared Meeting browser FULL_MEDIA journeys, packaged-app build/lifecycle smoke, repository validation and reusable evidence publication.
- Canonical target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`.

## Current integration state

PRS-16 is integrated. `HeavyWorkloadArbiter` remains the sole heavy-work owner: one ephemeral capture reservation waits for already-active managed work to finish normally, then prevents queued heavy work from starting for the recording lifetime. Work submitted during reserved capture stays in the same bounded queue and resumes after release; capacity is enforced against logical pending work even when a worker has dequeued an item behind capture priority.

`ResourcePolicy(capture_active)` remains the fail-safe for legacy/unreserved capture. `RecordingStore` remains the only recording persistence owner; reservation ids are transient and external runtimes remain caller-owned.

The frontend reserves capture before start, shows a truthful cancellable preparation state while AI finishes, starts the timer only with real capture, and releases priority on Stop/failure/recovery.

PRS-17 is integrated at `dev@19b15b0f`. `App.tsx` owns one adaptive workspace shell: desktop uses one stable left rail, compact/narrow windows reflow the same Today/Projects hierarchy and persistent New Meeting action into one bounded sticky toolbar, and a saved Meeting remains a child of Today rather than a third peer destination. Settings/theme/language/tour/demo/runtime status remain utilities. `workspace.css` owns the responsive shell behavior while routing, persistence, capture, preparation and runtime owners remain unchanged. The integrated `coherent-macos-workspace` FULL_MEDIA journey proves Today -> Meeting -> Projects hierarchy, theme continuity and 1440/780/560px resize behavior without page-wide horizontal overflow; archive-search and preparation fixtures were also hardened against execution-date and transient-progress timing assumptions.

## Release evidence still pending

Target-Mac UX/TCC/native audio, CPU/RSS/Metal/thermal evidence, PRS-9 representative audio comparison, production signing/notarization, subjective VoiceOver usability and material production ASR/LLM quality/latency claims remain release work. PRS-16 claims safe priority at the next supported managed-work boundary, not instant model pre-emption. PRS-17 does not claim headless Chrome proves packaged WKWebView/window chrome or subjective accessibility quality.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release is next.
- [`product-runtime-simplification.md`](workstreams/product-runtime-simplification.md): PRS-10 convergence remains open.
- [`ux-simplification.md`](workstreams/ux-simplification.md): deterministic work integrated; target-Mac confirmation remains a release gate.

## Next highest-value work

1. Advance PRS-18 measured release from `dev@19b15b0f` using the repository release contract and FULL validation.
2. Collect blocking target-Mac REAL_ENVIRONMENT evidence for WKWebView/window/focus/VoiceOver, TCC/native capture, representative resources/thermal behavior and the PRS-9 audio comparison.
3. Keep production signing/notarization and any material ASR/LLM quality/latency claims evidence-backed before `dev -> main` promotion.