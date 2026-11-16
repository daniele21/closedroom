# Speaker experience — redesign minimale della diarizzazione

> Piano di sviluppo · 2026-11-05 · ACTIVE · base `dev@0924d0860fd4f80c05b77c33067779c948e259d8`

**Scope:** PRODUCT_FEATURE · DELIVERY: ITERATION → INTEGRATION (PR incrementali verso `dev`) · VALIDATION: selector repo, atteso STRONG per dati/audio/cross-boundary e FULL solo se selezionato · EXECUTION: REMOTE_AUTOMATED Mac CI, REAL_ENVIRONMENT solo per evidenza fisica. Le quattro dimensioni sono indipendenti.

## 1. Problema, esito e vincoli

Utente: chi ha parlato? Quando? Come correggere un'identità? Ora `SpeakerDiarizationEditor`, `SpeakerTimeline`, `CommunityOneReviewPanel` e `DiarizationBenchmarkPanel` creano liste, player e controlli tecnici concorrenti.

**Bug P0 osservato:** campione Giulia a **25:15**, timeline **0:00–0:01**, cinque voci con zero segmenti ASR. `MeetingDetailPage.tsx` calcola `recordingDuration` ma non lo passa all'editor; `SpeakerTimeline.tsx` riceve 0 e usa `Math.max(1,...)`. `coverage` sul server descrive la finestra, non necessariamente l'intero meeting. Non sappiamo ancora se il raw del meeting reale è accessibile.

**Outcome:** una sola vista «Voci», una riga per persona con play + intervalli sulla stessa scala, un player, rinomina e correzioni inline, tecnicismi solo su richiesta. **Non-goal:** speaker identification biometrica, separazione audio, ricalcolo automatico, nuovo store/pagina/provider, cloud fallback, cambi ai file audio o al testo/timestamp ASR.

**Rischi:** valore = riconoscere persone con facilità; usabilità = non confondere sorgente e persona o segmenti ASR e intervalli audio; fattibilità = provenance e finestre bounded; sostenibilità = riuso di API, store, player e undo canonici. Audio sempre locale e fetch solo dopo Play.

## 2. Modello utente e UX target

- **Persona:** «Voce N» oppure nome confermato; una persona può raggruppare cluster dopo merge. **Sorgente:** mic/Computer/mixed, mai automaticamente un partecipante. «Tu» solo se il mapping lo conferma.
- **Intervallo audio** con track/start/end ≠ **frase attribuita** nella trascrizione; può esistere con 0 frasi. Gli overlap sono ascoltabili ma non isolati acusticamente.
- **Journey:** apri Voci → ascolta campione della voce ignota → inserisci nome (Invio salva, Esc annulla) → verifica gli intervalli → eventualmente unisci/escludi → undo → torna al meeting.

    VOCI              3 identificate · 2 da identificare     [···]
    Chi ha parlato?                               [Tutto] [5 min]
                      0:00         10:00        20:00      30:00
    ▷ Ismet  ✓         ███          ██              ██
    ▷ Andrea ✓           ███           ██             ██
    ▷ Giulia ✓                ███              ██
    ▷ Voce 4 ?             ██             ███
    ▷ Voce 5 ?                   ██              ███
    Voce 4 [▶ Campione 2/3]  [Nome persona ______] [···]
    Player unico: ▶ 18:32 ━━━━━ 18:39 [Vai al testo se esiste]
    [Migliora riconoscimento ▾] (opzionale)

Wide: una riga per speaker, una scala, nessuna seconda sidebar. Compact 640 px: timeline navigabile e dettaglio sotto la riga; niente overflow globale. Stati: pending → ascolta/nomina; confirmed → verifica; errore → recupera; review job → progresso/annulla. Fusione, esclusione, benchmark e cluster solo contestuali/avanzati.

## 3. Piano incrementale e dipendenze

