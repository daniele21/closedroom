# Meeting Detection — one-click native meeting recording

Status: ACTIVE (planning complete; implementation not started)
Target: `dev`; plan branch `plan/meeting-detection`
Scope: v0 macOS native calling activity -> opt-in suggestion -> one-click reliable recording
Last repository review: 2026-10-10, `dev@53662a1744632abf37d127cf253c1d70a667585d` (refresh on resume)

## Product intent and decisions

**User / job:** someone joining an online call wants to remember to capture it, without interrupting the call or navigating the full ClosedRoom workspace. ClosedRoom may **suggest**, but never silently start a recording.

**Desired outcome:** when a *supported* meeting app is plausibly using microphone input, the already-running ClosedRoom menu-bar companion offers an unobtrusive, actionable macOS notification. On **Record**, it invokes the **same canonical recording start** as New Meeting and displays compact feedback while staying out of the foreground. REC/timer/overlay appear only after real native capture readiness. User can choose **Not now**, suppressing that call's further prompts.

**Non-goals (v0):** calendar, meeting title/participant extraction, browser-tab inspection or extension, audio/content classification, auto-start, auto-stop, remote/cloud fallback, a new recording backend, new meeting catalog, screen-frame capture, analytics service, exact Zoom/Teams call semantics. Browser apps are not considered definitively in-call merely because their microphone is active.

**Defaults:** detection **off until explicit opt-in**; ask for system notification authorization only then; capture mode remains current default `both` (mic + computer), screen context remains **off**. User controls local microphone/screen-recording TCC authorization independently. Recording consent/notice to other participants remains user's responsibility.

**Risk and evidence (PRODUCT_FEATURE):**
- VALUE: forget-to-record is important enough to justify optional prompting; measure suggestion -> explicit-start conversion on opt-in test calls, using aggregate *local* counters.
- USABILITY: unnecessary prompts or focus theft outweigh recall; explicitly test dismiss/rejoin/overlay/VoiceOver and foreground app preservation.
- FEASIBILITY: per-process CoreAudio input activity, notification action delivery in a packaged macOS app, browser helper identity, and hidden-WKWebView start are **unproven on representative Macs**. A readiness spike must resolve these before claiming v0 support.
- VIABILITY: no perpetual expensive polling, no memory leak, no new always-running inference; all observation/diagnostic state is ephemeral and privacy-safe.

## Ownership and invariants

- `src/local_asr_server/menubar.py` is the macOS shell integration owner; `window.py` owns Cocoa/WKWebView/window/overlay focus behavior. Native UI mutations happen on main thread.
- `src/local_asr_server/settings.py` owns persisted opt-in and bounded preferences; Settings React page is only its UI. No additional persistence owner.
- Current canonical recording path: `frontend/src/pages/NewRecordingPage.tsx` -> `frontend/src/hooks/useRecorder.ts` -> existing capture-admission/API/NativeCaptureManager/RecordingStore. `HeavyWorkloadArbiter` remains sole heavy-work scheduler and reservation owner. Audit the current `RecordingController.start()` shell bridge before relying on it: `menubar.py` invokes JavaScript, but this alone does not prove background-start delivery from every current WKWebView route.
- Native app shell may own a **small, disposable detection/suggestion state machine**; it must never own a parallel recording state, recording catalog, job queue or audio capture path. Read the canonical active-recording/capture state before acting.
- No remote event transfer; never record audio or meeting/tab/window titles for detection. Ordinary logs must not contain microphone samples, transcripts, local paths, meeting names, or raw process inventories; diagnostics limited to supported/unknown signal, outcome reason, elapsed times and bounded counters.
- No forced focus to ClosedRoom on the golden path; permission/error recovery is the only reason to open the full app. Existing manual record, stop, notes, screenshots and browser-development behavior must remain valid.
- Detection capability is **three-valued** (`supported`, `unsupported`, `unknown/error`), not fake `no meeting` on CoreAudio failures. Notifications absent/denied must leave menu-bar/manual control available.

## User journey / states to implement

