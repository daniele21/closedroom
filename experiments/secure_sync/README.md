# Secure sync crypto proof — NOT production sync

Isolated, offline-only format experiment. No Google OAuth, network traffic, upload, background job, production Keychain integration, device pairing, cloud fallback, app integration or cleanup. Requires `cryptography` for all crypto tests and optional `keyring` for a genuine macOS Keychain probe (neither dependency is added to the product lockfile).

Run with the dependency available:

```sh
uv run --no-project --with cryptography --with keyring -- python -m unittest discover -s experiments/secure_sync -p 'test_*.py' -v
```

Additional isolated components:
- `vault_manifest.py`: Ed25519-signed manifest chain, opaque ciphertext digests and checkpoint verification. Authenticated latest head is an **independent trust requirement**, not provided by Google Drive alone.
- `vault_keychain.py`: explicit macOS Keychain-only prototype for vault and software Ed25519 signing secrets, an out-of-band owner key pin and a trusted local checkpoint. Fake Keychain tests do not demonstrate that a packaged Mac app can access the Keychain. The test injection is **not** a production option. No automatic initialization.
- `test_vault_foundation.py`: key corruption, wrong signer, replay, fork, restart and no-fallback cases.

No production cross-process compare-and-swap, durable pairing grants, independently qualified recovery, or provider-freshness guarantee exists. A clean device **must not accept Drive's purported current head as proof of freshness**. Do not activate upload or deletion.

The 32-byte secret is **test-only** in this experiment. Do not persist it in plaintext, pass it to telemetry, store it in Drive, or treat the local test fixture as a recovery-key protocol.

The format intentionally authenticates header fields and ciphertext using HKDF-SHA256 + AES-256-GCM. It does **not** establish remote freshness, authorization of devices, revocation, concurrency control, recovery, verified upload/restore or a production export/import path. In particular a malicious/compromised storage provider may delete objects or replay an older *valid* ciphertext; those protections need a trusted authenticated manifest/head checkpoint and independent backup.

Next step: review and adapt this format in the existing canonical TranscriptionStore/RecordingStore projection owners; add correctly locked crypto dependency, consent and Keychain management; add a read-only separate device cache and a Google Drive appDataFolder adapter behind explicit opt-in.

## Source-owned real-Mac gate

On the shared Mac validation lane, `.github/ci/local-test.sh` explicitly runs the `test_*.py` files with transient isolated Python dependencies. A genuine user GUI Keychain smoke is deliberately NOT run as a background CI step (the headless runner produced `errSecInteractionNotAllowed -25308`). It remains a separate real-environment requirement. The earlier exploratory direct invocation was:

```sh
uv run --no-project --python 3.12 --with 'cryptography>=46,<47' --with 'keyring>=25,<26' -- python experiments/secure_sync/macos_keychain_probe.py
```

The probe uses **synthetic temporary records only**, a second process and cleanup verification. Never use actual user credentials/vaults. Mac runner PASS is not installed-app Keychain/TCC proof.

## Native packaged-app Keychain proof (GUI user opt-in)

The `vault_keychain.py` experimental `keyring` adapter is NOT included in the
product. To prove the **actual frozen app executable's own Security.framework
context**, use the separate native Keychain diagnostic in
`src/local_asr_server/macos_keychain_native.py`.

From a clean checkout on an Apple Silicon Mac, using an interactive logged-in
GUI Terminal:

```bash
python3 scripts/probe_packaged_keychain.py --build
```

This creates an **ad-hoc signed, exact-HEAD** .app under `dist/`; it does not
install/replace `/Applications/ClosedRoom.app`. It checks source/manifest,
bundle ID and code signature and calls the packaged
`Contents/MacOS/ClosedRoom secure-sync-keychain-smoke`. That executable uses
a separate synthetic Keychain service: 32 random key bytes, readback,
same-signed-executable second-process HMAC challenge, cleanup and absence
check. The only output is bounded PASS/failure status; no secrets, meeting
data, server, Drive, OAuth or network.

Without `--build`, reuses ONLY an exact-HEAD finalized app; `--app`
accepts an explicit candidate only when it matches the checked-out SHA.
Background GitHub Mac Keychain access still FAIL `-25308`; this is a
different execution context and is not bypassed. An ad-hoc signature
is NOT Apple Developer ID/notarization or installed-app entitlement evidence.

## SYNC-2 offline recovery and pairing proof (not production)

- `recovery_capsule.py` encrypts the 256-bit vault key, **software**
  Ed25519 owner private identity and the trusted manifest checkpoint with a
  separate randomly generated, 256-bit `CR1-` recovery code. The code is
  never put in the capsule, local settings, Drive or CI logs. Store the code
  **independently**: possession of only a capsule or only a code is insufficient.
  Uses HKDF-SHA256 on a high-entropy code + random salt, AES-256-GCM and
  authenticated format/header. Arbitrary user passwords are NOT accepted.
- `device_pairing.py` creates an expiring (5-minute) X25519 device request.
  Owner approval must be explicit and preceded by comparing the exact
  eight-digit request fingerprint shown by **both physical Macs** through a
  separate user-trusted channel. Owner signs a **read-only** X25519/HKDF/
  AES-GCM vault-key grant tied to the request, device and checkpoint. Receiver
  requires an **independently authenticated owner public key**. The recipient
  does not receive the owner signing private key.
- `test_offline_trust.py` checks wrong recovery codes, stale/conflicting
  checkpoints, mismatched owner, tamper, timeout, refusal, substitutions,
  repeat grant use in one pending session and independently recovered owner
  keys issuing a read-only grant. All objects remain in memory; no transport.

