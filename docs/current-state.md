# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; under the current contract `dev -> main` is RELEASE. Target-Mac evidence is blocking only at release.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative evidence.
- PRS-11..17 integrated saved Meetings/Prepare notes, structured verifiable notes, bounded archive search, safe capture priority and the adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306, including 411 Python tests and declared Meeting FULL_MEDIA journeys.
- PRS-18 release tooling integrated through PR #48; PR #53 added one aggregate REAL_ENVIRONMENT runner over the measured target-Mac and PRS-16 contention owners while keeping release qualification fail-closed.
- PRS-18 measured release remains active.
- GitHub release productization is now planned in parallel so stable source promotion, product versioning and public binary publication have explicit non-overlapping contracts.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. Capture waits for the next safe managed-work boundary, holds bounded queued work during recording and releases it afterward; `ResourcePolicy` remains the fail-safe. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own the adaptive shell.

PRS-18 has two separate target-Mac evidence paths:

- **release evidence**: `release_build` produces the exact Developer-ID-signed, securely timestamped, notarized/stapled app + DMG and Gatekeeper proof; `release_evidence` exercises that immutable artifact through WKWebView/TCC FULL_MEDIA, real local MLX/resource/thermal, PRS-9 and PRS-16 contention evidence;
- **LOCAL REAL_ENVIRONMENT**: `python3 scripts/run_local_real_environment_suite.py` builds or reuses one exact finalized **ad-hoc** Apple-Silicon app and runs the same physical evidence owners through a local-only adapter. Evidence is written under `dist/evidence/local-real-environment/<revision>/`. This proves target-Mac behavior but never establishes signed public distribution.

The local adapter does not modify the canonical production-signing runners or their Developer ID/notarization requirement.

## Release evidence still pending

The current repository contract still blocks stable promotion until **RELEASE / FULL** automation and applicable target-environment evidence agree on the exact candidate, including distribution authority. The GitHub release productization workstream will deliberately split stable-source promotion from public binary distribution; until GRP-1 is implemented and integrated, the existing contract remains authoritative.

Product/runtime evidence still required where applicable:

- target-Mac WKWebView/accessibility + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability only where materially required and representative evidence for material production ASR/LLM quality or latency claims.

Distribution-only evidence remains separately blocked without Apple Developer authority:

- Developer ID signing and secure timestamp;
- app/DMG notarization and stapling;
- distribution Gatekeeper acceptance.

A passing LOCAL REAL_ENVIRONMENT run can satisfy applicable physical target-Mac product observations for its exact ad-hoc artifact, but cannot establish signed binary distribution qualification.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured product/runtime release evidence active.
- [`github-release-productization.md`](workstreams/github-release-productization.md): release-publication productization active; GRP-1 separates stable source from binary distribution, followed by canonical product versioning and draft GitHub Release automation.

These workstreams have separate write/ownership boundaries: PRS-18 owns product/runtime evidence; GitHub release productization owns version/release/publication mechanics.

## Next highest-value work

1. Implement GRP-1 so `dev -> main` can mean stable source promotion with FULL + applicable REAL_ENVIRONMENT product evidence, while Developer ID/notarization remains a separate public-distribution gate.
2. Add one canonical ClosedRoom product version owner before creating tag/release automation.
3. Complete the remaining PRS-18 target-Mac product evidence on the exact stable candidate without spending release effort on non-essential synthetic shortcut injection.
4. After stable promotion, implement draft GitHub Release publication from an exact `main` tag and publish a binary only when Apple distribution authority can qualify the exact immutable artifact.
