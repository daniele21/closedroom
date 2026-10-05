# Screenshot Capture Core — velocità, robustezza e prova continua

Status: ACTIVE
Owner: NativeCaptureManager, native capture helper, RecordingStore, overlay screenshot UX
Target branch: dev
Created: 2026-10-05

## Outcome

Lo screenshot manuale durante una registrazione deve essere rapido, ripetibile e affidabile:
feedback immediato, cattura one-shot locale, persistenza singola e nessuna interruzione audio.

Il path produttivo usa un worker screenshot persistente posseduto da `NativeCaptureManager`;
`RecordingStore` resta owner di asset, manifest, limiti, idempotenza, cleanup e recovery.

## Assi

- PRODUCT: PRODUCT_FEATURE
- DELIVERY: ITERATION durante implementazione; INTEGRATION solo dopo gate richiesti
- VALIDATION: STRONG
- EXECUTION: AGENT_LOCAL/REMOTE_AUTOMATED per gate deterministici; REAL_ENVIRONMENT per
  TCC/ScreenCaptureKit, latenza reale, multi-display e continuità audio

## Architettura e invarianti

Una recording session ha due failure domain distinti:
1. recording worker persistente per mic + system audio;
2. screenshot worker persistente per display registry + cattura one-shot.

Hot path:

`click -> API -> worker command -> one-shot capture -> encode -> RecordingStore commit -> 201`

Invarianti:
- local-first, nessun cloud transfer o fallback remoto;
- nessuna cattura continua quando l'utente non scatta;
- screenshot failure non ferma né riavvia il recording audio;
- nessun process spawn, TCC bootstrap o display discovery subprocess per click;
- Stop chiude admission e drena bounded gli screenshot già ammessi;
- display selection resta esplicita, senza silent switch;
- timestamp = `captured_uptime - recording_ready_uptime`;
- log/metriche contengono solo dati tecnici, mai pixel/OCR/transcript/window title;
- il comando standalone `helper screenshot` è solo diagnostico/legacy.

## SLO

| Metrica | Target |
| --- | ---: |
| feedback UI | p95 < 50 ms |
| backend -> worker | p95 < 10 ms |
| click -> frame | p50 < 250 ms, p95 < 500 ms |
| click -> persisted | p50 < 300 ms, p95 < 700 ms |
| failure detection/recovery | < 1.5 s |
| 20 screenshot consecutivi | 20/20 |
| audio interruption | 0 |
| process/discovery spawn per click | 0 |

## Work graph

| ID | Outcome | State |
| --- | --- | --- |
| SC-0 | baseline metriche/trace | DONE |
| SC-1 | protocollo JSONL + worker persistente | DONE |
| SC-2 | display registry cached | DONE |
| SC-3 | timeout, health, restart, decisione backend fallback | PARTIAL_REAL_ENV_PENDING |
| SC-4 | staging/atomic commit RecordingStore | DONE |
| SC-5 | overlay control center + display ownership | IMPLEMENTED_PENDING_VALIDATION |
| SC-6 | suite deterministica + benchmark harness | DONE |
| SC-7 | target-Mac burst/perf/TCC/audio continuity | PARTIAL_REAL_ENV_PASS |
| SC-8 | rimozione runtime path one-shot legacy | PLANNED |

## Stato implementazione 2026-10-05

Implementato:
- un solo screenshot worker per recording, separato dall'audio;
- AppKit/TCC/ScreenCaptureKit warm-up e display/filter cache;
- `GET /v1/capture/displays` usa la cache durante recording;
- timeout one-shot 1.2s e restart isolato del worker;
- staging paths + `os.replace` senza JPEG round-trip in Python;
- metriche capture/encode/write/roundtrip/persist e restart count;
- suite per 20 screenshot, stesso PID, timeout/recovery, staging/idempotenza;
- benchmark `scripts/benchmark_screenshot_capture_core.py`;
- runner `scripts/validate_capture_core.py`;
- source mode ricostruisce bundle frontend coerente in `.cache/frontend-static`;
- browser fallback overlay è atteso quando manca il native window manager;
- display scelto è posseduto dalla `CaptureSession` via
  `PUT /v1/recordings/{id}/screenshot-display`.

Aperto:
- SC-3: decidere eventuale backend fallback dai benchmark reali;
- SC-5: validazione exact-head dell'overlay;
- SC-7: matrice target-Mac completa;
- SC-8: rimozione/diagnostic-only del legacy one-shot.

