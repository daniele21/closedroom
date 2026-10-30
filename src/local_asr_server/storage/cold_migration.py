"""One-shot *explicit* encrypted GCS migration, distinct from cloud-mode backup.

No implicit uploads, gcloud ADC, meeting-data telemetry, merging or deletion.
Cold-snapshot all files in configured recordings/transcriptions roots plus
SQLite online backup. Transfer a *non-secret receipt*, encrypted recovery
envelope and (separately) one-time code to the other Mac. Restore into a new
isolated local data directory and optionally activate only after review.

Temporary space ~2x source on backup and ~3x on restore; deliberately refuse
without free space. This is not resumable; a failed upload may leave an
unreferenced encrypted object, never the loss of an original.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tarfile
import tempfile
from typing import Any
from urllib.parse import quote

from local_asr_server.storage.config import (
    migration_source_roots, DEFAULT_MIGRATION_SETTINGS, TEST_PROJECT, TEST_BUCKET,
)
from local_asr_server.storage.gcs_oauth import read_desktop_config

from local_asr_server.storage.gcs_archive import EncryptedAsset, GCSArchiveTransport
from local_asr_server.storage.gcs_oauth import GCSDesktopOAuth
from local_asr_server.storage.key_recovery import (
    ArchiveKeyVault, create_recovery_envelope, load_recovery_file, save_recovery_file,
)
DEFAULT_SETTINGS = DEFAULT_MIGRATION_SETTINGS

MIGRATION_FORMAT = "closedroom-cold-snapshot-v1"
DEFAULT_CATALOG = Path.home() / "Library" / "Application Support" / "ClosedRoom" / "closedroom.db"
REQUIRED = {"recordings", "transcriptions", "catalog"}
MARGIN_BYTES = 512 * 1024 * 1024


class MigrationBlocked(RuntimeError):
    """Sanitized static refusal reason. Never include private paths or identities."""


def _regular(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        raise MigrationBlocked("SOURCE_MISSING_OR_UNREADABLE") from None
    if not stat.S_ISREG(info.st_mode):
        raise MigrationBlocked("SOURCE_NOT_REGULAR")
    return info


def _root(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError:
        raise MigrationBlocked("SOURCE_ROOT_MISSING") from None
    if not stat.S_ISDIR(mode):
        raise MigrationBlocked("SOURCE_ROOT_NOT_DIRECTORY")


def _private_json(path: Path) -> dict[str, Any]:
    info = _regular(path)
    if info.st_mode & 0o077 or info.st_size > 16384:
        raise MigrationBlocked("PRIVATE_JSON_PERMISSIONS_OR_SIZE")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (OSError, UnicodeError, ValueError):
        raise MigrationBlocked("PRIVATE_JSON_INVALID") from None


def _save_private_json(path: Path, content: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise MigrationBlocked("PRIVATE_OUTPUT_ALREADY_EXISTS_OR_PARENT_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(content, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _assert_no_sqlite_sidecars(db: Path) -> None:
    for ext in ("-wal", "-shm", "-journal"):
        p = Path(str(db) + ext)
        if p.exists() or p.is_symlink():
            raise MigrationBlocked("CATALOG_HAS_LIVE_SIDECAR_CLOSE_APP")


def _sqlite_backup(source: Path, destination: Path) -> None:
    before = _regular(source)
    _assert_no_sqlite_sidecars(source)
    try:
        # An ordinary SQLite mode=ro connection can CREATE -wal/-shm files
        # merely by opening an idle WAL-mode catalog, spuriously triggering
        # the post-backup change guard and modifying the source directory.
        # immutable=1 is safe ONLY with the prechecked absence of WAL,
        # rollback journals and SHM, and an explicitly stopped application.
        # The post-backup stat + sidecar check below still rejects changes.
        uri = "file:" + quote(str(source.absolute()), safe="/") + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise MigrationBlocked("CATALOG_INTEGRITY_FAILED")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {"recordings", "transcriptions"} <= tables:
                raise MigrationBlocked("CATALOG_SCHEMA_INCOMPATIBLE")
            # sqlite3.Connection.__exit__ commits/rolls back but does NOT
            # close. Closing both connections ensures any destination WAL
            # pages are checkpointed before the file is added to the tar.
            with closing(sqlite3.connect(destination)) as dest:
                db.backup(dest, pages=256, sleep=0.05)
        if any(Path(str(destination) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
            raise MigrationBlocked("CATALOG_SNAPSHOT_SIDECAR_REMAINS")
        with closing(sqlite3.connect(
            "file:" + quote(str(destination.absolute()), safe="/") + "?mode=ro&immutable=1",
            uri=True,
        )) as verified:
            if verified.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise MigrationBlocked("CATALOG_SNAPSHOT_INVALID")
    except MigrationBlocked:
        raise
    except sqlite3.Error:
        raise MigrationBlocked("CATALOG_SNAPSHOT_FAILED") from None
    after = _regular(source)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or any(Path(str(source) + ext).exists() or
             Path(str(source) + ext).is_symlink()
             for ext in ("-wal", "-shm", "-journal")):
        raise MigrationBlocked("CATALOG_CHANGED_DURING_SNAPSHOT")


def _entries(root: Path, prefix: str) -> list[tuple[Path, str, os.stat_result]]:
    _root(root)
    result = []
    for base, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        basepath = Path(base)
        for d in directories:
            if (basepath / d).is_symlink():
                raise MigrationBlocked("SOURCE_SYMLINK_OR_SPECIAL_DIRECTORY")
        for filename in filenames:
            src = basepath / filename
            info = _regular(src)
            member = prefix + "/" + src.relative_to(root).as_posix()
            result.append((src, member, info))
    result.sort(key=lambda x: x[1])
    return result


def prepare_snapshot(
    recordings: Path, transcriptions: Path, catalog: Path, archive: Path,
    work_dir: Path,
) -> dict[str, Any]:
    """Explicit isolated tar of original files and a *consistent* SQLite copy."""
    _root(recordings)
    _root(transcriptions)
    _root(work_dir)
    if any(work_dir == x or x in work_dir.parents for x in (recordings, transcriptions)):
        raise MigrationBlocked("WORK_DIRECTORY_INSIDE_SOURCE")
    if archive.exists() or archive.is_symlink():
        raise MigrationBlocked("SNAPSHOT_OUTPUT_EXISTS")
    items = _entries(recordings, "recordings") + _entries(transcriptions, "transcriptions")
    with tempfile.TemporaryDirectory(prefix=".closedroom-snapshot-db-", dir=work_dir) as db_work:
        catalog_copy = Path(db_work) / "closedroom.db"
        _sqlite_backup(catalog, catalog_copy)
        items.append((catalog_copy, "catalog/closedroom.db", _regular(catalog_copy)))
        source_bytes = sum(x[2].st_size for x in items)
        if shutil.disk_usage(work_dir).free < source_bytes * 2 + MARGIN_BYTES:
            raise MigrationBlocked("INSUFFICIENT_TEMP_DISK_FOR_BACKUP")
        counts = {
            "recordings_files": sum(x[1].startswith("recordings/") for x in items),
            "transcriptions_files": sum(x[1].startswith("transcriptions/") for x in items),
        }
        try:
            with tarfile.open(archive, mode="x") as tar:
                for source, member, before in items:
                    current = _regular(source)
                    if (current.st_dev, current.st_ino, current.st_size,
                        current.st_mtime_ns) != (
                        before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns
                    ):
                        raise MigrationBlocked("SOURCE_CHANGED_DURING_SNAPSHOT")
                    info = tarfile.TarInfo(member)
                    info.size = before.st_size
                    info.mode = 0o600
                    info.mtime = 0
                    with source.open("rb") as stream:
                        tar.addfile(info, stream)
                    after = _regular(source)
                    if (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns) != (
                        before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns
                    ):
                        raise MigrationBlocked("SOURCE_CHANGED_DURING_SNAPSHOT")
            # Catch newly added or removed source files while tar was built:
            # a valid partial snapshot is not a complete backup.
            again = _entries(recordings, "recordings") + _entries(
                transcriptions, "transcriptions"
            )
            original = {
                name: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                for _, name, info in items
                if name != "catalog/closedroom.db"
            }
            latest = {
                name: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                for _, name, info in again
            }
            if latest != original:
                raise MigrationBlocked("SOURCE_TREE_CHANGED_DURING_SNAPSHOT")
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
    return {"schema_version": 1, "file_count": len(items), **counts}


def _gcs_transport(client_json: Path) -> GCSArchiveTransport:
    from google.cloud import storage
    client_id, client_secret = read_desktop_config(client_json)
    credentials = GCSDesktopOAuth(client_id=client_id, client_secret=client_secret).credentials()
    client = storage.Client(project=TEST_PROJECT, credentials=credentials)
    return GCSArchiveTransport(client.bucket(TEST_BUCKET), bucket_name=TEST_BUCKET)


def upload_snapshot(
    *, client_json: Path, settings_file: Path, catalog: Path, work_dir: Path,
    receipt: Path, recovery_file: Path, transport: GCSArchiveTransport | None = None,
    vault: ArchiveKeyVault | None = None,
) -> tuple[dict[str, Any], str]:
    if receipt.exists() or recovery_file.exists():
        raise MigrationBlocked("OUTPUT_ALREADY_EXISTS")
    try:
        recordings, transcriptions = migration_source_roots(settings_file)
    except ValueError as exc:
        raise MigrationBlocked(str(exc)) from None
    _root(work_dir)
    vault = vault or ArchiveKeyVault()
    key = vault.load()
    if key is None:
        key = os.urandom(32)
        vault.store_if_absent(key)
    with tempfile.TemporaryDirectory(prefix=".closedroom-migrate-", dir=work_dir) as tmp:
        tar_path = Path(tmp) / "snapshot.tar"
        summary = prepare_snapshot(recordings, transcriptions, catalog, tar_path, work_dir)
        envelope, recovery_code = create_recovery_envelope(key)
        save_recovery_file(recovery_file, envelope)
        transport = transport or _gcs_transport(client_json)
        asset = transport.upload_encrypted(tar_path, work_dir, key, kind="catalog")
        receipt_data = {
            "format": MIGRATION_FORMAT,
            "asset": asdict(asset),
            "summary": summary,
            "source_catalog": "explicit_application_support_candidate",
            "verified_on_second_mac": False,
        }
        _save_private_json(receipt, receipt_data)
    return {"status": "cold_snapshot_uploaded_pending_restore",
            "file_count": summary["file_count"],
            "bucket": TEST_BUCKET, "encrypted": True, "originals_deleted": False,
            "receipt_created": True, "recovery_file_created": True,
            "second_mac_restore_verified": False}, recovery_code


def _extract_staged(archive: Path, staging: Path, expected_files: int) -> int:
    count = 0
    with tarfile.open(archive, mode="r:") as tar:
        for member in tar:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or
                len(name.parts) < 2 or ".." in name.parts or
                name.parts[0] not in REQUIRED or
                (name.parts[0] == "catalog" and member.name != "catalog/closedroom.db")):
                raise MigrationBlocked("ARCHIVE_UNSAFE_MEMBER")
            dest = staging.joinpath(*name.parts)
            if not dest.resolve().is_relative_to(staging.resolve()):
                raise MigrationBlocked("ARCHIVE_UNSAFE_MEMBER")
            dest.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(dest, flags, 0o600)
            try:
                inp = tar.extractfile(member)
                if inp is None:
                    raise MigrationBlocked("ARCHIVE_INVALID_FILE")
                with os.fdopen(fd, "wb") as out:
                    shutil.copyfileobj(inp, out, length=1024 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            count += 1
    if count != expected_files:
        raise MigrationBlocked("SNAPSHOT_FILE_COUNT_MISMATCH")
    if not (staging / "catalog/closedroom.db").is_file():
        raise MigrationBlocked("SNAPSHOT_CATALOG_MISSING")
    return count


def restore_snapshot(
    *, client_json: Path, receipt: Path, recovery_file: Path, recovery_code: str,
    target: Path, work_dir: Path | None = None,
    transport: GCSArchiveTransport | None = None, vault: ArchiveKeyVault | None = None,
) -> dict[str, Any]:
    data = _private_json(receipt)
    if data.get("format") != MIGRATION_FORMAT or not isinstance(data.get("asset"), dict):
        raise MigrationBlocked("RECEIPT_UNSUPPORTED")
    try:
        asset = EncryptedAsset(**data["asset"])
        asset.validate()
        expected = int(data["summary"]["file_count"])
        if expected < 1 or expected > 1_000_000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise MigrationBlocked("RECEIPT_INVALID") from None
    if asset.bucket != TEST_BUCKET or target.exists() or target.is_symlink():
        raise MigrationBlocked("TARGET_EXISTS_OR_BUCKET_MISMATCH")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise MigrationBlocked("TARGET_PARENT_INVALID")
    work_dir = work_dir or target.parent
    _root(work_dir)
    if work_dir.stat().st_dev != target.parent.stat().st_dev:
        raise MigrationBlocked("TEMP_AND_TARGET_DIFFERENT_VOLUME")
    if shutil.disk_usage(work_dir).free < asset.plaintext_bytes * 3 + MARGIN_BYTES:
        raise MigrationBlocked("INSUFFICIENT_TEMP_DISK_FOR_RESTORE")
    key = (vault or ArchiveKeyVault()).import_recovery(
        load_recovery_file(recovery_file), recovery_code
    )
    transport = transport or _gcs_transport(client_json)
    with tempfile.TemporaryDirectory(prefix=".closedroom-restore-", dir=work_dir) as temp:
        temp_path = Path(temp)
        archive = temp_path / "snapshot.tar"
        transport.restore_encrypted(asset, archive, temp_path, key)
        staged = temp_path / "dataset"
        staged.mkdir(mode=0o700)
        file_count = _extract_staged(archive, staged, expected)
        # Atomic publication only on the SAME volume; never overwrite data.
        if target.exists() or target.is_symlink():
            raise MigrationBlocked("TARGET_ALREADY_EXISTS")
        os.rename(staged, target)
    return {"status": "cold_snapshot_restored_to_isolated_directory",
            "restored_files": file_count,
            "local_target_created": True, "activated_in_app": False,
            "existing_app_data_modified": False, "cloud_data_deleted": False}


def activate_import(target: Path, settings_file: Path) -> dict[str, Any]:
    """Explicitly switch app to imported *isolated* roots, preserving prior config."""
    for part in ("recordings", "transcriptions"):
        _root(target / part)
    _regular(target / "catalog/closedroom.db")
    if not settings_file.parent.is_dir() or settings_file.parent.is_symlink():
        raise MigrationBlocked("SETTINGS_PARENT_INVALID")
    if settings_file.exists():
        _regular(settings_file)
        try:
            current = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise MigrationBlocked("SETTINGS_INVALID") from None
        if not isinstance(current, dict):
            raise MigrationBlocked("SETTINGS_INVALID")
    else:
        current = {}
    prior = dict(current)
    current.update({
        "recordings_dir": str((target / "recordings").resolve()),
        "transcriptions_dir": str((target / "transcriptions").resolve()),
        "catalog_db_path": str((target / "catalog/closedroom.db").resolve()),
        "storage_mode": "local",
    })
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=".closedroom-settings-",
                                     dir=settings_file.parent, delete=False) as out:
        temp = Path(out.name)
        try:
            os.fchmod(out.fileno(), 0o600)
            json.dump(current, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    # Never silently overwrite a prior settings file without a local backup.
    try:
        if settings_file.exists():
            backup = settings_file.with_name(
                "settings.pre-migration-" + os.urandom(8).hex() + ".json"
            )
            _save_private_json(backup, prior)
        os.replace(temp, settings_file)
    finally:
        temp.unlink(missing_ok=True)
    return {"status": "isolated_import_activated_local_only",
            "prior_settings_backup_created": bool(prior),
            "gcs_runtime_enabled": False, "existing_meeting_files_deleted": False}
