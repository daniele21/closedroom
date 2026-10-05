from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import json
from pathlib import Path

import uvicorn

from local_asr_server.runtime.models import (
    DEFAULT_API_PORT,
    DEFAULT_DEV_RELOAD_PORT,
    DEFAULT_LOCAL_LLM_PORT,
    LOCAL_SERVICE_HOST,
)

DEFAULT_SERVER_PORT = DEFAULT_API_PORT
DEV_SERVER_PORT = DEFAULT_DEV_RELOAD_PORT


def _frontend_source_fingerprint(frontend_dir: Path) -> str:
    """Hash frontend sources/config that determine the static bundle."""
    digest = hashlib.sha256()
    roots = [frontend_dir / "src", frontend_dir / "public"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())
    for name in (
        "index.html",
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "tsconfig.node.json",
        "vite.config.ts",
        ".eslintrc.cjs",
    ):
        path = frontend_dir / name
        if path.is_file():
            files.append(path)

    for path in sorted(set(files), key=lambda item: item.relative_to(frontend_dir).as_posix()):
        relative = path.relative_to(frontend_dir).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ensure_dev_frontend_bundle(root: Path | None = None) -> bool:
    """Build source-mode web UI when frontend inputs changed."""
    from local_asr_server.paths import is_bundled

    if is_bundled():
        return False

    root = root or Path(__file__).resolve().parents[2]
    frontend_dir = root / "frontend"
    static_dir = root / "src" / "local_asr_server" / "static"
    if not frontend_dir.is_dir():
        return False

    fingerprint = _frontend_source_fingerprint(frontend_dir)
    cache_dir = root / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    marker = cache_dir / "frontend-build.sha256"
    current = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    static_ready = (static_dir / "index.html").is_file()
    if static_ready and current == fingerprint:
        return False

    if not (frontend_dir / "node_modules").is_dir():
        raise RuntimeError(
            "Frontend dependencies are missing. Run: "
            "cd frontend && corepack pnpm install --frozen-lockfile"
        )

    pnpm = shutil.which("pnpm")
    corepack = shutil.which("corepack")
    if pnpm:
        command = [pnpm, "build"]
    elif corepack:
        command = [corepack, "pnpm", "build"]
    else:
        raise RuntimeError(
            "Frontend sources changed but pnpm/corepack is unavailable. "
            "Install Node/Corepack or build the frontend before starting ClosedRoom."
        )

    print("Frontend sources changed; rebuilding ClosedRoom web UI...")
    subprocess.run(command, cwd=frontend_dir, check=True)
    if not (static_dir / "index.html").is_file():
        raise RuntimeError("Frontend build completed without producing static/index.html")
    marker.write_text(fingerprint + "\n", encoding="utf-8")
    print("ClosedRoom web UI bundle is up to date.")
    return True

def _default_model() -> str:
    local_model_path = Path(
        "~/.lmstudio/models/mlx-community/whisper-large-v3-turbo"
    ).expanduser()
    if local_model_path.exists():
        return str(local_model_path)
    return "mlx-community/whisper-large-v3-turbo"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-asr",
        description="Local ASR server powered by MLX Whisper.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the ASR server.")
    serve.add_argument(
        "--model",
        default=_default_model(),
        help="HF repo or local path to MLX Whisper model.",
    )
    serve.add_argument("--host", default="127.0.0.1", help="Bind address.")
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "HTTP port. Defaults to 1236, or 1237 when --reload is used "
            "so the development server stays separate from the macOS app."
        ),
    )
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Enable reload for development.",
    )
    serve.add_argument(
        "--recordings-dir",
        default=None,
        help=(
            "Override the recordings directory. By default the server follows "
            "the path saved in ClosedRoom Settings."
        ),
    )
    serve.add_argument(
        "--llm-port",
        type=int,
        nargs="?",
        const=DEFAULT_LOCAL_LLM_PORT,
        default=None,
        help=f"Start the local LLM server on this port in parallel (default: {DEFAULT_LOCAL_LLM_PORT}).",
    )
    serve.add_argument(
        "--llm-model",
        default=None,
        help="The local LLM model key to run in local-llm-server (e.g. nemotron-nano-4b-q8, voxtral-mini-3b).",
    )
    serve.add_argument(
        "--llm-model-path",
        default=None,
        help="The direct path to a local GGUF model file.",
    )

    subparsers.add_parser(
        "doctor",
        help="Check the macOS audio capture configuration.",
    )
    subparsers.add_parser(
        "setup-audio",
        help="Install macOS audio routing prerequisites.",
    )
    subparsers.add_parser(
        "app",
        help="Launch ClosedRoom in menu bar mode (macOS only).",
    )
    inspect_meeting = subparsers.add_parser(
        "inspect-meeting",
        help="Print persisted diagnostics for a recording.",
    )
    inspect_meeting.add_argument("recording_id")
    inspect_meeting.add_argument("--json", action="store_true", dest="as_json")

    subparsers.add_parser(
        "transcribe",
        help="Run ASR worker transcription inside a subprocess.",
    )
    return parser