| ID | Deliverable (risultato verificabile) | Owner / file da modificare | Dipendenze | Stato |
| --- | --- | --- | --- | --- |
| **SPK-0 — P0: integrità temporale** | La timeline rappresenta la durata verificata del meeting, o dichiara chiaramente quella sconosciuta; il campione al minuto 25 resta raggiungibile anche con zero segmenti ASR. Copertura riferita al meeting intero, distinta dai risultati della finestra. | `MeetingDetailPage.tsx`, `SpeakerTimeline.tsx`, `utils/formatters.ts`; `speaker_review.py`, router timeline solo se serve un summary read-only. | Nessuna | DONE · PR #188 |
| **SPK-1 — P0: contratto voci/evidenze** | Normalizzare nel read-model UI persona/gruppo vs sorgente/cluster, stato identificazione, intervalli audio vs frasi ASR; preservare raw evidence e associazioni con JobStore Community-1. Correzioni/undo riconciliano gruppi senza mutare fonti. | `speaker_labels.py`/`speaker_review.py` come owner, client types; test owner/API | SPK-0, definire shape prima della UI | DONE · PR #188 |
| **SPK-2 — P1: vista unificata** | **Una riga per persona** con nome, stato, play e intervalli; overview compatta e dettaglio zoomato sulla stessa scala. Nessuna lista duplicata, «Computer» non è persona, sovrapposizioni distinguibili. Aggregazione visiva bounded per meeting lunghi; nessun segmento inventato. | `SpeakerTimeline.tsx` / nuovo componente presentazionale solo se davvero necessario; `SpeakerDiarizationEditor.tsx` come orchestratore | SPK-0 + SPK-1 (shape congelata) | ACTIVE · PR #189 |
| **SPK-3 — P1: singolo player e correzioni** | Selezione, campioni 1/3, ascolto sequenziale di intervalli nativi anche con 0 segmenti ASR, rinomina inline, fusione/esclusione/recovery e undo; stato Playing sempre sincronizzato. Stop su cambio meeting. | `useSpeakerReviewPlayback.ts`, `SpeakerDiarizationEditor.tsx`, API esistenti | SPK-1; coordinare integrazione con SPK-2 | ACTIVE · PR #189 |
| **SPK-4 — P2: progressive disclosure** | «Migliora riconoscimento» apre l'attuale preview→applica→rollback; benchmark A/B e dettagli tecnici restano in strumenti avanzati. Nessuna rimozione di capacità o job già esistenti. | `MeetingDetailPage.tsx`, `CommunityOneReviewPanel.tsx`, `DiarizationBenchmarkPanel.tsx`; UX contract | SPK-2 + SPK-3 | ACTIVE · PR #189 |
| **SPK-5 — P2: rifinitura e integrazione** | Microcopy it/en, focus, tastiera, VoiceOver, riga selezionata/empty/error/loading/partial, contrasto, compact, 200% text, FULL_MEDIA, documentazione canonica e preflight. | design contract, test E2E, regression snapshots, docs | SPK-0..4 | ACTIVE · PR #189 |

**Sequenza:** PR #188 SPK-0/1 integrata; PR #189 SPK-2..5 da validare verso `dev`. Nessun merge in `main`.

**Parallelizzabile in sicurezza:** durante PR-A, un agente può preparare fixture/test E2E senza scrivere nei file del backend; durante PR-B, un altro può studiare i contratti di playback e scrivere test hook in un file distinto. Non assegnare contemporaneamente a due agenti `SpeakerDiarizationEditor.tsx` o `MeetingDetailPage.tsx`. Dopo ogni merge riallineare gli altri branch e rieseguire i gate invalidati. PR #186 (startup non distruttivo) è indipendente, ancora aperta; non assumerla integrata e non cambiare porte, packaging o runtime in questo workstream.

## 4. Acceptance — dati e invarianti

1. Meeting 30:00 con campione a 25:15, 5 voci, zero ASR: scala coerente con durata verificata, sample navigabile, mai `0:01`; se durata ignota mostra «durata non verificata». Non inventare 30 minuti.
2. Finestra iniziale senza turn ma voce a 25:15: overview la localizza; distinguere `coverage` globale dalla copertura della finestra. Nessuna barra piena artificiale.
3. 3 nomi + 2 ignoti + sorgente «Computer»: esattamente 5 persone, non 6. `0 frasi` non equivale a `0 intervalli audio`; play possibile se raw presente.
4. Community-1: job/transcription/recording/track/cluster set coerenti; fallback spiegato se stale/missing, mai riuso di raw diverso. Nessun testo o audio nei metadata endpoint.
5. Merge, rename, exclude, restore, apply e rollback conservano audio, parole, testo, segment times e cronologia; niente salvataggio senza fingerprint esatto.
6. Meeting 30/60/120 min e >5000 turn: metadata bounded, zoom/caricamento finestre, overview aggregata fedele, nessun overflow JS/DOM. Misurare prestazioni sul Mac.
7. Nessun download audio prima del Play, un player, stop/abort su navigazione e cambio meeting; niente elaborazione remota.

