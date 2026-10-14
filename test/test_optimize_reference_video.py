"""Source-only deterministic fidelity-gate tests with a synthetic tiny video."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import optimize_reference_video as video  # noqa: E402


class ReferenceVideoTests(unittest.TestCase):
    def test_rejects_unknown_or_unsupported_stream_layout(self):
        with self.assertRaisesRegex(ValueError, "topology"):
            video.check_source({"streams": [{"codec_type": "video", "width": 500, "height": 400},
                                            {"codec_type": "subtitle"}]})
        with self.assertRaisesRegex(ValueError, "HDR"):
            video.check_source({"streams": [{
                "codec_type": "video", "width": 500, "height": 400,
                "codec_name": "hevc", "pix_fmt": "yuv420p10le", "color_transfer": "smpte2084"
            }]})

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg absent")
    def test_fidelity_and_audio_stream_copy_with_real_synthetic_video(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fixture.mov"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx265",
                "-preset", "ultrafast", "-x265-params", "lossless=1", "-pix_fmt", "yuv420p10le",
                "-c:a", "pcm_s16le", str(source),
            ], check=True)
            orig = source.stat().st_size
            result = video.audit(source, crf=18, preset="fast", min_saving=0,
                                 min_avg_ssim=0, min_frame_ssim=0)
            self.assertFalse(result["applied"])
            self.assertTrue(result["accepted"])
            self.assertGreater(result["frames_compared"], 0)
            self.assertEqual(result["audio_streams_unchanged"], 1)
            self.assertEqual(source.stat().st_size, orig)
            blocked = video.audit(source, apply=True, crf=18, preset="fast",
                                  min_saving=0, min_avg_ssim=1.01, min_frame_ssim=0)
            self.assertFalse(blocked["accepted"])
            self.assertFalse(blocked["applied"])
            self.assertEqual(source.stat().st_size, orig)


if __name__ == "__main__":
    unittest.main()
