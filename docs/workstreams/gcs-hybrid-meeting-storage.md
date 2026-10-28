# GCS hybrid meeting storage — piano di implementazione

Status: READY
Owner: RecordingStore, CatalogStore, TranscriptionStore; Settings e saved Meeting come consumer
Read when: storage GCS opzionale, backup/ripristino e recupero spazio degli audio
Base: `dev` @ `229cef8c35b257258cf5782c1ef22967279bf86b` (2026-10-28); aggiornare base/HEAD alla ripresa.
Assi: PRODUCT_FEATURE / ITERATION / LEAN (solo piano) / AGENT_LOCAL. Futuro codice persistence/privacy: selettore almeno STRONG, target-Mac REAL_ENVIRONMENT dove applicabile.

## Outcome e product intent

**Utente/job:** professionista con meeting crescenti (7+ GB riferiti, da misurare) vuole una destinazione predefinita per i nuovi meeting: audio integrale su GCP, testo consultabile offline e backup recuperabile anche su un nuovo Mac.

**Successo osservabile:** opt-in GCS revocabile, registrazione/ASR/diarizzazione sempre locali, upload e restore verificati, nessuna perdita dati, cache audio limitata e riduzione spazio misurata dopo eviction. Per ogni meeting stato remoto/locale chiaro; migrazione sicura dei precedenti.

**Non-goals:** inferenza su GCP o fallback implicito, cloud obbligatorio, multiutente/Cloud SQL/Firestore, live upload durante capture, sync concorrente multi-Mac, supporto più storage provider nel MVP, compressione lossy, promessa 1 GB per app e modelli, mount FUSE come store.

**Rischi:** VALUE (GB realmente liberati); USABILITY (setup bucket/chiavi, offline, errore); FEASIBILITY (consumer che esigono Path locale); VIABILITY (attrito OAuth/IAM e costi GCS); PRIVACY/RELIABILITY (key loss, upload incompleti, delete e restore).

## Verifica su dev e owner

- `recordings.py`: `RecordingStore` possiede sessioni `YYYY-MM-DD/UUID`, metadata, tracce, note, screenshot, cancellazione e recovery. `audio_path`, `transcribable_tracks`, `public_metadata`, `list` e `_load` assumono file locali. Estendere **questo owner**, non creare secondo catalogo o rinominare cartelle in gs://.
- `catalog.py`: SQLite WAL e relazioni; DB locale operativo, mai direttamente sincronizzato come file WAL live.
- `transcriptions.py`: export JSON/TXT, speaker revision e indice; mantenere testo/ricerca locale e backup applicativo coerente.
- `routers/recordings.py`, `routers/transcriptions.py`, diarization/benchmark, `frontend/src/api/apiClient.ts`: consumano file/audio attraverso API/path; conservare URL e introdurre accessor con hydration/lease.
- `settings.py`, `schemas.py`, `services/settings_service.py`, `frontend/src/pages/SettingsPage.tsx`: solo percorsi locali; introdurre policy separata da ASR/LLM.
- `scripts/audit_footprint.py` misura tree/bundle, **non** dati meeting utente: serve audit dedicato senza leggere contenuti.
- Confini: `AGENTS.md`, `docs/architecture.md`, `SECURITY.md`, `design/ux-contract.json`. Lo storico `docs/cloud-provider-asr-analysis-implementation-plan.md` riguarda inferenza, non storage.

## Decisione iniziale proposta e gate di prodotto

