#!/usr/bin/env python3
"""Lossless, opt-in compression of documentation PNGs with reference-safe renaming.

Requires Pillow with WebP support. No meeting data, models or packaged app are read.
Dry run by default; --apply changes only docs/assets/ and tracked text references.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, features

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".rst", ".html", ".htm", ".css",
    ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml", ".py",
}


def tracked_paths(root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    return [root / Path(raw.decode("utf-8", "surrogateescape"))
            for raw in proc.stdout.split(b"\0") if raw]


def _equivalent(original: Image.Image, converted: Image.Image) -> bool:
    return (original.size == converted.size
            and original.convert("RGBA").tobytes() == converted.convert("RGBA").tobytes()
            and original.info.get("icc_profile") == converted.info.get("icc_profile"))


def optimize(root: Path, *, apply: bool = False, minimum_bytes: int = 100_000,
             minimum_percent: float = 10.0) -> dict:
    if not features.check("webp"):
        raise RuntimeError("Pillow was not compiled with lossless WebP support")
    root = root.resolve()
    sources = tracked_paths(root)
    pngs = sorted(p for p in sources if p.parent == root / "docs" / "assets"
                  and p.suffix.lower() == ".png" and p.is_file())
    text_files: dict[Path, str] = {}
    for path in sources:
        if path.suffix.lower() not in TEXT_EXTENSIONS or not path.is_file():
            continue
        try:
            text_files[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

    report = {"schema_version": 1, "mode": "apply" if apply else "dry_run",
              "sources_scanned": len(pngs), "converted": [], "skipped": [],
              "bytes_before": 0, "bytes_after": 0, "reference_files_changed": []}
    candidates: list[tuple[Path, Path, bytes, int]] = []
    for source in pngs:
        target = source.with_suffix(".webp")
        size = source.stat().st_size
        if target.exists():
            report["skipped"].append({"path": source.relative_to(root).as_posix(),
                                      "reason": "target_exists"})
            continue
        with Image.open(source) as original:
            if getattr(original, "n_frames", 1) != 1:
                report["skipped"].append({"path": source.relative_to(root).as_posix(),
                                          "reason": "animated_image"})
                continue
            metadata = {key: original.info[key] for key in ("icc_profile", "exif")
                        if key in original.info}
            output = io.BytesIO()
            original.save(output, format="WEBP", lossless=True, method=6, exact=True,
                          **metadata)
            encoded = output.getvalue()
            with Image.open(io.BytesIO(encoded)) as decoded:
                if not _equivalent(original, decoded):
                    raise ValueError(f"Decoded pixels or ICC profile differ: {source.name}")
        saving = size - len(encoded)
        if saving < minimum_bytes or (100 * saving / max(1, size)) < minimum_percent:
            report["skipped"].append({"path": source.relative_to(root).as_posix(),
                                      "reason": "insufficient_saving",
                                      "original_bytes": size, "candidate_bytes": len(encoded)})
            continue
        candidates.append((source, target, encoded, size))
        report["bytes_before"] += size
        report["bytes_after"] += len(encoded)
        report["converted"].append({
            "from": source.relative_to(root).as_posix(),
            "to": target.relative_to(root).as_posix(),
            "before_bytes": size, "after_bytes": len(encoded),
            "saved_bytes": saving,
        })

    updated = dict(text_files)
    for source, target, _, _ in candidates:
        original_name, replacement_name = source.name, target.name
        for path, content in list(updated.items()):
            if original_name in content:
                updated[path] = content.replace(original_name, replacement_name)
    report["reference_files_changed"] = sorted(
        path.relative_to(root).as_posix()
        for path, content in updated.items() if content != text_files[path]
    )
    # All tracked text references to an asset must be accounted for, including
    # shortened relative links (e.g. ../assets/diagram.png).
    for source, _, _, _ in candidates:
        for path, content in updated.items():
            if source.name in content:
                raise ValueError(f"Unrewritten asset reference: {path}")
    if apply:
        for source, target, data, _ in candidates:
            target.write_bytes(data)
            source.unlink()
        for path, content in updated.items():
            if content != text_files[path]:
                path.write_text(content, encoding="utf-8")
    report["total_saved_bytes"] = report["bytes_before"] - report["bytes_after"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true", help="Write replacements to working tree")
    parser.add_argument("--minimum-bytes", type=int, default=100_000)
    parser.add_argument("--minimum-percent", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        report = optimize(args.root, apply=args.apply,
                          minimum_bytes=args.minimum_bytes,
                          minimum_percent=args.minimum_percent)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"reference media optimization failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
