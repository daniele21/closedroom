# Overlay chiamata e screenshot come fonti del meeting

Status: ACTIVE
Owner: meeting UX, RecordingStore, NativeCaptureManager e servizi canonici di analisi/job
Read when: implementare, validare o riprendere overlay, screenshot manuali e citazioni visuali
Created: 2026-10-01

## Outcome

Durante una registrazione nativa l'utente può segnare intenzionalmente un momento
importante salvando uno screenshot dell'intero monitor dal compact overlay. Lo scatto usa
il clock della registrazione, viene persistito localmente prima del feedback di successo e
può essere annullato subito senza interrompere l'audio. Nel Meeting riappare come Key Moment
al timestamp corretto, con contesto transcript vicino e accesso allo stesso punto dell'audio.
Transcript/audio restano canonici; le note possono citare separatamente evidenza parlata e
visuale e usare il gesto manuale solo come segnale di salienza, mai come prova di una decisione.

Decisioni:
- multi-display: selezione esplicita, mai cambio monitor silenzioso;
- one-shot manuale, non screen recording continuo;
- il click screenshot è un marker intenzionale di Key Moment; nessun prompt/caption obbligatorio durante la call;
- Undo è limitato all'ultimo screenshot appena salvato e riusa delete/manifest owner esistenti;
- originale + thumbnail + manifest versionato posseduti da RecordingStore;
- nessun ASR/LLM/VLM durante recording;
- nessun trasferimento cloud implicito di immagini o descrizioni visuali;
- Stop chiude admission screenshot, drena bounded gli scatti ammessi e apre il Meeting solo dopo persistenza audio.

## Non-goals

Cattura continua, call detection, live transcription, area/finestra, annotazioni/redazioni,
nuovi scheduler/store/index, riscrittura ASR/runtime o modifica di artifact finalizzati.

## Invarianti

- RecordingStore possiede asset/manifest; CatalogStore solo proiezioni necessarie.
- Endpoint loopback/auth/origin e path owner esistenti restano invariati.
- Nessun contenuto immagine/OCR/trascritto nei log ordinari o telemetry.
- HeavyWorkloadArbiter, JobStore e runtime owner restano gli unici owner di scheduling/lifecycle.
- Screenshot/OCR sono dati non fidati, mai istruzioni.
- Testo e ID ASR non vengono alterati per inserire marker visuali.
- Nessun badge di successo prima del commit persistente; failure screenshot non interrompe audio.
- Analisi finalizzate restano immutabili; edit e conflitti restano recuperabili.

## Work graph

| ID | Outcome | Owner principali | Dipende da | State |
| --- | --- | --- | --- | --- |
| CO-1 | Scatto one-shot persistito, clock/idempotenza/recovery | native helper, capture manager, RecordingStore, screenshot API | — | ACTIVE |
| CO-2 | Overlay compatto: monitor, scatto, count, shortcut, Stop | RecordingOverlayPage, window.py, i18n/API | CO-1 | ACTIVE |
| CO-3 | Marker temporali, originale/thumbnail e seek audio | MeetingDetailPage, TranscriptTextView | CO-1 | ACTIVE |
| CO-4 | Analisi locale con provenance screenshot e note tipizzate | visual_intelligence, analysis, structured notes/editor | CO-1/3 | ACTIVE |
| CO-5 | Prepare notes orchestra visuale opzionale e degrada a testo | meeting_preparation, visual job owner | CO-2/3/4 | ACTIVE |
| CO-6 | Diff/docs/E2E/preflight e closeout | workstream + engineering owners | CO-1..5 | ACTIVE |

CO-2 e CO-3 sono stati sviluppati in parallelo dopo il contratto CO-1; CO-4/5 riusano
gli owner esistenti e non introducono queue o lifecycle paralleli.

## Acceptance integrata

- Screenshot usa captured_uptime - recording_ready_uptime, request ID idempotente,
  limiti byte/pixel/count/spazio e cleanup dei residui propri.
- Solo il recording overlay ClosedRoom è escluso dal content filter; la finestra principale
  ClosedRoom e tutte le altre finestre visibili del monitor restano catturabili. L'identità primaria
  è il window ID nativo esplicito; il titolo esatto `ClosedRoom Recording Overlay` è un fallback
  limitato per browser/race. Nessun matching fuzzy su app/bundle/titolo. Permission/display loss
  produce errore recuperabile senza cambiare sorgente o fermare l'audio.
