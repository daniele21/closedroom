# Speaker experience — redesign minimale della diarizzazione

> Piano di sviluppo · 2026-11-05 · PLANNED · base `dev@0924d0860fd4f80c05b77c33067779c948e259d8`

**Scope:** PRODUCT_FEATURE · DELIVERY: ITERATION → INTEGRATION (PR incrementali verso `dev`) · VALIDATION: selector repo, atteso STRONG per dati/audio/cross-boundary e FULL solo se selezionato · EXECUTION: REMOTE_AUTOMATED Mac CI, REAL_ENVIRONMENT solo per evidenza fisica. Le quattro dimensioni sono indipendenti.

## 1. Problema, esito e vincoli

L'utente apre Meeting → Speaker e vuole capire **chi ha parlato, quando e come correggere una voce**. Oggi la schermata presenta tre esperienze contemporanee: `SpeakerDiarizationEditor` (elenco/dettaglio), `SpeakerTimeline` (timeline separata), `CommunityOneReviewPanel` + `DiarizationBenchmarkPanel` (revisioni e confronto tecnico). Sono presenti due liste della stessa identità, più player, una sorgente audio che può sembrare una persona e controlli di motore sul percorso ordinario.

**Evidenza iniziale:** gli screenshot del meeting mostrano un campione di Giulia a **25:15** ma la timeline a **0:00–0:01**, cinque voci e **zero segmenti trascritti attribuiti**. In `MeetingDetailPage.tsx` viene calcolato `recordingDuration` ma non passato all'editor; `SpeakerTimeline.tsx` riceve `durationSeconds=0`, non usa `getDurationSeconds` e finisce in `Math.max(1, ...)`. Il server restituisce intervalli in una finestra richiesta e l'etichetta `coverage` riassume i soli intervalli ritornati. Il campione audio non implica che tutti i turni ASR siano attribuiti.

**Esito osservabile:** un'unica vista «Voci» per meeting: nome + pulsante d'ascolto + segmenti su asse temporale comune, un solo player contestuale e azioni di correzione nella stessa riga/pannello inline. L'utente può verificare una voce senza comprendere cluster, provider, sorgenti o motori.

**Non-goal:** nessun nuovo riconoscimento biometrico/identificazione automatica delle persone; nessuna separazione acustica delle voci; niente ricalcolo automatico; nessuna nuova pagina, store duplicato o backend cloud; non riscrivere audio, testo e timestamp originali; non nascondere anomalie o inventare segmenti.

**Rischi di prodotto:** VALUE = permettere davvero la verifica degli speaker; USABILITY = non far interpretare «Computer» e «0 interventi» come persone/assenza di audio; FEASIBILITY = distinguere tempi nativi dalla proiezione ASR e mantenerli bounded; VIABILITY = riusare owner e componenti canonici. Privacy/reliability = audio locale solo dopo Play, nessun upload implicito, niente perdita dei dati o delle revisioni, riproduzione cancellabile.

## 2. Modello utente e architettura informativa

- **Persona** = nome riconosciuto o «Voce N» da identificare; può raggruppare più cluster dopo una fusione. Un cluster tecnico non è automaticamente una persona.
- **Sorgente** = microfono, computer o traccia mista. «Computer» resta sotto «Origine audio»/diagnostica e non diventa una riga partecipante. «Tu» è un nome solo quando il mapping corrente lo giustifica; altrimenti indicare «Microfono» come origine.
- **Intervallo** = presenza di una voce nell'audio, con inizio/fine e track ID. Può essere sovrapposto e può esistere senza frase ASR; cliccarlo riproduce il **mix registrato**, non una traccia vocale isolata.
- **Frase attribuita** = segmento della trascrizione con speaker assegnato. Mostrare la relativa quantità solo come metrica secondaria, non confonderla con gli intervalli audio.
- **Revisione** = calcolo opzionale e successiva applicazione esplicita; rollback/versione gestiti dall'owner esistente.

### Journey canonico

`Apri Voci → seleziona voce ancora ignota → ascolta campione → inserisci nome → verifica sulla sua riga temporale → (eventualmente unisci/escludi) → feedback salvato e Annulla → torna al meeting`.

Quando tutto è confermato, lo stesso schermo diventa consultazione, **non** un editor vuoto. Un solo punto di accesso al task di miglioramento del riconoscimento, senza nuovo livello di navigazione.

