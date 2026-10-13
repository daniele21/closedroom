# Complexity ablation — minimum complexity, equivalent product behavior

Status: ACTIVE — ISOLATED EXPERIMENTS. No merge or PR to dev authorized.
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

1. **Pin baseline** from `dev`: exact commit/tree, dependencies, supported feature register `docs/features.md`, affected consumers and `.engineering/e2e.json` journeys. Treat known menu-bar/meeting-detection bugs as baseline bugs, not removable features.
2. **Characterize** identical input/output, provider selection, cache keys, persisted JSON/SQLite, partial failure/retry/cancellation and API auth/origin. Preserve original fixtures. Capture representative hardware metrics separately from deterministic fakes.
3. **Select one falsifiable ablation:** owner, removed mechanism, primary metric, secondary guardrails, expected impact, rollback, selected risks/gates and direct tests. No speculative abstraction or persistent feature flag.
4. **Apply on this branch only** with reviewable small commits; measure before/after: production LOC, *number of duplicated policy owners*, state variables/transitions, interfaces/dependency cycles; as relevant bundle bytes, launch latency, RSS/CPU/thermal and cleanup. Do not treat file relocation as reduction.
5. **Validate** owner tests first, differential E2E and selected gates on exact candidate; FULL_MEDIA for materially changed UI timing/flows, physical Mac/quality only where applicable. Failures get diagnosis, not weakened tests.
6. **Decide** KEEP / REWORK / REVERT / BLOCKED_FOR_EVIDENCE. KEEP requires proven behavioral equivalence, meaningful complexity reduction and no adverse guardrail. Unknown cannot be marked PASS.
7. **Stop** when remaining candidates lack proof, have marginal benefit or change user contracts. Record negative results. Do not integrate changes merely to finish the workstream.

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

- **C3 transcription (FIRST):** router adapter vs single-file use case. Do not collapse upload/path cache identities without differential evidence.
- **C1/C2 UI (NEXT):** `RecordingOverlayPage` ~1,236 lines/34 hooks and `MeetingDetailPage` ~2,188 lines/33 hooks. Reduction should eliminate duplicated state/effects, not merely split files; avoid concurrent shared UI writes and current physical overlay bugs.
- **C4 persistence (LATER):** `recordings.py` ~2,250 lines. Keep public facade, artifact recovery/idempotency and avoid SQLite migration PR #86 overlap.
- **C5 shell / C7 native (BLOCKED):** `menubar.py` ~1,360 lines, `native_capture.py` ~1,168 lines. Stabilize real Mac detection/menu and protocol/TCC evidence before ablation.
- **C6 packaged dependency diet (EVIDENCE-GATED):** use selective-efficiency SE-3/4/5/6; never drop ONNX/Silero/PyTorch-related paths on bundle size alone. Requires FULL packaged proof where relevant.

Independent owners can be inspected in parallel; exclusive write boundaries for edits. Evaluate cumulative complexity **on this branch**; `dev` is never automatically synchronized with experiments.

## Experiment ledger

### C3.1 — forwarding wrappers / empty finalizers (historical baseline only)

PR #118 previously integrated into `dev` at `747a0e5`. Router 759 -> 721 lines, four trivial forwarding wrappers and three empty finalizers removed. Source preflight INTEGRATION/SCOPED + repository health PASS. This is prior history, **not authorization to merge further experiments into dev**. No physical Mac claim.

### C3.2 — canonical initial diarization policy (KEEP, SCOPED SOURCE PASS)

Hypothesis: router `_apply_initial_diarization` duplicates `SingleFileTranscriptionUseCase._apply_diarization`, including disabled/completed/provider switching semantics.

One canonical `SingleFileTranscriptionUseCase.apply_initial_diarization` now serves upload, streaming and path, preserving provider options and endpoints.

**Result:** router 721 → 698; application 192 → 200; net −15 production lines/one policy. Tests 5+3+25 PASS (**38438564685**), not representative ASR/package proof.

**C3.3 rejected/deferred:** path uses ASR-only cache and re-applies diarization per request; upload uses final-result cache identity including diarization. Unifying them wholesale risks stale/wrong speaker results and altered persistence. Keep distinct until dedicated differential evidence supports a minimal unification.

