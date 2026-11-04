# Meeting Detection — one-click suggested recording

Status: ACTIVE — integrated into `dev` with INTEGRATION/STRONG automated PASS; REAL_ENVIRONMENT pending
Target: `dev` via PR #108, squash `e712f175a27c39f1c1bb39f62e9322ebac9fb10f`
Integrated source from `5f60eca1a5b5f3253dd175f5f200c656fb58cf22` on 2026-10-10.

## Outcome and product shape

**User/job:** a person joining a call wants a discreet recording suggestion.
**Outcome:** with content-free detection enabled by default for new installations (and reversible in Settings), the macOS menu-bar companion recognizes plausible active input use by a *supported* call app and offers a generic actionable macOS notification. **Record** requests the *existing* capture path; preparing is distinguished from actual recording, and the native overlay appears only on capture `ready`. **Not now** suppresses this call.
**Non-goals v0:** calendar, browser-tab/meeting-title/participant extraction, automatic start/stop, audio listening/classification, screen-content capture, remote processing, a second recording service/queue. Browser microphone activity alone is not proof of Google Meet.
**Defaults (2026-11-04 candidate):** detection ON for newly created settings; a saved false remains authoritative. Request macOS notification consent once when status is not-determined, never bypass a denial. Recording `both` (mic + computer) remains a deliberate click; optional screen-context capture OFF; do not silently downgrade sources.
**Product risks:** VALUE (opt-in conversion); USABILITY (annoyance/focus); FEASIBILITY (CoreAudio, background notification/start); VIABILITY (resource use/OS coverage). If unsupported, NARROW_SCOPE, CHOOSE_ALTERNATIVE or DO_NOT_BUILD.
**Evidence:** local content-free conversion/false-positive observations; SHIPPED is not product success.

## Canonical ownership and invariants

- Native shell: `src/local_asr_server/menubar.py`; main-thread Cocoa/window and native overlay: `window.py`; settings persisted by `settings.py` and exposed by existing Settings page/routes.
- `NewRecordingPage.tsx` -> `useRecorder.ts` owns start via existing reservation/API/`NativeCaptureManager`/`RecordingStore`; `HeavyWorkloadArbiter` owns heavy work. `menubar.py` calls `RecordingController.start()`: **verify delivery/ack on all routes and hidden windows**.
- Add only shell-local suggestion state; canonical recording states remain with existing owner. No second capture, meeting store or scheduler.
- Local-only; no audio buffers/content detection/remote calls/sensitive logs. Only volatile session tokens and bounded diagnostic reasons. Detection default, explicit user override, OS notification consent and capture/TCC grants are separate permissions.
- No focus theft; `Preparing` cancellable, actual `ready` gates REC/timer/overlay; preserve manual/browser recording, note, screenshot, Stop and recovery.
- Capability `supported|unsupported|unknown` must distinguish inability to inspect CoreAudio from an inactive call. If notifications are unavailable, preserve menu-bar and manual access.

## UX contract and edge states

`disabled|observing -> candidate -> menu_offer -> {notification_pending -> enqueued | retry_wait | exhausted} -> {record|not_now|dismiss|expired} -> {preparing -> ready/recording | blocked | failed | cancelled} -> ended`.

1. Stable mic-input use in a supported app (initial experiment: 3–5 s) -> generic "Possible meeting in progress" notification; app name only if confidently known; browser mic activity alone is insufficient.
2. **Record** is one idempotent start intent; **Not now**/dismiss suppress this call, body-click opens ClosedRoom but never starts; expired notification action fails closed.
3. **Preparing** stays in a small cancellable non-REC surface without stealing call focus. Once canonical native capture reports `ready`, display REC/timer/audio health/Note/Screenshot/Stop. Permission/storage/device failures open targeted recovery, not an implicit mic-only fallback.
4. No second prompt for the same call after ignore, dismiss or manual Stop, even across brief mute/reconnect/helper PID changes. Loss of detection never auto-stops recording; notification denial retains menu-bar access.
5. Foreground ClosedRoom uses contextual in-app presentation; keyboard, VoiceOver, status feedback and reduced-motion are mandatory.

**Transient contracts:** observation, ephemeral candidate, one-time notification action and authenticated recording acknowledgement. Only volatile session state; all native callbacks fail closed.

Experimental tuning, not product SLO: event-driven or ~1 Hz sample, 3–5 s activation debounce, 20–30 s inactivity hysteresis, bounded expiry and one prompt/session; calibrate on Mac.

## 2026-11-04 default-on reliability candidate (NOT integrated)

**Scope/axes:** PRODUCT_FEATURE (change to first-run privacy disclosure and notification consent); ITERATION → INTEGRATION into `dev`; STRONG for native shell/settings/cross-boundary behavior, selector can require more; REMOTE_AUTOMATED for deterministic CI and REAL_ENVIRONMENT on the installed target Mac for release. No new capture engine, persistence owner, audio capture, calendar integration or cloud routing.

**Observed root causes in source:** CoreAudio recognition and notification delivery were conflated: `MeetingSuggestionPolicy.observe` marked a candidate prompted before any OS submission acknowledgement; denied/unknown permission and failed asynchronous submission could suppress all later delivery for the same call. The menu-bar status timer also stopped scanning after a loopback API failure. PR #116 fixed Teams CoreAudio attribution but did not prove an installed app's actual Zoom/Teams helper PID identity, OS banner or TCC behavior.

