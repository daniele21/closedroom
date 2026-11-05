# Speaker timeline in the Meeting

Status: ITERATION on `feat/speaker-timeline-meeting-20261105` (base `dev@5a9ad90b`).
Product impact: PRODUCT_FEATURE. Delivery: ITERATION → INTEGRATION / STRONG (selector to confirm).
Execution: Mac remote-automated for deterministic checks; physical playback/TCC on installed WKWebView is REAL_ENVIRONMENT deferred to RELEASE.

## User problem, outcome and boundaries

After assigning names, the user cannot see when each person spoke or a common overview. A separate engine-comparison timeline exists but does not reflect confirmed people. The goal is to let the user verify who spoke, find any voice quickly, play exact recording intervals and navigate back to transcript within the existing Speaker tab.

Not in scope: speaker source separation, new ASR/diarization runs, model/provider changes, changing timestamp/text, remote services, a second screen, or trusting stale benchmark output as applied identity.

VALUE: validate 1:1 usefulness through live review. USABILITY: color+name+time, full recording by default, 1/5/10-minute zoom, keyboardable blocks, narrow WKWebView layout, honest empty/unavailable source states. FEASIBILITY: precise persisted native diarization only if its engine and full cluster set match the applied transcription; else attributed ASR intervals with explicit coverage label. VIABILITY: reuse canonical recording/transcription read surfaces and local clip player; no extra persistence or models.

## Canonical ownership

- `speaker_review.py`: bounded, read-only projection, local recording track identity and native provenance validation; never mutate audio, ASR, timestamps or user edits.
- `routers/transcriptions.py`: existing review context/auth, bounded timeline window endpoint.
- `SpeakerDiarizationEditor.tsx`: shared speaker selection/editing/playback; `SpeakerTimeline.tsx`: UI projection, zoom and navigation. Benchmark stays separate; raw clusters, source tracks and person names are not interchangeable.
- Source transcript segments remain the only applied fallback for reviewed Community-1 runs, not their potentially unrelated raw recording. Explicit `coverage=transcript` makes this limitation visible.
- If local audio is moved/unavailable, show time intervals read-only; disable playback instead of pretending to play or silently fetching cloud audio. Gray marks are unattributed, not confirmed people.

## Observable acceptance

1. Overview and one row per active non-source speaker share the same absolute time axis. Overlaps remain visible.
2. Clicking an available interval reuses the existing authorized local track player; no audio fetched on tab open. Playback/selection does not mutate the transcription.
3. Rename/merge/exclude/restore and reviewed diarization visibly re-project rows from updated metadata without duplicating/losing intervals; successful edits retain the canonical text, words and times.
4. Missing raw provenance downgrades to truthful transcript projection, including unmatched audio-only clusters with no fabricated words. No audio and limited viewport surface explicit states.
5. Window query is bounded to 8h and 5000 intervals; UI warns on truncation and supports smaller viewports.
6. Automated source/API tests + frontend lint/tsc + Mac FULL_MEDIA saved-meeting E2E with merge/undo checkpoints. Physical native-audio and WKWebView review remains release evidence.

## UX review states

Idle: full overview, first speaker selected. Selected: lane emphasis, other voices visible. Playing: shared player cursor with a local timestamp. Edit: names/groups update after canonical response. Undo: same intervals, previous grouping. Empty: no segments with explanatory text. Failure: visible API error. Moved audio: bars remain but nonplayable. Partial: clear truncation warning and zoom. Navigation-away: existing player cleanup.

P1: Need actual accuracy/performance evidence when installed; CI browser mock must not count as physical diarization or source-separated speech.
