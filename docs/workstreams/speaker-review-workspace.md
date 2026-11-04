# Speaker Review Workspace — progettazione e delivery

Status: ACTIVE — implementation in progress; exact-head STRONG/E2E evidence pending
Owner: canonical saved Meeting + TranscriptionStore/RecordingStore; source `dev`
Read when: speaker review audio, edits, queues, corrections, rollback, integration

## User, problem and outcome

**User:** a professional reviewing a completed private/local meeting.
**Job:** recognize each detected voice from short audio, name it, correct false/duplicate clusters, and verify *all attributed interventions* without replaying the full recording.
**Observed friction:** screenshot shows 8 equally weighted, two-column input cards with opaque `system:Sx` codes, technical `completed`/backend text, no embedded samples, no merge/exclude or per-speaker audition, tiny labels, and one global Save button unrelated to the current row. “Computer” may represent a *track/source* rather than a human: verify its origin, do not assert it is always a person. User must currently infer a name without evidence.

**Measurable result:** short path `select voice → play 3–8s → name → next`; a selected person can be heard through all attributed intervals; merge/exclude are reversible; original words, timings and audio never change. In a meeting like the supplied 7 detected speakers / 801 assigned segments, no requirement to inspect raw cluster IDs or a separate benchmarking page.

**Non-goals:** new navigation root, external speaker recognition/voice enrollment, speaker embeddings, mixing/cloud transfer, automatic identity guesses, diarization or ASR reruns for manual edits, deleting source audio/text, or implying that overlapping voices have been separated. Do not replace Community-1 review or A/B benchmark.

**Four axes:** PRODUCT_FEATURE; ITERATION while planning/developing, INTEGRATION when preparing PR→dev; STRONG for data/API/privacy/media lifecycle (plus FULL_MEDIA on affected material UI integration); REMOTE_AUTOMATED for unavailable deterministic tests and REAL_ENVIRONMENT for authentic target-Mac audio/WKWebView, as independent evidence.

## UX decision and scoped design reference

The target is a fast **selected speaker master-detail reviewer** in canonical Meeting → Speaker, stacked inline in compact WKWebView. One obvious `Ascolta campione` primary action, fast per-speaker name commit (no global Save), a low-emphasis merge/exclude menu with preview and undo, and `Ascolta i suoi interventi` for interval playback. Original raw speaker IDs, audio, ASR text and timestamps must remain unchanged. Never present `Computer` as a person solely from an audio-source label, nor claim true voice isolation from overlapping speech.

**Implementation-ready UX/UI specification**, wireframes, copy, full state matrix, sample/merge/playback semantics and accessibility criteria are in [speaker-review-interaction-reference.md](speaker-review-interaction-reference.md). It is a *proposed* temporary reference, not a shipped feature or a competing design system. Use `skills/interaction-quality-review/SKILL.md` to check its implementation against the current ClosedRoom design tokens and tested journeys.

## Delivery graph — bounded owners and dependency

| ID | State | Independently observable slice | Owner/write boundary | Depends |
| --- | --- | --- | --- | --- |
| SR-0 | DONE | Product task, UX/UI layout, microcopy, risk and acceptance modeled | this workstream + new `interaction-quality-review` local skill | dev source |
| SR-1 | ACTIVE | Read-only sample refs for transcript and unmatched current diarization timeline; safe audio range/track behavior | `RecordingStore`/read API, sample selector, backend tests | SR-0 |
| SR-2 | ACTIVE | Versioned speaker correction operations (rename/merge/exclude/reassign if feasible), same owner and rollback policy | `speaker_labels.py`, `TranscriptionStore`, transcription router, tests | SR-0 |
| SR-3 | ACTIVE | One local playback controller for sample and selected-speaker queue, cleanup and truthful overlaps | meeting playback hook, focused frontend tests | SR-1 API |
| SR-4 | ACTIVE | Wide/compact master-detail with row names, samples, merge preview, exclude, progress, undo | `SpeakerDiarizationEditor.tsx`, scoped components, UI tests | SR-2/3 |
| SR-5 | ACTIVE | Integrate single player/revision with Meeting, Community-1 and transcript view; fix `Computer` classification by evidence | `MeetingDetailPage.tsx`, consumer tests, no parallel ownership | SR-2/3/4 |
| SR-6 | BLOCKED | Required exact-head INTEGRATION evidence, visual/full-media + source gates, docs, UI acceptance and merge readiness | preflight, UX contract, feature docs | SR-1..5 |

