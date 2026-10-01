from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server import app_identity


class AppIdentityProductVersionTests(unittest.TestCase):
    def _contents_dir(self, payload: dict) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        tmp = tempfile.TemporaryDirectory()
        contents = Path(tmp.name) / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump(payload, handle)
        return tmp, contents

    def test_bundled_identity_uses_product_bundle_version_not_python_package_version(self) -> None:
        tmp, contents = self._contents_dir(
            {
                "CFBundleIdentifier": "com.closedroom.app",
                "CFBundleName": "ClosedRoom",
                "CFBundleDisplayName": "ClosedRoom",
                "CFBundleVersion": "0.2.0",
                "CFBundleShortVersionString": "0.2.0",
            }
        )
        self.addCleanup(tmp.cleanup)

        with (
            patch.object(app_identity, "get_app_contents_dir", return_value=contents),
            patch.object(app_identity, "is_bundled", return_value=True),
            patch.object(app_identity.metadata, "version", return_value="0.1.0"),
        ):
            identity = app_identity.get_app_identity()

        self.assertEqual(identity.version, "0.2.0")
        self.assertEqual(identity.as_health_payload()["app_version"], "0.2.0")
        self.assertNotEqual(identity.version, "0.1.0")

    def test_bundle_version_falls_back_to_cf_bundle_version(self) -> None:
        tmp, contents = self._contents_dir({"CFBundleVersion": "0.2.1"})
        self.addCleanup(tmp.cleanup)

        with patch.object(app_identity, "get_app_contents_dir", return_value=contents):
            self.assertEqual(app_identity.get_bundle_version(), "0.2.1")

    def test_non_bundled_identity_keeps_python_package_version(self) -> None:
        with (
            patch.object(app_identity, "is_bundled", return_value=False),
            patch.object(app_identity.metadata, "version", return_value="0.1.0"),
        ):
            self.assertEqual(app_identity.get_app_version(), "0.1.0")


if __name__ == "__main__":
    unittest.main()
