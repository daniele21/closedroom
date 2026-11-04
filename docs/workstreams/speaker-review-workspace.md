# Speaker Review Workspace — progettazione e delivery

Status: ACTIVE — UX/UI shaped; implementation NOT STARTED
Owner: canonical saved Meeting + TranscriptionStore/RecordingStore; source `dev`
Read when: speaker review audio, edits, queues, corrections, rollback, integration

## User, problem and outcome

**User:** a professional reviewing a completed private/local meeting.
**Job:** recognize each detected voice from short audio, name it, correct false/duplicate clusters, and verify *all attributed interventions* without replaying the full recording.
**Observed friction:** screenshot shows 8 equally weighted, two-column input cards with opaque `system:Sx` codes, technical `completed`/backend text, no embedded samples, no merge/exclude or per-speaker audition, tiny labels, and one global Save button unrelated to the current row. “Computer” may represent a *track/source* rather than a human: verify its origin, do not assert it is always a person. User must currently infer a name without evidence.

**Measurable result:** short path `select voice → play 3–8s → name → next`; a selected person can be heard through all attributed intervals; merge/exclude are reversible; original words, timings and audio never change. In a meeting like the supplied 7 detected speakers / 801 assigned segments, no requirement to inspect raw cluster IDs or a separate benchmarking page.

**Non-goals:** new navigation root, external speaker recognition/voice enrollment, speaker embeddings, mixing/cloud transfer, automatic identity guesses, diarization or ASR reruns for manual edits, deleting source audio/text, or implying that overlapping voices have been separated. Do not replace Community-1 review or A/B benchmark.

**Four axes:** PRODUCT_FEATURE; ITERATION while planning/developing, INTEGRATION when preparing PR→dev; STRONG for data/API/privacy/media lifecycle (plus FULL_MEDIA on affected material UI integration); REMOTE_AUTOMATED for unavailable deterministic tests and REAL_ENVIRONMENT for authentic target-Mac audio/WKWebView, as independent evidence.

## Design decision — task model first

One **Meeting → Speaker** tab, not another flow/page. Main hierarchy:
1. Header `Riconosci le voci` with truthful reviewed/remaining progress; status info below. No raw provider/engine in normal UI.
2. At wide widths: compact **speaker navigator** (left, ~260–320px) + **selected speaker inspector** (right). Highlight selected voice, counts and status; scroll independently without losing selection.
3. Inspector: large **Ascolta un campione** (play/pause, ~6s), **Altro campione** (up to 3 non-overlapping points), inline transcript excerpt + absolute timestamp and source, name input and commit feedback, `Ascolta gli interventi` playlist. Secondary `···` actions for merge/exclude.
4. Plain rows show one short name, status (`Da identificare`, `Confermato`, `Da verificare`, `Ignorato`) and utterance count; hide raw cluster ID, track/model detail behind `Dettagli tecnici`.
5. Below inspector, small chronological turn list `[timestamp] excerpt` for current person (bounded/virtualized). Selecting a turn seeks original audio. Benchmarking and manual engine review remain collapsed secondary tools.
6. Compact app window: same list→expanded inline inspector, not miniature forced two-column grid or a second route. Remember selection when resizing/back.

### Reference wireframe — wide (conceptual, not implemented)

```text
Meeting / Speaker
Riconosci le voci                 3 di 7 confermate   [Verifica rimanenti]
────────────────────────────────────────────────────────────────────────
 VOCI                                     VOCE SELEZIONATA
 ▶ Mario Rossi             ✓ 128         Mario Rossi                 [•••]
   Speaker 2               ·  93         [▶ Ascolta campione  0:06] [Altro]
   Speaker 3               ·  45         «Possiamo rivedere il piano...»
   Tu                      ✓ 201         14:26–14:32 · audio sistema
   Speaker 5               ·  82
   Speaker 6          ⚠ 0 segmenti       Nome [ Mario Rossi       ]  Salvato ✓
   Da attribuire              12         [▶ Ascolta i suoi interventi]
                                           1/128   14:26   [◀] [Ⅱ] [▶] [Vai al testo]
                                           ─────────────────────────────────
                                           14:26  «Possiamo rivedere...»
                                           16:04  «Per il prossimo sprint...»
                                           ...
                                           [Dettagli tecnici] (closed)
────────────────────────────────────────────────────────────────────────
 [Rivedi diarizzazione Community-1]  [Confronta motori] (collapsed)
```

