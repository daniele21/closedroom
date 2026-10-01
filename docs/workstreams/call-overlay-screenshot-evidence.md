 ACTIVE | ACTIVE | ACTIVE | ACTIVE | ACTIVE | ACTIVE |# Overlay chiamata e screenshot come fonti del meeting

Status: ACTIVE
Owner: meeting UX, RecordingStore, NativeCaptureManager e servizi canonici di analisi/job
Read when: implementare o riprendere overlay, screenshot manuali e citazioni visuali
Created: 2026-10-01

## Outcome e decisioni concordate

Overlay compatto per controllare la registrazione e scattare lo schermo intero.
Immagini locali citate nella trascrizione al momento acquisito e apribili dagli
appunti/analisi; audio e testo restano utilizzabili se l'AI fallisce.

- Scatto manuale dell'intero monitor; con più display, selezione esplicita e persistente nella sessione.
- Overlay compatto predefinito; dettagli e anteprima su richiesta, non una dashboard tecnica.
- Timestamp dell'acquisizione effettiva, non del click o della fine del salvataggio.
- Citazione disponibile nella trascrizione senza inferenza visuale.
- Riferimento immagine -> passaggio trascritto/audio e riferimento trascritto -> originale.
- Gli appunti distinguono evidenza visiva, parole pronunciate e inferenze/incertezze.
- Piano futuro: il prototipo della conversazione non è implementazione.

## Non-goals

- Cattura continua, rilevamento chiamate o trascrizione live.
- Area/finestra, annotazioni/redazioni avanzate o pausa audio.
- Riscrittura ASR/runtime, nuovi scheduler/store/index o cloud implicito.
- Modifiche ad artifact finalizzati o completamento PRS-18.

## Invarianti

- RecordingStore possiede asset/manifest; CatalogStore conserva solo proiezioni necessarie.
- Percorsi da settings/path owners; endpoint loopback autenticati con le restrizioni di origine esistenti.
- Nessun contenuto immagine/OCR/trascritto nei log ordinari o nella telemetria; cloud solo con scelta esplicita che includa queste fonti.
- Durante la registrazione solo acquisizione/scrittura bounded; niente ASR/LLM/VLM pesante.
- HeavyWorkloadArbiter, JobStore e runtime owner restano gli unici proprietari di scheduling/lifecycle.
- Le operazioni native ripristinano stato su successo, errore, timeout, annullamento e inizializzazione parziale; Cocoa/WebKit sul main thread.
- Screenshot/OCR sono dati non fidati, mai istruzioni.
- Audio, testo e ID dei segmenti non vengono alterati per inserire riferimenti visuali.
- Analisi finalizzate immutate; edit utente e conflitti recuperabili.
- Nessun badge di successo prima del salvataggio; silenzio, perdita sorgente e perdita connessione sono stati distinti.

## Work graph e confini di scrittura

| ID | Outcome verificabile | Owns/writes | Depends on | Parallel | State |
| --- | --- | --- | --- | --- | --- |
| CO-1 | Scatto locale persistito con tempo affidabile | `native_capture.py`, helper Swift, `recordings.py`, router/schemi/API capture | — | no | READY |
| CO-2 | Overlay monitora, scatta e termina | overlay page, `useRecorder.ts`, `window.py`, API finestra, CSS/i18n | CO-1 | con CO-3 | BLOCKED |
| CO-3 | Scatti apribili dalla trascrizione/meeting | `MeetingDetailPage.tsx`, viewer, componenti immagini, meeting/API | CO-1 | con CO-2 | BLOCKED |
| CO-4 | Analisi locale cita le immagini | `visual_intelligence/`, analysis service, structured notes/types/editor/proiezioni/cache | CO-1, CO-3 | no | BLOCKED |
| CO-5 | Prepara appunti con recovery testo/immagini | `meeting_preparation.py`, job identity, setup e consumer Meeting | CO-2, CO-3, CO-4 | no | BLOCKED |
| CO-6 | Percorso integrabile con prove/docs | E2E/script/registry, docs/design, smoke packaging | CO-1..5 | no | BLOCKED |

Stati: READY / ACTIVE / BLOCKED / DONE; BLOCKED indica dipendenze non completate.

