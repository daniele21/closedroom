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
