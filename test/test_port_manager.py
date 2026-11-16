from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.runtime.port_manager import (
    PortInUseError,
    clear_api_runtime,
    prepare_api_port,
    register_api_runtime,
    runtime_instance_lock,
)


class PortManagerTests(unittest.TestCase):
    def test_foreign_process_port_is_rejected_without_signalling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             patch("local_asr_server.runtime.port_manager.is_port_open", return_value=True), \
             patch("local_asr_server.runtime.port_manager.query_closedroom_health",
                   return_value={}), \
             patch("local_asr_server.runtime.port_manager.os.kill") as kill:
            path = Path(tmp) / "runtime-state.json"
            path.write_text('{"preserve": true}', encoding="utf-8")
            with self.assertRaisesRegex(PortInUseError, "occupied"):
                prepare_api_port(1236, state_path=path)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"preserve": true}')
            kill.assert_not_called()

    def test_live_closedroom_on_same_port_is_never_stopped(self) -> None:
        with patch("local_asr_server.runtime.port_manager.is_port_open", return_value=True), \
             patch("local_asr_server.runtime.port_manager.query_closedroom_health",
                   return_value={"ok": True, "server": "local-asr-server", "pid": 4321}), \
             patch("local_asr_server.runtime.port_manager.os.kill") as kill:
            with self.assertRaisesRegex(PortInUseError, "already listening"):
                prepare_api_port(1236)
            kill.assert_not_called()

    def test_free_port_does_not_kill_another_profile_or_clear_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "runtime-state.json"
            prior = json.dumps({
                "schema_version": 1,
                "apis": {"127.0.0.1:1237": {"pid": os.getpid(), "port": 1237}},
            })
            state_path.write_text(prior, encoding="utf-8")
            with patch("local_asr_server.runtime.port_manager.is_port_open",
                       return_value=False), \
                 patch("local_asr_server.runtime.port_manager.os.kill") as kill:
                prepare_api_port(1236, state_path=state_path)
                self.assertEqual(state_path.read_text(encoding="utf-8"), prior)
                kill.assert_not_called()

    def test_invalid_port_rejected_without_mutation(self) -> None:
        for port in (-1, 0, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                prepare_api_port(port)

    def test_instance_lock_rejects_second_writer_without_killing_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "instance.lock"
            with runtime_instance_lock(lock_path=lock_path):
                with self.assertRaisesRegex(PortInUseError, "data profile"):
                    with runtime_instance_lock(lock_path=lock_path):
                        self.fail("second writer acquired shared profile")
            # Exiting the first lock releases it without any stale PID cleanup.
            with runtime_instance_lock(lock_path=lock_path):
                self.assertTrue(lock_path.exists())

    def test_runtime_status_entry_is_only_removed_by_its_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime-state.json"
            register_api_runtime(1237, state_path=path)
            entry = json.loads(path.read_text(encoding="utf-8"))["apis"]["127.0.0.1:1237"]
            self.assertEqual(entry["pid"], os.getpid())
            clear_api_runtime(1237, state_path=path, pid=os.getpid() + 100)
            self.assertTrue(path.exists())
            clear_api_runtime(1237, state_path=path, pid=os.getpid())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
