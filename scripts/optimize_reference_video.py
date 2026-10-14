#!/usr/bin/env python3
"""Test a high-quality H.264 re-encode of ClosedRoom's public documentation demo.

Offline-only tools: ffmpeg and ffprobe. No meeting content, no app build.
Default: benchmark original vs candidate without modifying tracked files.
--apply replaces the existing .mov only after passing all stream/fidelity gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_SOURCE = Path("docs/assets/Closed-Room-demo.mov")
FRAME_SSIM = re.compile(r"\bAll:([0-9.]+)\b")


def run(args: list[str], *, stdout: bool = False) -> str:
    proc = subprocess.run(args, check=True, capture_output=True, text=True)
    return proc.stdout if stdout else proc.stderr


def probe(path: Path) -> dict:
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path)
    ], stdout=True))


def relevant_streams(metadata: dict) -> list[dict]:
    return [s for s in metadata.get("streams", []) if s.get("codec_type") in {"video", "audio"}]


def check_source(metadata: dict) -> tuple[dict, list[dict]]:
    streams = metadata.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) > 2 or len(videos) + len(audios) != len(streams):
        raise ValueError("Unexpected video/audio/metadata stream topology; preserve manually")
    v = videos[0]
    if not v.get("width") or not v.get("height"):
        raise ValueError("Missing frame dimensions")
    if v.get("pix_fmt") not in ("yuv420p", "yuv422p", "yuv444p", "nv12", "bgra", "rgb24"):
        raise ValueError("Unsupported pixel format: " + str(v.get("pix_fmt")))
    if v.get("color_transfer") in ("smpte2084", "arib-std-b67"):
        raise ValueError("HDR video: 8-bit SDR conversion would lose color information")
    if v.get("side_data_list"):
        if any("rotation" in s or "displaymatrix" in str(s).lower() for s in v["side_data_list"]):
            raise ValueError("Video has orientation/rotation metadata; do not discard")
    return v, audios


def streamhash(path: Path) -> list[str]:
    return [
        line.split("=", 1)[-1].strip()
        for line in run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-map", "0:a", "-c", "copy", "-f", "streamhash", "-hash", "SHA256", "-"
        ], stdout=True).splitlines()
        if "SHA256=" in line
    ]


def ssim_scores(reference: Path, candidate: Path, stats: Path) -> list[float]:
    # Use complete video frames, not a selective screenshot or thumbnail.
    run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(reference), "-i", str(candidate),
        "-filter_complex", f"[0:v:0][1:v:0]ssim=stats_file={stats}:shortest=1:repeatlast=0",
        "-an", "-f", "null", "-"
    ])
    scores = [float(match.group(1)) for match in FRAME_SSIM.finditer(stats.read_text())]
    if not scores or not all(math.isfinite(s) and 0.0 <= s <= 1.0 for s in scores):
        raise ValueError("SSIM per-frame data missing or invalid")
    return scores


def audit(source: Path, *, apply: bool = False, crf: int = 18, preset: str = "medium",
          min_saving: float = 25.0, min_avg_ssim: float = 0.985,
          min_frame_ssim: float = 0.94) -> dict:
    if not source.is_file() or not source.suffix.lower() == ".mov":
        raise ValueError("Requires an existing .mov file")
    meta = probe(source)
    v, audios = check_source(meta)
    original_bytes = source.stat().st_size
    with tempfile.TemporaryDirectory(prefix="closedroom-doc-video-") as tmp:
        candidate = Path(tmp) / "compressed.mov"
        stats = Path(tmp) / "ssim.log"
        run([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
            "-map_metadata", "0", "-map_chapters", "0",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(candidate)
        ])
        output_meta = probe(candidate)
        out_v, out_audio = check_source(output_meta)
        if (out_v["width"], out_v["height"]) != (v["width"], v["height"]):
            raise ValueError("Source/candidate dimensions differ")
        if (out_v.get("avg_frame_rate") != v.get("avg_frame_rate")
                or len(out_audio) != len(audios)):
            raise ValueError("Source/candidate frame rate or audio topology differs")
        for a, b in zip(audios, out_audio):
            if any(a.get(k) != b.get(k) for k in ("codec_name", "channels", "sample_rate")):
                raise ValueError("Audio format changed")
        if streamhash(source) != streamhash(candidate):
            raise ValueError("Audio compressed packets changed")
        source_duration = float(meta.get("format", {}).get("duration", 0))
        output_duration = float(output_meta.get("format", {}).get("duration", 0))
        if abs(source_duration - output_duration) > 0.05:
            raise ValueError("Video duration changed by over 50 milliseconds")
        scores = ssim_scores(source, candidate, stats)
        new_bytes = candidate.stat().st_size
        saving_percent = 100 * (original_bytes - new_bytes) / original_bytes
        report = {
            "source": DEFAULT_SOURCE.as_posix() if source.name == DEFAULT_SOURCE.name else source.name,
            "original_bytes": original_bytes, "candidate_bytes": new_bytes,
            "saved_bytes": original_bytes - new_bytes,
            "saved_percent": round(saving_percent, 3),
            "video_original_codec": v.get("codec_name"),
            "video_candidate_codec": out_v.get("codec_name"),
            "width": v["width"], "height": v["height"],
            "fps": v.get("avg_frame_rate"), "duration_seconds": source_duration,
            "audio_streams_unchanged": len(audios), "frames_compared": len(scores),
            "ssim_average": round(sum(scores)/len(scores), 6),
            "ssim_worst_frame": round(min(scores), 6),
            "thresholds": {"min_saving_percent": min_saving,
                           "min_average_ssim": min_avg_ssim, "min_frame_ssim": min_frame_ssim},
        }
        report["accepted"] = (
            saving_percent >= min_saving
            and sum(scores)/len(scores) >= min_avg_ssim
            and min(scores) >= min_frame_ssim
        )
        report["reason"] = "pass" if report["accepted"] else "savings_or_quality_threshold"
        if apply and report["accepted"]:
            # Preserve the current README/video path and restore original file mode.
            mode = source.stat().st_mode
            replacement = source.with_name(source.name + ".optimized")
            shutil.copyfile(candidate, replacement)
            os.chmod(replacement, mode)
            os.replace(replacement, source)
            report["applied"] = True
        else:
            report["applied"] = False
        return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", choices=("veryfast", "faster", "fast", "medium", "slow"), default="medium")
    p.add_argument("--min-saving", type=float, default=25.0)
    p.add_argument("--min-avg-ssim", type=float, default=0.985)
    p.add_argument("--min-frame-ssim", type=float, default=0.94)
    args = p.parse_args(argv)
    try:
        result = audit(args.source, apply=args.apply, crf=args.crf, preset=args.preset,
                       min_saving=args.min_saving, min_avg_ssim=args.min_avg_ssim,
                       min_frame_ssim=args.min_frame_ssim)
        print(json.dumps(result, indent=2))
        return 0 if result["accepted"] else 3
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as err:
        print("video optimization error:", err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