### C1.1 — overlay monitor policy and recovery (KEEP, SCOPED BROWSER PASS)

`RecordingOverlayPage.tsx` 1,236 -> 1,224 lines (−12); preserve all 20 `useState` declarations, eight effects, one SSE channel and all note/screenshot/Stop handlers. A single `reconcileBackendDisplaySelection` callback now mediates *both* the SSE event and the HTTP active-status snapshot, without allowing stale acknowledgements to overwrite an optimistic monitor selection. Also removed unused `loadDisplays(_autoSelectSingle)` parameter and deduplicated picker-recovery actions for two distinct backend error codes while preserving their distinct user-facing messages.

Source proof: same SSE and hooks, unchanged note/undo handlers. Lint/tsc PASS (**38438564685**); browser overlay PASS (**38439081168**). Physical Mac proof separate.

### Validation snapshot — 2026-10-13

Static comparison to `dev` `747a0e5`: 13 checks PASS, including 16 unchanged transcription routes, ASR cache adapter, identical initial diarization body and note/undo handlers. C3.2+C1.1 net −27 lines; no performance claim.

**Validation evidence:** temporary PR [#119](https://github.com/daniele21/closedroom/pull/119) targeting the experiment branch was **closed unmerged**. Run **38438564685** passed 33 Python tests plus frontend lint/tsc; browser run hit environment-only `spawn ffmpeg ENOENT` when assembling video after its checkpoints. Run **38439081168** installed the missing `ffmpeg` and passed the complete `call-overlay-screenshot-evidence` browser journey, including MP4 assembly; neither run uploaded artifacts. Workflow `.github/workflows/ablation-one-shot.yml` was deleted afterward. The application source was unchanged across validation runs; remaining commits affect only experimental documentation/validation workflow. These scoped results do not qualify packaged macOS app, native TCC/audio, or model quality.

**Baseline fact:** path HTTP projection reconstructs ASR stats before initial diarization. A cached ASR payload's diarization status is not itself authoritative for the path adapter. Tests now pin this existing behavior; do not inadvertently collapse path's ASR-stage cache into upload's final-result cache.

### C1.2 + C2.1 — state-owner/selector ablation (KEEP, scoped browser PASS)

- C1.2: overlay feedback now derives from persisted `lastSavedScreenshotId` / `lastSavedNoteId`, shared with Undo. Removes **2 React states and six setter calls**, preserves both 4.5-second timers. Overlay now **1,216 lines vs 1,236** at baseline; React states **34 → 32**.
- C2.1: `latestPreparation` uses `find` rather than allocating/memoizing a `preparationJobs` array only for `[0]`. Meeting page **2,184 vs 2,188 lines**, `useMemo` **7 → 6**; first-match semantics preserved.
- Evidence: temporary branch-only PR #119, run [38450289252](https://github.com/daniele21/closedroom/actions/runs/38450289252) **PASS**: lint, TypeScript, overlay screenshot/note E2E (new checks `Saved` agrees with Undo), meeting-preparation recovery E2E. PR **closed unmerged**, temporary workflow **deleted**. Browser fixture is synthetic; no packaged Mac/TCC/MLX claim.
- Cumulative C3.2 + C1.1 + C1.2 + C2.1: **−39 production lines**; 2 fewer policy duplications, 2 fewer UI state owners, 1 fewer memoized intermediate list. Not a measured RAM/CPU benefit.

## Resume checkpoint

- BASE read-only `dev`: `747a0e5dad92f1f8d190cddc8fb1a1d651c0d36f`; refresh base and comparison on next run.
- TARGET: `experiment/complexity-ablation`; no changes to `dev`. Verification-only PR #119 was closed without merge and its temporary workflow removed.
- Confirmed: C3.1 merged before isolation. C3.2/C1.1/C1.2/C2.1 KEEP on experiment branch; 33 Python tests, lint/tsc and both UI journeys PASS.
- Unresolved: full-repository exact-head integration gates if later requested, runtime performance/bundle measurements and physical Mac/WKWebView/TCC evidence; path/upload cache convergence is rejected without additional semantic/quality evidence.
- Next: characterize further owner/state duplications before code changes; all subsequent ablations remain isolated until explicitly authorized.
