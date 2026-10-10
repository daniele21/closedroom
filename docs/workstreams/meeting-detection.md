# Meeting Detection — one-click suggested recording

Status: ACTIVE — source candidate integrated on `feat/meeting-detection-integration`; deterministic and target-Mac evidence pending
Target: `dev`; implementation candidate `feat/meeting-detection-integration`; planning baseline `plan/meeting-detection`
Baseline inspected: `dev@53662a1744632abf37d127cf253c1d70a667585d` on 2026-10-10. Refresh before implementation.

## Outcome and product shape

**User/job:** a person joining a call wants a discreet recording suggestion.
**Outcome:** after explicit opt-in, the macOS menu-bar companion recognizes plausible active input use by a *supported* call app and offers a generic actionable macOS notification. **Record** requests the *existing* capture path; preparing is distinguished from actual recording, and the native overlay appears only on capture `ready`. **Not now** suppresses this call.
**Non-goals v0:** calendar, browser-tab/meeting-title/participant extraction, automatic start/stop, audio listening/classification, screen-content capture, remote processing, a second recording service/queue. Browser microphone activity alone is not proof of Google Meet.
**Defaults:** detection OFF; request notification authorization after opting in; recording `both` (mic + computer) as today; optional screen-context capture OFF; do not silently downgrade capture sources.
**Product risks:** VALUE (opt-in conversion); USABILITY (annoyance/focus); FEASIBILITY (CoreAudio, background notification/start); VIABILITY (resource use/OS coverage). If unsupported, NARROW_SCOPE, CHOOSE_ALTERNATIVE or DO_NOT_BUILD.
**Evidence:** local content-free conversion/false-positive observations; SHIPPED is not product success.

## Canonical ownership and invariants

- Native shell: `src/local_asr_server/menubar.py`; main-thread Cocoa/window and native overlay: `window.py`; settings persisted by `settings.py` and exposed by existing Settings page/routes.
- `NewRecordingPage.tsx` -> `useRecorder.ts` owns start via existing reservation/API/`NativeCaptureManager`/`RecordingStore`; `HeavyWorkloadArbiter` owns heavy work. `menubar.py` calls `RecordingController.start()`: **verify delivery/ack on all routes and hidden windows**.
- Add only shell-local suggestion state; canonical recording states remain with existing owner. No second capture, meeting store or scheduler.
- Local-only; no audio buffers/content detection/remote calls/sensitive logs. Only volatile session tokens and bounded diagnostic reasons. Opt-in, notification and capture/TCC grants are distinct.
- No focus theft; `Preparing` cancellable, actual `ready` gates REC/timer/overlay; preserve manual/browser recording, note, screenshot, Stop and recovery.
- Capability `supported|unsupported|unknown` must distinguish inability to inspect CoreAudio from an inactive call. If notifications are unavailable, preserve menu-bar and manual access.

## UX contract and edge states

`opted_out -> observing -> candidate -> suggestion -> {record|not_now|dismiss|expired} -> {preparing -> ready/recording | blocked | failed | cancelled} -> ended`.

1. Stable mic-input use in a supported app (initial experiment: 3–5 s) -> generic "Possible meeting in progress" notification; app name only if confidently known; browser mic activity alone is insufficient.
2. **Record** is one idempotent start intent; **Not now**/dismiss suppress this call, body-click opens ClosedRoom but never starts; expired notification action fails closed.
3. **Preparing** stays in a small cancellable non-REC surface without stealing call focus. Once canonical native capture reports `ready`, display REC/timer/audio health/Note/Screenshot/Stop. Permission/storage/device failures open targeted recovery, not an implicit mic-only fallback.
4. No second prompt for the same call after ignore, dismiss or manual Stop, even across brief mute/reconnect/helper PID changes. Loss of detection never auto-stops recording; notification denial retains menu-bar access.
5. Foreground ClosedRoom uses contextual in-app presentation; keyboard, VoiceOver, status feedback and reduced-motion are mandatory.

