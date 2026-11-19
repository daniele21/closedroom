# Secure multi-device transcript sync — Google Drive pilot

Status: ACTIVE / isolated security-format experiment on `feature/google-drive-secure-sync-foundation`
Target: `dev`. Product: PRODUCT_FEATURE; delivery: ITERATION; validation: FULL (repository selector: unknown executable `experiments/` path; risk floor STRONG for crypto/data lifecycle); execution: AGENT_LOCAL prototype, REMOTE_AUTOMATED integration, REAL_ENVIRONMENT for Keychain/OAuth and independent second Mac. No release claim.

## User and outcome

A ClosedRoom user records, transcribes, diarizes and analyzes meetings on-device, and can privately read the resulting transcript/notes on an authorized second device **while the original Mac is powered off**. Primary experience is read-only until conflicts and trust-recovery are proven. No assumption of cloud inference, cloud account requirement, browser execution or cloud fallback.

Non-goals of first pilot: remotely transcribing, syncing audio/screenshots/models, collaborative sharing, bidirectional editing, server-hosted plaintext search, silent automatic upload, cleanup or migration of legacy material.

### Risks and decisions

- **VALUE:** verify that a second Mac can read a finalized transcript offline; no mobile build is needed to validate the job.
- **USABILITY:** Google connection must not be confused with cryptographic authorization; device enrollment requires mutual verification and explicit approval. A comprehensible independent recovery flow is essential.
- **FEASIBILITY:** canonical data are split across `TranscriptionStore`, `RecordingStore` and `CatalogStore`; do not sync their raw files, WAL DB or directories, and do not create alternate persistence owners.
- **VIABILITY:** user-owned Google Drive storage avoids a ClosedRoom-hosted content server, but OAuth setup/review, API quotas and support still have costs.
- **PRIVACY/SECURITY:** default is local-only, user opts into Drive separately. The app encrypts *before* any network call. Google can observe account, traffic, object counts/sizes and timing. Google OAuth is not vault authorization. No analytics, meeting content or secrets in logs/CI.
- **DATA INTEGRITY:** upload success is not verified recovery; snapshot must be decryptable and restorable on an independent device before claiming recoverability. Do not evict audio/transcripts. A provider can delete/replay old authenticated data unless trusted state/backup prevents it.

## Canonical ownership and system contract

- `TranscriptionStore` owns transcription identity, content, correction and analysis; `RecordingStore` owns notes, screenshots and recording/audio lifecycle; `CatalogStore` owns local indexes.
- Future sync **reads a versioned allowlisted projection** from these owners. Do not mutate local canonical source data on import; remote read-only cache needs a scoped persistence owner and lifecycle design before implementation.
- Encrypt whole snapshot on originating Mac. In the proof format the public header is only schema version, opaque random object id, random HKDF salt/nonce, ciphertext. IDs, titles, speaker labels, notes and transcript are inside authenticated encryption.
- For production: a vault root key protected by Keychain (and a separately held user recovery secret), device-specific asymmetric identities, explicit pairing, key epoch/rotation, authenticated signed append-only manifest/head, replay/rollback detection with pinned trusted checkpoints, signed revocation and tested failure recovery.
- Storage: Drive API v3 `appDataFolder`, OAuth `drive.appdata` least privilege, on-device token storage, `changes.list` with `spaces=appDataFolder` only after an initial exhaustive inventory; bounded retry/rate limiting and offline queue. No sharing in appDataFolder: new device authenticates to same Google account but gets vault access **only** via authenticated pairing/recovery.
- Safe deletion in every layer: remote cache deletion != meeting deletion != audio eviction. Never delete the last verified copy. No secrets/API tokens in public manifests or exported docs.

## UX — first enrollment and additional device

1. Settings → Privacy & storage → Sync devices. Default OFF; consent explains what leaves the Mac (only ciphertext; no audio or screenshots). Connect Google account through OS/browser OAuth; show actual effective state, not saved preference as success.
2. Mac generates vault secret and device identity **locally**, stores secrets in Keychain; user receives independent recovery code and must confirm they saved it before enabling upload. No server stores plaintext keys. New transcripts remain local until explicit opt-in.
3. Second Mac: choose "Link existing vault" then sign in to same Google account (this proves storage access only). New device creates ephemeral key pair and a short-lived QR challenge.
4. Existing Mac: scan QR or enter a safe short linking code, compare a human-readable authentication phrase/6-digit code on *both* screens, explicitly approve the new device with name and permission "Read only". Expiring one-time challenge, mutual authentication, replay protection and no unverified key substitution.
5. Existing Mac encrypts a device-specific vault-key grant bound to new device public key and confirmed challenge; new Mac verifies owner signature and decrypts the grant locally. **Never put the root key, grants to unintended recipients or recovery secret in a QR or Drive plaintext.** A compromised Drive account alone must not authorize a new device.
6. New Mac downloads encrypted manifest/objects, checks authenticated revisions and decrypts into private read-only offline cache. UI: Downloading / Available offline / Locked / Key needed / Conflict / Not recoverable, with retry. No fake success when no verified decrypt.
7. Devices list: show name, enrollment time, last authenticated sync and read-only privilege; explicit revoke. Revocation rotates future content keys and stops new grants. Cached plaintext already accessed on a stolen device is **not remotely erasable with certainty**.
8. Recovery if no authorized device remains: supply independent recovery secret *plus* ownership of Drive data, reconstruct identity/keys on clean Mac, rotate device grants and invalidate old devices. If every key/recovery secret is lost, data are unrecoverable by design. Test a genuine independent restore before calling it backup.

