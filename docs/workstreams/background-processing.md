# Elaborazioni in background e Attività globali

Status: READY
Owner: job/persistence, importazione audio e frontend workspace
Read when: completare i job tra schermate.

## Risultato

Avviare una trascrizione o un'analisi, cambiare schermata e continuare a usare
ClosedRoom, ritrovando avanzamento, annullamento e risultato da qualunque vista.
Include registrazioni salvate, audio importato e analisi di testo/file.
Il lavoro prosegue mentre il server resta attivo; il riavvio interrompe il run e
consente un nuovo avvio esplicito, senza promettere ripresa dal punto raggiunto.

## Base verificata e confini

- `runtime/workload_arbiter.py`: unico scheduler pesante; default 1 attivo e 8
  pendenti. Le prenotazioni capture trattengono i job in attesa senza uccidere
  quelli attivi. Conservare questa precedenza e la resource policy.
- `jobs/job_store.py`: stato, payload, risultato, cancellazione ed eventi SQLite.
  `server.py` marca i run incompleti `interrupted` al riavvio.
- `transcription_jobs.py` e `analysis_jobs.py` eseguono indipendentemente dalla UI.
  `meeting_preparation.py` compone child job e conserva dedupe/riuso esistenti.
- `routers/transcriptions.py`: lista `/v1/jobs`, snapshot, eventi SSE e cancel.
  La lista attuale è per recenza e limitata a 500; non basta a garantire la
  scoperta di tutti i job attivi sotto uno storico molto popolato.
- `api/jobEvents.ts` e `hooks/useMeetingJobEvents.ts`: follower SSE e consumer
  Meeting esistenti; le pagine dedicate usano ancora polling e stato locale.
- `TranscriptionPage.tsx`: registrazioni via job; file audio via richiesta
  streaming diretta. Il loop job non include oggi `interrupted` tra i terminali.
- `AnalysisPage.tsx`: analisi via job, ma pre-trascrizione audio importato diretta;
  ritorno alla pagina senza recupero uniforme del run.
- `App.tsx` smonta le pagine al cambio route; manca una vista Attività globale.

Esclusi: coda distribuita, più concorrenza, riordino, esecuzione ad app chiusa,
notifiche di sistema, auto-retry. Preservare compatibilità API dirette.

## Invarianti

- Store esistenti restano proprietari di job, sorgenti, run e risultati.
- Un solo `HeavyWorkloadArbiter`; nessuna inferenza dentro nuovi worker UI/import.
- Local-first, cloud solo opt-in; auth/origin/loopback invariati. Nessun testo,
  audio, prompt o risultato sensibile in telemetry, log ordinari o storage UI.
- Cambio route e chiusura SSE fermano solo l'osservazione, mai il job. Cancel
  resta esplicito/cooperativo; `cancelling` non equivale a `cancelled`.
- Importazione bounded e cancellabile, path dagli owner; cleanup run-owned su
  errore/cancel/timeout/inizializzazione parziale e recupero residui dopo crash.
- Risultati validi e sorgenti sopravvivono a errori di arricchimento. Niente
  inferenze duplicate causate da remount, reconnect o retry di rete ambiguo.
- UI source in `frontend/src/`; nessuna modifica di artefatti finalizzati.

## Esperienza concordata per l'implementazione

Percorso: scegli sorgente → avvia → ricevi conferma → continua altrove → apri
Attività → controlla/annulla/apri risultato. Nessuna navigazione automatica
quando il run termina mentre stai lavorando in un'altra schermata.

- Entry Attività nella shell, con conteggio dei lavori attivi; disclosure di
  lista in corso/in attesa e storico recente. Nessun nuovo dashboard dominante.
- Riga: tipo, sorgente riconoscibile, stato e progresso reale; niente ETA o
  posizione di coda dedotta dalla recenza. Parent preparation come una attività
  principale; child visibili nei dettagli, senza conteggi/notifiche duplicati.
- Azioni contestuali: Apri, Annulla se attivo, Apri risultato se completato,
  Riprova se fallito/interrotto. Il retry crea un nuovo job correlato e riusa i
  risultati validi secondo gli owner; opzioni/provider restano quelli espliciti.