**Transient internal contracts to freeze in MD-0** (no persisted/public detection API):
- `ActivityObservation{bundle_id,pid?,monotonic_time,input_active,capability,reason}`.
- `MeetingCandidate{ephemeral_id,source_kind,label?,created_monotonic,expires_monotonic}` with call epoch distinct from PID.
- `SuggestionDecision{notify|suppress|close,reason,candidate_id?}` covers opt-out/ambiguity/active/pending/prior dismissal/expiry/denied notification.
- `NotificationAction{candidate_id,record|ignore|body_open}` processed once, with epoch + canonical active-state revalidation.
- `StartAcknowledgement{accepted|already_active|preparing|blocked|failed|cancelled|recording_ready}` tied to existing capture reservation/session; JS dispatch alone is **not** acknowledgement.

Experimental tuning, not product SLO: event-driven or ~1 Hz sample, 3–5 s activation debounce, 20–30 s inactivity hysteresis, bounded expiry and one prompt/session; calibrate on Mac.

## Dependency graph and parallel execution

```
MD-0  Boundary/feasibility decision   [serial]
  ├── MD-1  Native CoreAudio + policy  [Lane A]
  ├── MD-2  Actionable notification    [Lane B]   FOUR PARALLEL LANES
  ├── MD-3  Canonical recording start  [Lane C]
  └── MD-4  Opt-in + settings UI       [Lane D]
               ↓ merge early into refreshed dev, independent owners
MD-5  Shell/menu bar/overlay integration [single integration owner]
               ↓
MD-6  E2E, physical Mac, UX docs, rollout
```

**MD-0 — ACTIVE (source contract selected; physical feasibility not proven).** Inspect `dev`, root/scoped guides, directly impacted consumers/tests and current PRs; in particular open PR #105 (macOS 26 menu bar and Settings) and `architectural-consolidation` AC-1 edits to `useRecorder`. Validate CoreAudio `kAudioHardwarePropertyProcessObjectList`/`kAudioProcessPropertyIsRunningInput` compatibility on candidate macOS and app IDs, per-process access constraints, and actionable UNUserNotificationCenter delivery in packaged app (feasibility probe, not product claims). Choose minimal reliable **shared** start owner/ack from any WKWebView route with hidden window. Freeze input/action/start interface, supported-app matrix and no-focus contract; if any assumption fails, explicitly narrow scope before W1.

**W1 parallel lanes** (separate short-lived worktrees from refreshed `dev`; no shared-file simultaneous edits; experimental paths remain unused/disabled until integration):

| ID / lane | State | Exclusive write boundary | Observable deliverable / test |
| --- | --- | --- | --- |
| MD-1 / A | ACTIVE | New `src/local_asr_server/meeting_detection*.py` and new focused tests; isolated CoreAudio bridge only if feasibility requires it | Input activity/capability + pure deduplicating suggestion policy; start/end hysteresis, unsupported app, false positive, PID change, concurrent sources, session expiration, thread cleanup. Never write `menubar.py`/settings/recorder. |
| MD-2 / B | ACTIVE | New `macos_meeting_notifications.py` adapter and tests | UNUserNotificationCenter categories, Record/Not now/body/dismiss semantics, action IDs, callback completion, stale/duplicate handling, opt-in permission, no personal text; mockable native boundary. No `menubar.py` edits. |
| MD-3 / C | ACTIVE | `frontend/src/hooks/useRecorder.ts`, directly consumed recording controller/bridge or service/API contract, focused tests | Exactly one start owner shared by manual/menu-bar/notification, acknowledged despite hidden or non-recording route, atomic reservation, wait-for-AI cancel, correct error/ready, no duplicate session; browser/manual flow unchanged. Coordinate exclusive `useRecorder` ownership with AC-1. |
| MD-4 / D | ACTIVE | `settings.py`, Settings router/schema, `frontend/src/pages/SettingsPage.tsx`, related i18n/UI tests | `meeting_detection_enabled=false` default; user-readable privacy/capability and opt-in UI, clear status and diagnostics; permission request only after opt-in, opt-out persists; no modal/onboarding blocking recording. No `menubar.py` edits. |

W1 branches: `feat/meeting-detection-core`, `feat/meeting-detection-notifications`, `feat/meeting-detection-start`, `feat/meeting-detection-preferences`. Run owner-local gates, merge small disabled-by-default PRs into refreshed `dev`, avoid stacked long-lived changes and resolve PR #105 conflicts.

