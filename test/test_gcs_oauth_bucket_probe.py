"""OAuth bucket probe: explicit credentials only, synthetic data, no deletions."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.probe_closedroom_gcs_oauth import (
    BucketProbeFailed, PROBE_PREFIX, TEST_BUCKET, TEST_PROJECT,
    main, verify_bucket_oauth,
)


class FakeOAuth:
    def __init__(self):
        self.credential_calls = 0
        self.secret = object()
    def credentials(self):
        self.credential_calls += 1
        return self.secret


class FakeBucket:
    name = TEST_BUCKET
    def __init__(self, *, corrupted=False, denied=False, unknown_generation=False):
        self.objects = {}
        self.uploads = []
        self.corrupted = corrupted
        self.denied = denied
        self.unknown_generation = unknown_generation

    def blob(self, object_name, generation=None):
        bucket = self
        class Blob:
            def __init__(self):
                self.generation = generation
            def upload_from_string(self, data, **kwargs):
                if bucket.denied:
                    raise RuntimeError("SDK secret token test-sentinel")
                assert kwargs["if_generation_match"] == 0
                assert kwargs["checksum"] == "auto"
                assert kwargs["content_type"] == "application/octet-stream"
                assert object_name.startswith(PROBE_PREFIX)
                assert object_name not in bucket.objects
                bucket.objects[object_name] = data
                bucket.uploads.append(object_name)
                self.generation = None if bucket.unknown_generation else 23
            def download_as_bytes(self, **kwargs):
                assert generation == 23
                assert kwargs["if_generation_match"] == 23
                assert kwargs["checksum"] == "auto"
                return bucket.objects[object_name] + (b"x" if bucket.corrupted else b"")
        return Blob()


class FakeClient:
    def __init__(self, bucket):
        self.bucket_instance = bucket
        self.project = None
        self.credentials = None
    def factory(self, *, project, credentials):
        self.project = project
        self.credentials = credentials
        return self
    def bucket(self, name):
        assert name == TEST_BUCKET
        return self.bucket_instance


class OAuthBucketProbeTests(unittest.TestCase):
    def test_synthetic_only_create_read_uses_explicit_credentials(self):
        oauth = FakeOAuth()
        bucket = FakeBucket()
        client = FakeClient(bucket)
        result = verify_bucket_oauth(oauth, client_factory=client.factory, fixture=b"a" * 64)
        self.assertEqual(oauth.credential_calls, 1)
        self.assertIs(client.credentials, oauth.secret)
        self.assertEqual(client.project, TEST_PROJECT)
        self.assertEqual(result["status"], "oauth_bucket_read_write_verified")
        self.assertEqual(result["synthetic_bytes"], 64)
        self.assertTrue(result["remote_object_retained"])
        self.assertFalse(result["meeting_data_transferred"])
        self.assertEqual(len(bucket.uploads), 1)
        self.assertEqual(bucket.objects[bucket.uploads[0]], b"a" * 64)

    def test_no_implicit_use_of_adc_when_keychain_unavailable(self):
        class Unavailable:
            def credentials(self):
                raise RuntimeError("No Keychain credentials")
        bucket = FakeBucket()
        client = FakeClient(bucket)
        with self.assertRaises(RuntimeError):
            verify_bucket_oauth(Unavailable(), client_factory=client.factory)
        self.assertIsNone(client.credentials)
        self.assertFalse(bucket.objects)

    def test_integrity_tampering_fails_closed_without_delete(self):
        bucket = FakeBucket(corrupted=True)
        with self.assertRaises(BucketProbeFailed) as caught:
            verify_bucket_oauth(FakeOAuth(), client_factory=FakeClient(bucket).factory)
        self.assertEqual(caught.exception.code, "GCS_SYNTHETIC_INTEGRITY_MISMATCH")
        self.assertEqual(len(bucket.objects), 1)

    def test_generation_must_be_pinned(self):
        bucket = FakeBucket(unknown_generation=True)
        with self.assertRaises(BucketProbeFailed) as caught:
            verify_bucket_oauth(FakeOAuth(), client_factory=FakeClient(bucket).factory)
        self.assertEqual(caught.exception.code, "GCS_GENERATION_UNVERIFIED")

    def test_sdk_exceptions_are_sanitized(self):
        bucket = FakeBucket(denied=True)
        with self.assertRaises(BucketProbeFailed) as caught:
            verify_bucket_oauth(FakeOAuth(), client_factory=FakeClient(bucket).factory)
        self.assertEqual(caught.exception.code, "GCS_NETWORK_OR_SDK_FAILURE")
        self.assertNotIn("test-sentinel", str(caught.exception))

    def test_verify_bucket_requires_explicit_apply_before_auth(self):
        json_doc = {"installed": {
            "client_id": "12345678-test.apps.googleusercontent.com",
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "oauth.json"
            path.write_text(json.dumps(json_doc))
            path.chmod(0o600)
            error = io.StringIO()
            with (
                patch("scripts.probe_closedroom_gcs_oauth.GCSDesktopOAuth") as constructor,
                contextlib.redirect_stderr(error),
            ):
                rc = main(["verify-bucket", "--client-json", str(path)])
            self.assertEqual(rc, 2)
            constructor.assert_called_once()
            self.assertEqual(json.loads(error.getvalue())["error_code"], "GCS_EXPLICIT_APPLY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
