# ClosedRoom — GCS login-session broker

## Login-session bridge for opt-in real GCS cold backup (2026-11-03)

**Current reality:** interactive Terminal on new Mac successfully reports
`local_credentials_present` and user confirmed `oauth_bucket_read_write_verified`
for the explicit test bucket. Central self-hosted runner preflight still reports
`KEYCHAIN_READ_FAILED`; native diagnostics classify `interaction_denied`
in service context, `permission_denied` through `launchctl asuser`.
Never copy OAuth tokens into GitHub Actions secrets, permit hidden ADC, kill
ClosedRoom during recording or claim the ~9 GB uploaded. Code is not runtime
product cloud mode; it is a manual single cold-backup operation.

Canonical migration, archive and Keychain owners:
`src/local_asr_server/storage/cold_migration.py`,
`gcs_archive.py`, `gcs_oauth.py`, `key_recovery.py`.
The source-owned `scripts/run_gcs_backup_on_runner.py` is the single
headless execution entrypoint. A private, manually installed LaunchAgent
`scripts/closedroom_gcs_login_broker.py` runs the exact-source-pinned
allowlisted operation **in the logged-in Mac session**, not the Keychain-denied
runner job. The central `local-runner-infra` job sends only a private request
with nonce, source SHA, fixed test bucket and an explicit approved action.
No secret, meeting file, OAuth token or recovery code goes through CI
logs/artifacts. Both sides enforce private files (0600), directories (0700),
read-only preflight, a short replay window, no concurrent pending request,
and exactly one request/response per run. The real backup uses an explicit
`broker-backup` request and a separate `real_meeting_upload_approved=true`
central flag.

**Operator bootstrap (new Mac, once, interactive Terminal):**

```bash
cd ~/Projects/local-asr-server
git fetch origin
git switch feature/gcs-storage-discovery-project-tests
git pull --ff-only origin feature/gcs-storage-discovery-project-tests
python3 scripts/install_closedroom_gcs_login_broker.py install
```

The command installs only a user-owned, explicit `launchctl` LaunchAgent and
records the exact current source SHA in a private local configuration. It does
**not** start a backup or read OAuth credentials. On success it reports
`closedroom_login_gcs_broker_installed`. Its SHA **must match** the central
pinned request. macOS may require interactive approval for native Python
Keychain access; grant only to this locally reviewed installed code, not CI.
The broker stops processing when a job completes, but remains available to
receive a future explicit action. The operator can remove it later with:

```bash
cd ~/Projects/local-asr-server
python3 scripts/install_closedroom_gcs_login_broker.py uninstall
```

The central operator workflow is
`local-runner-infra/.github/workflows/closedroom-gcs-mac-backup.yml`.
Trigger *in order* `broker-oauth-verify` (synthetic GCS fixture only),
`broker-preflight` (app fully quit, local catalog/media, scratch space,
recovery Keychain read/write/delete probe), then and only after passing,
`broker-backup` (opt-in real encrypted upload). **A green dispatch or
synthetic probe is never proof of uploaded meetings.** The archive must report
`cold_snapshot_uploaded_pending_restore`, preserve local 0600 receipt
and envelope and store the one-time code in native macOS Keychain; never print
the code in GitHub Actions. Independently export the code into an offline
password manager/recovery location through a user-authenticated on-Mac action:
a Keychain item on the original Mac alone is insufficient disaster recovery.
Keep originals; second-Mac restore/decrypt and app correctness remain pending.

## Full restore verification via native login session (2026-11-04)

The **one-shot actual encrypted GCS backup** completed on the target Mac,
but successful upload alone is insufficient for automatic local audio eviction.
The new source-pinned `broker-restore-verify` operation is distinct from
`broker-backup` and is explicitly non-destructive:

- In the logged-in macOS user session, read only the previously written
  private receipt, encrypted recovery envelope and the recovery code from
  native Keychain. Never print or export the code through GitHub Actions.
- Use the envelope + code to derive a key in an **ephemeral recovery vault**,
  *not* the current Mac's native archive-key Keychain entry. This tests the
  portable recovery mechanism used on a different Mac.
- Download the pinned GCS object generation, authenticate AES-GCM decryption
  and hash checks, extract the entire 26,071-file snapshot into a fresh
  **throwaway 0700 directory** below the user's home, run restored SQLite
  `PRAGMA quick_check`, count recording and transcription rows, then clean
  up only the isolated scratch files created by this operation.
- Never touch existing ClosedRoom recordings, transcripts, catalog, settings,
  the private recovery receipt or the GCS object. No eviction, activation,
  remote deletion, nor cloud inference is performed.
- On insufficient scratch, invalid Keychain access, missing receipt, or
  any checksum/SQLite error: **fail closed** with a sanitized error code.
- The success status `cold_snapshot_restored_verified_isolated` means
  **same-Mac recovery materials worked**. It specifically does **not**
  prove independent custody of the code or a complete recovery on a
  different Mac. Keep all original meeting audio.

The existing installed LaunchAgent is pinned to an older source SHA. A
source update requires the operator to explicitly reinstall the private
agent from the updated branch; CI must never rewrite that config or read
Keychain itself. After updating `~/Projects/local-asr-server` on the
target Mac and confirming no pending request, run:

```bash
cd ~/Projects/local-asr-server
python3 scripts/install_closedroom_gcs_login_broker.py uninstall
git fetch origin
git switch feature/gcs-storage-discovery-project-tests
git pull --ff-only origin feature/gcs-storage-discovery-project-tests
python3 scripts/install_closedroom_gcs_login_broker.py install
```

Then the trusted central operator can pin the **exact newly installed source
SHA** and dispatch a fresh `broker-restore-verify` request with
`real_meeting_upload_approved=false`. The source and central broker
trust-contract tests must PASS first. Do not dispatch `broker-backup`
again: the one-shot source receipt already exists and an implicit re-upload
would violate the existing migration lifecycle.

**Further blocking gate before automatic audio eviction:** store the recovery
code off-device (e.g. password manager) independently of the envelope and
receipt, verify their availability from a second authenticated Mac or a
completely isolated restored Keychain setup, and integrate per-meeting GCS
asset refs/hydration with `RecordingStore`. This test only proves the
existing *cold backup* and never grants eviction authority.
