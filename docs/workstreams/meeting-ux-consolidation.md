# Meeting-first UX consolidation — navigation, library and saved Meeting

Status: ACTIVE — canonical Meeting routing, unified search first slice, notes/transcript companion and origin-preserving Projects return integrated; remaining UX-3/4 refinements, UX-6/7 pending.
Latest integration checkpoint: `dev` @ `f9ff980dcdbcc1083a8a4dc50b023b7f5c0e61b1` (2026-10-27).
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
- IA decision: propose `Meetings + Projects` with global New Meeting/search/secondary activities; the current `design/ux-contract.json` still declares Today/Projects until user-facing validation and integration.

## Current verified ownership (audit @ base)

- Navigation + legacy `recording/:id` route: `App.tsx`; canonical saved Meeting: `MeetingDetailPage.tsx`; old detail also lives in `RecordingPage.tsx`. Preserve `recording/auto/:token` capture handoff.
- Today/list/search/archive entry points: `DashboardPage.tsx`, `MeetingListDialog.tsx`, `MeetingSearchDialog.tsx`; retain bounded local server-side FTS5 paging, cancellation and archive recovery.
- Projects + insights: `ProjectsPage.tsx` and workspace components; project filters differ legitimately from global notes, but must not create another meeting detail.
- Expert input/results: `TranscriptionPage.tsx`, `ResultsStep.tsx`, `AnalysisPage.tsx`. Preserve independent import, export, merge/split, advanced rerun and unlinked-text analysis.
- Canonical notes, timestamps and diarization: `TranscriptTextView`, `StructuredNotesEditor`, `SpeakerDiarizationEditor`, `CommunityOneReviewPanel`; protect snapshot undo, source anchors and speaker provenance.
- Progress: `ActivitiesPage.tsx`, `MeetingProcessingStatus.tsx`; display distinct global/contextual views of the same jobs.

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
| UX-3 | ACTIVE | A single full-archive library surface for local search/filter/archive, including today/recent; no full transcript loading in UI | `DashboardPage.tsx`, `MeetingListDialog.tsx`, `MeetingSearchDialog.tsx`, archive search tests | UX-0 product decision; coordinate navigation contract with UX-5 |
| UX-4 | ACTIVE | Unified saved Meeting content hierarchy, synced audio/note/transcript/moments and speaker tools via progressive disclosure | `MeetingDetailPage.tsx`, meeting semantic components, relevant browser journeys | UX-1 and explicit responsive/content decision |
| UX-5 | DONE | Stable project-origin return, selected project and filter/deep-link restoration; avoid per-page improvised history state | canonical shell route owner (`App.tsx`) + `ProjectsPage.tsx`, targeted tests | UX-1; serialize with UX-3 shell integration |
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

Source: `dev` @ `f9ff980d`. PR #145 integrated legacy route alias with browser FULL_MEDIA; PR #149 integrated linked transcript results, one local Active/Archived search dialog and synchronized Notes/Transcript companion with INTEGRATION/SCOPED source and browser FULL_MEDIA; PR #150 integrated origin-aware Project Back and preserved local UI filters with the same automated gates. PR #146–148 were superseded by #149 and closed unmerged. UX-3 remains ACTIVE for destination-level library IA and UI polish; UX-4 remains ACTIVE for deeper content hierarchy/adaptive/accessibility review. UX-6 status utility and UX-7 legacy entry cleanup are READY. Automated integration proven only; representative packaged WKWebView / VoiceOver subjective evidence remains unclaimed. Next action: shape the remaining library destination and contextual Activities shell without duplicating search or job owners.
