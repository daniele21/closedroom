# Meeting moments, quick notes and context-aware menu bar

Status: active
Owner: meeting UX, RecordingStore, capture clock, macOS app shell
Read when: implementing or coordinating timestamped user notes, unified meeting moments, menu-bar recording actions or global shortcuts

## Goal

Make ClosedRoom useful as a deliberately minimal meeting note taker without turning it into a general-purpose editor.

During a recording the user can mark an important moment in two fast ways:

- capture what they see with the existing manual screenshot action;
- capture what they think with a lightweight text note.

Both are anchored to the meeting timeline and reappear near the transcript/audio context for the moment in which they were captured. User notes remain explicitly user-authored evidence; screenshots remain visual evidence; neither silently becomes spoken evidence or a confirmed decision.

The macOS menu bar becomes a meeting-aware companion rather than a server-control surface: it exposes the current meeting, fast note/screenshot actions, Stop, recent meetings and recovery only when needed.

## Product / delivery classification

- Product: PRODUCT_FEATURE.
- Delivery: ITERATION while slices are developed; INTEGRATION when the coherent note + timeline + menu-bar journey targets `dev`.
- Validation: STRONG for persistence/data-lifecycle and native-shell changes; material UX integration requires affected FULL_MEDIA journeys. RELEASE remains FULL.
- Execution: AGENT_LOCAL for deterministic implementation/tests where equivalent tooling exists. REAL_ENVIRONMENT remains required for macOS menu-bar/hotkey/focus/TCC behavior that cannot be represented faithfully elsewhere.

## User outcome

Primary user: a professional who is already in a call and wants to remember one important thing without leaving the call context.

Job:

> When something important happens, let me mark it in one or two seconds so ClosedRoom can put it back in the right place later.

Successful outcome:

1. click/tap a note action from the compact overlay or menu bar;
2. type plain text;
3. save with Enter;
4. receive persistent success feedback;
5. later open the Meeting and see that note beside the transcript around the correct timestamp;
6. click the timestamp to seek the meeting audio;
7. use Prepare notes with the user note as a high-salience source whose provenance remains `user_note`.

## Non-goals

- General-purpose document editor, Notion/Obsidian replacement or rich-text workspace.
- Formatting toolbar, tags, folders, nested notes, checklists or collaborative notes during recording.
- Automatic/live transcription in the overlay.
- LLM/VLM/ASR work during recording.
- Treating a user note as proof that something was spoken, agreed or decided.
- Moving screenshot persistence into a new generic store merely to make notes and screenshots look similar in the UI.
- New scheduler, queue, search index or runtime owner.
- Silent cloud processing or remote fallback.
- Continuous screen capture.
- Redesigning the full Meeting workspace outside the surfaces needed for Moments.

## Product decisions

### 1. One mental model: mark this moment

The recording experience exposes two intentional markers:

- Screenshot: “capture what I see”.
- Note: “capture what I’m thinking”.

The UI may group them under a user-facing concept such as **Moments / Key moments**, but persistence remains source-specific. A shared UI concept must not force a speculative shared storage abstraction.

### 2. Note-taking stays deliberately minimal

Recording composer behavior:

- one plain-text field;
- focus immediately after opening;
- Enter saves;
- Shift+Enter inserts a newline;
- Escape cancels;
- empty/whitespace notes cannot be saved;
- bounded length with a clear counter only near the limit;
- no title/category/format choice during capture;
- after persistent commit, show short “Note saved” feedback and a bounded Undo for the latest note when safe.

The normal interaction is click -> type -> Enter.

### 3. Timestamp means user intent time

A note is anchored to the recording time when the composer is opened, not when the user finishes typing.

The timestamp must be derived from the canonical recording/capture clock, not browser wall-clock time. The implementation may obtain a capture-clock anchor when the composer opens and commit it with the note later.

Editing a note after the meeting never changes its original anchor timestamp.

### 4. Provenance is explicit

Source kinds:

- `spoken`: transcript/audio evidence;
- `visual`: screenshot-derived evidence;
- `user_note`: text authored by the user;
- `mixed`: a derived result that explicitly cites more than one kind.

A note such as “Decision: launch on 12 Nov” is still `user_note` until other evidence supports a decision claim.

