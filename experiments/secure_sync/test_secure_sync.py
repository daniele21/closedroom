from __future__ import annotations

import base64
import json
import unittest

from secure_sync import (
    MAX_ENVELOPE_BYTES, SecureSyncError, generate_vault_key,
    open_snapshot, seal_snapshot, transcript_snapshot,
)


class SecureSyncTests(unittest.TestCase):
    def setUp(self):
        self.key = generate_vault_key()
        self.snapshot = transcript_snapshot(
            {
                "id": "private-transcript-id", "recording_id": "secret-recording-id",
                "timestamp": "2026-11-19T09:40:00Z", "language": "it",
                "text": "Piano di acquisizione estremamente riservato.",
                "segments": [{"text": "Ciao", "speaker": "Daniele", "start": 0, "end": 1}],
                "analysis": {"summary": "Budget M&A confidenziale"},
                "audio_filename": "/private/sensitive-mic.wav",
                "provider_options": {"api_key": "DO_NOT_EXPORT_KEY"},
            }, title="Board M&A", notes=[{
                "note_id": "note-1", "text": "Decisione segreta", "timestamp": 1.0,
                "revision": 2, "local_path": "/secret/path",
            }],
        )

    def test_roundtrip_across_independent_key_holders(self):
        blob = seal_snapshot(self.snapshot, self.key)
        self.assertEqual(open_snapshot(bytes(blob), bytes(self.key)), self.snapshot)

    def test_no_plaintext_leak_or_raw_metadata(self):
        blob = seal_snapshot(self.snapshot, self.key)
        for phrase in (b"Board M&A", b"Piano di acquisizione", b"Daniele", b"Decisione segreta", b"private-transcript-id"):
            self.assertNotIn(phrase, blob)
        self.assertNotIn("audio_filename", self.snapshot)
        self.assertNotIn("provider_options", self.snapshot)
        self.assertNotIn("local_path", str(self.snapshot))

    def test_wrong_key_and_tampering_fail_closed(self):
        blob = seal_snapshot(self.snapshot, self.key)
        with self.assertRaises(SecureSyncError):
            open_snapshot(blob, generate_vault_key())
        package = json.loads(blob)
        raw = bytearray(base64.b64decode(package["ciphertext"]))
        raw[-1] ^= 1
        package["ciphertext"] = base64.b64encode(raw).decode("ascii")
        with self.assertRaises(SecureSyncError):
            open_snapshot(json.dumps(package).encode(), self.key)
        package = json.loads(blob)
        package["object_id"] = "0" * 32
        with self.assertRaises(SecureSyncError):
            open_snapshot(json.dumps(package).encode(), self.key)

    def test_unique_seals_of_same_snapshot(self):
        self.assertNotEqual(seal_snapshot(self.snapshot, self.key), seal_snapshot(self.snapshot, self.key))

    def test_parser_rejects_duplicate_unknown_and_future_versions(self):
        blob = seal_snapshot(self.snapshot, self.key)
        with self.assertRaises(SecureSyncError):
            open_snapshot(blob[:-1] + b',"version":1}', self.key)
        package = json.loads(blob)
        package["version"] = 2
        with self.assertRaises(SecureSyncError):
            open_snapshot(json.dumps(package).encode(), self.key)
        package = json.loads(blob)
        package["secret"] = "foo"
        with self.assertRaises(SecureSyncError):
            open_snapshot(json.dumps(package).encode(), self.key)

    def test_size_limits_and_input_validations(self):
        with self.assertRaises(SecureSyncError):
            seal_snapshot(self.snapshot, b"bad")
        with self.assertRaises(SecureSyncError):
            open_snapshot(b"x" * (MAX_ENVELOPE_BYTES + 1), self.key)
        with self.assertRaises(SecureSyncError):
            transcript_snapshot({"id": "x", "text": "hello"}, notes=[{"text": "no-id"}])
        with self.assertRaises(SecureSyncError):
            seal_snapshot({**self.snapshot, "text": "x" * (9 * 1024 * 1024)}, self.key)


if __name__ == "__main__":
    unittest.main()
