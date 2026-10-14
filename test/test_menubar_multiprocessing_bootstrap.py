from __future__ import annotations

import builtins
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


class MenubarMultiprocessingBootstrapTests(unittest.TestCase):
    def test_auxiliary_process_exits_before_native_app_imports(self) -> None:
        entrypoint = Path(__file__).resolve().parents[1] / "src/local_asr_server/menubar.py"
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "local_asr_server.window":
                self.fail("Multiprocessing child reached the native app bootstrap")
            return original_import(name, *args, **kwargs)

        # PyInstaller's freeze_support dispatches resource trackers/workers and
        # exits. Exercise the real entrypoint without starting Cocoa or an API.
        with patch("multiprocessing.freeze_support", side_effect=SystemExit(73)) as freeze, \
             patch("builtins.__import__", side_effect=guarded_import):
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(entrypoint), run_name="__main__")
        self.assertEqual(exited.exception.code, 73)
        freeze.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
