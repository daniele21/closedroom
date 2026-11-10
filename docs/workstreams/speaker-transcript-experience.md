# Meeting transcript × voices — coherent speaker experience

> 2026-11-10 · ACTIVE (residual C/D) · integrated baseline `dev@65f82f09f2694d2e1b6f827b08313df22795e5e9`.
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
| C edge integrity | Imported/legacy mixed speaker IDs, overlaps, source-only rows, 401+/5000+ segment navigation and player reconciliation need representative tests beyond existing fixtures. | READY |
| D analysis provenance | Compare a stored speaker-attribution source digest to the current transcript in read-only Meeting/Project run projections; warn and offer explicit analysis regeneration, preserve user notes/edits and old runs. Legacy runs with no source digest are unverifiable if speaker changes exist. | ACTIVE — candidate PR / exact-head gates pending |
| D real UX | Installed WKWebView, physical mic+system media/TCC, VoiceOver, small window/200% text and representative long meetings. | BLOCKED on REAL_ENVIRONMENT release evidence |

## Integration evidence and limits

- PR #194 `39afb46`, PR #195 `094f4a8` and PR #196 `ad78474` each had successful integration preflight and exact-HEAD `local-ci/mac`; each PR was squash-merged to `dev`. The saved Meeting FULL_MEDIA browser journey includes Conversation/Details, sample/merge/restore, scoped correction and undo. Projection unit tests cover immutable raw clusters, same-voice grouping/overlaps and source-only fallback; backend unit/API tests cover segment IDs, stale fingerprints and persistence.
- E2E uses deterministic loopback/browser fixtures. This is **not** proof that installed WKWebView, physical audio switching or microphone/system playback work on the representative Mac. Nor is it performance/quality proof for 401+/5000+ segments or all historical transcripts.
- Test-only failures were diagnosed and fixed with intact invariants (canonical merged ID in fixture; comparing immutable raw export rather than decorated read projection). No pass inferred from intermediate failed heads.
- `dev` includes the feature. RELEASE/FULL for `dev→main`, physical media/TCC, packaged lifecycle, subjective VoiceOver and qualifying distribution artifacts still block promotion.
- No new remote transfer, automatic model download, audio upload or second persistence/history owner was introduced.

## Remaining actions and acceptance

1. **C · edge/read-model integrity:** collect minimal anonymized/synthetic legacy fixture variants; test source-only Computer, renamed/merged cluster, 0 ASR segments, overlapping turns, stale identity and 401+/5000+ segment navigation. No best-effort speaker label inferred from a track name.
2. **D · analysis provenance:** complete integration gates for the source-digest and read-only warning candidate; verify caching, Meeting API/Project read model, historical run compatibility and browser warning/explicit regeneration affordance before marking DONE. No automatic mutation of old notes.
3. **D · packaged UX:** record exact candidate, test speaker sample playback and per-turn correction/undo on installed WKWebView with real dual-track recording, keyboard/VoiceOver and compact/zoomed layout. Release authority and target-Mac evidence remain separate from GitHub Actions source tests.
4. Before closure transfer any remaining findings to `docs/features.md`, `docs/current-state.md`, `design/ux-contract.json` and release evidence owners, then delete this temporary plan per `skills/finalize-workstream`.

Checkpoint: the existing analysis-job run `input_hash` is text-only while structured cache identity includes displayed speaker; saved Meeting previously lacked an attributable source check after speaker-review mutations. Candidate `feat/speaker-analysis-provenance-20261110` adds SHA-256 of effective speaker assignments into new structured source snapshots, source-derived status projection with legacy uncertainty, browser alert and explicit `meeting_default` regeneration. Must validate exact HEAD/base; `Prepara note` can deduplicate an earlier completed parent and is not the correct regeneration action.
