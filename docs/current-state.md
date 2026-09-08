# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.10.0**, maturity **L2**, with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. Integration requires selector-owned deterministic/E2E evidence; applicable target-Mac evidence is blocking only at release.

## Integrated baseline

- Exact-head/tree-equivalent preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- PRS-5..9 integrated Meeting-first defaults, visual on-demand, bounded model residency, SSE progress and privacy-safe audio-strategy benchmark tooling; dual-track audio remains canonical pending representative release evidence.
- PRS-11..14 integrated fast saved-Meeting open, durable `Prepare notes`, one structured default notes run and source-verifiable editable actions/decisions.
- PRS-15 / #39 integrated bounded FTS5-backed local archive search.
- Governance baseline 0.10.0 / #40 is integrated.
- PRS-16 / #41 integrated capture priority at the next safe managed-work boundary without force-killing active AI or losing bounded queued work; its STRONG evidence passed source, browser FULL_MEDIA and packaged lifecycle gates.
- PRS-17 / #43 integrated one adaptive Today/Meeting/Projects workspace. Candidate `c1c79f31` passed FULL preflight #306: guards, frontend, 411 Python tests, all declared Meeting FULL_MEDIA journeys, packaged lifecycle and repository validation.
- The MIT `LICENSE` already on stable `main` was restored to the release line through PR #46.
- Product/runtime convergence and UX simplification are complete for development integration; their release obligations are consolidated below.
- Target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`.

## Current integration state

`HeavyWorkloadArbiter` remains the sole heavy-work owner. A transient capture reservation waits for active managed work to finish normally, blocks queued heavy work during capture and releases it afterward; `ResourcePolicy(capture_active)` remains the fail-safe for unreserved capture. `RecordingStore` remains the persistence owner and external runtimes remain caller-owned.

The frontend reserves before capture, shows truthful cancellable preparation, starts the timer only with real capture and releases priority on Stop/failure/recovery. `App.tsx` + `workspace.css` own one adaptive shell: Meeting remains under Today, Projects is the peer destination, New Meeting stays primary and Settings/theme/language/tour/demo/runtime status remain utilities. Routing, persistence, capture, preparation and runtime owners are unchanged.

## Release evidence still pending

PRS-18 is the only active workstream. Stable promotion is blocked until **RELEASE / FULL** automation and every applicable target-environment confirmation agree on the exact candidate.

Required release evidence:

- target-Mac packaged WKWebView/window/accessibility-tree/keyboard-focus behavior plus recording FULL_MEDIA;
- TCC-backed native `both` capture with non-empty mic + system-audio persistence and clean lifecycle;
- representative CPU/RSS/Metal/thermal behavior under capture and managed AI;
- PRS-9 representative dual-track vs mixed-track benchmark; changing the canonical strategy requires a separately validated change;
- production signing/notarization before distributing a production artifact;
- subjective VoiceOver/usability observation where materially required;
- representative evidence for any material production ASR/LLM quality or latency claim.

PRS-16 proves safe priority at the next supported boundary, not instant pre-emption. Browser UI evidence does not substitute for packaged target-Mac or subjective accessibility proof.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..17 integrated; PRS-18 measured release active.

## Next highest-value work

1. Prepare exact `dev -> main` PRS-18 and run selector-owned **RELEASE / FULL** automation against live `main`.
2. Collect blocking target-Mac UI/TCC, representative resource/thermal and PRS-9 audio evidence.
3. Verify the production-signed/notarized artifact before stable promotion; keep `main` unchanged while any required release gate is missing.