### 5. Recording remains the resource priority

Creating, editing or deleting a user note is bounded local persistence. It must not start ASR, LLM or VLM work during recording.

Screenshot behavior keeps the existing rules: one-shot, selected display, no silent display switch, persistence before success.

### 6. Menu bar is a projection, not a state owner

The menu bar reads the canonical app/recording/job state and invokes existing actions. It must not create a second recording state machine, timer or note store.

Internal concepts such as “server active”, ports and runtime processes are removed from the normal menu. They surface only through diagnostics/recovery when actionable.

## Target experience

### Compact recording overlay

Collapsed:

```text
● 18:42      Product Weekly

   [ camera ]   [ note ]      [ stop ]
```

Note composer:

```text
18:42
┌──────────────────────────────────────┐
│ Add a note about this moment…        │
│                                      │
└──────────────────────────────────────┘
Enter to save · Esc to cancel
```

After commit:

```text
✓ Note saved · 18:42        Undo
```

Screenshot and Note have equal “mark this moment” semantics but distinct iconography and feedback.

### Meeting detail

Transcript remains canonical. Moments are inserted/projection-mapped without modifying ASR segment IDs or splitting transcript segments.

```text
12:31  Marco
We should probably move the launch...

12:42  YOUR NOTE
       Ask Marco for updated numbers before Friday.

12:49  Sarah
I'll send the revised financial model tomorrow.

13:06  SCREENSHOT
       [thumbnail]

13:14  You
Okay, then November 12 is our tentative date.
```

Required interactions:

- click moment timestamp -> seek audio to its anchor;
- edit/delete a user note post-meeting;
- open screenshot original as today;
- visually distinguish user note, screenshot and transcript source;
- missing asset/note failure remains explicit rather than shifting nearby markers.

A compact Moments summary may show user-marked moments above the transcript, but the timestamped transcript placement is the primary contract.

### Menu bar — idle

```text
ClosedRoom

New meeting

Recent
  Product Weekly
  Hiring Sync
  Venture review

Open ClosedRoom
Settings…
Quit
```

No “Server active” item in the normal healthy state.

### Menu bar — recording

```text
● Product Weekly
  18:42

Add note
Take screenshot

Open recording controls
Stop recording
```

Rules:

- Add note opens the same quick-note composer contract used by the overlay, preferably in a small focused panel/popover without opening the full app.
- Take screenshot uses the already-selected display. If display selection is missing/invalid, open the recording controls for explicit selection rather than silently choosing another display.
- Stop uses the existing canonical stop path.
- current meeting title/timer are projections of canonical recording state.

### Menu bar — processing/recovery

Show user outcome/state, for example “Preparing notes…” or a concise recovery action. Do not show backend/server terminology unless a diagnostic/recovery view is explicitly opened.

## Data and ownership contract

### User note artifact

RecordingStore remains the canonical owner of durable user-note artifacts for a recording.

Minimum logical contract:

```text
note_id
recording_id
timestamp_seconds
created_at
updated_at
text
revision
```

Additional internal idempotency/recovery fields are allowed when owned by RecordingStore and hidden from ordinary UI.

Constraints:

- timestamp is relative to the same meeting start/capture clock used for timeline evidence;
- note text is local meeting content and follows the same privacy boundary as transcript;
- writes are atomic/recoverable;
- create is idempotent for one request identity;
- edit uses revision/conflict semantics rather than last-write-wins ambiguity;
- delete/Undo follows the same RecordingStore lifecycle boundary;
- finalized audio/transcript identity is not mutated by note operations;
- user-note text is not emitted in ordinary telemetry/logs.

The first implementation should prefer a RecordingStore-owned artifact/manifest inside the recording session over adding text duplication to SQLite. Catalog projection is added only when required by a concrete archive/search/query outcome.

### Shared timeline projection

Do not create a generic `MeetingMomentStore` up front.

Instead:

- screenshots keep their existing screenshot artifact owner;
- user notes use RecordingStore note methods;
- MeetingDetail builds a read projection that merges transcript segments + screenshots + user notes by timestamp;
- shared frontend types may call the rendered entries `MeetingMoment` when useful.

This creates one user model without creating a second persistence owner.

