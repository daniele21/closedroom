# GCS hybrid meeting storage — archivio remoto opzionale e cache locale

Status: READY
Owner: RecordingStore / CatalogStore / TranscriptionStore; impostazioni e saved Meeting come consumer
Read when: progettare o implementare storage GCS opt-in, backup/ripristino e rilascio spazio dei meeting
Base di pianificazione: `dev` @ `229cef8c35b257258cf5782c1ef22967279bf86b` (2026-10-28). Ricontrollare HEAD, base e consumer a ogni ripresa.
Assi: PRODUCT_FEATURE / ITERATION (piano) / LEAN (solo documentazione) / AGENT_LOCAL (redazione). Implementazione: STRONG almeno per persistenza, credenziali, privacy, file lifecycle e migrazione; selettore del repository vincolante. REAL_ENVIRONMENT dove richiesto per macOS, cattura e recupero.

## User job, risultato e confini

Professionista con archivio ClosedRoom crescente (riferiti 7+ GB, **non misurati nel repository**) vuole selezionare una **destinazione predefinita per i nuovi meeting**, conservare gli originali audio fuori dal Mac, continuare a leggere e cercare offline le trascrizioni, e recuperare il sorgente quando serve. L'utente deve poter migrare anche meeting preesistenti senza perdita di dati.

Risultati osservabili:
1. L'utente sceglie esplicitamente **Solo Mac** (default invariato) oppure **GCS ibrido** per i meeting futuri; la scelta rimane visibile, revocabile e non modifica retroattivamente i meeting.
2. Registrazione, ASR, diarizzazione e analisi locali continuano a funzionare; la cattura e il lavoro attivo hanno staging locale. GCS è archivio di oggetti, **non** servizio di inferenza.
3. Gli audio consolidati sono caricati, verificati e recuperabili; i metadati/trascrizioni rimangono consultabili offline, con backup cloud coerente se scelto.
4. **Solo dopo prove positive di ripristino** può essere abilitata l'eviction dei grandi file locali; indicare esattamente spazio archiviato, cache locale, spazio recuperabile e file non migrabili.
5. Un nuovo Mac può ripristinare archivio e riferimenti senza richiedere il vecchio Mac, con chiavi disponibili; il caso chiave persa deve essere esplicito.

Non-goals: hosting AI su GCP, provider ASR cloud implicito, Cloud SQL/Firestore/multiutente, sync bidirezionale concorrente multi-Mac, pubblicazione automatica dei meeting, compressione lossy, stream diretto su GCS durante la cattura, Cloud Run/VM, supporto simultaneo di più provider, quota totale dell'app/modelli garantita sotto 1 GB. Non usare un mount FUSE come filesystem canonico.

## Evidenza attuale e owners da preservare

- `src/local_asr_server/recordings.py`: `RecordingStore` crea `YYYY-MM-DD/uuid/` e `metadata.json`, possiede tracce, screenshot, note, manifest, eliminazione archivio e startup recovery. `public_metadata()`, `transcribable_tracks()` e `audio_path()` dipendono dalla presenza del file; `list()` e `_load()` scandiscono i manifest locali. **Non basta cancellare l'audio lasciando invariati i metadati pubblici.**
- `src/local_asr_server/catalog.py`: SQLite WAL e indicizzazione, inclusi percorsi e relazioni; esiste migrazione/ricerca di possibili posizioni storiche del DB. Il catalogo non è un sostituto di backup consistente.
- `src/local_asr_server/transcriptions.py`: `TranscriptionStore` persiste JSON/TXT e indice SQLite; il transcript e le revisioni speaker/undo non devono dipendere dall'audio sempre presente.
- `src/local_asr_server/routers/recordings.py`, `routers/transcriptions.py`, consumer di diarizzazione/benchmark e `frontend/src/api/apiClient.ts`: lettura e download tracce, richiedono oggi `Path` locale. Conservare gli URL API e fornire hydration attraverso l'owner.
- `src/local_asr_server/settings.py`, `schemas.py`, `services/settings_service.py`, `frontend/src/pages/SettingsPage.tsx`: solo `recordings_dir` e `transcriptions_dir` locali; nessuna configurazione GCS integrata su questa base.
- `scripts/audit_footprint.py` misura **tree Git / app bundle**, non l'archivio privato degli utenti. Non riutilizzare il suo risultato come misura dei 7 GB.
- `docs/architecture.md`, `SECURITY.md`, `design/ux-contract.json`: default local-first, loopback/auth/origin, owner unico della persistenza, meeting come oggetto primario, concetti tecnici progressivamente esposti.
- `docs/cloud-provider-asr-analysis-implementation-plan.md` riguarda **provider di inferenza**; non attribuirgli ownership del nuovo archivio.

