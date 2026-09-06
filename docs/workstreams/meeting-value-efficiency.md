# ClosedRoom: useful notes, simple journeys and efficient execution

Status: active — PRS-15 integration candidate
Owner: meeting product, canonical job/persistence owners and local runtime
Baseline: dev `a3902f3c`, 2026-09-06.

## Outcome and invariants

Record, prepare useful notes, verify decisions and find them later while the Mac stays usable. PRS-11 through PRS-14 are integrated; PRS-15 is the current integration candidate. No production-model performance or memory gain is claimed without representative evidence.

- Meeting is primary; normal recording requires no technical choice.
- `Prepare notes` is explicit after Stop; `Transcript only` is secondary.
- Reuse valid transcript, then existing notes analysis. Ready notes open first; explicit tab selection wins.
- Audio/transcript survive enrichment failure/cancel. Local-first and explicit cloud opt-in remain unchanged.
- Canonical owners stay unchanged: RecordingStore capture, JobStore durable jobs, CatalogStore persisted runs/indexes, HeavyWorkloadArbiter heavy-work scheduling, runtime services managed cleanup.
- Excluded: rewrite, second scheduler/runtime/index owner, implicit cloud, mandatory visuals, unproven audio strategy.

## Work graph

| ID | Observable outcome | Owner paths/contracts | Depends on | State |
| --- | --- | --- | --- | --- |
| PRS-11 | Fast saved Meeting open | MeetingDetailPage, API client, visual hook | — | DONE |
| PRS-12 | One recoverable Prepare notes action | jobs, analysis/transcription services, Meeting UI | PRS-11 | DONE |
| PRS-13 | Consistent notes with less repeated inference | analysis templates/jobs/service/catalog reads | PRS-12 | DONE |
| PRS-14 | Verify/edit actions and decisions | notes schema/catalog, transcript, Meeting UI | PRS-13 | DONE |
| PRS-15 | Search complete local archive | CatalogStore, workspace/API/UI | — | INTEGRATION |
| PRS-16 | Record safely while AI is busy | RecordingStore, resource policy/arbiter/runtime | — | READY |
| PRS-17 | Coherent macOS workspace | App/pages/components/design contracts | PRS-12,14,15,16 | BLOCKED |
| PRS-18 | Measured release | current-state, benchmarks, target-Mac evidence | selected increments | BLOCKED |

Default sequence: 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17. PRS-15/16 may advance earlier, but shared schema/service/UI edits remain serialized into coherent outcome PRs.

## PRS-11 — integrated

Saved Meeting core content loads independently from diagnostics and visual services. Accessory errors/retries stay local, stale route responses are ignored and terminal reloads are coalesced. Evidence includes focused tests and `saved-meeting-fast-open` FULL_MEDIA. Target WKWebView/TCC fidelity remains release evidence when material.

## PRS-12 — integrated

`Prepare notes` is a durable `meeting_preparation` JobStore parent that composes the existing transcription and analysis jobs. Durable identity covers recording source, effective ASR options and analysis/template identity; valid transcripts skip ASR. Cancel prevents future stages including admission races, restart interrupts incomplete work and explicit resume starts from the first missing stage. Meeting follows the parent SSE, exposes transcript before notes finish and does not promote output from failed/interrupted/cancelled preparation pipelines. Existing expert transcription/analysis APIs remain compatible. Integration evidence included owner/API/persistence tests plus `meeting-preparation-recovery` FULL_MEDIA and packaged-app smoke.

## PRS-13 — integrated shared structured notes

The default notes path now reduces overlapping inference without degrading the logical note views. `meeting_default` with no explicit `analysis_types` executes one internal `meeting_notes_shared` v2 analysis job instead of four overlapping physical jobs; `meeting_deep`, explicit analysis types and expert single analyses remain unchanged.

The canonical result is `closedroom.meeting_notes` schema v2 with a `generated` boundary containing summary, actions, decisions and risks. Every non-empty generated claim requires a canonical transcript segment reference with timing/speaker metadata when available. One persisted v2 run is projected at read time into stable `meeting_brief`, `action_items`, `decisions` and `risks_blockers` views without synthetic jobs or rows; old persisted v1 runs continue to read unchanged.

Structured cache identity includes transcript segment ids/timing/speaker/text. Short inputs use one extraction; long inputs use bounded source-aware chunks plus bounded aggregation, and oversize input fails explicitly rather than truncating. Source refs cannot escape the chunk/aggregation evidence supplied to the inference. The internal shared template remains hidden from the public template picker and `HeavyWorkloadArbiter` remains the only heavy-work scheduler.

Integration evidence covered schema/projection/cache/long-input/source-boundary tests, existing analysis/preparation suites, frontend deterministic checks, `meeting-preparation-recovery` FULL_MEDIA and selector-owned STRONG/package gates. Production model quality/latency/RSS and target WKWebView/TCC fidelity remain release deltas unless a comparable integration baseline exists.

## PRS-14 — integrated verifiable, editable notes

