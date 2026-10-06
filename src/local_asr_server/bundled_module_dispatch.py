from __future__ import annotations

import importlib
import json
import runpy
import sys
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
)


def _run_bundle_runtime_smoke() -> None:
    """Import the packaged dynamic AI surfaces without starting model inference."""
    imported: list[str] = []
    for module_name in BUNDLE_RUNTIME_IMPORTS:
        importlib.import_module(module_name)
        imported.append(module_name)
    print(json.dumps({"ok": True, "imports": imported}, sort_keys=True))


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