### Wireframe desktop (contenuto, non nuovo design system)

    VOCI                        3 identificate · 2 da identificare   [···]
    Chi ha parlato                                       [Tutto] [5 min ▾]
                         00:00         10:00        20:00       30:00
    ▷ Ismet       ✓       ██       █████            ███
    ▷ Andrea      ✓           ██             ███       █
    ▷ Giulia      ✓              ██              ███       ██
    ▷ Voce 4      ?                 ███          ██
    ▷ Voce 5      ?           ██                    ██
    ───────────────────────────────────────────────────────────────
    Voce 4 · campione 2 di 3         [▶ Ascolta] [Nome persona ____]
    [Ascolta tutti gli intervalli]   [··· Unisci / Escludi / Ripristina]
    Riproduzione: ▶ 18:32  ━━━━━━━  18:39  [Vai al testo quando esiste]
    [Migliora riconoscimento ▾]  (solo se necessario)

**Schermo stretto (640 px):** stessa gerarchia; timeline condivisa navigabile sopra, righe speaker sotto a piena larghezza, selezione con dettaglio inline immediatamente sotto la riga, player accessibile senza scroll orizzontale della pagina. A 900/1280 px nessuna seconda sidebar dell'app e niente riduzione indiscriminata dei testi.

**Gerarchia delle azioni:** stato `pending` → primaria «Ascolta campione» e input nome; `confirmed` → «Ascolta»/«Verifica»; `error` → «Riprova»; `processing review` → avanzamento e Annulla; fusione/esclusione in menu contestuale; opzioni tecniche solo in disclosure avanzata. Un solo comando d'ascolto attivo alla volta.

## 3. Piano incrementale e dipendenze

| ID | Deliverable (risultato verificabile) | Owner / file da modificare | Dipendenze | Stato |
| --- | --- | --- | --- | --- |
| **SPK-0 — P0: integrità temporale** | La timeline rappresenta la durata verificata del meeting, o dichiara chiaramente quella sconosciuta; il campione al minuto 25 resta raggiungibile anche con zero segmenti ASR. Copertura riferita al meeting intero, distinta dai risultati della finestra. | `MeetingDetailPage.tsx`, `SpeakerTimeline.tsx`, `utils/formatters.ts`; `speaker_review.py`, router timeline solo se serve un summary read-only. | Nessuna | READY |
| **SPK-1 — P0: contratto voci/evidenze** | Normalizzare nel read-model UI persona/gruppo vs sorgente/cluster, stato identificazione, intervalli audio vs frasi ASR; preservare raw evidence e associazioni con JobStore Community-1. Correzioni/undo riconciliano gruppi senza mutare fonti. | `speaker_labels.py`/`speaker_review.py` come owner, client types; test owner/API | SPK-0, definire shape prima della UI | READY |
| **SPK-2 — P1: vista unificata** | **Una riga per persona** con nome, stato, play e intervalli; overview compatta e dettaglio zoomato sulla stessa scala. Nessuna lista duplicata, «Computer» non è persona, sovrapposizioni distinguibili. Aggregazione visiva bounded per meeting lunghi; nessun segmento inventato. | `SpeakerTimeline.tsx` / nuovo componente presentazionale solo se davvero necessario; `SpeakerDiarizationEditor.tsx` come orchestratore | SPK-0 + SPK-1 (shape congelata) | BLOCKED |
| **SPK-3 — P1: singolo player e correzioni** | Selezione, campioni 1/3, ascolto sequenziale di intervalli nativi anche con 0 segmenti ASR, rinomina inline, fusione/esclusione/recovery e undo; stato Playing sempre sincronizzato. Stop su cambio meeting. | `useSpeakerReviewPlayback.ts`, `SpeakerDiarizationEditor.tsx`, API esistenti | SPK-1; coordinare integrazione con SPK-2 | BLOCKED |
| **SPK-4 — P2: progressive disclosure** | «Migliora riconoscimento» apre l'attuale preview→applica→rollback; benchmark A/B e dettagli tecnici restano in strumenti avanzati. Nessuna rimozione di capacità o job già esistenti. | `MeetingDetailPage.tsx`, `CommunityOneReviewPanel.tsx`, `DiarizationBenchmarkPanel.tsx`; UX contract | SPK-2 + SPK-3 | BLOCKED |
| **SPK-5 — P2: rifinitura e integrazione** | Microcopy it/en, focus, tastiera, VoiceOver, riga selezionata/empty/error/loading/partial, contrasto, compact, 200% text, FULL_MEDIA, documentazione canonica e preflight. | design contract, test E2E, regression snapshots, docs | SPK-0..4 | BLOCKED |

