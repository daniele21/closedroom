# Speaker Review Workspace — ascolta, identifica, unisci, verifica

Status: ACTIVE — product/UX decision captured; implementation not started
Owner: ClosedRoom saved Meeting (frontend + canonical transcription/recording owners)
Read when: revising speaker identities, audio samples, timeline playback or speaker-only corrections

## Product outcome and boundaries

A professional opens **Meeting → Speaker** after local diarization and wants to recognize each voice, correct wrongly split or spurious speakers, and check the full result without replaying the entire meeting. Speaker review should be faster and less error-prone than renaming eight opaque `system:Sx` rows.

**Outcome:** each speaker has a readily playable voice sample, a clear name and status, actions to merge/exclude without losing content, and a speaker-only playback/verification mode. Typical path: listen → name → next → verify (optionally merge/exclude) → saved.

**Non-goals:** re-run ASR or diarization for ordinary corrections; cloud transcription/analysis; audio cloning; auto-identification of people from voice; deleting transcript words, timestamps or raw audio; automatic speaker merging because names look identical; replacing advanced Community-1 preview/apply/undo or diarization benchmarks.

**Four axes:** PRODUCT_FEATURE / ITERATION initially (INTEGRATION for PR→dev; RELEASE only dev→main) / STRONG (speaker identity contracts, persistence and audio replay, plus material UI evidence at integration) / REMOTE_AUTOMATED for Mac/browser deterministic gates missing locally; REAL_ENVIRONMENT for target-Mac WKWebView, device-audio and qualitative VoiceOver evidence.

### Risks and assumptions

- **VALUE:** users can identify voices more reliably with samples than with opaque IDs; compare per-speaker identification time/corrections against today's editor.
- **USABILITY:** four primary capabilities, but only one default action (play sample); advanced merge/exclude behind per-row menu; no diagnostics codes in main row.
- **FEASIBILITY:** current `frontend/src/components/meeting/SpeakerDiarizationEditor.tsx` is name-only. Segment timestamps/provider_speaker live in transcription; `/v1/recordings/{id}/tracks/{track}/audio` serves local audio, while `speaker-diarization.json` can retain the native diarization timeline. `TranscriptionStore` and Community-1 review own persistence and optimistic undo.
- **VIABILITY:** no model inference or network call to listen; bounded playback intervals and metadata; keep CPU/memory negligible.
- **PRIVACY/RELIABILITY:** respect localhost auth/origin policy; no remote audio, analytics or voice embeddings; fail explicitly if selected audio was offloaded or removed rather than silently fetching. Never change immutable source media.

## Decision: task and information hierarchy

Keep this **inside the canonical saved Meeting → Speaker** tab, not a new route, modal workflow or competing editor. Replace the current grid of eight inputs with an easy-to-scan vertical review list.

1. **Header:** “Riconosci le voci” and progress (e.g. 3/7 recognized). Primary contextual action “Ascolta tutte le voci”/“Verifica”, not a global “Salva” dominating a field grid. Save edits explicitly, with unsaved-state notice and keyboard support.
2. **Speaker row:** prominent name/edit input, 3–8 s sample play/pause, 1–3 alternative samples (different points), transcript utterance count and duration, low-emphasis more menu; show generic `system:Sx` only under details. A row with zero transcript segments still gets a sample **when a matching saved diarization timeline exists**; otherwise clearly “Campione non disponibile” and explain why. `mic:S1` should be labelled “Tu” by default only where semantics support it.
3. **More actions:** “Unisci con…” opens target selection + before/after counts + confirmation; “Escludi speaker” unassigns that identity but never removes utterances; “Ripristina”/Undo follows versioned canonical review state. Rows merged into another are collapsed with traceable source identity; avoid silent irreversible deletion.
4. **Speaker-only check:** “Ascolta solo [nome]” starts a queue of that person's original timed utterances, skipping intervening speakers/silences (no new audio output file). Show current excerpt, source timestamp, index/total, prev/next/pause, optionally jump to transcript, clear exit back to ordinary meeting playback. Interleaved/overlap intervals are handled deterministically; one active player per Meeting.
5. **Progressive disclosure:** raw cluster ID, provider, source track and model choice remain behind a diagnostic details disclosure; benchmarking/Community-1 remains advanced below ordinary review.

