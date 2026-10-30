"""Opt-in encrypted GCS object transport, not a meeting persistence owner.

Never initialize cloud credentials, read app settings or run from a recording
callback. RecordingStore will own policy, journal, recovery and cache leases.
The caller provides a verified bucket client and an unlocked 32-byte key.
This module never evicts local media, deletes remote objects, logs content or
writes a persisted archive manifest by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Any
import uuid

MAGIC = b"CRGCS-A1"  # eight-byte versioned envelope marker
NONCE_LENGTH = 12
TAG_LENGTH = 16
BLOCK_BYTES = 1024 * 1024
KINDS = frozenset({"audio", "transcript", "catalog", "visual"})
OBJECT_PATTERN = re.compile(r"closedroom-archive/[0-9a-f]{32}/(audio|transcript|catalog|visual)-[0-9a-f]{32}\.crenc\Z")


class ArchiveIntegrityError(ValueError):
    """An encrypted object failed authentication or the expected digests."""


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError("cryptography is required for encrypted GCS storage") from exc
    return Cipher, algorithms, modes


def _check_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("Archive key must be 32 bytes, supplied by an external key owner")


def new_object_name(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError("Unsupported archive object kind")
    return f"closedroom-archive/{uuid.uuid4().hex}/{kind}-{uuid.uuid4().hex}.crenc"


def _check_object_name(name: str) -> None:
    if not isinstance(name, str) or not OBJECT_PATTERN.fullmatch(name):
        raise ValueError("Invalid opaque archive object identifier")


@dataclass(frozen=True)
class EncryptedAsset:
    """Value returned to the canonical store; does not contain secrets."""
    bucket: str
    object_name: str
    generation: int
    plaintext_sha256: str
    ciphertext_sha256: str
    plaintext_bytes: int
    ciphertext_bytes: int
    format_version: int = 1

    def validate(self) -> None:
        _check_object_name(self.object_name)
        if not self.bucket or self.generation < 1 or self.format_version != 1:
            raise ValueError("Invalid archive reference")
        if self.plaintext_bytes < 0 or self.ciphertext_bytes < 0:
            raise ValueError("Invalid archive file sizes")
        for digest in (self.plaintext_sha256, self.ciphertext_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid archive digest")


@dataclass(frozen=True)
class _Prepared:
    plaintext_sha256: str
    ciphertext_sha256: str
    plaintext_bytes: int
    ciphertext_bytes: int


def _encrypt(source: Path, encrypted: Path, key: bytes) -> _Prepared:
    """Bounded streaming AES-256-GCM; refuse changing/nonregular source."""
    _check_key(key)
    previous = source.lstat()
    if not stat.S_ISREG(previous.st_mode) or source.name.endswith('.part'):
        raise ValueError("Only finalized regular local files may be archived")
    Cipher, algorithms, modes = _aes()
    nonce = secrets.token_bytes(NONCE_LENGTH)
    enc = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    content_hash = hashlib.sha256()
    remote_hash = hashlib.sha256()
    n_plain = 0
    n_encrypted = 0
    with source.open('rb') as incoming, encrypted.open('xb') as outgoing:
        header = MAGIC + nonce
        outgoing.write(header)
        remote_hash.update(header)
        n_encrypted += len(header)
        while chunk := incoming.read(BLOCK_BYTES):
            content_hash.update(chunk)
            n_plain += len(chunk)
            data = enc.update(chunk)
            outgoing.write(data)
            remote_hash.update(data)
            n_encrypted += len(data)
        final = enc.finalize() + enc.tag
        outgoing.write(final)
        remote_hash.update(final)
        n_encrypted += len(final)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    afterward = source.lstat()
    if (previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_size) != (
        afterward.st_dev, afterward.st_ino, afterward.st_mtime_ns, afterward.st_size
    ):
        raise ValueError("Source changed during encryption; do not archive")
    return _Prepared(content_hash.hexdigest(), remote_hash.hexdigest(), n_plain, n_encrypted)


def _restore(ciphertext: Path, destination: Path, key: bytes, asset: EncryptedAsset) -> None:
    """Authenticate entire object before publishing plaintext; no overwrite."""
    _check_key(key)
    asset.validate()
    if ciphertext.is_symlink() or not ciphertext.is_file():
        raise ValueError("Encrypted object must be a regular local file")
    expected = asset.ciphertext_bytes
    if expected < len(MAGIC) + NONCE_LENGTH + TAG_LENGTH or ciphertext.stat().st_size != expected:
        raise ArchiveIntegrityError("Encrypted object size mismatch")
    actual_cipher_hash = hashlib.sha256()
    with ciphertext.open('rb') as inp:
        while chunk := inp.read(BLOCK_BYTES):
            actual_cipher_hash.update(chunk)
    if actual_cipher_hash.hexdigest() != asset.ciphertext_sha256:
        raise ArchiveIntegrityError("Encrypted object checksum mismatch")
    Cipher, algorithms, modes = _aes()
    with ciphertext.open('rb') as incoming:
        header = incoming.read(len(MAGIC) + NONCE_LENGTH)
        if not header.startswith(MAGIC):
            raise ArchiveIntegrityError("Unsupported encrypted object version")
        nonce = header[len(MAGIC):]
        incoming.seek(-TAG_LENGTH, os.SEEK_END)
        tag = incoming.read(TAG_LENGTH)
        incoming.seek(len(header))
        dec = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        size = expected - len(header) - TAG_LENGTH
        content_hash = hashlib.sha256()
        bytes_written = 0
        fd, candidate = tempfile.mkstemp(prefix='.closedroom-restore-', suffix='.tmp', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                while size:
                    chunk = incoming.read(min(BLOCK_BYTES, size))
                    if not chunk:
                        raise ArchiveIntegrityError("Truncated encrypted object")
                    size -= len(chunk)
                    plain = dec.update(chunk)
                    output.write(plain)
                    content_hash.update(plain)
                    bytes_written += len(plain)
                try:
                    dec.finalize()
                except Exception:
                    raise ArchiveIntegrityError("Encrypted object authentication failed") from None
                output.flush()
                os.fsync(output.fileno())
            if bytes_written != asset.plaintext_bytes or content_hash.hexdigest() != asset.plaintext_sha256:
                raise ArchiveIntegrityError("Restored plaintext integrity mismatch")
            # Exclusive link avoids a time-of-check/time-of-use overwrite window.
            os.link(candidate, destination)
        finally:
            os.unlink(candidate)


class GCSArchiveTransport:
    """Cloud object transport only. Bucket must come from explicit auth/consent.

    The bucket argument is an injected google-cloud-storage Bucket object or
    compatible fake. Never call storage.Client()/ADC implicitly in ClosedRoom.
    """
    def __init__(self, bucket: Any, *, bucket_name: str):
        if not bucket_name or getattr(bucket, 'name', None) != bucket_name:
            raise ValueError("Configured and authenticated bucket mismatch")
        self.bucket = bucket
        self.bucket_name = bucket_name

    def upload_encrypted(self, source: Path, work_dir: Path, key: bytes, *, kind: str) -> EncryptedAsset:
        _check_key(key)
        if not work_dir.is_dir() or work_dir.is_symlink():
            raise ValueError("Private staging directory required")
        object_name = new_object_name(kind)
        with tempfile.TemporaryDirectory(prefix='closedroom-gcs-', dir=work_dir) as temporary:
            encrypted = Path(temporary) / 'encrypted.crenc'
            prepared = _encrypt(source, encrypted, key)
            blob = self.bucket.blob(object_name)
            # Generation=0 is create-only; CRC/MD5 is an independent transport check.
            blob.upload_from_filename(str(encrypted), content_type='application/octet-stream',
                                      if_generation_match=0, checksum='auto', timeout=120)
            generation = int(blob.generation or 0)
            asset = EncryptedAsset(self.bucket_name, object_name, generation,
                                   prepared.plaintext_sha256, prepared.ciphertext_sha256,
                                   prepared.plaintext_bytes, prepared.ciphertext_bytes)
            asset.validate()
            return asset

    def restore_encrypted(self, asset: EncryptedAsset, destination: Path, work_dir: Path, key: bytes) -> None:
        _check_key(key)
        asset.validate()
        if asset.bucket != self.bucket_name:
            raise ValueError("Archive reference points to another bucket")
        if not work_dir.is_dir() or work_dir.is_symlink():
            raise ValueError("Private staging directory required")
        with tempfile.TemporaryDirectory(prefix='closedroom-gcs-', dir=work_dir) as temporary:
            ciphertext = Path(temporary) / 'download.crenc'
            blob = self.bucket.blob(asset.object_name, generation=asset.generation)
            blob.download_to_filename(str(ciphertext), if_generation_match=asset.generation,
                                      checksum='auto', timeout=120)
            _restore(ciphertext, destination, key, asset)
