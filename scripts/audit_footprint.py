#!/usr/bin/env python3
"""Measure ClosedRoom's tracked Git tree or a locally built .app without reading meeting data.

Usage:
  python3 scripts/audit_footprint.py repository [--root .] [--ref HEAD]
  python3 scripts/audit_footprint.py bundle --app /path/to/ClosedRoom.app
  python3 scripts/audit_footprint.py bundle --app /path/to/ClosedRoom.app --compare previous.json

JSON contains repository-relative paths or bundle-internal paths only. It never
reads file contents in bundle mode and does not scan the user's data directory.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA_VERSION = 1


def _size_groups(files: list[dict], group_for) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    for item in files:
        group = groups[group_for(item["path"])]
        group["files"] += 1
        group["bytes"] += item["bytes"]
    return dict(sorted(groups.items()))


def _largest(files: list[dict], limit: int = 12) -> list[dict]:
    return sorted(files, key=lambda item: (-item["bytes"], item["path"]))[:limit]


def repository_audit(root: Path, ref: str = "HEAD") -> dict:
    root = root.resolve()
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-l", "-z", ref],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    files = []
    grouped_by_blob: dict[str, list[str]] = defaultdict(list)
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, blob, size = metadata.decode("ascii").split()
        if kind != "blob" or size == "-":
            continue
        path = raw_path.decode("utf-8", "surrogateescape")
        # Do not read file contents; Git's tree contains immutable blob size/identity.
        files.append({"path": path, "bytes": int(size)})
        grouped_by_blob[blob].append(path)

    def classify(path: str) -> str:
        if path.startswith("docs/assets/"):
            return "documentation_media"
        if path.startswith("src/local_asr_server/static/"):
            return "committed_frontend_build"
        if path.startswith("frontend/public/"):
            return "frontend_public"
        return "other_tracked"

    duplicates = []
    for paths in grouped_by_blob.values():
        if len(paths) <= 1:
            continue
        size = next(item["bytes"] for item in files if item["path"] == paths[0])
        duplicates.append({"paths": sorted(paths), "bytes_per_copy": size, "redundant_bytes": size * (len(paths) - 1)})
    duplicates.sort(key=lambda item: (-item["redundant_bytes"], item["paths"][0]))
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "repository_tree",
        "source_revision": revision,
        "count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "groups": _size_groups(files, classify),
        "largest_documentation_media": _largest([item for item in files if classify(item["path"]) == "documentation_media"]),
        "duplicate_blob_groups": duplicates[:20],
        "measurement": "uncompressed Git blob sizes at the specified commit; not clone size, app size, or Git history",
    }


def bundle_audit(app: Path) -> dict:
    if app.suffix != ".app" or not (app / "Contents").is_dir():
        raise ValueError("Expected an existing macOS .app directory containing Contents/")
    files = []
    symlinks = 0
    for folder, dirs, names in os.walk(app, followlinks=False):
        base = Path(folder)
        real_dirs = []
        for name in dirs:
            p = base / name
            if p.is_symlink():
                symlinks += 1
            else:
                real_dirs.append(name)
        dirs[:] = real_dirs
        for name in names:
            p = base / name
            if p.is_symlink():
                symlinks += 1
                continue
            if not p.is_file():
                continue
            files.append({"path": p.relative_to(app).as_posix(), "bytes": p.stat().st_size})

    def classify(path: str) -> str:
        pieces = Path(path).parts
        return "/".join(pieces[:2]) if len(pieces) >= 2 else "app_root"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "macos_app_bundle",
        "app_name": app.name,
        "count": len(files),
        "symlinks_not_followed": symlinks,
        "total_bytes": sum(item["bytes"] for item in files),
        "groups": _size_groups(files, classify),
        "largest_files": _largest(files, 25),
        "measurement": "file logical sizes within .app, excluding symlink targets; not disk allocation, DMG, memory or startup",
        "caution": "PyInstaller archives hide per-Python-package bytes; no dependency removal is inferred from this report",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    repo = sub.add_parser("repository", help="Measure the immutable Git tree, no working-tree reads")
    repo.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    repo.add_argument("--ref", default="HEAD")
    bundle = sub.add_parser("bundle", help="Measure an existing local packaged app, never build it")
    bundle.add_argument("--app", type=Path, required=True)
    for command in (repo, bundle):
        command.add_argument("--compare", type=Path, help="Previous report JSON of the same kind")
    args = parser.parse_args(argv)
    try:
        report = repository_audit(args.root, args.ref) if args.mode == "repository" else bundle_audit(args.app)
        if args.compare:
            baseline = json.loads(args.compare.read_text(encoding="utf-8"))
            if baseline.get("kind") != report["kind"] or baseline.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Comparison report has a different kind or schema_version")
            report["comparison"] = {
                "baseline_total_bytes": baseline["total_bytes"],
                "delta_bytes": report["total_bytes"] - baseline["total_bytes"],
                "delta_files": report["count"] - baseline["count"],
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"footprint audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
