# Meeting-first UX consolidation — navigation, library and saved Meeting

Status: ACTIVE (planning baseline; implementation slices not yet integrated)
Base: `dev` @ `20795b9e440efaf8b4d9817c3a13c9e2916acdda` (2026-10-26)
Product / delivery / validation / execution: PRODUCT_FEATURE / ITERATION; risk-selected SCOPED for isolated routes, STRONG when shared navigation/meeting contracts or recovery changes; REMOTE_AUTOMATED for unavailable deterministic Mac/browser gates, REAL_ENVIRONMENT for subjective macOS usability/TCC when materially affected. Integration always uses repository selector, affected FULL_MEDIA UX journeys, exact head/base evidence.

## User job and scope

A privacy-conscious professional wants to **find one saved meeting, understand what happened, verify the source, take the next action and return to the previous context** without choosing among competing recording/transcript/analysis workspaces. Normal recording remains a one-action local-first flow; saved Meeting is the primary object.

Desired outcomes:
1. One predictable library entry point for today's, recent, all and archived meetings; full-archive search remains bounded and local.
2. Any linked recording/transcription/analysis opens **one canonical saved Meeting**; independent imported text and expert-only tools stay reachable separately.
3. Ready notes and synchronized transcript/audio/moments are easy to scan; errors, partial notes and provenance are not hidden.
4. Projects provide a scoped view onto the **same** meeting rather than a second meeting detail; Back restores project/filter context.
5. Job progress is discoverable globally and contextual inside its meeting, with a single job state owner.

Non-goals: brand rework, changing ASR/LLM/diarization engines, replacing storage, altering run history/IDs, automatic screenshots or recording, making visual AI mandatory, adding cloud, removing experts' file import/merge/split or diagnostic controls, macOS packaging changes.

## Product assumptions and risks

- VALUE: redundant routes increase hesitation and hide notes. Falsify with time-to-find and time-to-evidence comparisons, not screenshot aesthetics.
- USABILITY: `Today` and `Meetings` represent the same core collection at different filters; confirm people retain quick daily review. Proposed navigation is `Meetings` + `Projects` with persistent New Meeting, global search and secondary activity indicator; **this is a proposal** until a tested implementation reconciles `design/ux-contract.json`'s current Today/Projects contract.
- FEASIBILITY: legacy `recording/:id`, transcript-result views and meeting tab panes use different state/routes. Keep IDs and back/forward/deep-link compatibility; do not reinterpret arbitrary imported text as a saved Meeting.
- VIABILITY: preserve discoverability of all paid/useful power-user capabilities and macOS-native workflow. No migration/data loss.
- PRIVACY/RELIABILITY: no remote fallback, new telemetry, transcript in logs/URLs, hidden capture, status fiction, stale write or rollback regression. Search stays in canonical local FTS5/archive owner. Never claim representative target-Mac validation from a browser fixture.

## Current confirmed inventory (audit @ base)

| Experience | Owners | UX duplication / preservation requirement |
| --- | --- | --- |
| Workspace navigation | `frontend/src/App.tsx`, `workspace.css` | Primary Today/Projects/Activities with contextual recording/transcription/analysis routes; avoid two active navigation models. |
| Today and library | `DashboardPage.tsx`, `MeetingListDialog.tsx`, `MeetingSearchDialog.tsx` | Separate recent-list, archive-list and full-text search entry points. Preserve bounded paged search and archive actions. |
| Project | `ProjectsPage.tsx`, `ProjectSidebar`, `InsightDetailDialog` | Timeline / summary / actions / decisions / risks are valid project context, not a second meeting detail. |
| Saved Meeting | `MeetingDetailPage.tsx`, `TranscriptTextView`, `StructuredNotesEditor`, `SpeakerDiarizationEditor` | Canonical detail already exists; tab/layout and hardcoded return to Today need attention. Preserve notes revisions, timestamped moments, playback and speaker undo. |
| Legacy recording detail | `RecordingPage.tsx` under `#recording/:id` | Audio, transcript and analysis card duplicate Meeting; preserve legacy deep links until migration tests prove safe. `#recording/auto/:token` must continue the capture path. |
| Transcript tools | `TranscriptionPage.tsx`, `ResultsStep.tsx` | Wizard/alternate transcript+analysis useful for independent imports, rerun, merge/split; linked meeting should have a canonical review destination. |
| Analysis tools | `AnalysisPage.tsx`, Meeting analysis tab | Saved-meeting analysis belongs beside source material; standalone text analysis remains separate. |
| Activities | `ActivitiesPage.tsx`, `MeetingProcessingStatus.tsx` | Different scopes legitimate but should share lifecycle semantics. |

