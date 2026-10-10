# Meeting Detection — one-click suggested recording

Status: ACTIVE (plan only; implementation not started)
Target: `dev`; planning branch `plan/meeting-detection`
Baseline inspected: `dev@53662a1744632abf37d127cf253c1d70a667585d` on 2026-10-10. Refresh before implementation.

## Outcome and product shape

**User/job:** a person joining an online call wants ClosedRoom to offer recording before they forget, without interrupting the call.
**Outcome:** after explicit opt-in, the macOS menu-bar companion recognizes plausible active input use by a *supported* call app and offers a generic actionable macOS notification. **Record** requests the *existing* capture path; preparing is distinguished from actual recording, and the native overlay appears only on capture `ready`. **Not now** suppresses this call.
**Non-goals v0:** calendar, browser-tab/meeting-title/participant extraction, automatic start/stop, audio listening/classification, screen-content capture, remote processing, a second recording service/queue. Browser microphone activity alone is not proof of Google Meet.
**Defaults:** detection OFF; request notification authorization after opting in; recording `both` (mic + computer) as today; optional screen-context capture OFF; do not silently downgrade capture sources.
**Product risks:** VALUE (does suggestion help people record?); USABILITY (annoyance, focus theft); FEASIBILITY (CoreAudio per-process activity, notification callbacks when hidden, background-start contract); VIABILITY (CPU/RSS/wakeups, compatibility). If feasibility fails, decide NARROW_SCOPE, CHOOSE_ALTERNATIVE or DO_NOT_BUILD rather than pretending every microphone event is a meeting.
**Evidence:** local aggregate suggestion->record/ignore counters and false-positive scenarios, without meeting content. SHIPPED is not proof of usefulness.

## Canonical ownership and invariants

- Native shell: `src/local_asr_server/menubar.py`; main-thread Cocoa/window and native overlay: `window.py`; settings persisted by `settings.py` and exposed by existing Settings page/routes.
- Today `NewRecordingPage.tsx` -> `useRecorder.ts` orchestrates start via the existing capture reservation, API and `NativeCaptureManager`/`RecordingStore`. `HeavyWorkloadArbiter` alone schedules heavy work. `menubar.py` currently calls `RecordingController.start()` in WKWebView: **audit its actual delivery/ack across routes and hidden windows** before relying on it.
- Add only a lightweight shell-local detection/suggestion policy; canonical active/preparing/recording states must still come from the existing recording owner. Never create a parallel capture lifecycle, persisted meeting state or AI scheduler.
- Local-only. No audio buffers, content-based detection, remote requests, app/tab inventories in telemetry, transcript/path/title logging. Volatile session token and bounded content-free diagnostic outcomes only. Separate opt-in from macOS notification and capture/TCC permissions.
- No foreground focus on the happy path. `Preparing` is cancellable; only real capture `ready` starts REC/timer/overlay. Preserve manual New Meeting, browser-development recording fallback, notes, screenshots, Stop and recovery.
- Capability `supported|unsupported|unknown` must distinguish inability to inspect CoreAudio from an inactive call. If notifications are unavailable, preserve menu-bar and manual access.

## UX contract and edge states

`opted_out -> observing -> candidate -> suggestion -> {record|not_now|dismiss|expired} -> {preparing -> ready/recording | blocked | failed | cancelled} -> ended`.

1. Require stable input-use evidence from allowlisted apps (initial trial: 3–5 s), identify app only with reliable bundle ID, and avoid browser false positives; notification: "Possible meeting in progress" plus app label only when confirmed.
2. Actions: **Record** sends one explicit, deduplicated start intent; **Not now** / dismissal suppress this session; body-click opens contextual ClosedRoom but never starts; stale action after call ended fails closed.
3. On accepted Record, keep call app foreground, surface small non-REC preparation/cancel status, and resolve actual readiness from existing capture events. If permission/storage/device fails, show actionable recovery, opening the full ClosedRoom window only when necessary.
4. Once capturing, show compact overlay and menu-bar controls (timer, audio health, Note, Screenshot, Stop). Never show REC before native `ready`; do not auto-stop when meeting activity disappears.
5. No repeated prompt within same session after dismiss, ignore, starting, recording or manual Stop; brief mute, helper PID change or reconnect must not reopen a prompt. Remove/expire outstanding notifications when source ends.
6. If ClosedRoom is foreground, favor in-app contextual presentation; if native notifications are denied, menu bar remains usable. Ensure keyboard, VoiceOver and reduced-motion behavior.