**MVP:** bucket Google Cloud Storage privato BYO (configurato dall'utente), classe Standard e regione scelta esplicitamente. Default app **Solo Mac**; l'opzione GCS non si attiva per effetto della selezione di un provider ASR/LLM. Cattura e processing scrivono staging locale; **solo al termine** si sincronizza. Niente VM/server GCP.

**CS-1 deve provare prima del build:** OAuth desktop per account utente, IAM least privilege sul bucket, consenso/scopes e problemi di verifica OAuth, credenziali in macOS Keychain, revoca e restore su Mac diverso. ADC/gcloud solo per sviluppo, non dipendenza invisibile della app. Vietati file JSON di service account nel bundle, secret in settings/log/manifest/API. Se UX BYO GCS è troppo complessa, scegliere NARROW_SCOPE (backup manuale, niente eviction) o CHOOSE_ALTERNATIVE; non implementare Firebase in parallelo.

**Cifratura:** contenuti cloud cifrati e autenticati client-side con libreria consolidata e formato/versione dichiarati. Oltre alla chiave Keychain, occorre **recupero indipendente dal Mac provato** prima di eliminare l'unica copia locale; dichiarare il rischio di perdita chiave. Object names opachi senza titoli/testi; bucket non pubblico, uniform bucket-level access, HTTPS, niente link pubblici. Valutare costi download, regione, GCS soft delete (normalmente 7 giorni) e lifecycle prima di attivare purge. Crittografia server-side GCS da sola non equivale a E2E.

## Politica dati e contratti

| Artefatto | Solo Mac (default) | Ibrido GCS opt-in |
| --- | --- | --- |
| Audio mic/system/mixed | originale locale | staging in cattura/processing; originale cifrato GCS; cache locale rimuovibile |
| Transcript, speaker, note e analisi | offline in store locali | offline su Mac + snapshot cloud cifrato |
| Catalogo e relazioni | SQLite e manifest locali | indice locale canonico + snapshot di restore coerente su GCS |
| Screenshot/frame | locali | solo se categoria esplicitamente consentita, altrimenti mai inviati |
| Modelli AI, cache inference, token | locali | esclusi dal backup ordinario |

**Scope policy:** default salvato per nuove registrazioni e *congelato per ogni meeting* (bucket/prefix e classi dati); cambio di preferenza non migra i precedenti né autorizza upload retroattivi. Import e transcript slegati da meeting fuori scope finché manca policy/provenance esplicita.

**Asset reference:** schema versionato e migrazione idempotente nei canonical store: meeting/track/role, local cache, bucket/object opaco, generation, size, SHA-256 plaintext privato, checksum ciphertext, key/version, verified_at, stato ed errore sanitizzato. Evitare duplicazione di policy/stato in UI/router.

**Lifecycle:** LOCAL_ONLY → UPLOAD_QUEUED → UPLOADING → REMOTE_VERIFIED; dopo verifica: LOCAL_CACHED / REMOTE_ONLY / HYDRATING / UNAVAILABLE. Stati di *backup* e *retention/eviction eligibility* separati dallo stato di upload. Write condizionali generation-match, upload resumable/idempotente, retry/backoff bounded, checksum e prova decrypt/restore **prima** di REMOTE_VERIFIED.

**Eviction:** default OFF fino ai gate; mai cancellare asset con capture, ASR, benchmark, playback, lease, backup incompleto, credenziali/chiave non recuperabili o ultima copia non provata. File grandi oltre quota cache usano scratch temporaneo bounded con controllo spazio libero. Il cleanup non cancella sorgenti in uso e tratta cancel/crash/reboot.

**Hydration:** un unico accessor canonico restituisce Path temporaneo con lease ai consumer, senza GCS calls durante list/search. Offline: transcript e note funzionano; audio mostra indisponibilità e retry. Scaricare la traccia richiesta, ripristino verificato e riproduzione/diarizzazione corretti senza duplicare audio permanentemente.

**Backup/restore:** snapshot applicativo transazionale coerente di catalogo, metadata, trascrizioni, speaker revision, note, analisi, archivi e loro riferimenti; manifest/versione e commit logico remoto. Restore su nuovo Mac deve preservare ID e relazioni, distinguere asset mancanti/corrotti e fallire senza lasciare catalogo falsamente completo. Non copiare a caldo `closedroom.db` WAL.

**Delete:** separare "rimuovi cache", "libera copia locale" e "elimina meeting ovunque". Delete ovunque richiede tombstone, idempotenza SQL/FS/GCS, protezione dei riferimenti condivisi, recovery crash e indicazione della retention/soft delete remota. Estendere il contratto di `delete_archived_meeting`.

## UX critica

`Settings → Archiviazione`: Solo Mac / GCS ibrido; test connessione/bucket; spiega **quali** tipi di contenuto vanno fuori dal Mac; backup e recovery key; quota cache; pulizia automatica OFF fino a restore provato; stato ed errore sanificato. GCP IAM e dettagli tecnici in disclosure avanzata.

`Saved Meeting`: stato comprensibile (Solo Mac / Backup in corso / Archiviato / Solo cloud / Offline / Errore), azione pertinente (Riprova / Scarica / Rendi offline / Libera copia), progress e ripresa dopo cambio pagina. Non creare seconda pagina meeting o secondo job store; tastiera/VoiceOver e no hidden cloud fallback.

Journey: opt-in/test → capture locale → stop + processing → upload cifrato → checksum + decrypt verificato → backup snapshot → disponibilità remota visibile → eviction manuale/opt-in → on-demand hydration per playback/diarizzazione → cache reclaim. Fallimenti di rete/auth non eliminano mai l'unica copia.

## Work graph e parallelismo

| ID | Stato | Deliverable verificabile | Write boundary | Dipende |
| --- | --- | --- | --- | --- |
| CS-0 | READY | Audit read-only di dati privati: GB per audio/transcript/visual/cache/DB, duplicati fisici, spazio davvero liberabile; solo aggregati | nuovo script e test fixture, **non** audit bundle | — |
| CS-1 | READY | Decisione UX/privacy/IAM/Keychain/encryption/recovery; prova GCS con fixture e go/no-go BYO | piano, spike isolato; ADR solo dopo evidenza | — |
| CS-2 | BLOCKED | Settings, policy per meeting, schema asset/catalog e migration idempotente | `settings.py`, `schemas.py`, `settings_service.py`, `recordings.py`, `catalog.py`, test | CS-1 |
| CS-3 | BLOCKED | Adapter GCS con OAuth/cifratura/checksum/retry e mock | adapter e test propri, senza edit simultanei degli store | CS-1; interfaccia concordata con CS-2 |
| CS-4 | BLOCKED | Backup coerente e restore su catalogo vuoto, preservando relazioni | `transcriptions.py`, owner snapshot/restore, test DB | CS-2, CS-3 |
| CS-5 | BLOCKED | Upload post-finalize, retry/crash recovery e zero eviction | RecordingStore/uploader/integrazione router; serializzare con CS-2 | CS-2, CS-3 |
| CS-6 | BLOCKED | Hydration/lease per audio API, ASR, speaker/benchmark; quota e cleanup | accessor+consumer/test, serializzare edit RecordingStore con CS-5 | CS-5 |
| CS-7 | BLOCKED | Eviction e remote/local delete fail-closed | RecordingStore/catalog/test recovery; owner esclusivo di delete | CS-4, CS-6 |
| CS-8 | BLOCKED | Settings + saved Meeting UX, offline/progress/VoiceOver | frontend source, UI tests, design contract in integrazione | CS-2 contract; mock CS-5/6 |
| CS-9 | BLOCKED | Migrazione legacy: dry-run, sync/resume, proof, commit e cleanup opzionale | migration CLI/service + fixture storiche, coordinare store | CS-4..7 |
| CS-10 | BLOCKED | E2E, misure, aggiornamento docs canoniche e integrazione su dev | tests/E2E, architecture/features/SECURITY/README/current-state | CS-4..9 |

**Parallelo reale:** CS-0 + CS-1; poi CS-2 (schema) + CS-3 (adapter isolato). CS-8 può sviluppare mock UI solo dopo contratto API congelato. CS-4/5 condividono store/snapshot → integrazione serializzata; CS-5/6/7 non toccano insieme `recordings.py`. PR piccole basate su `dev` aggiornato, convergenza precoce, no duplicazione proprietari.

## Milestone, acceptance e validation

1. **Gate decisione (CS-0/1):** audit aggregato sul Mac, scenari legacy, OAuth/IAM/Keychain, chiave recuperabile e restore fixture. Se fallisce, no eviction. Il footprint dell'app non è misura dei meeting.
2. **A — Copia sicura (CS-2/3/4/5):** cloud opzionale funzionante **senza cancellazioni**; test byte-exact di transfer/decrypt, backup/restore completo e upload crash/retry.
3. **B — Recupero su richiesta (CS-6/8):** audio riproducibile e diarizzabile dopo hydration, offline leggibile, cache limitata, accessibilità/progress verificati.
4. **C — Recupero spazio (CS-7/9):** dopo prove di restore su Mac distinto/fixture e crash invariants, abilitare eviction opt-in e migrazione dry-run; confrontare byte fisicamente liberati con baseline.
5. **Integrazione (CS-10):** selector `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration`; gates selezionati senza downgrade; E2E percorsi critici con FULL_MEDIA per UX materiale. RELEASE `dev → main`: FULL + evidenza target-Mac pertinente.

**Test di falsificazione:** offline durante capture, credenziale revocata, bucket negato, rete interrotta, checksum alterato, oggetto remoto assente, chiave perduta, quota disco/cache, upload duplicato, cancellazione crash, DB WAL, transcriptions merged, più roots legacy, job attivo, cancel, soft delete. Mai ultima copia cancellata. No dati personali in fixture/log/telemetria.

**Evidence owners:** `test/test_recordings.py`, `test/test_recording_api.py`, `test/test_settings_service.py`, nuovi test storage/backup/migration, frontend lint/typecheck + journey, `python3 scripts/verify_docs.py`; usare `.engineering/commands.json` e selettore per gates effettivi. CI deterministica non sostituisce TCC/cattura/Keychain/MLX/Metal reali; costo GCS verificato su bucket test.

## Prossimo slice, checkpoint e chiusura

**Avviare CS-0 + CS-1** senza toccare dati reali: audit che non apre i contenuti, report aggregato per classe/dedup/spazio reclaimable; prova auth GCS e recovery key su fixture. Acceptance: decisione BUILD/NARROW_SCOPE/CHOOSE_ALTERNATIVE, misure e contratto versione documentati.

**Checkpoint:** piano su `plan/gcs-hybrid-meeting-storage`, base `229cef8c`; nessun test runtime o cloud PASS dichiarato. A ogni sessione aggiornare head/tree/base, fatti, ipotesi escluse con evidenza, blocker e prossimo test discriminante.

**Documentazione a integrazione:** `docs/architecture.md` owner/boundary, `docs/features.md` comportamento, `SECURITY.md` chiavi/deletion, `design/ux-contract.json` UX, README usage, `docs/current-state.md` solo quando vero. ADR per decisioni durevoli. Dopo completamento trasferire verità e obblighi REAL_ENVIRONMENT, quindi eliminare questo piano secondo `docs/workstreams/README.md`.
