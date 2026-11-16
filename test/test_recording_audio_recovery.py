from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from local_asr_server.recording_audio_recovery import AudioRecoveryError, recover_checkpoint_audio
from local_asr_server.recordings import RecordingConflict, RecordingStore


def checkpoint(session: Path, source: str, index: int, pcm: bytes) -> Path:
    directory = session / '.audio-recovery' / source
    directory.mkdir(parents=True, exist_ok=True)
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    payload = data.getvalue()
    target = directory / f'{index:08d}.wav'
    target.write_bytes(payload)
    (directory / f'{index:08d}.json').write_text(json.dumps({
        'version': 1, 'source': source, 'sequence': index,
        'file': target.name, 'bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
        'start_pts': float(index), 'end_pts': float(index + 1),
        'frames': len(pcm) // 2, 'total_frames': (index + 1) * len(pcm) // 2,
    }))
    return target


class RecordingAudioRecoveryTests(unittest.TestCase):
    def test_verified_prefix_is_repeatable_and_never_overwrites_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            original = session / 'mic.wav'
            original.write_bytes(b'unclosed original')
            first = struct.pack('<h', 123) * 16000
            second = struct.pack('<h', -123) * 16000
            checkpoint(session, 'mic', 0, first)
            checkpoint(session, 'mic', 1, second)
            partial = session / '.audio-recovery/mic/.00000002.wav.part'
            partial.write_bytes(b'incomplete tail')
            result = recover_checkpoint_audio(session, 'mic')
            self.assertEqual(result, recover_checkpoint_audio(session, 'mic'))
            self.assertEqual(original.read_bytes(), b'unclosed original')
            self.assertEqual(partial.read_bytes(), b'incomplete tail')
            with wave.open(str(result)) as audio:
                self.assertEqual(audio.getnframes(), 32000)
                self.assertEqual(audio.readframes(32000), first + second)

    def test_corruption_gap_symlink_and_uncommitted_audio_do_not_publish_output(self):
        for failure in ('checksum', 'gap', 'timing', 'symlink', 'manifest', 'truncated', 'frame_horizon'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                session = Path(tmp)
                audio = checkpoint(session, 'mic', 0, b'\0\0' * 16000)
                manifest = audio.with_suffix('.json')
                if failure == 'checksum':
                    audio.write_bytes(b'bad checkpoint')
                elif failure == 'gap':
                    manifest.rename(manifest.with_name('00000001.json'))
                elif failure == 'timing':
                    data = json.loads(manifest.read_text())
                    data['end_pts'] = float('nan')
                    manifest.write_text(json.dumps(data))
                elif failure == 'symlink':
                    original = session / 'external.wav'
                    audio.rename(original)
                    audio.symlink_to(original)
                elif failure == 'manifest':
                    manifest.write_text('{broken')
                elif failure == 'frame_horizon':
                    data = json.loads(manifest.read_text())
                    data['total_frames'] = 1
                    manifest.write_text(json.dumps(data))
                else:
                    audio.write_bytes(audio.read_bytes()[:-2])
                    data = json.loads(manifest.read_text())
                    data.update(bytes=audio.stat().st_size, sha256=hashlib.sha256(audio.read_bytes()).hexdigest())
                    manifest.write_text(json.dumps(data))
                before = {p: p.read_bytes() for p in session.rglob('*') if p.is_file()}
                with self.assertRaises(AudioRecoveryError):
                    recover_checkpoint_audio(session, 'mic')
                self.assertEqual(before, {p: p.read_bytes() for p in session.rglob('*') if p.is_file()})
                self.assertEqual(list(session.glob('*.recovered-*.wav')), [])
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            audio = checkpoint(session, 'mic', 0, b'\0\0' * 16000)
            audio.with_suffix('.json').unlink()
            self.assertIsNone(recover_checkpoint_audio(session, 'mic'))
            self.assertTrue(audio.exists())

    def test_sync_failure_keeps_checkpoints_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            checkpoint(session, 'mic', 0, b'\0\0' * 16000)
            before = {p: p.read_bytes() for p in session.rglob('*') if p.is_file()}
            with patch('local_asr_server.recording_audio_recovery.os.fsync', side_effect=OSError('disk full')):
                with self.assertRaises(AudioRecoveryError):
                    recover_checkpoint_audio(session, 'mic')
            self.assertEqual(before, {p: p.read_bytes() for p in session.rglob('*') if p.is_file()})

    def test_store_restart_recovers_checkpoints_without_a_final_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RecordingStore(root, use_settings_dir=False)
            recording = store.create(title='Synthetic crash', mime_type='audio/wav', model='test', language=None,
                                     capture_backend='native', capture_mode='both')
            session = store.session_dir(recording['id'])
            checkpoint(session, 'mic', 0, b'\1\0' * 16000)
            checkpoint(session, 'system', 0, b'\2\0' * 16000)
            (session / 'mic.wav').write_bytes(b'unclosed original')
            restarted = RecordingStore(root, use_settings_dir=False)
            self.assertEqual(restarted.get(recording['id'])['status'], 'recoverable')
            result = restarted.recover(recording['id'])
            self.assertEqual(result['status'], 'recorded')
            self.assertTrue(result['partial'])
            self.assertEqual(result['primary_track_id'], 'system')
            self.assertEqual((session / 'mic.wav').read_bytes(), b'unclosed original')
            with wave.open(str(restarted.track_audio_path(recording['id'], 'mic'))) as audio:
                self.assertEqual(audio.readframes(16000), b'\1\0' * 16000)
            after = RecordingStore(root, use_settings_dir=False)
            self.assertEqual(after.recover(recording['id'])['audio_file'], result['audio_file'])

    def test_normal_finalization_uses_closed_original_without_duplicate_derivative(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp), use_settings_dir=False)
            recording = store.create(title='Normal stop', mime_type='audio/wav', model='test', language=None,
                                     capture_backend='native', capture_mode='mic_only')
            session = store.session_dir(recording['id'])
            segment = checkpoint(session, 'mic', 0, b'\1\0' * 16000)
            original = session / 'mic.wav'
            original.write_bytes(segment.read_bytes())
            expected = original.read_bytes()
            result, _ = store.finalize(recording['id'])
            self.assertEqual(result['status'], 'recorded')
            self.assertEqual(store.audio_path(recording['id']), original)
            self.assertEqual(original.read_bytes(), expected)
            self.assertEqual(list(session.glob('*.recovered-*.wav')), [])

    def test_closed_shorter_original_does_not_hide_longer_committed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp), use_settings_dir=False)
            recording = store.create(title='Short original', mime_type='audio/wav', model='test', language=None,
                                     capture_backend='native', capture_mode='mic_only')
            session = store.session_dir(recording['id'])
            first = checkpoint(session, 'mic', 0, b'\1\0' * 16000)
            checkpoint(session, 'mic', 1, b'\2\0' * 16000)
            original = session / 'mic.wav'
            original.write_bytes(first.read_bytes())
            before = original.read_bytes()
            store.recover(recording['id'])
            self.assertNotEqual(store.audio_path(recording['id']), original)
            with wave.open(str(store.audio_path(recording['id']))) as audio:
                self.assertEqual(audio.getnframes(), 32000)
            self.assertEqual(original.read_bytes(), before)

    def test_closed_original_cannot_bypass_a_corrupt_checkpoint_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp), use_settings_dir=False)
            recording = store.create(title='Corrupt horizon', mime_type='audio/wav', model='test', language=None,
                                     capture_backend='native', capture_mode='mic_only')
            session = store.session_dir(recording['id'])
            first = checkpoint(session, 'mic', 0, b'\1\0' * 16000)
            second = checkpoint(session, 'mic', 1, b'\2\0' * 16000)
            original = session / 'mic.wav'
            original.write_bytes(first.read_bytes())
            manifest = second.with_suffix('.json')
            data = json.loads(manifest.read_text())
            data['total_frames'] = 1
            manifest.write_text(json.dumps(data))
            before = original.read_bytes()
            with self.assertRaises(RecordingConflict):
                store.recover(recording['id'])
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(list(session.glob('*.recovered-*.wav')), [])


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'Requires Apple native writer')
class NativeDurabilityProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix='native-durability-build-')
        root = Path(__file__).resolve().parents[1]
        native = root / 'src/local_asr_server/native_capture_helper'
        cls.binary = Path(cls.build.name) / 'probe'
        result = subprocess.run(['swiftc', '-O', '-module-cache-path', str(Path(cls.build.name) / 'cache'),
            str(native / 'Support.swift'), str(native / 'SampleBufferWavSink.swift'),
            str(native / 'AudioRecoverySegments.swift'), str(root / 'test/fixtures/native_durability_probe.swift'),
            '-o', str(cls.binary), '-framework', 'Foundation', '-framework', 'AVFoundation'],
            capture_output=True, text=True, timeout=120)
        if result.returncode:
            cls.build.cleanup()
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def test_kill_native_writer_recovers_committed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            process = subprocess.Popen([str(self.binary), 'kill', tmp], stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    if (session / '.audio-recovery/mic/00000001.json').exists():
                        break
                    time.sleep(.05)
                process.kill()
                output = process.communicate(timeout=5)[0]
                self.assertTrue((session / '.audio-recovery/mic/00000001.json').exists(), output)
                before = (session / 'mic.wav').read_bytes()
                recovered = recover_checkpoint_audio(session, 'mic')
                self.assertEqual((session / 'mic.wav').read_bytes(), before)
                with wave.open(str(recovered)) as audio:
                    self.assertGreaterEqual(audio.getnframes(), 32000)
                    self.assertLess(audio.getnframes(), 64000)
                    count = audio.getnframes()
                    expected = b''.join(struct.pack('<h', i % 2001 - 1000) for i in range(count))
                    self.assertEqual(audio.readframes(count), expected)
                self.assertEqual(recovered, recover_checkpoint_audio(session, 'mic'))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_normal_finish_commits_last_segment_and_matches_original_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            finished = subprocess.run([str(self.binary), 'finish', tmp], capture_output=True, text=True, timeout=15)
            self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
            recovered = recover_checkpoint_audio(Path(tmp), 'mic')
            with wave.open(str(recovered)) as checkpoint_audio, wave.open(str(Path(tmp) / 'mic.wav')) as original:
                self.assertEqual(checkpoint_audio.getnframes(), 64000)
                self.assertEqual(checkpoint_audio.readframes(64000), original.readframes(64000))

    def test_float_48khz_input_checkpoints_preserve_duration_and_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            finished = subprocess.run([str(self.binary), 'finish48k', tmp], capture_output=True, text=True, timeout=15)
            self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
            recovered = recover_checkpoint_audio(Path(tmp), 'mic')
            with wave.open(str(recovered)) as audio:
                self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 4, delta=.02)
                samples = struct.unpack('<' + 'h' * audio.getnframes(), audio.readframes(audio.getnframes()))
                rms = (sum(s * s for s in samples) / len(samples)) ** .5
                self.assertGreater(rms, 600)
                self.assertLess(rms, 800)

    def test_checkpoint_write_failure_keeps_previous_committed_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            directory = session / '.audio-recovery/mic'
            process = subprocess.Popen([str(self.binary), 'kill', tmp], stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    if (directory / '00000000.json').exists():
                        break
                    time.sleep(.02)
                self.assertTrue((directory / '00000000.json').exists())
                committed = (directory / '00000000.wav').read_bytes()
                directory.chmod(0o500)
                output = process.communicate(timeout=10)[0]
                self.assertEqual(process.returncode, 3, output)
                self.assertEqual((directory / '00000000.wav').read_bytes(), committed)
                recovered = recover_checkpoint_audio(session, 'mic')
                with wave.open(str(recovered)) as audio:
                    self.assertGreaterEqual(audio.getnframes(), 16000)
            finally:
                if directory.exists():
                    directory.chmod(0o700)
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_exclusive_run_claim_and_empty_finish_preserve_existing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(subprocess.run([str(self.binary), 'claim', tmp], capture_output=True).returncode, 0)
            repeated = subprocess.run([str(self.binary), 'claim', tmp], capture_output=True)
            self.assertNotEqual(repeated.returncode, 0)
            original = Path(tmp) / 'mic.wav'
            original.write_bytes(b'original recording')
            finished = subprocess.run([str(self.binary), 'empty-finish', tmp], capture_output=True, timeout=5)
            self.assertEqual(finished.returncode, 0, finished.stderr)
            self.assertEqual(original.read_bytes(), b'original recording')

    def test_concurrent_native_claims_and_preexisting_outputs_are_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            processes = [subprocess.Popen([str(self.binary), 'claim', tmp], stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE) for _ in range(2)]
            try:
                for process in processes:
                    process.communicate(timeout=5)
                self.assertEqual(sorted(p.returncode == 0 for p in processes), [False, True])
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
        for name in ['mic.wav', 'system.wav', 'recording.wav.part']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / name
                target.write_bytes(b'prior audio')
                result = subprocess.run([str(self.binary), 'claim', tmp], capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), b'prior audio')
