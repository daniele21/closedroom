# ClosedRoom · Recording overlay and meeting screenshot experience (design v1)

Status: UX handoff only, not implemented UI or release evidence.
Base: `dev` `bb38105620e3547b0d28b541d6d4b0cec968945f` inspected 2026-11-13.
Design system: `design/brand-kit.json`, `design/ux-contract.json`; the canonical implementation remains `frontend/src/`.

## User and outcome

During a call, the user must write a brief timestamped note or deliberately capture a screenshot without obscuring the conversation or disrupting audio capture. After the call, **every saved screenshot is visible in the saved Meeting's Notes and sources view, even before transcription/AI analysis**. Selecting it reveals a useful thumbnail, exact timestamp, nearby note/transcript context when available and a seek-to-audio action.

### Compact overlay (macOS floating companion)

Default minimal surface, roughly 450 px wide, no sidebar or large recording dashboard. Stable top row: red **REC**, truncated meeting title, truthful recording timer. Second line: microphone / computer source health using text + color, with degraded source recovery affordance. Constant controls: **Add note**, **Screenshot**, **Stop** (distinct destructive styling, explicit finalization). Selected capture display appears in a compact control; show unavailable/permission state rather than falsely enabling screenshot. Counts of saved notes/screenshots remain secondary.

Opening Add note expands the **same overlay**, anchored to the current canonical capture clock, with multiline field, Save, Cancel, keyboard Enter/Shift+Enter and Escape. On submit show Saving, then Saved with Undo **only after the authoritative local API confirms persistence**. Preserve input on failure. Opening Screenshot uses the already selected display and shows Capturing → Saved at timestamp → Undo last; no extra modal after an eligible manual action. An absent selection prompts a single compact display chooser instead. Only one capture and one last-undo action in flight; Stop waits on real local finalization. Hide overlay is not Stop.

Overlay can be repositioned and collapsed without losing note drafts. Avoid taking over keyboard focus while user is in the calling app. Status/controls do not depend on color alone. UI must never claim continuous screen recording or introduce a background VLM/LLM when saving an image.

### Saved Meeting: Notes and sources

One canonical Meeting identity, one player and timestamps. In the Notes context, **screenshots are a first-class section alongside authored notes**, not an unrelated panel below giant analytics blocks and not hidden inside “Visual intelligence”. At desktop width:
- left: user-authored timed notes, prepared notes/actions when available;
- right: **Screenshots (N)** with 2–3 thumbnail items in the first viewport, select one → larger local preview + timestamp/source identity + nearby audio/transcript context + `Go to 06:28`.
- selection keeps the same Meeting, tab and player; seeking the screenshot marker moves the canonical playback clock. A missing transcript says “Transcript not available yet”, without hiding the screenshot.
- grouped similar screenshots can collapse only on explicit user request; manual screenshots remain individually discoverable. No screenshot card pretends to be AI-derived evidence. Explicit distinction between user capture and automatically derived visual insights.

Compact width: same ordered content with screenshot strip below notes (or reachable by a visible anchored subheading), no second persistent sidebar. `Esc` closes preview; focus returns to selected thumbnail. The photo is locally served via existing authenticated thumbnail/image URLs; thumbnail failure shows `Image unavailable · Retry`, not `No screenshots`.

### Visual and interaction contract

Use local brand colors and platform font stack; muted surfaces, a single main action per state, no invented percent/progress, no permanent giant cards. The small overlay is intentionally more compact than the main Meeting workspace.

| State | Observable UX | Recovery |
| --- | --- | --- |
| recording | REC timer + real source health; Note/Screenshot/Stop | source switch warning and permissions route |
| note composing | fixed capture timestamp, unsaved draft and explicit save | close with draft preservation/confirmation |
| note saving | busy only for the local write | keep text + retry |
| screenshot capturing | disable second screenshot until response | failure toast + retry; no success/count |
| screenshot saved | count, time, explicit Undo last | version-checked rollback; no separate new owner |
| no screenshot | small empty screenshot section without blocking notes | explain manual capture in next call |
| screenshot unavailable | thumbnail or source error on only that tile | retry local fetch, never delete records |
| transcript pending | screenshots/notes usable without transcript | context displayed once available |
| stopping | finalize status only while backend is finalizing | recovery if stop/finalization fails |
| navigating | preserve selection, scroll/focus, unsaved note | restore context from canonical owner |

## Existing implementation surfaces / constraints

- `frontend/src/pages/RecordingOverlayPage.tsx` already owns note composer, display selector, screenshot action, last note/screenshot Undo, source-health/status and SSE reconciliation. Redesign this surface, **do not add another capture state machine**.
- `frontend/src/pages/MeetingDetailPage.tsx` already has `screenshots`, `loadScreenshots`, `openKeyMoment`, `keyMomentContexts`, real thumbnails, source validity, and `data-meeting-screenshot-gallery`. Gallery currently exists as an upper standalone section (`~1372`), while the notes+reference transcript are inside the analysis tab (`~1910`): **reposition/recompose**, do not implement a second screenshot fetch or duplicate media state.
- `RecordingNote` and `RecordingScreenshot` APIs and timestamps remain authoritative; no file mutation, no cloud transfer, no silent enrichment.

## Falsifiable acceptance (material UI integration)

1. Small floating overlay screenshot, with Note/Screenshot/Stop all reachable by mouse/keyboard at narrow macOS sizes; source degraded and screenshot permission-failure states visible.
2. Simulated save failure retains text, does not increment counts and offers Retry. Last screenshot Undo removes only confirmed latest capture; Stop never succeeds before local finalization.
3. Saved Meeting with 3 screenshots and no analysis shows all 3 images in the Notes and sources journey without scrolling through unrelated panels. Selecting the second moves playback to its canonical timestamp and displays context if available.
4. Saved Meeting with zero screenshots has a compact truthful explanation; unreadable thumbnail stays listed with Retry; transcript pending does not hide images.
5. The same screenshot provenance/time is used by Meeting Notes, transcript companion and advanced visual enrichment; only one local owner for playback and data.
6. Wide / 900 px / compact, keyboard focus, VoiceOver labels, 200% text scale, reduced motion and no horizontal clipping verified using browser snapshots and affected FULL_MEDIA gates. Final WKWebView/native capture/TCC audio evidence is a separate REAL_ENVIRONMENT requirement.

## Design reference

Eight existing editable high-level concepts: https://www.figma.com/design/VbELzf6PuSKxFbpZzUCBuu (includes prior full recording view but **not** this specific overlay/gallery amendment).

A standalone, local HTML interaction prototype is delivered as a conversation artifact for this design amendment, showing three states: Saved Meeting with 3 selectable screenshots, Compact overlay and Expanded note composer. It is intentionally illustrative and **does not capture, play or store actual meeting data**. Figma Starter call limit prevented updating the existing design file directly on 2026-11-13; do not claim that the amendment exists as editable Figma layers until actually synchronized.
