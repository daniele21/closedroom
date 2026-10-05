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
| SC-0 | baseline metriche e trace current path | native manager/helper | — | ACTIVE |
| SC-1 | protocollo JSONL + ScreenshotWorker persistente | helper + manager | — | ACTIVE |
| SC-2 | DisplayRegistry cached senza ScreenCaptureKit hot-path | helper + manager + API | SC-1 | ACTIVE |
| SC-3 | timeout locale, health, restart e backend fallback | worker | SC-1 | PLANNED |
| SC-4 | staging/atomic commit RecordingStore senza read/write duplicato | RecordingStore + API | SC-1 | PLANNED |
| SC-5 | overlay state/feedback rapido e no refresh display ridondanti | frontend | SC-2 | PLANNED |
| SC-6 | capture-core deterministic suite + benchmark harness | tests/scripts | SC-1..5 | ACTIVE |
| SC-7 | target-Mac burst/perf/TCC/audio-continuity evidence | real environment | SC-1..6 | PLANNED |
| SC-8 | rimozione runtime path one-shot subprocess legacy | manager/helper | SC-7 | PLANNED |

SC-1, SC-2 e SC-6 sono intenzionalmente sviluppabili in parallelo dopo il contratto sopra.

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
