#!/usr/bin/env python3
"""Read-only, privacy-safe size inventory of ClosedRoom user meeting data.

Reads only settings.json keys to discover roots; meeting files are *stat*ed,
never opened. JSON output contains aggregates, never private paths or IDs.
The estimate of allocated bytes is not APFS clone-aware or a proof of reclaimability.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import stat
import sys

DEFAULT_RECORDINGS = Path('~/ClosedRoom/Recordings/ClosedRoom').expanduser()
DEFAULT_TRANSCRIPTS = Path('~/ClosedRoom/Transcriptions/ClosedRoom').expanduser()
DEFAULT_CATALOG = Path('~/ClosedRoom/closedroom.db').expanduser()
DEFAULT_SETTINGS = Path('~/Library/Application Support/ClosedRoom/settings.json').expanduser()
AUDIO_EXTENSIONS = frozenset({'.wav', '.m4a', '.mp3', '.mp4', '.webm', '.ogg', '.flac', '.aiff', '.aac'})
VISUAL_EXTENSIONS = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.heic', '.tiff'})


def classify(relative: Path, scope: str) -> str:
    """Classify conservatively, including temporary media and sqlite sidecars."""
    name = relative.name.lower()
    parts = {part.lower() for part in relative.parts}
    if name.endswith(('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite-wal', '.sqlite-shm')):
        return 'catalog'
    if scope == 'cache':
        return 'cache'
    if name.endswith('.part') and Path(name[:-5]).suffix.lower() in AUDIO_EXTENSIONS:
        return 'audio_in_progress'
    if relative.suffix.lower() in AUDIO_EXTENSIONS:
        return 'audio_finalized'
    if relative.suffix.lower() in VISUAL_EXTENSIONS or 'screenshots' in parts or 'visual-runs' in parts:
        return 'visual_artifacts'
    if scope == 'transcriptions' or name.startswith('transcript_'):
        return 'transcriptions'
    if name == 'metadata.json' or name in {'timeline.json', 'quality_report.json'}:
        return 'meeting_metadata'
    if 'notes' in parts or name.startswith('note'):
        return 'notes'
    return 'other_meeting_data'


def inventory(roots: list[tuple[str, Path]]) -> dict:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {'files': 0, 'logical_bytes': 0, 'allocated_bytes_estimate': 0})
    seen: set[tuple[int, int]] = set()
    missing = unreadable = symlinks = hardlinks = skipped_special = 0
    for scope, root in roots:
        root = root.expanduser()
        try:
            mode = root.lstat().st_mode
        except FileNotFoundError:
            missing += 1
            continue
        except OSError:
            unreadable += 1
            continue
        if stat.S_ISLNK(mode):
            symlinks += 1
            continue
        if stat.S_ISREG(mode):
            entries = [(root, Path(root.name))]
        elif stat.S_ISDIR(mode):
            entries = []
            def walk_error(_err: OSError) -> None:
                nonlocal unreadable
                unreadable += 1
            for base, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
                basepath = Path(base)
                allowed = []
                for name in directories:
                    try:
                        is_link = (basepath / name).is_symlink()
                    except OSError:
                        is_link = True
                    if is_link:
                        symlinks += 1
                    else:
                        allowed.append(name)
                directories[:] = allowed
                for name in files:
                    file = basepath / name
                    entries.append((file, file.relative_to(root)))
        else:
            skipped_special += 1
            continue
        for file, relative in entries:
            try:
                info = file.lstat()
            except OSError:
                unreadable += 1
                continue
            if stat.S_ISLNK(info.st_mode):
                symlinks += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                skipped_special += 1
                continue
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                hardlinks += 1
                continue
            seen.add(identity)
            group = groups[classify(relative, scope)]
            group['files'] += 1
            group['logical_bytes'] += info.st_size
            group['allocated_bytes_estimate'] += getattr(info, 'st_blocks', 0) * 512
    ordered = dict(sorted(groups.items()))
    total = lambda field: sum(item[field] for item in ordered.values())
    return {
        'schema_version': 1, 'kind': 'closedroom_user_data_inventory',
        'measurement': 'metadata-only stat; allocated bytes approximate; APFS clones and active jobs not assessed',
        'roots_requested': len(roots), 'roots_missing': missing, 'roots_unreadable_or_scan_errors': unreadable,
        'symlinks_skipped': symlinks, 'duplicate_inode_entries_skipped': hardlinks,
        'special_files_skipped': skipped_special,
        'files_total': total('files'), 'logical_bytes_total': total('logical_bytes'),
        'allocated_bytes_estimate_total': total('allocated_bytes_estimate'),
        'audio_finalized_candidate_bytes': ordered.get('audio_finalized', {}).get('logical_bytes', 0),
        'groups': ordered,
    }


def configured_roots(settings_file: Path, extra_recordings: list[Path], cache: list[Path]) -> list[tuple[str, Path]]:
    # Only configuration is read. Never read an audio, transcription or metadata payload.
    config = {}
    if settings_file.exists():
        value = json.loads(settings_file.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Settings file must contain an object')
        config = value
    def configured(key: str, default: Path) -> Path:
        value = config.get(key)
        return Path(value).expanduser() if isinstance(value, str) and value.strip() else default
    recordings = configured('recordings_dir', DEFAULT_RECORDINGS)
    transcripts = configured('transcriptions_dir', DEFAULT_TRANSCRIPTS)
    catalog = configured('catalog_db_path', DEFAULT_CATALOG)
    return [('recordings', recordings), ('transcriptions', transcripts), ('catalog', catalog)] + [
        ('recordings', p) for p in extra_recordings
    ] + [('cache', p) for p in cache]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-file', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--extra-recordings-root', type=Path, action='append', default=[])
    parser.add_argument('--cache-root', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    try:
        roots = configured_roots(args.settings_file, args.extra_recordings_root, args.cache_root)
    except (OSError, ValueError, json.JSONDecodeError):
        print('Cannot read ClosedRoom settings; no data was modified.', file=sys.stderr)
        return 2
    print(json.dumps(inventory(roots), sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
