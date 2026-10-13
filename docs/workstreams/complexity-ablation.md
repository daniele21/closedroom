# Complexity ablation — minimum complexity, equivalent product behavior

Status: PAUSED AFTER SELECTIVE REVIEW — ISOLATED EXPERIMENTS. No merge or PR to dev authorized.
Experiment branch: `experiment/complexity-ablation`
Read-only reference: `dev` at `747a0e5dad92f1f8d190cddc8fb1a1d651c0d36f` (2026-10-13). Refresh baseline identity on resume.

## Outcome, scope, axes

Reduce total owner/policy/state/dependency/build/runtime complexity **without dropping features, changing responses or data lifecycle, degrading quality, or crossing the local-first trust boundary**. Removing 100 lines by adding a second state owner is a regression.

- PRODUCT: PRODUCT_NONE for proven behavior-preserving experiments; escalate if behavior changes.
- DELIVERY: ITERATION **only on the experiment branch**. Never push to `dev`, open integration PR, merge, or promote without explicit later authorization.
- VALIDATION: selector-defined SCOPED or STRONG per isolated change; FULL for packaging/toolchain/release-impacting experiments. Overall program has shared-contract/privacy risk. A passing fake is not physical Mac/TCC/MLX evidence.
- EXECUTION: AGENT_LOCAL if available; REMOTE_AUTOMATED for deterministic gates when necessary; REAL_ENVIRONMENT for representative Mac/capture/ASR/thermal only. Never run packaged builds or upload large media artifacts through Actions.

Not in scope: redesign, framework rewrites, product renaming, removing providers/models without quality/compatibility proof, remote AI fallback, silent transfer of meeting data, replacing the existing owner boundaries.

Durable owners/invariants: `RecordingStore` facade, filesystem artifacts + SQLite catalog projection, single `HeavyWorkloadArbiter`, `RuntimeServiceManager` lifecycle, `frontend/src` as UI source, native Swift helper/JSON protocol, protected loopback auth/origin, bounded cancellable/recoverable jobs, idempotent chunks/screenshots, macOS TCC/main-thread and explicit cloud opt-in. Preserve error states, recovery, settings, UX and VoiceOver.

Reuse evidence from `architectural-consolidation.md` and `selective-efficiency.md`, not duplicate implementations. Open overlapping PRs at bootstrap: #86 DB migrations, #95 VAD evidence, #105 menu bar; avoid those files until stabilized.

## Controlled experiment loop

1. Pin `dev`, direct consumers, feature contracts and E2E oracles; preserve known baseline bugs.
2. Characterize cache/persistence/auth/retries/cancellation; separate Mac hardware from fake evidence.
3. Choose reversible owner-level ablation with guardrails; measure state/policy/LOC deltas, not file movement.
4. Change only this experiment branch; keep diff bounded, no silent cloud or privacy regressions.
5. Run focused and selector-required tests/E2E; diagnose failures without weakening tests.
6. KEEP / REWORK / REVERT / BLOCKED_FOR_EVIDENCE; no automatic merge to `dev`.

## Feature coverage and guarded surfaces

| Surface | Canonical owners | Required equivalence oracle |
| --- | --- | --- |
| Native/browser recording, permissions, recovery, menu/detection | `useRecorder`, native helper, `RecordingStore`, `menubar.py` | recording API, native lifecycle, recording UI, meeting-detection-start; real Mac separately |
| Note/screenshot/display overlay | `RecordingOverlayPage`, `RecordingStore` screenshot artifacts | call-overlay-screenshot-evidence, meeting-moments-notes + native capture recovery |
| Upload/path/multi-track transcription + diarization | transcription router, application/service, jobs | transcription application, router ablation, recording API and transcription-workflow |
| Analysis, edits, meeting/project search | analysis jobs, catalog, `MeetingDetailPage` | shared analysis pipeline, note edit revision, archive search, persistence |
| Local/opt-in providers, inference lifecycle | `RuntimeServiceManager`, AI adapters | explicit selection, model readiness, resource arbitration, bounded cleanup |
| Packaging, native app identity | `ClosedRoom.spec`, build scripts | immutable artifact smoke; source tests alone not enough |

## Candidate queue and independence

- **C1/C2 UI:** remove duplicated state/policy; preserve UX and existing overlay bug evidence.
- **C3 transcription:** keep semantically distinct path/upload caches.
- **C4 storage:** defer until SQLite migration PR #86; preserve recovery/idempotency.
- **C5/C7 native:** defer until physical Mac menubar/TCC/audio evidence.
- **C6 bundle:** defer to FULL package testing; no speculative model-dependency removal.

Disjoint writes only; `dev` read-only.

## Experiment ledger — isolated branch only

All checks below are **source/synthetic or scoped**; they do not prove representative WKWebView, native TCC/audio, Metal/MLX, package size or release readiness. Temporary PRs #119–#123 targeted the experiment branch and were closed **unmerged**; their validation workflows were deleted. No macOS app builds or GitHub media uploads.

