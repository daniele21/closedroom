# GCS hybrid meeting storage — piano di implementazione

Status: ACTIVE — CS-0 audit tool and CS-1 GCS bootstrap prepared; real Mac inventory, GCP bucket and credential/recovery proof pending.
Owner: RecordingStore, CatalogStore, TranscriptionStore; Settings e saved Meeting come consumer
Read when: storage GCS opzionale, backup/ripristino e recupero spazio degli audio
Base: `dev` @ `229cef8c35b257258cf5782c1ef22967279bf86b` (2026-10-28); aggiornare base/HEAD alla ripresa.
Assi: PRODUCT_FEATURE / ITERATION / SCOPED (tooling only, selector authoritative) / AGENT_LOCAL. Future persistence/privacy code requires STRONG at least; target-Mac REAL_ENVIRONMENT where applicable.

## Outcome e product intent

**Utente/job:** professionista con meeting crescenti (7+ GB riferiti, da misurare) vuole una destinazione predefinita per i nuovi meeting: audio integrale su GCP, testo consultabile offline e backup recuperabile anche su un nuovo Mac.

**Successo osservabile:** opt-in GCS revocabile, registrazione/ASR/diarizzazione sempre locali, upload e restore verificati, nessuna perdita dati, cache audio limitata e riduzione spazio misurata dopo eviction. Per ogni meeting stato remoto/locale chiaro; migrazione sicura dei precedenti.

**Non-goals:** cloud inference/fallback implicito, sync concorrente multi-Mac, Cloud SQL/Firestore, stream GCS durante capture, più provider nel MVP, compressione lossy, FUSE, promessa di 1 GB inclusi modelli AI.

**Rischi:** VALUE spazio, USABILITY setup, FEASIBILITY Path, VIABILITY IAM/costi, PRIVACY/RELIABILITY recovery.

## Verifica su dev e owner

- `recordings.py`: `RecordingStore` possiede sessioni `YYYY-MM-DD/UUID`, metadata, tracce, note, screenshot, cancellazione e recovery. `audio_path`, `transcribable_tracks`, `public_metadata`, `list` e `_load` assumono file locali. Estendere **questo owner**, non creare secondo catalogo o rinominare cartelle in gs://.
- `catalog.py`: SQLite WAL e relazioni; DB locale operativo, mai direttamente sincronizzato come file WAL live.
- `transcriptions.py`: export JSON/TXT, speaker revision e indice; mantenere testo/ricerca locale e backup applicativo coerente.
- `routers/recordings.py`, `routers/transcriptions.py`, diarization/benchmark, `frontend/src/api/apiClient.ts`: consumano file/audio attraverso API/path; conservare URL e introdurre accessor con hydration/lease.
- `settings.py`, `schemas.py`, `services/settings_service.py`, `frontend/src/pages/SettingsPage.tsx`: solo percorsi locali; introdurre policy separata da ASR/LLM.

## Decisione iniziale proposta e gate di prodotto