### Interaction rules

- **Sample sourcing:** choose up to three bounded, intelligible clips per original cluster using transcript segment times where available, preferentially several separated points; avoid zero-duration, very short or overlap-heavy clips. If no linked transcript interval, use matching persisted raw diarization timeline from the same engine/revision. Return only timestamps, speaker IDs and track identifiers; audio is requested on deliberate play via existing local track endpoints.
- **Tracks:** `system:Sx` uses system audio; `mic:S1` uses mic; legacy mixed uses its available track. Validate source track exists and matches the recording; no cross-recording access or UI guessing based on display names. Audio controls should seek safely and stop at interval end.
- **Multiple examples:** offer short primary sample plus “Altro esempio”/next, not all waveforms at once. Keep active state per recording, cleanup on navigation/unmount, lost audio, missing permission or source removal.
- **Merge:** source and target must be different valid identities from this transcription; prevent cycles/chains or canonicalize them. Preserve original `provider_speaker` IDs/provenance and group through one resolved attribution mapping; change visible name and grouped playback only. Combined playlist includes all source identities.
- **Exclude:** show exact affected segment count. With zero matching segments, hide just the spurious row; with matching segments, label them “Speaker non identificato” pending reassignment. Do not delete ASR words, timestamps, recordings, diarization evidence or source clusters. No automatic exclusion because segment overlap is zero.
- **Rename:** no automatic merge when two rows have same name. Use one canonical persisted projection for transcript, analysis context, exports and speaker-only queue; avoid divergent frontend-only identity groups.
- **Version safety/Undo:** create a review candidate against exact transcription fingerprint; reject stale apply after a changed transcription, later Community-1 apply or manual names. Save an atomic, locally private snapshot with opaque undo token using the existing `TranscriptionStore` review ownership; one undo step after each committed action. Avoid silently invalidating Community-1 rollback.
- **Text invariant:** review changes speaker attribution **only**. Canonical ASR text, word/segment start-end, per-segment text, audio bytes and recording IDs are unchanged. The display may re-render attributed lines; do not rewrite original transcript text.
- **Accessibility:** button labels include speaker name + sample number; keyboard focus, Enter/Space, Escape to cancel merge, visible focus, reduced motion, ARIA live announcement for save/merge/undo and unavailable media; compact WKWebView becomes one column.

## Executable work graph

| ID | Work | Canonical write owner | Dependency | Parallel | State |
| --- | --- | --- | --- | --- | --- |
| SR-0 | Confirm UX semantics, reproducible fixtures and this plan | this workstream, relevant UX contract | dev | yes | DONE |
| SR-1 | Bounded sample references including unmatched raw-timeline speakers + read-only API; no audio copying or diarization rerun | `RecordingStore` timeline reader, focused `routers/recordings.py` or transcription endpoint, pure sample helper + backend tests | SR-0 | yes | READY |
| SR-2 | Speaker-only canonical revision contract for rename/merge/exclude, optimistic lock, persisted projection and safe undo | `speaker_labels.py`, `transcriptions.py`, `routers/transcriptions.py`, API/contract tests | SR-0 | yes | READY |
| SR-3 | Shared local playback controller: sample clips and one-speaker sequential queue; track alignment, stop/seek/error cleanup | new small meeting UI hook + tests | SR-1 API signature | no | BLOCKED |
| SR-4 | Replace name-only row grid with speaker review list/actions; simple path plus explicit merge/exclude/undo, compact/a11y UX | `SpeakerDiarizationEditor.tsx`, scoped components/styles + browser tests | SR-2 contract, SR-3 | no | BLOCKED |
| SR-5 | Integrate with saved Meeting and Community-1; no competing playback controller or undo surface | `MeetingDetailPage.tsx`, `CommunityOneReviewPanel.tsx`, affected journeys | SR-2..4 | no | BLOCKED |
| SR-6 | Full relevant source, API, UI E2E FULL_MEDIA, docs and exact-head/base INTEGRATION proof | preflight + affected canonical feature/UX docs | SR-1..5 | no | BLOCKED |

