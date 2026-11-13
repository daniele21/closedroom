#!/usr/bin/env python3
"""Measure ClosedRoom's tracked Git tree or a locally built .app without reading meeting data.

Usage:
  python3 scripts/audit_footprint.py repository [--root .] [--ref HEAD]
  python3 scripts/audit_footprint.py bundle --app /path/to/ClosedRoom.app
  python3 scripts/audit_footprint.py bundle --latest-finalized --root .
  python3 scripts/audit_footprint.py bundle --app /path/to/ClosedRoom.app --compare previous.json
  python3 scripts/audit_footprint.py bundle --latest-finalized --pyinstaller-toc build/ClosedRoom/COLLECT-00.toc

JSON contains repository-relative paths or bundle-internal paths only. It never
reads file contents in bundle mode and does not scan the user's data directory.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import json
import os
from pathlib import Path, PurePosixPath
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


def _component_group(path: str) -> str:
    """A real file/directory in the .app, never inferred Python distribution size."""
    parts = Path(path).parts
    if len(parts) >= 3 and parts[:2] in (
        ("Contents", "Frameworks"), ("Contents", "Resources")
    ):
        # Loose binaries/files directly under a section share one group.
        return "/".join((*parts[:2], parts[2] if len(parts) > 3 else "_root_files"))
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return "_app_root"


def _file_role(path: str) -> str:
    """Non-overlapping physical-file categories, *not* dependency attribution."""
    parts = Path(path).parts
    name = parts[-1].lower()
    suffix = Path(name).suffix
    if "static" in parts or ("web" in parts and suffix in {".js", ".css", ".html"}):
        return "bundled_web_ui"
    if suffix in {".gguf", ".onnx", ".safetensors", ".mlmodel", ".mlmodelc"}:
        return "model_or_ml_artifact"
    if suffix in {".pyz", ".zip", ".whl"} or name.startswith("pyz-"):
        return "opaque_archives"
    if suffix in {".dylib", ".so", ".metallib", ".pyd", ".a"}:
        return "native_libraries_and_extensions"
    if ".framework" in parts or any(part.endswith(".framework") for part in parts):
        return "framework_files"
    if suffix in {".png", ".jpg", ".jpeg", ".icns", ".json", ".txt", ".tiktoken", ".npz", ".db", ".sqlite", ".html", ".css", ".js"}:
        return "other_resources"
    return "unclassified_bundle_files"


def _validated_manifest(app: Path, *, counted_files: int, bytes_total: int) -> dict:
    manifest_path = app.parent / "build-manifest.json"
    if not manifest_path.exists():
        return {"status": "absent", "source_revision": None}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = manifest.get("artifacts", {}).get("app", {})
    if (manifest.get("status") != "successful"
            or identity.get("path") != app.name
            or identity.get("bytes") != bytes_total
            or identity.get("file_count") != counted_files):
        raise ValueError("Adjacent build manifest does not match this .app's size, file count and name")
    source = manifest.get("source", {})
    lineage = manifest.get("lineage", {})
    dmg = manifest.get("artifacts", {}).get("dmg")
    return {
        "status": "size_and_count_match_not_checksum_verified",
        "source_revision": source.get("revision"),
        "source_dirty": source.get("dirty"),
        "build_id": manifest.get("build_id"),
        "product_version": manifest.get("product_version"),
        "channel": lineage.get("channel"),
        "signing": manifest.get("configuration", {}).get("signing"),
        "dmg_bytes_if_present": dmg.get("bytes") if isinstance(dmg, dict) else None,
    }


def latest_finalized_app(root: Path) -> Path:
    """Match smoke_packaged_app's finalized-artifact selection, without its runtime imports."""
    items: list[tuple[str, Path]] = []
    for manifest_file in (root / "dist" / "artifacts").glob("*/*/build-manifest.json"):
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if manifest.get("status") != "successful":
            continue
        filename = manifest.get("artifacts", {}).get("app", {}).get("path")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".app"):
            continue
        app = manifest_file.parent / filename
        if app.is_dir():
            items.append((str(manifest.get("created_at") or ""), app))
    if not items:
        raise ValueError("No finalized local .app and build-manifest.json found under dist/artifacts")
    return max(items, key=lambda pair: pair[0])[1]