Counts/names/times are **illustrative**, not app data. Never show a second "Computer" voice if its only origin is a track label: when ambiguous, show under source details until proven otherwise. A real cluster with 0 transcript turns is still reviewable from matching raw timeline evidence.

### Reference wireframe — compact

```text
Riconosci le voci   3/7
[Da identificare · 4] [Tutte]
▸ Mario Rossi                 ✓ 128
▾ Speaker 2                    · 93
    [▶ Ascolta 6s] [Altro]
    [Nome _____________________]
    [Ascolta i suoi interventi] [···]
▸ Speaker 3                    · 45
▸ Tu                          ✓ 201
[Revisioni avanzate ▾]
```

No permanent waveforms or decorative avatar grid; an amplitude bar is allowed only from real local media evidence and only if it improves scrubbing. Existing ClosedRoom semantic CSS tokens/Lucide icon set must be reused; no new UI kit or brand. Speaker names 14–16px+; metadata readable at 12–13px+, normal-case labels, visible focus, semantic status text instead of color only. Restrained 120–200ms transitions only where state continuity benefits; reduced motion disables them.

## Critical journeys and interaction copy

| Intent | Input → feedback → outcome/recovery |
| --- | --- |
| Identify | Select unreviewed row → play sample → edit name → Enter/blur commits *one speaker* after validation → inline `Salvataggio…` → `Salvato`, focus stays logical; Escape reverts unsaved typing; conflict preserves input and offers reload/retry. No global Save for normal path. |
| Hear other evidence | `Altro campione` rotates among up to 3 separated, genuinely available clips (3–8 seconds); show `Campione non disponibile` with explanation when no source evidence/audio. |
| Merge | Contextual `Unisci con…` → select target → A/B listen each identity + before/after segment counts → explicit `Unisci` → collapse source under target and `Annulla modifica`. Prevent self/cycles/stale preview; show provenance on demand. |
| Exclude | `Escludi questa voce` → preview count; 0 turns: hide the spurious identity; >0: move all its visible turns to `Da attribuire`, never delete words/time/audio → confirm, undo/restorable list. Label action honestly. |
| Verify | `Ascolta i suoi interventi` → one media controller plays original source-track intervals in time order, skipping unassigned intervals; prev/next/pause, `n/N`, timestamps, excerpt, jump-to-transcript, clear `Torna all'ascolto completo`. Playback must end/stop on selection, route or recording change. |
| Fix one passage | In speaker playback or transcript companion, select one timestamped passage → `Correggi speaker di questo intervento` (advanced) → choose existing/Unidentified and confirm; only identity metadata changes; rollback. Include as later scope if segment edits require separate contract. |
| Recover | Local media missing, short/overlap sample, permission/range error, stale revision, imported text-only, recording deleted, demo read-only → no fake playback or silent network fallback; explain next available action and preserve edits. |

**No autoplay** when opening Speaker or changing selection. Playing *all* turns requires explicit `Ascolta i suoi interventi`. Inline sample play stops at end; only one audio controller can be active in Meeting. Media labels must not imply separated sound: if mixed track contains overlapping voices, show `Contiene voci sovrapposte` where overlap evidence exists; playback follows detected intervals, not acoustic source separation.

## Content and trust constraints

