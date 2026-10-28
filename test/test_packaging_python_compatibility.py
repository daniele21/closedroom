from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class PackagingPythonCompatibilityTests(unittest.TestCase):
    def test_canonical_and_direct_builds_default_to_python_312(self) -> None:
        direct = (ROOT / "build.sh").read_text(encoding="utf-8")
        artifact = (ROOT / "scripts/build_artifact.sh").read_text(encoding="utf-8")
        self.assertIn('BUILD_PYTHON_VERSION="${CLOSEDROOM_BUILD_PYTHON_VERSION:-3.12}"', direct)
        self.assertIn('uv venv build_venv --python "$BUILD_PYTHON_VERSION"', direct)
        self.assertIn('uv venv .venv --python "${CLOSEDROOM_BUILD_PYTHON_VERSION:-3.12}"', artifact)
        self.assertNotIn("CLOSEDROOM_BUILD_PYTHON_VERSION:-3.10", direct + artifact)

    def test_fail_closed_on_scipy_dyld_import_in_packaged_environment(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        self.assertIn('"scipy>=1.16"', build)
        self.assertIn("build_venv/bin/python -c 'import scipy.signal; import scipy.sparse.linalg; import mlx_whisper'", build)
        self.assertIn('die "Packaging dependency import failed', build)
        self.assertLess(build.index("Packaging dependency import failed"), build.index("Running PyInstaller from build_venv"))

    def test_spec_discovers_mlx_whisper_tokenizers_without_eager_runtime_import(self) -> None:
        spec = (ROOT / "ClosedRoom.spec").read_text(encoding="utf-8")
        self.assertIn('importlib.util.find_spec("mlx_whisper")', spec)
        self.assertIn("submodule_search_locations", spec)
        self.assertIn("mlx_w_dir.rglob(ext)", spec)
        self.assertNotIn("import mlx_whisper as _mlx_w", spec)
        self.assertIn('"mlx_whisper.transcribe"', spec)


if __name__ == "__main__":
    unittest.main()
