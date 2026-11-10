# Meeting transcript × voices — coherent speaker experience

> 2026-11-10 · ACTIVE · `dev@65a6b5b09996e78cba5c608f2da18adbb4ba85c5` · candidate branch `feat/speaker-conversation-ux-20261110`.
> PRODUCT_FEATURE · DELIVERY ITERATION → INTEGRATION (`dev`) · VALIDATION selector-owned (shared attribution/privacy implies STRONG; material UI integration FULL_MEDIA) · EXECUTION REMOTE_AUTOMATED for Mac CI, REAL_ENVIRONMENT for packaged WKWebView/physical audio.

## Outcome / non-goals

A user opens a meeting, reads who said what without scrolling through hundreds of padded cards, locates a voice, listens, confirms/merges a person, corrects a specific misattributed turn, and returns to the exact text/time. Ordinary use is local, accessible and requires zero model/provider decisions. No cloud fallback, biometric speaker recognition, audio source separation, mutation of original words/ASR timestamps, or new parallel persistence stores.

This extends the integrated PR #189 Voices experience and `design/ux-contract.json`; it does **not** replace its canonical player or diarization review/rollback.

## Ownership and staged work

| Lane | Observable deliverable | Canonical owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| A1 · reading | Meeting defaults to compact conversation, original segment data and note/screenshot anchors remain; details opt-in | `TranscriptTextView.tsx`, `MeetingDetailPage.tsx`, E2E | none | ACTIVE — committed, gates pending |
| A2 · projection | Raw cluster/group identity distinct from display name/source; legacy Computer not presented as person, warnings honest | `speakerPresentation.ts`, `SpeakerDiarizationEditor.tsx`; owner contracts/tests | none; parallel A1 files | ACTIVE — committed, gates pending |
| A3 · navigation | Voice timeline jump reveals matching transcript page and synchronized playback | `MeetingDetailPage.tsx`, `TranscriptTextView.tsx` | A1 | ACTIVE — committed, gates pending |
| B · precise correction | Correct **one** segment speaker independent of rename-all/merge; preview scope, version-checked commit and undo preserving original text/word times | `speaker_review.py`, route/store API, UI action | A2 and explicit conflict/revision contract | READY |
| C · integrity | Real one-voice/track and merged cluster read model; historical imported transcripts migration/compatibility, overlapping turns/0 ASR/source only | speaker owner + API/tests | B design | READY |
| D · integrated journey | User flows, copied names, analysis provenance/staleness, 1280/900/640 views, 200% text and VoiceOver | browser E2E, design contract, target Mac | A–C | READY |

Parallel independent ownership: A1 presentation, A2 source projection/tests, and acceptance fixture/E2E may progress simultaneously, but shared `MeetingDetailPage.tsx` and `SpeakerDiarizationEditor.tsx` writes must be serialized. B is deliberately gated by canonical correction/undo design; never fake it as a frontend-only fix.

## Interaction contract / states

- **Initial:** conversation view, no audio telemetry by default; click timestamp to play exact recording, diagnostic cards available under Details; all matches searchable, pagination bounded.
- **Source-only:** “Audio non attribuito” (not a detected person). Legacy Computer is preserved in metadata for investigation. If a real cluster remains but was named Computer by fallback, “Voce da identificare” points to Voices.
- **Selection/playback:** one existing local player. On voice-to-transcript navigation, show correct page/time. Abort sample fetch on meeting switch; never prefetch private audio.
- **Rename/merge/restore:** save revision-aware on existing server owner; render updated names from raw IDs, then show success and undo.
- **Future per-turn correction:** explicit scope (this turn vs whole voice), confirmation if ambiguous, atomic fingerprint and revision-safe undo. Conflicts show reload, not silent overwrite. Analysis previously generated is marked stale rather than silently altered.
- **Unavailable:** missing source track keeps transcription readable; no fake audio or fallback; zero-ASR still permits diarized intervals.
- **Viewport/accessibility:** WKWebView 1280/900/640 px, keyboard/visible focus, non-color distinctions, 200% font, 5k+ segments bounded.

## Evidence checklist / gates

- Browser `scripts/browser_saved_meeting_e2e.mjs`: conversation default, detail opt-in, audio on demand and full speaker review/undo flow. New `scripts/test_speaker_presentation.mjs`: actual TS projection tested for legacy sources, confirmations, grouped/overlap boundaries and immutability.
- TypeScript `pnpm exec tsc --noEmit`, ESLint; Python speaker/diarization/review contract tests and preflight selector where affected.
- Integration requires source SHA/base, complete diff, exact-head CI and FULL_MEDIA; target-Mac packaged WKWebView, local playback/VoiceOver and real TCC evidence remain RELEASE obligations, not implied by hosted browser fixtures.
- A/B acceptance: 401+ segments readable, no cards in default mode, no phantom Computer participant, rename/merge reflect in reading, timeline seek goes to correct page, no original text/timing mutation.

## Checkpoint

First implementation on `feat/speaker-conversation-ux-20261110`. A1/A2/A3 source changes and targeted browser assertion are prepared; tests/CI and REAL_ENVIRONMENT are **not yet claimed PASS**. Next: PR preflight, error classification, then B as a separate shared-contract increment after precise edit/undo proof.
