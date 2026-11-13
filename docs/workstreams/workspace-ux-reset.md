# ClosedRoom — UX/UI meeting-first redesign

Status: ACTIVE — design approved; implementation not yet integrated. Owner: product/front-end. Target: dev.
Resume identity: dev bb38105620e3547b0d28b541d6d4b0cec968945f (2026-11-13); refresh head/base/PRs before work.

## Product outcome and boundaries

A privacy-conscious macOS user can start a reliable call, write notes and take intentional screenshots while recording, transcribe/identify speakers, run an outcome-driven analysis, then find the same Meeting by project or search in a clear, continuous interface. Reduce steps, repeated actions, initial loading and unnecessary cognitive effort. **Meeting is the one canonical user object.**

No cloud inference or silent fallback; no new recording, transcript, screenshot, model, player, speaker or persistence owners; no replacement of source audio/text/timestamps or finalized artifacts; no new UI framework, parallel design tokens, cosmetic AI processing or unlicensed competitor code. Preserve local privacy, loopback auth, explicit optional storage, recoverable edits and screenshot provenance.

Axes: intended product PRODUCT_FEATURE; this plan-only edit PRODUCT_NONE. Delivery ITERATION now, INTEGRATION on each PR to dev, RELEASE only for stable promotion. Validation LEAN for this doc, risk-selected SCOPED/STRONG for implementation, FULL for release. Execution AGENT_LOCAL where equivalent tools exist, REMOTE_AUTOMATED for deterministic unavailable Mac/browser gates, REAL_ENVIRONMENT for installed macOS/TCC/physical audio, VoiceOver and subjective UX. Treat axes independently.

## Designs and current truth

- Eight editable screens: https://www.figma.com/design/VbELzf6PuSKxFbpZzUCBuu — Riunioni; Progetti; Meeting Notes; Voci; Analisi; Nuovo meeting; Registrazione attiva; Progetti compatti.
- Dedicated **compact floating overlay** and **saved Meeting screenshot gallery** are specified in design/overlay-screenshot-ux-v1.md on open PR #210; conversation HTML prototype is illustrative. These changes are NOT yet Figma-editable screens because the Figma Starter limit blocked that addition; synchronize when available, without blocking code delivery.
- dev already contains reliable local source owners for note and screenshot persistence, overlay display selection, note/screenshot undo, Meeting image thumbnails/context, transcription and speakers. Redesign the journey, not storage.
- PR #210 (daniele/workspace-ux-reset → dev) implements first Projects hierarchy/loading changes but is **open, unmerged**. Its branch workstream must converge with this plan rather than establish a second roadmap.
- docs/workstreams/meeting-ux-consolidation.md records earlier integrated UX and legacy-route obligations: preserve them; do not redo integrated UX-0..6. Code + design/ux-contract.json + design/brand-kit.json remain canonical, not Figma.

## Information architecture and approved flows

Primary rail: **Riunioni**, **Progetti**, persistent **Nuovo meeting**. Utilities: Attività, Impostazioni. Opening a Meeting is contextual, not a third root destination. Back restores parent list, search, project selection, filter, scroll and focus.

- **Riunioni:** searchable local archive, recent rows at top, one Open action; status, date, project and duration visible. Empty/archived/filter states concise.
- **Progetti:** project selection → meeting list directly under heading, same global Meeting identities; one time filter, search within project; insight digest/actions/risks below meetings only when present.
- **Capture:** New Meeting → optional title/project → truthful source/permission readiness → Start → compact overlay (REC, timer, mic/system health, display, Note/Screenshot/Stop) → finalization → saved Meeting. Hide overlay never stops recording.
- **Saved Meeting:** one player and four user views: **Note e fonti** (authored notes, generated notes when present, captured screenshots and source timestamps); **Trascrizione** (compact readable conversation); **Voci** (sample, name/merge/exclude, attribution and timeline); **Analisi** (outcome selection, status, results).
- **Screenshot first-class:** every manual image is visible in Note e fonti *without* ASR/AI, with a real thumbnail, selected preview, capture timestamp/display provenance, nearby note/transcript when available and seek in the same player. Similar shots may group only with discoverable “Mostra tutti”; missing thumbnail remains a row with Retry.
- **Analysis:** select “Sintesi e prossimi passi”, “Decisioni e rischi”, or “Domanda personalizzata”, then explicitly start a local analysis. Never confuse visual-only evidence with spoken decisions. Re-attributed voices do not silently rewrite old analyses.

## Independent work graph

