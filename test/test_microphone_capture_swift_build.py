"""The native source-recovery code must compile on an available macOS runner.

This is a deterministic toolchain gate, not a proof of physical device switching.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest

from local_asr_server.native_capture_helper import compile as native_compile


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Requires macOS Swift toolchain")
class MicrophoneCaptureSwiftBuildTests(unittest.TestCase):
    def test_complete_native_helper_compiles_and_reports_capabilities(self):
        sources = {path.name for path in native_compile._swift_sources()}
        self.assertIn("MicrophoneCapture.swift", sources)
        executable = native_compile.compile_helper(force=False)
        result = subprocess.run(
            [executable, "capabilities"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIn("backend", response)
        self.assertEqual(response["backend"], "native")


if __name__ == "__main__":
    unittest.main()
