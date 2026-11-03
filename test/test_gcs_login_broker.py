"""Deterministic tests for the user-login GCS broker and private request contract."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from scripts import closedroom_gcs_login_broker as broker


SHA = "a" * 40
NONCE = "b" * 32
CONFIG = {"schema": broker.SCHEMA, "source_sha": SHA,
          "source_root": "/tmp/closedroom-test", "uv_path": "/usr/bin/uv"}
REQUEST = {"schema": broker.SCHEMA, "nonce": NONCE, "source_sha": SHA,
           "bucket": broker.BUCKET, "action": "oauth-verify",
           "approved": False, "created_at": 10000}


class LoginBrokerTests(unittest.TestCase):
    def test_synthetic_and_preflight_authorized_without_real_upload(self):
        for action in ("oauth-verify", "preflight"):
            req = dict(REQUEST, action=action)
            broker.validate_request(req, CONFIG, 10000)

    def test_backup_requires_explicit_approval(self):
        broker.validate_request(dict(REQUEST, action="backup", approved=True), CONFIG, 10000)
        for approved in (False, "true", 1, None):
            with self.subTest(approved=approved), self.assertRaises(broker.BrokerRefusal):
                broker.validate_request(dict(REQUEST, action="backup", approved=approved),
                                        CONFIG, 10000)

    def test_untrusted_bucket_sha_nonce_and_expired_request_rejected(self):
        changes = [
            {"bucket": "attacker-bucket"},
            {"source_sha": "c" * 40},
            {"nonce": "n" * 32},
            {"created_at": 10001 + broker.MAX_AGE_SECONDS + 45},
            {"extra": "unknown"},
        ]
        for delta in changes:
            request = dict(REQUEST, **delta)
            when = 10000 if "created_at" not in delta else request["created_at"] + 10
            if "created_at" in delta:
                when = request["created_at"] + broker.MAX_AGE_SECONDS + 1
            with self.subTest(delta=delta), self.assertRaises(broker.BrokerRefusal):
                broker.validate_request(request, CONFIG, when)

    def test_safe_result_drops_secrets_and_rejects_unrecognized_status(self):
        raw = json.dumps({
            "status": "cold_snapshot_uploaded_pending_restore",
            "file_count": 123,
            "recovery_code_stored_in_native_keychain": True,
            "token": "secret-token-must-never-leak",
            "recovery_code": "CR1-hidden",
            "meeting_path": "/private/home/user",
        })
        result = broker._status_from_output(raw, "backup")
        self.assertEqual(result["file_count"], 123)
        self.assertNotIn("secret-token", json.dumps(result))
        self.assertNotIn("CR1-", json.dumps(result))
        self.assertNotIn("/private/", json.dumps(result))
        with self.assertRaises(broker.BrokerRefusal):
            broker._status_from_output(
                '{"status": "cold_snapshot_uploaded_pending_restore"}', "backup",
            )
        with self.assertRaises(broker.BrokerRefusal):
            broker._status_from_output(
                '{"status": "something-else", "token": "secret"}', "backup",
            )

    def test_sanitized_backend_error_code(self):
        with self.assertRaises(broker.BrokerRefusal) as e:
            broker._status_from_output(
                '{"status":"blocked","error_code":"KEYCHAIN_READ_FAILED",'
                '"secret":"do-not-log"}', "preflight",
            )
        self.assertEqual(e.exception.code, "KEYCHAIN_READ_FAILED")
        with self.assertRaises(broker.BrokerRefusal) as e:
            broker._status_from_output(
                '{"status":"failed","error_code":"my /secret/path"}', "oauth-verify",
            )
        self.assertEqual(e.exception.code, "BACKEND_FAILED")

    def test_private_queue_fails_closed_and_executes_only_validated_request(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            os.chmod(base, 0o700)
            for file, data in (("config.json", CONFIG), ("request.json", REQUEST)):
                p = base / file
                p.write_text(json.dumps(data), encoding="utf-8")
                os.chmod(p, 0o600)
            with mock.patch.object(broker.sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1"}), \
                mock.patch.multiple(broker, BROKER_DIR=base, CONFIG=base/"config.json",
                                    REQUEST=base/"request.json", PROCESSING=base/"processing.json",
                                    RESULT=base/"result.json"), \
                mock.patch.object(broker, "run_action", return_value={
                    "status": "oauth_bucket_read_write_verified",
                    "action": "oauth-verify",
                }) as run, \
                mock.patch.object(broker.time, "time", return_value=10000):
                self.assertEqual(broker.poll(), 0)
                self.assertEqual(run.call_count, 1)
                self.assertFalse((base/"request.json").exists())
                self.assertFalse((base/"processing.json").exists())
                result = json.loads((base/"result.json").read_text())
                self.assertEqual(result["nonce"], NONCE)
                self.assertTrue(result["ok"])
                self.assertEqual(broker.poll(), 0)
                self.assertEqual(run.call_count, 1)

    def test_private_json_refuses_symlink_and_world_readable_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            regular = root/"good.json"
            regular.write_text('{"schema":"x"}')
            os.chmod(regular, 0o600)
            self.assertEqual(broker.read_private_json(regular), {"schema":"x"})
            os.chmod(regular, 0o644)
            with self.assertRaises(broker.BrokerRefusal):
                broker.read_private_json(regular)
            link = root/"link.json"
            link.symlink_to(regular)
            with self.assertRaises(broker.BrokerRefusal):
                broker.read_private_json(link)


if __name__ == "__main__":
    unittest.main()