- Offline: mostra ultimo stato come non aggiornato, riconcilia al reconnect e
  non reinvia un avvio senza conoscerne l'esito. Errore/coda piena recuperabili.
- Feedback in-app al terminale, una volta per run osservato; nessuna raffica per
  storico ricaricato. Risultati disponibili anche se il completamento avviene
  durante assenza/disconnessione. UI metadata minimo, senza duplicare payload.
- Importazione distinta dall'elaborazione: il job parte solo dopo sorgente
  durevole. Il trasferimento deve sopravvivere al cambio route tramite owner
  nella shell e offrire cancel; reload può interromperlo con cleanup esplicito.
- Accessibilità e layout seguono componenti/token e `design/ux-contract.json`.

## Work graph

Fasi sequenziali; `BLOCKED` indica una dipendenza non completata.

| ID | Esito osservabile e confine di scrittura | Dipende da | Stato |
| --- | --- | --- | --- |
| BG-1 | Contratto recuperabile: lista attivi/storico, snapshot/eventi, identità sorgente/risultato e terminali uniformi. Owner: jobs, router/schemas, manager, test/API client. | — | READY |
| BG-2 | Audio importato elaborabile come le registrazioni, senza cattura fittizia; composizione audio→analisi persistita. Owner: RecordingStore/router, manager preparation/analysis, client e test. | BG-1 | BLOCKED |
| BG-3 | Cambiare schermata conserva osservazione e contesto; ritorno o reload recupera i job dal server. Owner: shell/provider frontend, jobEvents, pagine e consumer Meeting. | BG-2 | BLOCKED |
| BG-4 | Attività globali con cancel, risultato, retry e feedback accessibili. Owner: App/componenti/i18n/design, test UI. | BG-3 | BLOCKED |
| BG-5 | Percorso completo verificato e pronto all'integrazione. Owner: test, browser E2E/registro, docs durature; preflight sul candidato. | BG-4 | BLOCKED |

### BG-1 — contratto e recupero

Audit dei consumer/fake prima di estendere API. Definire filtri server-side per
attivi e storico bounded/paginabile, senza perdere attivi oltre il limite dei
recenti. Non fare un fan-out di payload completi per la lista; caricare dettagli
al bisogno. Verificare campi per destinazione, parent/child e correlazione retry.
Condividere terminali/progress semantics nei consumer frontend.
Verificare dedupe di submit per ciascun avvio: un retry ambiguo della stessa
richiesta deve recuperare il job ammesso; un rilancio voluto può crearne uno nuovo.

Acceptance: job ritrovabile senza stato della pagina; eventi riconciliati allo
snapshot; `interrupted` termina il follower; cancel queued libera capacità alla
normale boundary; coda piena e capture restituiscono esito veritiero.
Prova: store/router/manager con race di submit/cancel/completion, storico >500,
riavvio, stream reconnect e fallback; nessuna regressione privacy/auth.

### BG-2 — sorgenti importate e dipendenze

Estendere l'owner recording per importazione atomica e finalizzazione, dopo
audit di create/chunks/finalize e `active_recording()`: una sorgente importata
non deve occupare capture né falsarne lo stato. Definire limiti/formati e
retention delle sorgenti secondo il lifecycle esistente, senza storage parallelo.
Creare transcription job solo dopo import completato; persistere opzioni e
identità. Per analisi da audio, estendere l'orchestrazione esistente per avviare
l'analisi dopo transcript pronto, anche con pagina smontata. Non accodare un
parent pesante che attende un child sullo stesso scheduler a concorrenza 1.

Acceptance: import→ASR e import→ASR→analisi continuano tra route; errori/cancel
non lasciano upload orfani; testo/audio validi restano consultabili; dedupe e
cloud opt-in invariati. Prova: filesystem/DB isolati, partial upload, crash,
cancel di ogni fase, fallimento analisi con transcript preservato e capture.

### BG-3 — osservazione indipendente dalle pagine

Owner UI nella shell per trasferimenti e proiezione dei job. Bootstrap/reconnect
da lista attivi e snapshot; SSE riusa `followJobEvents`, con discovery bounded
per avvii da altre superfici. Un follower per job nella shell, consumer tramite
subscription; evitare doppio follow con Meeting e duplicati parent/child.
Cleanup di listener/timer/fetch su unmount/logout/shutdown e reconnect con backoff.
Le pagine avviano e mostrano lo stesso job recuperato da route/sorgente/run ID;
nessun setState o redirect tardivo della pagina smontata. Eliminare attese locali
infinite e polling ad alta frequenza dove SSE copre il flusso.

