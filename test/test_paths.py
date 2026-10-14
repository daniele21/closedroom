from __future__ import annotations

import tempfile
import plistlib
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.paths import (
    get_native_capture_helper_path,
    get_speaker_diarization_helper_path,
    get_runtime_state_file,
    get_service_log_file,
    get_cache_dir,
)


class BundlePathTests(unittest.TestCase):
    def test_runtime_state_file_lives_in_app_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch("local_asr_server.paths.Path.home", return_value=Path(temp)):
                self.assertEqual(
                    get_runtime_state_file(),
                    Path(temp) / "Library" / "Application Support" / "ClosedRoom" / "runtime-state.json",
                )

    def test_service_log_file_lives_in_logs_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch("local_asr_server.paths.Path.home", return_value=Path(temp)):
                self.assertEqual(
                    get_service_log_file("llm-server"),
                    Path(temp) / "Library" / "Logs" / "ClosedRoom" / "llm-server.log",
                )

    def test_test_app_has_isolated_runtime_state_cache_logs_and_models(self) -> None:
        from local_asr_server.paths import get_models_dir
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contents = root / "ClosedRoom Test.app" / "Contents"
            contents.mkdir(parents=True)
            with (contents / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app.test"}, handle)
            with (
                patch("local_asr_server.paths.Path.home", return_value=root),
                patch("local_asr_server.paths.is_bundled", return_value=True),
                patch("local_asr_server.paths.get_app_contents_dir", return_value=contents),
            ):
                self.assertEqual(get_runtime_state_file(), root / "Library/Application Support/ClosedRoom Test/runtime-state.json")
                self.assertEqual(get_cache_dir(), root / "Library/Caches/ClosedRoom Test")
                self.assertEqual(get_service_log_file("api"), root / "Library/Logs/ClosedRoom Test/api.log")
                self.assertEqual(get_models_dir(), root / "Library/Application Support/ClosedRoom Test/models")
            with (contents / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": "com.closedroom.app"}, handle)
            with (
                patch("local_asr_server.paths.Path.home", return_value=root),
                patch("local_asr_server.paths.is_bundled", return_value=True),
                patch("local_asr_server.paths.get_app_contents_dir", return_value=contents),
            ):
                self.assertEqual(get_runtime_state_file(), root / "Library/Application Support/ClosedRoom/runtime-state.json")

    def test_native_capture_helper_prefers_embedded_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contents_dir = Path(temp) / "ClosedRoom.app" / "Contents"
            executable = contents_dir / "MacOS" / "ClosedRoom"
            bundle_dir = contents_dir / "Frameworks"
            helper = (
                contents_dir
                / "Helpers"
                / "ClosedRoomNativeCapture.app"
                / "Contents"
                / "MacOS"
                / "ClosedRoomNativeCapture"
            )
            helper.parent.mkdir(parents=True)
            helper.touch()
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("local_asr_server.paths.is_bundled", return_value=True),
                patch("local_asr_server.paths.get_bundle_dir", return_value=bundle_dir),
                patch("local_asr_server.paths.sys.executable", str(executable)),
            ):
                self.assertEqual(get_native_capture_helper_path(), helper.resolve())

    def test_native_capture_helper_falls_back_to_legacy_bundled_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contents_dir = Path(temp) / "ClosedRoom.app" / "Contents"
            executable = contents_dir / "MacOS" / "ClosedRoom"
            bundle_dir = contents_dir / "Frameworks"
            legacy = bundle_dir / "native-capture-helper"
            legacy.parent.mkdir(parents=True)
            legacy.touch()
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("local_asr_server.paths.is_bundled", return_value=True),
                patch("local_asr_server.paths.get_bundle_dir", return_value=bundle_dir),
                patch("local_asr_server.paths.sys.executable", str(executable)),
            ):
                self.assertEqual(get_native_capture_helper_path(), legacy.resolve())

    def test_speaker_diarization_helper_resolves_from_bundle_frameworks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contents_dir = Path(temp) / "ClosedRoom.app" / "Contents"
            executable = contents_dir / "MacOS" / "ClosedRoom"
            helper = contents_dir / "Frameworks" / "speaker-diarization-helper"
            executable.parent.mkdir(parents=True)
            executable.touch()
            helper.parent.mkdir(parents=True)
            helper.touch()
            with (
                patch("local_asr_server.paths.is_bundled", return_value=True),
                patch("local_asr_server.paths.get_bundle_dir", return_value=helper.parent),
                patch("local_asr_server.paths.sys.executable", str(executable)),
            ):
                self.assertEqual(get_speaker_diarization_helper_path(), helper.resolve())


if __name__ == "__main__":
    unittest.main()