## Execution graph and evidence

| ID | Outcome | Status | Required evidence |
| --- | --- | --- | --- |
| SYNC-0 | Threat model, consent boundaries, pairing/recovery flow; no implicit remote fallback | DONE design | Review with canonical storage owners |
| SYNC-1 | Prove a portable AES-256-GCM authenticated transcript-only object with no raw export of paths/provider credentials | DONE experimental | Synthetic round-trip, wrong key, tamper, invalid schema/size, plaintext absence (6 local tests) |
| SYNC-2 | Production vault identity/Keychain and independent recovery materials, crypto dependency+locked build, signed manifest/head/anti-rollback | ACTIVE (offline proof only) | Clean/compromised-device, key loss, replay, rotation, crash and security review |
| SYNC-3 | Explicit OAuth `drive.appdata` and Drive read/write adapter, offline outbox, receipts and bounded incremental list | BLOCKED on SYNC-2 | Fake transport faults + real isolated Google test account, no sensitive user meetings |
| SYNC-4 | Read-only canonical projection and isolated second-Mac cache; pairing/permissions/revoke UX | BLOCKED on SYNC-2/3 | Second physical Mac with source powered off, cache offline, mutual QR verification, revoke |
| SYNC-5 | Integrated Settings/Meeting status, complete privacy copy, accessible UX and correct cleanup | BLOCKED on SYNC-4 | Automated E2E FULL_MEDIA; WKWebView/Keychain target Mac; security/recovery audit |
| SYNC-6 | Consider mobile companion/read-write editing **only after** the above is verified | BLOCKED | Product evidence and conflict-management design |

### Offline proof extension (2026-11-19)

- Isolated `vault_manifest.py`: Ed25519 owner-signed chain, opaque ciphertext references, contiguous revisions/epochs, pinned owner, fork and replay detection against a trusted checkpoint. A fresh device cannot prove remote freshness from Drive alone.
- Isolated `vault_keychain.py`: fail-closed macOS Keychain-only prototype storing independent AES vault and **software** Ed25519 signing secrets, authenticated owner pin and checkpoint. Not hardware Secure Enclave. Synthetic unit tests cover restart, tampering, bad signer, key replacement/corruption, failures and replay.
- Missing: genuine recovery materials, cross-process CAS, authenticated pairing, revocation/rotation, second-device trust anchor and verified backup. No OAuth, sync, migration, upload, local eviction, app integration or production cryptographic dependencies yet.

### Mac result and failure classification — 2026-11-19

- Source SHA `c14c8e16` ran on the central Mac runner ([run 44498140756](https://github.com/daniele21/local-runner-infra/actions/runs/44498140756)). **977 repository tests PASS; 17 isolated crypto/manifest/fake-Keychain tests PASS.**
- **Real Keychain smoke FAIL** before storing the first synthetic secret. `keyring.backends.macOS.api.Error (-25308)` means `errSecInteractionNotAllowed`: current runner security context cannot permit the operation. Classify as an **environment/session authority** blocker pending an interactive user-login Keychain proof; do not relabel it a cryptographic regression or success.
- Source commit `b4cfd627` fixes the independent repository-doc budget failure (3,125 > 3,000 estimated tokens); hosted governance checks now PASS. It has **not** passed exact-HEAD Mac validation; the earlier runner failure remains blocking for the Keychain gate.
- **Repeat after user unlocked login Keychain**: source `159afbfc74e0abc40ae6c004248451a451075ce2`, central [run 44510352786](https://github.com/daniele21/local-runner-infra/actions/runs/44510352786) on `local-mac-mini-3` (`MacminiiDaniele`). Main suite 977 PASS, crypto 17 PASS; real Keychain write still FAIL `errSecInteractionNotAllowed (-25308)`; `local-ci/mac=failure`. Earlier run used `local-mac-mini-4` on the same machine. This falsifies the hypothesis that unlocking login Keychain alone would resolve runner access. Next action requires a separate GUI-user/signed-app or explicitly authorized launch-session proof, not retrying the same background runner unchanged. Real-environment gate remains blocked.
- Next discriminating action: verify Keychain operations in a trusted logged-in GUI-user/signed-app execution context, without exposing an unlock password to CI or silently substituting a file-based secret store. Preserve failure on inaccessible Keychain. Run again against exact candidate when correct environment exists.

### Current checkpoint

- Source branch based on `dev@de0d1809`; GCS remains configuration-only. No active sync service.
- Head before real Mac request: `c14c8e16`; PR #225 draft. `.github/ci/local-test.sh` now calls the isolated crypto suite and synthetic real-Keychain smoke via a transient Python dependency environment. The central Mac run for that SHA is tracked under `local-ci/mac`.
- At this stage, Mac source checks, packaged-app Keychain behavior, OAuth and second-device recovery must not be reported PASS without separate evidence. The next action is to evaluate exact Mac test logs, fix diagnosed failures without weakening tests, then rerun on new exact HEAD.
