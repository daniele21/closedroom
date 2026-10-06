from __future__ import annotations

import importlib
import importlib.util
import json
import runpy
import sys
import tempfile
from pathlib import Path
from collections.abc import Sequence


SUPPORTED_BUNDLED_MODULES = {
    "local_llm_server",
    "local_asr_server.runtime.local_llm_entrypoint",
    "mlx_vlm.server",
}
# Keep deterministic non-Cocoa commands available from the frozen executable.
# `serve` is used by packaged-app CI smoke to exercise the real bundled Python
# runtime and static assets without requiring TCC prompts or interactive UI.
SUPPORTED_CLI_COMMANDS = {"inspect-meeting", "transcribe", "serve"}
BUNDLE_RUNTIME_SMOKE_COMMAND = "bundle-runtime-smoke"
BUNDLE_RUNTIME_IMPORTS = (
    "local_llm_server.cli",
    "mlx_vlm.server",
    "mlx_vlm.models.qwen3_vl",
    "mlx_whisper.transcribe",
)


def _run_bundle_runtime_smoke() -> None:
    """Exercise packaged ASR/VLM surfaces without starting model inference."""
    imported: list[str] = []
    for module_name in BUNDLE_RUNTIME_IMPORTS:
        importlib.import_module(module_name)
        imported.append(module_name)

    import numpy as np
    from PIL import Image
    from local_llm_server.vision import prepare_image_message
    from mlx_vlm.utils import load_image
    from mlx_whisper.audio import log_mel_spectrogram

    with tempfile.TemporaryDirectory(prefix="closedroom-runtime-smoke-") as tmp:
        image_path = Path(tmp) / "frame.png"
        Image.new("RGB", (8, 8), (16, 32, 48)).save(image_path, format="PNG")
        loaded = load_image(image_path)
        if loaded.size != (8, 8):
            raise RuntimeError(f"Unexpected packaged image size: {loaded.size}")
        message = prepare_image_message(image_path, "Describe only visible content.")
        if not message:
            raise RuntimeError("Packaged image message preparation returned no content")

    mel = log_mel_spectrogram(np.zeros(16_000, dtype=np.float32))
    if tuple(mel.shape)[0] != 80:
        raise RuntimeError(f"Unexpected packaged MLX Whisper mel shape: {tuple(mel.shape)}")

    excluded_modules = ("cv2", "datasets", "pyarrow", "pandas", "multiprocess", "torch")
    module_presence = {
        module_name: importlib.util.find_spec(module_name) is not None
        for module_name in excluded_modules
    }
    if any(module_presence.values()):
        raise RuntimeError(f"Excluded non-runtime dependencies still packaged: {module_presence}")

    print(json.dumps({
        "ok": True,
        "imports": imported,
        "image_path_ok": True,
        "mlx_whisper_audio_ok": True,
        "excluded_module_presence": module_presence,
    }, sort_keys=True))


def dispatch_bundled_module(argv: Sequence[str] | None = None) -> bool:
    """Dispatch supported CLI/module calls from the frozen app executable.

    A frozen PyInstaller executable cannot interpret ``-m`` itself: launching
    ``sys.executable -m ...`` starts the ClosedRoom entry point again. The app
    entry point calls this dispatcher before constructing any Cocoa UI.
    """

    arguments = list(sys.argv if argv is None else argv)
    if len(arguments) >= 2 and arguments[1] == BUNDLE_RUNTIME_SMOKE_COMMAND:
        _run_bundle_runtime_smoke()
        return True
    if len(arguments) >= 2 and arguments[1] in SUPPORTED_CLI_COMMANDS:
        from local_asr_server.cli import main

        sys.argv = ["local-asr", *arguments[1:]]
        main()
        return True

    if len(arguments) < 3 or arguments[1] != "-m" or arguments[2] not in SUPPORTED_BUNDLED_MODULES:
        return False

    module = arguments[2]
    sys.argv = [module, *arguments[3:]]
    if module == "local_llm_server":
        from local_llm_server.cli import main

        main()
    elif module == "local_asr_server.runtime.local_llm_entrypoint":
        from local_asr_server.runtime.local_llm_entrypoint import run_local_llm_server_cli

        run_local_llm_server_cli()
    else:
        runpy.run_module(module, run_name="__main__")
    return True
