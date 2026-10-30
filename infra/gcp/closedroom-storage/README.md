# ClosedRoom GCS test infrastructure

Scope: **existing test bucket only** in `project-tests-498508`.
This is a development aid, NOT permission to upload real recordings.

## Safety contract

- The bucket already exists and is **imported**, never recreated; `force_destroy = false` and `prevent_destroy = true`.
- Region `EUROPE-WEST8`, Standard, uniform access, public access prevention `enforced`, soft delete **604800 seconds**.
- No role is granted by default. `oauth_user_email` is explicit and grants ONLY bucket-scoped `roles/storage.objectCreator` and `roles/storage.objectViewer`. These are additive **IAM member** resources; they do not remove existing permissions or reduce any project-level roles the user already has.
- No OAuth Client ID, consent screen, browser login, refresh token, Keychain secret, customer content or Google service-account key is created or persisted by Terraform.
- `terraform destroy` is prohibited. Do not change the bucket name, project, location, or replace the bucket. Do not bypass `prevent_destroy`.
- Terraform state and plan may contain resource configuration and IAM principal identifiers; never commit them. This directory ignores local state and plans. Before team/production use, move state to a **separate, access-restricted remote backend** (not this archive bucket), with a reviewed migration and access policy.

## First use (authorized Mac)

1. Install Terraform >= 1.5 and Google Cloud SDK. Authenticate your infrastructure operator using `gcloud auth application-default login` (Terraform Google provider uses ADC). This is **only for Terraform**, not ClosedRoom runtime. Use a principal authorized to read and manage the test bucket/IAM.
2. `gcloud config set project project-tests-498508`. Confirm the bucket before import:

   ```bash
   python3 scripts/probe_closedroom_gcs_fixture.py check-bucket --apply
   ```

3. From the repo root, enter `infra/gcp/closedroom-storage` and prepare a protected state directory:

   ```bash
   cd infra/gcp/closedroom-storage
   umask 077
   terraform init
   terraform fmt -check
   terraform validate
   terraform plan -out=closedroom.tfplan
   terraform show closedroom.tfplan
   terraform show -json closedroom.tfplan | python3 ../../../scripts/verify_gcs_terraform_plan.py
   ```

   The guard must print `safe_plan_guard_pass` and `bucket_modifications: 0`; it **refuses** bucket creation, update, replacement, deletion, unknown resources or unapproved IAM roles. This does not replace human review of the complete `terraform show` output.

4. The **initial plan should show the bucket being imported** and **zero bucket creates, destroys, or replacements**. Abort on unexpected drift or security-setting changes. When the plan is reviewed, `terraform apply closedroom.tfplan` performs the import and any explicitly approved changes. This may require bucket-management permissions.
5. Only after the Google OAuth Desktop client and authorized user are known, optionally add `oauth_user_email = "your-user@example.com"` to `terraform.tfvars`; repeat the plan, inspect two additive IAM members, then explicitly approve `terraform apply`. If existing project-level roles already grant more, these additions do not reduce those privileges. An OAuth consent grant is **not** created by IAM.
6. From repo root, run `python3 scripts/probe_closedroom_gcs_fixture.py check-bucket --apply` again. Do not claim Terraform PASS without `fmt`, `validate`, reviewed `plan`, and actual state/application evidence.

## Separate Google Auth Platform step

In `project-tests-498508`, create/configure Google Auth Platform branding, audience and test users as appropriate, then **Clients > Create client > Desktop app**. Export the Desktop OAuth JSON to a private path **outside git** (`chmod 600`). The client ID/consent is not managed by this Terraform provider configuration.

After the OAuth client is prepared, run the separate (still experimental) ClosedRoom script from the repository root. Always validate the file first: `check-client` reads the local private JSON but does **not** start the browser, access Keychain or contact Google. Google Desktop exports may use either official authorization endpoint; do not edit the downloaded JSON to work around a rejected endpoint.


```bash
PYTHONPATH=src uv run --no-project --with cryptography --with keyring --with google-auth-oauthlib --with google-auth python scripts/probe_closedroom_gcs_oauth.py check-client --client-json /private/path/oauth-desktop.json
PYTHONPATH=src uv run --no-project --with cryptography --with keyring --with google-auth-oauthlib --with google-auth python scripts/probe_closedroom_gcs_oauth.py status --client-json /private/path/oauth-desktop.json
PYTHONPATH=src uv run --no-project --with cryptography --with keyring --with google-auth-oauthlib --with google-auth python scripts/probe_closedroom_gcs_oauth.py connect --client-json /private/path/oauth-desktop.json
```

