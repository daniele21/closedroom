"""No cloud credentials, no user recording files: injected GCS fake fixtures."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from local_asr_server.storage.gcs_archive import (  # noqa: E402
    GCSArchiveTransport, ArchiveIntegrityError, EncryptedAsset, new_object_name,
)


class FakeBucket:
    name = 'test-closedroom-bucket'
    def __init__(self):
        self.stored = {}
        self.calls = []

    def blob(self, name, generation=None):
        parent = self
        class FakeBlob:
            def __init__(self):
                self.generation = generation
            def upload_from_filename(self, filename, **opts):
                assert opts['if_generation_match'] == 0
                assert opts['checksum'] == 'auto'
                assert name not in parent.stored
                parent.calls.append(('upload', name))
                parent.stored[name] = Path(filename).read_bytes()
                self.generation = 12345
            def download_to_filename(self, filename, **opts):
                assert generation == opts['if_generation_match'] == 12345
                parent.calls.append(('download', name))
                Path(filename).write_bytes(parent.stored[name])
        return FakeBlob()


class ArchiveTransportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.key = bytes(range(32))
        self.bucket = FakeBucket()
        self.transport = GCSArchiveTransport(self.bucket, bucket_name=self.bucket.name)

    def test_streaming_roundtrip_and_no_source_removal(self):
        source = self.root / 'mic.wav'
        source.write_bytes(os.urandom(2 * 1024 * 1024 + 257))
        original = source.read_bytes()
        asset = self.transport.upload_encrypted(source, self.root, self.key, kind='audio')
        self.assertEqual(asset.format_version, 1)
        self.assertEqual(asset.plaintext_bytes, len(original))
        self.assertNotEqual(self.bucket.stored[asset.object_name], original)
        self.assertTrue(source.exists())
        target = self.root / 'restored.wav'
        self.transport.restore_encrypted(asset, target, self.root, self.key)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['mic.wav','restored.wav'])
        self.assertEqual(len(self.bucket.calls), 2)

    def test_wrong_key_and_tampering_fail_without_plaintext(self):
        source = self.root / 'system.wav'
        source.write_bytes(os.urandom(1024))
        asset = self.transport.upload_encrypted(source, self.root, self.key, kind='audio')
        target = self.root / 'recovered.wav'
        with self.assertRaises(ArchiveIntegrityError):
            self.transport.restore_encrypted(asset, target, self.root, b'z'*32)
        self.assertFalse(target.exists())
        blob = bytearray(self.bucket.stored[asset.object_name]); blob[40] ^= 1
        self.bucket.stored[asset.object_name] = bytes(blob)
        with self.assertRaises(ArchiveIntegrityError):
            self.transport.restore_encrypted(asset, target, self.root, self.key)
        self.assertFalse(target.exists())

    def test_refuses_to_overwrite_existing_destination(self):
        source = self.root / 'mic.wav'; source.write_bytes(b'hello')
        asset = self.transport.upload_encrypted(source, self.root, self.key, kind='audio')
        target = self.root / 'target.wav'; target.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            self.transport.restore_encrypted(asset, target, self.root, self.key)
        self.assertEqual(target.read_bytes(), b'existing')

    def test_rejects_wrong_bucket_forged_name_and_bad_key(self):
        source = self.root / 'audio.wav'; source.write_bytes(b'ok')
        with self.assertRaises(ValueError):
            self.transport.upload_encrypted(source, self.root, b'123', kind='audio')
        with self.assertRaises(ValueError):
            new_object_name('../../audio')
        with self.assertRaises(ValueError):
            GCSArchiveTransport(self.bucket, bucket_name='another')
        asset = self.transport.upload_encrypted(source, self.root, self.key, kind='audio')
        forged = EncryptedAsset('another', asset.object_name, asset.generation, asset.plaintext_sha256,
                                asset.ciphertext_sha256, asset.plaintext_bytes, asset.ciphertext_bytes)
        with self.assertRaises(ValueError):
            self.transport.restore_encrypted(forged, self.root / 'bad.wav', self.root, self.key)
        forged2 = EncryptedAsset(asset.bucket, '../private', asset.generation, asset.plaintext_sha256,
                                 asset.ciphertext_sha256, asset.plaintext_bytes, asset.ciphertext_bytes)
        with self.assertRaises(ValueError):
            self.transport.restore_encrypted(forged2, self.root / 'bad.wav', self.root, self.key)

    def test_refuses_in_progress_track_and_symlink(self):
        part = self.root / 'mic.wav.part'; part.write_bytes(b'partial')
        with self.assertRaises(ValueError):
            self.transport.upload_encrypted(part, self.root, self.key, kind='audio')
        linked = self.root / 'linked.wav'; linked.symlink_to(part)
        with self.assertRaises(ValueError):
            self.transport.upload_encrypted(linked, self.root, self.key, kind='audio')


if __name__ == '__main__':
    unittest.main()
