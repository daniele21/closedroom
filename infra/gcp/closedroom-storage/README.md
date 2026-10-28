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

## Blocking before real meeting backup

Desktop OAuth identity and bucket access, native Keychain storage, portable recovery on a second Mac, dependency packaging, and the canonical RecordingStore/metadata backup lifecycle are still outstanding. `storage_mode=local` remains enforced; **no real media upload, eviction or remote deletion**.
