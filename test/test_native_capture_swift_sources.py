from __future__ import annotations

import unittest

from local_asr_server.native_capture_helper import compile as native_compile


class NativeCaptureSwiftSourceTests(unittest.TestCase):
    def test_native_helper_compiles_all_swift_units_with_main_first(self) -> None:
        sources = native_compile._swift_sources()
        self.assertGreaterEqual(len(sources), 2)
        self.assertEqual(sources[0].name, "native_capture_helper.swift")
        self.assertIn("Support.swift", {source.name for source in sources})


    def test_split_helper_uses_explicit_main_entry_point(self) -> None:
        main_source = native_compile._SWIFT_SOURCE.read_text(encoding="utf-8")
        self.assertIn("@main", main_source)
        self.assertIn("struct ClosedRoomNativeCaptureMain", main_source)

    def test_native_helper_hash_covers_split_swift_sources(self) -> None:
        sources = native_compile._swift_sources()
        expected_names = {source.name for source in sources}
        self.assertIn("native_capture_helper.swift", expected_names)
        self.assertIn("Support.swift", expected_names)
        self.assertEqual(len(native_compile._swift_source_hash()), 64)


if __name__ == "__main__":
    unittest.main()