**Sequenza delle PR:** PR-A SPK-0 + read-model SPK-1; PR-B SPK-2 con nuovo layout; PR-C SPK-3 media/editing; PR-D SPK-4 + SPK-5 UX hardening. Tutte su branch feature dedicati basati sul `dev` aggiornato e verso `dev`, nessuna verso `main`. Sono milestone, non quattro implementazioni da avviare simultaneamente senza contratto.

**Parallelizzabile in sicurezza:** durante PR-A, un agente può preparare fixture/test E2E senza scrivere nei file del backend; durante PR-B, un altro può studiare i contratti di playback e scrivere test hook in un file distinto. Non assegnare contemporaneamente a due agenti `SpeakerDiarizationEditor.tsx` o `MeetingDetailPage.tsx`. Dopo ogni merge riallineare gli altri branch e rieseguire i gate invalidati. PR #186 (startup non distruttivo) è indipendente, ancora aperta; non assumerla integrata e non cambiare porte, packaging o runtime in questo workstream.

## 4. Acceptance e falsificazione — dati

1. **Durata:** fixture meeting 30:00 senza segmenti trascritti, sample a 25:15, 5 cluster nativi, mic+system. Asse almeno 30:00 se durata verificabile; mai 0:01. Se fine recording sconosciuta, mostra indicatore «durata non verificata» e non inventa `30:00`.
2. **Fonte temporale:** endpoint query 00:00–05:00 vuoto ma audio rilevato 25:15–25:22: overview/seek consentono localizzare l'intervallo; stato full-vs-partial non deriva soltanto dal sottoinsieme visibile.
3. **Identità:** 3 persone confermate + 2 ignote + «Computer» come sorgente: stato conteggio 3/5, cinque righe umane, non sei; source track rimane recuperabile nella diagnostica.
4. **Assenza ASR:** quando esistono intervalli di diarizzazione, il player «Ascolta questa voce» non viene disabilitato solo perché `transcript_segment_count=0`; il link al testo è disabilitato con motivazione.
5. **Provenienza:** una run Community-1 deve corrispondere a transcription, recording, job, track e cluster set; run mancante/stale/non corrispondente provoca fallback esplicitamente etichettato o assenza evidenza, mai riuso di run diversa.
6. **Timeline lunga:** 30/60/120 min e >5000 intervalli: nessun overflow JS/DOM, API bounded, viewport che carica solo finestre e overview aggregata in bucket a densità definita; eventi microscopici navigabili con zoom. Misurare render/richieste in Mac CI; scegliere una soglia dal baseline, non inventarne una.
7. **Persistenza:** rename/merge/exclude/restore e rollback dopo review non cambiano audio, testo, parole né start/end; non cambiano le etichette degli speaker sbagliati e non perdono revisioni in caso di stale fingerprint.
8. **Privacy:** nessun fetch bytes audio prima di Play; solo loopback autenticato, nessun servizio remoto/silent fallback, nessuna duplicazione del file audio; solo un player con pulizia `pause/revoke/abort` su unmount/cambio meeting.

## 5. UX state matrix / behavior

| Stato | UI principale | Azione ed esito/recovery |
| --- | --- | --- |
| Iniziale | Nomi + timeline completa o etichetta durata ignota, pending evidenziati | Play campione o scegli voce |
| Voce selezionata | Una sola riga attiva, editor inline | Invio salva, Esc annulla; focus ritorna alla riga |
| Riproduzione | Player persistente con tempo assoluto e cue nella riga | Play/pause/next/stop e salto intervallo senza avviare due audio |
| Salvataggio | Etichetta «Salvataggio…», controlli conflittuali disabilitati | Successo «Salvato» + undo, non mostrare prima del commit |
| Fusione/esclusione | Menu contestuale + conferma con conseguenze | Preview persone coinvolte; nessun testo cancellato; undo |
| Stale/conflitto | Messaggio azionabile, nessun salvataggio silenzioso | Ricarica la versione corrente e riprova |
| Nessun intervallo | «Non ci sono intervalli verificabili», non barra piena artificiale | «Migliora riconoscimento» se dati/runtimes idonei |
| Solo trascrizione | Copertura «Intervalli attribuiti al testo; audio non completo» | Riproduci i segmenti disponibili |
| Audio non locale | Tempo/voce ancora visibili, play disabilitato | Spiega disponibilità senza fetch cloud implicito |
| Processing/error/undo | Barra job con cancel e preview; errore riprovabile | Apply esplicito; undo esatto; recovery senza mutation nascosta |

