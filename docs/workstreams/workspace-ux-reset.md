# ClosedRoom — meeting-first UX reset

Status: active
Owner: product UX, frontend workspace, local workspace read model
Read when: changing core recording / saved Meeting / Projects journeys or their loading and navigation behavior
Base: `dev` at `bb38105620e3547b0d28b541d6d4b0cec968945f` (2026-11-13); refresh before implementation/integration.

## User and desired outcome

A privacy-conscious macOS professional records a call, writes timestamped notes and takes intentional screenshots without leaving the call, transcribes and attributes speech afterward, requests a repeatable analysis outcome, then finds the recording by project in seconds. The same Meeting is the canonical object throughout.

Outcome: an obvious meeting-first navigation, no redundant destinations/actions, no simulated processing, immediate navigation with progressive local content, reliable capture/undo, and one consistent visual/interaction language. **User-visible processing only when work is actually happening.**

Non-goals: cloud inference or silent remote fallback; new recording, transcription, speaker or job persistence owners; deleting advanced features; rewriting finalized artifacts or existing analysis; replacing the existing brand; importing competitors' code without license review.

## Evidence: current UX problems and owner

Screenshots supplied 2026-11-13 show a full-screen Projects loading card with a fixed 62%, four metric tiles, a large unavailable digest, an empty actions block and empty decisions/risks before the first Meeting. Left project navigation consumes its own tall scroll column, and there are multiple time filters.

Code audit (`dev`):
- `frontend/src/pages/ProjectsPage.tsx:154-178`: `listProjects()` on every mount, full-page loading guard; no instant cached view. `:342-355` passes a hard-coded `progress={62}`; `:535-550` passes `progress={72}` to an unrelated project digest animation.
- `ProjectsPage.tsx:323-340`: the "Generate project situation" action uses a fixed 850ms timeout and pre-existing local digest items, not a real new analysis. The copy/progress must not imply an inference task.
- `ProjectsPage.tsx:461-714`: four KPIs and multiple empty insight panels precede the Meeting timeline, which is clipped to the first three items unless manually expanded.
- `src/local_asr_server/routers/helpers.py:139-184`: `GET /v1/projects` loops over up to 999 recordings and reads transcription, runs by recording, runs by transcription and preparation jobs per recording; plausible N+1 latency source. Measure, do not assert latency impact without profiling.
- `frontend/src/App.tsx:267-312,546-550`: route switch mounts/unmounts page components and uses lazy page chunks. `frontend/src/components/workspace/MeetingSearchDialog.tsx:82-131` introduces 180ms debounce even for an initial unfiltered archive load.
- Existing `docs/workstreams/meeting-ux-consolidation.md` and `design/ux-contract.json` already specify a canonical Meeting and shared local library; this reset must **finish and simplify** that ownership, not invent a competing architecture.

## Competitive research (patterns only)

- Granola: meeting list/notes first, folders/spaces and contextual chat; official guide https://docs.granola.ai/help-center/getting-started/granola-101
- Fireflies: combined meeting notes/transcript/audio/actions with a search-to-timestamp path; https://guide.fireflies.ai/articles/6653885315-learn-about-the-fireflies-notepad
- Fathom: live scratchpad to unified post-meeting view; https://www.fathom.ai/whats-new
- Code references to inspect selectively: Meetily https://github.com/Zackriya-Solutions/meetily; Meet2Notes https://github.com/estebanstifli/Meet2Notes; MeetMind https://github.com/aslahtp/meetmind. Verify license and source owner before reuse. No code/network dependency in the product.

## Product decision / IA

Primary root: `Meetings` (Today/All/Archived, fast local search); `Projects` (grouping/filtering of the **same** saved Meetings). Persistent `New Meeting` action. `Activities` and `Settings` stay secondary.

Primary journey:
`Open app -> locate Meeting or Project -> open saved Meeting -> read notes/transcript -> seek source audio/screenshot -> review actions/decisions -> return to same context`.

Capture journey:
`New Meeting -> choose optional project -> readiness -> Start -> note/screenshot during recording -> Stop -> saved Meeting -> Transcribe -> review speaker labels -> run selected analysis outcome`.
Capture status must be truthful for waiting/permission/device switch/stop/finalization; note/screenshot persisted before success. No forced ASR/diarization without a user choice or an explicit settled default.

Projects default: `Project title + scoped search/filter -> meeting list` in the first viewport. Meeting rows show date/title/duration/processing/readiness and one primary Open action; rename/move/archive contextual. Insight digest/actions/decisions/risks are a secondary `Project insights` section, hidden when all empty or represented by a single compact explanatory state. One project time range controls the entire page; no independent action-only range.

Saved Meeting: title, project and local activity status always visible. Normal work is `Notes | Transcript | Voices | Analysis` under one identity with consistent tabs/CTAs; screenshot and manual note evidence is visible in the appropriate note/timestamp context. Expert reprocessing/benchmark/providers/diagnostics stay under one Advanced disclosure and never duplicate primary navigation.

## States and performance contract

1. Navigation does not block on unrelated project aggregation or analysis. Render current/snapshot meeting list immediately; background refresh updates only the affected area, with visible, truthful stale/error/retry state.
2. Separate index (project names, counts, recent Meeting metadata) from expensive per-Meeting derived insights where profiling proves a need; prefer one canonical server read projection over N+1 requests and client duplicates.
3. Cache may hold an in-memory view snapshot only, bounded and revalidated; no new persistence, never cache local transcripts in third-party services, and invalidate after recording/project mutations.
4. Real progress is determinate only if backend supplies measured work units; otherwise use an indeterminate status without percentages or invented stages. Never delay a synchronous projection solely to show an animation.
5. Project or Meeting changes cancel/ignore stale async responses; mutation failures preserve inputs; restore origin/selection/filter and scroll/focus when returning.
6. First content should remain useful even when ASR, diarization, model, screenshot enrichment or analytics is pending/failed.

