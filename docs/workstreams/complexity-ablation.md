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

## Experiment ledger

### C3.1 — forwarding wrappers / empty finalizers (historical baseline only)

Historical PR #118 merged to `dev` at `747a0e5`: router 759 → 721, forwarding wrappers and empty finalizers removed, source gates PASS; further merges not authorized.

### C3.2 — canonical initial diarization policy (KEEP, SCOPED SOURCE PASS)

Hypothesis: router `_apply_initial_diarization` duplicates `SingleFileTranscriptionUseCase._apply_diarization`, including disabled/completed/provider switching semantics.

One canonical `SingleFileTranscriptionUseCase.apply_initial_diarization` now serves upload, streaming and path, preserving provider options and endpoints.

**Result:** router 721 → 698; application 192 → 200; net −15 production lines/one policy. Tests 5+3+25 PASS (**38438564685**), not representative ASR/package proof.

**C3.3 rejected/deferred:** path uses ASR-only cache and re-applies diarization per request; upload uses final-result cache identity including diarization. Unifying them wholesale risks stale/wrong speaker results and altered persistence. Keep distinct until dedicated differential evidence supports a minimal unification.

### C1.1 — overlay monitor acknowledgement (KEEP, browser PASS)

`RecordingOverlayPage.tsx` 1,236 → 1,224 (−12). One `reconcileBackendDisplaySelection` replaces SSE/HTTP duplicated acknowledgement; preserves optimistic in-flight selection. Removed unused `loadDisplays` argument and duplicate picker recovery, retaining distinct error messages. Lint/tsc PASS (**38438564685**), synthetic overlay E2E PASS (**38439081168**). No target-Mac proof.

### Evidence snapshot (2026-10-13)

Comparison against `dev` `747a0e5`: 13 static guards PASS, including unchanged 16 transcription routes, distinct ASR path cache and canonical diarization policy. Temporary validation PR #119 closed unmerged. **38438564685**: 33 Python tests + frontend lint/tsc PASS; video-stage ffmpeg missing (environment). **38439081168**: browser overlay PASS after installing ffmpeg. No artifacts uploaded, workflow removed.

**Cache constraint:** path rebuilds stats before diarization from ASR cache; upload caches final diarization-aware results. Do not unify cache keys without new semantic evidence.

### C1.2 + C2.1 — state-owner/selector ablation (KEEP, scoped browser PASS)

