# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. Integration requires selector-owned deterministic/E2E evidence; applicable target-Mac evidence is blocking only at release.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative release evidence.
- PRS-11..17 integrated the saved-Meeting/Prepare-notes flow, structured verifiable notes, bounded archive search, safe capture priority and one adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306: guards, frontend, 411 Python tests, all declared Meeting FULL_MEDIA journeys, packaged lifecycle and repository validation.
- The MIT `LICENSE` already on stable `main` was restored to the release line through PR #46.
- PRS-18 release tooling integrated through PR #48. Source head `9bfd7efc` passed exact-head INTEGRATION/FULL preflight #329, including repository/contract guards, frontend checks, the Python suite and finalized packaged-app lifecycle smoke; squash merge `94fa3d3` preserved the validated source tree.
- PR #53 integrated one aggregate REAL_ENVIRONMENT runner over the measured target-Mac and PRS-16 contention owners while keeping release qualification fail-closed.
- Product/runtime convergence and UX simplification development workstreams are finalized; PRS-18 measured release is the only active workstream.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. Capture waits for the next safe managed-work boundary, holds bounded queued work during recording and releases it afterward; `ResourcePolicy` remains the unreserved-capture fail-safe. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own one adaptive shell with Meeting under Today, Projects as the peer destination and New Meeting as the persistent primary action.

PRS-18 now has two deliberately separate target-Mac evidence paths:

- **release evidence**: `release_build` creates the exact clean Developer-ID-signed, securely timestamped, notarized/stapled `.app` + DMG and Gatekeeper evidence; `release_evidence` runs that immutable production app through WKWebView/TCC FULL_MEDIA, real local MLX/resource/thermal, PRS-9 benchmark and the dedicated PRS-16 AI-busy contention confirmation;
- **LOCAL REAL_ENVIRONMENT**: `python3 scripts/run_local_real_environment_suite.py` builds or reuses one exact finalized **ad-hoc** Apple-Silicon app, runs the same physical measured-release and PRS-16 evidence owners through a local-only artifact adapter, and writes privacy-bounded evidence under `dist/evidence/local-real-environment/<revision>/`. This path proves target-Mac behavior but explicitly marks distribution authority as blocked and does not establish release readiness.

The local adapter never changes the production artifact policy: invoking the canonical release runners normally still requires Developer ID + notarization evidence.

## Release evidence still pending

Stable promotion remains blocked until **RELEASE / FULL** automation and every applicable target-environment confirmation agree on the exact candidate.

Required remaining evidence:

- actual Developer-ID/notary authority producing the exact production artifact; when Apple Developer Program authority is unavailable this remains an explicit external release blocker rather than a failed local physical test;
- target-Mac WKWebView/window/accessibility-tree/keyboard-focus + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- real PRS-16 contention confirmation: local MLX active before Start and still active while `Preparing recording` is visible, waiting UI FULL_MEDIA captured, no premature capture, capture starts only after the safe boundary, and physical mic/system persistence succeeds;
- representative managed-AI/capture CPU/RSS/thermal observations and local MLX completion;
- PRS-9 representative dual-track vs mixed-track benchmark; changing the canonical strategy requires a separately validated change;
- subjective VoiceOver/usability observation where materially required;
- representative evidence for any material production ASR/LLM quality or latency claim.

A passing LOCAL REAL_ENVIRONMENT run can satisfy the applicable physical target-Mac behavior observations above for its exact ad-hoc artifact, but it cannot satisfy Developer ID/notarization/stapling/distribution-Gatekeeper qualification for the stable release artifact.

PRS-16 proves safe priority at the next supported boundary, not instant pre-emption. Hosted/browser evidence does not substitute for target-Mac or subjective accessibility proof.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release active.

## Next highest-value work

1. Freeze the exact `dev` candidate and live `main` base; obtain selector-owned RELEASE/FULL automation for that exact identity.
2. When Apple distribution authority is unavailable, run `python3 scripts/run_local_real_environment_suite.py` on the representative Apple-Silicon Mac and retain the exact local evidence; keep Developer ID/notary distribution authority explicitly blocked rather than relabeling local evidence as release evidence.
3. If/when Apple distribution authority becomes available, build the Developer-ID-signed/notarized production artifact from the exact candidate, run the canonical release evidence against that immutable artifact, record any materially required subjective VoiceOver observation, recheck candidate/base freshness/full diff and only then promote to `main`.
