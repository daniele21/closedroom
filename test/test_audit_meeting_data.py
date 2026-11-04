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
            (root / 'closedroom.db-wal').write_bytes(b'y' * 3)
            (root / 'closedroom.db-shm').write_bytes(b'z' * 2)
            settings = root / 'settings.json'
            settings.write_text(json.dumps({'recordings_dir': str(rec), 'transcriptions_dir': str(tr),
                                            'catalog_db_path': str(catalog), 'gemini_api_key': 'private-token'}))
            roots = audit.configured_roots(settings, [], [])
            self.assertEqual(len(roots), 5)
            report = audit.inventory(roots)
            self.assertEqual(report['groups']['catalog']['logical_bytes'], 10)
            self.assertNotIn('private-token', json.dumps(report))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(audit.main(['--settings-file', str(settings)]), 0)
            self.assertNotIn(str(root), output.getvalue())

    def test_readiness_exposes_missing_catalog_without_disclosing_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            records = root / 'recordings'
            trans = root / 'trans'
            records.mkdir()
            trans.mkdir()
            # Simulate the operator output: two data directories but no DB
            # or SQLite optional sidecars.
            settings = root / 'settings.json'
            settings.write_text(json.dumps({
                'recordings_dir': str(records),
                'transcriptions_dir': str(trans),
                'catalog_db_path': str(root / 'secret-catalog.db'),
                'gemini_api_key': 'private-token',
            }))
            report = audit.inventory(audit.configured_roots(settings, [], []))
            self.assertEqual(report['roots_missing'], 3)
            self.assertEqual(report['root_status'], [
                {'kind': 'recordings', 'status': 'present', 'optional': False},
                {'kind': 'transcriptions', 'status': 'present', 'optional': False},
                {'kind': 'catalog_db', 'status': 'missing', 'optional': False},
                {'kind': 'catalog_wal', 'status': 'missing', 'optional': True},
                {'kind': 'catalog_shm', 'status': 'missing', 'optional': True},
            ])
            serialized = json.dumps(report)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn('private-token', serialized)
            self.assertNotIn('secret-catalog', serialized)

    def test_missing_sqlite_sidecars_are_optional(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            main = root / 'closedroom.db'
            main.write_bytes(b'fixture')
            report = audit.inventory([
                ('catalog', main),
                ('catalog', root / 'closedroom.db-wal'),
                ('catalog', root / 'closedroom.db-shm'),
            ])
            self.assertEqual(report['roots_missing'], 2)
            self.assertEqual(report['root_status'][0]['status'], 'present')
            self.assertEqual([x['optional'] for x in report['root_status']], [False, True, True])

    def test_discover_catalog_when_configured_db_missing_but_app_support_exists(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / 'private-home-id'
            recordings = home / 'ClosedRoom' / 'Recordings' / 'ClosedRoom'
            transcripts = home / 'ClosedRoom' / 'Transcriptions' / 'ClosedRoom'
            recordings.mkdir(parents=True)
            transcripts.mkdir(parents=True)
            app_support = home / 'Library' / 'Application Support' / 'ClosedRoom'
            app_support.mkdir(parents=True)
            (app_support / 'closedroom.db').write_bytes(b'fake-sqlite-header')
            roots = [
                ('recordings', recordings), ('transcriptions', transcripts),
                ('catalog', home / 'ClosedRoom' / 'closedroom.db'),
            ]
            result = audit.discover_catalog_candidates(roots, home=home, environment={})
            statuses = {r['location']: r['status'] for r in result['candidate_statuses']}
            self.assertEqual(statuses['configured'], 'missing')
            self.assertEqual(statuses['application_support'], 'file_present')
            self.assertEqual(result['existing_candidate_count'], 1)
            self.assertFalse(result['active_catalog_resolved'])
            self.assertFalse(result['catalog_database_verified'])
            self.assertNotIn(str(home), json.dumps(result))
            self.assertNotIn('private-home-id', json.dumps(result))

    def test_discover_catalog_reports_environment_override_without_leakage(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            recordings = home / 'r'
            transcripts = home / 't'
            db = home / 'secret-env-db-id.db'
            db.write_bytes(b'x')
            result = audit.discover_catalog_candidates(
                [('recordings', recordings), ('transcriptions', transcripts),
                 ('catalog', home / 'configured.db')],
                home=home, environment={'CLOSEDROOM_CATALOG_DB': str(db)},
            )
            self.assertEqual(
                next(v['status'] for v in result['candidate_statuses']
                     if v['location'] == 'process_env_override'),
                'file_present',
            )
            self.assertNotIn(str(db), json.dumps(result))
            self.assertNotIn('secret-env-db-id', json.dumps(result))

    def test_discover_catalog_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            target = home / 'db-copy'
            target.write_bytes(b'fake')
            configured = home / 'closedroom.db'
            configured.symlink_to(target)
            result = audit.discover_catalog_candidates(
                [('recordings', home / 'r'), ('transcriptions', home / 't'),
                 ('catalog', configured)], home=home, environment={},
            )
            self.assertEqual(result['candidate_statuses'][0],
                             {'location': 'configured', 'status': 'symlink_skipped'})
            self.assertEqual(result['existing_candidate_count'], 0)

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