## Decisioni di prodotto e scelta GCP

**Scelta iniziale proposta:** Google Cloud Storage regionale Standard, bucket privato **BYO bucket** (creato/scelto dal proprietario), policy per meeting separata dalla scelta di ASR/LLM. Regione e budget sono configurabili e verificati, non fissati in codice. Cloud Storage è la destinazione durevole; SQLite/manifest locali restano owner di uso e lavoro; niente server sempre acceso.

Prima del codice validare con una prova minima l'autenticazione GCS da app macOS distribuita:
- Percorso utente: OAuth per app desktop con consenso esplicito, privilegi limitati al bucket tramite IAM, token sensibili in macOS Keychain; disconnessione/revoca funzionanti. Valutare schermate di consenso, verifica OAuth, permessi GCP del bucket e project quota. `gcloud` ADC è consentito **solo per sviluppo/test**, mai prerequisito invisibile della UI consumer.
- Niente credenziali service account JSON, secrets, token o chiavi di cifratura in `settings.json`, log, manifest pubblici, repo o bundle.
- Se UX/permessi di BYO bucket non sono accettabili, **fermarsi e rivalutare** una successiva opzione Firebase/provisioning, senza costruire parallelamente due sistemi.
- Cifratura locale autenticata (client-side) dei contenuti remoti, inclusi audio, transcript, screenshot e backup metadati. Usare libreria consolidata, formato versionato e nonce/key derivation sicuri; prevedere export/recovery della chiave indipendente dal Mac **prima dell'eviction**. Cifratura server-side GCS da sola non equivale a privacy end-to-end.
- Nomi oggetto opachi, bucket privato con uniform bucket-level access e IAM minimo, niente URL pubblici, shared links, user text o titolo negli object names; lifecycle, soft delete, region e costi spiegati prima dell'attivazione. GCS soft delete ha normalmente 7 giorni di default: non promettere cancellazione fisica immediata.

Rischi da falsificare: **VALUE** spazio recuperato davvero; **USABILITY** configurazione comprensibile, chiarezza offline/errore/chiavi; **FEASIBILITY** file/path consumers e read-after-evict, recovery senza doppio owner; **VIABILITY** costi e attrito BYO bucket; **PRIVACY/RELIABILITY** chiavi, copia incompleta, delete accidentale, backup consistente e assenza di trasferimenti nascosti.

## Policy dati: destinazione e disponibilità

| Dato | Local-first (default) | GCS ibrido opt-in |
| --- | --- | --- |
| Mic/system/mixed e audio importato come meeting | Originali locali | staging durante cattura/processing; originali cifrati su GCS; cache locale opzionale e vincolata |
| Trascrizioni, segmenti/speaker e analisi | locali | accessibili e ricercabili offline; snapshot/backup cifrati GCS |
| Catalogo/relazioni/identità ID, note e revisioni | SQLite + file canonici | SQLite rimane operativo locale; esportazione **consistente e versionata** per restore cloud |
| Screenshot/frame, manifest e evidenze visuali | locali | opt-in esplicito per queste classi di contenuto; remote encrypted se inclusi, altrimenti mai trasferiti |
| Cache ASR/LLM, modelli, temporanei, token | locali | mai oggetti di backup di default |

Il setting sceglie un **profilo per nuovi meeting**; ogni meeting fissa in metadata la policy effettiva e l'identità del bucket/prefix alla creazione, evitando che un cambio nelle impostazioni lo sposti silenziosamente. Escludere dati di origine indipendente (transcript senza recording, import expert) finché non hanno policy/provenance verificabili. Non copiare automaticamente screenshot solo perché è stato scelto cloud audio.

