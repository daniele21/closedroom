# Overlay chiamata e screenshot come fonti del meeting

Status: ACTIVE
Owner: meeting UX, RecordingStore, NativeCaptureManager e servizi canonici di analisi/job
Read when: implementare, validare o riprendere overlay, screenshot manuali e citazioni visuali
Created: 2026-10-01

## Outcome

Durante una registrazione nativa l'utente può salvare intenzionalmente uno screenshot
dell'intero monitor dal compact overlay. Lo scatto usa il clock della registrazione,
viene persistito localmente prima del feedback di successo e riappare nel Meeting al
timestamp corretto. Transcript/audio restano canonici; le note possono citare
separatamente evidenza parlata e visuale.

Decisioni:
- multi-display: selezione esplicita, mai cambio monitor silenzioso;
- one-shot manuale, non screen recording continuo;
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
- ClosedRoom è escluso dal content filter; permission/display loss produce errore
  recuperabile senza cambiare sorgente o fermare l'audio.
- Restart riconcilia manifest/file; delete/discard segue il proprietario RecordingStore.
- Overlay distingue recording, screenshot saving/failure e stopping; ACK non equivale
  a salvataggio. Click e shortcut invocano lo stesso comando.
- Marker Screenshot N · mm:ss è deterministico anche dentro turni lunghi, nei silenzi
  e con paginazione; non divide/rinumera segmenti.
- Asset mancanti restano riferimenti espliciti; thumbnail lazy e originale apribile.
- Ogni screenshot manuale disponibile riceve un candidato shared-content ma resta dentro
  lo stesso hard ceiling visuale; provenance conserva screenshot ID/hash/display.
- Structured notes distinguono spoken, visual, mixed; visual-only non può diventare
  implicitamente “detto/deciso”. Provider cloud non riceve fonti visuali implicitamente.
- Preparation identity include set/hash screenshot senza invalidare inutilmente ASR;
  visual failure produce warning e note testo-only utilizzabili.

## Stato implementazione 2026-10-01

Implementazione CO-1..5 presente su work/call-overlay-screenshot-evidence.
Il lavoro è partito dall'esatto dev=d34dfc0e. Durante il lavoro quel dev è stato
promosso a main=741edb5 con tree equivalente e cancellato; dev è stato
ripristinato a 741edb5 secondo il contratto repository e il branch è ora basato
sullo stesso target. Draft PR di integrazione: #72.

CO-6 è attivo. Il primo remote preflight ha classificato STRONG e la repository
validation è passata; i guard si sono fermati solo perché questo workstream superava
il budget documentale 3000 token. Il piano è stato compattato prima di ripetere i gate.
Il diff review ha inoltre individuato e corretto il rischio che i candidati manuali
potessero essere aggiunti oltre il ceiling visuale.

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
