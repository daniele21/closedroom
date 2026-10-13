# Complexity ablation — behavior-preserving reduction

Status: ACTIVE — C3.1 IMPLEMENTED; integration evidence pending
Target: `dev`; work branch: `work/complexity-ablation`
Source identity at plan bootstrap: `dev` `15ec412ce10cb5e49438f6e09271f2883ea65973` (2026-10-13)
Read root/scoped AGENTS and the repository-owned validation selector and workstream skills.

## Desired outcome and non-goals

Reduce ClosedRoom complexity **without losing features, changing user journeys/contracts, or moving private data off-device**. Optimize ownership, states, dependencies and build/runtime costs, not line count alone.

Non-goals: redesign, unverified provider/model removal, wholesale rewrite, off-device processing, renaming, dropping browser fallback, opt-in providers or packaged app support.

Reuse `architectural-consolidation` and `selective-efficiency` evidence; do not duplicate their code or overlap PRs.

## Axes and boundaries

- PRODUCT: **PRODUCT_NONE** per behavior-preserving experiment. Reclassify to PRODUCT_LOCAL/FEATURE if observable semantics actually change and stop treating that experiment as pure ablation.
- DELIVERY: **ITERATION** per experiment; **INTEGRATION** PR -> `dev` only after exact-head/base proof. This plan alone is documentation.
- VALIDATION: **STRONG** for the overall cross-boundary effort; selector chooses concrete gates per experiment (SCOPED/STRONG; FULL when packaging/toolchain or release rules require). A pure planning edit is LEAN.
- EXECUTION: **AGENT_LOCAL** where equivalent tests can run; **REMOTE_AUTOMATED** for deterministic macOS/source/browser/build gates unavailable locally; **REAL_ENVIRONMENT** for physical TCC, audio, MLX/Metal/thermal and interactive macOS truth. Do not run packaged builds in GitHub Actions.
- Preserve `RecordingStore` as aggregate facade, SQLite catalog projection, `HeavyWorkloadArbiter` as sole heavy-work scheduler, `RuntimeServiceManager` as local LLM lifecycle owner, `frontend/src` as UI source, and native process/JSON interface.
- Preserve loopback auth/origin, no implicit cloud fallback, one owner per artifact/job/recording, bounded cancellation and cleanup, monotonic/idempotent chunk and screenshot contracts, finalized-artifact immutability, accessible keyboard/focus/VoiceOver paths, and Cocoa main-thread requirements.

## Experimental method

### AB-0: lock baseline and trace product coverage — READY

1. Pin `dev` commit/tree, environment and artifact; refresh for each candidate.
2. Map `docs/features.md` and `.engineering/e2e.json` to owners, API/persistence consumers, flows and failure states: native/browser recording and permissions, visuals/screenshots/notes/overlay, detection/menu bar, transcription/diarization, analysis/edits, archive/projects, jobs, opt-in providers, settings and packaging.
3. Separate known bugs and open PRs from ablation evidence; existing failures are not permission to remove features.
4. Capture HTTP/auth, old/new/interrupted storage, cancellation/restart/fallback, UI and model/provider fixtures; normalize nondeterminism only where safe, never expose private content.
5. On fixed hardware/scenarios, measure artifact/dependency bytes, startup, idle/recording/AI RSS, latency and cleanup; record samples/noise bands. Separate fake/CI and representative Mac/ASR evidence.

**Gate:** no destructive experiment without mapped behavior and a regression oracle. Baseline measurements: PENDING.

### AB-1: inventory candidates and value — READY

For each candidate produce one experiment card:
`ID | owner and direct consumers | current mechanism | hypothesized redundant mechanism | smallest reversible change | protected behavior | complexity metric | required gate | risk/blocked-by | evidence | decision`.

Metrics are **a vector** (not a vanity LOC score):
- Structural: reachable production SLOC, live modules, public interfaces, responsibilities/owner, duplicated policies, state variables/transitions, fan-in/fan-out, cyclic dependencies.
- Packaging: direct/transitive dependencies actually bundled, bundle bytes, build time, boot/import cost.
- Runtime: cold/warm start, idle/recording/ASR/LLM peak RSS/CPU, latency, thermal and I/O only where the lane touches them.
- Reliability: lifecycle/cancel/restart paths, test pass and behavioral coverage, output compatibility.
- Maintenance: deletion of a policy/owner/branch preferred over merely moving its lines into a new abstraction.

Choose one primary before/after metric, guardrails, and record negative results. Never trade protected behavior for an aggregate score.

### AB-2: one controlled ablation at a time — READY after AB-0/1

1. State one falsifiable hypothesis about redundant policy and preserved contract.
2. Branch from refreshed `dev`; one reversible change, no permanent flags or second owners.
3. Characterize the seam with identical-input differential tests, then remove/converge one mechanism.
4. Compare API/UI/storage/errors, run selected gates + affected E2E; FULL_MEDIA for material UI timing/sequence. Fakes never prove physical Mac/MLX.
5. Preserve model/provider/prompt/input/persistence; stochastic text need not be byte-equal. Obtain representative evidence if AI quality could change.
6. Repeat before/after benchmarks with identical model/cache/hardware/settings. Regression beyond uncertainty/limits = reject; unknown = NOT PROVEN.
7. Decide **KEEP/REWORK/REVERT/BLOCKED_FOR_EVIDENCE**. KEEP requires equivalence + meaningful reduction + no adverse tradeoff.
8. Before integration inspect full diff and exact head/base; use selector/preflight, no Actions builds or unnecessary reruns. Rebase remaining lanes.

### AB-3: convergence and stopping rule — READY after first KEEP