### Contratto minimo di lifecycle per asset

- Associare a ogni asset un riferimento persistente tipizzato: meeting/track/ruolo, versione schema, identity locale, bucket+object **opaco**, generation, size plaintext/ciphertext, SHA-256 plaintext (privato), checksum ciphertext, crittografia/key version, policy, timestamp di verifica, stato e errore sanitizzato. Non duplicare policy in router/frontend; estendere `RecordingStore` e catalogo con migration atomica/idempotente.
- Stati distinti: `LOCAL_ONLY` → `UPLOAD_QUEUED` → `UPLOADING` → `REMOTE_VERIFIED`; `REMOTE_VERIFIED` può essere `LOCAL_CACHED`, `REMOTE_ONLY`, `HYDRATING` o `UNAVAILABLE`. Eviction è **un'azione** consentita solo su `REMOTE_VERIFIED` e asset non in uso, non un effetto del cambio setting. Persistenza del job/snapshot e recovery crash-safe.
- Upload idempotente con object generation precondition, retry/backoff bounded, checksum end-to-end e verifica integrità/decrypt **prima** di segnare REMOTE_VERIFIED. Un checksum GCS del ciphertext da solo non certifica il plaintext recuperabile.
- Un asset locale non viene eliminato durante capture, ASR, diarizzazione, benchmark, playback/stream attivo, snapshot backup incompleto o finché non esistono chiavi di recupero. Evitare race con read lease/reference count; pin e quota cache persistenti, scratch per file maggiori della quota con controllo spazio libero.
- Playback/download/API/ASR riutilizzano i consumer esistenti; un solo accessor nel dominio fornisce `Path` temporanei con lease e cleanup bounded. Evitare Cloud Storage calls dentro GET catalogo/list/search. Offline: testo resta disponibile e audio remoto mostra stato e retry, non "file corrotto".
- Backup: snapshot applicativo del catalogo e file metadata/transcript/relazioni **a barriera di consistenza** (no copia opportunistica di DB WAL), manifest versionato, commit remoto atomico logico e restore deterministico che preserva ID, speaker, note, analysis, archive e dipendenze. Rifiutare backup misti/incompleti.
- Delete: distinguere `Elimina copia locale`, `Rimuovi cache`, `Elimina meeting ovunque`; per quest'ultima orchestrare tombstone, SQL/FS e cancellazione remota ritentabile, protezioni su riferimenti condivisi e semantica GCS soft delete. L'attuale `delete_archived_meeting()` non copre oggetti remoti.

## Esperienza critica e comportamento recuperabile

`Impostazioni → Archiviazione`: destinazione predefinita (solo Mac / GCS), connect/test bucket, cosa lascia il Mac, cosa viene trasferito (audio/trascrizioni/screenshot), backup/recovery key, pulizia automatica **inizialmente disattivata**, quota cache e stato sincronizzazione. Config expert GCP progressiva. Consentire di disattivare GCS **senza** far perdere i meeting remoti.

`Saved Meeting`: piccola indicazione di disponibilità (`Solo Mac`, `Backup in corso`, `Archiviato`, `Solo cloud`, `Offline`, `Errore`) e una singola azione pertinente (`Riprova`, `Scarica audio`, `Rendi disponibile offline`, `Libera copia locale`). Nessuna nuova pagina meeting o secondo job store. Controlli accessibili con tastiera/VoiceOver e progress/error su route change.

Percorso: consenso e test connessione → registra/stop locale → processing locale → upload cifrato in background bounded → verifica → backup coerente → stato verificabile → eviction opzionale → playback o diarizzazione da GCS con hydration esplicita → liberazione cache. Errori/rete assente/credenziali revocate non cancellano mai l'unica copia valida.

## Grafo di lavoro (ownership senza conflitti)