## API contract direction

Exact endpoint naming may follow existing router conventions, but the outcome must support:

- list notes for a recording;
- capture a canonical note anchor when the composer opens;
- create an idempotent non-empty note using that anchor;
- update note text with revision/conflict protection;
- delete a note;
- recover/list notes after app restart.

The note-anchor action must be cheap and must not enqueue heavy work.

## Prepare notes behavior

User notes become optional high-salience inputs to the existing meeting-preparation owner.

Rules:

- no AI work starts because a note is created;
- Prepare notes reads the current note set after recording;
- `user_note` provenance is retained through source references;
- manual note wording may influence salience but may not be relabeled as spoken/confirmed;
- deleting/editing a note invalidates only derived work whose input identity includes that note set;
- transcript reuse remains unchanged;
- visual failure does not invalidate usable text/user-note preparation.

## Work graph

| ID | Work | Owns/writes | Depends on | Parallel | State |
| --- | --- | --- | --- | --- | --- |
| MM-0 | Freeze note timestamp/provenance/API contract and acceptance fixtures | workstream, schemas/contracts/tests only | — | no: integration spine | READY |
| MM-1 | RecordingStore user-note persistence, idempotency, revision/delete/recovery and API | `recordings.py`, recording router/schemas, focused persistence/API tests | MM-0 | yes | BLOCKED |
| MM-2 | Overlay quick-note composer and saved/undo/error states | `RecordingOverlayPage.tsx`, overlay API client/i18n/styles, focused frontend tests | MM-0 | yes; fixture-driven until MM-1 lands | BLOCKED |
| MM-3 | Meeting timeline projection: notes beside transcript + seek/edit/delete | `MeetingDetailPage.tsx`, meeting components/API client, focused frontend tests | MM-0 | yes; fixture-driven until MM-1 lands | BLOCKED |
| MM-4 | Prepare notes consumes user-note provenance and salience | meeting-preparation / structured-notes owners + source-boundary tests | MM-1 | yes with MM-3/MM-5 after API settles | BLOCKED |
| MM-5 | Context-aware menu bar states and actions; remove healthy server chrome | `menubar.py` + shell-facing tests only | MM-0 | yes | BLOCKED |
| MM-6 | Menu-bar quick-note panel reuses the same note action/composer contract | window/app shell + dedicated quick-note surface; no new persistence owner | MM-1, MM-2, MM-5 | yes with MM-4/MM-7 | BLOCKED |
| MM-7 | Native global hotkeys for core meeting actions without Accessibility dependency where platform allows | one macOS hotkey owner + shell integration/tests | MM-5; action contracts stable | yes with MM-4/MM-6 | BLOCKED |
| MM-8 | Coherent integration: Moments, menu bar, E2E, docs, preflight and closeout | cross-slice integration only | MM-1..7 | no | BLOCKED |

Allowed states: `READY`, `ACTIVE`, `BLOCKED`, `DONE`.

## Parallel execution lanes

After MM-0 freezes the shared contract, execute these lanes concurrently:

### Lane A — persistence/API

MM-1.

Write boundary:

- RecordingStore note owner;
- schemas/router/API tests;
- no Meeting/overlay/menu UI edits.

Observable completion:

- note survives restart;
- timestamp and request identity are stable;
- duplicate create request does not duplicate notes;
- edit conflict is explicit;
- delete is durable;
- no note text appears in ordinary logs.

### Lane B — capture UX

MM-2.

Write boundary:

- recording overlay + overlay-local UI/API bindings;
- no RecordingStore implementation;
- no MeetingDetail or menu-bar files.

Use deterministic API fixtures until MM-1 is merged into the work branch.

Observable completion:

- open -> focused input;
- anchor captured at open;
- Enter save / Shift+Enter newline / Esc cancel;
- saving/saved/failure states;
- temporary Undo after durable commit;
- audio controls remain dominant and usable at compact sizes.

### Lane C — review UX

MM-3.

Write boundary:

- MeetingDetail and meeting components;
- no overlay/menu/persistence changes.

Use fixtures containing transcript + screenshot + note timestamps.

Observable completion:

