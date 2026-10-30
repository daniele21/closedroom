"""Guard real Terraform JSON plans before any GCS apply (no cloud access)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_gcs_terraform_plan import validate_plan, UnsafeTerraformPlan  # noqa: E402


def bucket_change(action="no-op"):
    return {
        "mode": "managed", "type": "google_storage_bucket",
        "address": "google_storage_bucket.closedroom_test",
        "change": {"actions": [action], "after": {
            "name": "project-tests-498508-closedroom-test",
            "project": "project-tests-498508",
            "location": "EUROPE-WEST8",
            "storage_class": "STANDARD",
            "uniform_bucket_level_access": True,
            "public_access_prevention": "enforced",
            "force_destroy": False,
            "soft_delete_policy": [{"retention_duration_seconds": 604800}],
        }},
    }


def iam_change(name, role, action="create"):
    return {
        "mode": "managed", "type": "google_storage_bucket_iam_member",
        "address": f'google_storage_bucket_iam_member.{name}["user:example@example.com"]',
        "change": {"actions": [action], "after": {
            "bucket": "project-tests-498508-closedroom-test",
            "role": role, "member": "user:example@example.com",
        }},
    }


class TestTerraformPlanGuard(unittest.TestCase):
    def test_import_only_safe(self):
        self.assertEqual(validate_plan({"resource_changes": [bucket_change()]}),
                         {"bucket_modifications": 0, "iam_members_created": 0})

    def test_bucket_import_plus_two_additive_iam_safe(self):
        plan = {"resource_changes": [
            bucket_change(),
            iam_change("oauth_object_creator", "roles/storage.objectCreator"),
            iam_change("oauth_object_viewer", "roles/storage.objectViewer"),
        ]}
        self.assertEqual(validate_plan(plan)["iam_members_created"], 2)

    def test_rejects_bucket_create_update_delete_and_replacement(self):
        for actions in (["create"], ["update"], ["delete"], ["delete", "create"]):
            with self.subTest(actions=actions):
                plan = {"resource_changes": [bucket_change()]}
                plan["resource_changes"][0]["change"]["actions"] = actions
                with self.assertRaises(UnsafeTerraformPlan):
                    validate_plan(plan)

    def test_rejects_bucket_security_drift_and_wrong_bucket(self):
        for field, value in (
            ("name", "other-bucket"),
            ("location", "US"),
            ("public_access_prevention", "inherited"),
            ("uniform_bucket_level_access", False),
            ("force_destroy", True),
            ("soft_delete_policy", [{"retention_duration_seconds": 0}]),
        ):
            with self.subTest(field=field):
                plan = {"resource_changes": [bucket_change()]}
                plan["resource_changes"][0]["change"]["after"][field] = value
                with self.assertRaises(UnsafeTerraformPlan):
                    validate_plan(plan)

    def test_rejects_unexpected_or_overprivileged_iam(self):
        valid = {"resource_changes": [bucket_change()]}
        bad = (
            iam_change("oauth_object_creator", "roles/storage.admin"),
            iam_change("oauth_object_creator", "roles/storage.objectCreator", "delete"),
            iam_change("oauth_object_admin", "roles/storage.objectAdmin"),
        )
        for extra in bad:
            with self.subTest(extra=extra):
                with self.assertRaises(UnsafeTerraformPlan):
                    validate_plan({"resource_changes": [bucket_change(), extra]})

    def test_rejects_partial_new_iam_and_empty_plan(self):
        with self.assertRaises(UnsafeTerraformPlan):
            validate_plan({"resource_changes": [bucket_change(),
                                                  iam_change("oauth_object_creator", "roles/storage.objectCreator")]})
        with self.assertRaises(UnsafeTerraformPlan):
            validate_plan({"resource_changes": []})

    def test_duplicate_iam_role_does_not_pass_as_two_approved_roles(self):
        twice = [
            bucket_change(),
            iam_change("oauth_object_creator", "roles/storage.objectCreator"),
            iam_change("oauth_object_creator", "roles/storage.objectCreator"),
        ]
        twice[-1]["address"] = twice[-1]["address"].replace("example@example.com", "other@example.com")
        twice[-1]["change"]["after"]["member"] = "user:other@example.com"
        with self.assertRaises(UnsafeTerraformPlan):
            validate_plan({"resource_changes": twice})

    def test_two_roles_must_target_same_identity(self):
        changes = [
            bucket_change(),
            iam_change("oauth_object_creator", "roles/storage.objectCreator"),
            iam_change("oauth_object_viewer", "roles/storage.objectViewer"),
        ]
        changes[-1]["change"]["after"]["member"] = "user:other@example.com"
        with self.assertRaises(UnsafeTerraformPlan):
            validate_plan({"resource_changes": changes})

    def test_no_secret_bearing_output_for_failures(self):
        with self.assertRaises(UnsafeTerraformPlan) as caught:
            validate_plan({"resource_changes": [dict(bucket_change(), address="user:private@example.com")]})
        self.assertNotIn("private@example.com", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
