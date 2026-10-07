# Meeting moments, quick notes and context-aware menu bar

Status: active
Owner: meeting UX, RecordingStore, capture clock, macOS app shell
Read when: implementing or integrating timestamped user notes, meeting moments or menu-bar meeting actions

## Goal

Make ClosedRoom a deliberately simple meeting note taker without turning it into a general editor.

During recording the user can mark an important moment by:

- taking the existing manual screenshot: capture what I see;
- writing a quick user note: capture what I think.

Both reappear at the corresponding transcript/audio time. Notes stay explicitly user-authored evidence; screenshots stay visual evidence; neither alone proves what was spoken, agreed or decided.

The macOS menu bar becomes a meeting-aware companion for New meeting, recent meetings, Add note, Screenshot, recording controls and Stop.

## Classification

- Product: PRODUCT_FEATURE.
- Delivery: ITERATION until automated readiness; INTEGRATION when targeting `dev`.
- Validation: STRONG because persistence/native shell change; affected Meeting UI requires FULL_MEDIA.
- Execution: AGENT_LOCAL where equivalent; REMOTE_AUTOMATED for unavailable deterministic macOS gates; REAL_ENVIRONMENT remains release evidence for actual menu/hotkey/focus/TCC behavior.

## Product contract

- Recording UX is click -> type -> Enter; Shift+Enter newline; Esc cancel.
- Plain text only, max 4000 characters. No formatting, tags, folders or checklist UI.
- Note anchor is captured when the composer opens, not when Save finishes.
- Native recording uses the same authoritative `recording_ready_uptime` clock family as screenshots.
- Editing after the meeting never moves the original anchor.
- Success is shown only after durable local persistence.
- RecordingStore owns note artifacts; no `MeetingMomentStore` is introduced.
- Transcript segments/IDs remain immutable; Meeting builds a read projection of transcript + screenshot + user note timestamps.
- Source kinds remain distinct: `spoken`, `visual`, `user_note`, `mixed`.
- User notes may increase salience for Prepare notes but cannot alone establish a spoken/agreed/decided claim.
- Creating a note never starts ASR/LLM/VLM work.
- User-note text is not emitted to ordinary logs/telemetry.
- Cloud providers do not receive user notes implicitly; current structured-note enrichment is local/mock only.
- Menu bar reads canonical app/recording state and invokes canonical APIs/actions; it owns no recording or note state machine.
- Healthy menu UI never exposes server/port/runtime terminology.
- Core meeting hotkeys use narrow native registration; Accessibility remains only for legacy clipboard actions that synthesize input.

## Durable note contract

RecordingStore session artifact: `notes.json`, schema v1.

Logical item:

```text
note_id
recording_id
request_id
sequence
timestamp
created_at
updated_at
text
revision
source_kind = user_note
```

Rules:

- create is idempotent by request identity;
- edit uses optimistic revision conflicts;
- delete is durable;
- restart reloads the same manifest;
- timestamp is finite/non-negative and immutable after create;
- CatalogStore gets only recording metadata projection such as note count, not duplicate note text.

API:

- `POST /v1/recordings/{id}/notes/anchor`
- `GET /v1/recordings/{id}/notes`
- `POST /v1/recordings/{id}/notes`
- `PATCH /v1/recordings/{id}/notes/{note_id}`
- `DELETE /v1/recordings/{id}/notes/{note_id}`

## Target experience

Overlay:

```text
● 18:42  Product Weekly
[ Screenshot ] [ Note ] [ Stop ]

Note -> 18:42
[ Add a note about this moment… ]
Enter to save · Esc to cancel
```

Meeting:

```text
12:31  Marco  We should move the launch…
12:42  YOUR NOTE  Ask Marco for updated numbers.
13:06  SCREENSHOT  [thumbnail]
13:14  You  November 12 is tentative.
```

Clicking a note timestamp seeks audio. User notes can be edited/deleted post-meeting with anchor preserved.

Menu bar:

```text
Pronto
+ Nuovo meeting
Recenti >

during recording:
● Product Weekly
Add note
Screenshot
Open recording controls
Stop recording
```

Native meeting shortcuts:

- `⌘⇧R`: start/stop meeting;
- `⌘⇧N`: add quick note;
- `⌘⇧9`: screenshot selected display.

Registration collision/failure is visible and menu actions remain usable; there is no silent Accessibility fallback for these core actions.

## Work graph

