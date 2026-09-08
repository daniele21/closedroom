# ClosedRoom Feature Registry

Questo registro e la fonte minima per tracciare le feature di ClosedRoom dal
punto di vista business e tecnico. Ogni modifica funzionale deve aggiornare
questo file oppure dichiarare nel riepilogo finale perche la documentazione non
e cambiata.

## Regole di aggiornamento

- Aggiorna questo registro quando cambi workflow utente, API, persistenza,
  impostazioni, routing audio, analisi, build, bundle o comportamento frontend.
- Mantieni separati valore business, proprietario tecnico, dati persistiti e
  verifica.
- Non copiare endpoint, chiavi settings, nomi modello o path a memoria: ricavali
  dal codice prima di aggiornare il documento.
- Se una feature usa dati condivisi, indica il modulo che fa da fonte di verita.
- Quando una feature tocca UI e backend, aggiorna entrambi i lati della riga.

## Fonti di verita tecniche

| Area | Fonte primaria |
| --- | --- |
| API FastAPI e composition root | `src/local_asr_server/server.py` |
| Path dev/bundle e directory macOS | `src/local_asr_server/paths.py` |
| Impostazioni utente e default | `src/local_asr_server/settings.py` |
| Catalogo SQLite metadati | `src/local_asr_server/catalog.py` |
| Registrazioni e chunk audio | `src/local_asr_server/recordings.py` |
| Archivio trascrizioni | `src/local_asr_server/transcriptions.py` |
| Trascrizione, cache e streaming | `src/local_asr_server/transcriber.py` |
| Runtime locale e servizi gestiti | `src/local_asr_server/runtime/` |
| Routing audio macOS | `src/local_asr_server/audio_router.py` e `src/local_asr_server/macos_audio_helper/` |
| App macOS menu bar e WKWebView | `src/local_asr_server/menubar.py` e `src/local_asr_server/window.py` |
| Frontend React sorgente | `frontend/src/` |
| Frontend statico servito | `src/local_asr_server/static/` |

## Feature attuali

