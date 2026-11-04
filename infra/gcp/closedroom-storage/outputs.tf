output "bucket_name" {
  description = "Existing GCS test bucket managed through import."
  value       = google_storage_bucket.closedroom_test.name
}

output "oauth_iam_member_configured" {
  description = "Indicates whether non-authoritative IAM bindings were configured by this stack; not proof of valid OAuth consent."
  value       = var.oauth_user_email != null
}
