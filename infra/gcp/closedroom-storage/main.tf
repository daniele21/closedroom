# Existing GCS test bucket ONLY; do not create another or replace it.
# Terraform 1.5+ imports the existing bucket on the first approved apply.
resource "google_storage_bucket" "closedroom_test" {
  project                     = "project-tests-498508"
  name                        = "project-tests-498508-closedroom-test"
  location                    = "EUROPE-WEST8"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Explicitly preserve the seven-day soft-delete policy verified on the Mac.
  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  # Never allow this IaC stack to destroy or empty a meeting archive bucket.
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}

# Non-authoritative IAM additions: other bucket IAM members stay untouched.
# Consent is explicit and managed outside Terraform in the Desktop OAuth client.
locals {
  oauth_member = var.oauth_user_email == null ? [] : ["user:${var.oauth_user_email}"]
}

resource "google_storage_bucket_iam_member" "oauth_object_creator" {
  for_each = toset(local.oauth_member)

  bucket = google_storage_bucket.closedroom_test.name
  role   = "roles/storage.objectCreator"
  member = each.value
}

resource "google_storage_bucket_iam_member" "oauth_object_viewer" {
  for_each = toset(local.oauth_member)

  bucket = google_storage_bucket.closedroom_test.name
  role   = "roles/storage.objectViewer"
  member = each.value
}
