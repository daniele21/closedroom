# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. Target-Mac evidence is blocking only at release.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative evidence.
- PRS-11..17 integrated saved Meetings/Prepare notes, structured verifiable notes, bounded archive search, safe capture priority and the adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306, including 411 Python tests and declared Meeting FULL_MEDIA journeys.
- PRS-18 release tooling integrated through PR #48; PR #53 added one aggregate REAL_ENVIRONMENT runner over the measured target-Mac and PRS-16 contention owners while keeping release qualification fail-closed.
- PRS-18 measured release remains the only active workstream.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. Capture waits for the next safe managed-work boundary, holds bounded queued work during recording and releases it afterward; `ResourcePolicy` remains the fail-safe. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own the adaptive shell.

PRS-18 has two separate target-Mac evidence paths:

- **release evidence**: `release_build` produces the exact Developer-ID-signed, securely timestamped, notarized/stapled app + DMG and Gatekeeper proof; `release_evidence` exercises that immutable artifact through WKWebView/TCC FULL_MEDIA, real local MLX/resource/thermal, PRS-9 and PRS-16 contention evidence;
- **LOCAL REAL_ENVIRONMENT**: `python3 scripts/run_local_real_environment_suite.py` builds or reuses one exact finalized **ad-hoc** Apple-Silicon app and runs the same physical evidence owners through a local-only adapter. Evidence is written under `dist/evidence/local-real-environment/<revision>/`. This proves target-Mac behavior but never establishes distribution or release readiness.

The local adapter does not modify the canonical release runners or their Developer ID/notarization requirement.

## Release evidence still pending

Stable promotion remains blocked until **RELEASE / FULL** automation and applicable target-environment evidence agree on the exact candidate.

Still required:

- Developer-ID/notary authority for the exact production artifact; without Apple Developer Program membership this is an explicit external release blocker, not a failed local physical test;
- target-Mac WKWebView/accessibility/focus + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability where materially required and representative evidence for material production ASR/LLM quality or latency claims.

A passing LOCAL REAL_ENVIRONMENT run can satisfy the applicable physical target-Mac observations for its exact ad-hoc artifact, but cannot satisfy Developer ID/notarization/stapling/distribution-Gatekeeper qualification.

## Active workstream

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release active.

## Next highest-value work

1. Freeze the exact `dev` candidate and live `main` base and obtain RELEASE/FULL automation.
2. Without Apple distribution authority, run `python3 scripts/run_local_real_environment_suite.py` on the representative Mac and retain its exact evidence while keeping distribution authority blocked.
3. If distribution authority becomes available, run the canonical signed/notarized release path and promote only when all blocking evidence matches the frozen candidate.
