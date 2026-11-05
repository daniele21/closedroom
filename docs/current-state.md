# Current state

## Engineering baseline

Baseline: `repo-template-sw` **0.10.0**, **L2**, profiles Python/TypeScript/macOS/local-AI/product-UI. Integration → `dev`; `dev → main` requires RELEASE/FULL and target-Mac evidence. Distributable binaries need separate artifact qualification.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio benchmark tooling; dual-track audio remains canonical pending representative evidence.
- PRS-11..17 integrated saved Meetings/Prepare notes, structured verifiable notes, bounded archive search, safe capture priority and adaptive Today/Meeting/Projects workspace.
- PR #186 integrated (`9c7f86c`): source server port 1237, isolated Development data, non-destructive startup; physical check pending.
- PR #189 (`03a6d6d`) integrated: minimal Voices timeline, shared player, restore; 894 tests + browser FULL_MEDIA PASS. WKWebView/real audio pending.
- PR #183 (`9df62d0`) integrated: optional GCS preference only; effective storage stays local. Upload/restore/eviction not enabled.
- PR #181: local voice samples, rename/merge/exclude/undo integrated; packaged WKWebView/audio/accessibility proof pending.
- PRS-18 tooling integrated through PR #48; PR #53 added aggregate REAL_ENVIRONMENT coverage for measured target-Mac and PRS-16 contention owners.
- Release: root `VERSION=0.2.0` owns product version; app identity `ClosedRoom.app` / `com.closedroom.app` stays fixed. Final artifacts carry version/build/source SHA.
- PR #137 consolidated UI/ASR; path/upload caches stay distinct. PRs #138–139 cut doc media and add read-only footprint audit; native dependency removal awaits Mac measurements.
- GRP-3 stages immutable artifacts with source identity and checksums.
- GRP-4/5 now build and draft releases locally from the exact tag; Actions release workflows are retired. Apple notarization remains mandatory.

## Current integration state

`HeavyWorkloadArbiter` is the sole heavy-work owner. Capture waits for a safe managed-work boundary, queues bounded work during recording and releases it afterward; `ResourcePolicy` is the fail-safe. `RecordingStore` owns persistence and external runtimes remain caller-owned.

The frontend reserves before capture, shows cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own the adaptive shell.

Native retention/checkpoint recovery needs target-Mac release proof; no power-loss guarantee.

PRS-18 has two target-Mac evidence paths:

- **Production**: `release_build` signs/notarizes the exact app + DMG; `release_evidence` covers WKWebView/TCC, MLX, thermal and contention on that artifact;
- **Local**: `scripts/run_local_real_environment_suite.py` runs target-Mac checks on one exact finalized ad-hoc Apple-Silicon app. Evidence: `dist/evidence/local-real-environment/<revision>/`; not public distribution proof.

## Stable-source evidence still pending

Promotion `dev -> main` remains blocked until **RELEASE / FULL** automation and applicable target-environment observations agree on the exact candidate.

Still required where material:

- target-Mac WKWebView/accessibility + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability and representative production ASR/LLM quality or latency only when material.

Stable source needs target-Mac evidence, not Apple distribution authority. A downloadable binary additionally needs Developer ID signing, notarization/stapling and Gatekeeper acceptance.

## Active workstreams

- [`audio-continuity-auto-recovery.md`](workstreams/audio-continuity-auto-recovery.md): P0 integrato in `dev` via PR #176 (`772a5f68`): ripresa microfono e audio sistema solo nativo; FULL automated PASS, switch fisico/TCC ancora da provare.
- [`meeting-detection.md`](workstreams/meeting-detection.md): default-on/retry integrated (#184); real Teams/Zoom notifications/TCC pending.
- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured product/runtime release evidence active.
- [`github-release-productization.md`](workstreams/github-release-productization.md): GRP-1..5 automation implemented; Apple authority/environment configuration and first public release remain blocked.
- [`architectural-consolidation.md`](workstreams/architectural-consolidation.md): Wave 1 integrated; Wave 2 internal runtime/service boundaries under integration validation.
- [`selective-efficiency.md`](workstreams/selective-efficiency.md): persisted audio fingerprint reuse and privacy-safe VAD comparison tooling; ONNX removal remains evidence-gated.

- Meeting Moments (#100) integrated; Mac menu/focus/hotkey/TCC remains RELEASE evidence.

## Next highest-value work

1. ACR: verificare switch reale BT/USB, gap, dual-track e permessi TCC su build installata; non dedurre la ripresa fisica dai test automatici.
2. Complete remaining PRS-18 target-Mac evidence on the exact stable candidate and promote stable source only when RELEASE/FULL evidence agrees.
3. Run `release_build` locally with Apple authority on the exact tag; create a draft with `release_draft`.
4. Publish GRP-6 only after exact stable source and exact qualified artifact agree; add README download links only after a real GitHub Release exists.