**MD-5 — ACTIVE (source integrated; unverified); single integration owner.** Wire only this lane into `menubar.py` and `window.py` (and necessary app lifecycle/packaging), start/stop detector, keep delegate retained and Cocoa calls on main thread, ensure one monitor per process and bounded shutdown, expose contextual menu-bar action, actionable-notification start and fallback when notifications denied, foreground preservation, truthful preparing/ready/recovery and native overlay after real capture. Coordinate PR #105 changes; no competing edits to these files.

**MD-6 — BLOCKED on validation of MD-5.** Add affected FULL_MEDIA browser journey (synthetic detector/notification fixtures), focused integration tests and physical Mac matrix; update `design/ux-contract.json`, `docs/features.md`, `docs/current-state.md`, architecture docs only if ownership changed. Decide whether native-app v0 is useful enough to enable as an opt-in setting; no promises for browser Meet without evidence.

## Acceptance and validation checklist

**Deterministic matrix:** supported/ambiguous/unsupported app; activation/mute/rejoin/end/PID changes; opt-out/deny/stale action/double-Record; active or AI-busy recording reservation; hidden window/non-recording route; permission/storage/device failures and cancellation cleanup; true capture-ready timing; preserved manual/browser fallback, Stop->saved Meeting, notes and screenshots; no sensitive logging/network or monitor leaks. Extend relevant `test/test_recording_api.py`, `test/test_native_capture.py`, `test/test_macos_hotkeys.py`, frontend recorder/overlay tests and new dedicated detector/notification tests. Require behavioral assertions.

**Browser FULL_MEDIA:** opt-in -> fixture suggestion -> Record -> preparing -> simulated native-ready -> overlay -> Stop; also ignore, retry/blocked permission and stale action. Browser fixtures **do not prove** macOS CoreAudio/notification delivery.

**Mac REAL_ENVIRONMENT:** packaged app on supported OS with real Teams/Zoom mic tests, browser false positives, notification when hidden/other Space/fullscreen, Record/Not now/expired callback, TCC-backed nonempty mic+system tracks, true timer/overlay, notification denial and macOS 26 menu-bar allowance, idle CPU/RSS/wakeups, exit cleanup and VoiceOver/usability. Keep source/build/OS identity, no call content.

**Axes:** PRODUCT_FEATURE; DELIVERY=ITERATION per lane, INTEGRATION into `dev`, RELEASE only `dev -> main`; VALIDATION=SCOPED pure core/Settings, STRONG shared native/start integration, FULL if selector/release requires; EXECUTION=AGENT_LOCAL for available deterministic gates, REMOTE_AUTOMATED if unavailable, REAL_ENVIRONMENT for physical Mac/TCC. Select gates with `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration`; affected UI requires FULL_MEDIA. Minimize Actions through local owner tests and exact-head/tree-equivalent evidence reuse; never downgrade or substitute simulation for device evidence.

**Done:** opt-in suggestion from supported call app, one-click confirmed background start, no repeated prompts/implicit cloud/auto-capture, true ready/REC, user-visible recoverable errors, manual and overlay regressions green, matching docs. Not release-ready until RELEASE/FULL + applicable real-Mac proof.

**Resume checkpoint:** source candidate implemented on integration branch but not validated; baseline `dev@53662a1744632abf37d127cf253c1d70a667585d` is context, not gate evidence; CoreAudio and notification Mac feasibility unverified; PR #105 and AC-1 are possible conflict owners. Refresh head/base, finish MD-0, then unblock four lanes. On integration transfer durable behavior/release obligations to canonical docs and delete completed workstream per policy.

### Integration checkpoint — 2026-10-10

- MD-1..4 candidate source exists in four separate feature branches; consolidation into `feat/meeting-detection-integration` includes CoreAudio process observation, ephemeral policy, notification category/actions, opt-in Settings and one-time API-claimed native-only start route.
- MD-5 candidate native shell wiring and authenticated start-intent/feedback endpoints are drafted; prior undefined `RecordingController.start()/stop()` menu-bar invocations have been replaced by the existing recorder start and canonical stop API. No separate recording owner was created.
- Supported-app allowlist is intentionally narrow: Zoom and Teams only, no assumption about Chrome/Meet. No packaged macOS, notification delivery, TCC, wakeups or interactive evidence has been observed; do not declare these PASS.
- The remaining blocking work is exact-head selected validation and affected FULL_MEDIA, any fixes revealed by that evidence, physical feasibility on packaged macOS and PR #105 menu-bar changes. Do not promote to stable `main` without release gates.
