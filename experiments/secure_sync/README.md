# Secure sync crypto proof — NOT production sync

Isolated, offline-only format experiment. No Google OAuth, network traffic, upload, background job, Keychain, device pairing, cloud fallback, app integration or cleanup. Requires `cryptography` (not added to the product lockfile).

Run with the dependency available:

```sh
python3 -m unittest discover -s experiments/secure_sync -v
```

The 32-byte secret is **test-only** in this experiment. Do not persist it in plaintext, pass it to telemetry, store it in Drive, or treat the local test fixture as a recovery-key protocol.

The format intentionally authenticates header fields and ciphertext using HKDF-SHA256 + AES-256-GCM. It does **not** establish remote freshness, authorization of devices, revocation, concurrency control, recovery, verified upload/restore or a production export/import path. In particular a malicious/compromised storage provider may delete objects or replay an older *valid* ciphertext; those protections need a trusted authenticated manifest/head checkpoint and independent backup.

Next step: review and adapt this format in the existing canonical TranscriptionStore/RecordingStore projection owners; add correctly locked crypto dependency, consent and Keychain management; add a read-only separate device cache and a Google Drive appDataFolder adapter behind explicit opt-in.