`inactive/opt-out -> monitoring -> candidate -> eligible -> suggested -> {record_requested | dismissed | expired} -> {preparing -> recording | blocked/error | canceled} -> call_ended`

1. After opt-in, on a compatible system detect plausible input use by explicitly supported call apps; require a short stable signal (initial experiment: 3-5 s), no content capture.
2. Before suggesting, check ClosedRoom not already recording or preparing, source call not already dismissed, and notification permission; keep title generic: "**Possible meeting in progress**". Show app label only if reliably identified.
3. Notification category actions: **Record** and **Not now**. Body tap opens contextual ClosedRoom (never records). Dismiss/timeout do not trigger recording. Notification can be removed/invalidated when call ends; old callbacks revalidate current epoch/recording state.
4. On Record, atomically accept one intent for the current candidate; provide `Preparing recording` with explicit cancel while reservation/permissions/capture are pending; keep the current conferencing app in focus.
5. On actual native `ready`: project `recording` state; show native compact overlay with audio health, Note, Screenshot, Stop. Never show red REC or advance timer while only preparing.
6. On blocked permission/storage/device: show clear actionable recovery and open ClosedRoom at relevant existing settings/New Meeting recovery; do **not** start only-mic capture silently if the user requested `both`. On start failure: visible recoverable error with Retry/Open ClosedRoom.
7. If user ignores/dismisses/stops recording during the same call, do not prompt again until observed session has genuinely ended. Brief mute, app switching, disconnect/reconnect and browser helper changes must not create notification storms. Do not auto-stop on loss of detection signal.

### Suggested contract (freeze in MD-0)

Observation (internal, volatile only): `{ source_bundle_id, process_id?, observed_at_monotonic, input_active, capability, evidence_kind }`; no audio data.

Candidate: `{ ephemeral_session_id, source_kind, app_display_label?, created_at_monotonic, expires_at_monotonic, confidence_reason }`. Identity must withstand PID changes/rejoin hysteresis; never infer private meeting title.

Policy result: `{ decision: notify|suppress|close, reason, candidate_id? }`; suppression reasons include opt-out, unsupported app, ambiguous browser activity, active/pending ClosedRoom recording, prior dismissal, stale candidate, notification denied, cooldown.

Notification action: `{ candidate_id, action: record|ignore|body_open }`, processed once; **revalidate** candidate epoch and canonical active recording before any start. Ignore and duplicate actions are idempotent.

Start result: `accepted / already_active / preparing / blocked / failed / canceled / recording_ready`, correlated by existing canonical reservation/session ID; never use a fire-and-forget JS command as evidence of success. Acknowledgement must survive hidden/route-switched WKWebView or use the proper backend application owner; choose the smallest reliable shared approach at MD-0, not a second lifecycle.

Initial tunables for measurement, not asserted product SLOs: sample/observe at ~1 Hz or event-driven where reliable; 3-5 s activation debounce; 20-30 s inactive hysteresis; one prompt per inferred session; bounded expiration/cooldown and no busy-loop while idle. Tune from local observations, do not hard-code arbitrary confidence claims.

## Execution graph: independent parallel work with early convergence

**W0: one short serial decision gate** — MD-0 (READY). Freeze interfaces, baseline acceptance, test fixture schema and minimum supported macOS/call-app list. Check any open UI/menu-bar PR, particularly #105, and concurrent `architectural-consolidation` AC-1 `useRecorder` edits. Recheck latest `dev`. Do not spawn divergent start coordinators.

