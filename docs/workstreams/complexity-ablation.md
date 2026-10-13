# Complexity ablation — behavior-preserving reduction

Status: ACTIVE — METHOD / BASELINE DESIGN (no runtime ablations applied)
Target: `dev`; work branch: `work/complexity-ablation`
Source identity at plan bootstrap: `dev` `15ec412ce10cb5e49438f6e09271f2883ea65973` (2026-10-13)
Read with: root/scoped AGENTS, `.engineering/baseline.json`, `.engineering/commands.json`, `.engineering/e2e.json`, `skills/structured-change/SKILL.md`, `skills/validate-change/SKILL.md`.

## Desired outcome and non-goals

Reduce the minimum necessary complexity of ClosedRoom **without reducing supported features, changing the default user journey, modifying public/serialization contracts, or moving private data off-device**. Optimize for total ownership, states, dependencies, build/runtime resources and maintenance cost, not line count alone.

Non-goals: new features or UX redesign; unverified model/provider elimination; wholesale framework rewrite; externalizing inference/recordings/telemetry; package or product renaming; silently changing support for browser fallback, cloud providers explicitly selected by users, or macOS packaging.

This is distinct from `architectural-consolidation` (canonical owner boundaries) and `selective-efficiency` (measured runtime/bundle improvements): consume their evidence and avoid duplicate implementations or overlapping PRs.

## Axes and boundaries

- PRODUCT: **PRODUCT_NONE** per behavior-preserving experiment. Reclassify to PRODUCT_LOCAL/FEATURE if observable semantics actually change and stop treating that experiment as pure ablation.
- DELIVERY: **ITERATION** per experiment; **INTEGRATION** PR -> `dev` only after exact-head/base proof. This plan alone is documentation.
- VALIDATION: **STRONG** for the overall cross-boundary effort; selector chooses concrete gates per experiment (SCOPED/STRONG; FULL when packaging/toolchain or release rules require). A pure planning edit is LEAN.
- EXECUTION: **AGENT_LOCAL** where equivalent tests can run; **REMOTE_AUTOMATED** for deterministic macOS/source/browser/build gates unavailable locally; **REAL_ENVIRONMENT** for physical TCC, audio, MLX/Metal/thermal and interactive macOS truth. Do not run packaged builds in GitHub Actions.
- Preserve `RecordingStore` as aggregate facade, SQLite catalog projection, `HeavyWorkloadArbiter` as sole heavy-work scheduler, `RuntimeServiceManager` as local LLM lifecycle owner, `frontend/src` as UI source, and native process/JSON interface.
- Preserve loopback auth/origin, no implicit cloud fallback, one owner per artifact/job/recording, bounded cancellation and cleanup, monotonic/idempotent chunk and screenshot contracts, finalized-artifact immutability, accessible keyboard/focus/VoiceOver paths, and Cocoa main-thread requirements.

## Experimental method

### AB-0: lock baseline and trace product coverage — READY

1. Pin `dev` commit + tree, target/base, environment, dependencies and artifact identity; refresh before each candidate, never measure a moving baseline.
2. Map current feature registry (`docs/features.md`) and `.engineering/e2e.json` to owners, API consumers, persisted artifacts, user flows and failure/recovery states. Include recording (native/browser), native permissions, optional screen context, manual screenshots, timestamped notes, overlay, meeting detection/menu bar, transcription/diarization, analysis/structured edits, archive/project memory, jobs/SSE, explicit optional providers, settings and packaged app lifecycle.
3. Record *known baseline bugs* separately (e.g. menu bar visibility/detection on target Mac) and the open PRs touching those owners. A baseline bug cannot be interpreted as permission to delete a feature; bug fixing needs a separate lane.
4. Capture contract fixtures: HTTP requests/responses/errors and auth/origin, persisted file/SQLite fixtures (old + fresh + interrupted), state transitions including cancellation/restart/fallback, representative UI journeys, supported model/provider options. Normalize nondeterministic IDs/timestamps only when equivalence permits; do not snapshot private audio/transcripts into telemetry.
5. Record performance baselines on fixed hardware/scenarios when applicable: app/DMG and dependency closure bytes, launch time, idle/recording/AI RSS, cancellation/cleanup time, latency and resource peak. Separate deterministic CI fixtures from representative Mac/ASR quality. Capture source/config/environment identity, sample count and noise bands.

**Gate:** no destructive experiment until the affected current behavior is mapped and a regression oracle exists. Baseline status: PENDING measurement/evidence; documentation and existing tests are not proof of runtime equivalence.

### AB-1: inventory candidates and value — READY

For each candidate produce one experiment card:
`ID | owner and direct consumers | current mechanism | hypothesized redundant mechanism | smallest reversible change | protected behavior | complexity metric | required gate | risk/blocked-by | evidence | decision`.

