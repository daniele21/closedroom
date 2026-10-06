from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.transcriber import (
    get_cached_result,
    prune_transcription_cache,
    save_cached_result,
)


def _cache_key(character: str) -> str:
    return character * 64


class TranscriptionCacheBudgetTests(unittest.TestCase):
    def test_prune_removes_oldest_sha_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            oldest = root / f"{_cache_key('a')}.json"
            newest = root / f"{_cache_key('b')}.json"
            unrelated = root / "runtime-state.json"
            oldest.write_bytes(b"x" * 700)
            newest.write_bytes(b"y" * 700)
            unrelated.write_bytes(b"z" * 700)
            os.utime(oldest, ns=(1_000_000_000, 1_000_000_000))
            os.utime(newest, ns=(2_000_000_000, 2_000_000_000))

            with patch("local_asr_server.transcriber.CACHE_DIR", root):
                result = prune_transcription_cache(max_bytes=800)

            self.assertFalse(oldest.exists())
            self.assertTrue(newest.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(result["removed_files"], 1)
            self.assertEqual(result["remaining_bytes"], 700)

    def test_cache_hit_promotes_file_recency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache_file = root / f"{_cache_key('c')}.json"
            cache_file.write_text(json.dumps({"text": "cached"}), encoding="utf-8")
            os.utime(cache_file, ns=(1_000_000_000, 1_000_000_000))

            with patch("local_asr_server.transcriber.CACHE_DIR", root):
                result = get_cached_result(_cache_key("c"))

            self.assertEqual(result, {"text": "cached"})
            self.assertGreater(cache_file.stat().st_mtime_ns, 1_000_000_000)

    def test_save_keeps_new_entry_and_prunes_older_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / f"{_cache_key('d')}.json"
            old.write_bytes(b"x" * 990)
            os.utime(old, ns=(1_000_000_000, 1_000_000_000))

            with (
                patch("local_asr_server.transcriber.CACHE_DIR", root),
                patch("local_asr_server.transcriber.TRANSCRIPTION_CACHE_MAX_BYTES", 1024),
            ):
                save_cached_result(_cache_key("e"), {"text": "new result"})

            self.assertFalse(old.exists())
            self.assertTrue((root / f"{_cache_key('e')}.json").exists())

    def test_entry_larger_than_budget_is_not_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = _cache_key("f")
            cache_file = root / f"{key}.json"
            cache_file.write_bytes(b"x" * 2048)

            with patch("local_asr_server.transcriber.CACHE_DIR", root):
                result = prune_transcription_cache(max_bytes=1024, protected_cache_key=key)

            self.assertFalse(cache_file.exists())
            self.assertEqual(result["remaining_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
