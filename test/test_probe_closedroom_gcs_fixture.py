"""Synthetic AES-GCM fixture and fail-closed cloud gate; no GCP calls."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import probe_closedroom_gcs_fixture as probe  # noqa: E402


class TestGcsFixture(unittest.TestCase):
    def test_prepare_verify_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'fixture'
            result = probe.prepare(folder, probe.DEFAULT_BUCKET)
            self.assertEqual(result['project'], 'project-tests-498508')
            self.assertEqual((folder / 'key.bin').stat().st_mode & 0o077, 0)
            ciphertext = (folder / 'ciphertext.bin').read_bytes()
            self.assertTrue(probe.validate_plaintext(folder, ciphertext)['aes_gcm_authenticated'])
            tampered = bytearray(ciphertext); tampered[-1] ^= 0x01
            with self.assertRaises(ValueError):
                probe.validate_plaintext(folder, bytes(tampered))
            key = folder / 'key.bin'
            key.write_bytes(b'Z' * 32)
            with self.assertRaises(ValueError):
                probe.validate_plaintext(folder, ciphertext)

    def test_cloud_dry_run_never_calls_gcloud(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'fixture'
            probe.prepare(folder, probe.DEFAULT_BUCKET)
            with patch.object(probe, 'call_cloud') as call, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(probe.main(['upload', '--directory', str(folder)]), 0)
            self.assertEqual(json.loads(output.getvalue())['status'], 'dry_run')
            call.assert_not_called()

    def test_reject_foreign_bucket_and_tainted_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'fixture'
            probe.prepare(folder, probe.DEFAULT_BUCKET)
            file = folder / 'manifest.json'
            manifest = json.loads(file.read_text()); manifest['object'] = '../../private'
            file.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                probe.read_fixture(folder)
            with self.assertRaises(ValueError):
                probe.prepare(Path(root) / 'invalid', 'somebody-else')

    def test_owner_and_bucket_security_are_mandatory(self):
        good_project = json.dumps({'projectNumber': '12345'})
        good_bucket = {
            'projectNumber': '12345', 'location': 'EUROPE-WEST8',
            'storageClass': 'STANDARD', 'iamConfiguration': {
                'uniformBucketLevelAccess': {'enabled': True},
                'publicAccessPrevention': 'enforced',
            }, 'softDeletePolicy': {'retentionDurationSeconds': '604800'},
        }
        with patch.object(probe, 'call_cloud', side_effect=[good_project, json.dumps(good_bucket)]):
            probe.verify_bucket(probe.DEFAULT_BUCKET)
        bad_bucket = dict(good_bucket)
        bad_bucket['projectNumber'] = '999'
        with patch.object(probe, 'call_cloud', side_effect=[good_project, json.dumps(bad_bucket)]):
            with self.assertRaises(RuntimeError):
                probe.verify_bucket(probe.DEFAULT_BUCKET)


if __name__ == '__main__':
    unittest.main()
