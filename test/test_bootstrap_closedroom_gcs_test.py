"""No real GCP calls; validates safe bucket bootstrap behavior."""
from __future__ import annotations

import contextlib
import io
import json
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


if __name__ == '__main__':
    unittest.main()