- deterministic temporal placement;
- no transcript segment mutation;
- seek from note;
- edit/delete note;
- provenance visually distinguishable and accessible;
- overlapping screenshot/note timestamps remain stable.

### Lane D — macOS shell

MM-5 first, then MM-6 and MM-7.

MM-5 can run in parallel with A/B/C because it initially uses existing recording state/actions and changes only the menu projection.

MM-6 converges on the MM-1/MM-2 note contract.

MM-7 stays isolated from note persistence and focuses only on native action registration/delivery.

Observable completion:

- healthy menu contains no server implementation language;
- idle/recording/processing/error states are coherent;
- recording menu actions operate while the main window is hidden;
- quick-note composer works without opening the full workspace;
- native hotkey conflict/failure is visible and recoverable rather than silently ignored.

### Lane E — derived notes

MM-4 begins once MM-1 contract is stable and can run in parallel with MM-3/MM-6/MM-7.

Write boundary:

- structured notes / meeting preparation / provenance tests;
- no recording-time UI or shell work.

## Integration points

### I1 — contract freeze

MM-0 defines one canonical note payload, timestamp rule, revision semantics and source kind. Parallel lanes may not invent local variants.

### I2 — API convergence

MM-1 exposes the real endpoints/types; MM-2/MM-3 replace fixtures without changing product behavior.

### I3 — shared composer semantics

Overlay and menu-bar quick-note surfaces share action semantics, keyboard behavior and persistence flow. They may render in different containers but do not maintain separate business logic.

### I4 — shared timeline/provenance

MeetingDetail and Prepare notes consume the same durable user-note source identity. UI ordering and AI provenance must agree.

### I5 — native shell

Menu-bar and hotkey actions call canonical recording/screenshot/note commands. They never mutate storage directly.

## Failure and recovery contract

- Note-anchor failure: keep recording running; show “Couldn’t start note” with retry.
- Save failure: keep text in the composer and allow retry/copy; never show saved state before commit.
- App/window close while typing: unsaved text may be lost in v1; no false saved state.
- Duplicate request/reconnect: return the same committed note.
- Edit conflict: preserve both current server value and user's draft for explicit resolution.
- Delete failure/Undo failure: retain note and show recoverable error.
- Recording stops while composer is open: allow commit only if the canonical note anchor belongs to that just-stopped recording and the store is still accepting the bounded final note operation; otherwise preserve draft and explain.
- Screenshot failure does not affect note capture; note failure does not affect audio/screenshot capture.
- Menubar cannot reach canonical state: show one recovery action; do not invent local state.

## Accessibility / adaptive behavior

- Note action and composer are fully keyboard reachable.
- Focus moves into the note field when opened and returns to the invoking control after save/cancel.
- Success/error announcements are semantic, not color-only.
- Compact overlay keeps Stop and audio health higher priority than note/screenshot feedback.
- Menu actions use native macOS naming/order where practical.
- Menu-bar icon should move toward a template image/SF-symbol-compatible treatment rather than emoji-only status, preserving dark/light-mode legibility.
- Reduced motion rules from the existing UX contract remain unchanged.

## Native hotkey direction

Replace `pynput`/Accessibility as the normal owner for core global meeting hotkeys when a native registration path is proven on supported macOS versions.

Requirements:

- preserve existing documented shortcut behavior unless product review deliberately changes it;
- registration failure/collision is detectable;
- no Accessibility permission is requested solely for these core shortcuts;
- handler dispatches onto the canonical app/main-thread action boundary;
- unregister cleanly on shutdown;
- no synthetic keypress is needed for Start/Stop, Add note or Take screenshot;
- keep Accessibility only for features that genuinely require accessibility automation.

A small native/Carbon registration owner is preferable to broad keyboard interception. The exact implementation belongs in MM-7 after the action contract is stable.

## Validation by slice

MM-0:
- contract/schema tests only;
- no behavior claim.

MM-1:
- STRONG because it changes recording persistence/data lifecycle;
- focused unit/API/restart/idempotency/conflict/delete tests;
- privacy/logging assertions.

MM-2:
- component/browser tests for composer interaction and states;
- compact-width visual/media evidence at integration.

MM-3:
- deterministic temporal-placement tests across long transcript turns, silence, same-timestamp notes/screenshots and pagination;
- edit/delete/seek browser journey;
- accessibility semantics.