**Proposed internal contracts to freeze at MD-0** (not persisted/public API):
- `ActivityObservation{bundle_id,pid?,monotonic_time,input_active,capability,reason}` — no media.
- `MeetingCandidate{ephemeral_id,source_kind,label?,created_monotonic,expires_monotonic}` — rejoin-safe identity/epoch.
- `SuggestionDecision{notify|suppress|close,reason,candidate_id?}` — includes opt-out, unsupported, ambiguous, previously dismissed, already active/pending, cooldown, denied notifications.
- `NotificationAction{candidate_id,record|ignore|body_open}` — process once and revalidate epoch + active recording before starting.
- `StartAcknowledgement{accepted|already_active|preparing|blocked|failed|cancelled|recording_ready}` — correlated to **existing** capture reservation/session, never inferred from fire-and-forget JavaScript.

Initial *experimental*, not contractual, tuning: ~1 Hz or reliable events; 3–5 s activation debounce, 20–30 s inactivity hysteresis, one suggestion per inferred session; bounded expiration and low idle polling. Measure real devices before selecting final values.

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

**MD-0 — READY (blocking contract gate).** Inspect `dev`, root/scoped guides, directly impacted consumers/tests and current PRs; in particular open PR #105 (macOS 26 menu bar and Settings) and `architectural-consolidation` AC-1 edits to `useRecorder`. Validate CoreAudio `kAudioHardwarePropertyProcessObjectList`/`kAudioProcessPropertyIsRunningInput` compatibility on candidate macOS and app IDs, per-process access constraints, and actionable UNUserNotificationCenter delivery in packaged app (feasibility probe, not product claims). Choose minimal reliable **shared** start owner/ack from any WKWebView route with hidden window. Freeze input/action/start interface, supported-app matrix and no-focus contract; if any assumption fails, explicitly narrow scope before W1.

**W1 parallel lanes** (separate short-lived worktrees from refreshed `dev`; no shared-file simultaneous edits; experimental paths remain unused/disabled until integration):

| ID / lane | State | Exclusive write boundary | Observable deliverable / test |
| --- | --- | --- | --- |
| MD-1 / A | BLOCKED on MD-0 | New `src/local_asr_server/meeting_detection*.py` and new focused tests; isolated CoreAudio bridge only if feasibility requires it | Input activity/capability + pure deduplicating suggestion policy; start/end hysteresis, unsupported app, false positive, PID change, concurrent sources, session expiration, thread cleanup. Never write `menubar.py`/settings/recorder. |
| MD-2 / B | BLOCKED on MD-0 | New `macos_meeting_notifications.py` adapter and tests | UNUserNotificationCenter categories, Record/Not now/body/dismiss semantics, action IDs, callback completion, stale/duplicate handling, opt-in permission, no personal text; mockable native boundary. No `menubar.py` edits. |
| MD-3 / C | BLOCKED on MD-0 | `frontend/src/hooks/useRecorder.ts`, directly consumed recording controller/bridge or service/API contract, focused tests | Exactly one start owner shared by manual/menu-bar/notification, acknowledged despite hidden or non-recording route, atomic reservation, wait-for-AI cancel, correct error/ready, no duplicate session; browser/manual flow unchanged. Coordinate exclusive `useRecorder` ownership with AC-1. |
| MD-4 / D | BLOCKED on MD-0 | `settings.py`, Settings router/schema, `frontend/src/pages/SettingsPage.tsx`, related i18n/UI tests | `meeting_detection_enabled=false` default; user-readable privacy/capability and opt-in UI, clear status and diagnostics; permission request only after opt-in, opt-out persists; no modal/onboarding blocking recording. No `menubar.py` edits. |

W1 branches: `feat/meeting-detection-core`, `feat/meeting-detection-notifications`, `feat/meeting-detection-start`, `feat/meeting-detection-preferences`. Validate owner-local work independently; publish short focused PRs to `dev` behind off-by-default behavior and converge early instead of building a long stacked PR tree. Resolve current base/PR #105 movement and API mismatches before each merge.

