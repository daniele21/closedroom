# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is the stable-source RELEASE boundary. Applicable target-Mac product/runtime evidence blocks that boundary. Public binary distribution is separately qualified from an exact stable `main` commit/tag.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio benchmark tooling; dual-track audio remains canonical pending representative evidence.
- PRS-11..17 integrated saved Meetings/Prepare notes, structured verifiable notes, bounded archive search, safe capture priority and adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306, including 411 Python tests and declared Meeting FULL_MEDIA journeys.
- PRS-18 tooling integrated through PR #48; PR #53 added aggregate REAL_ENVIRONMENT coverage for measured target-Mac and PRS-16 contention owners.
- PR #65 made Search release evidence prove accessible open/focus/close rather than synthetic Cmd-K/Escape delivery; shortcuts remain technically tested but are not a stable-source blocker.
- PRS-18 measured product/runtime release evidence remains active.
- GitHub release productization separates stable source from binary publication. Root `VERSION` owns the ClosedRoom product version (`0.2.0`) independently from the Python package version.
- GRP-3 defines release staging as an adapter over immutable production artifacts: exact version/source/distribution evidence, unchanged DMG bytes, canonical public names, checksums, notes and asset inventory.

## Current integration state

`HeavyWorkloadArbiter` is the sole heavy-work owner. Capture waits for a safe managed-work boundary, queues bounded work during recording and releases it afterward; `ResourcePolicy` is the fail-safe. `RecordingStore` owns persistence and external runtimes remain caller-owned.

The frontend reserves before capture, shows cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own the adaptive shell.

PRS-18 has two target-Mac evidence paths:

- **production distribution evidence**: `release_build` produces the exact Developer-ID-signed, timestamped, notarized/stapled app + DMG and Gatekeeper proof; `release_evidence` exercises that immutable artifact through WKWebView/TCC FULL_MEDIA, local MLX/resource/thermal, PRS-9 and PRS-16 contention evidence;
- **LOCAL REAL_ENVIRONMENT**: `python3 scripts/run_local_real_environment_suite.py` builds or reuses one exact finalized **ad-hoc** Apple-Silicon app and runs the same physical product/runtime evidence owners. Evidence lives under `dist/evidence/local-real-environment/<revision>/`. This can prove target-Mac behavior for stable-source promotion, never signed public distribution.

The local adapter does not weaken the production-signing path.

## Stable-source evidence still pending

Promotion `dev -> main` remains blocked until **RELEASE / FULL** automation and applicable target-environment observations agree on the exact candidate.

Still required where material:

- target-Mac WKWebView/accessibility + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability and representative production ASR/LLM quality or latency only when material.

Apple distribution authority is **not** a stable-source prerequisite. It remains required before a normal downloadable macOS binary can be published:

- Developer ID signing and secure timestamp;
- app/DMG notarization and stapling;
- distribution Gatekeeper acceptance.

A passing LOCAL REAL_ENVIRONMENT run may close physical product/runtime obligations for an exact stable candidate while public binary distribution remains externally blocked.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured product/runtime release evidence active.
- [`github-release-productization.md`](workstreams/github-release-productization.md): GRP-1 stable-source/distribution separation, GRP-2 canonical versioning and GRP-3 release surface/staging implemented; draft GitHub Release automation remains.

PRS-18 owns product/runtime evidence; GitHub release productization owns version/release/publication mechanics.

## Next highest-value work

1. Complete remaining PRS-18 target-Mac evidence on the exact stable candidate without treating Apple distribution authority as a blocker to `main`.
2. Implement GRP-4 draft GitHub Release automation bound to tag/main and qualified GRP-3 output.
3. Keep stable binary publication blocked until Apple distribution authority qualifies the exact immutable artifact; add README download links only after a real GitHub Release exists.