## Target information architecture and critical journey

`Meetings (Today filter | Recent | All | Archived + search)` → `Saved Meeting` ↔ `Project`; `+ New Meeting` is global. Contextual `Import`, `Transcription tools`, `Analyze`, `Speakers`, `Benchmark`, `Settings/Diagnostics` do not become primary destinations. Activity indicator stays globally available.

Saved Meeting hierarchy:
- Essential: title, origin/project, truthful processing state, audio transport, ready notes, decision/actions with anchors and readable synchronized transcript.
- Contextual: user notes/screenshots at exact capture timestamps, speaker name correction, review related evidence, Ask/analysis when explicitly invoked.
- Advanced: retranscription, Community-1 preview/apply/rollback, A/B diarization benchmarking and run history.
- Diagnostics: job IDs, backend/model internals, error detail, resources; never mask a user-recoverable error behind the drawer.
- Responsive: parallel note/transcript panes on wide desktop; consistent semantic navigation and focus/reading order on narrow WKWebView; no forced two-column squeeze.

Critical journey: `open app → filter/search library → open meeting → review note → seek cited audio/transcript → return to same list/project selection`. Alternate: `New Meeting → Record/Stop → Prepare notes → Meeting`. On failed/cancelled job: keep original content, show error and retry in place.

## Parallel work graph

States: READY / ACTIVE / BLOCKED / DONE. Parallel means non-overlapping **write ownership**, not competing edits to shared `App.tsx` or `design/ux-contract.json`.

| ID | State | Independently observable deliverable | Owning files (write boundary) | Dependency |
| --- | --- | --- | --- | --- |
| UX-0 | ACTIVE | Audited plan, acceptance and sequencing in this document | `docs/workstreams/meeting-ux-consolidation.md` | Base dev |
| UX-1 | ACTIVE | Legacy saved-recording route resolves to Meeting while `recording/auto` stays canonical New Meeting; saved output opens Meeting | `frontend/src/App.tsx`, `frontend/src/pages/RecordingPage.tsx`, route contract tests | Base dev |
| UX-2 | ACTIVE | Recording-linked transcription results prominently return to saved Meeting, including optional notes CTA; unlinked input retains expert analysis | `frontend/src/pages/transcription/components/ResultsStep.tsx`, transcript workflow tests | Base dev |
| UX-3 | READY | A single full-archive library surface for local search/filter/archive, including today/recent; no full transcript loading in UI | `DashboardPage.tsx`, `MeetingListDialog.tsx`, `MeetingSearchDialog.tsx`, archive search tests | UX-0 product decision; coordinate navigation contract with UX-5 |
| UX-4 | READY | Unified saved Meeting content hierarchy, synced audio/note/transcript/moments and speaker tools via progressive disclosure | `MeetingDetailPage.tsx`, meeting semantic components, relevant browser journeys | UX-1 and explicit responsive/content decision |
| UX-5 | READY | Stable project-origin return, selected project and filter/deep-link restoration; avoid per-page improvised history state | canonical shell route owner (`App.tsx`) + `ProjectsPage.tsx`, targeted tests | UX-1; serialize with UX-3 shell integration |
| UX-6 | READY | Global activity status as secondary utility and accessible in-context progress, without a second job store | `ActivitiesPage.tsx`, `MeetingProcessingStatus.tsx`, `App.tsx` after UX-5 | UX-5 (shared shell owner) |
| UX-7 | READY | Retire remaining duplicate legacy entry points **only after** use-site census; unify notes/analysis/transcript defaults and finish documentation | `RecordingPage.tsx`, `AnalysisPage.tsx`, `TranscriptionPage.tsx`, `design/ux-contract.json`, `docs/features.md`, README usage, e2e | UX-3..6 |