**MD-5 — BLOCKED on MD-1..4; single integration owner.** Wire only this lane into `menubar.py` and `window.py` (and necessary app lifecycle/packaging), start/stop detector, keep delegate retained and Cocoa calls on main thread, ensure one monitor per process and bounded shutdown, expose contextual menu-bar action, actionable-notification start and fallback when notifications denied, foreground preservation, truthful preparing/ready/recovery and native overlay after real capture. Coordinate PR #105 changes; no competing edits to these files.

**MD-6 — BLOCKED on MD-5.** Add affected FULL_MEDIA browser journey (synthetic detector/notification fixtures), focused integration tests and physical Mac matrix; update `design/ux-contract.json`, `docs/features.md`, `docs/current-state.md`, architecture docs only if ownership changed. Decide whether native-app v0 is useful enough to enable as an opt-in setting; no promises for browser Meet without evidence.

## Acceptance and validation checklist

**Deterministic:** stable/ambiguous/unsupported observation, activate/mute/rejoin/end, duplicate/noisy process events, opt-out, denied notifications, old callback, two rapid Record taps, existing pending/active ClosedRoom recording, hidden/route-switched WKWebView, AI-busy reservation, capture-ready timing, cancel/failed permissions/missing storage/missing source, stop -> persisted Meeting, notes/screenshot unchanged, restart/shutdown resource cleanup, no sensitive or remote telemetry, keyboard/focus/VoiceOver structure. Extend `test/test_recording_api.py`, `test/test_native_capture.py`, existing frontend recording/overlay tests and `test/test_macos_hotkeys.py` as actually affected; add behavior tests, not just source-string assertions.

**Browser FULL_MEDIA:** opted-out -> opt-in -> simulated suggestion -> Record -> preparing -> native-ready fixture -> overlay -> Stop, plus ignore, blocked permission, stale/duplicate action and existing manual flow. Mocked fixtures **do not** prove macOS notification/CoreAudio delivery.

**REAL_ENVIRONMENT on exact packaged Mac artifact:** Teams/Zoom call+mic tests on explicitly supported OS/app versions; browser/helper identity and false positives; notifications when app background/hidden/fullscreen/another Space; Record and Not now, stale action after call end, native TCC mic+system WAV persisted, truthful timers and overlay, notification denied and menu-bar recovery (incl macOS 26 allowance), idle CPU/RSS/wakeups and shutdown. Record source/OS/build identity and aggregate observations only; subjective interruption/VoiceOver needs human evaluation.

**Axes:** PRODUCT_FEATURE. DELIVERY=ITERATION per lane -> INTEGRATION into `dev` -> RELEASE only `dev -> main`. VALIDATION=SCOPED for pure policy/settings, STRONG for native/recording/shared lifecycle/integration; selector can escalate to FULL for packaging or other risks, never downgrade. EXECUTION=AGENT_LOCAL for available deterministic gates, REMOTE_AUTOMATED for unavailable deterministic Mac/toolchain gates, REAL_ENVIRONMENT for actual app/TCC/notification tests. Run `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration` plus selected gates and affected FULL_MEDIA; at release require FULL and applicable target-Mac proof. Avoid repeated redundant GitHub Actions: local lane checks first, reuse exact-head/tree-equivalent evidence when valid, one sufficient remote run after coherent integration when required.

**Definition of done:** opt-in one-click recording from supported native call app, no silent recording or remote processing, duplicate-free prompts, reliable acknowledged start even when window hidden, true ready/REC transition, clean cancellation/recovery, manual/overlay regression gates green, docs aligned. Do not call target-Mac evidence complete on simulator/CI.

**Resume checkpoint:** plan only; no feature code, no CoreAudio feasibility or macOS notification proof. Source baseline `dev@53662a1744632abf37d127cf253c1d70a667585d` is context, not passing gate evidence. On resume: refresh head/tree/base, inspect PR #105 and AC-1, complete MD-0 discriminating probes/contract, then unblock W1. After integration transfer durable truth to canonical docs and delete completed workstream per repository policy.