def pyinstaller_collect_audit(toc_file: Path, files: list[dict]) -> dict:
    """Read only a COLLECT-00.toc literal, never evaluate it or inspect source paths.

    PyInstaller's (destination, source, type) list is a build input; only
    destination paths with exactly one physical match in this .app are counted.
    It cannot attribute pure Python modules packed in the executable/PYZ.
    """
    if toc_file.name != "COLLECT-00.toc" or toc_file.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Expected a COLLECT-00.toc of at most 32 MiB")
    try:
        value = ast.literal_eval(toc_file.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise ValueError("Malformed COLLECT-00.toc literal") from None
    if not isinstance(value, (list, tuple)) or len(value) > 100000:
        raise ValueError("Invalid COLLECT-00.toc list or excessive entries")
    physically_present = {entry["path"]: entry["bytes"] for entry in files}
    possible_roots = (
        "Contents/MacOS", "Contents/Frameworks", "Contents/Resources",
        "Contents/MacOS/_internal", "Contents/Frameworks/_internal",
        "Contents/Resources/_internal",
    )
    count_unmatched = count_ambiguous = count_ignored = 0
    candidate_matches: dict[str, list[tuple[str, str]]] = {}
    for entry in value:
        if (not isinstance(entry, (tuple, list)) or len(entry) != 3
                or not all(isinstance(part, str) or part is None for part in entry)):
            raise ValueError("Invalid COLLECT-00.toc entry")
        dest, _source_private, entry_type = entry
        if not dest or not isinstance(dest, str) or not isinstance(entry_type, str):
            raise ValueError("Invalid COLLECT-00.toc destination or type")
        # Never include _source_private in output or filesystem access.
        if entry_type not in {"BINARY", "EXTENSION", "DATA", "ZIPFILE"}:
            count_ignored += 1
            continue
        dest_path = PurePosixPath(dest)
        if (dest.startswith("/") or "\\" in dest or ":" in dest
                or any(part in ("", ".", "..") for part in dest.split("/"))
                or dest_path.as_posix() != dest):
            raise ValueError("Unsafe COLLECT-00.toc destination")
        candidates = [f"{prefix}/{dest}" for prefix in possible_roots
                      if f"{prefix}/{dest}" in physically_present]
        if not candidates:
            count_unmatched += 1
        elif len(candidates) > 1:
            count_ambiguous += 1
        else:
            group = dest.split("/", 1)[0] if "/" in dest else "_top_level_files"
            candidate_matches.setdefault(candidates[0], []).append((group, entry_type))

    aggregate: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    type_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    matched_bytes = 0
    matched_count = 0
    for path, claims in candidate_matches.items():
        if len(claims) != 1:
            count_ambiguous += len(claims)
            continue
        group, entry_type = claims[0]
        size = physically_present[path]
        aggregate[group]["files"] += 1
        aggregate[group]["bytes"] += size
        type_totals[entry_type]["files"] += 1
        type_totals[entry_type]["bytes"] += size
        matched_bytes += size
        matched_count += 1
    return {
        "evidence": "user_supplied_pyinstaller_collect_toc",
        "provenance": "toc_to_app_revision_not_verified",
        "source_paths_exposed": False,
        "matched_file_count": matched_count,
        "matched_bytes": matched_bytes,
        "unmatched_entry_count": count_unmatched,
        "ambiguous_entry_count": count_ambiguous,
        "ignored_non_physical_entry_count": count_ignored,
        "destination_groups": [
            {"destination_prefix": name, **counts}
            for name, counts in sorted(aggregate.items(), key=lambda pair: (-pair[1]["bytes"], pair[0]))
        ],
        "entry_types": dict(sorted(type_totals.items())),
        "unattributed_bundle_bytes": sum(item["bytes"] for item in files) - matched_bytes,
        "caution": "Names are COLLECT destination prefixes, not proven installed Python distribution sizes. Compressed/PYZ/EXE modules remain opaque; the TOC may come from a different build.",
    }


def bundle_audit(app: Path, *, pyinstaller_toc: Path | None = None) -> dict:
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

    total_bytes = sum(item["bytes"] for item in files)
    manifest = _validated_manifest(app, counted_files=len(files) + symlinks, bytes_total=total_bytes)
    components = _size_groups(files, _component_group)
    roles = _size_groups(files, _file_role)
    toc_report = pyinstaller_collect_audit(pyinstaller_toc, files) if pyinstaller_toc else None
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "macos_app_bundle",
        "app_name": app.name,
        "count": len(files),
        "symlinks_not_followed": symlinks,
        "total_bytes": total_bytes,
        "groups": _size_groups(files, classify),
        "component_groups": components,
        "largest_component_groups": [
            {"path": name, **counts}
            for name, counts in sorted(components.items(), key=lambda item: (-item[1]["bytes"], item[0]))[:25]
        ],
        "file_roles": roles,
        "unattributed_opaque_archive_bytes": roles.get("opaque_archives", {}).get("bytes", 0),
        "artifact_identity": manifest,
        "pyinstaller_collect": toc_report,
        "largest_files": _largest(files, 25),
        "measurement": "logical file sizes within .app, excluding symlinks; not disk allocation, DMG, memory or startup",
        "caution": "Groups count physically bundled files only. PyInstaller executable/PYZ/zip contents may hide modules; no per-dependency size or safety-to-remove claim.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    repo = sub.add_parser("repository", help="Measure the immutable Git tree, no working-tree reads")
    repo.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    repo.add_argument("--ref", default="HEAD")
    bundle = sub.add_parser("bundle", help="Measure an existing local packaged app, never build it")
    selector = bundle.add_mutually_exclusive_group(required=True)
    selector.add_argument("--app", type=Path, help="Existing .app path")
    selector.add_argument("--latest-finalized", action="store_true", help="Resolve latest successful local artifact manifest")
    bundle.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Checkout containing dist/artifacts, only for --latest-finalized")
    bundle.add_argument("--pyinstaller-toc", type=Path,
                        help="Explicit build/ClosedRoom/COLLECT-00.toc; ignores private source paths")
    for command in (repo, bundle):
        command.add_argument("--compare", type=Path, help="Previous report JSON of the same kind")
    args = parser.parse_args(argv)
    try:
        if args.mode == "repository":
            report = repository_audit(args.root, args.ref)
        else:
            app = latest_finalized_app(args.root) if args.latest_finalized else args.app
            report = bundle_audit(app, pyinstaller_toc=args.pyinstaller_toc)
        if args.compare:
            baseline = json.loads(args.compare.read_text(encoding="utf-8"))
            if baseline.get("kind") != report["kind"] or baseline.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Comparison report has a different kind or schema_version")
            report["comparison"] = {
                "baseline_total_bytes": baseline["total_bytes"],
                "delta_bytes": report["total_bytes"] - baseline["total_bytes"],
                "delta_files": report["count"] - baseline["count"],
            }
            if report["kind"] == "macos_app_bundle":
                for group in ("file_roles", "groups", "component_groups"):
                    previous = baseline.get(group, {})
                    current = report.get(group, {})
                    report["comparison"][group + "_delta_bytes"] = {
                        name: current.get(name, {}).get("bytes", 0) - previous.get(name, {}).get("bytes", 0)
                        for name in sorted(set(previous) | set(current))
                        if current.get(name, {}).get("bytes", 0) != previous.get(name, {}).get("bytes", 0)
                    }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"footprint audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
