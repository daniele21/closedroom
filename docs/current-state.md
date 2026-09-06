# Current state

## Engineering baseline

ClosedRoom follows `daniele21/repo-template-sw` **0.9.2** at maturity **L2** with `python`, `typescript`, `macos`, `local-ai`, `product-ui`. Changes integrate through `dev`; `dev -> main` is RELEASE. PRs into `dev` require selector-owned deterministic/E2E evidence, while applicable target-Mac `REAL_ENVIRONMENT` evidence is `DEFERRED_TO_RELEASE`.

## Integrated baseline

- Exact-head/tree-equivalent remote preflight, immutable finalized artifacts and packaged-app lifecycle smoke are established.
- Product/runtime PRS-5..8 are integrated: Meeting-first defaults, visual intelligence on demand, bounded managed model residency and persisted SSE job progress with 512-event/job retention.
- PRS-9 benchmark tooling is integrated; dual-track audio remains canonical until representative release evidence supports a change.
- PRS-11 / PR #35: saved Meeting core content opens independently from diagnostics/visual routes, with local accessory recovery and browser FULL_MEDIA evidence.
- PRS-12 / PR #36: `Prepare notes` is one durable Meeting workflow backed by a persisted `meeting_preparation` parent, reuse/cancel/restart/resume contracts and `meeting-preparation-recovery` FULL_MEDIA. Existing transcription/analysis managers and `HeavyWorkloadArbiter` remain execution owners.
- PRS-13 / PR #37: implicit default notes use one shared structured v2 analysis instead of four overlapping physical jobs, with source-aware bounded extraction, virtual legacy projections and exact cache identity.
- PRS-14 / PR #38 merged to `dev` at `a3902f3cd5620ace3550ec6d4e48aab1ab620a2f`: actions/decisions are source-verifiable and editable through a persisted overlay/revision model; regeneration conflicts are explicit and the `meeting-note-edit-revision` FULL_MEDIA journey is integrated.
- Canonical target-Mac runner: `python3 scripts/real_environment_ui_evidence.py --build`. Production signing/notarization, subjective VoiceOver usability and representative MLX/Metal performance remain release claims.

## Current integration candidate

PRS-15 is implemented on `feat/prs-15-complete-archive-search` from `dev@a3902f3c`. It replaces the old global-search behavior that depended on at most the recent RecordingStore window and compact transcript previews in React.

The candidate keeps `CatalogStore` as the persistence owner and adds a derived FTS5 projection inside the same SQLite database. Canonical recording/transcription/analysis mutations mark recording ids dirty through SQLite triggers; search refreshes only affected rows before serving results. First use backfills the existing catalog once, while schema metadata and row-count healing cover restored/copied databases.

`GET /v1/meetings` remains backward-compatible when `q` is omitted. Supplying `q` opts into complete bounded archive paging with stable `page`, `limit`, `total`, `has_more` and optional exact project filtering. Text queries are interpreted as bounded plain text rather than raw FTS syntax; pages are capped at 50.

The Today page is now independent from global-search state. `⌘K` opens a dedicated archive dialog that requests 25-item server pages, cancels/ignores stale responses, shows loading/error/empty/load-more states and preserves the query across source navigation. Demo-mode search stays local to synthetic demo fixtures.

FTS5 availability is fail-closed: there is no whole-archive fallback scan. The packaged-app lifecycle smoke probes the authenticated archive endpoint inside the frozen runtime, so integration evidence must prove the bundled SQLite runtime actually supports the capability.

Expected integration depth is **STRONG** because the change touches persistence projection, API paging, material Meeting search UI, `.engineering/e2e.json` and packaged behavior. Required automated evidence includes catalog/API/frontend tests, all affected Meeting browser FULL_MEDIA journeys including `meeting-archive-search`, packaged-app FTS5/lifecycle smoke and repository validation on exact HEAD/base.

## Release evidence still pending

Representative CPU/RSS/Metal/thermal evidence, target-Mac UX/TCC/native-audio confirmation, PRS-9 representative audio comparison and any material production ASR/LLM quality/latency claim remain release work. PRS-15 does not claim a production performance improvement; it claims bounded archive behavior and packaged FTS5 capability only after automated evidence passes.

## Active workstreams

- [`meeting-value-efficiency.md`](workstreams/meeting-value-efficiency.md): PRS-11..14 integrated; PRS-15 integration candidate; PRS-16 ready.
- [`product-runtime-simplification.md`](workstreams/product-runtime-simplification.md): PRS-10 convergence remains open.
- [`ux-simplification.md`](workstreams/ux-simplification.md): deterministic work integrated; target-Mac confirmation remains a release gate.

## Next highest-value work

1. Complete exact-head INTEGRATION validation for PRS-15; merge only if selector-required source/FULL_MEDIA/package gates agree.
2. Advance PRS-16 recording-while-AI-busy on the integrated PRS-15 base.
3. Then converge PRS-17 workspace UX and collect representative resource/audio/target-Mac evidence for PRS-18 / `dev -> main` release acceptance.
