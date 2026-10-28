#!/usr/bin/env python3
"""Provision an isolated private ClosedRoom GCS test bucket, never user media.

Dry-run by default. --apply requires the operator's authenticated gcloud
identity with bucket-creation authority in the fixed test project. It does not
grant IAM principals or upload any recording. It is NOT app OAuth integration.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

PROJECT = 'project-tests-498508'
BUCKET_PREFIX = PROJECT + '-closedroom-test'
DEFAULT_BUCKET = BUCKET_PREFIX
DEFAULT_LOCATION = 'europe-west8'


def create_command(bucket: str, location: str) -> list[str]:
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('Invalid bucket identifier')
    if not (bucket == BUCKET_PREFIX or bucket.startswith(BUCKET_PREFIX + '-')):
        raise ValueError('Bucket must use the dedicated ClosedRoom test prefix')
    if not re.fullmatch(r'[a-z]+(?:-[a-z]+)*[0-9]+', location):
        raise ValueError('Expected a GCP regional location')
    return [
        'gcloud', 'storage', 'buckets', 'create', 'gs://' + bucket,
        '--project=' + PROJECT, '--location=' + location,
        '--default-storage-class=STANDARD', '--uniform-bucket-level-access',
        '--public-access-prevention', '--soft-delete-duration=7d',
    ]



def classify_create_failure(stderr: str) -> tuple[str, str]:
    """Reduce untrusted gcloud diagnostics to a stable, non-sensitive reason.

    Never print the raw diagnostics: they may include email, token or bucket
    identifiers. Do not claim a conflict bucket is ours without verification.
    """
    error = stderr.casefold()
    if any(marker in error for marker in (
        'unauthorized_client', 'invalid_grant', 'no active account',
        're-authentication', 'reauthentication', 'login required',
        'please run: gcloud auth login', 'invalid credentials',
    )):
        return ('AUTHENTICATION', 'Authenticate with gcloud auth login; check the active identity with gcloud auth list.')
    if any(marker in error for marker in (
        'already exists', 'already in use', 'already taken',
        'bucket name is not available', 'conflict', 'http 409', 'httperror 409',
    )):
        return ('NAME_CONFLICT', 'Bucket names are global. Verify an existing bucket ownership/policy, or retry with --bucket project-tests-498508-closedroom-test-<unique-suffix>.')
    if any(marker in error for marker in (
        'orgpolicy', 'organization policy', 'resource locations constraint',
        'gcp.resourcelocations', 'violates constraint',
    )):
        return ('ORG_POLICY', 'Check project organization restrictions, especially allowed regions and bucket naming policy.')
    if any(marker in error for marker in (
        'billing account', 'billing is disabled', 'billing not enabled',
        'project has no billing', 'billingdisabled',
    )):
        return ('BILLING', 'Check billing status of project-tests-498508 before provisioning.')
    if any(marker in error for marker in (
        'storage.googleapis.com is disabled', 'api has not been used',
        'has not been enabled', 'service_disabled',
    )):
        return ('API_DISABLED', 'Confirm the Cloud Storage API is enabled for project-tests-498508.')
    if any(marker in error for marker in (
        'permission storage.buckets.create', "permission 'storage.buckets.create'", 'permission denied', 'access denied',
        'forbidden', 'http 403', 'httperror 403', 'permission ', 'does not have permission',
    )):
        return ('PERMISSION_DENIED', 'Check the active gcloud identity has storage.buckets.create on project-tests-498508.')
    if any(marker in error for marker in (
        'unrecognized arguments', 'unknown arguments', 'invalid choice',
        'no such option', 'not a valid choice',
    )):
        return ('CLI_FLAGS', 'Check gcloud --version and gcloud storage buckets create --help; update the CLI if necessary.')
    if any(marker in error for marker in ('not found', 'http 404', 'httperror 404', 'project does not exist')):
        return ('PROJECT_NOT_FOUND', 'Verify project-tests-498508 exists and that the active identity can access it.')
    if any(marker in error for marker in ('invalid location', 'invalid location constraint', 'http 400', 'httperror 400')):
        return ('INVALID_ARGUMENT', 'Inspect bucket name/location and project constraints; keep region europe-west8 unless explicitly changed.')
    return ('UNCLASSIFIED', 'Run the equivalent gcloud storage buckets create command directly to inspect the original error locally; redact personal information before sharing it.')



def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bucket', default=DEFAULT_BUCKET)
    p.add_argument('--location', default=DEFAULT_LOCATION)
    p.add_argument('--apply', action='store_true', help='Actually create the bucket')
    args = p.parse_args(argv)
    try:
        command = create_command(args.bucket, args.location)
    except ValueError as exc:
        p.error(str(exc))
    if not args.apply:
        print(json.dumps({'status': 'dry_run', 'project': PROJECT, 'bucket': args.bucket,
                          'location': args.location, 'command': command,
                          'warning': 'No cloud changes, credentials, IAM grants or uploads attempted.'}, indent=2))
        return 0
    if not shutil.which('gcloud'):
        print('gcloud is unavailable; bucket was not created.', file=sys.stderr)
        return 2
    # No shell, no service account key, no implicit login or IAM role changes.
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print('Bucket creation timed out. Outcome is unknown: inspect bucket state before retrying.', file=sys.stderr)
        return 2
    except OSError:
        print('Cannot start gcloud. Check local CLI installation and execution permissions.', file=sys.stderr)
        return 2
    if result.returncode:
        code, action = classify_create_failure(result.stderr or '')
        print(f'Bucket creation failed [{code}]: {action}', file=sys.stderr)
        print('No provisioning success is claimed. Never infer bucket ownership from a name conflict.', file=sys.stderr)
        return 1
    print(json.dumps({'status': 'create_command_succeeded', 'project': PROJECT,
                      'bucket': args.bucket, 'location': args.location,
                      'next': 'Verify bucket IAM and independent fixture upload/decrypt/restore before proceeding.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