Parallelize SR-1 and SR-2 only after freezing the shared speaker sample/revision response DTOs; no concurrent writes to `SpeakerDiarizationEditor.tsx` or the saved Meeting owner.

## Contract and tests — acceptance

1. Meeting with 7 detected speakers/801 assigned segments: sample play from correct local track, rename and confirm an individual speaker in a few actions; no need to open developer tools, rerun ASR or memorize `system:Sx`.
2. Transcript speaker with 0 matched ASR segments and raw diarization evidence: get a real sample from its source timeline; if evidence absent, show explicit unavailable status, never fabricate an example or play another voice.
3. Merge two real clusters, reload app, see one combined name/playlist (all original utterances still present, times and words unchanged); Undo restores both identities. Reject unknown target, self-merge and cycles.
4. Exclude a spurious/empty cluster: hide it from standard view, but show recoverable ignored status and preserve raw evidence; excluding cluster with segments leaves segments in visible “Non identificato” group, not lost.
5. Speaker-only playback plays exactly eligible segments in chronological order across one or more original clusters, skips other speaker intervals, seeks/cancels cleanly and displays true timestamps; absence of selected local track fails with clear recovery.
6. Concurrent stale review, Community-1 apply/undo, rename and another Meeting selection never overwrite newer edits or leak prior Meeting audio; exact recording/transcription ownership required at API.
7. Local-first/privacy: no network endpoints other than app localhost, no generated voice assets, no cloud fallback, no leaking raw paths/metadata. Tests include import/no segments, no audio, mixed/mic/system, overlapping segments, short durations and transcript revision conflicts.
8. Browser wide/compact and keyboard/focus journeys plus real WKWebView target-Mac playback/VoiceOver observation at RELEASE where applicable.

## Implementation boundary and evidence

Source of truth: `frontend/src/` for UI, `TranscriptionStore` for durable speaker edits and undo, `RecordingStore` for bounded audio/timeline access. Never add a second speaker data store or playback audio export. Preserve existing Community-1 candidate/apply/rollback and benchmark isolation.

Validate with repository-selected `scripts/select_validation_profile.py`; focus `test/test_speaker_labels.py`, `test/test_diarization_review.py`, `test/test_diarization_review_api.py`, new sample/revision API tests, frontend TypeScript/lint and UI journeys. At PR→dev select STRONG and affected automated FULL_MEDIA; exact-head source evidence required. On dev→main choose RELEASE/FULL and relevant real target-Mac TCC/audio/WKWebView checks. Neither a plan nor a merged PR proves product success.

## Checkpoint

Base: `dev` at `779009b2d6fbb1cdff40aa6f3b20419f760ca075` (2026-11-04). Observed: editor currently only supports manual names; `apply_speaker_labels` builds mappings and may rebuild display text; `speaker-diarization.json` retains native timeline; `TranscriptionStore.apply_reviewed_diarization` provides fingerprint-based apply and rollback; source audio endpoints already exist. Design is shaped but no implementation/evidence is yet claimed. Next discriminating action: define the bounded sample source and merge/exclude revision DTOs, then implement SR-1/SR-2 on disjoint owners and validate before UI integration.

Durable destinations after implementation: `design/ux-contract.json` for final task/navigation contract, `docs/features.md` for user capabilities, tests/code for exact request/state contracts; update `docs/current-state.md` and delete this plan after completion.