def _inspect_meeting(recording_id: str, *, as_json: bool = False) -> bool:
    from local_asr_server.catalog import CatalogStore
    from local_asr_server.jobs import JobStore

    catalog = CatalogStore()
    transcriptions, _ = catalog.list_transcriptions(page=1, limit=500)
    transcription = next(
        (item for item in transcriptions if item.get("recording_id") == recording_id),
        None,
    )
    jobs = JobStore(catalog.db_path).list_jobs(
        job_type="transcription", scope_type="recording", scope_id=recording_id, limit=20
    )
    from local_asr_server.paths import get_service_log_file
    from local_asr_server.meeting_diagnostics import build_meeting_diagnostic_report
    log_file = get_service_log_file("closedroom", create_parent=False)
    report = build_meeting_diagnostic_report(
        recording_id,
        transcription,
        JobStore(catalog.db_path),
        log_file=log_file,
    )
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Meeting {recording_id}: {report['outcome_status']}")
        for item in report["diagnostics"]:
            backend = item.get("actual_backend") or item.get("requested_backend") or "n/a"
            print(f"- {item.get('component')}: {item.get('status')} [{backend}]")
            if item.get("fallback_used") or item.get("fallback_reason"):
                print(f"  fallback: {item.get('fallback_reason') or 'used'}")
            if item.get("error"):
                print(f"  error: {item['error']}")
        print(f"Jobs: {len(report['jobs'])}; events: {len(report['events'])}; log: {log_file}")
    return transcription is not None or bool(report["jobs"])


def _resolve_serve_port(args: argparse.Namespace) -> int:
    if args.port is not None:
        return args.port
    return DEV_SERVER_PORT if args.reload else DEFAULT_SERVER_PORT


def _print_audio_status() -> bool:
    """Check and display the audio routing configuration status."""
    from local_asr_server.audio_router import AudioRouter

    status = AudioRouter.get_status()

    # Check Swift audio helper
    helper_ok = status.get("audio_helper_available", False)
    swift_check = "OK" if helper_ok else "MISSING"

    checks = (
        ("macOS", status["platform"] == "darwin"),
        ("BlackHole 2ch", status["blackhole_installed"]),
        ("Audio Helper", helper_ok),
    )
    for label, passed in checks:
        print(f"{'OK' if passed else 'MISSING':7} {label}")

    if status.get("physical_output"):
        print(f"        Current output: {status['physical_output']}")

    routing_active = status.get("routing_active", False)
    if routing_active:
        print(f"        Routing:        Active (temporary device)")

    if status["ready_to_record"]:
        print(
            "\nAudio routing is ready."
            "\nMulti-Output devices are created automatically when recording."
        )
        return True

    print("\nAudio routing is not ready.")
    missing = status.get("missing", [])
    if "audio_helper" in missing:
        print("- Audio helper not available. Run: local-asr setup-audio")
    if "blackhole" in missing:
        print("- BlackHole 2ch not installed. Run: brew install blackhole-2ch")
    return False


