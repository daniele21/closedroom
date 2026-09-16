# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is the stable-source RELEASE boundary. Target-Mac product/runtime evidence is blocking when applicable at that boundary. Public binary distribution is a separate qualification from an exact stable `main` commit/tag.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative evidence.
- PRS-11..17 integrated saved Meetings/Prepare notes, structured verifiable notes, bounded archive search, safe capture priority and the adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306, including 411 Python tests and declared Meeting FULL_MEDIA journeys.
- PRS-18 release tooling integrated through PR #48; PR #53 added one aggregate REAL_ENVIRONMENT runner over the measured target-Mac and PRS-16 contention owners while keeping product/runtime qualification fail-closed.
- PRS-18 measured product/runtime release evidence remains active.
- GitHub release productization is active in parallel; stable source promotion and public binary publication now have explicit non-overlapping contracts.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. Capture waits for the next safe managed-work boundary, holds bounded queued work during recording and releases it afterward; `ResourcePolicy` remains the fail-safe. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own the adaptive shell.

PRS-18 has two target-Mac evidence paths with different claims:

- **production distribution evidence**: `release_build` produces the exact Developer-ID-signed, securely timestamped, notarized/stapled app + DMG and Gatekeeper proof; `release_evidence` exercises that immutable artifact through WKWebView/TCC FULL_MEDIA, real local MLX/resource/thermal, PRS-9 and PRS-16 contention evidence;
- **LOCAL REAL_ENVIRONMENT**: `python3 scripts/run_local_real_environment_suite.py` builds or reuses one exact finalized **ad-hoc** Apple-Silicon app and runs the same physical product/runtime evidence owners through a local-only adapter. Evidence is written under `dist/evidence/local-real-environment/<revision>/`. This can establish representative target-Mac behavior for stable-source promotion, but never establishes signed public distribution.

The local adapter does not modify or weaken the production-signing path.

## Stable-source evidence still pending

Promotion `dev -> main` remains blocked until **RELEASE / FULL** automation and every applicable target-environment product/runtime observation agree on the exact candidate.

Still required where material:

- target-Mac WKWebView/accessibility + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability only where materially required and representative evidence for material production ASR/LLM quality or latency claims.

Apple distribution authority is **not** a stable-source promotion prerequisite. It remains required before a normal downloadable macOS binary can be published as a stable GitHub Release:

- Developer ID signing and secure timestamp;
- app/DMG notarization and stapling;
- distribution Gatekeeper acceptance.

A passing LOCAL REAL_ENVIRONMENT run may therefore close the applicable physical product/runtime obligations for an exact stable candidate while public binary distribution remains externally blocked.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured product/runtime release evidence active.
- [`github-release-productization.md`](workstreams/github-release-productization.md): GRP-1 stable-source/distribution separation implemented; canonical product versioning and draft GitHub Release automation remain.

These workstreams have separate write/ownership boundaries: PRS-18 owns product/runtime evidence; GitHub release productization owns version/release/publication mechanics.

## Next highest-value work

1. Complete the remaining PRS-18 target-Mac product/runtime evidence on the exact stable candidate, without treating Apple distribution authority as a blocker to `main`.
2. Resolve the non-essential synthetic shortcut checkpoint so target-Mac qualification reflects release-critical user outcomes rather than synthetic key injection.
3. Implement GRP-2: add one canonical ClosedRoom product version owner before tag/release automation.
4. After stable promotion, implement draft GitHub Release publication from an exact `main` tag and publish a binary only when Apple distribution authority can qualify the exact immutable artifact.