MM-4:
- source-boundary/provenance tests;
- preparation input-identity invalidation tests;
- confirm `user_note` cannot silently become spoken/decision evidence.

MM-5/MM-6/MM-7:
- deterministic shell/action tests where possible;
- packaged-app smoke when selected;
- REAL_ENVIRONMENT at release for native menu placement, focus, global shortcut delivery/collision, Spaces/fullscreen and interaction while Zoom/Meet/Teams owns focus.

MM-8:
- repository selector on exact head/base;
- full diff inspection;
- affected FULL_MEDIA journey:
  recording -> add note -> screenshot -> Stop -> Meeting -> timestamped note/screenshot -> seek -> edit note -> Prepare notes with provenance;
- menu-bar journey:
  hidden main window -> Add note -> save -> screenshot/Stop -> open resulting Meeting;
- required packaged/build gates selected by repository policy;
- update durable docs before integration.

Do not claim target-Mac usability/hotkey PASS from synthetic/browser evidence.

## Current executable slice

`MM-0`

Acceptance:

- note contract and timestamp rule are represented in executable schemas/fixtures;
- no new persistence abstraction is introduced;
- existing screenshot provenance/capture invariants remain intact;
- parallel lanes have non-conflicting write ownership;
- exact branch/base identity is refreshed before implementation begins.

Validation:

- focused schema/contract tests selected by the changed files;
- documentation/context verification if required by repository routing.

## Durable documentation destinations

On integration, transfer only current truth:

- `design/ux-contract.json`: add user-note/Moments recording and review semantics, menu-bar user-facing hierarchy and critical journey if materially changed.
- `docs/features/*`: durable user-visible behavior if the existing feature documentation owner requires it.
- `docs/architecture.md`: only if RecordingStore/native-shell ownership changes materially.
- `docs/current-state.md`: integrated capability and remaining REAL_ENVIRONMENT obligations.
- tests/contracts: executable truth for timestamp/provenance/persistence.
- existing screenshot workstream: retain screenshot-specific contract; do not duplicate its persistence rules here.

Delete this workstream by default after durable truth and deferred obligations are transferred.

## Resume checkpoint

Base at plan creation:

- target branch: `dev`;
- base commit: `271d5b6b8b01a97097909dab8a620b98f391bbfa`;
- work branch: `work/meeting-moments-notetaker-menubar`.

Confirmed facts:

- RecordingStore is the canonical recording/artifact owner.
- Existing screenshot flow already persists manual screenshots and projects them as timestamped Key Moments.
- Existing UX contract forbids ASR/LLM/VLM during recording.
- Current menu bar exposes implementation-facing “server” state and record/stop/copy actions.
- Current global meeting shortcuts are implemented through `pynput` and gated by Accessibility permission.
- The existing screenshot workstream requires explicit display selection and prohibits silent display switching.

Unresolved implementation questions to settle inside MM-0, without reopening product intent:

- exact wire name for note source kind and note revision field;
- exact RecordingStore manifest filename/schema version;
- smallest capture-clock API needed to anchor composer-open time;
- whether bounded Undo uses immediate delete or a short reversible tombstone, based on existing store semantics;
- menu-bar quick-note container implementation that best reuses the composer without a second state owner.

Deferred REAL_ENVIRONMENT obligations:

- menu-bar layout/focus behavior in the packaged macOS app;
- global hotkey registration/delivery/collision without Accessibility;
- quick-note panel behavior while another app/fullscreen Space owns focus;
- screenshot action with multiple displays and TCC permissions.

Next discriminating action:

- execute MM-0 against the fresh work-branch head, inspect direct consumers/tests, then unlock MM-1/MM-2/MM-3/MM-5 in parallel.

## Completion

Implementation is complete only when note persistence, overlay capture, Meeting projection, preparation provenance and menu-bar actions agree on the same contract.

Integration is complete only when exact-head/base validation, affected FULL_MEDIA journeys, durable docs and packaging-selected gates agree.

Release readiness still requires applicable REAL_ENVIRONMENT macOS evidence. Product success remains unknown until the flow is observed to be faster/easier than leaving the call context to take notes elsewhere.
