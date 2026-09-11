# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-11..17 integrated; PRS-18 measured release in progress
Owner: meeting product, canonical job/persistence owners and local runtime
Integration checkpoint: PRS-18 tooling merged on `dev` at `94fa3d3`, 2026-09-08; final release candidate not yet frozen.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. No production performance, memory, audio-strategy or release-readiness claim is accepted without representative evidence.

- Meeting is primary; normal recording requires no technical choice.
- `Prepare notes` is explicit after Stop; `Transcript only` is secondary.
- Reuse valid transcript and notes; ready notes open first unless the user selects another tab.
- Audio/transcript survive enrichment failure/cancel; local-first and explicit cloud opt-in remain unchanged.
- Canonical owners remain RecordingStore, JobStore, CatalogStore, HeavyWorkloadArbiter and runtime services.
- Excluded: rewrite, second scheduler/runtime/index owner, implicit cloud, mandatory visuals, unsafe kill, unproven audio strategy.
- Stable promotion is `dev -> main`, always RELEASE/FULL, and applicable REAL_ENVIRONMENT evidence is blocking.

## Work graph

| ID | Observable outcome | State |
| --- | --- | --- |
| PRS-11 | Fast saved Meeting open | DONE |
| PRS-12 | One recoverable Prepare notes action | DONE |
| PRS-13 | Consistent notes with less repeated inference | DONE |
| PRS-14 | Verify/edit actions and decisions | DONE |
| PRS-15 | Search complete local archive | DONE |
| PRS-16 | Record safely while AI is busy | DONE |
| PRS-17 | Coherent macOS workspace | DONE |
| PRS-18 | Measured production release | IN PROGRESS |

## Integrated slices

PRS-11..14 established independent saved-Meeting loading, one durable recoverable `meeting_preparation` parent, one structured default notes analysis and source-anchored editable actions/decisions with revision/conflict semantics.

PRS-15 added bounded server-side FTS5 archive search inside canonical `closedroom.db`; PR #39 integrated source/frontend tests, `meeting-archive-search` FULL_MEDIA and packaged FTS5 smoke.

PRS-16 kept `HeavyWorkloadArbiter` as the sole heavy-work scheduler and added one transient capture reservation. Active managed work finishes normally; queued work remains bounded and waits during capture; the frontend shows preparation until real capture starts. PR #41 integrated STRONG source/browser/package evidence. Physical audio/TCC and representative MLX/thermal behavior remained release-only.

PRS-17 converged Today, saved Meeting and Projects into one adaptive macOS workspace without changing routing/data/runtime ownership. PR #43 integrated on `dev`; exact candidate `c1c79f31` passed FULL preflight #306 with guards, frontend checks, 411 Python tests, every declared Meeting browser FULL_MEDIA journey and packaged lifecycle validation.

PRS-18 release tooling integrated through PR #48. Exact source head `9bfd7efc` passed INTEGRATION/FULL preflight #329; squash merge `94fa3d3` preserved the validated source tree. The integrated tooling owns production signing/notarization, measured target-Mac release evidence and the physical PRS-16 AI-busy contention confirmation. This proves tooling integration only: production authority and target-environment evidence remain pending and blocking for stable promotion.

## PRS-18 — measured release

### Outcome

Promote only an exact production candidate that is fully validated automatically and on representative Apple-Silicon hardware. Final-environment evidence confirms the candidate; it must not discover basic deterministic regressions that belonged in integration.

### Production artifact owner

Canonical command:

```bash
python3 scripts/build_production_artifact.py
```

Required properties:

- clean Apple-Silicon checkout and full source revision identity;
- Developer ID Application signing with hardened runtime and secure timestamp;
- notarize the signed `.app` archive, staple/validate the `.app`, and pass Gatekeeper execution assessment;
- build the DMG from that stapled app, notarize/staple/validate the DMG and pass Gatekeeper open assessment;
- restore only generated frontend source output after packaging and fail if the checkout is otherwise dirty or moves;
- write production release evidence before immutable build manifest/checksums, with no post-finalization artifact mutation;
- missing signing identity, notary profile, tools or Apple acceptance fails closed.

### Target-Mac evidence owner

Canonical command:

```bash
python3 scripts/measured_release_target_mac.py --app <exact-production-app> && \
python3 scripts/record_while_ai_busy_target_mac.py --app <exact-production-app>
```

One exact production `.app` must prove:

1. packaged WKWebView/window/accessibility-tree/keyboard-focus journey with FULL_MEDIA;
2. TCC-backed native `both` capture and non-empty persisted `mic` + `system` tracks;
3. clean application/runtime lifecycle;
4. a real local transcription job on the captured meeting, with `HeavyWorkloadArbiter` activity observed;
5. bounded privacy-safe CPU/RSS/runtime scheduler samples and a macOS thermal/performance observation (`pmset -g therm`); missing data stays `unknown`, never zero;
6. local MLX completion rather than a cloud fallback;
7. PRS-9 `dual_track_vs_mixed_asr` benchmark on that same representative recording, using its real schema/repeat count and retaining no transcript text;
8. the PRS-16 physical contention boundary: navigate to a ready New Meeting, start a real local MLX transcription on an existing recording, observe `HeavyWorkloadArbiter` active before pressing Start and still active while the packaged UI visibly waits in `Preparing recording`, retain ClosedRoom-window FULL_MEDIA for the truthful waiting → active recording transition, require absence of active capture while AI runs, then require real native `both` capture with non-empty mic/system tracks after that workload reaches its normal boundary.

No numeric performance threshold is invented without a comparable baseline. The evidence runner records observations and completion truth; a later product/architecture change is required if benchmark evidence justifies changing the canonical dual-track strategy. Source/browser tests remain the primary proof for bounded queue ordering/cancellation; target-Mac contention evidence confirms the packaged WKWebView/TCC/physical-audio/MLX boundary instead of replacing those lower-level tests.

### Human evidence

VoiceOver spoken-output quality and subjective usability remain human judgement when materially required. Accessibility tree, focus and keyboard paths are automated and do not need to be reclassified as human work.

### Promotion

After tooling integration:

1. finish durable-state closeout, freeze the exact `dev` candidate and live `main` base, and keep/open the canonical `dev -> main` release PR;
2. run selector-owned RELEASE/FULL automation on that exact candidate/base;
3. build the production artifact from that exact source;
4. run both measured target-Mac evidence runners against the exact notarized artifact;
5. record any genuinely required subjective VoiceOver observation;
6. recheck candidate/base freshness and full diff;
7. promote to `main` only if all blocking evidence matches the candidate.

A candidate/base move, material source edit, build/signing mutation or artifact rebuild invalidates affected evidence.

## Evidence policy

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE requires FULL automation plus applicable target-Mac evidence. Hosted CI is never relabeled as physical TCC/audio/WKWebView/MLX proof.

Durable owners: `.engineering/commands.json`, `.engineering/e2e.json`, `docs/current-state.md`, `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and this active workstream. Complete PRS-18 only when source, artifact, automation, target-Mac evidence, docs and stable branch state agree.