Acceptance: cambio route durante upload, queued e running; ritorno prima/dopo
fine; reload dopo submit; nessun doppio job, follower, toast o leak. Prova:
test runtime UI con eventi/reconnect controllati e richieste/API osservate.

### BG-4 — Attività e recupero esplicito

Implementare disclosure globale e azioni descritte sopra, riusando componenti.
Apri risultato risolve ID canonici per transcript, analysis run e Meeting;
sorgente eliminata o risultato indisponibile mostrano recupero esplicito.
Retry passa dagli owner server, preserva opzioni e protegge doppio click;
nessun retry automatico su reconnect. Confermare slot/count e messaggi per
queued, running, waiting/retrying, cancelling e tutti i terminali.

Acceptance: cancel, risultato e storico accessibili anche da tastiera e in layout compatto.
Prova: browser journey per happy path, error/offline/cancel/retry e parent/child.

### BG-5 — verifica e integrazione

Test mirati durante iterazione; selector per rischi/gate concreti a ogni cambio
di confine. Integrare journey background nelle fixture/browser runner esistenti
e `.engineering/e2e.json`; FULL_MEDIA per la nuova sequenza UI in integrazione.
Integrare una prova API/persistenza assemblata: fixture browser da sole non
provano che il backend esegua dopo disconnessione. Check package quando selezionato.

Acceptance finale: due elaborazioni ordinate dalla coda; cambio schermata
senza perdita; risultato apribile; cancel pending/running; riavvio→interrupted
e rilancio; disconnessione SSE recuperata; import→analisi; capture prioritario;
assenza di residui e dati sensibili nei log. Nessuna promessa MLX/TCC da fake.

## Verifiche e documentazione

- Baseline mirata: suite job store/arbiter, analysis/transcription e preparation;
  aggiungere test runtime di navigazione, non soltanto assert sul testo sorgente.
- Frontend: `cd frontend && pnpm run lint && pnpm exec tsc --noEmit`.
- Docs: `python3 scripts/verify_docs.py` e context route con questo workstream.
- INTEGRATION: leggere `skills/preflight-change/SKILL.md`, selector su head/base
  aggiornati, diff completo, gate richiesti e journey affetti FULL_MEDIA. Niente
  build/package o upload FULL_MEDIA in Actions; prove package locali.
- RELEASE: FULL e obblighi target-Mac applicabili; WKWebView, capture fisico/TCC
  e memoria/Metal rappresentativi restano `DEFERRED_TO_RELEASE` in integrazione.
- Trasferire comportamento in `docs/features.md`, ownership in architecture,
  UX in `design/ux-contract.json`, uso pubblico in README se cambiato, gap e
  obblighi in `docs/current-state.md`/runbook release. Identità prodotto N/A.
  Applicare `finalize-workstream` e cancellare il piano soltanto a lavoro concluso.

## Checkpoint unico di ripresa

- Data: 2026-10-14. Pianificazione soltanto; nessuna implementazione eseguita.
- Branch `dev`; HEAD/base locale osservata
  `15ec412ce10cb5e49438f6e09271f2883ea65973`; base PR/remota non verificata.
  Tree HEAD `d9f16ca4f16a9df4821aac5d02a3b50a182c5aa3`; tree locale già dirty.
- Modifiche preesistenti: docs/design/policy, MeetingDetailPage, browser
  preparation, verifier docs, menubar, test e static generati. Non attribuirle
  al workstream né sovrascriverle; rivalutare overlap prima delle modifiche.
- Fatti confermati: owner e percorsi elencati nella base, verificati nel codice.
  Esclusa l'ipotesi “manca uno scheduler”: arbiter cablato in `server.py` per
  entrambi i manager. Nessun test di esecuzione background svolto in questa chat.
- Da verificare: correlazione retry, import senza capture, run senza recording.
- Prossima azione: aggiornare head/tree/base e overlap; riprodurre avvio→route→
  ritorno con runtime isolato, poi definire il contratto BG-1 con test failing.