- Integrate proven small changes, not a rewrite; update canonical docs when affected.
- Keep a ledger: baseline, hypothesis, single change, risks/gates, metrics, result, exact evidence.
- Stop when gain is marginal, unproven, or adds conceptual complexity. Preserve negative evidence, not dead code.
- Target-Mac obligations remain RELEASE blockers; source tests do not prove release readiness.

## Initial, evidence-based candidate queue (not removal decisions)

Observed sizes from `dev` at bootstrap are *screening signals*, not proof of dead code or duplications:

| Queue | Candidate / baseline observation | Hypothesis & relation to existing work | Default gating |
| --- | --- | --- | --- |
| C1 | `frontend/src/pages/RecordingOverlayPage.tsx` ~1,236 lines, ~34 hooks | AC-2 follow-up: isolate the screenshot/note/display interaction policies and remove overlapping page state only if external contract stays stable. Beware current target-Mac overlay bugs. | SCOPED during iteration; STRONG/FULL_MEDIA if integration changes interactive flows |
| C2 | `frontend/src/pages/MeetingDetailPage.tsx` ~2,188 lines, ~33 hooks | AC-2: inspect remaining coordinator vs accessory lifecycle, remove redundant page orchestration after `useMeetingAccessories` extraction. | SCOPED -> affected UI E2E/FULL_MEDIA |
| C3 | `src/local_asr_server/routers/transcriptions.py` ~759 lines | AC-3: replace duplicate upload/path/recording orchestration with one existing use case without changing streaming, cache identity, provider options or payloads. | STRONG, shared API/cache/job contract |
| C4 | `src/local_asr_server/recordings.py` ~2,250 lines | AC-4: inventory legacy artifact/visual policy remaining after `ScreenshotArtifactStore`; eliminate only duplicative logic, preserve `RecordingStore` facade and recovery. Avoid open SQLite migration PR #86 overlap. | STRONG, persistence/recovery |
| C5 | `src/local_asr_server/menubar.py` ~1,360 lines | Shell owns many concerns, but do **not** ablate while menu visibility/detection and open PR #105 are unsettled; first stabilize physical behavior and derive narrow tests. | BLOCKED for now; STRONG + REAL_ENVIRONMENT when material |
| C6 | `ClosedRoom.spec` and pinned MLX/VLM/ASR dependencies | Reuse SE-3/4/5/6 evidence. Remove only runtime imports/deps conclusively unused in frozen image path. Never remove ONNX/Silero solely for size. | FULL packaged-app validation + representative quality when relevant |
| C7 | `src/local_asr_server/native_capture.py` ~1,168 lines | AC-5 native capture complexity: convergence only after protocol-level characterization and when Mac lifecycle evidence can be obtained. | STRONG + physical Mac obligations |

**Prioritization rule:** Start with contained, testable, low-overlap and reversible candidates; do not start C5/C6/C7 merely because of large file or bundle size. Favor **deletion/convergence** over decomposition-only changes where both preserve canonical ownership.

## Work graph and parallelism

```text
AB-0 feature/behavior + baseline proof (serial)
         |
AB-1 candidate ledger, risk/benefit ranking (serial)
         |
         +-- Lane UI: C1/C2 (shared frontend owner; serialize within lane)
         +-- Lane API: C3 (independent transcription boundary)
         +-- Lane data: C4 (avoid catalog/migration overlap)
         +-- Lane packaging: C6 (after representative SE evidence)
         |
AB-2 short reversible experiments + per-lane differential tests
         |
AB-3 integrate in small PRs -> refreshed dev; measure cumulative Pareto
         |
Release-only representative Mac validations where required
```

A lane has exclusive owning files. Native/menu bar lanes C5/C7 remain blocked until physical behavior/proofs and overlapping PRs settle. Do not run simultaneous changes against `useRecorder`, `RecordingStore`, database migrations, menu-bar shell or build selector from separate PRs.

## C3.1 — first controlled experiment

Hypothesis: four private route aliases of canonical `TranscriptionService` methods and three `finally: pass` blocks add no policy. Remove them while keeping route/API, cache, ASR, diarization and persistence behavior identical.

- Measured: `routers/transcriptions.py` **759 -> 721 lines (-38 / -5.0%)**, four forwarders + three empty finalizers removed, same endpoint decorators. This is owner-local, not a product-wide improvement.
- Characterization: new `test/test_transcription_router_ablation.py` covers path JSON/text response, provider option projection, persistence and 404/500; existing `test_transcription_application`, `test_recording_api` and transcription-workflow contracts remain required.
- Gate: **INTEGRATION / STRONG candidate**, subject to repository selector; automated tests **PENDING**, so KEEP is not established yet. No material UI, packaging or target-Mac behavior intended.
- Important boundary: upload uses final-result/diarization-aware caching while path uses ASR-result caching; unifying them is a **separate** C3.2 experiment that requires a differential oracle.

**Next:** verify exact PR head/base and all selected tests; classify failures, fix or revert; then rank follow-up candidates from real evidence.

## Resume checkpoint

- Baseline branch/head observed: `dev` @ `15ec412ce10cb5e49438f6e09271f2883ea65973`; MUST refresh on resume.
- Existing workstreams: `docs/workstreams/architectural-consolidation.md`, `docs/workstreams/selective-efficiency.md`.
- Open overlapping PRs at inspection: #105 (menu bar), #95 (VAD benchmark), #86 (SQLite migrations).
- Structural observations: C1–C7 sizes measured by fetching files on `dev`, not by local AST/test execution.
- C3.1 source changed, but exact-head test equivalence is NOT YET VERIFIED; no app build or representative Mac measurement performed.
- Next discriminating action: run selected C3.1 integration gates and classify failures; do not converge distinct path/upload cache behavior yet.