| Slice | Source change and scope | Evidence |
| --- | --- | --- |
| C3.1 **historical dev** | PR #118 removed ASR forwarding wrappers/empty finalizers; router 759→721 before experiment isolation | prior source preflight PASS |
| C3.2 | Upload/path/stream now use one `SingleFileTranscriptionUseCase.apply_initial_diarization` policy: router 721→698, use-case 192→200 (net −15 LOC) | [38438564685](https://github.com/daniele21/closedroom/actions/runs/38438564685), 33 Python tests + lint/tsc PASS |
| C1.1 | One overlay display acknowledgement for HTTP and SSE, preserves optimistic selection and picker recovery; −12 LOC | [38439081168](https://github.com/daniele21/closedroom/actions/runs/38439081168), overlay E2E PASS |
| C1.2 / C2.1 | Derive screenshot/note saved feedback from Undo IDs (−2 overlay states); remove one unused Meeting preparation memo (−1 `useMemo`) | [38450289252](https://github.com/daniele21/closedroom/actions/runs/38450289252), overlay and preparation browser PASS |
| C1.3 / C1.4 | Derive open note from anchor (−1 overlay state); share HTTP/SSE persisted progress projection while retaining separate transport lifecycles | [38454243679](https://github.com/daniele21/closedroom/actions/runs/38454243679), lint/tsc + note re-anchor E2E PASS |
| C2.2 | One load request identity replaces 3 Meeting request/queue/generation refs; preserves stale-response rejection and queued reload | [38457647226](https://github.com/daniele21/closedroom/actions/runs/38457647226), preparation and saved-Meeting browser PASS |
| C2.3 | Two-Meeting fixture with held late success and late 503; no production edit | [38464277299](https://github.com/daniele21/closedroom/actions/runs/38464277299), both race checkpoints PASS |
| C2.4 | One internal list-loader policy for note/screenshot instances; each retains separate data/status/generation; **+12 production LOC** | [38465528741](https://github.com/daniele21/closedroom/actions/runs/38465528741), separate failure/retry recovery and overlay E2E PASS |

**Negative / deferred:** C3.3 would incorrectly collapse path ASR-only cache (diarization per call) with upload final-result cache (diarization in key); do **not** unify without differential evidence. C4 storage migrations, C5/C7 native lifecycle and C6 dependency/package dieting remain evidence-gated.

## Selective architecture review — 2026-10-13

**Decision: KEEP existing ablations on this isolated branch, with a stop on speculative cuts.** The current diff contains 5 production files, 4 test files and this workstream; no dependency/build/CI workflow change remains. All **9 source/test Git blobs exactly match** the successfully validated merge source `88c0a617909878f3235cdf0734fafba7dfb9a282` (run 38465528741). The intervening commits changed docs/temporary workflows only, so no further Actions were needed for this documentation-only review.

| Area | Decision and reason |
| --- | --- |
| C3.2 | **KEEP:** one diarization policy, cache owners stay separate |
| C1.1–C1.4 | **KEEP:** 3 overlay states and duplicated SSE/HTTP policies removed without losing observable Undo/note flows |
| C2.1–C2.3 | **KEEP:** −2 load refs, −1 unnecessary memo; delayed-result/failed-result regressions covered |
| C2.4 | **KEEP but NO GENERALIZATION:** +12 LOC buys one canonical list-loading policy with two independent state instances; diagnostics and visual frames intentionally remain separate |
| C3.3/C4–C7 | **BLOCKED / NOT PROVEN:** correctness/migration, representative native/capture or packaged performance gates |

**Measured source change vs `dev`: −24 net production LOC; overlay React `useState` declarations 34→31; Meeting load refs 3→1; one Meeting memo removed.** The C2.4 helper has fewer syntactic `useState` *call sites*, not fewer runtime React states. No performance, memory, inference-quality or release claim follows from this experiment.

**STOP / HOLD:** No speculative general-purpose hook, monolith file split or cache merge. A new ablation needs a reproduced defect or measurable improvement. Integration to `dev` requires separate user authorization, exact HEAD/base and repository-selected validation.

## Resume checkpoint

- BASE read-only `dev`: `747a0e5dad92f1f8d190cddc8fb1a1d651c0d36f`; refresh base and comparison on next run.
- TARGET: `experiment/complexity-ablation`; no changes to `dev`. Validation PRs #119–#123 closed without merge; disposable workflows removed.
- Confirmed: C3.1 merged before isolation. C3.2/C1.1/C1.2/C2.1/C1.3/C1.4/C2.2/C2.3/C2.4 KEEP on experiment branch; focused Python/frontend/browser checks PASS.
- Unresolved: full-repository exact-head integration gates if later requested, runtime performance/bundle measurements and physical Mac/WKWebView/TCC evidence; path/upload cache convergence is rejected without additional semantic/quality evidence.
- Next: HOLD after selective review; resume only with measurable or user-visible motivation or explicit integration authorization.
