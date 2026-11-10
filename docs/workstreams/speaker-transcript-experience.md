# Meeting transcript × voices — coherent speaker experience

> 2026-11-10 · ACTIVE (C historical-import and REAL_ENVIRONMENT evidence) · integrated baseline `dev@6aa10ab6c8e6780836e6d44144333f8a6a2c92b2`.
> PRODUCT_FEATURE · DELIVERY INTEGRATION for the completed increments / future ITERATION for remaining scope · VALIDATION scoped UI + strong persistence contracts + required FULL_MEDIA E2E · EXECUTION REMOTE_AUTOMATED (deterministic Mac), REAL_ENVIRONMENT (installed app and physical audio).

## Goal and boundary

A person can read a long recorded meeting as a conversation, know which identity is confirmed or merely an audio source, audition a voice without uploading it, correct one specific misattributed turn, and undo safely. Preserve original captured WAV and ASR provider cluster, words and time. Cloud is never an implicit fallback; existing `TranscriptionStore` and speaker-review API own persistence/revisions, not React.

## Delivered to `dev`

| Lane | Verified outcome / owner | Status and evidence |
| --- | --- | --- |
| A1 reading | `TranscriptTextView` defaults to compact Conversation in Meeting, with Details and audio telemetry optional. Same underlying segment IDs, notes and screenshot anchors. | DONE · PR #194, `21213bd` |
| A2 identity projection | `speakerPresentation.ts` distinguishes person cluster/group from source labels (legacy Computer); name/merge/exclusion remain owned by existing review state. | DONE · PR #194 |
| A3 navigation | Voice timeline jumps reveal the transcript page and seek the shared local player. | DONE · PR #194 |
| B correction contract | `speaker_review.py`, `speaker_labels.py`, API and `TranscriptionStore` persist `segment_assignments` by ID with existing fingerprint conflict and one-revision undo; raw words/timestamps/audio remain original. | DONE · PR #195, `5857882` |
| B UI integration | `TurnSpeakerCorrection` supports an exact segment even within a grouped paragraph, explicit target, stale reload, keyboard-focus recovery and undo in Meeting. | DONE · PR #196, `65f82f0` |
| C edge integrity | Synthetic 5,005-turn navigation/search and source-only Computer passed in #199; browser text-only imported and fully empty transcription states are now being checked. Genuine imported files, stale/mixed speaker mappings and representative performance remain unproven. | ACTIVE — #199 integrated; text-only/empty browser regression candidate |
| D analysis provenance | New structured analysis snapshot stores a digest of canonical effective speaker assignment; Meeting/Project read-only projections show current/stale/unverifiable, preserve old notes/edits and offer explicit analysis regeneration. | DONE · PR #198, `f92fe05`, 932 Python tests + browser FULL_MEDIA on checked head |
| D real UX | Installed WKWebView, physical mic+system media/TCC, VoiceOver, small window/200% text and representative long meetings. | BLOCKED on REAL_ENVIRONMENT release evidence |

## Integration evidence and limits

- PRs #194–196, #198 and #199 had successful integration preflight and exact-head `local-ci/mac`; each was squash-merged to `dev`. #199 exercised a synthetic 5,005-turn transcript across 201 pages (last-page bounds, cross-page search, source-only Computer, no eager audio/inference). The #198 Mac lane ran 932 Python tests plus browser FULL_MEDIA with stale-note UI and API current→stale→current after undo. The saved Meeting FULL_MEDIA browser journey includes Conversation/Details, sample/merge/restore, scoped correction and undo. Projection unit tests cover immutable raw clusters, same-voice grouping/overlaps and source-only fallback; backend unit/API tests cover segment IDs, stale fingerprints and persistence.
- E2E uses deterministic loopback/browser fixtures. This is **not** proof that installed WKWebView, physical audio switching or microphone/system playback work on the representative Mac. Nor is it performance/quality proof for 401+/5000+ segments or all historical transcripts.
- Test-only failures were diagnosed and fixed with intact invariants (canonical merged ID in fixture; comparing immutable raw export rather than decorated read projection). No pass inferred from intermediate failed heads.
- `dev` includes the feature. RELEASE/FULL for `dev→main`, physical media/TCC, packaged lifecycle, subjective VoiceOver and qualifying distribution artifacts still block promotion.
- No new remote transfer, automatic model download, audio upload or second persistence/history owner was introduced.

## Remaining actions and acceptance

1. **C · edge/read-model integrity:** synthetic source-only Computer, overlap, 201-page navigation and cross-page search are covered by #199. Add checks for legacy raw-text-only imports and genuinely empty transcripts; collect representative real historical imports for mixed/merged/stale IDs and source-vs-person reconciliation. No speaker inferred from a track name.
2. **C · long/legacy evidence:** #199 passed synthetic >5000 ASR turns, bounded DOM and cross-page search on Mac CI. Run text-only/empty-browser regression on current exact head, then supplement with real imported meeting files and representative measured performance; do not mark C complete from fixture tests alone.
3. **D · packaged UX:** record exact candidate, test speaker sample playback and per-turn correction/undo on installed WKWebView with real dual-track recording, keyboard/VoiceOver and compact/zoomed layout. Release authority and target-Mac evidence remain separate from GitHub Actions source tests.
4. Before closure transfer any remaining findings to `docs/features.md`, `docs/current-state.md`, `design/ux-contract.json` and release evidence owners, then delete this temporary plan per `skills/finalize-workstream`.

Checkpoint: PRs #198 and #199 integrated. Source digest normalizes raw catalog vs decorated transcription read paths on a copy; analysis input cache is structured v4, with speaker group/provider identity. Meeting/Project annotations are read-only and skip hashing if no completed source-linked analysis. `Prepara note` may deduplicate an earlier completed parent, so the warning offers only deliberate `meeting_default` regeneration. The current C candidate checks text-only/empty historical transcript browsing; its exact-head source/browser gates are pending.