| ID | Outcome | Write owner | Depends | State |
| --- | --- | --- | --- | --- |
| MM-0 | Freeze timestamp/provenance/API contract | schemas/contracts/tests | — | ACTIVE |
| MM-1 | Durable note persistence + API | RecordingStore/router/schemas | MM-0 | ACTIVE |
| MM-2 | Minimal overlay quick-note capture | RecordingOverlayPage/API | MM-0 | ACTIVE |
| MM-3 | Transcript timeline + seek/edit/delete | MeetingDetail/TranscriptTextView | MM-0 | ACTIVE |
| MM-4 | Prepare notes provenance/salience | preparation/structured notes | MM-1 | ACTIVE |
| MM-5 | Context-aware menu + Recent | menubar shell | MM-0 | ACTIVE |
| MM-6 | Menu-bar quick note/screenshot | shell + canonical API | MM-1/2/5 | ACTIVE |
| MM-7 | Native core meeting hotkeys | macos_hotkeys + shell | MM-5 | ACTIVE |
| MM-8 | Full diff/docs/E2E/preflight/integration | cross-slice only | MM-1..7 | ACTIVE |

Allowed states: `READY`, `ACTIVE`, `BLOCKED`, `DONE`. MM-0..7 implementation is present; they remain ACTIVE until required exact-head automated evidence is green.

## Integration points

- I1: one note payload/timestamp/revision/source contract.
- I2: overlay, Meeting and menu bar call the same recording-note API.
- I3: Meeting and Prepare notes consume the same durable note identity/provenance.
- I4: menu/hotkeys call canonical actions only; no direct storage mutation.
- I5: existing screenshot storage/capture invariants remain unchanged.

## Failure/recovery

- Anchor/save failure never stops audio.
- Save failure keeps the overlay draft available for retry.
- Duplicate create returns the same committed note.
- Edit conflict is explicit; no silent last-write-wins.
- Screenshot failure and note failure are independent.
- Missing display never causes the menu bar to switch display silently; it opens recording controls.
- Menu API calls preserve loopback auth via the local session token and refresh once on 401.
- Native hotkey collision/failure leaves menu actions available.
- Unsaved quick-note text may be lost if its small composer is closed in v1; it is never reported as saved.

## Validation

Required integration evidence selected by repository policy:

- governance/repository checks;
- frontend lint + TypeScript;
- full Python unit/integration suite;
- affected browser FULL_MEDIA journey;
- packaged-app smoke because persistence/native boundaries changed.

The existing call-overlay FULL_MEDIA journey now also proves:

recording overlay -> screenshot -> note anchor -> note commit -> Stop -> Meeting -> structured `user_note` citation -> transcript marker -> note edit with unchanged timestamp -> screenshot/audio context.

Focused contracts include note persistence/restart/idempotency/revision/delete, preparation source identity, structured-note provenance, frontend marker behavior and native-hotkey constants/ownership.

REAL_ENVIRONMENT remains required at release for:

- Carbon shortcut registration/delivery/collision on supported macOS;
- menu-bar quick-note focus while another app/fullscreen Space owns focus;
- packaged WKWebView behavior;
- real TCC/ScreenCaptureKit display selection/capture;
- physical audio behavior already owned by existing release evidence.

## Durable documentation destinations

- `design/ux-contract.json`: current meeting-moment and menu semantics.
- `.engineering/e2e.json`: meeting-moments automated/real-environment contract.
- `docs/features.md`: durable user-visible behavior.
- `docs/current-state.md`: integration/readiness state when exact-head evidence is known.
- `docs/architecture.md`: no update unless ownership/topology changes beyond existing RecordingStore/shell boundaries.

## Resume checkpoint

Target/base:

- target: `dev`;
- base at latest refresh: `271d5b6b8b01a97097909dab8a620b98f391bbfa`;
- branch: `work/meeting-moments-notetaker-menubar`;
- base movement at latest refresh: none.

Implementation present:

- RecordingStore `notes.json` artifact + note API/revision/idempotency;
- authoritative native note anchor + explicit browser/dev fallback;
- overlay composer + persistent success/Undo;
- Meeting timestamp projection + seek/edit/delete;
- Prepare notes local/mock `user_note` provenance and source hashing;
- meeting-aware menu, Recent, quick note/screenshot;
- native Carbon meeting hotkey owner; legacy pynput limited to clipboard tools;
- loopback auth retained for shell API actions;
- source/static contracts and affected FULL_MEDIA fixture updated.

Unresolved evidence:

- deterministic exact-head integration preflight has not yet run;
- target-Mac interactive/native confirmation is intentionally deferred to RELEASE.

Next discriminating action:

- refresh head/base, inspect full diff, open one integration PR to `dev` and use repository remote preflight for the required STRONG gates. Diagnose any failure by invariant/owner before patching.

## Completion

Implementation complete != integration complete.

MM-0..7 become DONE only when their required automated evidence agrees with exact source. MM-8 completes after integration docs/evidence agree and the temporary workstream can be removed. Release readiness remains separate and requires the deferred target-Mac evidence above.