| ID | Stato | Outcome autonomo verificabile | Scrittura canonica proposta | Dipende da |
| --- | --- | --- | --- | --- |
| CS-0 | READY | Audit privato read-only degli **user data**: audio per track, transcript, visual, cache, DB, duplicati fisici e spazio liberabile; solo aggregati, niente contenuto/path privati | nuovo script di audit dati e test fixture dedicati; **non** `audit_footprint.py` | — |
| CS-1 | READY | Decision record UX/privacy, minacce, IAM/OAuth/Keychain/recovery provati su bucket test; criteri di go/no-go BYO GCS | `docs/workstreams/...` (questo file), futura ADR solo dopo decisione; fixture spike fuori dai dati reali | — |
| CS-2 | BLOCKED | Settings validati, profilo per meeting, schema asset/reference e migrazione idempotente; i metadati remoti non sostituiscono owner locale | `settings.py`, `schemas.py`, `services/settings_service.py`, `recordings.py`, `catalog.py`, migration/test | CS-1 |
| CS-3 | BLOCKED | GCS adapter autenticato/cifrato, trasferimenti robusti e contratti checksum/mock, senza inviare dati prima dell'opt-in | nuovo adapter GCS e test isolati; integrazione attraverso owner CS-2, **non** router diretti | CS-1; interfaccia congelata con CS-2 |
| CS-4 | BLOCKED | Pipeline backup remota per trascrizioni/metadati e restore su catalogo vuoto, versionati e verificati | `transcriptions.py`, owner snapshot/restore, test DB/rollback; non modificare `recordings.py` in parallelo a CS-2 | CS-2, CS-3 |
| CS-5 | BLOCKED | Upload audio post-finalize e recovery dopo crash/retry, senza eviction | coordinamento `RecordingStore`, uploader bounded, `routers/recordings.py` solo integrazione, test lifecycle | CS-2, CS-3 |
| CS-6 | BLOCKED | Accessor con lease/hydration per playback, ASR e speaker/benchmark, quota/cleanup e ripresa offline | owner asset accessor + adapters consumer; serializzare edit a `recordings.py` con CS-5 | CS-5 |
| CS-7 | BLOCKED | Eviction e delete cloud/locale sicuri, policy esplicita, fail-closed e recupero disconnessione | `RecordingStore`, `catalog.py`, test recovery/delete; serializzare con CS-4/5/6 | CS-4, CS-6 |
| CS-8 | BLOCKED | Settings e Saved Meeting UI, stati comprensibili, accessibilità e recovery; senza duplicare storage state | `frontend/src/pages/SettingsPage.tsx`, saved Meeting components, UI tests, `design/ux-contract.json` **a integrazione** | contratto CS-2; mock stati concordati con CS-5/6 |
| CS-9 | BLOCKED | Migrazione legacy read-only preview → upload/check → backup/restore proof → commit/evict opzionale; report aggregati e resume | migration CLI/service e test su fixture di layout storici; integra con store in sequenza | CS-4, CS-5, CS-6, CS-7 |
| CS-10 | BLOCKED | Esperienza E2E GCS + offline + restore + crash + tracking footprint; documentazione attuale coerente | E2E e contract tests, `docs/architecture.md`, `docs/features.md`, `SECURITY.md`, README usage, `docs/current-state.md` quando integrato | CS-4..9 |

Parallelismo consentito: **CS-0 e CS-1**, poi **CS-3 (adapter isolato) e CS-2 (schema/store)** dopo contratto scritto. **CS-8 mock UX** dopo contratto pubblico stabilizzato, evitando modifiche simultanee a store/schemas. CS-4/5 non devono scrivere insieme le medesime migrazioni; convergere presto a PR piccole, ognuna da `dev` corrente, e integrare prima di ripartire. Nessuna PR stacked che nasconda il vero base.

## Sequenza di rilascio e gates

