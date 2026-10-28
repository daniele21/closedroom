#!/usr/bin/env python3
"""Synthetic, encrypted GCS roundtrip probe; never accesses user meeting data.

Runs locally by default. Remote upload/restore requires --apply, authenticated
gcloud and a private bucket verified to belong to project-tests-498508.
The exported 0600 test key is NOT the product's Keychain or cross-device key
recovery mechanism. This is a discovery gate, never a backup tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import uuid

from bootstrap_closedroom_gcs_test import DEFAULT_BUCKET, DEFAULT_LOCATION, PROJECT, create_command

FORMAT = 'closedroom-gcs-fixture-v1'
MAGIC = b'CRGCSFIX1\x00'
AAD = b'ClosedRoom GCS fixture probe v1'
OBJECT_RE = re.compile(r'closedroom-fixtures/[0-9a-f]{32}\.bin\Z')
FIXTURE_SIZE = 64 * 1024


def crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError('cryptography is required for synthetic AES-256-GCM validation') from exc
    return AESGCM


def seal(key: bytes, plaintext: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + crypto()(key).encrypt(nonce, plaintext, AAD)


def unseal(key: bytes, payload: bytes) -> bytes:
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 12 + 16:
        raise ValueError('Invalid fixture envelope')
    start = len(MAGIC)
    try:
        return crypto()(key).decrypt(payload[start:start + 12], payload[start + 12:], AAD)
    except Exception:
        raise ValueError('Fixture authentication failed') from None


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def prepare(directory: Path, bucket: str) -> dict:
    create_command(bucket, DEFAULT_LOCATION)  # Strict test-bucket allowlist.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory.chmod(0o700)
    key = secrets.token_bytes(32)
    plaintext = b'ClosedRoom synthetic fixture only.\n' + secrets.token_bytes(FIXTURE_SIZE)
    ciphertext = seal(key, plaintext)
    manifest = {
        'schema': FORMAT, 'project': PROJECT, 'bucket': bucket,
        'object': 'closedroom-fixtures/' + uuid.uuid4().hex + '.bin',
        'plaintext_sha256': sha256(plaintext), 'ciphertext_sha256': sha256(ciphertext),
        'ciphertext_bytes': len(ciphertext),
    }
    fd = os.open(directory / 'key.bin', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as file:
        file.write(key)
        file.flush(); os.fsync(file.fileno())
    (directory / 'ciphertext.bin').write_bytes(ciphertext)
    (directory / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
    return manifest


def read_fixture(directory: Path) -> tuple[dict, bytes]:
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != FORMAT or manifest.get('project') != PROJECT:
        raise ValueError('Unexpected probe manifest schema/project')
    create_command(manifest['bucket'], DEFAULT_LOCATION)
    if not isinstance(manifest.get('object'), str) or not OBJECT_RE.fullmatch(manifest['object']):
        raise ValueError('Unsafe GCS fixture object key')
    key_file = directory / 'key.bin'
    if key_file.is_symlink() or key_file.stat().st_mode & 0o077:
        raise ValueError('Fixture key permissions are not private')
    key = key_file.read_bytes()
    if len(key) != 32:
        raise ValueError('Invalid fixture key')
    return manifest, key


def validate_plaintext(directory: Path, ciphertext: bytes) -> dict:
    manifest, key = read_fixture(directory)
    if len(ciphertext) != manifest['ciphertext_bytes'] or sha256(ciphertext) != manifest['ciphertext_sha256']:
        raise ValueError('Remote ciphertext differs from prepared fixture')
    plaintext = unseal(key, ciphertext)
    if sha256(plaintext) != manifest['plaintext_sha256']:
        raise ValueError('Decrypted fixture hash mismatch')
    return {'status': 'verified', 'ciphertext_bytes': len(ciphertext), 'sha256_match': True,
            'aes_gcm_authenticated': True}


def call_cloud(command: list[str]) -> str:
    if not shutil.which('gcloud'):
        raise RuntimeError('gcloud unavailable; no cloud operation attempted')
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=180)
    if result.returncode:
        # Never echo gcloud output: tokens/account/object details could leak.
        raise RuntimeError('GCS operation failed; inspect cloud authorization and bucket configuration locally')
    return result.stdout


def verify_bucket(bucket: str) -> None:
    create_command(bucket, DEFAULT_LOCATION)
    project = json.loads(call_cloud(['gcloud', 'projects', 'describe', PROJECT, '--format=json']))
    raw = json.loads(call_cloud(['gcloud', 'storage', 'buckets', 'describe', 'gs://' + bucket,
                                 '--raw', '--format=json', '--project=' + PROJECT]))
    project_number = project.get('projectNumber') or project.get('project_number')
    bucket_number = raw.get('projectNumber') or raw.get('project_number')
    iam = raw.get('iamConfiguration') or {}
    uniform = (iam.get('uniformBucketLevelAccess') or {}).get('enabled')
    pap = iam.get('publicAccessPrevention')
    retention = (raw.get('softDeletePolicy') or {}).get('retentionDurationSeconds')
    if not project_number or str(project_number) != str(bucket_number) or (
        str(raw.get('location', '')).lower() != DEFAULT_LOCATION or
        str(raw.get('storageClass', '')).upper() != 'STANDARD' or
        uniform is not True or pap != 'enforced' or str(retention) != '604800'
    ):
        raise RuntimeError('Bucket owner or privacy/region/class/soft-delete policy could not be verified')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'verify-local', 'upload', 'restore'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--apply', action='store_true', help='Allow GCS network operations')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'prepare':
            result = prepare(args.directory, args.bucket)
            output = {'status': 'prepared', 'project': PROJECT, 'bucket': result['bucket'],
                      'object_created': False, 'encryption': 'AES-256-GCM'}
        elif args.operation == 'verify-local':
            output = validate_plaintext(args.directory, (args.directory / 'ciphertext.bin').read_bytes())
        else:
            manifest, _key = read_fixture(args.directory)
            if not args.apply:
                output = {'status': 'dry_run', 'operation': args.operation, 'project': PROJECT,
                          'remote_changes': False}
            else:
                verify_bucket(manifest['bucket'])
                uri = 'gs://' + manifest['bucket'] + '/' + manifest['object']
                if args.operation == 'upload':
                    validate_plaintext(args.directory, (args.directory / 'ciphertext.bin').read_bytes())
                    call_cloud(['gcloud', 'storage', 'cp', str(args.directory / 'ciphertext.bin'), uri,
                                '--if-generation-match=0', '--project=' + PROJECT])
                    output = {'status': 'uploaded_not_restored', 'project': PROJECT, 'object_is_synthetic': True}
                else:
                    destination = args.directory / 'restored-ciphertext.bin'
                    if destination.exists() or destination.is_symlink():
                        raise RuntimeError('Restore destination already exists')
                    call_cloud(['gcloud', 'storage', 'cp', uri, str(destination), '--project=' + PROJECT])
                    try:
                        output = validate_plaintext(args.directory, destination.read_bytes())
                    finally:
                        destination.unlink(missing_ok=True)
        print(json.dumps(output, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired):
        # Avoid echoing arbitrary exception text or private paths from the filesystem.
        print('Fixture operation blocked or failed; check environment, test key and bucket policy.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
