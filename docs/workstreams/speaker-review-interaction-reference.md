# Speaker Review — interaction design reference (PROPOSED, not shipped)

Status: PROPOSED; only `docs/workstreams/speaker-review-workspace.md` owns the workstream checkpoint. This is bounded task/interaction source material for the upcoming implementation; after delivery, transfer realized contract to `design/ux-contract.json` and remove this temporary reference. No new visual design-system owner.

Scope: canonical Meeting → Speaker tab, aligned with `skills/design-product-experience/SKILL.md` and `skills/interaction-quality-review/SKILL.md`. Reference data and examples are fictional.

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



## Deliberate alternative considered

The existing two-column grid of identical speaker forms is expensive to scan; a giant timeline-first design hides quick naming; a separate speaker-setup wizard creates unnecessary navigation. Choose a selected-person inspector instead. If a narrow screen makes split view cramped, collapse to an inline selected detail rather than shrinking the controls.

## Validation questions for usability sessions

Can a user: (1) name the first unfamiliar speaker without opening a diagnostic drawer; (2) understand that “Computer” may be a sound source; (3) compare two samples before merging; (4) recover a mistaken exclusion; (5) recognize that isolated *intervals* can still contain overlapping speech; and (6) return to transcript at the true timestamp? Gather task time, confusion points and wrong identity assignments; do not infer success from appearance.

## References

[Anthropic frontend design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md), [Vercel web guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines), [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), [Apple split views](https://developer.apple.com/design/human-interface-guidelines/split-views), [Otter Speaker Management](https://help.otter.ai/hc/en-us/articles/40586357592471-Speaker-Management), [Fireflies speaker edits](https://guide.fireflies.ai/articles/4994477228-how-to-edit-speaker-labels-or-names-in-a-transcript).
