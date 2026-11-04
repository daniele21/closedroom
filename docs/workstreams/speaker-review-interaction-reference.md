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

- **Person ≠ raw cluster ≠ mic/system track:** `Computer` is often a source name, not a human. Keep cluster ID provenance in technical details; `Tu` only when backed by actual mic identity.
- **Sample contract:** bounded `{cluster_id,track_id,start,end,kind,revision}`, true transcript turns or raw native timeline for the exact transcription engine/revision. Never use unrelated benchmark output, fake voice waveforms or silent cloud fallback. Audio loads only on explicit user play through authenticated loopback.
- **Correction contract:** persist reviewed identity mapping while preserving raw `provider_speaker`, ASR text/words/times, source media and IDs. Merge reuses all original clusters; exclude nonempty voices into `Non identificato`. Any per-turn correction overrides the group only when explicitly implemented.
- **Safety:** optimistic fingerprint, private atomic one-step undo from `TranscriptionStore`, stale 409 rather than overwrite, coherent Community-1 rollback. Playlist follows only canonical groups, checks track identity, stops on errors/navigation, and discloses overlapping voices. Never export local audio or text.
- **Privacy:** no remote speaker detection, embeddings, telemetry, cloud read or remote fallback.

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



## Design rationale and usability check

The repeated form grid is slower to scan; a wizard adds navigation. Keep one inspector and inline compact details. Test naming, distinguishing sources from people, safe merge/undo, overlap caveat, and true timestamp seeking. Measure task success and error rates.

External patterns: [Anthropic](https://github.com/anthropics/skills), [Vercel](https://github.com/vercel-labs/agent-skills), [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
