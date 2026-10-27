# Meeting-first UX consolidation — navigation, library and saved Meeting

Status: ACTIVE — UX-0/1/2/3/5/6 integrated; UX-4/7 remaining: canonical Recording parity and target-Mac usability. Wave 3 adds source tracks/quality and optional local Audio Intelligence to Meeting.
Latest integration checkpoint: `dev` @ `83d70c7c1102fc44662d9e9a1bc1d19d60c5a89e` (2026-10-27, PR #156).
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

- VALUE/USABILITY: duplicate views obscure meeting notes and old decisions; compare find-meeting/seek-source completion with the current flow. Retain fast Today access.
- FEASIBILITY: preserve recording/transcription IDs, independent imports, deep links, browser history, complete-text local search, note revisions, timestamps, audio seek and Community-1 rollback.
- VIABILITY: preserve expert tools without imposing technical choices on ordinary recording.
- PRIVACY/RELIABILITY: no remote fallback, new telemetry, implicit capture, leaked transcripts or hidden errors; the existing local FTS5 owner stays canonical.
- IA decision: `Meetings + Projects` is now the integrated primary navigation; Today is a quick view, All is the library destination, and Activities is a secondary utility in `design/ux-contract.json`.

## Canonical ownership

`App.tsx` owns routes and compatibility. `MeetingDetailPage.tsx` owns saved Meeting and advanced tools. `MeetingsPage.tsx`, `DashboardPage.tsx` and `MeetingSearchDialog.tsx` share bounded local FTS5. `ProjectsPage.tsx` scopes the same Meeting. `AnalysisPage.tsx`/`TranscriptionPage.tsx` retain independent imports. `useActivities` projects one canonical job store. Legacy `RecordingPage.tsx` still owns editable title/project and redundant capture form; verify remaining route/consumer parity before deletion.

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
| UX-0 | DONE | Audited plan, acceptance and sequencing in this document | `docs/workstreams/meeting-ux-consolidation.md` | Base dev |
| UX-1 | DONE | Legacy saved-recording route resolves to Meeting while `recording/auto` stays canonical New Meeting; saved output opens Meeting | `frontend/src/App.tsx`, `frontend/src/pages/RecordingPage.tsx`, route contract tests | Base dev |
| UX-2 | DONE | Recording-linked transcription results prominently return to saved Meeting, including optional notes CTA; unlinked input retains expert analysis | `frontend/src/pages/transcription/components/ResultsStep.tsx`, transcript workflow tests | Base dev |
| UX-3 | DONE | A single full-archive library surface for local search/filter/archive, including today/recent; no full transcript loading in UI | `DashboardPage.tsx`, `MeetingListDialog.tsx`, `MeetingSearchDialog.tsx`, archive search tests | UX-0 product decision; coordinate navigation contract with UX-5 |
| UX-4 | ACTIVE | Unified saved Meeting content hierarchy, synced audio/note/transcript/moments and speaker tools via progressive disclosure | `MeetingDetailPage.tsx`, meeting semantic components, relevant browser journeys | UX-1 and explicit responsive/content decision |
| UX-5 | DONE | Stable project-origin return, selected project and filter/deep-link restoration; avoid per-page improvised history state | canonical shell route owner (`App.tsx`) + `ProjectsPage.tsx`, targeted tests | UX-1; serialize with UX-3 shell integration |
| UX-6 | DONE | Global activity status as secondary utility and accessible in-context progress, without a second job store | `ActivitiesPage.tsx`, `MeetingProcessingStatus.tsx`, `App.tsx` after UX-5 | UX-5 (shared shell owner) |
| UX-7 | ACTIVE | Retire remaining duplicate legacy entry points **only after** use-site census; unify notes/analysis/transcript defaults and finish documentation | `RecordingPage.tsx`, `AnalysisPage.tsx`, `TranscriptionPage.tsx`, `design/ux-contract.json`, `docs/features.md`, README usage, e2e | UX-3..6 |

Converge early on disjoint owners; the shell and shared Meeting component are serialized. UX-6 and UX-7 must preserve exact-head validation.

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

## Integration checkpoints — 2026-10-27

- PR #155 (`88e00ce`): Meetings library and global Activities, removed duplicate list.
- PR #156 (`83d70c7`): library retry/compact layout, accessible notes→source focus, linked expert analysis→Meeting. Exact-head source/browser FULL_MEDIA PASS.
- Wave 3: local audio metrics on explicit Meeting disclosure, source tracks and quality in advanced details. Preserve no eager fetch, mock attribution and previous recording IDs. Old Recording page deletion waits for title/project and consumer parity; native WKWebView/VoiceOver/outcome evidence remains pending.

## Resume checkpoint — 2026-10-27

Base: `dev` `83d70c7`. Wave 3 branch `ux/meeting-recording-details-parity`: source tracks, quality and lazily loaded Audio Intelligence. Integration pending; real target-Mac usability/VoiceOver and legacy Recording removal still open.
