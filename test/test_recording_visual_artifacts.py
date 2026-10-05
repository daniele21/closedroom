from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.recording_visual_artifacts import VisualArtifactStore


class VisualArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.session = Path(self.temp.name)
        self.store = VisualArtifactStore()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def test_frame_staging_preserves_monotonic_contract(self) -> None:
        first = self.store.stage_frame(
            self.session,
            sequence=0,
            timestamp=1.0,
            content=b"\xff\xd8\xffframe",
            write_bytes_atomic=self._write_atomic,
            conflict_error=ValueError,
        )
        self.assertEqual(first["sequence"], 0)
        frames = self.store.list_frames(self.session)
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0]["path"].is_file())

        with self.assertRaisesRegex(ValueError, "monotonic"):
            self.store.stage_frame(
                self.session,
                sequence=0,
                timestamp=1.5,
                content=b"\xff\xd8\xffother",
                write_bytes_atomic=self._write_atomic,
                conflict_error=ValueError,
            )

    def test_jsonl_helpers_keep_valid_recovery_items_only(self) -> None:
        self.store.append_observation(self.session, {"observation_id": "one"})
        with self.store.observations_path(self.session).open("a", encoding="utf-8") as output:
            output.write("not-json\n")
        self.store.append_observation(self.session, {"observation_id": "two"})

        items = self.store.read_valid_jsonl(self.store.observations_path(self.session))
        self.assertEqual([item["observation_id"] for item in items], ["one", "two"])

        self.store.reset_observations(self.session)
        self.assertFalse(self.store.observations_path(self.session).exists())


if __name__ == "__main__":
    unittest.main()
