# Current state

## Engineering baseline

Baseline: `repo-template-sw` **0.10.0**, **L2**; profiles Python/TS/macOS/local-AI/product-UI. Integration → `dev`; `dev → main` requires RELEASE/FULL and target-Mac evidence. Distributable binaries need separate artifact qualification.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..17: Meeting-first transcription/analysis, visual on-demand, bounded model residency, structured notes, archive search, capture priority and adaptive Today/Meeting/Projects. Dual-track audio still needs representative evidence.
- PR #186 (`9c7f86c`): dev port 1237, isolated data, non-destructive startup; physical check pending.
- PR #189 (`03a6d6d`): minimal Voices timeline, shared player and restore; browser FULL_MEDIA passed, installed WKWebView/real audio pending.
- PR #183 (`9df62d0`) integrated: optional GCS preference only; effective storage stays local. Upload/restore/eviction not enabled.
- PR #181: local voice samples, rename/merge/exclude/undo integrated; packaged WKWebView/audio/accessibility proof pending.
- PRs #194–196/#198–199: compact conversation, source/person identity, scoped correction/undo, stale-note warning and synthetic 5,005-turn browser/Mac PASS. Historical imports, performance and installed WKWebView/audio/VoiceOver proof pending.
- PRS-18 tooling and target-Mac measured/AI-contention evidence suite are in place (#48/#53).
- Release: root `VERSION=0.2.0` owns product version; app identity `ClosedRoom.app` / `com.closedroom.app` stays fixed. Final artifacts carry version/build/source SHA.
- PRs #137–139 consolidated UI/ASR and bounded footprint audit; path/upload caches remain separate, native dependency removal awaits Mac measurements.
- GRP-3..5 stage immutable source-identified artifacts and build/draft releases locally from exact tags; Actions release builds retired, Apple notarization mandatory.

## Current integration state

`HeavyWorkloadArbiter` owns bounded heavy work; recording reserves priority, waits at safe boundaries and releases queued work after Stop. `ResourcePolicy` fails safe; `RecordingStore` persists. The frontend shows cancellable preparation, starts the timer only after capture, and `App.tsx`/`workspace.css` own the shell.

Native retention/checkpoint recovery needs target-Mac release proof; no power-loss guarantee.

PRS-18 target-Mac evidence paths: **production** signs/notarizes exact app/DMG and runs WKWebView/TCC, MLX, thermal and contention checks; **local** `scripts/run_local_real_environment_suite.py` verifies one finalized ad-hoc Apple-Silicon app, not public distribution.

## Stable-source evidence still pending

Promotion `dev -> main` requires **RELEASE/FULL** and target-Mac evidence for the exact candidate.

Still required where material:

- target-Mac WKWebView/accessibility + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- PRS-16 real AI-busy contention: local MLX active while `Preparing recording` is visible, no premature capture, then capture after the safe boundary with mic/system persistence;
- representative CPU/RSS/thermal + local MLX completion and the PRS-9 dual-vs-mixed benchmark;
- subjective VoiceOver/usability and representative production ASR/LLM quality or latency only when material;
- installed WKWebView voice journey (real dual tracks, sample playback, correction/undo, keyboard/VoiceOver) and long/legacy transcripts. Speaker-sensitive notes now derive a read-only current/stale/unverifiable status; no automatic rewrite of old notes.

Public binaries additionally require Developer ID signing, notarization/stapling and Gatekeeper acceptance.

## Active workstreams

- [`audio-continuity-auto-recovery.md`](workstreams/audio-continuity-auto-recovery.md): P0 integrato in `dev` via PR #176 (`772a5f68`): ripresa microfono e audio sistema solo nativo; FULL automated PASS, switch fisico/TCC ancora da provare.
- [`meeting-detection.md`](workstreams/meeting-detection.md): default-on/retry integrated (#184); real Teams/Zoom notifications/TCC pending.
- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured product/runtime release evidence active.
- [`github-release-productization.md`](workstreams/github-release-productization.md): GRP-1..5 automation implemented; Apple authority/environment configuration and first public release remain blocked.
- [`architectural-consolidation.md`](workstreams/architectural-consolidation.md): Wave 1 integrated; Wave 2 internal runtime/service boundaries under integration validation.
- [`selective-efficiency.md`](workstreams/selective-efficiency.md): persisted audio fingerprint reuse and privacy-safe VAD comparison tooling; ONNX removal remains evidence-gated.
- [`speaker-transcript-experience.md`](workstreams/speaker-transcript-experience.md): #194–196/#198–199 integrated; historical import, text-only/empty browser and packaged speaker UX evidence pending.

- Meeting Moments (#100) integrated; Mac menu/focus/hotkey/TCC remains RELEASE evidence.

## Next highest-value work

1. ACR: verificare switch reale BT/USB, gap, dual-track e permessi TCC su build installata; non dedurre la ripresa fisica dai test automatici.
2. Complete remaining PRS-18 target-Mac evidence on the exact stable candidate and promote stable source only when RELEASE/FULL evidence agrees.
3. Run `release_build` locally with Apple authority on the exact tag; create a draft with `release_draft`.
4. Publish GRP-6 only after exact stable source and exact qualified artifact agree; add README download links only after a real GitHub Release exists.