def _setup_audio() -> None:
    """Install audio prerequisites and compile the Swift helper."""
    if sys.platform != "darwin":
        raise SystemExit("setup-audio is supported only on macOS.")
    brew = shutil.which("brew")
    if not brew:
        raise SystemExit("Homebrew is required: https://brew.sh")

    # Install BlackHole (SwitchAudioSource no longer required)
    print("Installing BlackHole 2ch...")
    subprocess.run(
        [brew, "install", "blackhole-2ch"],
        check=True,
    )

    # Compile the Swift audio helper
    print("\nCompiling Core Audio helper...")
    try:
        from local_asr_server.macos_audio_helper.compile import compile_helper
        binary_path = compile_helper(force=True)
        print(f"Audio helper compiled: {binary_path}")
    except RuntimeError as exc:
        print(f"WARNING: Failed to compile audio helper: {exc}")
        print("You may need to install Xcode Command Line Tools:")
        print("  xcode-select --install")
        return

    print(
        "\nSetup complete! Multi-Output devices are now created "
        "automatically when you start a recording.\n"
        "No manual Audio MIDI Setup configuration is needed.\n"
        "Run 'local-asr doctor' to verify."
    )


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    if not argv:
        argv = ["serve"]
    args = parser.parse_args(argv)

    if args.command == "doctor":
        if not _print_audio_status():
            raise SystemExit(1)
        return
    if args.command == "setup-audio":
        _setup_audio()
        return
    if args.command == "app":
        _ensure_dev_frontend_bundle()
        from local_asr_server.menubar import main as menubar_main
        menubar_main()
        return
    if args.command == "inspect-meeting":
        if not _inspect_meeting(args.recording_id, as_json=args.as_json):
            raise SystemExit(1)
        return
    if args.command == "transcribe":
        _run_transcribe_worker()
        return
    if args.command != "serve":
        parser.print_help()
        return

    _ensure_dev_frontend_bundle()

    from local_asr_server.server import create_app
    from local_asr_server.runtime.port_manager import (
        clear_api_runtime,
        prepare_api_port,
        register_api_runtime,
    )

    port = _resolve_serve_port(args)
    prepare_api_port(port, host=args.host)
    register_api_runtime(port, host=args.host)
    app = create_app(
        default_model=args.model,
        recordings_dir=Path(args.recordings_dir).expanduser() if args.recordings_dir else None,
    )

    llm_process = None
    if args.llm_port:
        from local_asr_server.settings import load_settings, save_settings
        settings = load_settings()
        settings["local_llm_mode"] = "external"
        settings["local_llm_url"] = f"http://{LOCAL_SERVICE_HOST}:{args.llm_port}"
        
        # Get model key from args, settings, or default
        llm_model = args.llm_model or settings.get("local_llm_model") or "nemotron-nano-4b-q8"
        from local_asr_server.runtime.models import resolve_local_llm_model_path
        llm_model_path = args.llm_model_path or resolve_local_llm_model_path(settings, llm_model)
        settings["local_llm_model"] = llm_model
        settings["local_llm_model_path"] = llm_model_path
        save_settings(settings)

        # Build command to start local-llm-server
        visual_model = settings.get("visual_llm_model") or "qwen3-vl-4b"
        cmd = [
            sys.executable, "-m", "local_llm_server", "serve",
            "--host", LOCAL_SERVICE_HOST, "--port", str(args.llm_port),
            "--enable-admin-api",
            "--models", llm_model, visual_model
        ]

        binary = shutil.which("local-llm-server")
        if binary:
            cmd = [
                binary, "serve",
                "--host", LOCAL_SERVICE_HOST, "--port", str(args.llm_port),
                "--enable-admin-api",
                "--models", llm_model, visual_model
            ]
        
        desc = f"path: {llm_model_path}" if llm_model_path else f"model: {llm_model}"
        print(f"Starting local LLM server ({desc}) on port {args.llm_port} in background...")
        llm_process = subprocess.Popen(cmd)

    try:
        if args.reload:
            import os
            if args.model:
                os.environ["CLOSEDROOM_DEFAULT_MODEL"] = args.model
            if args.recordings_dir:
                os.environ["CLOSEDROOM_RECORDINGS_DIR"] = str(Path(args.recordings_dir).expanduser())
            uvicorn.run(
                "local_asr_server.server:app",
                host=args.host,
                port=port,
                reload=True,
            )
        else:
            uvicorn.run(
                app,
                host=args.host,
                port=port,
                reload=False,
            )
    finally:
        clear_api_runtime(port, host=args.host)
        if llm_process:
            print("Stopping local LLM server...")
            llm_process.terminate()
            try:
                llm_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                llm_process.kill()


def _run_transcribe_worker() -> None:
    import sys
    import json
    import contextlib
    from local_asr_server.transcriber import transcribe_file_sync

    class IPCStdoutCapture:
        def __init__(self):
            self._buffer = []

        def write(self, data: str) -> None:
            if not data:
                return
            self._buffer.append(data)
            if data.endswith("\n"):
                line = "".join(self._buffer).rstrip("\r\n")
                self._buffer = []
                if line:
                    if line.startswith("ASR_PROGRESS:"):
                        processed = float(line.split(":", 1)[1])
                        sys.__stdout__.write(json.dumps({
                            "type": "progress",
                            "phase": "transcribing",
                            "processed_audio_seconds": processed,
                        }, ensure_ascii=False) + "\n")
                        sys.__stdout__.flush()
                    elif line.startswith("DOWNLOAD_PROGRESS:"):
                        parts = line.split(":")
                        if len(parts) >= 4:
                            percent = float(parts[1])
                            sys.__stdout__.write(json.dumps({"type": "progress", "percent": percent, "message": line}, ensure_ascii=False) + "\n")
                            sys.__stdout__.flush()
                    else:
                        sys.__stdout__.write(json.dumps({"type": "progress", "message": line}, ensure_ascii=False) + "\n")
                        sys.__stdout__.flush()

        def flush(self) -> None:
            sys.__stdout__.flush()

    try:
        config_str = sys.stdin.read()
        kwargs = json.loads(config_str)
        
        capture = IPCStdoutCapture()
        with contextlib.redirect_stdout(capture):
            result = transcribe_file_sync(**kwargs)
            
        sys.__stdout__.write(json.dumps({"type": "result", "data": result}, ensure_ascii=False) + "\n")
        sys.__stdout__.flush()
    except Exception as e:
        import traceback
        err_msg = f"{e}\n{traceback.format_exc()}"
        sys.__stdout__.write(json.dumps({"type": "error", "message": err_msg}, ensure_ascii=False) + "\n")
        sys.__stdout__.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()