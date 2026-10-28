"""Privacy-safe stat-only inventory tests; no cloud or macOS dependency."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_meeting_data as audit  # noqa: E402


class MeetingDataInventoryTests(unittest.TestCase):
    def test_groups_hardlinks_symlinks_and_no_identifiers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            audio = root / 'recordings' / '2026-01-01' / 'secret-meeting-id'
            audio.mkdir(parents=True)
            (audio / 'mic.wav').write_bytes(b'a' * 1024)
            (audio / 'system.wav.part').write_bytes(b'b' * 17)
            (audio / 'metadata.json').write_text('{"sensitive":"secret-meeting-id"}')
            (audio / 'mic-hardlink.wav').hardlink_to(audio / 'mic.wav')
            outside = root / 'private-outside.wav'
            outside.write_bytes(b'not part of recordings')
            (audio / 'symlink.wav').symlink_to(outside)
            (audio / 'linked-dir').symlink_to(root, target_is_directory=True)
            trans = root / 'transcripts'
            trans.mkdir()
            (trans / 'transcript_abc.json').write_bytes(b'abc')
            report = audit.inventory([('recordings', root / 'recordings'), ('transcriptions', trans)])
            self.assertEqual(report['groups']['audio_finalized']['logical_bytes'], 1024)
            self.assertEqual(report['groups']['audio_in_progress']['logical_bytes'], 17)
            self.assertEqual(report['groups']['transcriptions']['files'], 1)
            self.assertEqual(report['duplicate_inode_entries_skipped'], 1)
            self.assertEqual(report['symlinks_skipped'], 2)
            serialized = json.dumps(report)
            self.assertNotIn('secret-meeting-id', serialized)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn('sensitive', serialized)
            self.assertEqual((audio / 'mic.wav').read_bytes(), b'a' * 1024)

    def test_settings_only_selects_paths_and_hides_secret_values(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = root / 'recordings'; rec.mkdir()
            tr = root / 'trans'; tr.mkdir()
            catalog = root / 'closedroom.db'; catalog.write_bytes(b'x' * 5)
            settings = root / 'settings.json'
            settings.write_text(json.dumps({'recordings_dir': str(rec), 'transcriptions_dir': str(tr),
                                            'catalog_db_path': str(catalog), 'gemini_api_key': 'private-token'}))
            roots = audit.configured_roots(settings, [], [])
            self.assertEqual(len(roots), 3)
            report = audit.inventory(roots)
            self.assertEqual(report['groups']['catalog']['logical_bytes'], 5)
            self.assertNotIn('private-token', json.dumps(report))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(audit.main(['--settings-file', str(settings)]), 0)
            self.assertNotIn(str(root), output.getvalue())

    def test_missing_roots_and_unreadable_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            missing = audit.inventory([('recordings', root / 'missing')])
            self.assertEqual(missing['roots_missing'], 1)
            self.assertEqual(missing['logical_bytes_total'], 0)
            bad = root / 'invalid.json'; bad.write_text('["wrong shape"]')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(audit.main(['--settings-file', str(bad)]), 2)


if __name__ == '__main__':
    unittest.main()
