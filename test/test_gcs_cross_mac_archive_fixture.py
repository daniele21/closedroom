"""Synthetic cross-Mac archive restoration: new Keychain + encrypted GCS object."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from local_asr_server.storage.gcs_archive import GCSArchiveTransport
from local_asr_server.storage.key_recovery import (
    ArchiveKeyVault, create_recovery_envelope, load_recovery_file,
    save_recovery_file,
)


class FakeMacKeychain:
    def __init__(self):
        self.secrets = {}
    def get_password(self, service, account):
        return self.secrets.get((service, account))
    def set_password(self, service, account, password):
        self.secrets[(service, account)] = password


class FixtureBucket:
    name = "synthetic-closedroom-bucket"
    def __init__(self):
        self.objects = {}
    def blob(self, name, generation=None):
        bucket = self
        class Object:
            def __init__(self):
                self.generation = generation
            def upload_from_filename(self, filename, **kwargs):
                if kwargs["if_generation_match"] != 0 or name in bucket.objects:
                    raise AssertionError("Unsafe overwrite")
                bucket.objects[name] = Path(filename).read_bytes()
                self.generation = 9
            def download_to_filename(self, filename, **kwargs):
                if generation != 9 or kwargs["if_generation_match"] != 9:
                    raise AssertionError("Generation not pinned")
                Path(filename).write_bytes(bucket.objects[name])
        return Object()


class CrossMacArchiveFixtureTests(unittest.TestCase):
    def test_encrypted_audio_restored_with_portable_key_without_original_mac(self):
        first_mac = ArchiveKeyVault(FakeMacKeychain(), fixture=True)
        second_mac = ArchiveKeyVault(FakeMacKeychain(), fixture=True)
        key = os.urandom(32)
        first_mac.store_if_absent(key)
        bucket = FixtureBucket()
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            source = root / "mic.wav"
            original = os.urandom(2 * 1024 * 1024 + 3)
            source.write_bytes(original)
            transport = GCSArchiveTransport(bucket, bucket_name=bucket.name)
            asset = transport.upload_encrypted(source, root, first_mac.load(), kind="audio")
            envelope, code = create_recovery_envelope(first_mac.load())
            recovery = root / "recovery.json"
            save_recovery_file(recovery, envelope)

            # A different Mac has neither the source recording nor Keychain key.
            source.unlink()
            self.assertIsNone(second_mac.load())
            second_mac.import_recovery(load_recovery_file(recovery), code)
            destination = root / "restored.wav"
            transport.restore_encrypted(asset, destination, root, second_mac.load())
            self.assertEqual(destination.read_bytes(), original)
            self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