**W1: four independent lanes started in parallel after MD-0:**
- **Lane A / MD-1:** CoreAudio detector + pure suggestion policy; writes only new `src/local_asr_server/meeting_detection*.py` modules and their new unit tests (or one narrowly-scoped native bridge if MD-0 demonstrates PyObjC/ctypes inadequate); **no** `menubar.py`, `settings.py` or existing recorder edits.
- **Lane B / MD-2:** macOS actionable notification adapter; writes only new `src/local_asr_server/macos_meeting_notifications.py` (or chosen single adapter) and tests; **no** shell integration. Stub/mock native framework boundary; no extra process/service.
- **Lane C / MD-3:** shared start-path hardening, acknowledgement, cancellation and route-independent invocation; exclusive owner of `frontend/src/hooks/useRecorder.ts`, related recording controller/bridge and directly impacted API/service paths/tests. Do not touch `menubar.py`, Settings or policy. Coordinate with AC-1 before edits.
- **Lane D / MD-4:** local opt-in settings, Settings UI and copy/accessibility; exclusive owner of `src/local_asr_server/settings.py`, `frontend/src/pages/SettingsPage.tsx`, related settings router/schema/i18n and tests. Do not touch `menubar.py`, `window.py` or recorder hook.

Use four short-lived task branches/worktrees from refreshed `dev` (`feat/meeting-detection-core`, `feat/meeting-detection-notifications`, `feat/meeting-detection-start`, `feat/meeting-detection-preferences`). Each lane produces a focused green owner-local change behind **disabled-by-default** behavior; merge/rebase early onto `dev`, never let independently developed shared API contracts drift. No stacked long-lived PR chain.

**W2: one integration owner** — MD-5 (BLOCKED on MD-1..4). Wire detector/policy/notification/opt-in/start to `menubar.py` and, only as necessary, `window.py`, app boot/shutdown and packaged identity. Add context-sensitive menu-bar affordance; no duplicate monitoring thread on restarts, no unnecessary foreground activation, and proper delegate lifecycle. This lane alone updates `menubar.py` and `window.py`; rebase around PR #105 if it lands. Add fallback to menu-bar entry if notifications unavailable.

**W3: integrated evidence and rollout** — MD-6 (BLOCKED on MD-5). Add end-to-end journeys and representative Mac matrix, update `design/ux-contract.json`, `docs/features.md`, `docs/current-state.md` and any affected architecture/packaging docs; run repository-selected gates. Do not promote to stable `main` until required RELEASE/FULL and REAL_ENVIRONMENT obligations are satisfied.

## Work items with observable acceptance

| ID | Status | Deliverable / acceptance | Gate / depends |
| --- | --- | --- | --- |
| MD-0 | READY | Decision note: supported min OS and app IDs, consent/notification copy, exact source of recording-start authority, foreground/focus contract; prototype process-input property and notification callbacks on packaged candidate where feasible. If stable per-process identification fails, NARROW_SCOPE to clearly supported apps or choose alternative menu-bar-only suggestion; never market generic browser activity as meeting detection. | First; source inspection + feasibility evidence |
| MD-1 | BLOCKED | Detector exposes stable/unknown/inactive observation and pure policy with one-prompt-per-session, mute/rejoin hysteresis, supported-app filtering, deduplication, expiry, shutdown cleanup. All records volatile; unit tests cover false positives and unsupported macOS. | MD-0; SCOPED local tests, native packaging at integration |
| MD-2 | BLOCKED | Opt-in-authorized UNUserNotificationCenter registration, category/actions, delegate lifecycle, background handling, genuine dismiss/body click, no leaking titles, idempotent stale callback rejection, disabled-notifications fallback signal. | MD-0; mocked contract + target-Mac delivery evidence |
| MD-3 | BLOCKED | Notification-triggered Start shares manual start's reservation/permission/native-ready/stop behavior and cannot silently no-op when hidden or on another WKWebView route. One in-flight request, confirmed ACK, cancel, clean failure and no timer before native ready. Browser dev/manual path unchanged. | MD-0; STRONG lifecycle/API tests; AC-1 collision check |
| MD-4 | BLOCKED | `meeting_detection_enabled=false` default; explain privacy, supported apps, notification authorization and start-at-login relation; opt-in/out persists; no prompt before opt-in; accessible UI/status/diagnostic; no initial modal. | MD-0; settings API/UI and no-permission tests |
| MD-5 | BLOCKED | Native integration emits timely generic suggestion, no focus stealing, conditional menu item, click-to-start and mini preparation/recovery feedback, overlay only on ready; shutdown tears down monitor/delegate and pending prompts. | MD-1..4; integration tests, packaged smoke |
| MD-6 | BLOCKED | Full golden path and refusal/recovery E2E, measured idle footprint, privacy/log checks, docs and explicit target-Mac evidence matrix; outcome metrics reported as observed, not assumed. | MD-5; INTEGRATION/STRONG selected gates + affected FULL_MEDIA |