**MVP:** bucket Google Cloud Storage privato BYO (configurato dall'utente), classe Standard e regione scelta esplicitamente. Default app **Solo Mac**; l'opzione GCS non si attiva per effetto della selezione di un provider ASR/LLM. Cattura e processing scrivono staging locale; **solo al termine** si sincronizza. Niente VM/server GCP.

**CS-1 deve provare prima del build:** OAuth desktop con consenso e IAM minimo sul bucket; verifica OAuth, credenziali Keychain, revoca e restore su altro Mac. ADC/gcloud solo per sviluppo; mai service-account JSON/secrets nel bundle o settings. Se BYO GCS non è praticabile, restringere a backup senza eviction o scegliere alternativa, senza doppio provider.

**Cifratura:** client-side autenticata/versionata; Keychain e **recovery indipendente dal Mac provato** prima dell'eviction. Oggetti opachi, bucket privato, IAM minimo; costi download, lifecycle e soft delete espliciti. GCS server-side non è E2E.

## Politica dati e contratti

| Artefatto | Solo Mac (default) | Ibrido GCS opt-in |
| --- | --- | --- |
| Audio mic/system/mixed | originale locale | staging in cattura/processing; originale cifrato GCS; cache locale rimuovibile |
| Transcript, speaker, note e analisi | offline in store locali | offline su Mac + snapshot cloud cifrato |
| Catalogo e relazioni | SQLite e manifest locali | indice locale canonico + snapshot di restore coerente su GCS |
| Screenshot/frame | locali | solo se categoria esplicitamente consentita, altrimenti mai inviati |
| Modelli AI, cache inference, token | locali | esclusi dal backup ordinario |

**Scope policy:** default congelato per ogni nuovo meeting (bucket/prefix, classi dati); cambiarlo non migra i precedenti. Import/transcript indipendenti richiedono consenso/provenance dedicati.

**Asset reference:** schema versionato: meeting/track, object+generation opachi, hash plaintext/ciphertext, key/version, size, verified_at, stato e errore sanificato. Migrazione idempotente, owner unico.

**Lifecycle:** LOCAL_ONLY → UPLOAD_QUEUED → UPLOADING → REMOTE_VERIFIED; dopo verifica: LOCAL_CACHED / REMOTE_ONLY / HYDRATING / UNAVAILABLE. Stati di *backup* e *retention/eviction eligibility* separati dallo stato di upload. Write condizionali generation-match, upload resumable/idempotente, retry/backoff bounded, checksum e prova decrypt/restore **prima** di REMOTE_VERIFIED.

**Eviction:** OFF fino ai gate. Non cancellare mai ultima copia non verificata o file in uso da capture/job/playback/lease; vietata anche con backup incompleto o chiave non recuperabile. Cache e scratch bounded, cleanup sicuro dopo crash.

**Hydration:** un unico accessor canonico restituisce Path temporaneo con lease ai consumer, senza GCS calls durante list/search. Offline: transcript e note funzionano; audio mostra indisponibilità e retry. Scaricare la traccia richiesta, ripristino verificato e riproduzione/diarizzazione corretti senza duplicare audio permanentemente.

**Backup/restore:** snapshot coerente di catalogo, manifest, transcript, speaker, note, analisi e riferimenti; manifest versionato. Restore su Mac vuoto preserva ID/relazioni, segnala oggetti assenti e non lascia cataloghi falsamente completi. No copia del DB WAL live.

**Delete:** distinguere cache, eviction audio e delete ovunque; tombstone idempotenti, protezione riferimenti condivisi, recovery crash e soft delete espliciti. Estendere `delete_archived_meeting`.

## UX critica

`Settings → Archiviazione`: Solo Mac / GCS ibrido; test connessione/bucket; spiega **quali** tipi di contenuto vanno fuori dal Mac; backup e recovery key; quota cache; pulizia automatica OFF fino a restore provato; stato ed errore sanificato. GCP IAM e dettagli tecnici in disclosure avanzata.

`Saved Meeting`: stato comprensibile (Solo Mac / Backup in corso / Archiviato / Solo cloud / Offline / Errore), azione pertinente (Riprova / Scarica / Rendi offline / Libera copia), progress e ripresa dopo cambio pagina. Non creare seconda pagina meeting o secondo job store; tastiera/VoiceOver e no hidden cloud fallback.

Journey: opt-in/test → capture e processing locali → upload cifrato verificato → backup coerente → eventuale eviction → hydration per playback/diarizzazione → cleanup. Errori rete/auth non cancellano l'ultima copia.

## Work graph e parallelismo

| ID | Stato | Deliverable verificabile | Write boundary | Dipende |
| --- | --- | --- | --- | --- |
| CS-0 | ACTIVE | Audit read-only di dati privati: GB per audio/transcript/visual/cache/DB, duplicati fisici, spazio davvero liberabile; solo aggregati | nuovo script e test fixture, **non** audit bundle | — |
| CS-1 | ACTIVE | Decisione UX/privacy/IAM/Keychain/encryption/recovery; prova GCS con fixture e go/no-go BYO | piano, spike isolato; ADR solo dopo evidenza | — |
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

**Test di falsificazione:** offline, auth revocata, bucket negato, upload interrotto/duplicato, checksum alterato, oggetto assente, chiave persa, disco pieno, delete crash, legacy roots, job attivo, cancel, soft delete. Mai unica copia persa, mai PII nei log.

**Evidence owners:** test recordings/API/settings e nuovi storage/backup/migration, frontend lint/typecheck + journey, verify_docs, gates selezionati. CI non sostituisce Keychain/TCC/cattura/MLX/Metal reali; misurare costi su bucket di test.

## Prossimo slice, checkpoint e chiusura

**CS-0/1 ACTIVE.** Audit WAL/SHM: `python3 scripts/audit_meeting_data.py` (legacy: `--extra-recordings-root <path>`); GCS dry-run: `python3 scripts/bootstrap_closedroom_gcs_test.py` (`--apply` richiede autorità GCP). Bucket proposto `gs://project-tests-498508-closedroom-test` in `europe-west8`, Standard, UBLA, PAP e soft delete 7d. Nome non verificato. Fixture: `python3 scripts/probe_closedroom_gcs_fixture.py prepare --directory <dir>` e `verify-local`; upload/restore richiedono `--apply`. Chiave fixture 0600, non Keychain. Pending: Mac inventory, GCS auth e restore remoto.

**Checkpoint 2026-10-28:** feature branch da `dev` `229cef8c`; audit+bootstrap+probe: 11 test locali PASS; compileall PASS. Nessuna verifica GCP, Keychain o Mac reale. CS-0/1 ACTIVE; al resume rivedere head/tree/base.

**Documentazione a integrazione:** `docs/architecture.md` owner/boundary, `docs/features.md` comportamento, `SECURITY.md` chiavi/deletion, `design/ux-contract.json` UX, README usage, `docs/current-state.md` solo quando vero. ADR per decisioni durevoli. Dopo completamento trasferire verità e obblighi REAL_ENVIRONMENT, quindi eliminare questo piano secondo `docs/workstreams/README.md`.