Metrics are **a vector** (not a vanity LOC score):
- Structural: reachable production SLOC, live modules, public interfaces, responsibilities/owner, duplicated policies, state variables/transitions, fan-in/fan-out, cyclic dependencies.
- Packaging: direct/transitive dependencies actually bundled, bundle bytes, build time, boot/import cost.
- Runtime: cold/warm start, idle/recording/ASR/LLM peak RSS/CPU, latency, thermal and I/O only where the lane touches them.
- Reliability: lifecycle/cancel/restart paths, test pass and behavioral coverage, output compatibility.
- Maintenance: deletion of a policy/owner/branch preferred over merely moving its lines into a new abstraction.

Give each metric a baseline and an expected direction. Choose a primary metric before implementation, add secondary guardrails and record negative results. Do **not** optimize a single total score by trading away protected behavior.

### AB-2: one controlled ablation at a time — READY after AB-0/1

1. State falsifiable hypothesis: e.g. "this policy branch duplicates canonical owner X and can be removed, preserving contract Y".
2. Start a short-lived branch from *refreshed* `dev`; keep the patch isolated and reversible. No permanent feature flags, duplicated owners or speculative scaffolding.
3. First build a differential or characterization test for the changed seam using identical fixed inputs; then remove/converge **one** policy/branch/adapter/dependency.
4. Run focused tests, compare API/UI/persistence/error semantics, then repository-selected gates. Expand to affected automated E2E, and FULL_MEDIA for material UI sequence/timing. Do not treat deterministic fake evidence as physical macOS/audio/model proof.
5. For AI output, assert preserved model/provider configuration, prompts, inputs, persistence and quality thresholds; do not require byte-equal stochastic generation. If model/quality itself could change, stop and obtain representative quality evidence.
6. Benchmark before/after with same source scenario, model/cache/hardware/settings, repeat enough to distinguish noise. Reject a regression outside recorded uncertainty or stated product limits; unknown = NOT PROVEN.
7. Decide **KEEP**, **REWORK**, **REVERT**, or **BLOCKED_FOR_EVIDENCE**. KEEP requires equivalence + meaningful reduction in at least one complexity dimension + no material adverse tradeoff. "Tests passed" without improvement is not sufficient.
8. Before PR/integration inspect the complete diff, target/base and evidence identity; use existing selector/preflight, avoid GitHub Actions builds/artifact uploads and redundant reruns. Rebase other lanes on new `dev` promptly.

### AB-3: convergence and stopping rule — READY after first KEEP

- Integrate independent, proven small changes; do not accumulate a large rewrite branch. Update canonical feature/architecture/current-state docs only when their truth is affected.
- Maintain an **ablation ledger**: baseline, hypothesis, one changed mechanism, selected risks/gates, result vector, failure classification, retained/rejected decision and exact source/evidence reference.
- Stop when remaining candidates are unproven, have small marginal benefit, increase conceptual ownership, or require a behavior contract change. Preserve failed/reverted experiments as decision evidence, not dead code.
- Reconfirm target-Mac obligations at RELEASE for changes affecting physical capabilities. `dev` merge or passing source tests does not prove stable-source release readiness.

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

## First executable slice and acceptance

**Slice 0 (no behavior change):**
- Produce the feature-to-contract matrix and a reproducible complexity measurement/scoreboard referencing a pinned `dev` baseline.
- Link existing tests and E2E owners rather than duplicating suites.
- Mark coverage gaps and unavailable host/target-Mac measurements truthfully.
- Identify one C3 or C1 small reversible hypothesis with direct consumers, before/after metric, differential test and selected gates; prefer C3 if UI/overlay target-Mac bugs are still active.
- Capture a checkpoint with exact refreshed source/tree/base, what was measured, unresolved gaps and one next falsification action.

**Success:** a replicable experiment methodology and at least one future independently verifiable ablation candidate, not a numerical lines-deleted target. No runtime code has been changed by creating this plan.

## Resume checkpoint

- Baseline branch/head observed: `dev` @ `15ec412ce10cb5e49438f6e09271f2883ea65973`; MUST refresh on resume.
- Existing workstreams: `docs/workstreams/architectural-consolidation.md`, `docs/workstreams/selective-efficiency.md`.
- Open overlapping PRs at inspection: #105 (menu bar), #95 (VAD benchmark), #86 (SQLite migrations).
- Structural observations: C1–C7 sizes measured by fetching files on `dev`, not by local AST/test execution.
- Deterministic/physical equivalence: NOT YET VERIFIED; no app build, runtime benchmark or actual source ablation performed here.
- Next discriminating action: pin refreshed head + establish C3 upload/path/recording route-contract baseline and direct tests, while separately auditing UI C1 state dependencies; choose first ablation only after coverage is sufficient.
