from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "src/local_asr_server/speaker_diarization_helper"


class NemotronHelperContractTests(unittest.TestCase):
    def test_swift_cli_exposes_same_track_contract_without_cloud_fallback(self):
        swift = (HELPER / "Sources/main.swift").read_text(encoding="utf-8")
        self.assertIn('engine == "fluidaudio-community-1"', swift)
        self.assertIn('Nemotron3Config.preset(named: preset)', swift)
        self.assertIn("Nemotron3Models.loadFromHuggingFace(", swift)
        self.assertIn("Nemotron3Diarizer.segments(", swift)
        self.assertIn("String($0.speakerIndex)", swift)
        self.assertIn("tracks[input.id]", swift)
        self.assertIn("end: Double($0.endSeconds)", swift)

    def test_swift_model_dependency_is_pinned(self):
        package = (HELPER / "Package.swift").read_text(encoding="utf-8")
        resolved = (HELPER / "Package.resolved").read_text(encoding="utf-8")
        self.assertIn('exact: "0.17.7"', package)
        self.assertIn('"version" : "0.17.7"', resolved)


if __name__ == "__main__":
    unittest.main()
