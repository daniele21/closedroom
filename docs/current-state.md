# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. Integration requires selector-owned deterministic/E2E evidence; applicable target-Mac evidence is blocking only at release.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative release evidence.
- PRS-11..17 integrated the saved-Meeting/Prepare-notes flow, structured verifiable notes, bounded archive search, safe capture priority and one adaptive Today/Meeting/Projects workspace.
- PRS-17 candidate `c1c79f31` passed FULL preflight #306: guards, frontend, 411 Python tests, all declared Meeting FULL_MEDIA journeys, packaged lifecycle and repository validation.
- The MIT `LICENSE` already on stable `main` was restored to the release line through PR #46.
- Product/runtime convergence and UX simplification development workstreams are finalized; PRS-18 is the only active workstream.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. Capture waits for the next safe managed-work boundary, holds bounded queued work during recording and releases it afterward; `ResourcePolicy` remains the unreserved-capture fail-safe. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation and starts the timer only with real capture. `App.tsx` + `workspace.css` own one adaptive shell with Meeting under Today, Projects as the peer destination and New Meeting as the persistent primary action.

PRS-18 release tooling is being integrated around two canonical commands:

- `release_build`: build the exact clean candidate with Developer ID + secure timestamp, notarize/staple the `.app`, build and notarize/staple the DMG, verify Gatekeeper, then write immutable manifest/checksums;
- `release_evidence`: run that exact production `.app` on the target Mac through the normal WKWebView/TCC recording FULL_MEDIA + local MLX/resource/thermal + PRS-9 benchmark protocol, then run a dedicated PRS-16 contention confirmation that requires real managed MLX to be active when Start is pressed, captures bounded window FULL_MEDIA for the truthful waiting → recording transition, proves capture is not active while AI owns the safe boundary, and finally verifies TCC-backed native `both` capture with non-empty mic/system tracks after the workload completes.

## Release evidence still pending

Stable promotion remains blocked until **RELEASE / FULL** automation and every applicable target-environment confirmation agree on the exact candidate.

Required remaining evidence:

- actual Developer-ID/notary authority producing the exact production artifact;
- target-Mac WKWebView/window/accessibility-tree/keyboard-focus + TCC-backed native `both` capture with non-empty mic/system tracks and clean lifecycle;
- real PRS-16 contention confirmation: local MLX active before Start, waiting UI FULL_MEDIA captured, no premature capture, capture starts only after the safe boundary, and physical mic/system persistence succeeds;
- representative managed-AI/capture CPU/RSS/thermal observations and local MLX completion;
- PRS-9 representative dual-track vs mixed-track benchmark; changing the canonical strategy requires a separately validated change;
- subjective VoiceOver/usability observation where materially required;
- representative evidence for any material production ASR/LLM quality or latency claim.

PRS-16 proves safe priority at the next supported boundary, not instant pre-emption. Hosted/browser evidence does not substitute for target-Mac or subjective accessibility proof.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release active.

## Next highest-value work

1. Integrate the PRS-18 release tooling into `dev` with selector-owned exact-head validation.
2. Create the exact production artifact from the final `dev` candidate and collect both normal measured-release and AI-busy capture target-Mac evidence.
3. Open `dev -> main` only after live `main` freshness, RELEASE/FULL automation and the matching REAL_ENVIRONMENT evidence are all complete.