Implementation checkpoint 2026-10-01: CO-1..5 sono implementati sul branch `work/call-overlay-screenshot-evidence`; CO-6 è attivo per diff review, selector, E2E/preflight e chiusura documentale. Il lavoro è partito dal `dev` esatto `d34dfc0e`. Durante l'implementazione quel branch è stato promosso e rimosso; `main` è avanzato solo attraverso commit di promozione/tree-equivalent rispetto a `d34dfc0e`, quindi il workstream viene riallineato a `main` prima del preflight senza sostituire owner o contratti locali.
Ogni fase possiede i test relativi. Parallelismo possibile, non delega ad agenti.
CO-1 congela i contratti prima di CO-2/3; revisioni passano dal suo owner.
CO-3 termina prima di CO-5 sul Meeting; CO-4 possiede i tipi fonte.

## Current executable slice: CO-1

Prima prova: scatto backend/helper con fixture e sessione attiva; distinguere
richiesta accettata, acquisizione e persistenza. Definire il protocollo puntuale
prima della UI: il helper attuale avvia cattura continua.

Acceptance:

- Scatta funziona senza attivare il campionamento visuale continuo e senza cambiare la sorgente audio.
- Asset stabile con `screenshot_id`, `recording_id`, sequenza, tempo relativo, monitor, formato/dimensioni e hash; timestamp dalla base monotona canonica della cattura pronta.
- Mappare clock nativo, offset audio/traccia e presentazione; mai derivare il tempo dal timer React.
- Originale a risoluzione leggibile e miniatura separata; adattare l'ingresso visuale senza forzare l'originale nel limite JPEG/1280px dei frame attuali.
- Distinguere manuale/automatico e versionare il manifest; meeting e risultati legacy restano leggibili senza backfill AI.
- Escludere il pannello ClosedRoom; segnalare monitor intero e possibile presenza di altre finestre/notifiche.
- Validare input e ownership; limiti per byte/pixel/spazio/tempo e concorrenza espliciti; retry idempotente con request ID, nessun falso conteggio o asset duplicato.
- Stop chiude l'ammissione di nuovi scatti e risolve quelli già ammessi entro un timeout; errore/annullamento puliscono solo residui propri e preservano gli asset già salvati.
- Restart riconcilia file e manifest; cancellazione meeting elimina asset/derivati attraverso il proprietario canonico.
- Display perso/permesso revocato: niente cambio monitor implicito; audio sano continua e scatto recuperabile.

Validation iniziale: estendere `test.test_recordings`, `test.test_recording_api`,
`test.test_native_capture`, `test.test_visual_intelligence_persistence`; eseguire
solo i casi interessati tramite il runtime canonico. La prova fisica rimane distinta.

## Acceptance delle fasi successive

CO-2:

- Titolo, durata, stato, sorgente monitor, Scatta, conteggio immagini e Termina; backend/dB/byte in diagnostica.
- Design tokens condivisi; compatto/espanso spostabili, riapribili e leggibili su monitor/Spaces/fullscreen.
- Nascondi non termina la registrazione; Termina mostra salvataggio fino all'esito persistito e poi apre il meeting.
- Click/scorciatoia globale sullo stesso comando; conflitti OS, focus/tastiera/VoiceOver e reduced motion verificati.
- Stato da sessione canonica, reconcile dopo reconnect; ACK non significa salvato; warnings e errori azionabili anche nel compatto.
- Browser fallback dichiara le capability reali: niente promessa di scatto/esclusione overlay se il percorso non li supporta.

CO-3:

- Evento «Screenshot N · mm:ss» nel punto acquisito, anche dentro interventi lunghi, senza dividere o rinumerare segmenti ASR.
- Ordinamento deterministico e riferimenti visibili anche con silenzi, segmenti sovrapposti, prima/dopo il parlato, paginazione e ricerca.
- Apri originale, cerca audio dal timestamp, torna al contesto dalla raccolta. Metadati piccoli; immagini/miniature lazy.
- Meeting resta rapido con molte immagini o asset mancanti; errori accessori non bloccano audio/testo; segnalare fonte rimossa/indisponibile.
- Rimozione scatto aggiorna manifest, proiezioni e validità analisi; niente riferimenti risolti a immagini diverse.
- Verificare i consumer Meeting, ResultsStep, FullTextView e export esistenti; formati senza immagini mantengono marker e timestamp separati dal testo pronunciato.

CO-4:

- OCR e lettura visuale locali dopo Stop; riusare i task shared-content, separando questa funzione dall'attribuzione degli speaker.
- Ogni scatto manuale incluso è trattato o segnalato: niente sampling/dedupe automatico che lo scarti silenziosamente; job/costi restano bounded e cancellabili.
- Fonti tipizzate transcript/screenshot, con ID stabili e provenance; validazione vieta citazioni inventate, tratteggio temporale non prova causalità.
- Retrocompatibilità fonti con validatori/editor/hash item/conflitti/proiezioni/UI/export aggiornati.
- OCR non basta per grafici/relazioni: qualità insufficiente o modello indisponibile sono stati espliciti; niente interpretazioni presentate come fatti.
- Separare ciò che appare da ciò che viene discusso/deciso; citazioni apribili nelle sintesi, decisioni e azioni che usano immagini.