## 5. Stati e recupero

| Stato | UI e feedback |
| --- | --- |
| Idle/selezionata | Righe e overview; selezione evidenzia una voce; solo un dettaglio inline |
| Playing | Player con tempo assoluto, pausa/next/stop; link testo solo se disponibile |
| Saving/saved | Stato «Salvataggio…», poi «Salvato» + Annulla dopo commit; focus mantenuto |
| Merge/exclude/undo | Menu contestuale, conferma conseguenze, reversibilità verificata |
| Conflitto/stale | Non sovrascrivere; mostra «Ricarica» e riprova |
| Vuoto/solo ASR/solo raw | Stato e copertura veri, azione pertinente, nessuna traccia fittizia |
| Audio non disponibile | Timeline leggibile, play disabilitato con spiegazione, no cloud fallback |
| Job in corso/fallito | Progresso, cancel, preview/apply separati, recovery e rollback |

## 6. Test plan e gate (obbligatori)

- **Unit/data:** `test/test_speaker_timeline.py`, `test/test_speaker_labels.py`, `test/test_speaker_review.py`, `test/test_diarization_review_api.py` ampliati con fixture 25:15, 0 ASR, sorgente vs persona, overlap, paginazione/coverage, revision fingerprint, source missing e long meeting.
- **Frontend:** lint/typecheck e test selezione/row + player hook (eventi aria, un solo stream, start/stop/abort, focus). Usare semantic tokens esistenti; non introdurre CSS globale parallelo.
- **End-to-end:** ampliare `scripts/browser_saved_meeting_e2e.mjs` con journey «apri → ascolta campione → nomina → verifica riga 25:15 → unisci → undo → rivedi → applica review → rollback» e snapshot FULL_MEDIA; verificare 1280/900/640 CSS px, localizzazione it/en, 200% scaling e invalid states.
- **Gates:** all'inizio e prima di ogni PR/merge invocare selector e preflight del repository; minimo scoped su UI pura, STRONG sulle modifiche ai contratti audio/API/persistenza, FULL se il selector lo richiede. Run Mac via `daniele21/local-runner-infra`, evidence exact HEAD/base e nessun PASS inventato; integrazione richiede FULL_MEDIA quando il journey cambia.
- **REAL_ENVIRONMENT:** su app macOS installata verificare playback locale, TCC/audio reale, overlapping speaker, window resizing e VoiceOver; questa evidenza non è sostituibile da browser/runner automatizzato e rimane gate reale di RELEASE. Non cambiare `main` in questo piano.

## 7. Decisioni tecniche e privacy

- Un solo owner canonico della durata (RecordingStore metadata, fallback documentato), mai due calcoli React divergenti. Stato unknown esplicito.
- Preferire read projection su `speaker_review.py` / router attuale per summary overview e coverage **globale** bounded; niente store o cache non giustificata.
- Preserve immutable ASR text/word/start/end and raw cluster IDs. `Computer` è source track, non speaker; `Tu` richiede mapping affidabile.
- PR #186 sul port manager è indipendente e ancora aperta: nessun cambiamento di runtime o packaging in questo redesign.
- Successo prodotto da test di task con meeting reale (riconoscere/nominare/correggere senza tool avanzati), non dal solo merge.

## 8. Checkpoint e completamento

**2026-11-05:** base originale `dev@0924d086`; SPK-0/1 integrati in `dev` via PR #188 (`d5abe344`), test Mac ARM64: 894 Python + FULL_MEDIA PASS. SPK-2..5 implementati nella PR #189 su branch `feat/speaker-minimal-meeting-workspace-20261105`; validazione exact-head e verifica reale ancora pendenti. PR #186 indipendente.

**Verificato:** `recordingDuration` non passa all'editor; durata forzata a ≥1 sec; più componenti nello stesso tab; sample a 25:15 con timeline a 0:01. **Non verificato:** raw completo del meeting reale.

**Prossimo step:** controllare TypeScript/E2E di PR #189 e correggere solo regressioni motivate dai log; validare l'intero journey su Mac. La fixture 25:15/no-ASR e il summary read-only sono presenti in PR #188. Fine lavoro dopo PR su `dev`, gate esatti, FULL_MEDIA, owner/docs allineati e rilascio con evidenza REAL_ENVIRONMENT distinta. Trasferire decisioni consolidate a `design/ux-contract.json` e chiudere questo workstream.

