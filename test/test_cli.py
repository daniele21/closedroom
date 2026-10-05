from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.cli import (
    _build_parser,
    _ensure_dev_frontend_bundle,
    _frontend_source_fingerprint,
    _resolve_serve_port,
)


class CliPortTests(unittest.TestCase):
    def test_serve_defaults_to_app_port_without_reload(self) -> None:
        args = _build_parser().parse_args(["serve"])
        self.assertEqual(_resolve_serve_port(args), 1236)

    def test_reload_defaults_to_dedicated_dev_port(self) -> None:
        args = _build_parser().parse_args(["serve", "--reload"])
        self.assertEqual(_resolve_serve_port(args), 1237)

    def test_explicit_port_overrides_reload_default(self) -> None:
        args = _build_parser().parse_args(["serve", "--reload", "--port", "1240"])
        self.assertEqual(_resolve_serve_port(args), 1240)

    def test_recordings_directory_defaults_to_persisted_settings(self) -> None:
        args = _build_parser().parse_args(["serve"])
        self.assertIsNone(args.recordings_dir)

    def test_recordings_directory_can_be_explicitly_overridden(self) -> None:
        args = _build_parser().parse_args(["serve", "--recordings-dir", "/tmp/closedroom"])
        self.assertEqual(args.recordings_dir, "/tmp/closedroom")


class CliFrontendBundleTests(unittest.TestCase):
    def _make_root(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        frontend = root / "frontend"
        (frontend / "src").mkdir(parents=True)
        (frontend / "public").mkdir(parents=True)
        (frontend / "node_modules").mkdir()
        (frontend / "src" / "main.tsx").write_text("export const version = 1;\n", encoding="utf-8")
        (frontend / "public" / "logo.svg").write_text("<svg/>\n", encoding="utf-8")
        (frontend / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
        (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        static = root / "src" / "local_asr_server" / "static"
        static.mkdir(parents=True)
        (static / "index.html").write_text("<html/>\n", encoding="utf-8")
        return temp, root

    def test_frontend_fingerprint_changes_with_source(self) -> None:
        temp, root = self._make_root()
        try:
            frontend = root / "frontend"
            first = _frontend_source_fingerprint(frontend)
            (frontend / "src" / "main.tsx").write_text("export const version = 2;\n", encoding="utf-8")
            second = _frontend_source_fingerprint(frontend)
            self.assertNotEqual(first, second)
        finally:
            temp.cleanup()

    def test_source_mode_rebuilds_once_then_reuses_matching_bundle(self) -> None:
        temp, root = self._make_root()
        try:
            with (
                patch("local_asr_server.paths.is_bundled", return_value=False),
                patch("local_asr_server.cli.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "pnpm" else None),
                patch("local_asr_server.cli.subprocess.run") as run,
            ):
                self.assertTrue(_ensure_dev_frontend_bundle(root))
                run.assert_called_once()
                self.assertFalse(_ensure_dev_frontend_bundle(root))
                run.assert_called_once()
        finally:
            temp.cleanup()

    def test_source_mode_refuses_stale_bundle_without_frontend_dependencies(self) -> None:
        temp, root = self._make_root()
        try:
            (root / "frontend" / "node_modules").rmdir()
            with patch("local_asr_server.paths.is_bundled", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "Frontend dependencies are missing"):
                    _ensure_dev_frontend_bundle(root)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()