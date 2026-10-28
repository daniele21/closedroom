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
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        # Do not echo stderr: remote diagnostics may contain private account details.
        print('Bucket creation failed. Inspect authenticated gcloud errors locally; no success claimed.', file=sys.stderr)
        return 1
    print(json.dumps({'status': 'create_command_succeeded', 'project': PROJECT,
                      'bucket': args.bucket, 'location': args.location,
                      'next': 'Verify bucket IAM and independent fixture upload/decrypt/restore before proceeding.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
