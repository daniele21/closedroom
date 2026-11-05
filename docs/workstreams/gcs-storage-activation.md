# GCS storage — from selection to safe per-meeting lifecycle

Status: ACTIVE (configuration selection implemented on feature branch; cloud runtime blocked)
Base: `dev` at implementation start, NOT the divergent experimental GCS migration branch
Axes: PRODUCT_FEATURE / ITERATION -> INTEGRATION / STRONG / AGENT_LOCAL + REMOTE_AUTOMATED + REAL_ENVIRONMENT

## User job and boundaries

A user wants to choose **Solo Mac** or **Google Cloud Storage** for future meeting audio, keep transcripts and AI processing on-device, and reduce local disk usage only when the audio is independently recoverable. This is a genuine local/cloud trust-boundary decision: the default stays on-device and there is no implicit remote processing or upload.

The October/November GCS experiment in `feature/gcs-storage-discovery-project-tests` demonstrated a **manual, one-shot encrypted cold backup** and a 26,071-file isolated restore (198 recording rows, 86 transcription rows) on the original Mac. It is not wired to app recording, playback, Settings or per-meeting metadata. The experimental branch diverged substantially from `dev`; port reviewed owners rather than merging its entire history. The original inventory included 203/91 rows: reconcile snapshot coverage before treating it as a complete live-state backup.

## Shipped in this preparation slice (feature branch only until integration)

- `Settings -> Archiviazione`: accessible **Solo Mac / GCS** preference, optional project/bucket/region fields, explicit status that GCS is **not active**, retention unchanged, no misleading connection-test action.
- Canonical `SettingsService` validates and persists **identifiers only** (`storage_preference`, `gcs_project_id`, `gcs_bucket_name`, `gcs_region`), not OAuth tokens or secrets.
- Public `storage_effective_mode=local`, `storage_capability=preparation_only` and `gcs_configuration_complete` are **server-derived**, never inferred from saved user preference.
- No network requests, backup job, automatic cleanup, remote deletion, or per-meeting cloud status is introduced. Existing recordings/transcripts/catalog remain on the Mac.

This is an intentionally incomplete **configuration capability**. It is NOT a usable GCS storage mode and must not be described as such in release notes.

## Work graph, ordered by prerequisites

| ID | Owner / deliverable | Requires | Proof |
| --- | --- | --- | --- |
| CS-SEL | Settings + UI preference, truthful capability and tests | Existing settings owner | Settings PATCH unit + frontend lint/typecheck/interaction states |
| CS-GCS | Port/normalize narrowly scoped OAuth Keychain, authenticated AES-GCM transport and recovery owners from experimental branch | Design of new per-meeting object schema, IAM | Synthetic upload/download, tamper and revoked-auth tests |
| CS-MET | RecordingStore owns frozen effective destination, per-meeting track refs (generation, digests, key version), nonsecret progress/error | CS-GCS | durable state/retry/restart/idempotence tests |
| CS-UP | Post-finalize explicit opt-in upload, checksum/decrypt verification, local original retained | CS-MET | network-failure, cancellation, permissions, duplicate and crash tests |
| CS-RC | Consistent transcript/catalog recovery snapshot and independent recovery material | CS-UP | fully isolated recovery on **second authenticated Mac** + row reconciliation |
| CS-HYD | Canonical leased hydration accessor for playback, ASR, diarization, multi-track and offline UX | CS-RC | media E2E and lease cleanup; offline readable transcripts |
| CS-EVICT | Independent recovery and local age/lease checks, crash-safe and explicit eviction | CS-HYD | model + real Mac proofs; zero loss after interrupted operations |
| CS-UX | Meeting UI remote status, retry, progress and recovery; no duplicate page or store | CS-MET..HYD | browser FULL_MEDIA + WKWebView/TCC/VoiceOver release evidence |

## Acceptance and protections

- Opting in does not retroactively migrate historic meetings. Saved preference ≠ effective destination; only a validated per-meeting recording transition can become GCS.
- Capture/ASR/diarization/inference are local. No implicit cloud fallback, no credentials/meeting metadata in GitHub Actions or ordinary logs.
- Missing OAuth, invalid bucket, offline state, corrupt object, lost recovery key, active playback/capture/job, or incomplete transcript cannot remove local audio.
- `audio_auto_cleanup_enabled` stays false until real independent recovery + hydration + transactional eviction are proven.
- RecordingStore remains the canonical owner of audio identity and metadata; CatalogStore/TranscriptionStore stay on-device.
- On this slice: validate SettingsService and frontend contract, check APIs, run frontend typecheck and UX browser journey. Integration requires repository selector STRONG/affected FULL_MEDIA; macOS/Keychain and second-Mac recovery are REAL_ENVIRONMENT gates.

## Current next action

Validate exact-head automated tests and frontend build on the feature branch. Then raise a PR to `dev` for the **preparation-only** selection, without claiming remote storage is live. Begin CS-GCS with a separate tightly scoped implementation branch after consolidating the experimental GCS source.
