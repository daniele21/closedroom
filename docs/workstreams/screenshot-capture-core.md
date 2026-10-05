# Screenshot Capture Core — velocità, robustezza e prova continua

Status: ACTIVE
Owner: NativeCaptureManager, native capture helper, RecordingStore, overlay screenshot UX
Target branch: dev
Created: 2026-10-05

## Outcome

Lo screenshot manuale durante una registrazione ClosedRoom deve essere percepito come istantaneo,
ripetibile e affidabile: il click produce feedback immediato, la cattura one-shot viene eseguita
localmente senza process churn per ogni click, viene persistita una sola volta e non può
interrompere l'audio.

Il workstream sostituisce il path produttivo basato su `subprocess.run(helper screenshot ...)`
con un worker screenshot persistente e isolato, posseduto da `NativeCaptureManager`, mantenendo
RecordingStore come owner della persistenza e il boundary local-first.

## Assi

- PRODUCT: PRODUCT_FEATURE
- DELIVERY: ITERATION durante implementazione; INTEGRATION solo dopo gate richiesti
- VALIDATION: STRONG
- EXECUTION: AGENT_LOCAL per gate deterministici; REAL_ENVIRONMENT per TCC/ScreenCaptureKit,
  latenza reale, multi-display e continuità audio

## Problema osservato

L'implementazione corrente:
- apre processi helper separati per display discovery e screenshot;
- inizializza AppKit/TCC/ScreenCaptureKit ripetutamente;
- interroga `SCShareableContent` nell'hot path;
- scrive JPEG temporanei, li rilegge in Python e li riscrive via RecordingStore;
- può riuscire una volta e andare in timeout alla cattura successiva;
- usa un timeout esterno di 15s incompatibile con l'esperienza attesa.

## Architettura target

Una recording session possiede due failure domain nativi distinti:

1. Recording worker persistente: microfono + audio di sistema.
2. Screenshot worker persistente: AppKit/TCC/display registry + cattura one-shot.

Il worker screenshot:
- nasce una volta per recording e resta idle finché l'utente non scatta;
- comunica via JSONL stdin/stdout;
- serializza le richieste;
- non mantiene screen recording continuo;
- può essere riavviato senza interrompere audio;
- espone display state cached;
- emette metriche tecniche privacy-safe.

Hot path target:

`click -> API -> command worker -> one-shot capture -> encode -> RecordingStore commit -> 201`

Non devono esserci process spawn, TCC bootstrap o display discovery ScreenCaptureKit per singolo click.

## Invarianti

- Nessun cloud transfer o fallback remoto.
- Nessuna cattura continua dello schermo quando l'utente non preme screenshot.
- Screenshot failure non ferma né degrada il recording audio.
- RecordingStore resta owner di asset, manifest, limiti, idempotenza, cleanup e recovery.
- Nessun contenuto immagine/OCR/titolo finestra nei log o metriche.
- Stop chiude admission screenshot e drena bounded le richieste già ammesse.
- Display selection resta esplicita; nessun cambio monitor silenzioso.
- Timestamp continua a derivare da `captured_uptime - recording_ready_uptime`.
- Il path standalone `helper screenshot` può restare solo diagnostico, non produttivo.

## SLO iniziali

Questi sono target da validare, non risultati già provati:

| Metrica | Target |
| --- | ---: |
| feedback UI al click | p95 < 50 ms |
| dispatch backend -> worker | p95 < 10 ms |
| click -> frame | p50 < 250 ms |
| click -> frame | p95 < 500 ms |
| click -> persisted | p50 < 300 ms |
| click -> persisted | p95 < 700 ms |
| failure detection/recovery | < 1.5 s |
| 20 screenshot consecutivi | 20/20 success |
| audio interruption dovuta a screenshot | 0 |
| process spawn per screenshot | 0 |
| display discovery subprocess per screenshot | 0 |

## Work graph

| ID | Outcome | Owner | Dipende da | State |
| --- | --- | --- | --- | --- |
| SC-0 | baseline metriche e trace current path | native manager/helper | — | DONE |
| SC-1 | protocollo JSONL + ScreenshotWorker persistente | helper + manager | — | IMPLEMENTED_PENDING_VALIDATION |
| SC-2 | DisplayRegistry cached senza ScreenCaptureKit hot-path | helper + manager + API | SC-1 | IMPLEMENTED_PENDING_VALIDATION |
| SC-3 | timeout locale, health, restart e backend fallback | worker | SC-1 | PARTIAL_PENDING_VALIDATION |
| SC-4 | staging/atomic commit RecordingStore senza read/write duplicato | RecordingStore + API | SC-1 | IMPLEMENTED_PENDING_VALIDATION |
| SC-5 | overlay state/feedback rapido e no refresh display ridondanti | frontend | SC-2 | PARTIAL_PENDING_VALIDATION |
| SC-6 | capture-core deterministic suite + benchmark harness | tests/scripts | SC-1..5 | IMPLEMENTED_PENDING_EXECUTION |
| SC-7 | target-Mac burst/perf/TCC/audio-continuity evidence | real environment | SC-1..6 | PLANNED |
| SC-8 | rimozione runtime path one-shot subprocess legacy | manager/helper | SC-7 | PLANNED |

SC-1, SC-2 e SC-6 sono intenzionalmente sviluppabili in parallelo dopo il contratto sopra.

## Stato implementazione 2026-10-05

Prima ondata implementata sul branch `work/screenshot-capture-core`, senza integrazione su `dev`.

