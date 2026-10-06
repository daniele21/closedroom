"""
pyi_rth_mlx.py — PyInstaller runtime hook for MLX worker processes.

ClosedRoom keeps the menu/API process lightweight. MLX is preloaded only for
frozen child processes that actually execute ASR or local LLM/VLM inference.
This preserves the metallib resolution workaround without paying its startup
and idle-memory cost in the ordinary app process.
"""

import ctypes
import os
import sys
from pathlib import Path


_MLX_MODULE_WORKERS = {
    "local_llm_server",
    "local_asr_server.runtime.local_llm_entrypoint",
    "mlx_vlm.server",
}


def _needs_mlx_preload(argv: list[str]) -> bool:
    args = argv[1:]
    if not args:
        return False
    if args[0] == "transcribe":
        return True
    return len(args) >= 2 and args[0] == "-m" and args[1] in _MLX_MODULE_WORKERS


if (
    getattr(sys, "frozen", False)
    and hasattr(sys, "_MEIPASS")
    and _needs_mlx_preload(sys.argv)
):
    _meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    _mlx_lib = _meipass / "mlx" / "lib"

    if _mlx_lib.exists():
        _libmlx = _mlx_lib / "libmlx.dylib"
        _libjaccl = _mlx_lib / "libjaccl.dylib"

        # Load JACCL first because libmlx may depend on it.
        for _lib in (_libjaccl, _libmlx):
            if _lib.exists():
                try:
                    ctypes.CDLL(str(_lib))
                except OSError:
                    pass

        # Secondary lookup path for libraries loaded later by MLX extensions.
        _existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        _paths = [str(_mlx_lib)]
        if _existing:
            _paths.append(_existing)
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(_paths)