- C1.2: overlay feedback now derives from persisted `lastSavedScreenshotId` / `lastSavedNoteId`, shared with Undo. Removes **2 React states and six setter calls**, preserves both 4.5-second timers. Overlay now **1,216 lines vs 1,236** at baseline; React states **34 → 32**.
- C2.1: `latestPreparation` uses `find` rather than allocating/memoizing a `preparationJobs` array only for `[0]`. Meeting page **2,184 vs 2,188 lines**, `useMemo` **7 → 6**; first-match semantics preserved.
- [38450289252](https://github.com/daniele21/closedroom/actions/runs/38450289252): lint/tsc, overlay Undo and Meeting-preparation E2Es PASS. PR #119 closed unmerged; workflow deleted. Browser simulated.
- Subtotal through C2.1: −39 production lines; no measured RAM/CPU effect.

### C1.3 + C1.4 — canonical note visibility / backend progress (KEEP, browser PASS)

- **C1.3:** removed independent `noteComposerOpen` state; derive it from `noteAnchor !== null`. All original open, close and stop paths set both together. Preserve focus, note timestamp, resize, Escape/Close/Cancel and Save.
- **C1.4:** HTTP status and SSE now use one `applyBackendProgress` for recording-active, bytes, warnings, screenshot/note counts and acknowledged monitor. Its type derives from `ApiClient.getActiveRecording`. SSE signal meters and HTTP title/backend/timer remain source-specific.
- Overlay 1,216 → 1,217 lines this wave (+1), but one fewer state and duplicated policy; vs `dev` 1,236 → 1,217, states 34 → 31. No performance proof.
- [38454243679](https://github.com/daniele21/closedroom/actions/runs/38454243679): lint/tsc, screenshot and note open/close/re-anchor E2E PASS. PR #120 closed unmerged, workflow removed; no real-Mac proof.

### C2.2 — one Meeting request token (KEEP, scoped browser PASS)

Three independent load refs (`loadGenerationRef`, `loadQueuedRef`, `loadInFlightRef`) → one request token containing key, queued flag and promise. Identity rejects stale completions, same-key calls queue one refresh, cleanup invalidates prior requests. Nine effects and `useMeetingJobEvents` unchanged. Meeting page 2,188 → 2,186 lines (+2 since C2.1), but −2 refs.

[Run 38457647226](https://github.com/daniele21/closedroom/actions/runs/38457647226): lint, tsc, `meeting-preparation` reconnect/recovery and `saved-meeting-fast-open` browser E2Es **PASS**. [PR #121](https://github.com/daniele21/closedroom/pull/121) closed unmerged; workflow removed. Synthetic browser does not prove all cross-meeting races or real WKWebView/TCC.

Cumulative experiment: **−36 production lines**, −3 overlay states, −2 Meeting load refs, −1 Meeting memoization. No RAM/CPU measurement.

### C2.3 — rapid Meeting switching / out-of-order responses (KEEP, browser PASS)

Added two-Meeting synthetic HTTP race cases to `scripts/browser_saved_meeting_e2e.mjs`. While A's GET is held, navigate to B, observe B's replacement GET, then release A's late success: B's title/transcript remain correct. Reverse the route and release a stale **503 error**: current Meeting remains intact, no old error leaks. Checkpoints `07-late-success-ignored`, `08-late-error-ignored`. C2.2's existing request identity passed, **no new production edit**.

[38464277299](https://github.com/daniele21/closedroom/actions/runs/38464277299) PASS: browser script syntax, lint, TypeScript, both Meeting race checkpoints and preparation reconnect/recovery. PR #122 closed unmerged; temporary workflow removed, no app build/media upload. Simulated browser does not prove WKWebView/TCC/physical audio.

### C2.4 — shared screenshot/note list policy (KEEP, scoped browser PASS)

`useMeetingItemList<T>` replaces two duplicated list loaders; screenshot and note data/status/generations/retry/reset remain independent. Diagnostics and visual frames stay separate. Source delta **+12 production lines** this wave; cumulative **−24** vs `dev`, one fewer duplicated loading policy. No RAM/CPU/latency measurements.

[38465528741](https://github.com/daniele21/closedroom/actions/runs/38465528741) **PASS**: lint/tsc, `saved-meeting-fast-open` with `09-independent-list-recovery` (dual failure → screenshot retry preserves note error → notes retry), and overlay screenshot/note E2E. Synthetic browser; no .app, TCC or physical audio proof. PR #123 closed unmerged; one-shot workflow removed.

## Resume checkpoint

- BASE read-only `dev`: `747a0e5dad92f1f8d190cddc8fb1a1d651c0d36f`; refresh base and comparison on next run.
- TARGET: `experiment/complexity-ablation`; no changes to `dev`. Validation PRs #119–#123 closed without merge; disposable workflows removed.
- Confirmed: C3.1 merged before isolation. C3.2/C1.1/C1.2/C2.1/C1.3/C1.4/C2.2/C2.3/C2.4 KEEP on experiment branch; focused Python/frontend/browser checks PASS.
- Unresolved: full-repository exact-head integration gates if later requested, runtime performance/bundle measurements and physical Mac/WKWebView/TCC evidence; path/upload cache convergence is rejected without additional semantic/quality evidence.
- Next: characterize further owner/state duplications before code changes; all subsequent ablations remain isolated until explicitly authorized.