Implementato:
- worker screenshot persistente separato dal recording worker, con JSONL stdin/stdout;
- warm-up AppKit/TCC/ScreenCaptureKit una volta per recording e cache dei content filter;
- display cache posseduta dal worker con callback CoreGraphics per reconfiguration;
- `GET /v1/capture/displays` usa la cache durante recording e non esegue discovery subprocess;
- timeout interno one-shot a 1.2s e restart isolato del worker su timeout;
- audio worker resta un failure domain separato e non viene riavviato da screenshot failure;
- RecordingStore riserva staging paths e promuove gli asset con `os.replace`, evitando JPEG round-trip in RAM Python e seconda scrittura;
- metriche tecniche capture/encode/write/roundtrip/persist e worker restart count;
- overlay stabilizzato per evitare ricreazioni del callback display dovute alla selezione monitor;
- suite deterministica per 20 screenshot, stesso PID, display cache, timeout/recovery, atomic staging e API idempotency;
- benchmark target-Mac `scripts/benchmark_screenshot_capture_core.py` e runner focalizzato `scripts/validate_capture_core.py`.

Ancora aperto:
- SC-3: il restart su timeout è implementato; fallback automatico a backend alternativo non è ancora introdotto e va deciso dai benchmark reali;
- SC-5: il churn callback è ridotto, ma lo stato UX esplicito worker warming/ready resta da rifinire dopo evidenza reale sulla warm-up latency;
- SC-7: TCC, ScreenCaptureKit reale, 20-shot burst, p50/p95, multi-display e continuità audio richiedono target Mac;
- SC-8: il comando standalone one-shot resta presente come diagnostica/legacy finché il nuovo path non è validato.

Validazione: non ancora dichiarata. In questo ambiente il repository non è disponibile come checkout locale e l'accesso Git via DNS non è disponibile; per indicazione del maintainer non si usano GitHub Actions come sostituto. I gate deterministici, frontend typecheck/lint, compilazione Swift e packaged-app restano quindi PENDING finché non possono essere eseguiti localmente sull'exact head. Nessun PASS viene inferito dalla sola review del sorgente.

## Contratto worker

Startup:
- Python avvia un solo screenshot worker per recording.
- Worker inizializza AppKit/TCC e pubblica `screenshot_worker_ready` con PID/backend/displays.
- CaptureSession conserva process, reader, cached displays, pending requests e health.

Command:
```json
{"type":"capture_screenshot","request_id":"...","display_id":1,"original_file":"...","thumbnail_file":"...","recording_ready_uptime":123.4}
```

Success:
```json
{"type":"screenshot_completed","request_id":"...","display_id":1,"captured_uptime":124.1,"width":3024,"height":1964,"capture_ms":120,"encode_ms":45}
```

Failure:
```json
{"type":"screenshot_failed","request_id":"...","reason":"capture_timeout","recoverable":true}
```

Display state:
```json
{"type":"displays_changed","displays":[{"display_id":1,"width":3024,"height":1964,"is_main":true}]}
```

## Performance instrumentation

Per ogni screenshot, solo dati tecnici:
- trace/request id
- worker PID/restart count/backend
- dispatch_ms
- display_lookup_ms
- capture_ms
- original_encode_ms
- thumbnail_encode_ms
- persist_ms
- total_ms
- success/failure reason

Mai pixel, OCR, transcript, window title o meeting content.

## Test contract

### Deterministici

- worker start/ready/stop
- stesso worker PID per screenshot 1..N
- 20 screenshot command/response senza process spawn
- request correlation e idempotenza
- timeout request non ferma recording worker
- timeout/restart -> screenshot successivo recupera
- display cache serve API senza nuovo helper
- monitor rimosso -> selected_display_unavailable senza silent switch
- Stop durante screenshot drena bounded
- staging cleanup su success/failure/timeout
- persistence singola e manifest coerente
- API 5 screenshot -> 5 asset/timestamp crescenti
- duplicate request -> un solo asset
- frontend loading/success/failure/retry senza refresh display ridondanti

### Benchmark host/fake

Misurare overhead infrastrutturale senza attribuirlo a ScreenCaptureKit:
- IPC roundtrip
- commit RecordingStore
- N=20 latency distribution
- process spawn count = 0

### REAL_ENVIRONMENT

Sul target Mac:
- 20 screenshot stesso display;
- intervalli 0.5s / 2s / 10s;
- alternanza tra due display;
- recording `both` attivo durante burst;
- zero audio gaps/restart;
- latency p50/p95 e failure rate;
- CPU/RSS bounded;
- TCC deny/grant/relaunch;
- fullscreen/Spaces/display withdrawal;
- worker recovery dopo timeout/errore simulabile.

## Validation

Il selector deve restare STRONG perché il blast radius include native lifecycle, ScreenCaptureKit,
concurrency, persistence e runtime resources.

Durante sviluppo:
- non usare GitHub Actions;
- eseguire i test solo dopo il completamento dell'ondata implementativa;
- usare i comandi repository-owned e un capture-core selector rapido.

Prima di integrazione:
- full diff e target/base fresh;
- source tests richiesti dal profilo;
- packaged-app gate;
- affected E2E call-overlay-screenshot-evidence;
- REAL_ENVIRONMENT resta evidenza separata e non può essere sostituita da fixture.

## Done

Il workstream è completabile solo quando:
- il path produttivo non crea processi per screenshot;
- display discovery non è nell'hot path;
- 20-shot deterministic suite è verde;
- persistence evita il doppio I/O;
- failure recovery non interrompe audio;
- performance evidence espone p50/p95 e rispetta gli SLO approvati;
- target-Mac conferma ScreenCaptureKit/TCC e continuità audio;
- il path legacy one-shot subprocess è rimosso dal prodotto o marcato diagnostic-only.