Parallel execution: SR-1 and SR-2 can run independently after shared DTO review; no concurrent edits to speaker editor or meeting shell. If per-turn override significantly expands scope, keep it as a dedicated follow-up rather than blocking fast identify/merge/exclude/playlist.

## Evidence and acceptance

**Core acceptance:** 1) recognize/name a voice via genuine local sample; 2) A/B-compare and merge two clusters with preserved original turn attribution, surviving reload and reversible; 3) exclude a spurious 0-turn cluster without data loss; exclude nonempty cluster only into Unidentified; 4) hear only selected intervals in order (with known overlap caveat), jump-to-transcript; 5) zero-match raw-timeline clip only when exact source proof exists; 6) one speaker row clearly distinguishable from source `Computer`; 7) stale edits cannot overwrite newer Community-1 or user changes; 8) no new network/telemetry/media-copy boundary.

Run focused unit/API `test/test_speaker_labels.py`, `test/test_diarization_review.py`, `test/test_diarization_review_api.py`, new selector/revision/audio tests, frontend lint + TS; add browser journey on deterministic fixtures including 7+ speakers, zero turns, sample failure, merge preview/undo, compact keyboard. Use actual repo `scripts/select_validation_profile.py` (never downgrade selected profile). At PR→dev: full diff, exact source/base, STRONG gate selection and affected material UI `FULL_MEDIA`. At dev→main: RELEASE/FULL plus applicable interactive WKWebView, VoiceOver, TCC/real track seek evidence on target Mac; no synthetic browser pass presented as physical audio proof. Success metrics to measure: seconds and actions to recognize a voice, correction time, mistaken merges, completion rate, and recovery from error (baseline unknown, avoid invented targets).

## References and resume checkpoint

Internal: `AGENTS.md`, `skills/design-product-experience/SKILL.md`, `skills/interaction-quality-review/SKILL.md`, `design/ux-contract.json`, `design/brand-kit.json`, and native source/tests cited above. External pattern inspiration (do not copy design systems): [Anthropic frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md); [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines); [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill); [Apple split view](https://developer.apple.com/design/human-interface-guidelines/split-views); [Otter speaker management](https://help.otter.ai/hc/en-us/articles/40586357592471-Speaker-Management); [Fireflies speaker edits](https://guide.fireflies.ai/articles/4994477228-how-to-edit-speaker-labels-or-names-in-a-transcript). Public examples describe workflow inspiration, not ClosedRoom implementation or local data processing.

Base observed: `dev` `779009b2d6fbb1cdff40aa6f3b20419f760ca075` on 2026-11-04; refresh before implementation/integration. Confirmed: current editor only names, existing authenticated track audio endpoints and saved diarization summary, `TranscriptionStore` fingerprint/undo for Community-1. Pending: actual raw-timeline file consumer, `Computer` provenance, time alignment and media seek on packaged WKWebView, exact current integration head. Next discriminating action: inspect recording timeline storage and current catalog projections, freeze audio-sample DTO and speaker revision token, then begin SR-1/SR-2 in parallel. Transfer implemented UX to `design/ux-contract.json` and affected feature docs only when code is real; after completion update current-state and delete temporary workstream by default.

## Iteration checkpoint — 2026-11-04

Branch `feature/speaker-review-workspace` is based on dev `779009b2`. Implemented in this branch (not merged): safe sample references with raw-timeline provenance guard; `TranscriptionStore`-backed optimistic rename/merge/exclude/restore and undo; single source-track playback hook; responsive list/inspector, unassigned-source disclosure and contextual controls; Meeting integration and browser fixture coverage. Added `test/test_speaker_review.py` and browser journey. Keep SR-1..5 ACTIVE until selected tests and UI evidence pass; SR-6 BLOCKED. A documentation-route budget failure was corrected with a shorter UX reference and AGENTS routing; latest exact-head validation still pending. Next: run actual source/frontend/API/browser gates through repo automation, diagnose failures with logs, verify complete diff and UI media; defer physical WKWebView audio/VoiceOver to release only if automatic integration evidence is adequate. No local Mac media proof claimed.
