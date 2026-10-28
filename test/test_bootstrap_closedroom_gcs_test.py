"""No real GCP calls; validates safe bucket bootstrap behavior."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bootstrap_closedroom_gcs_test as bootstrap  # noqa: E402


class GCSBootstrapTests(unittest.TestCase):
    def test_exact_project_private_standard_and_seven_day_soft_delete(self):
        cmd = bootstrap.create_command(bootstrap.DEFAULT_BUCKET, 'europe-west8')
        self.assertIn('--project=project-tests-498508', cmd)
        self.assertIn('--uniform-bucket-level-access', cmd)
        self.assertIn('--public-access-prevention', cmd)
        self.assertIn('--soft-delete-duration=7d', cmd)
        self.assertIn('--default-storage-class=STANDARD', cmd)

    def test_malformed_or_out_of_scope_bucket_rejected(self):
        for name in ['somebody-else-bucket', 'x; echo unsafe', 'project-tests-498508-closedroom-prod', 'A' * 64]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                bootstrap.create_command(name, 'europe-west8')

    def test_dry_run_never_calls_gcloud(self):
        output = io.StringIO()
        with patch.object(bootstrap.subprocess, 'run') as run, contextlib.redirect_stdout(output):
            self.assertEqual(bootstrap.main([]), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['status'], 'dry_run')

    def test_apply_without_cli_fails_closed(self):
        with patch.object(bootstrap.shutil, 'which', return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bootstrap.main(['--apply']), 2)


    def test_failures_classify_without_exposing_account_identity(self):
        cases = [
            ('HTTPError 409: Bucket name already exists', 'NAME_CONFLICT'),
            ('HTTPError 403: caller lacks storage.buckets.create', 'PERMISSION_DENIED'),
            ('ERROR: gcloud: no active account selected', 'AUTHENTICATION'),
            ('HTTPError 412: violates constraint constraints/gcp.resourceLocations', 'ORG_POLICY'),
            ('ERROR: billing account is disabled', 'BILLING'),
            ('ERROR: storage.googleapis.com is disabled', 'API_DISABLED'),
            ('ERROR: unrecognized arguments: --public-access-prevention', 'CLI_FLAGS'),
            ('unexpected failure', 'UNCLASSIFIED'),
        ]
        for raw, expected in cases:
            with self.subTest(expected=expected):
                category, message = bootstrap.classify_create_failure(
                    raw + ' user@example.com secret-token-123'
                )
                self.assertEqual(category, expected)
                self.assertNotIn('user@example.com', message)
                self.assertNotIn('secret-token-123', message)

    def test_apply_prints_sanitized_diagnostic_only_and_returns_failure(self):
        stderr = 'HTTPError 403: storage.buckets.create denied for user@example.com private-token'
        mocked = subprocess.CompletedProcess(args=['gcloud'], returncode=1, stdout='', stderr=stderr)
        output = io.StringIO()
        with patch.object(bootstrap.shutil, 'which', return_value='/fake/gcloud'), \
             patch.object(bootstrap.subprocess, 'run', return_value=mocked) as run, \
             contextlib.redirect_stderr(output):
            self.assertEqual(bootstrap.main(['--apply']), 1)
        self.assertIn('[PERMISSION_DENIED]', output.getvalue())
        self.assertNotIn('user@example.com', output.getvalue())
        self.assertNotIn('private-token', output.getvalue())
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_timeout_never_claims_success(self):
        output = io.StringIO()
        with patch.object(bootstrap.shutil, 'which', return_value='/fake/gcloud'), \
             patch.object(bootstrap.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['gcloud'], 120)), \
             contextlib.redirect_stderr(output):
            self.assertEqual(bootstrap.main(['--apply']), 2)
        self.assertIn('Outcome is unknown', output.getvalue())



if __name__ == '__main__':
    unittest.main()