1. **Decision gate / CS-0+CS-1:** misurare dati reali con audit non invasivo su Mac, provare OAuth/Keychain, permessi e decrypt/restore di fixture. Se chiavi recuperabili, consenso o UX GCP non sono fattibili: NARROW_SCOPE verso backup manuale/no eviction o CHOOSE_ALTERNATIVE, non forzare GCS.
2. **Milestone A — backup senza perdita:** CS-2/3/4/5. Cloud copia opzionale, nessuna pulizia audio; test indipendenti di accesso cloud e roundtrip byte-exact. Fermo punto di recupero.
3. **Milestone B — on-demand audio:** CS-6/8. Riapertura audio/diarizzazione con lease; timeout, cancellazione, offline e quota testati; nessuna dipendenza dal cloud per leggere trascrizioni.
4. **Milestone C — spazio recuperato:** CS-7/9. Solo dopo restore cross-Mac e prove di crash, abilitare eviction opt-in, migrazione dry-run, percentuale di recovery e spazio effettivamente riconquistato.
5. **Integration / CS-10:** PR → `dev` dopo selector `python3 scripts/select_validation_profile.py --base <base> --head <head> --stage integration`; profilo mai inferiore al selezionato. E2E di playback, ASR, diarizzazione, delete e restore; UI material UX richiede FULL_MEDIA. Stable `dev → main` richiede RELEASE/FULL e target-Mac reale.

### Prove obbligatorie, con fixture e cloud di test separato

- **Unit/contract:** settings opt-in false/default, invalid bucket/no permissions, auth revocation, Keychain secret redaction, path traversal, encryption format/version/recovery, checksum tampered, upload crash/retry/generation precondition, no duplicate state, stale catalog e backup snapshot atomico.
- **Recovery/migration:** empty Mac → restore ID/metadata/transcript/notes/speaker/analysis → audio playable; filesystem legacy e layout multipli senza duplicati; backup old/new schema; interruzione a ogni checkpoint; no-delete when pending jobs/lease/key unavailable.
- **Negative:** rete assente in registrazione, credenziale revocata a metà, quota piena, oggetto mancante/alterato, cloud soft-delete, storage cache pieno, crash durante eviction/delete, upload residuo; nessuna perdita dell'unica copia, nessuna inferenza remota implicita.
- **Performance/privacy:** audio lungo su Mac Apple Silicon reale con capture nativa mic/system, tempi di upload/download, throttling bounded e pressione disco, non bloccare cattura/HeavyWorkloadArbiter, no payload sensibili in log/telemetria, footprint locale misurato prima/dopo esclusi modelli bundle e cache AI estranea. Test deterministic CI **non** provano Keychain/TCC/MLX/Metal e rete reale.
- **Evidenze:** test Python proprietari (`test/test_recordings.py`, `test/test_recording_api.py`, `test/test_settings_service.py`, `test/test_transcription_service_cache.py` e nuovi), frontend lint/typecheck/journey, `python3 scripts/verify_docs.py`, e gate selezionati da `.engineering/commands.json`. Solo snapshot/revisioni esatte permettono claim PASS.

## Primo slice eseguibile e checkpoint

**Prossima azione CS-0 + CS-1:** produrre audit read-only su data root senza aprire file contenuti, misurare quali categorie compongono i 7+ GB; nel contempo fissare la decisione di autenticazione GCS e prova reale di ripristino chiave. Nessuna modifica ai dati utente. Acceptance: totali aggregati, differenza tra byte logici e spazio fisicamente liberabile, casi di layout storici, policy cloud e confini di sicurezza espliciti.

Checkpoint iniziale: branch `plan/gcs-hybrid-meeting-storage` da HEAD `229cef8c`, nessuna implementazione ancora avviata, nessun PASS sul cloud né sul Mac dichiarato. A ogni ripresa aggiornare qui HEAD/tree/base, fatti provati, ipotesi escluse, blockers, evidence refs e prossima azione discriminante.

## Destinazioni documentali e chiusura

- `docs/architecture.md`: owner, trust boundary, storage contracts, restore e schema quando **implementati**.
- `docs/features.md` (o feature doc dedicato): comportamento utente corrente, opzioni di storage e verification.
- `SECURITY.md`: key lifecycle, cloud access, scope del consenso e remote deletion; `design/ux-contract.json`: UX definitiva.
- README usage e `docs/current-state.md` solo quando il nuovo comportamento è davvero integrato.
- Decisioni durevoli non ovvie → ADR dopo verifica; piano temporaneo eliminato dopo trasferimento del sapere e delle obbligazioni REAL_ENVIRONMENT nei documenti canonici.