Actions and decisions now carry stable source-anchored identity, immutable generated content and a persisted user-edit overlay. Corrections survive restart; regeneration creates a new revision and carries edits only when safe. Changed or removed generated items surface explicit `generated_changed` / `item_missing` conflicts rather than silent remapping. PATCH uses the generated fingerprint for optimistic concurrency, discard is explicit, and source evidence remains reachable from current and retained conflict items.

Integration evidence included domain identity/overlay/revision tests, real CatalogStore reopen persistence, API stale-generation/rebase/discard coverage, frontend contract checks, the `meeting-note-edit-revision` FULL_MEDIA journey and packaged-app validation. Target WKWebView focus/accessibility and production-model behavior remain release confirmation when material.

## PRS-15 — complete search, bounded archive — integration candidate

Goal: make every persisted Meeting discoverable from the normal search surface without loading the whole archive or relying on compact preview text in React.

Implementation candidate:
- `CatalogStore` remains the canonical persistence owner. `CatalogMeetingSearch` creates a derived FTS5 projection inside the same `closedroom.db`; there is no second database, scheduler or archive owner;
- SQLite triggers on canonical recording, transcription and analysis-run tables only mark affected recording ids dirty. Before a search, dirty ids are refreshed transactionally from current canonical rows, including the latest visible transcript and latest completed analysis revision per type;
- the first search backfills the existing catalog once. A schema marker plus row-count healing handles restored/copied databases; subsequent mutations stay incremental through the dirty set;
- user query text is tokenized as plain bounded text rather than accepted as raw FTS syntax. Search is capped at 12 terms, 64 characters per term and 50 results per page;
- `GET /v1/meetings` keeps the legacy recent-list response when `q` is omitted. Supplying `q` (including an empty string) opts into complete paged archive search with stable `page`, `limit`, `total`, `has_more` and optional exact project filtering;
- search result ordering is relevance then creation time/id for text queries, and creation time/id for blank archive paging;
- the Today page no longer filters its compact recent data when the user searches. `⌘K` opens a dedicated archive dialog that requests bounded pages, handles stale requests/loading/error/empty states, and preserves the query across source navigation;
- demo mode remains local to deterministic demo fixtures; production search remains server-side and local-only;
- FTS5 absence is an explicit 503 capability failure, never a fallback to whole-archive Python/React scanning. Packaged-app smoke probes the authenticated search endpoint inside the frozen runtime so hosted source Python cannot hide a packaging gap.

Acceptance before merge:
- a meeting outside the old recent/preview limits is found by title, project, full transcript or current notes;
- blank-query paging and project filtering are stable, bounded and non-overlapping;
- title/project, transcript, analysis edit/revision and deletion mutations refresh search without manual reindexing;
- reopen preserves search and copied/restored databases heal the derived projection;
- Today remains independent from global-search state and never extracts the whole archive into React;
- stale frontend responses cannot replace a newer query, and loading/error/empty/load-more states are explicit and keyboard reachable;
- `meeting-archive-search` FULL_MEDIA proves recent Today -> `⌘K` -> archive-only hit -> source open -> Back -> restored query;
- packaged `.app` lifecycle smoke proves the bundled SQLite runtime can execute the FTS5 archive endpoint.

Checks: `test_catalog_meeting_search.py`, `test_meeting_archive_search_api.py`, `test_frontend_archive_search.py`, existing catalog/workspace/frontend suites, frontend lint/typecheck, browser FULL_MEDIA including `meeting-archive-search`, packaged-app FTS5/lifecycle smoke and selector-owned STRONG validation. Target-WKWebView focus/accessibility remains release confirmation when material.

## PRS-16 — recording while AI is busy

Resolve atomic capture/heavy-work admission for both orderings. Managed work may yield/cancel only at safe supported boundaries; no unsafe thread kill or false instant-start promise. Preserve data on wait/cancel/retry and keep external services caller-owned. Controlled worker/lifecycle races plus busy-AI -> record/stop -> resume FULL_MEDIA; physical capture/thermal evidence is release-only. STRONG expected.

## PRS-17 — coherent macOS workspace

Unify hierarchy across Today, Meeting, Projects, themes and supported window sizes. Keep one dominant action per state, advanced tools discoverable, async navigation stable and focus/keyboard/reduced-motion semantics intact. Component/routing checks plus complete journey FULL_MEDIA; SCOPED expected unless contracts expand.

## Evidence and release

INTEGRATION requires fresh `dev`, reviewed diff/current contracts, selector `auto` and affected deterministic/E2E gates; material UI uses FULL_MEDIA. Missing deterministic automation is `AUTOMATION_CAPABILITY_GAP`, not user work.

RELEASE `dev -> main` requires FULL automation plus applicable target-Mac TCC/audio/WKWebView/VoiceOver, representative MLX/resources and PRS-9 audio evidence. Use `python3 scripts/real_environment_ui_evidence.py --build`. Numeric budgets come from comparable baseline measurements; missing data stays unknown.

Durable owners: `design/ux-contract.json`, `docs/features.md`, `docs/architecture.md`, tests and `docs/current-state.md`. Complete a slice only when code, consumers, recovery, docs and evidence agree.
