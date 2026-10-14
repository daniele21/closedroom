from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_identity.py"
spec = importlib.util.spec_from_file_location("build_identity", SCRIPT)
assert spec and spec.loader
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class LocalBuildIdentityTests(unittest.TestCase):
    def test_test_app_has_distinct_fixed_bundle_and_name(self) -> None:
        live = identity.app_identity("stable", environ={})
        test = identity.app_identity("test", environ={
            "CLOSEDROOM_APP_BUNDLE_NAME": "ClosedRoom.app",
            "CLOSEDROOM_APP_BUNDLE_ID": "com.closedroom.app",
        })
        self.assertEqual(live, ("ClosedRoom", "ClosedRoom.app", "ClosedRoom", "com.closedroom.app"))
        self.assertEqual(test, ("ClosedRoom", "ClosedRoom Test.app", "ClosedRoom Test", "com.closedroom.app.test"))
        self.assertNotEqual(live[1], test[1])
        self.assertNotEqual(live[3], test[3])

    def test_all_builds_increment_persistently_even_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "build-number.txt"
            self.assertEqual(identity.next_number(path), 1)
            self.assertEqual(identity.next_number(path), 2)
            self.assertEqual(path.read_text(), "2\n")
            self.assertEqual(identity.next_number(path), 3)

    def test_invalid_counter_fails_closed_without_reset(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "build-number.txt"
            path.write_text("invalid")
            with self.assertRaisesRegex(ValueError, "positive decimal"):
                identity.next_number(path)
            self.assertEqual(path.read_text(), "invalid")

    def test_explicit_build_number_validation(self) -> None:
        for invalid in ("0", "-3", "1.2.0", "abc", "2147483648"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                identity.validate_number(invalid)
        self.assertEqual(identity.validate_number("00017"), 17)

    def test_repo_scripts_share_build_identity_owner(self) -> None:
        repo = Path(__file__).parents[1]
        for path in ("build.sh", "scripts/build_artifact.sh"):
            content = (repo / path).read_text(encoding="utf-8")
            self.assertIn("scripts/build_identity.py", content)
        spec_source = (repo / "ClosedRoom.spec").read_text(encoding="utf-8")
        self.assertIn("CLOSEDROOM_BUILD_NUMBER", spec_source)
        self.assertIn('"CFBundleVersion": BUILD_NUMBER', spec_source)


if __name__ == "__main__":
    unittest.main()