- **Real identities vs audio tracks:** distinguish `speaker entity`, raw `provider_speaker` cluster, mic/system/mixed *track*, per-turn overrides, and display name. A label `Computer` or `Tu` can mean source/provenance; never silently count an internal source label as a separate human. Confirm if the mic is truly a stable single speaker before defaulting to `Tu`.
- **Sample API:** return bounded intervals `{cluster_id,track_id,start,end,kind,provenance,revision}` from true transcript turns; if 0 turns use native timeline linked to this exact transcription diarization revision, *not* an arbitrary latest benchmark. Disallow stale/foreign recording IDs. Choose primary clean 3–8s, separated secondary samples, prefer low overlap and stable continuous speech; avoid fabricated waveforms. Audio is fetched on user play from existing authenticated loopback media endpoint; if locally absent due to opted-in storage tier, show unavailable and require explicit documented retrieval path rather than remote fallback.
- **Speaker grouping:** original raw IDs and audio untouched. Canonical revision layer maps raw IDs to reviewed identities and stores ignored identities; merge groups original IDs, including mixed mic/system when explicitly confirmed, without rewriting `provider_speaker`. Segment-level correction (if implemented) overrides group mapping for that turn only.
- **Text invariant:** ASR `text`, `words`, per-segment `start/end/text`, recording ID, media and original diarization output invariant. Speaker display projection affects transcript labels, search/export/analysis **where consumer contracts use speaker metadata**, never silently regenerate an existing analysis run or edit original canonical text.
- **Conflict/undo:** versioned optimistic token tied to same recording/transcription, durable locally private atomic persistence, one-step `Annulla` after a committed speaker action. Community-1 preview/apply/undo and manual review must share one coherent speaker revision policy; stale operations return 409 and require refreshing. No separate frontend-only speaker store. A renamed speaker with an identical name to another never auto-merges.
- **Queue:** source-track-aware, bounded list from canonical projection; exclude false identities; merged speaker includes all original clusters. Overlaps handled deterministically and marked; if source track cannot be played, stop with clear error, never play wrong audio. Clear audio/object URLs/listeners on interruption/navigation.
- **Privacy:** 127.0.0.1 loopback auth/origin enforced; no cloud, remote fallback, telemetry of voice/text, external voice identity provider or generated audio asset. Full transcript and diarization evidence are private local data.

## State and accessibility matrix

| State | Visible contract | Guard/proof |
| --- | --- | --- |
| New/unreviewed | `Speaker N`, `Da identificare`, active listen | no forced naming |
| Selected / sampling | selected row + pause/seek/end label | one player; time-bounded source |
| Named / saving / saved | field+inline status | Enter/blur commit, Escape discard |
| Playlist playing | `Intervento n/N` + timestamp + transcript excerpt | only selected reviewed group |
| Merge / exclude preview | 2 voice samples + impact count | confirm required, no source deletion |
| Undo available | contextual `Annulla ultima modifica` | revision-bound, survives reopening |
| Conflict | `Il meeting è cambiato`, keep draft + refresh action | no stale overwrite |
| No ASR match | `Nessun intervento collegato al testo`, raw clip if safe | distinct from no speech |
| No local audio | disabled listen + explanation | no fake sample / cloud fallback |
| No diarization / imported text / demo | clear empty/read-only state | no controls advertising impossible work |

Keyboard: tab order follows selected list→inspector→actions; Enter/Space activate controls; Escape cancels rename/merge, merge dialog restores focus to trigger; focus cannot hide behind sticky controls. Accessible button names: `Ascolta campione 2 di Speaker 3`, `Unisci Speaker 3 con…`; status announcements with `aria-live` but not on every audio time tick. Source labels and speaker names distinguishable without color. Test long names, 200% text zoom, IT/EN, reduced motion, 1280/900/640 viewport *contexts* plus packaged WKWebView.

## Delivery graph — bounded owners and dependency