Early-convergence rule: UX-1 and UX-2 start in parallel directly from exact `dev`. Merge/rebase only after required evidence. UX-3 and UX-4 can run concurrently with disjoint files after UX-1 stabilizes; UX-5/6 own shell changes sequentially to avoid hidden coupling. Do not stack every feature PR or refactor backend to solve UI duplication.

## Incremental checkpoints and acceptance

1. **Compatibility slice (UX-1, UX-2):** Old `#recording/{id}` (not auto token) and saved transcriptions reach one Meeting; imports without recording still work; no new user-facing technical decision. Test direct deep-link, saved recording, imported transcription, round-trip and cancellation.
2. **Library slice (UX-3):** One obvious collection; same search results from keyboard `⌘K`, all and archive; bounded server-side paging and query cancellation; no data duplication. Distinguish searchable content, list filters and archived status; screenshot / FULL_MEDIA on wide and compact.
3. **Meeting slice (UX-4):** Ready notes first when applicable; verified anchors keep seek behavior; manual notes/screenshots edits, speaker attribution/apply/undo, partial analysis and errors remain recoverable. Check keyboard tabs, VoiceOver labels, reduced motion and small window.
4. **Context slice (UX-5/6):** Meeting Back restores previous project/time filter or library search; browser back/forward/direct URLs remain coherent. Activity can be reached from all normal surfaces, links to canonical Meeting, and progress does not suggest work already finished.
5. **Consolidation (UX-7):** Remove obsolete route/page only after finding zero direct consumers other than an explicit compatibility redirect; regressions and negative cases pass; update design contract, affected feature docs and README usage.

Outcome measurement, proposed baseline+comparison: attempts/clicks and elapsed time to find a prior meeting; note→source-seek task completion; successful return-to-project/context; percentage of normal tasks requiring a wizard; zero duplicate canonical meeting views. Record measured values rather than inventing thresholds.

## Evidence, integration and rollback

- For each slice: inspect direct consumers and tests first; use repository-owned `scripts/select_validation_profile.py` with exact base/head/stage and do not undercut required gates. Early source-local checks target `frontend pnpm lint`, `pnpm exec tsc --noEmit`, affected Python contracts and relevant browser journeys.
- At PR→dev: exact head/base, full diff, updated canonical docs, required selector gates and affected UI `FULL_MEDIA` on eligible automated Mac/browser path. GitHub source Actions do not build apps/upload media. Missing deterministic tool execution is REMOTE_AUTOMATED pending, never an invented PASS or delegated manual check.
- At dev→main: RELEASE/FULL and applicable REAL_ENVIRONMENT target Mac evidence remain mandatory. No claim of complete product success from automated delivery alone.
- Keep individual slices reviewable and revertible; do not migrate transcript/recording IDs, rename persistent owners or delete finalized artifacts. Protect original texts/times, screenshot provenance and version-checked speaker rollback.
- Owner for resume checkpoint: **this file only**. Before resuming refresh head/tree/base, branch/PR outcomes, failures and next proof. Transfer final UX rules into `design/ux-contract.json` and affected canonical owners before deleting the workstream plan.

## Resume checkpoint — initial

Source: `dev` @ `20795b9e`; UI code owns routes in `App.tsx`, detailed Meeting in `MeetingDetailPage.tsx`, and `ResultStep` still has independent linked-recording results. Files and tests inspected: workspace-coherence, archive search, transcription workflow. No exact-head deterministic or representative Mac evidence from this planning baseline. Initial parallel tasks UX-1 / UX-2 are implementation candidates; merge readiness and usability are **not established**.