## Evidenza corrente

Ultimo REAL_ENVIRONMENT PASS precedente: `11ffb8343a475333a9fd3cdf8216e305c06eebfa`,
con `python3 scripts/validate_capture_core.py --real --enforce-slo`: deterministic suite,
20-shot persistent-worker benchmark e SLO PASS.

Quell'evidenza è STALE per l'HEAD corrente perché il lifecycle è poi cambiato per evitare
bootstrap concorrente del ScreenshotWorker prima dell'evento audio `ready`.
Non usarla come exact-head readiness.

SC-7 resta parziale: manca ancora evidenza completa per recording `both` concorrente,
multi-display, fullscreen/Spaces, TCC deny/grant/relaunch e recovery reale.

## Overlay e screenshot exclusion

La `CaptureSession` possiede il display del prossimo screenshot. Il compact overlay espone
timer, health mic/system, display target, screenshot e Stop; diagnostica estesa resta nei Details.
Il display picker è esplicito e un heartbeat SSE stale non può fare rollback di una selezione
in-flight.

Contratto di cattura:
- lo screenshot conserva tutte le finestre visibili del display selezionato;
- la finestra principale ClosedRoom resta catturabile;
- viene escluso solo il recording overlay;
- native: identità primaria = window ID esatto dell'`NSPanel`;
- browser/race fallback = titolo esatto `ClosedRoom Recording Overlay`;
- matching fuzzy su process/app/bundle/title `contains("closedroom")` è vietato;
- l'ID native viene acquisito quando l'overlay diventa visibile e riusato dal capture manager,
  senza hop sincrono al Cocoa main thread nell'hot path;
- nessuna preview/live screen capture viene introdotta.

Acceptance:
- Display A -> B resta B dopo heartbeat SSE;
- screenshot successivo senza override usa B;
- display invalid/disconnected viene rifiutato;
- Chrome/VS Code/main ClosedRoom visibili restano nello screenshot;
- recording overlay non compare nello screenshot.

## Worker contract

Startup:
- Python avvia il worker dopo audio `ready`;
- worker pubblica `screenshot_worker_ready` con PID/backend/displays;
- sessione conserva process, reader, cache, pending requests e health.

Command essenziale:
`capture_screenshot(request_id, display_id, excluded_window_ids, output paths, ready_uptime)`.

Success espone ID/display/timestamp/dimensioni e metriche; failure espone reason/recoverable.
`displays_changed` aggiorna la cache senza cambiare silenziosamente il display selezionato.

## Test contract

Deterministico:
- worker start/ready/stop e stesso PID 1..20;
- nessun subprocess legacy nell'hot path;
- exact overlay exclusion IDs sanitizzati/deduplicati;
- nessun fuzzy matching ClosedRoom;
- timeout non ferma audio, restart recupera il click successivo;
- display cache e disconnected display;
- Stop drena screenshot admitted;
- staging cleanup/persistenza/idempotenza;
- frontend feedback e display ownership;
- browser/native overlay identity esatta.

REAL_ENVIRONMENT:
- 20 screenshot stesso display a intervalli diversi;
- alternanza multi-display;
- recording `both` durante burst e zero audio gap/restart;
- p50/p95/failure rate + CPU/RSS bounded;
- TCC deny/grant/relaunch;
- fullscreen/Spaces/display withdrawal;
- recovery dopo fault;
- prova visiva: finestre utente presenti, solo recording overlay escluso.

## Validation

Il selector resta STRONG: native lifecycle, ScreenCaptureKit, concurrency, persistence e runtime.

Durante sviluppo usare il capture-core selector rapido. Per INTEGRATION servono:
- head/tree/base freschi e full diff;
- source tests e repository gates richiesti dal selector;
- packaged-app gate quando selezionato;
- affected E2E `call-overlay-screenshot-evidence`;
- REAL_ENVIRONMENT resta separato e non può essere sostituito da fixture.

## Done

Chiudere il workstream solo quando:
- hot path senza process/discovery spawn;
- 20-shot deterministic suite verde;
- persistenza singola e cleanup coerente;
- failure recovery non interrompe audio;
- SLO p50/p95 approvati;
- target-Mac conferma ScreenCaptureKit/TCC/audio continuity;
- screenshot preserva tutte le finestre utente ed esclude solo l'overlay;
- legacy one-shot è rimosso dal prodotto o diagnostic-only.
