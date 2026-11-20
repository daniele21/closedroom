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
| SYNC-2 | Production vault identity/Keychain, independent recovery and signed manifest/head | ACTIVE (offline proof PASS only) | Durable anti-replay, authenticated pairing UX, key rotation/revocation, real second Mac recovery, review |
| SYNC-3 | Explicit OAuth `drive.appdata` and Drive read/write adapter, offline outbox, receipts and bounded incremental list | BLOCKED on SYNC-2 | Fake transport faults + real isolated Google test account, no sensitive user meetings |
| SYNC-4 | Read-only canonical projection and isolated second-Mac cache; pairing/permissions/revoke UX | BLOCKED on SYNC-2/3 | Second physical Mac with source powered off, cache offline, mutual QR verification, revoke |
| SYNC-5 | Integrated Settings/Meeting status, complete privacy copy, accessible UX and correct cleanup | BLOCKED on SYNC-4 | Automated E2E FULL_MEDIA; WKWebView/Keychain target Mac; security/recovery audit |
| SYNC-6 | Consider mobile companion/read-write editing **only after** the above is verified | BLOCKED | Product evidence and conflict-management design |

### Offline proof extension (2026-11-19)

- Isolated `vault_manifest.py`: Ed25519 owner-signed chain, opaque ciphertext references, contiguous revisions/epochs, pinned owner, fork and replay detection against a trusted checkpoint. A fresh device cannot prove remote freshness from Drive alone.
- Isolated `vault_keychain.py`: fail-closed macOS Keychain-only prototype storing independent AES vault and **software** Ed25519 signing secrets, authenticated owner pin and checkpoint. Not hardware Secure Enclave. Synthetic unit tests cover restart, tampering, bad signer, key replacement/corruption, failures and replay.
- Missing: genuine recovery materials, cross-process CAS, authenticated pairing, revocation/rotation, second-device trust anchor and verified backup. No OAuth, sync, migration, upload, local eviction, app integration or production cryptographic dependencies yet.

### Validation — 2026-11-19/20

- Exact source `b8dfea6474eee488b2a99e754941aab91fb17648`: [self-hosted Mac run 44552089974](https://github.com/daniele21/local-runner-infra/actions/runs/44552089974) `local-ci/mac=success`; **987 Python tests PASS; 17 crypto tests PASS; browser FULL_MEDIA PASS**. `KEYCHAIN_REAL_ENVIRONMENT=NOT_RUN` is intentional in non-interactive CI.
- Earlier attempts to access Keychain from a background runner failed `errSecInteractionNotAllowed (-25308)`, even with login Keychain unlocked. The same local synthetic `keyring` smoke passed interactively in Terminal, but without a supplied exact Git SHA; separate from bundle proof.
- **Packaged ad-hoc GUI Keychain gate PASS (user-supplied terminal evidence, test run 2026-11-19):** source `b8dfea6474eee488b2a99e754941aab91fb17648`, finalized artifact manifest `dist/artifacts/macos-arm64-local-real-environment-app/local-20261119T161450Z-f0de04/build-manifest.json`. `scripts/probe_packaged_keychain.py --build` reported `bundle_id=com.closedroom.app`, `signing=ad-hoc`, `status=pass`, `independent_child=true`, `cleanup=true`, `installed_app_modified=false`, scope `packaged-GUI-Terminal-Keychain-only`. The script validates finalized artifact provenance/signature and executes the Security.framework probe from the frozen app binary. Evidence is supplied by the operator, not independently downloaded from the Mac.
- **Gate qualified only for ad-hoc packaged diagnostic.** No Developer ID signing/notarization or installed-app workflow, no production vault key lifecycle, authenticated pairing, recovery, revocation, Google OAuth, Drive integration, upload or remote restoration has been proven.

### Current checkpoint

- Source branch from `dev`; draft PR #225. The Keychain experiment and packaged-app synthetic security smoke are **implemented and qualified at the scope above**; product sync is still OFF. No GCS/Drive transmission or real user meeting data transferred.
- SYNC-2 offline proof at `ca4549f4`: [Mac run 44709517507](https://github.com/daniele21/local-runner-infra/actions/runs/44709517507) **987 app tests PASS, 31 isolated security tests PASS, browser FULL_MEDIA PASS**, `local-ci/mac=success`. Random 256-bit recovery code + AES-GCM capsule of owner key/vault key/trusted checkpoint; 5-minute X25519 read-only grant signed by Ed25519 owner, independently pinned owner key and manual SAS UX required. All synthetic, no production sync or real two-Mac pairing.
- SYNC-2 next offline candidate: `owner_ledger.py` uses SQLite FULL + `BEGIN IMMEDIATE` to serialize a signed public device registry, persisted enrollment nonces, and separate Keychain high-water digest. Failure between SQLite commit and Keychain update **freezes** vault; no auto reconciliation. Signed manifest key_epoch advances on revocation, fresh **independent** epoch secret stored in Keychain before commit; survivors require new grant, revoked device retains old read access. New synthetic regression suite `test_owner_ledger.py`; exact Mac run evidence pending.
- Still SYNC-2 ACTIVE: recovery from frozen split-commit (no silent fix), out-of-band checkpoint freshness, owner public-key bootstrap, recovery-code update after rotation, persistent recipient-side trust state, fully authenticated two-screen GUI, real second Mac test, secure SDK/model lifecycle integration. No Drive/OAuth, production Keychain integration, user data sync or release claims.
