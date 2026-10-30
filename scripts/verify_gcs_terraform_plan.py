#!/usr/bin/env python3
"""Fail-closed guard for terraform show -json on ClosedRoom's EXISTING GCS test bucket.

Reads Terraform JSON plan from stdin; prints only aggregate safety result.
Never parses secrets, exports state or applies changes.
"""
from __future__ import annotations

import json
import sys
from typing import Any

PROJECT = "project-tests-498508"
BUCKET = PROJECT + "-closedroom-test"
BUCKET_RESOURCE = "google_storage_bucket.closedroom_test"
PERMITTED_IAM = {
    "google_storage_bucket_iam_member.oauth_object_creator": "roles/storage.objectCreator",
    "google_storage_bucket_iam_member.oauth_object_viewer": "roles/storage.objectViewer",
}
PERMITTED_ACTIONS = {"no-op", "create"}


class UnsafeTerraformPlan(ValueError):
    pass


def validate_plan(plan: Any) -> dict[str, int]:
    if not isinstance(plan, dict):
        raise UnsafeTerraformPlan("Invalid Terraform JSON plan")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list) or not changes:
        raise UnsafeTerraformPlan("Missing resource changes; no approval possible")
    seen_bucket = False
    created_iam_roles: dict[str, str] = {}
    for resource in changes:
        if not isinstance(resource, dict) or resource.get("mode") != "managed":
            raise UnsafeTerraformPlan("Unexpected Terraform resource mode")
        address = resource.get("address")
        change = resource.get("change")
        if not isinstance(change, dict):
            raise UnsafeTerraformPlan("Missing Terraform change record")
        actions = change.get("actions")
        if not isinstance(actions, list) or len(actions) != 1:
            raise UnsafeTerraformPlan("Replacement/deletion is prohibited")
        action = actions[0]
        after = change.get("after")
        if not isinstance(after, dict):
            raise UnsafeTerraformPlan("Missing planned resource attributes")
        if address == BUCKET_RESOURCE:
            if seen_bucket or resource.get("type") != "google_storage_bucket" or action != "no-op":
                raise UnsafeTerraformPlan("Existing bucket must only be imported/read, never changed")
            seen_bucket = True
            expected = {
                "name": BUCKET, "project": PROJECT, "location": "EUROPE-WEST8",
                "storage_class": "STANDARD", "uniform_bucket_level_access": True,
                "public_access_prevention": "enforced", "force_destroy": False,
            }
            if any(after.get(k) != v for k, v in expected.items()):
                raise UnsafeTerraformPlan("Bucket security configuration is not exact")
            policy = after.get("soft_delete_policy")
            if (
                not isinstance(policy, list)
                or len(policy) != 1
                or not isinstance(policy[0], dict)
                or str(policy[0].get("retention_duration_seconds")) != "604800"
            ):
                raise UnsafeTerraformPlan("Bucket soft-delete policy is unexpected")
        elif address and any(address.startswith(prefix + "[") or address == prefix for prefix in PERMITTED_IAM):
            matching = [role for prefix, role in PERMITTED_IAM.items() if address.startswith(prefix + "[") or address == prefix]
            if resource.get("type") != "google_storage_bucket_iam_member" or len(matching) != 1 or action not in PERMITTED_ACTIONS:
                raise UnsafeTerraformPlan("Unexpected IAM change")
            if after.get("bucket") != BUCKET or after.get("role") != matching[0]:
                raise UnsafeTerraformPlan("IAM role or target is unexpected")
            member = after.get("member")
            if not isinstance(member, str) or not member.startswith("user:") or len(member) < 7:
                raise UnsafeTerraformPlan("IAM principal must be a named user")
            if action == "create":
                if matching[0] in created_iam_roles:
                    raise UnsafeTerraformPlan("Multiple new grants for the same role are prohibited")
                created_iam_roles[matching[0]] = member
        else:
            raise UnsafeTerraformPlan("Unexpected resource in Terraform plan")
    if not seen_bucket:
        raise UnsafeTerraformPlan("Expected bucket import/ownership resource missing")
    if created_iam_roles and (
        len(set(created_iam_roles.values())) != 1
        or set(created_iam_roles) != set(PERMITTED_IAM.values())
    ):
        raise UnsafeTerraformPlan("New IAM grants must have both permitted roles for one user")
    return {"bucket_modifications": 0, "iam_members_created": len(created_iam_roles)}


def main() -> int:
    try:
        plan = json.load(sys.stdin)
        summary = validate_plan(plan)
    except (ValueError, TypeError, KeyError):
        print("BLOCKED: Terraform plan did not meet GCS import/least-privilege guardrails.", file=sys.stderr)
        return 2
    print(json.dumps({"status": "safe_plan_guard_pass", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