| ID / state | Shippable result and single write owner | Dependency |
| --- | --- | --- |
| UX0 ACTIVE | Finish PR #210: ProjectsPage.tsx meeting-first layout, truthful loading, no duplicated CTA, reuse bounded snapshot; preserve source and browser evidence | Existing PR → dev gates |
| UX1 READY | App.tsx + MeetingsPage.tsx + MeetingSearchDialog.tsx: one rail/search/navigation model; fast route change, proper Back and context recovery | UX0 IA agreement |
| UX2 READY | routers/workspace.py + routers/helpers.py: profile /v1/projects (1/25/200 records), remove proven N+1; bounded canonical metadata projection/cache invalidation | UX0 API semantics |
| UX3 READY | MeetingDetailPage.tsx + small extracted presentation components as needed: Note e fonti plus visible screenshot strip/gallery/preview/seek. Reuse current screenshot hooks and player | Existing saved Meeting contract |
| UX4 READY | RecordingOverlayPage.tsx and overlay-specific CSS: compact/expanded control, persistent timer/source health, note composer, selected display, screenshot, Stop/Undo | Existing recorder/screenshot owners |
| UX5 READY | NewRecordingPage.tsx: one Start, readiness/permissions and honest waiting, safe transition to overlay/saved Meeting | UX4 visible state contract |
| UX6 BLOCKED | TranscriptTextView + SpeakerDiarizationEditor: no “Computer” person; mic identity, readable correction/undo. MeetingDetailPage tab wiring serialized after UX3 | UX3 shared parent |
| UX7 BLOCKED | Analysis child dialogs/editors: reusable predefined outcomes and truthful processing. MeetingDetailPage integration serialized after UX3/UX6 | UX3 + UX6 tabs |
| UX8 BLOCKED | Semantic UI components + workspace.css/index.css: consistent controls/type/spacing, 1280/900/640 layouts, light/dark tokens, accessibility, restrained motion | UX1 + UX3 hierarchy |
| UX9 BLOCKED | End-to-end UX convergence: critical journeys, performance, accessibility, source docs, exact-head validation and PR-to-dev integration | affected slices |

**Parallel execution:** UX2 backend, UX3 saved Meeting, UX4 overlay and UX1 shell may proceed on *disjoint files*. UX5 can start with NewRecordingPage after UX4 action contract is settled. UX6/UX7 may prepare child-only pieces in parallel, but only UX3 owns MeetingDetailPage until handoff. UX8 must not write shared CSS while UX1 does. Merge small coherent PRs early; no multi-agent edits on the same file.

## Required interaction states and recovery

- Navigation: preserve previous Meeting rows on return while background local refresh runs; stale/error/retry visible; ignore responses for prior selections. No full-screen fake “62%”/“72%”; real percentage only from measured backend units. Measure first-open latency separately from warm navigation.
- Overlay: displayed REC only after capture-ready; mic/system warnings remain distinct and a device switch never silently discards surviving audio. Notes capture canonical timestamp; Save→persisted confirmation→Undo, draft retained on failure. Screenshot uses explicit selected display; Capturing→backend commit→count/time/Undo, no false success. Stop reports actual finalization; overlay exclusion and display choice remain canonical.
- Saved screenshots: zero images → single compact empty state; unreadable/missing asset → visible placeholder and Retry; transcript unavailable → screenshots still accessible; selected image → local preview and source seek; Escape closes and returns focus.
- Voci: person ≠ source track, manually corrected names don't alter ASR words/times; source/revision-checked preview/apply/undo; source-sensitive analysis marked stale when speaker attribution changes.
- Analysis: queued/waiting/running/failed/ready distinguishable, cancel/retry where supported; no automatic inference on navigation, capture or editing.
- Responsive/accessible: keyboard + VoiceOver semantics, focus return, 200% text, reduced motion, no clipped three-column layout, no tooltip-only or color-only actions.

## Acceptance and validation evidence

| Journey | Concrete evidence required |
| --- | --- |
| Project 0/1/many meetings | Meetings above analytics in first viewport; no fake progress; global/project search and filter/Back survive; profile 1/25/200 latency/read count without invented SLO |
| Library and source | Search matching canonical Meeting ID, open and seek audio, return to same context; no duplicate Transcribe or speaker button |
| Capture and overlay | Real ready/record/stop states; note/screenshot Save failure preserves draft; Undo only persisted marker; display change persists across SSE; Stop drains admitted writes |
| Meeting Note e fonti | With three screenshot fixtures and no ASR, see all images; select second, preview + audio seek to its real time; unavailable image offers Retry |
| Transcript/Voci/Analisi | Current labels visible in transcript, verification and rollback; predefined outcome runs with provenance; old analysis not silently rewritten |
| UI fidelity/accessibility | Browser screenshots + FULL_MEDIA at 1280/900/640, keyboard/focus/zoom/contrast; installed WKWebView, multi-display/TCC/audio and VoiceOver as separate REAL_ENVIRONMENT release proof |

Use repository selector `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration`. Targeted frontend `pnpm run lint`, `pnpm exec tsc --noEmit`, relevant API tests, `scripts/browser_meeting_ui_e2e.mjs`, `scripts/browser_workspace_coherence_e2e.mjs` and repository E2E suites (call-overlay-screenshot-evidence, meeting-moments-notes, archive, speakers). Actual code PRs require **exact head/base, full diff, required selected gates, affected FULL_MEDIA**. Deterministic Mac tests run via repository REMOTE_AUTOMATED workflows if needed, not delegated manually. RELEASE requires FULL and applicable blocking target-Mac physical/TCC/WKWebView evidence; fixture PASS is never physical PASS.

## Resume and durable closeout

**Next:** reconcile #210 with this plan, inspect its exact-head FULL_MEDIA and integrate UX0 only if required gates pass. In parallel start UX2 profiling and UX4 overlay. The redesign is **planned, not shipped**; latency, usability and real hardware outcomes remain unmeasured.

At convergence update design/ux-contract.json, affected docs/features.md or bounded feature owner, docs/current-state.md and executable tests; update design/brand-kit.json only if approved tokens change. Remove temporary workstream after durable truth and deferred release obligations are transferred.
