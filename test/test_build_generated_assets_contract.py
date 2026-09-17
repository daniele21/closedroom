from __future__ import annotations

import subprocess
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
HELPER_APP = "build_assets/ClosedRoomNativeCapture.app"


class GeneratedBuildAssetsContractTests(unittest.TestCase):
    def test_native_helper_app_is_generated_and_ignored(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", f"{HELPER_APP}/Contents/Info.plist"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", f"{HELPER_APP}/Contents/Info.plist"],
            cwd=ROOT,
            check=False,
        )

        self.assertNotEqual(
            tracked.returncode,
            0,
            "generated native helper Info.plist must not be tracked",
        )
        self.assertEqual(
            ignored.returncode,
            0,
            "generated native helper app must remain ignored",
        )

    def test_build_regenerates_and_embeds_native_helper_app(self) -> None:
        build_script = (ROOT / "build.sh").read_text(encoding="utf-8")

        self.assertIn(
            'NATIVE_HELPER_APP="$BUILD_ASSETS/ClosedRoomNativeCapture.app"',
            build_script,
        )
        self.assertIn('rm -rf "$NATIVE_HELPER_APP"', build_script)
        self.assertIn(
            'cat > "$NATIVE_HELPER_APP/Contents/Info.plist" <<PLIST',
            build_script,
        )
        self.assertIn(
            'ditto "$NATIVE_HELPER_APP" "$NATIVE_HELPER_APP_IN_APP"',
            build_script,
        )


if __name__ == "__main__":
    unittest.main()