## 6. Test plan e gate (obbligatori)

- **Unit/data:** `test/test_speaker_timeline.py`, `test/test_speaker_labels.py`, `test/test_speaker_review.py`, `test/test_diarization_review_api.py` ampliati con fixture 25:15, 0 ASR, sorgente vs persona, overlap, paginazione/coverage, revision fingerprint, source missing e long meeting.
- **Frontend:** lint/typecheck e test selezione/row + player hook (eventi aria, un solo stream, start/stop/abort, focus). Usare semantic tokens esistenti; non introdurre CSS globale parallelo.
- **End-to-end:** ampliare `scripts/browser_saved_meeting_e2e.mjs` con journey «apri → ascolta campione → nomina → verifica riga 25:15 → unisci → undo → rivedi → applica review → rollback» e snapshot FULL_MEDIA; verificare 1280/900/640 CSS px, localizzazione it/en, 200% scaling e invalid states.
- **Gates:** all'inizio e prima di ogni PR/merge invocare selector e preflight del repository; minimo scoped su UI pura, STRONG sulle modifiche ai contratti audio/API/persistenza, FULL se il selector lo richiede. Run Mac via `daniele21/local-runner-infra`, evidence exact HEAD/base e nessun PASS inventato; integrazione richiede FULL_MEDIA quando il journey cambia.
- **REAL_ENVIRONMENT:** su app macOS installata verificare playback locale, TCC/audio reale, overlapping speaker, window resizing e VoiceOver; questa evidenza non è sostituibile da browser/runner automatizzato e rimane gate reale di RELEASE. Non cambiare `main` in questo piano.

## 7. Decisioni e rischi prima di scrivere codice

- Prima distinguere errore di asse temporale da assenza di job / raw diarization nel meeting reale; non simulare timeline completa se il dato manca.
- La durata deve avere **un solo owner canonico**, non due calcoli concorrenti in React: preferire metadata RecordingStore e fallback verificato; esporre uno stato unknown dove manca l'evidenza.
- L'overview completa e il dettaglio zoomato possono richiedere un summary API bounded per bucket/coverage; estendere il router attuale, non introdurre un secondo store né inviare voce/testo.
- Non utilizzare il conteggio dei segmenti ASR come numero di interventi audio; non visualizzare «Computer» come speaker umano.
- Preserve invariants of PR #186 when merged: isolated dev data and non-destructive startup; **this plan must not modify** runtime/process lifecycle.
- La metrica di successo UX va validata con prove di task su meeting vero: utente individua e nomina una voce sconosciuta senza aprire strumenti avanzati, si orienta nel meeting lungo e recupera una correzione errata. Shipped ≠ product-success.

## 8. Resume checkpoint / completion

- **Checkpoint:** 2026-11-05, base `dev@0924d086`; current branch `plan/speaker-experience-redesign-20261105`; PR #186 di startup è aperta e indipendente. Nessuna modifica applicativa avviata da questo piano.
- **Confirmed:** 0:01 nello screenshot non corrisponde al sample a 25:15; editor riceve durata di default 0 e timeline usa `Math.max(1,...)`; frontend riproduzione campioni usa hook condiviso; tre tool-panel vengono montati nello stesso tab. Non confermata la disponibilità completa dei raw turn del meeting reale.
- **Next discriminating action:** creare fixture che riproduce screenshot e catturare un payload privacy-safe della timeline (`duration`, `interval_count`, `coverage`, `origin`, `job id present` senza audio/testo) prima del fix. Poi PR-A.
- **Exit:** tutte le PR integrate in `dev`, source + FULL_MEDIA PASS su HEAD coerenti, gate applicabili soddisfatti, doc canonicali aggiornati, release gap REAL_ENVIRONMENT chiaramente dichiarato. Spostare in `design/ux-contract.json` solo regole d'esperienza consolidate, poi eliminare/chiudere il piano attivo secondo document policy.