## Test/evidence matrix

Deterministic unit/contract:
- supported/unsupported/unidentifiable process, denied permission/notification, timer rollover, rapid mute/unmute, helper-PID replacement, simultaneous apps, user ignored, rejoin, stale notification and duplicate-click race;
- `Record` with window hidden / other route / already recording / already preparing / active AI / killed-restarted app; no duplicate `RecordingStore` session or reservation; cancellation releases owned state;
- permission withheld, native capture failure, unavailable audio device, storage not configured, browser fallback, handoff to overlay and Stop -> saved Meeting with notes/screenshots still functional;
- content-free local logs, no network calls by detector, throttled observation, bounded shutdown, accessible status and notifications disabled.

Affected source owners include `test/test_recording_api.py`, `test/test_native_capture.py`, existing frontend recording tests, `test/test_macos_hotkeys.py`, and new dedicated meeting detection/notification/start tests; prefer behavior assertions over grep-only guards.

Browser FULL_MEDIA (new `meeting-detection-start` journey or extension of `record-meeting`): simulate detector/notification decisions with deterministic fixtures; ensure pending -> ready -> overlay -> stop; errors, cleanup, keyboard/focus, opt-in. Do **not** label this as proof of native notification or CoreAudio behavior.

Representative macOS REAL_ENVIRONMENT: packaged app icon/notification permission, source-app microphone toggles in Teams/Zoom and browser false-positive checks; notification action delivered while app hidden, in another Space, and after the call ended; microphone+computer audio persisted and elapsed timer true; menu-bar visibility on macOS 26 settings; CPU/RSS/wakeups idle-vs-enabled, TCC identity and shutdown. Record observations by OS/app version and exact artifact/source revision, no call content. Genuine user confirmation of perceived annoyance/VoiceOver remains human usability evidence.

Validation: PRODUCT_FEATURE / DELIVERY=ITERATION per lane then INTEGRATION to `dev`, RELEASE only at `dev -> main`; VALIDATION=SCOPED for isolated pure policy/UI slices, STRONG for lifecycle/native/notification integration (escalate via selector; packaging selector may require FULL); EXECUTION=AGENT_LOCAL when tools exist, REMOTE_AUTOMATED only for missing deterministic Mac/build/browser gates, REAL_ENVIRONMENT for physical app/TCC/notification observations. Use `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration` and selected gates. Do not launch four redundant remote full pipelines during experimentation; reuse valid exact-head/tree-equivalent evidence where allowed. UI integration requires affected FULL_MEDIA; release requires FULL and applicable target-Mac proof.

## Completion, rollout and resume

- First mergeable user outcome (v0): reliable call proposal on explicitly supported native app(s), confirmation from a macOS notification or menu bar, background start with true READY/REC transition, opt-in and anti-spam, preserved manual flows. Chrome/Google Meet detection is **not** promised until grounded browser-specific evidence exists.
- On readiness evidence, choose `BUILD`, `NARROW_SCOPE`, `CHOOSE_ALTERNATIVE` or `DO_NOT_BUILD` transparently; product success requires measurement, not merely SHIPPED code.
- Upon MD-6 integration, move stable behavior and release evidence obligations into canonical feature/UX/current-state owners. Delete this plan per repository policy only after knowledge is transferred.
- **Resume checkpoint (planning):** source reference `dev@53662a1744632abf37d127cf253c1d70a667585d` (not execution proof); MD-0..6 unimplemented; PR #105 currently open touching menu bar + Settings; AC-1 may edit `useRecorder`; no CoreAudio or notification REAL_ENVIRONMENT evidence yet. Next action: refresh `dev`, inspect PR #105 / AC-1 current status, execute MD-0 feasibility + shared-start-contract decision, then start W1 lanes independently.
