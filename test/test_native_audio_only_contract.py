"""Retired global audio-routing paths must not return during native capture work."""
from __future__ import annotations

import unittest
from pathlib import Path

from local_asr_server.cli import _build_parser


ROOT = Path(__file__).resolve().parents[1]


class NativeOnlySystemAudioContractTests(unittest.TestCase):
    def test_no_legacy_router_or_virtual_driver_helper_in_source_tree(self):
        for relative in (
            "src/local_asr_server/audio_router.py",
            "src/local_asr_server/macos_audio_helper/audio_helper.swift",
            "src/local_asr_server/macos_audio_helper/compile.py",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_build_and_setup_do_not_install_driver_or_package_router(self):
        for relative in ("setup.sh", "build.sh", "scripts/build_artifact.sh", "ClosedRoom.spec"):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("blackhole-2ch", source.casefold())
                self.assertNotIn("macos_audio_helper", source)
                self.assertNotIn("local-asr setup-audio", source)
        spec = (ROOT / "ClosedRoom.spec").read_text(encoding="utf-8")
        self.assertNotIn("local_asr_server.audio_router", spec)
        self.assertNotIn('(str(AUDIO_HELPER), ".")', spec)

    def test_cli_does_not_expose_global_audio_route_installer(self):
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["setup-audio"])


if __name__ == "__main__":
    unittest.main()