| Feature | Valore business | Superficie tecnica | Persistenza e configurazione | Verifica minima |
| --- | --- | --- | --- | --- |
| Avvio server locale | Espone ClosedRoom come servizio locale per registrare, trascrivere e analizzare audio con accesso protetto same-origin, mantenendo separato il backend dev dall'app macOS. In modalità LLM locale gestita il sidecar resta cold all'avvio, parte solo alla prima fase AI che lo richiede e, dopo il rilascio della residency, viene fermato se rimane inutilizzato oltre la finestra idle posseduta da ClosedRoom. | CLI `local-asr serve`, risoluzione porta in `cli.py` (`1236` normale, `1237` con `--reload` salvo `--port` esplicito), `create_app()`, endpoint pubblici `/health` e `/v1/session`, static serving, middleware auth locale; `RuntimeServiceManager.ensure_llm_ready()` resta l'owner dell'avvio on-demand, `release_llm_residency()` del rilascio modelli e il service manager serializza il bounded idle shutdown con ensure/start/restart/stop. | Token sessione generato in app state o `LOCAL_ASR_API_TOKEN`; CORS solo da `LOCAL_ASR_ALLOWED_ORIGINS`; cache in `.cache/` dev o `~/Library/Caches/ClosedRoom/` bundle. `managed_llm_idle_shutdown_seconds` governa la finestra idle dell'auto-mode posseduto; external/disabled non vengono mutati. | `UV_CACHE_DIR=.cache/uv uv run local-asr serve --reload`, `curl http://127.0.0.1:1237/health`, `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_cli.py' -v`, `test_server_resource_policy_contract.py`, test runtime service manager e bootstrap cookie via `/v1/session` prima delle API protette. |
| App macOS menu bar | Offre avvio nativo, finestra WKWebView e accesso rapido da barra menu, possedendo anche il lifecycle dei sidecar runtime quando avviati dalla app. | `local-asr app`, `menubar.py`, `window.py`, `launchd.py`, `app_identity.py`, `build.sh`, `ClosedRoom.spec`; `build.sh` legge la versione da `pyproject.toml`, produce `dist/ClosedRoom-<version>.app`, rimuove artefatti `.app` non versionati rimasti da build precedenti e passa nome file e display name versionati alla spec PyInstaller, mentre l'eseguibile interno resta `ClosedRoom`; `menubar.py` confronta l'identità esposta da `/health` e, se la porta standard è occupata da una build diversa, sceglie una porta locale libera invece di riusare il vecchio server; `launchd.py` installa l'auto-start puntando al binario dell'app versionata corrente quando è in bundle; `menubar.py` usa le costanti runtime condivise e chiama `RuntimeServiceManager.shutdown()` in uscita. | Risorse bundle risolte da `paths.py`; dati utente in Application Support; sidecar locali fermati allo shutdown dell'app quando la modalità è gestita; `/health` espone `app_version`, `bundle_identifier`, `bundle_display_name`, `bundled` e `pid` per distinguere processi vecchi e build correnti. | Build mirata con `./build.sh --no-dmg` quando cambiano bundle, risorse o helper nativo; `PYTHONPATH=src python -m py_compile src/local_asr_server/menubar.py src/local_asr_server/runtime/service_manager.py`. |
| Workspace macOS adattiva | Mantiene Today, Meeting e Projects dentro una sola gerarchia di prodotto coerente: Meeting resta figlio di Today, Projects è la seconda destinazione peer, New Meeting resta l'azione primaria persistente e Settings/tema/lingua/tour/demo/runtime rimangono utility. La stessa gerarchia resta utilizzabile su finestre wide, compact e narrow senza introdurre un secondo modello di navigazione. | `frontend/src/App.tsx` possiede una sola workspace shell; `frontend/src/workspace.css` possiede rail desktop, toolbar sticky compact/narrow, riduzione label, bounded overflow e reduced-motion. Le pagine esistenti continuano a possedere Today, Meeting, Projects, registrazione, ricerca e preparazione; `design/ux-contract.json` è il contratto UX della gerarchia/adattività. | Nessuna nuova persistenza, API o configurazione runtime. Tema, lingua e altre preferenze continuano a usare i proprietari esistenti; navigazione e responsive chrome sono stato UI derivato, non un nuovo store. | `test/test_frontend_workspace_coherence.py`, frontend lint/typecheck, browser FULL_MEDIA `coherent-macos-workspace` dentro `scripts/browser_meeting_ui_e2e.mjs`, più packaged-app build/lifecycle smoke quando selezionato dal preflight. |
| Registrazione audio locale | Salva audio progressivamente senza avviare automaticamente AI pesante e permette di recuperare sessioni interrotte. Nel normale New Meeting titolo/progetto sono opzionali e ClosedRoom prova mic + audio computer senza chiedere backend, device o diarizzazione; il contesto schermo non entra nel golden path e resta una disclosure secondaria esplicita, disattivata per default. Sorgenti/device audio compaiono solo come recovery quando l'automatico non è disponibile. | `NewRecordingPage`, `useRecorder`, `RecordingStore`, endpoint recording/chunk/stop/recovery. Il meter visibile limita il redraw a circa 12,5 Hz, gli aggiornamenti React dei livelli a 4 Hz, timer a 1 Hz e overlay a 2 Hz; il documento hidden salta il lavoro del meter senza cambiare capture/finalizzazione. Con backend nativo pronto, la disclosure `Contesto schermo` carica le finestre catturabili e passa al recorder una sola sorgente scelta esplicitamente. `/v1/recordings/active`, overlay e `/health` derivano lo stato dalla registrazione persistita, non da flag globali FastAPI. | `<recordings_dir>/<data>/<uuid>/metadata.json` con ledger chunk `sequence`/SHA-256/dimensione; file `.part` finche non finalizzati; stati `interrupted` e `recoverable`; metadati anche in `CatalogStore`. Senza selezione esplicita della sorgente visuale non vengono acquisiti frame. | `test_recordings.py`, `test_recording_api.py`, `test_frontend_new_meeting_simplicity.py`, `test_frontend_recording_efficiency.py`, `test_frontend_visual_on_demand.py` e frontend lint/typecheck. |
| Cattura nativa macOS | Registra microfono e audio computer senza configurazione BlackHole quando macOS 13+, permessi macOS e helper nativo sono disponibili, rendendo evidente il fallback solo quando serve. Può inoltre catturare, solo su opt-in, frame a bassa frequenza da una finestra/schermo scelti per un successivo arricchimento locale. | Helper Swift `native_capture_helper` con AVFoundation e ScreenCaptureKit, `NativeCaptureManager`, endpoint `/v1/capture/capabilities`, `/v1/capture/permissions`, `/v1/capture/request-permissions`, `/v1/capture/ensure-permissions`, `/v1/capture/diagnostics` e `/v1/recordings/{id}/capture/*` (incluso l'event-stream di volume in tempo reale); il New Meeting usa il backend nativo automaticamente quando pronto, mostra selezione sorgente/device audio solo nel recovery e separa la scelta opzionale del contesto schermo. Il preflight richiede i permessi necessari prima della cattura e timer/overlay partono solo sull'evento `ready`. | Tracce WAV `mic.wav`, `system.wav` (16 kHz mono downsampled) e `recording.wav` (mixed via ffmpeg post-stop); `RecordingStore.finalize()` preserva i WAV scritti direttamente dal helper quando esistono placeholder `.part` vuoti; capability/permission/diagnostics separate per Screen Recording/Microfono; `capture_backend`, `capture_status`, `timeline.json`, `quality_report.json`; JPEG visuali restano locali nella sessione; packaging helper invariato. | `test_native_capture.py`, `test_recordings.py`, `test_paths.py`, `test_frontend_visual_on_demand.py`; frontend checks quando cambia New Meeting; `./build.sh --no-dmg` quando cambia helper/bundle. |
| Routing audio macOS | Cattura microfono e audio computer con ripristino dell'uscita originale. | `AudioRouter`, helper Swift/Core Audio, endpoint `/v1/system/audio/*`. | Stato routing in `.cache/audio-routing-state.json`; requisiti BlackHole/helper. | `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_audio_router.py' -v`, confrontando la baseline nota in `AGENTS.md`. |
| Trascrizione audio | Converte upload o registrazioni locali in testo con provider ASR locale MLX o, se esplicitamente selezionato, Speechmatics Batch cloud; la scelta resta local-first di default e vale anche per tracce mic/system registrate. | Endpoint `/v1/audio/transcriptions`, `/path`, `/v1/asr/providers`, `asr_provider.py` come catalogo/provider resolver e owner dei metadati pubblici ASR, `speechmatics_asr.py` per Batch API lazy, `asr_models.py` per runtime locali, `runtime/asr_worker.py`, `services/transcription_service.py`, `routers/transcriptions.py`, `transcriber.py`, `transcription_quality.py`, `TranscriptionStore`, frontend Transcription con selettore provider e opzioni Speechmatics e helper `transcriptionMetadata.ts` per renderizzare provider/modello da campi strutturati. | `settings.json` include `asr_provider`, `speechmatics_region`, `speechmatics_model`, `speechmatics_diarization`, timeout/poll interval e `speechmatics_api_key` write-only. `GET /v1/settings` espone solo `speechmatics_api_key_configured`. La cache SHA-256 include provider, backend, regione, modello provider e diarization; transcript JSON/SQLite salvano `asr_provider`, `backend`, `model`, `provider_options` e `source_tracks[].transcription_metadata` senza API key/header. Speechmatics risolve sempre il modello effettivo dalle opzioni provider/settings, non dal default locale Whisper, crea un job separato per ogni traccia trascrivibile e preserva eventuali speaker label provider come metadata/segment fields senza sostituire le label ClosedRoom `mic`/`system`. Nemotron/Whisper mantengono la pipeline locale precedente. | `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_caching.py' -v`; `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_speechmatics_asr.py' -v`; `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_recording_api.py' -v`; `cd frontend && npm run build`; evitare test rapido con modelli reali per non scaricare modelli grandi. |
| Job trascrizione, analisi e preparazione Meeting | Esegue trascrizioni/analisi come job monitorabili e cancellabili e offre nel Meeting una sola azione durevole `Prepara note` che riusa risultati validi, rende il transcript leggibile appena pronto e riduce il default da quattro inferenze sovrapposte a una estrazione strutturata condivisa per brief, azioni, decisioni e rischi. | `JobStore`, `TranscriptionJobManager`, `AnalysisJobManager`, `MeetingPreparationManager`, `HeavyWorkloadArbiter`, `structured_notes.py`, `structured_notes_projection.py`, `structured_notes_evaluation.py` e `runtime/resource_policy.py`. Il parent `meeting_preparation` persiste composizione e link agli stessi child job esistenti e non introduce queue/worker pesanti. `meeting_default` crea un solo child `meeting_notes_shared` v2; `meeting_deep`, `analysis_types` espliciti e percorsi expert restano compatibili. Input lunghi usano chunk source-aware bounded + aggregazione; input oltre il budget falliscono esplicitamente invece di essere troncati. Le quattro viste legacy sono proiezioni read-only del run canonico. | Job, eventi e relazioni parent→child restano in SQLite. `analysis_runs` persiste solo l'esecuzione fisica canonica v2; le proiezioni `meeting_brief`, `action_items`, `decisions` e `risks_blockers` non creano job o righe DB sintetiche. La cache v2 include identità di segmenti, timing, speaker e testo; ogni output non vuoto richiede `source_refs` validi e i vecchi run v1 restano leggibili. La dedupe di preparazione continua a includere recording/source, opzioni ASR e identità template/analisi; cancel/restart/resume mantengono gli invarianti PRS-12. | `test_shared_analysis_pipeline.py`, `test_structured_notes.py`, `test_structured_notes_source_boundaries.py`, `test_meeting_preparation.py`, suite job/analysis/transcription, frontend lint/typecheck, browser FULL_MEDIA `meeting-preparation-recovery` e packaged-app smoke quando selezionati dal preflight. |
| Note Meeting verificabili e modificabili | Permette di verificare azioni e decisioni contro la registrazione, correggerle senza perdere l'output generato e mantenere le correzioni dopo reload/restart. Una rigenerazione crea una revisione: correzioni compatibili vengono riapplicate, mentre cambi o rimozioni diventano conflitti espliciti invece di essere rimappati in silenzio. | `structured_note_edits.py` assegna identità deterministica e fingerprint agli item e applica l'overlay; `structured_notes_projection.py` ricostruisce revisioni/proiezioni; `routers/analysis.py` espone PATCH/DELETE sugli item con 409 per fingerprint stale; `StructuredNotesEditor.tsx` rende azioni/decisioni editabili, fonti temporali e recovery dei conflitti nel Meeting. | `CatalogStore.analysis_runs.result_json` resta l'unico owner persistente: conserva `generated`, `user_edits`, `effective`, `revision` e `conflicts` senza nuova tabella o migrazione. Ogni nuovo edit conserva anche lo snapshot generato di base con `source_refs`; `item_missing` mantiene quindi evidenza verificabile finché l'utente non scarta esplicitamente la correzione. Un `user_edits: []` esplicito sulla nuova revisione impedisce di re-ereditare edit già scartati. I vecchi v2 vengono decorati read-time e i v1 restano invariati. | `test_structured_note_edits.py`, `test_structured_note_projection_edits.py`, `test_structured_note_catalog_persistence.py`, `test_structured_note_api.py`, `test_frontend_structured_notes_editor.py`, frontend lint/typecheck, browser FULL_MEDIA `meeting-note-edit-revision` e packaged-app smoke quando selezionati dal preflight. |
| Diagnostica meeting e fallback | Rende subito utilizzabile un Meeting salvato anche se diagnostica o servizi visuali sono lenti/non disponibili, e rende visibile quando un arricchimento è fallito o ha usato un backend sostitutivo senza trasformare il problema accessorio in un errore dell'intero Meeting. | `MeetingDetailPage` carica come core solo `/v1/meetings/{id}`. Il report condiviso `meeting_diagnostics.py` e l'endpoint autenticato `/v1/meetings/{id}/diagnostics` vengono richiesti solo quando l'utente apre Dettagli; il frame-list `/v1/recordings/{id}/visual-frames` e il dettaglio visual intelligence sono disclosure dell'area Analisi. Errori accessori hanno stato/retry locale, le risposte stale A→B vengono ignorate e i reload terminali sovrapposti vengono coalescati. Restano inoltre il contratto centrale `diagnostics.py`, outcome/eventi in `TranscriptionService`/`TranscriptionJobManager`, la pagina risultato Trascrizione, CLI `local-asr inspect-meeting`, `macos_permissions.py` e `/v1/system/accessibility`. | `stats.diagnostics` e `stats.outcome_status` nel transcript JSON/SQLite, payload degli eventi job e log ruotato `~/Library/Logs/ClosedRoom/closedroom.log`; registra backend richiesto/effettivo per traccia, fallback, causa, errore, contatori e durata. I log includono `recording_id`/`job_id` e redigono token e secret. I nuovi loading boundary non aggiungono persistenza, telemetry o chiamate AI. | `test_diagnostics.py`, `test_frontend_diagnostics.py`, `test_frontend_meeting_fast_open.py`, browser journey `saved-meeting-fast-open` con ready/partial/error/recovery screenshot + MP4, `test_macos_permissions.py`, `test_bundled_module_dispatch.py`, test diarizzazione/visual/audio intelligence; frontend lint/typecheck e packaged-app smoke quando selezionato dal preflight. |
| Audio intelligence shadow | Arricchisce le trascrizioni di registrazioni con metriche locali leggere su canali, tempo parlato, pause, overlap, speech rate, energia e insight mock provvisori, senza chiamare LLM e senza generare clip audio persistenti; la UI mostra una card dedicata nel dettaglio registrazione e badge sui segmenti trascritti. | Modulo `audio_intelligence`, integrazione in `run_recording_transcription()`, endpoint read-only `/v1/recordings/{id}/intelligence`, client React `ApiClient.recordingIntelligence()` e pannello `AudioIntelligencePanel`; calcolo RMS a finestre con lettura streaming WAV o pipe `ffmpeg`. | `intelligence.json` compatto nella directory registrazione; summary in `stats.audio_intelligence`; segmenti arricchiti con `channel`, `pause_before`, `speech_rate_wpm`, `energy`, `overlap`; `analysis` resta riservato al futuro risultato LLM. | `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_audio_intelligence.py' -v`; `UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -p 'test_recording_api.py' -v`; `cd frontend && npm run build`. |
| Diarizzazione speaker post-meeting | Separa gli interlocutori in cluster temporali senza richiedere a priori il numero di partecipanti. Nel workflow tecnico/import l'utente può ancora scegliere per-run `Disattivata`, FluidAudio locale o Speechmatics cloud e può ricalcolare soltanto gli speaker; il normale New Meeting non espone più un toggle diarizzazione. Nelle registrazioni a tracce separate il MIC resta un unico speaker noto e soltanto SYSTEM viene processato dal backend scelto. | `speaker_diarization.py` possiede FluidAudio, lease runtime, cluster grezzi, copertura transcript e assegnazione temporale; `transcription_diarization.py` orchestra diarizzazione iniziale/rerun track-aware; `speaker_labels.py` unisce cluster grezzi e segmenti. `TranscriptionService`, `routers/transcriptions.py`, `ConfigureStep.tsx`/`ResultsStep.tsx` mantengono l'override per i power workflow. | La cache pipeline è versionata e include provider, regione e modello di diarizzazione. `speaker-diarization.json` e transcript JSON/SQLite conservano timeline, cluster e mapping; il rerun rimuove mapping/nominativi precedenti perché gli ID cluster non sono stabili. Speechmatics richiede API key e può generare costi. | `test_transcription_diarization.py`, `test_speaker_diarization.py`, `test_speaker_labels.py`, `test_caching.py`, `test_job_store.py`, `test_recording_api.py`; compilazione SwiftPM e frontend checks. |
| Visual intelligence post-meeting | Offre contesto visivo locale solo quando l'utente lo sceglie: New Meeting mantiene l'audio come golden path e presenta `Contesto schermo` come disclosure secondaria off-by-default. Se viene selezionata una sorgente, ClosedRoom conserva frame a bassa frequenza senza avviare VLM durante la registrazione; dopo la trascrizione Meeting verifica la disponibilità dei frame soltanto entrando in Analisi ed espone `Analizza contesto schermo` solo se i frame esistono. | `visual_intelligence/`, `PostMeetingVisualService`, `routers/visual_jobs.py`, API visual-frame/v2 visual intelligence/debug, `frontend/src/api/visualJobs.ts` e consumer Meeting/Results. La normale apertura di Meeting non enumera i frame e non carica visual intelligence; l'azione esplicita crea un job persistito/cancellabile `visual_intelligence` tramite l'esistente `TranscriptionJobManager`/`HeavyWorkloadArbiter`, arricchisce la trascrizione esistente in place e forza per-run il routing task-aware `v2` senza mutare Settings. Il router esegue candidate detection/dedupe e poi applica un hard ceiling di 2048 work item con sampling deterministico sull'intera timeline; un errore del router in `v2` esplicito fallisce chiuso e non degrada al legacy non bounded. | JPEG e manifest restano in `.visual-staging/`; artefatti promossi in `visual-runs/<generation-id>/` e `current_visual_generation.json`. La trascrizione mantiene lo stesso ID/path/created_at e riceve solo gli artefatti/statistiche visuali aggiornati; il `job_id` runtime non viene persistito come campo del transcript. Cleanup TTL rimuove checkpoint/generazioni incomplete, non i frame. Settings visuali restano compatibili in Advanced per i workflow tecnici/legacy. | `test_visual_intelligence_service.py`, `test_visual_intelligence_router.py`, `test_visual_on_demand.py`, `test_frontend_visual_on_demand.py`, `test_frontend_diagnostics.py`, `test_frontend_meeting_fast_open.py`, browser journey `saved-meeting-fast-open`, `test_recording_api.py`, frontend lint/typecheck e packaged-app smoke. |

Scelta Qwen per-run: prima di trascrivere una registrazione salvata, la UI
tecnica permette ancora di abilitare o disabilitare l'analisi immagini per
quella singola esecuzione. Il valore iniziale deriva da
`visual_intelligence_enabled`, non modifica le impostazioni persistenti e viene
incluso nella cache della pipeline. Quando è disabilitato, il job non entra
nello step `visual_processing`, non invia progress immagini e conserva i frame
per un eventuale run futuro. Questo resta un power/compatibility workflow distinto
dall'azione visuale on-demand di Meeting. Durante l'elaborazione la UI espone
inoltre `Interrompi elaborazione`: per le registrazioni richiede il cancel del
job persistente e la pipeline si arresta al successivo confine sicuro, inclusa
la fine dell'inferenza visuale corrente; per gli upload interrompe direttamente
lo stream HTTP.

Nota qualità P2: in modalità v2 `visual_intelligence/adapter.py` confronta le
firme dei bordi possedute da `signatures.py`; quando rileva un unico nuovo
highlight, `ocr.py` usa macOS Vision sulla label e accetta soltanto un match
non ambiguo con i partecipanti noti. Il successo crea una osservazione locale
e salta Qwen; indisponibilità, errore o ambiguità fanno fallback a Qwen. Il
summary registra `ocr_attempt_count`, `ocr_bypass_count` e `qwen_call_count`.
`datasets/visual-meetings/`, `visual_intelligence/benchmark.py` e
`scripts/replay_visual_intelligence.py` possiedono fixture e quality gate
riproducibili senza dati reali, ASR o inferenza Qwen.

Nota affidabilità worker ASR: `runtime/asr_worker.py` mantiene aperto il drain
IPC finché sia il processo sia il thread lettore stdout sono terminati. Questo
evita di perdere il messaggio JSON `result` quando viene accodato subito dopo
l'uscita del processo, caso che in precedenza produceva il falso errore
`ASR process exited without returning result`. Inoltre `cli.py` esegue
esplicitamente `main()` anche sotto `python -m local_asr_server.cli`, requisito
del worker separato in sviluppo: senza questo entry point il processo usciva
con codice 0 senza avviare ASR né restituire JSON. Le regressioni sono coperte
da `test/test_asr_worker.py`.

Nota progresso ASR locale: durante `transcribing_mic` e
`transcribing_system`, `TranscriptionService` persiste un
`ASRTrackProgress` con traccia corrente, durata audio, secondi elaborati,
percentuale, tempo trascorso ed ETA. `runtime/asr_worker.py` inoltra i
timestamp verbose di Whisper, mentre Nemotron emette avanzamento strutturato
dalla propria timeline cumulativa; in assenza temporanea di nuovi segmenti un
heartbeat aggiorna comunque job e log UI. L’ETA resta in calcolo finché non
esiste progresso reale sufficiente. Verifica: `test/test_asr_worker.py`,
`test/test_nemotron_asr.py` e build frontend.

La UI di avanzamento descrive inoltre obiettivo, percentuale interna ed ETA
della fase attiva per tutti i cinque step narrativi. Le fasi prive di una
metrica backend affidabile mostrano esplicitamente che la stima non è ancora
disponibile; completate e future restano rispettivamente al 100% e 0%. Ogni
transizione di step alimenta anche il log tecnico, indipendentemente dalla
presenza di eventi ASR o visuali dettagliati.

Nota nomi speaker: `speaker_labels.py` è la fonte centralizzata per trasformare
i cluster `provider_speaker` in label visibili. La priorità è nome manuale,
nome visuale Qwen accettato, quindi fallback stabile `Speaker N`. Il contratto
`PATCH /v1/transcriptions/{id}/speakers` salva le correzioni, rigenera full
text e segmenti e aggiorna JSON/TXT e catalogo SQLite. La pagina risultato
espone un campo modificabile per ogni cluster anche quando Qwen VL non dispone
di frame o si astiene. Anche le trascrizioni precedenti vengono normalizzate
in lettura, senza richiedere una nuova inferenza ASR.

Nota storage e immagini: l’avvio CLI e menu bar non congelano più un
`recordings_dir` parallelo, ma seguono il valore persistito mostrato nelle
impostazioni; `--recordings-dir` resta un override solo se esplicitamente
fornito. `RecordingStore` mantiene lettura compatibile dal precedente default
`~/Recordings/local-asr`, mentre le nuove registrazioni usano il path UI. La
pagina risultato legge i JPEG preservati tramite API autenticata e mostra una
galleria anche quando Qwen VL fallisce. Il sidecar assegna inoltre una porta
libera al processo interno `mlx_vlm.server`, evitando collisioni con worker
visuali orfani sulla precedente porta fissa. Il processo viene avviato in un
process group dedicato e stop/restart terminano anche i figli; il preflight
elimina esclusivamente processi il cui comando contiene `-m mlx_vlm.server`,
così un arresto precedente non può lasciare un backend visuale stale.
Le scritture atomiche di metadata, timeline e artefatti usano file temporanei
univoci per operazione, evitando collisioni `*.tmp` quando stop cattura, retry
trascrizione e pipeline visuale aggiornano contemporaneamente la stessa
sessione.

Nota lifecycle porte: `runtime/port_manager.py` è la fonte di verità per il
preflight delle porte API. CLI e menu bar leggono
`runtime-state.json`, verificano PID, comando processo e `/health`, terminano
tutte le precedenti istanze API ClosedRoom, incluse quelle orfane non più
registrate o avviate su un'altra porta, attendono il rilascio della socket e
registrano atomicamente l'unica nuova ownership. Wrapper `uv`, worker ASR,
helper nativi e processi estranei non vengono terminati. Server standard,
reload e menu bar sono quindi mutuamente esclusivi. Verifica:
`test/test_port_manager.py`, `test/test_cli.py` e `test/test_paths.py`.