# GCS audio retention — safe progression (2026-11-04)

Status: **PHASE 1 IMPLEMENTED ON FEATURE BRANCH — NOT INTEGRATED IN dev**
Owner: `RecordingStore` per-meeting metadata and audio lifecycle;
`SettingsService` owns global preferences, `TranscriptionStore` and
`CatalogStore` remain authoritative for local text/catalog;
future GCS adapter must be integrated only behind those owners.

## User outcome

A privacy-first ClosedRoom user can continue recording and transcribing
entirely on the Mac, optionally keep encrypted recordings on a user-selected
private GCS bucket, and eventually reclaim disk space without risking their
only recoverable copy. **Transcripts, notes, speaker assignments, search and
catalog must remain readable offline**. Optional remote storage is not remote
inference and must not activate without the user's explicit consent.

## Product decision and four independent axes

PRODUCT_FEATURE / ITERATION / STRONG (data retention, loss prevention,
Keychain, persistence, asynchronous transfer) / AGENT_LOCAL for tests;
REAL_ENVIRONMENT for authorization and actual isolated restore.

The backup verified on the separate one-shot migration PR #170 was a
**cold snapshot**: 26,071 files including a SQLite catalog, ~9.67 GB,
successfully encrypted and uploaded to GCS on November 3, 2026. It is not
an integrated per-meeting storage policy. It did not verify independent
restore from lost-Mac conditions; it did not activate local eviction.

## Fail-safe acceptance contract

1. **Local first:** recording finalization and ASR/diarization complete on
   local files. New meetings default to `local_only`; existing meetings
   remain local and get no inferred remote evidence. A preference is not
   proof of a cloud transfer.
2. **Per-track proof:** for every finalized audio track store a byte size
   and SHA-256 matching the local file; remote proof must also identify
   an immutable GCS generation, authenticated encryption, and hashes of
   plaintext/ciphertext. A single mixed-track object never qualifies
   a multi-track meeting.
3. **Real recovery:** record the verified download + authenticated decrypt,
   independently preserved recovery materials, and an isolated restore of
   original audio and the relationship to the local transcript/catalog.
   Without a real, reproducible restore the media cannot be evicted.
4. **Temporary redundancy:** use 14 days by default, configurable to 7 or
   30 days. The timer starts **after proven restore**, not after recording
   end or upload success. Retention is frozen per meeting at creation;
   changing preferences affects future meetings only.
5. **Never infer idle:** audio is not eligible while capture, ASR,
   diarization, playback, visual processing, hydration or a reader lease
   can still require it. Unknown activity == unsafe.
6. **Eviction separate from deletion:** do not reuse
   `delete_archived_meeting` or `discard` for audio cache eviction.
   Never delete transcripts, note exports, analysis, catalog or encryption
   evidence during eviction. Remote delete and local cache cleanup must
   have distinct user affordances.
7. **Crash recovery:** stage files under a private, process-owned path,
   re-check all canonical data and remote object conditions, commit a
   recoverable local state transition and only then remove staged audio.
   On interruption before the final commit restore local files, not assume
   success. Deleting the last unverified local audio is forbidden.
8. **UI truth:** display separately `Solo Mac`, `Backup in corso`,
   `Copia verificata`, `Solo GCS`, `Offline`, `Ripristino fallito`.
   Never label an uploaded object as recovered or imply GCS cloud mode is
   working when only a one-shot snapshot exists.

## Current stage (this PR)

- `recording_storage_policy.assess_audio_cleanup` is a pure **candidate**
  evaluator only. It checks strict per-track identity, independent recovery
  material, immutable remote generation/digests, aware timestamps,
  configured delay, completion, local transcript and active work.
- `RecordingStore` persists the preference for newly created meetings
  and exposes a sanitized, **read-only** `audio_storage` status. The
  `_audio_cloud_proof` internal field is deliberately redacted from public
  metadata. Legacy recordings default to `local_only`.
- Settings allow 7/14/30 day preference and reject
  `audio_auto_cleanup_enabled=true`. UI clearly says that the
  retention selection is *future-only* and that no automatic upload or
  deletion runs. There is **no active eviction mechanism, scheduler or
  cloud inference**.
- No actual per-meeting GCS adapter was added to the `dev` baseline
  because the one-shot archive code remains on PR #170 and cannot be
  treated as the production RecordingStore lifecycle. Integration must
  reconcile those branches/contracts without creating a parallel owner.

## Next gates (not implemented in this phase)

**Gate R1 — recovery evidence (REAL_ENVIRONMENT):** export receipt,
envelope and recovery code independently of original Mac, restore complete
cold snapshot into isolated target, validate catalog and media hash, confirm
offline transcript linkages. No old media removed.

**Gate R2 — per-meeting opt-in sync (STRONG):** connect OAuth/key identity
in an approved user session; append-only local outbox/jobs with bounded
retry, no implicit provider fallback, immutable generation and SHA-256
validation; no eviction. Test crash, offline, IAM/token expiry, parallel
capture, missing transcript and reused track IDs.

**Gate R3 — hydration (STRONG):** canonical audio accessor acquires a
lease, downloads only requested asset, authenticates before playback/ASR,
keeps transcript/catalog offline, provides progress and cache bounds.

**Gate R4 — safe eviction (STRONG + REAL_ENVIRONMENT):** read-only
eligibility plus live re-verification under owner lock, recovery receipt,
two-phase staging and crash replay, exact file-content rehash; show user
reclaimed bytes, separate delete-everywhere action, full UI/VoiceOver E2E.
Default cleanup OFF until validated; cloud failure leaves originals intact.

Release requires selector-selected FULL validation and representative target
Mac proof. Current phase must not be presented as full hybrid storage.