- Restart riconcilia manifest/file; delete/discard segue il proprietario RecordingStore.
- Overlay distingue recording, screenshot saving/failure e stopping; ACK non equivale
  a salvataggio. Click e shortcut invocano lo stesso comando.
- Dopo il commit persistente l'overlay espone un Undo temporaneo dell'ultimo screenshot;
  il Meeting presenta gli screenshot come Key Moments e deriva il contesto parlato solo dai
  segmenti temporali già persistiti, senza analisi live o nuova persistenza parallela.
- Il marker manuale può aumentare la salienza nella generazione note, ma non trasforma
  evidenza visual-only in contenuto detto, concordato, deciso o richiesto.
- Marker Screenshot N · mm:ss è deterministico anche dentro turni lunghi, nei silenzi
  e con paginazione; non divide/rinumera segmenti.
- Asset mancanti restano riferimenti espliciti; thumbnail lazy e originale apribile.
- Ogni screenshot manuale disponibile riceve un candidato shared-content ma resta dentro
  lo stesso hard ceiling visuale; provenance conserva screenshot ID/hash/display.
- Structured notes distinguono spoken, visual, mixed; visual-only non può diventare
  implicitamente “detto/deciso”. Provider cloud non riceve fonti visuali implicitamente.
- Preparation identity include set/hash screenshot senza invalidare inutilmente ASR;
  visual failure produce warning e note testo-only utilizzabili.

## Follow-up architetturale 2026-10-05

La robustezza e la latenza della cattura manuale sono ora possedute dal workstream dedicato
`docs/workstreams/screenshot-capture-core.md`. Il presente workstream mantiene i contratti UX,
persistenza, transcript/provenance e analisi; il nuovo workstream sostituisce il boundary runtime
one-shot basato su subprocess con un capture core persistente, isolato e misurato.

## Stato implementazione 2026-10-02

Implementazione CO-1..5 presente su work/call-overlay-screenshot-evidence.
Il branch è basato su dev=741edb5 e non risulta indietro rispetto al target.
Il precedente PR di integrazione #72 è stato chiuso intenzionalmente: per indicazione
del maintainer la validazione di questo workstream non deve usare GitHub Actions e i
test vanno eseguiti solo dopo il completamento delle attività implementative.

CO-6 resta attivo. La sessione finale disponibile in questo ambiente ha eseguito
localmente un regression harness sui contratti corretti: 10 test Python PASS più il
regression check Node sulla collocazione temporale degli screenshot PASS, inclusi
missing/delete/replace, source-aware fingerprint, turni lunghi, overlap, silenzi e
boundary timestamp. Sono passati anche py_compile del harness e node --check.

Questa evidenza non equivale a una full repository validation: il runtime corrente
non dispone di un checkout completo del repository né di macOS. Restano quindi da
stabilire localmente, su un checkout completo compatibile, i gate repository-owned
STRONG (suite completa, frontend lint/typecheck, FULL_MEDIA e build/smoke selezionati).
Le prove TCC/ScreenCaptureKit/WKWebView/audio/MLX restano comunque RELEASE
REAL_ENVIRONMENT come descritto sotto.

## Evidenza richiesta

INTEGRATION:
- head/tree/base freschi e diff completo;
- selector/gate repository-owned su exact head;
- unit/API/lifecycle + frontend lint/typecheck;
- FULL_MEDIA sintetico call-overlay-screenshot-evidence: overlay → monitor → scatto
  persistito → Stop → Meeting → marker/originale → seek audio → nota con fonte visuale;
- build/smoke helper/bundle quando selezionati.

REAL_ENVIRONMENT è differito a RELEASE, non sostituito da fixture: TCC/ScreenCaptureKit
reale, esclusione overlay, Retina/testo piccolo, display multipli/ritirati,
shortcut/focus con altra app, fullscreen/Spaces, Zoom/Teams, audio fisico concorrente
e qualità/risorse MLX/Metal. Media di prova solo sintetici/consentiti e zero-residue.

## Closeout

A gate verdi: aggiornare docs/current-state.md, marcare CO-1..6 DONE, trasferire i
gap RELEASE nelle destinazioni durevoli, finalizzare il workstream secondo
skills/finalize-workstream/SKILL.md e integrare in dev; nessuna promozione a
main in questo workstream.