The CLI returns safe JSON error codes: `CLIENT_FILE_MISSING` (wrong path), `CLIENT_FILE_PERMISSIONS` (use `chmod 600`), `CLIENT_FILE_NOT_DESKTOP` (download a Google Desktop OAuth client, not Web/service-account JSON), `CLIENT_ENDPOINT_UNSUPPORTED` (invalid identity endpoint), `CLIENT_ID_INVALID`, `KEYCHAIN_UNAVAILABLE` / `KEYCHAIN_READ_FAILED`, `OAUTH_BROWSER_FLOW_FAILED` (browser, consent, local callback or exchange), `OAUTH_REFRESH_TOKEN_MISSING`, and `KEYCHAIN_WRITE_FAILED`. Never copy the JSON, refresh token, callback URL or client secret into a support issue.

The CLI is **opt-in** and not a production UI. Credentials are meant for the macOS Keychain; project IAM and refresh behavior must still be validated with the *desktop* identity and a real GCS request. Disconnecting locally does not revoke the remote Google grant.

## Verify the *Keychain OAuth* identity against GCS (synthetic only)

After an operator has seen `desktop_oauth_saved_in_keychain`, prove that
the desktop identity (rather than Terraform/gcloud ADC) can both create and
read an object on the private test bucket. The probe hardcodes the approved
test project and bucket and creates only 4 KiB of random bytes under
`closedroom-oauth-fixtures/`. It does not enumerate or send meeting data,
delete objects, print secrets or use a default-credential fallback.

From the repository root:

```bash
CLIENT_JSON="$HOME/.config/closedroom/oauth-desktop.json"
PYTHONPATH=src uv run --no-project --with keyring --with google-auth --with google-auth-oauthlib --with google-cloud-storage python scripts/probe_closedroom_gcs_oauth.py status --client-json "$CLIENT_JSON"
PYTHONPATH=src uv run --no-project --with keyring --with google-auth --with google-auth-oauthlib --with google-cloud-storage python scripts/probe_closedroom_gcs_oauth.py verify-bucket --client-json "$CLIENT_JSON" --apply
```

Expected final `status`: `oauth_bucket_read_write_verified`; it reports
`auth_source=native_keychain`, `generation_pinned=true` and
`meeting_data_transferred=false`. The synthetic object is retained (the
minimum create/viewer IAM roles intentionally **do not permit delete**).
The Google OAuth client may be in Testing mode, requiring renewed consent
after token expiry.

On `GCS_IAM_FORBIDDEN`, first check which Google account was granted
consent. If necessary, set `oauth_user_email` in the local, gitignored
Terraform `terraform.tfvars` for that **same** principal; review
`terraform plan -out=iam.tfplan`, inspect `terraform show` and run
`terraform show -json iam.tfplan | python3 ../../../scripts/verify_gcs_terraform_plan.py`
from the infrastructure directory. Only after an approved plan containing
two additive bucket IAM members and zero bucket changes, explicitly
apply `iam.tfplan`; then re-run the probe. Do not add IAM blindly:
the OAuth identity may already have adequate permissions via other grants.

`GCS_OAUTH_TOKEN_REJECTED` points to the token/refresh grant,
`GCS_BUCKET_OR_OBJECT_NOT_FOUND` to target or object read,
`GCS_GENERATION_CONFLICT` to an unexpected generation failure and
`GCS_NETWORK_OR_SDK_FAILURE` to network/SDK conditions. Raw credential
errors are intentionally suppressed; never paste tokens or downloaded JSON.

## Next gate: portable archive-key recovery on two physical Macs

This is a **test-only Keychain service**, distinct from OAuth and any future
real meeting encryption key. This is not a cloud-backup test and does not need
IAM or another Terraform apply. The completed OAuth probe proves test-bucket
create/read rights only for the tested Google account.

On **Mac A**, with the feature branch checked out and an interactive terminal:

```bash
cd ~/Personal/local-asr-server
umask 077
mkdir -p "$HOME/.config/closedroom"
PYTHONPATH=src uv run --no-project --with cryptography --with keyring \
  python scripts/verify_gcs_keychain_recovery.py create-fixture \
  --recovery-file "$HOME/.config/closedroom/key-recovery-fixture.json"
```

The command creates an encrypted recovery envelope with `0600` permissions
and prints a **one-time 256-bit test recovery code**. Keep that code
**separate from the file**; do not paste it into issues, chat, command-line
arguments, terminal logs or screenshots. Do not delete the Mac A Keychain key.

Transfer **only** `key-recovery-fixture.json` privately to **Mac B**
(never commit it). On Mac B, use the same ClosedRoom feature branch, place
the file at a private path, then:

```bash
chmod 600 "$HOME/.config/closedroom/key-recovery-fixture.json"
PYTHONPATH=src uv run --no-project --with cryptography --with keyring \
  python scripts/verify_gcs_keychain_recovery.py restore-fixture \
  --recovery-file "$HOME/.config/closedroom/key-recovery-fixture.json"
PYTHONPATH=src uv run --no-project --with cryptography --with keyring \
  python scripts/verify_gcs_keychain_recovery.py check-fixture \
  --recovery-file "$HOME/.config/closedroom/key-recovery-fixture.json"
```

Type the test recovery code at the **hidden** prompt. Both commands must
report `fingerprint matches: True`. The test refuses to overwrite a
different Keychain key and does not mutate the archive bucket. If an earlier
test key already exists on Mac B, don't delete it blindly; examine the
fixture-service conflict first. This proves key portability only, not
production backup/restore or independent recovery of a full meeting.

## Legacy Mac migration preflight: locate actual catalog (read-only)

Before any real meeting upload, run the anonymous catalog locator on the **old Mac**:

```bash
cd ~/Personal/local-asr-server
python3 scripts/audit_meeting_data.py --discover-catalog
```

The command only reads local settings and stats known candidate DB paths from
`CatalogStore.default_db_path`; it never opens or creates SQLite, initiates
network requests, or outputs private full paths/meeting IDs. `file_present`
is **not** proof that the file is the active SQLite catalog; inspect the app's
actual configured/runtime DB and compare a consistent SQLite snapshot before
migration. If `configured` is missing, a DB at `application_support` or a
legacy parent may explain the earlier inventory's missing catalog. Running
the audit with an environment override can differ from the packaged app.

On 2026-10-30 the old Mac's `--discover-catalog` showed exactly one
candidate: `application_support=file_present`; the configured catalog and
other known paths were missing. That does **not** prove this is the *active*
catalog because fallback behavior and the packaged app environment differ.

For the next read-only check, **quit ClosedRoom entirely first** so no
process can write the database. Then from the repository root:

```bash
python3 scripts/inspect_closedroom_catalog.py
```

This explicit diagnostic opens only the existing `Application Support`
candidate with SQLite `mode=ro&immutable=1`; it rejects WAL/SHM/journal
sidecars instead of silently ignoring pending transactions. It reports
schema presence, SQLite `quick_check`, aggregate recording/transcription/
analysis counts and references to missing recording IDs, **not** titles,
IDs, paths or transcript content. It does not construct CatalogStore (that
would initialize/migrate/create files), open a cloud connection or upload.

A `catalog_candidate_read_only_inspected` result is **not** proof the
candidate is the DB used by the app; verify against the actual running
app and consistent migration snapshot in a later dedicated gate. If a
sidecar exists, quit the app properly and inspect the condition rather
than deleting the sidecar.

The operator's 2026-10-30 closed-app read-only catalog inspection returned
`quick_check_pass=true`, 203 recording rows, 91 transcription rows, 73
analysis runs, 89 transcripts linked to valid recording rows and 2 independent
transcripts. The earlier file inventory counted 299 `metadata.json` files
and 182 files in the transcriptions root: JSON+TXT is the normal export pair,
but do **not** infer there are 91 matching pairs without checking. Catalog
candidate is still **not proven to be the active runtime database**.

Next, with ClosedRoom still fully quit and current branch checked out:

```bash
python3 scripts/reconcile_closedroom_data.py
```

This read-only scan compares in-memory IDs from `YYYY-MM-DD/UUID/metadata.json`
and `transcript_*.json` against candidate SQLite tables. It reports **only
aggregate difference counts** (files absent from catalog, catalog rows missing
files, invalid metadata and mismatched transcription filenames); it does not
send content to GCS, print names/IDs/text or write SQLite. It rejects WAL,
SHM or journal sidecars to avoid stale immutable reads. Even a clean report
does not authorize cloud migration: actual active DB, consistent snapshot,
archive manifest and tested independent restore are separate blocking gates.

Do **not** upload the raw running SQLite DB or `-wal`/`-shm` files, blindly
regenerate a catalog, or purge local originals. Take a SQLite online backup
from the canonical owner only when the migration implementation is ready,
then validate complete recording/transcription relationships and independent
restore on another Mac. All real-user uploads remain disabled at this stage.

## Blocking before real meeting backup

Desktop OAuth identity and bucket access, native Keychain storage, portable recovery on a second Mac, dependency packaging, and the canonical RecordingStore/metadata backup lifecycle are still outstanding. `storage_mode=local` remains enforced; **no real media upload, eviction or remote deletion**.
