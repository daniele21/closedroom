# Meeting Detection — one-click suggested recording

Status: ACTIVE — integrated into `dev` with INTEGRATION/STRONG automated PASS; REAL_ENVIRONMENT pending
Target: `dev` via PR #108, squash `e712f175a27c39f1c1bb39f62e9322ebac9fb10f`
Integrated source from `5f60eca1a5b5f3253dd175f5f200c656fb58cf22` on 2026-10-10.

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

**MD-0 — CONTRACT CHOSEN (physical feasibility unproven).** Inspect `dev`, root/scoped guides, directly impacted consumers/tests and current PRs; in particular open PR #105 (macOS 26 menu bar and Settings) and `architectural-consolidation` AC-1 edits to `useRecorder`. Validate CoreAudio `kAudioHardwarePropertyProcessObjectList`/`kAudioProcessPropertyIsRunningInput` compatibility on candidate macOS and app IDs, per-process access constraints, and actionable UNUserNotificationCenter delivery in packaged app (feasibility probe, not product claims). Choose minimal reliable **shared** start owner/ack from any WKWebView route with hidden window. Freeze input/action/start interface, supported-app matrix and no-focus contract; if any assumption fails, explicitly narrow scope before W1.

**W1 parallel lanes** (separate short-lived worktrees from refreshed `dev`; no shared-file simultaneous edits; experimental paths remain unused/disabled until integration):

| ID / lane | State | Exclusive write boundary | Observable deliverable / test |
| --- | --- | --- | --- |
| MD-1 / A | INTEGRATED | New `src/local_asr_server/meeting_detection*.py` and new focused tests; isolated CoreAudio bridge only if feasibility requires it | Input activity/capability + pure deduplicating suggestion policy; start/end hysteresis, unsupported app, false positive, PID change, concurrent sources, session expiration, thread cleanup. Never write `menubar.py`/settings/recorder. |
| MD-2 / B | INTEGRATED | New `macos_meeting_notifications.py` adapter and tests | UNUserNotificationCenter categories, Record/Not now/body/dismiss semantics, action IDs, callback completion, stale/duplicate handling, opt-in permission, no personal text; mockable native boundary. No `menubar.py` edits. |
| MD-3 / C | INTEGRATED | `frontend/src/hooks/useRecorder.ts`, directly consumed recording controller/bridge or service/API contract, focused tests | Exactly one start owner shared by manual/menu-bar/notification, acknowledged despite hidden or non-recording route, atomic reservation, wait-for-AI cancel, correct error/ready, no duplicate session; browser/manual flow unchanged. Coordinate exclusive `useRecorder` ownership with AC-1. |
| MD-4 / D | INTEGRATED | `settings.py`, Settings router/schema, `frontend/src/pages/SettingsPage.tsx`, related i18n/UI tests | `meeting_detection_enabled=false` default; user-readable privacy/capability and opt-in UI, clear status and diagnostics; permission request only after opt-in, opt-out persists; no modal/onboarding blocking recording. No `menubar.py` edits. |

W1 branches: `feat/meeting-detection-{core,notifications,start,preferences}`. Owner-local tests and early convergence; handle PR #105 conflicts before integrating.

**MD-5 — INTEGRATED (native behavior unverified).** Wire only this lane into `menubar.py` and `window.py` (and necessary app lifecycle/packaging), start/stop detector, keep delegate retained and Cocoa calls on main thread, ensure one monitor per process and bounded shutdown, expose contextual menu-bar action, actionable-notification start and fallback when notifications denied, foreground preservation, truthful preparing/ready/recovery and native overlay after real capture. Coordinate PR #105 changes; no competing edits to these files.

**MD-6 — MENU VISIBILITY RESTORED.** `UserNotifications` fixes missing block metadata; signed build notifications authorized (2026-10-13). Menu recovery preserves the old item on failure; native geometry alone is not visibility proof. Recreation, Finder launch and ControlCenter restart failed. Registry confirms disabled `com.openai.codex.menuItemLocations` also contains ClosedRoom, overriding its allowed row. Removing that association and reloading user preferences/ControlCenter restored onscreen hosts; final registry matches the approved policy and the user confirms visibility. ChatGPT remains disabled; original backup retained. Evidence: `dist/evidence/menu-bar-policy-20261013/applied.json`. Native notification/capture proof and FULL_MEDIA integration remain pending; browser Meet unsupported.

## Acceptance and validation checklist

**Implementation evidence checkpoint:** PR #108 INTEGRATION/STRONG exact source head `5f60eca1`: frontend, Python, browser FULL_MEDIA, packaged macOS smoke and aggregate validation PASS (run #38088512808); repository health PASS (run #38088512800). Squash into `dev` commit `e712f175`; REAL_ENVIRONMENT is not covered by CI. Browser FULL_MEDIA `meeting-detection-start` now exercises authenticated one-time claim -> AI-safe preparing -> ready -> Stop using shared fixture harness. `test_window_origin.py` covers the independent overlay route. A content-free target-Mac probe is provided: `python3 scripts/probe_meeting_detection.py --seconds 60 --expect-app Zoom --require-on-off --output dist/evidence/meeting-detection/zoom.json` (repeat for Microsoft Teams). Real notification callbacks, TCC, macOS 26 menu placement, foreground retention and CPU/RSS remain unproven until physical evidence.



**SCOPED owner tests:** CoreAudio unsupported/unknown, debounce, mute/rejoin, PID/duplicate callback, opt-out, privacy-safe logs; Pydantic settings partial updates; authenticated nonce claimed once; native-only start prevents browser fallback; failed permission and cancellation. New tests: `test_meeting_detection.py`, `test_macos_meeting_notifications.py`, `test_meeting_detection_settings.py`, `test_meeting_detection_api.py`, `test_frontend_meeting_detection.py`; preserve existing recording/overlay regressions.

**INTEGRATION / STRONG + affected FULL_MEDIA:** automatic journey verified in CI through Record -> preparing -> ready -> Stop. Simulated notifications do not prove macOS delivery or TCC.

**REAL_ENVIRONMENT (release blocker):** packaged app actual Zoom/Teams CoreAudio activity, notification actions with hidden window/other Space, no false Meet/browser claims, full mic+system TCC audio and true REC, menu-bar visibility (incl macOS 26), CPU/RSS/wakeups, stop/exit cleanup and usability/VoiceOver. Record build/OS identity, no meeting content. RELEASE to `main` still requires FULL plus target-Mac proof.

**Axes:** PRODUCT_FEATURE; INTEGRATION in `dev` automated-ready; STRONG PASS; remote Mac CI is not REAL_ENVIRONMENT. RELEASE still needs FULL plus physical proof.

**Done:** user opt-in, supported-app suggestion, explicit once-only action, true recording readiness, suppress repeat prompts and preserve manual flows; evidence and durable docs agree.
