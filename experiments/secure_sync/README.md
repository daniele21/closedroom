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

No cross-process compare-and-swap, signed device grants, user recovery secret, real Mac/Keychain integration or provider-freshness guarantee exists. A clean device **must not accept Drive's purported current head as proof of freshness**. Do not activate upload or deletion.

The 32-byte secret is **test-only** in this experiment. Do not persist it in plaintext, pass it to telemetry, store it in Drive, or treat the local test fixture as a recovery-key protocol.

The format intentionally authenticates header fields and ciphertext using HKDF-SHA256 + AES-256-GCM. It does **not** establish remote freshness, authorization of devices, revocation, concurrency control, recovery, verified upload/restore or a production export/import path. In particular a malicious/compromised storage provider may delete objects or replay an older *valid* ciphertext; those protections need a trusted authenticated manifest/head checkpoint and independent backup.

Next step: review and adapt this format in the existing canonical TranscriptionStore/RecordingStore projection owners; add correctly locked crypto dependency, consent and Keychain management; add a read-only separate device cache and a Google Drive appDataFolder adapter behind explicit opt-in.

## Source-owned real-Mac gate

On the shared Mac validation lane, `.github/ci/local-test.sh` explicitly runs the `test_*.py` files with transient isolated Python dependencies, then runs:

```sh
uv run --no-project --python 3.12 --with 'cryptography>=46,<47' --with 'keyring>=25,<26' -- python experiments/secure_sync/macos_keychain_probe.py
```

The probe uses **synthetic temporary records only**, a second process and cleanup verification. Never use actual user credentials/vaults. Mac runner PASS is not installed-app Keychain/TCC proof.
