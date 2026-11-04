# Import before managing existing infrastructure. Do not let Terraform create it.
# This import is safe to retain: Terraform skips it after the resource is in state.
import {
  to = google_storage_bucket.closedroom_test
  id = "project-tests-498508/project-tests-498508-closedroom-test"
}