**New contracts:**
- `settings.py` defaults content-free native observation ON only for an absent preference. Persisted explicit OFF remains OFF; no silent migration of historic users. New installs must see the toggle and understandable disclosure.
- `MeetingNotificationCenter` requests macOS permission once per launch only when status is `not_determined`; authorization status is never inferred from the detection setting. Disabled users get no prompt. No automatic recording, audio access, external upload or browser Meet inference.
- A meeting first becomes a durable **volatile menu offer**, independent of notification availability. OS submission has a separate attempt count, pending timeout, exponential-independent bounded 15s cooldown, maximum 3 attempts and async success/failure callbacks. `enqueued` means macOS accepted the request, **not** that the banner was visible (Focus mode/OS user choice can suppress display).
- Denial/unknown permission does **not** consume attempts; granting permission mid-call can submit the still-active offer. Late/duplicate callbacks cannot mutate another attempt or revived session. Ignoring/dismissing/recording prevents repeated prompts.
- CoreAudio polling continues during transient local API outages, but capture still fails closed if the canonical recording server is unavailable. Settings expose capabilities, unattributed active-input count, OS authorization, suggestion and submission state; no meeting titles/PIDs/audio contents are recorded.

**Deterministic test matrix:** settings missing vs saved OFF and PATCH false/omitted; Teams/Zoom debounce, no helper inference from browsers, rejoin dedupe, busy stop, retry after async failure, timeout and stale callback, exhausted retry ceiling, late OS permission, no callbacks on denial, native authorization metadata tests, content-free probe on/off transitions and unattributed cases, existing one-time authenticated start / native-only recording / frontend FULL_MEDIA journey.

**Physical target-Mac acceptance:** launch exact installed artifact on representative macOS, enable/disable setting, grant/deny notification, join real Teams then Zoom meetings with mic mute/unmute and rapid rejoin; run `python3 scripts/probe_meeting_detection.py --seconds 60 --expect-app "Microsoft Teams" --require-on-off --output dist/evidence/meeting-detection/teams.json` and repeat for Zoom. Verify real banner and action Record while window is hidden/other Space, captured MIC+SYSTEM nonempty, truthful preparing→REC, no duplicate post-ignore prompt, no false browser Meet, menu-bar visibility under Tahoe, consent focus and CPU/RSS resource profile. A synthetic GitHub Actions PASS cannot replace this evidence.

**Status:** source/test changes staged on `fix/meeting-detection-default-reliability-20261104`; no exact-head CI or target-Mac PASS claim until collected. In particular an already-saved OFF preference will continue to require the user to turn detection ON.

## Integrated milestones

PR #108 integrated CoreAudio observation, native notifications, canonical one-time recording intent and Settings; PR #116 fixed Teams process attribution. Physical target-Mac proof remains open. Old parallel lane plans were superseded by code/tests.

## Acceptance and validation checklist

**Implementation evidence checkpoint:** PR #108 INTEGRATION/STRONG exact source head `5f60eca1`: frontend, Python, browser FULL_MEDIA, packaged macOS smoke and aggregate validation PASS (run #38088512808); repository health PASS (run #38088512800). Squash into `dev` commit `e712f175`; REAL_ENVIRONMENT is not covered by CI. Browser FULL_MEDIA `meeting-detection-start` now exercises authenticated one-time claim -> AI-safe preparing -> ready -> Stop using shared fixture harness. `test_window_origin.py` covers the independent overlay route. A content-free target-Mac probe is provided: `python3 scripts/probe_meeting_detection.py --seconds 60 --expect-app Zoom --require-on-off --output dist/evidence/meeting-detection/zoom.json` (repeat for Microsoft Teams). Real notification callbacks, TCC, macOS 26 menu placement, foreground retention and CPU/RSS remain unproven until physical evidence.



**SCOPED owner tests:** CoreAudio unsupported/unknown, debounce, mute/rejoin, PID/duplicate callback, opt-out, privacy-safe logs; Pydantic settings partial updates; authenticated nonce claimed once; native-only start prevents browser fallback; failed permission and cancellation. New tests: `test_meeting_detection.py`, `test_macos_meeting_notifications.py`, `test_meeting_detection_settings.py`, `test_meeting_detection_api.py`, `test_frontend_meeting_detection.py`; preserve existing recording/overlay regressions.

**INTEGRATION / STRONG + affected FULL_MEDIA:** automatic journey verified in CI through Record -> preparing -> ready -> Stop. Simulated notifications do not prove macOS delivery or TCC.

**REAL_ENVIRONMENT (release blocker):** packaged app actual Zoom/Teams CoreAudio activity, notification actions with hidden window/other Space, no false Meet/browser claims, full mic+system TCC audio and true REC, menu-bar visibility (incl macOS 26), CPU/RSS/wakeups, stop/exit cleanup and usability/VoiceOver. Record build/OS identity, no meeting content. RELEASE to `main` still requires FULL plus target-Mac proof.

**Axes:** PRODUCT_FEATURE; INTEGRATION in `dev` automated-ready; STRONG PASS; remote Mac CI is not REAL_ENVIRONMENT. RELEASE still needs FULL plus physical proof.

**Done:** user opt-in, supported-app suggestion, explicit once-only action, true recording readiness, suppress repeat prompts and preserve manual flows; evidence and durable docs agree.