CO-5:

- «Includi N screenshot»: default locale incluso per scatti manuali, scelta persistita nel job.
- Il percorso senza immagini conserva la semplicità attuale; provider cloud già configurato non autorizza implicitamente invio di immagini/OCR/descrizioni.
- Trascrizione -> evidenze visuali -> sintesi tramite arbiter esistente; transcript disponibile appena pronto.
- Fallimento visuale produce esito parziale dichiarato e appunti utilizzabili, senza perdere audio/testo; retry/resume rifanno solo lavoro mancante o invalidato.
- Identità/cache dipendono anche da set/hash degli scatti inclusi, versioni OCR/VLM/prompt e scelta delle fonti; cambiare immagini non invalida inutilmente ASR.
- Ogni run conserva lo snapshot delle fonti; risultati antecedenti a rimozione/cambio selezione sono riconoscibili e non vengono sovrascritti.

## Evidenza e gate

ITERATION: prove owner-local di persistenza/lifecycle, tempo, idempotenza/fonti/recovery;
frontend lint/typecheck. Selector per rischi/gate; nessun costo prestazionale inventato.

INTEGRATION: head/tree/base freschi, diff completo, docs correnti e gate selector;
E2E FULL_MEDIA del percorso start -> scatti -> stop -> riapertura -> marker/audio ->
appunti citati, più permesso negato, scatto fallito, reconnect e retry visuale.
Estendere gli E2E esistenti e `.engineering/e2e.json`; build/smoke dell'helper e
bundle quando selezionati. Gate deterministici mancanti localmente -> remote preflight.

RELEASE: FULL e prova sull'esatto artifact immutabile Apple-Silicon di TCC,
ScreenCaptureKit, esclusione overlay, Retina/testo piccolo, display multipli/ritirati,
focus/scorciatoia con altra app, fullscreen/Spaces e reale condivisione Zoom/Teams.
Esclusione dai nostri screenshot non dimostra invisibilità nella condivisione della
call. Misurare audio fisico concorrente e qualità/risorse MLX/Metal con meeting e
scatti rappresentativi; fixture non li provano. Questi gap sono DEFERRED_TO_RELEASE
in integrazione e bloccanti quando applicabili al rilascio, non delega dei gate CI.
Media di prova limitati a contenuti sintetici/consentiti, retention e zero-residue.

## Destinazioni della verità durevole e closeout

- `docs/features.md`: comportamento/recovery/verifiche; split solo se riduce contesto.
- `docs/architecture.md`: contratti/persistenza/fusione; `SECURITY.md` per lifecycle/trust.
- `design/ux-contract.json` / brand owner: overlay/citazioni/disclosure; `frontend/src/` source of truth.
- README usage per workflow/prerequisiti; registry E2E/comandi per nuove semantiche.
- `docs/current-state.md`: stato integrato e obblighi release, non claim del prototipo.
- `finalize-workstream`: provare acceptance, trasferire obblighi, eliminare piano/indice, verificare link/gate.

## Unico checkpoint di ripresa

- Baseline 2026-10-01: branch `prs18/keyboard-bridge-diagnostics`; HEAD `f2082a94490b1eb40ce74f70339961bffcd82afe`; tree `87b0669702d875661927d520c7973b50c388142e`; checkout pulito prima del piano.
- Target: `dev`; `origin/dev` locale = `06bfefe66f38475589f86b51fe54850b2c452eba`, remoto non verificato. Solo piano/indice modificati, nessuna implementazione.
- Fatti da ricontrollare: overlay `RecordingOverlayPage.tsx`; frame store/API `recordings.py:373` e `routers/recordings.py:78`; helper `VisualWindowCapture`; notes `structured_notes.py`; preparation `meeting_preparation.py:68,413`.
- Confermato nei suddetti owner: frame disponibili, notes/source refs transcript-only, identità preparation audio-only, marker screenshot assente; il solo bottone non basta.
- CO-1 aperto: protocollo/capability macOS, clock/audio, manifest/quote, originale/frame, browser, esclusione pannello dell'altro processo.
- Target-Mac non provato: obblighi RELEASE aperti; qualità/performance non misurate.
- Next: aggiornare head/tree/base e guide scoped; congelare contratto e provare timestamp/stop/idempotenza prima dell'overlay.