## One layout, responsive semantics

Wide: app rail | optional project list | **meeting list** and, on selection, same canonical Meeting detail. Compact: project picker -> meeting list -> selected Meeting; no squeezed three-column grid. Avoid secondary full-page loader, duplicate action bars, oversize empty-state cards, high-chroma gradients everywhere, tiny all-caps metadata and redundant borders. Use existing `design/brand-kit.json`, semantic controls and tokens; one primary CTA per surface.

## Four independently valuable tracks

| ID | State | Outcome | Write owner | Dependency |
| --- | --- | --- | --- | --- |
| UX-R0 | ACTIVE | Project meeting-first hierarchy, truthful loading and no fake digest delay; browser regression coverage | `ProjectsPage.tsx` and targeted workspace journey | base `dev` |
| UX-R1 | READY | Profile server Projects N+1, implement compact/index + detail projection if warranted, query/coalescing and invalidation evidence | `routers/workspace.py`, `routers/helpers.py`, catalog/read tests | data-contract agreement with R0 |
| UX-R2 | READY | Navigation/visual grammar, one search/list/filter pattern, fast route transitions with selection/focus restoration, bounded query state | `App.tsx`, `MeetingsPage.tsx`, `MeetingSearchDialog.tsx`, `workspace.css` | R0 semantics; serialize shared shell writes |
| UX-R3 | READY | Single reliable capture flow: readiness, notes, screenshots, Stop and recovery; target-Mac audio/TCC evidence separate | `NewRecordingPage.tsx`, `RecordingOverlayPage.tsx`, capture UI tests | canonical capture lifecycle; independent R0 |
| UX-R4 | READY | Coherent saved Meeting defaults; one transcript/voice/analysis flow and an explicit outcome/template selection; no duplicate CTAs | `MeetingDetailPage.tsx`, speaker/notes components, meeting E2E | shared contract audit; independent R0/R3 writing |
| UX-R5 | BLOCKED | Integrated usability, accessibility and latency checks, durable UX contract/feature docs, safe `dev` integration | `design/ux-contract.json`, affected docs and e2e manifest | R0–R4 |

Parallelism: R1/R3/R4 can proceed with disjoint owners; R0 writes Projects; R2 owns App/shared shell only after agreement about project route and filter contracts. No parallel writes to the same file. Release validation is a separate axis.

## Acceptance and evidence

- P0: entering Projects and returning from a Meeting does **not** show the fake 62% multi-step loader; no fixed percentages for synchronous work; the project Meeting list appears before analytics, with all recent meetings discoverable without scrolling through empty tiles.
- P0: zero-analysis projects display meetings and a single truthful compact empty insight state; analysis ready/pending/error are distinct. A newly created or moved Meeting appears after refresh, without assuming cached content is fresh.
- P0: project filtering and selection persist across Meeting -> Back; archive search/direct links/legacy routes remain functional.
- P1: count and instrument local `/v1/projects` database calls and timings at bounded fixture sizes (e.g., 1/25/200), then establish a measured regression threshold from baseline. No fabricated fixed performance promise.
- P1: find a project Meeting, open it, seek an audio/notes timestamp, and return using keyboard and mouse at wide/compact widths; project and global search semantics are consistent.
- P1: one primary Transcribe/Identify voices/Analyze action per eligible saved Meeting state; all outcomes retain provenance, undo and version safety.
- P1: note and screenshot during an active recording survive Stop/reopen; failed captures never show success; switching devices must retain available recording source and report real gaps honestly.
- Validation: `python3 scripts/select_validation_profile.py --base <dev> --head <feature> --stage integration` selects mandatory gates; frontend lint+tsc; backend contract/source tests when changed; `scripts/browser_workspace_coherence_e2e.mjs`, saved Meeting, archive, note/screenshot and recording journeys in FULL_MEDIA when materially affected; exact-head/base preflight and relevant Mac automation. WKWebView/TCC, real physical audio switching, MLX/Metal and VoiceOver user judgement remain RELEASE / REAL_ENVIRONMENT, never inferred from fixtures.

## Product risk and observability

VALUE: faster meeting discovery and fewer duplicated actions; test scripted task success.
USABILITY: first-viewport meeting list, consistent verbs, clear empty/failure states; test three sample projects (empty, one meeting, many).
FEASIBILITY: expensive project aggregation and massive saved Meeting component; profile read path before introducing a new cache/invalidation owner.
VIABILITY: preserve local/offline data and low resource overhead; do not automatically start heavy AI to populate dashboards.
PRIVACY/RELIABILITY: preserve loopback auth, original source audio/transcript/markers, explicit optional storage, cancel/retry and rollback.

No product-success or latency PASS claim until user journey tests and representative measurements exist.

## Checkpoint and next action

Initial checkpoint: `dev` `bb38105620e3547b0d28b541d6d4b0cec968945f`, `main` `7f1136eb6bf7034c56942ae2590b42da881e105a`. Code and screenshots confirm hierarchy and fake progress; measured server timing is unknown. Next: land UX-R0 focused, add DOM+FULL_MEDIA assertion for first-viewport Meeting ordering, then profile server path before optimizing storage/query. Refresh identity before each integration. Transfer final product decisions into `design/ux-contract.json` and update `docs/current-state.md` only when integrated. Delete this workstream after durable convergence.