| ID | State | Independently observable slice | Owner/write boundary | Depends |
| --- | --- | --- | --- | --- |
| SR-0 | DONE | Product task, UX/UI layout, microcopy, risk and acceptance modeled | this workstream + new `interaction-quality-review` local skill | dev source |
| SR-1 | READY | Read-only sample refs for transcript and unmatched current diarization timeline; safe audio range/track behavior | `RecordingStore`/read API, sample selector, backend tests | SR-0 |
| SR-2 | READY | Versioned speaker correction operations (rename/merge/exclude/reassign if feasible), same owner and rollback policy | `speaker_labels.py`, `TranscriptionStore`, transcription router, tests | SR-0 |
| SR-3 | BLOCKED | One local playback controller for sample and selected-speaker queue, cleanup and truthful overlaps | meeting playback hook, focused frontend tests | SR-1 API |
| SR-4 | BLOCKED | Wide/compact master-detail with row names, samples, merge preview, exclude, progress, undo | `SpeakerDiarizationEditor.tsx`, scoped components, UI tests | SR-2/3 |
| SR-5 | BLOCKED | Integrate single player/revision with Meeting, Community-1 and transcript view; fix `Computer` classification by evidence | `MeetingDetailPage.tsx`, consumer tests, no parallel ownership | SR-2/3/4 |
| SR-6 | BLOCKED | Required exact-head INTEGRATION evidence, visual/full-media + source gates, docs, UI acceptance and merge readiness | preflight, UX contract, feature docs | SR-1..5 |

Parallel execution: SR-1 and SR-2 can run independently after shared DTO review; no concurrent edits to speaker editor or meeting shell. If per-turn override significantly expands scope, keep it as a dedicated follow-up rather than blocking fast identify/merge/exclude/playlist.

## Evidence and acceptance

**Core acceptance:** 1) recognize/name a voice via genuine local sample; 2) A/B-compare and merge two clusters with preserved original turn attribution, surviving reload and reversible; 3) exclude a spurious 0-turn cluster without data loss; exclude nonempty cluster only into Unidentified; 4) hear only selected intervals in order (with known overlap caveat), jump-to-transcript; 5) zero-match raw-timeline clip only when exact source proof exists; 6) one speaker row clearly distinguishable from source `Computer`; 7) stale edits cannot overwrite newer Community-1 or user changes; 8) no new network/telemetry/media-copy boundary.

Run focused unit/API `test/test_speaker_labels.py`, `test/test_diarization_review.py`, `test/test_diarization_review_api.py`, new selector/revision/audio tests, frontend lint + TS; add browser journey on deterministic fixtures including 7+ speakers, zero turns, sample failure, merge preview/undo, compact keyboard. Use actual repo `scripts/select_validation_profile.py` (never downgrade selected profile). At PR→dev: full diff, exact source/base, STRONG gate selection and affected material UI `FULL_MEDIA`. At dev→main: RELEASE/FULL plus applicable interactive WKWebView, VoiceOver, TCC/real track seek evidence on target Mac; no synthetic browser pass presented as physical audio proof. Success metrics to measure: seconds and actions to recognize a voice, correction time, mistaken merges, completion rate, and recovery from error (baseline unknown, avoid invented targets).

## References and resume checkpoint

Internal: `AGENTS.md`, `skills/design-product-experience/SKILL.md`, `skills/interaction-quality-review/SKILL.md`, `design/ux-contract.json`, `design/brand-kit.json`, and native source/tests cited above. External pattern inspiration (do not copy design systems): [Anthropic frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md); [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines); [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill); [Apple split view](https://developer.apple.com/design/human-interface-guidelines/split-views); [Otter speaker management](https://help.otter.ai/hc/en-us/articles/40586357592471-Speaker-Management); [Fireflies speaker edits](https://guide.fireflies.ai/articles/4994477228-how-to-edit-speaker-labels-or-names-in-a-transcript). Public examples describe workflow inspiration, not ClosedRoom implementation or local data processing.

Base observed: `dev` `779009b2d6fbb1cdff40aa6f3b20419f760ca075` on 2026-11-04; refresh before implementation/integration. Confirmed: current editor only names, existing authenticated track audio endpoints and saved diarization summary, `TranscriptionStore` fingerprint/undo for Community-1. Pending: actual raw-timeline file consumer, `Computer` provenance, time alignment and media seek on packaged WKWebView, exact current integration head. Next discriminating action: inspect recording timeline storage and current catalog projections, freeze audio-sample DTO and speaker revision token, then begin SR-1/SR-2 in parallel. Transfer implemented UX to `design/ux-contract.json` and affected feature docs only when code is real; after completion update current-state and delete temporary workstream by default.
