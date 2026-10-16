# Complexity ablation — minimum complexity, equivalent product behavior

Status: SELECTED INTEGRATION CANDIDATE; updated-dev gates + packaged-app proof PENDING.
Experiment branch: `experiment/complexity-ablation`
Experiment baseline: `dev@747a0e5dad92f1f8d190cddc8fb1a1d651c0d36f` (2026-10-13). Integration branch `integration/complexity-ablation-selected` starts from `dev@ff65035bca385430d2e47da5f3a0b5b2a6b35c85`, preserving later Activities/backend changes.

## Outcome, scope, axes

Reduce total owner/policy/state/dependency/build/runtime complexity **without dropping features, changing responses or data lifecycle, degrading quality, or crossing the local-first trust boundary**. Removing 100 lines by adding a second state owner is a regression.

- PRODUCT: PRODUCT_NONE for proven behavior-preserving experiments; escalate if behavior changes.
- DELIVERY: experiment remains ITERATION; user-authorized selected transfer to an independent INTEGRATION branch and PR targeting `dev`, gated on exact-head/updated-base evidence. No direct `dev` mutation.
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

## Affected surfaces

Meeting/overlay/recording UI, transcription router/application and read-only RecordingStore projection. Preserve local-first, provenance, recovery and native capture/package identity; synthetic browser evidence ≠ WKWebView/TCC/MLX.

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

## Selection summary

C1/C2/C3.2 and E4/E5-read are retained; C3.3 cache conflation is rejected. Synthetic source tests do not establish physical Mac/runtime or performance evidence. The original experiment branch preserves the per-step test history.

## E4/E5 bounded follow-up — 2026-10-14

**E4.1 KEEP (PRODUCT_LOCAL / ITERATION / SCOPED / REMOTE_AUTOMATED):** Meeting screenshot selection now retains `{meetingId,id}`, not a stale object. +6 production LOC, no state count change. Browser test uses colliding screenshot IDs on two meetings and rejects leaked modal. [38546454969](https://github.com/daniele21/closedroom/actions/runs/38546454969) PASS.

**E5 KEEP only read projection (PRODUCT_NONE / ITERATION / SCOPED / REMOTE_AUTOMATED):** `RecordingStore.list_visual_evidence_frames` centralizes available/unavailable screenshot metadata and resolves assets only when available. −11 LOC, preserves provenance/order, no SQLite/manifest/write/recovery change. Two visual + four note tests and synthetic Meeting browser PASS on [38546454969](https://github.com/daniele21/closedroom/actions/runs/38546454969). SQLite PR #86 OPEN; all persistence write paths HOLD.

**E4.2 KEEP:** one recorder overlay fallback policy; recording, timing, and lease lifecycles stay distinct. Synthetic evidence: [38550028682](https://github.com/daniele21/closedroom/actions/runs/38550028682) PASS.

**E4.3 KEEP:** capture helper failure copy centralized, permissions and readiness still screen-owned. [38553150338](https://github.com/daniele21/closedroom/actions/runs/38553150338) PASS.

**E4.4 KEEP (PRODUCT_LOCAL / ITERATION / SCOPED / REMOTE_AUTOMATED):** Remove sticky `keyMomentVisualRequested` state; visual context loads on analysis tab or currently open meeting-scoped key-moment dialog. −3 LOC, **−1 React state**. [38554778757](https://github.com/daniele21/closedroom/actions/runs/38554778757) PASS: 12 source contracts, lint/tsc, synthetic browser V2 fetch only when opened + refetch on close/reopen, plus late Meeting replies and notes/screenshots retry. PR #131 closed unmerged, workflow deleted. Intentional tradeoff: repeat local fetch on reopening rather than retain idle data. No actual macOS/WKWebView/TCC or performance measurements.

**Net production LOC vs `dev`: −48** (previous −45, E4.4 −3), overlay React states −3, Meeting React states −1, Meeting load refs 3→1. All one-shot validation workflows removed; no merge into `dev`. Stop speculative ablations; broader E5 HOLD pending #86; exact-head/base gates and representative Mac proof remain before integration/release.

## Consolidated pre-integration audit — 2026-10-14

`dev` `747a0e5`: **55 changed files**. Production **−48 LOC** (10 files), tests/E2E **+869 LOC**, optional tooling **+506 LOC**. Fifteen lossless WebP images save ~51.9 MiB. Fewer owners/states do not mean fewer total lines or measured RAM/CPU. No overlapping files with open SQLite PR #86.

Selector **INTEGRATION / STRONG**: governance, source-tests, browser-e2e, **packaged-app**. [Consolidated run 38560561537](https://github.com/daniele21/closedroom/actions/runs/38560561537) PASS: governance/docs, **716/716 Python**, lint/tsc, **8/8 browser FULL_MEDIA**. Earlier [38559430185](https://github.com/daniele21/closedroom/actions/runs/38559430185) had 4 obsolete static assertions: corrected to enforce independent list generations, stale-load identity and note/visual lifetimes; no product behavior weakened. Disposable PRs #132/#133 closed unmerged; workflow deleted. Final exact-HEAD/base proof is **not** established by the temporary PR.

**Base changed:** `dev` advanced to `a30e69e` (+1 background-processing commit). Candidate is behind by 1. Both touch `MeetingDetailPage.tsx` and `design/ux-contract.json`; no same-line hunks detected, but semantic reconciliation and new-base gates remain PENDING. Source PASS applies to old `dev` `747a0e5` only.

**PENDING:** local finalized macOS .app/FTS5 lifecycle gate; representative WKWebView/TCC/audio/MLX remain release evidence. Selected integration now carries (1) frontend state/policy ablations with browser oracles and (2) backend ASR/diarization/read-only visual projection, ported onto the newer `dev` base using uniquely matching source hunks; (3) documentation media conversion, README references and optional footprint-audit tooling deliberately remain isolated. Exact-head source and Mac package evidence still PENDING; no merge into `dev` yet.

## Integration candidate checkpoint — 2026-10-16

- Candidate `integration/complexity-ablation-selected` is based on `dev@ff65035bca385430d2e47da5f3a0b5b2a6b35c85`. It ports the C1/C2/C3.2/E4/E5 read-only behavior-preserving source slices and their focused source/browser tests; latest `dev` Activities and job/capture changes remain authoritative.
- Four overlapping owners (`useRecorder`, `MeetingDetailPage`, `RecordingStore` read projection, transcriptions router) were reconciled by context-matched hunks instead of wholesale replacement. Three-way matching alone is not proof of semantics: run selector-defined integration tests and affected browser E2E against exact head/base.
- Documentation image conversion (15 PNG→WebP files), README references and footprint audit/optimization tools are **not** part of this integration; evaluate separately. No binary media or artifact build is authorized in GitHub Actions.
- Validation at this checkpoint is PENDING. Required source/E2E and local packaged-app/smoke are independent; target-Mac real WKWebView/TCC/MLX remains deferred to RELEASE. No claim of performance improvement without measurements.