**Security boundary:** this is protocol experimentation only. Manual SAS
verification cannot be inferred from passing a string to the API; a real
two-screen UX and authenticated owner-public bootstrap must be designed and
tested. In-memory `PendingDevice.consumed` is NOT durable anti-replay or
device authorization. Recovering the owner signing secret restores full owner
authority; recovery material needs stronger UX, locked Keychain persistence,
crash-safe transaction handling, loss/restore and key compromise reviews.
A Drive provider could replay a previously valid encrypted recovery capsule:
without an independent newer checkpoint a fresh Mac cannot detect staleness.
Revocation/rotation does not yet exist. No second real Mac has been tested.

## SYNC-2 durable owner ledger and future-key revocation (offline experiment)

`owner_ledger.py` extends the existing experimental `vault_keychain.py`
with a **public, Ed25519-signed device/epoch registry** in a mode-0600 SQLite
file (FULL-synchronous `BEGIN IMMEDIATE` serialized writes). A separate
high-water digest/revision lives in the macOS Keychain, NOT in that SQLite DB.
Every read/operation verifies the owner's independently pinned public key,
signed registry document, schema, and exact Keychain high-water anchor.

- A changed/rolled-back/vanished DB or Keychain anchor **fails closed**.
  SQLite and Keychain cannot commit atomically; a crash between DB commit
  and anchor update deliberately freezes reads. No silent repair from either
  untrusted side, no automatic data loss or remote fallback.
- Owner enrollment grants are issued only after the existing human-approval
  protocol, consume a request ID **durably** and record device/epoch status.
  Writers must share the canonical database path to get SQLite serialization.
  This does NOT replace trusted cross-device pairing UI or provider trust.
- Signed manifest epoch must advance exactly once for revocation. The owner
  creates a fresh random, independent 256-bit epoch key *in Keychain before*
  advancing the ledger; the target becomes `revoked` and surviving devices
  `needs_repair`. They require fresh authenticated grants. A revoked device
  may retain old ciphertext/plaintext; there is no remote erase.
- Keychain write failure before SQL commit leaves old epoch current (possible
  orphan secret). Each new SQLite update is now preceded by an **exact forward
  intent in Keychain** binding the trusted old anchor to the new signed record.
  Every unresolved intent freezes normal reads, including ambiguous attempts
  where SQLite still equals the old anchor (possible attacker rollback).
  `recover_prepared_transition(..., expected_new_digest=..., explicit_confirmation=True)`
  is **manual and forward-only**: it authenticates the owner signer, pinned
  owner and SQLite signature, compares the independent Keychain intent and
  prior/current high-water, validates the new epoch key, and completes only the
  exact one-step signed successor. Missing/tampered intent, old DB, wrong key
  and owner mismatch never auto-heal. App UX and recovery of ambiguous or
  orphaned state still require separate design.
- The persistent ledger has no secret material and uses an **experimental**
  Keychain adapter / fake backend in unit tests. No installation into the
  production app, Developer ID signature, independent trusted head, actual
  physical device provisioning, persisted recipient-side consumed grants,
  two-phase cloud publish, Google Drive or automatic rollout.

Run the isolated `test_owner_ledger.py` suite via the existing
`unittest discover -s experiments/secure_sync` Mac CI selector.

The prepared Keychain record is **not** a user-held off-device recovery
proof, does not ensure monotonic Keychain state under OS backup restore, and
does not establish global/provider freshness. A bool/API digest argument
cannot establish a genuine human approval or independently archived receipt:
the app must introduce a reviewed confirmation boundary before enabling it.
Crash during initial genesis bootstrap is still fail-closed and requires
independent recovery; no automatic reset/repair was added.

## Native bundle-backed vault probe (not user vault storage)

The actual frozen macOS executable has a second diagnostic command,
`secure-sync-native-vault-smoke`, based on `NativeVaultProbeBackend` in
`src/local_asr_server/macos_keychain_native.py`. It uses a distinct fixed
`com.closedroom.app.secure-sync-vault-probe.v1` service and bounded synthetic
account names only. SecItemAdd creates a local device-only, unlocked-login
Keychain record; SecItemUpdate modifies an existing record; a same-signed
second process authenticates a challenge with the new key; a temporary
prepared-intent record is cleared; cleanup is verified. Normal app startup
and all meeting data remain untouched. Failures never fall back to files.

`scripts/probe_packaged_keychain.py --build` now checks both the previous
single-secret path and this new update/clear/readback path, on an exact-SHA
signed test artifact. This does NOT prove the experimental `keyring` vault
is wired to the product, nor Keychain rollback resistance, durable recovery,
production consent, Developer ID/notarization or a second Mac.

### Data Protection Keychain compatibility (macOS)

A real GUI-user ad-hoc signed packaged run on 2026-11-20 created the app
artifact but failed the **new** native-vault diagnostic; the basic prior
probe had already passed. The previous wrapper incorrectly recommended
the login session without surfacing the OSStatus, so root cause was not
diagnosed by that output alone.

Apple requires `kSecUseDataProtectionKeychain=true` for any macOS
`kSecAttrAccessibleWhenUnlockedThisDeviceOnly` item. The native probe now
uses that flag for **all** create/read/update/delete queries under its
isolated synthetic service; never uses `kSecAttrSynchronizable` (iCloud),
never removes ThisDeviceOnly and never silently retries against the
legacy login Keychain. The driver reports only a bounded operation and
OSStatus on failure. Pending new exact-HEAD GUI Terminal verification;
ad-hoc signing/entitlements may still be insufficient, and this must be
treated as a separate real-environment gate rather than an automated PASS.
