from __future__ import annotations

import os
import hmac
import secrets
import tempfile
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from local_asr_server.analysis_jobs import AnalysisJobManager
from local_asr_server.app_services import AppServices, install_compatibility_aliases
from local_asr_server.app_identity import get_app_version
from local_asr_server.audio_router import AudioRouter
from local_asr_server.catalog import CatalogStore
from local_asr_server.jobs import JobStore
from local_asr_server.native_capture import NativeCaptureManager
from local_asr_server.recordings import RecordingStore
from local_asr_server.transcription_jobs import TranscriptionJobManager
from local_asr_server.paths import get_static_dir
from local_asr_server.runtime.resource_policy import ResourcePolicy, recording_has_active_capture
from local_asr_server.runtime.service_manager import RuntimeServiceManager
from local_asr_server.runtime.workload_arbiter import HeavyWorkloadArbiter
from local_asr_server.services.transcription_service import TranscriptionService
from local_asr_server.transcriber import transcribe_file_sync
from local_asr_server.app_logging import configure_application_logging

from local_asr_server.routers.helpers import (
    _env_bool,
    _parse_allowed_origins,
    _extract_bearer_token,
)
from local_asr_server.routers import (
    analysis,
    capture_admission,
    demo,
    recordings,
    settings,
    transcriptions,
    system,
    visual_jobs,
    workspace,
)

PUBLIC_AUTH_PATHS = {
    "/",
    "/health",
    "/v1/session",
    "/favicon.svg",
    "/logo.svg",
    "/logo-dark.svg",
    "/logo-light.svg",
}


def create_app(
    default_model: str = "mlx-community/whisper-large-v3-turbo",
    recordings_dir: Path | None = None,
    *,
    enable_auth: bool | None = None,
    allowed_origins: list[str] | None = None,
) -> FastAPI:
    if default_model == "mlx-community/whisper-large-v3-turbo":
        default_model = os.environ.get("CLOSEDROOM_DEFAULT_MODEL", default_model)
    if recordings_dir is None:
        env_rec_dir = os.environ.get("CLOSEDROOM_RECORDINGS_DIR")
        if env_rec_dir:
            recordings_dir = Path(env_rec_dir)

    app = FastAPI(
        title="ClosedRoom",
        version=get_app_version(),
        description="Local ASR transcription server powered by MLX Whisper.",
    )

    cors_origins = allowed_origins if allowed_origins is not None else _parse_allowed_origins(os.environ.get("LOCAL_ASR_ALLOWED_ORIGINS"))
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.state.default_model = default_model
    capture_manager = NativeCaptureManager()
    runtime_services = RuntimeServiceManager()
    from local_asr_server.runtime.leases import ModelRuntimeLeaseManager
    ModelRuntimeLeaseManager.set_service_manager(runtime_services)
    transcription_service = TranscriptionService()
    app.state.auth_enabled = _env_bool("LOCAL_ASR_REQUIRE_AUTH", True) if enable_auth is None else enable_auth
    app.state.api_token = os.environ.get("LOCAL_ASR_API_TOKEN") or secrets.token_urlsafe(32)
    
    from local_asr_server import transcriptions as transcriptions_module
    temp_root = Path(tempfile.gettempdir()).resolve()
    transcriptions_root = Path(
        transcriptions_module.load_settings()["transcriptions_dir"]
    ).expanduser().resolve()
    if temp_root in transcriptions_root.parents or transcriptions_root == temp_root:
        catalog_path = transcriptions_root / "closedroom.db"
    elif recordings_dir is not None and temp_root in recordings_dir.expanduser().resolve().parents:
        catalog_path = recordings_dir.expanduser().resolve() / "closedroom.db"
    else:
        catalog_path = CatalogStore.default_db_path()
    app.state.app_log_file = configure_application_logging(fallback_dir=catalog_path.parent)

    catalog_store = CatalogStore(catalog_path)
    app.state.prompts_file = catalog_path.parent / "prompts.json" if temp_root in catalog_path.resolve().parents else None
    job_store = JobStore(catalog_path)
    interrupted_jobs = job_store.interrupt_incomplete()
    catalog_store.interrupt_analysis_runs_for_jobs(
        [job["id"] for job in interrupted_jobs if job["type"] == "analysis"],
        reason="Interrupted by server restart",
    )
    recording_store = RecordingStore(
        recordings_dir or Path("~/Recordings/local-asr"),
        use_settings_dir=recordings_dir is None,
        catalog=catalog_store,
    )

    # RecordingStore is the existing canonical capture-state owner. ResourcePolicy
    # narrows its durable UI/recovery state to actual capture signals, while
    # HeavyWorkloadArbiter remains the only heavy-work scheduler.
    resource_policy = ResourcePolicy(
        capture_active=lambda: recording_has_active_capture(recording_store.active_recording()),
    )
    heavy_workloads = HeavyWorkloadArbiter.from_env(
        admission_guard=resource_policy.assert_heavy_work_admissible,
    )
    app.state.resource_policy = resource_policy
    app.state.heavy_workload_arbiter = heavy_workloads
    transcription_jobs = TranscriptionJobManager(job_store, arbiter=heavy_workloads)
    
    import logging
    logger = logging.getLogger("uvicorn.error")

    @app.on_event("startup")
    def _report_runtime_mode():
        llm_status = runtime_services.llm_status()
        llm_mode = llm_status.get("mode", "disabled")
        
        # Color formatting
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        # Show ClosedRoom Web UI URL
        print(f"\n{BOLD}{GREEN}[★] ClosedRoom Web UI: {RESET}{BOLD}http://127.0.0.1:1236/{RESET}\n")

        if llm_mode == "auto":
            # Managed local AI is intentionally cold at application startup.
            # RuntimeServiceManager.ensure_llm_ready() starts it on the first
            # local AI phase, avoiding speculative model/process residency.
            print("Local LLM: managed on demand (cold until first local AI request)")
            logger.info("Local LLM: managed on demand; sidecar remains cold at startup")
        elif llm_mode == "external":
            ext_url = llm_status.get("url", "")
            print(f"\n{BOLD}{CYAN}[★] External LLM Server: {RESET}{BOLD}{ext_url}/{RESET}\n")
            logger.info(f"Local LLM: mode is 'external' (using configured URL: {ext_url})")
        else:
            print("Local LLM: disabled")
            logger.info("Local LLM: disabled")

    from local_asr_server.transcriptions import TranscriptionStore
    transcription_store = TranscriptionStore(catalog=catalog_store)
    from local_asr_server.transcription_diarization import TranscriptionDiarizationService
    services = AppServices(
        capture=capture_manager,
        runtime=runtime_services,
        transcription=transcription_service,
        catalog=catalog_store,
        jobs=job_store,
        transcription_jobs=transcription_jobs,
        diarization=TranscriptionDiarizationService(),
        analysis_jobs=cast(AnalysisJobManager, None),
        recordings=recording_store,
        transcriptions=transcription_store,
    )
    services.analysis_jobs = AnalysisJobManager(services, job_store, arbiter=heavy_workloads)
    install_compatibility_aliases(app, services)

    # Clean up any orphan aggregate devices from previous runs/crashes
    AudioRouter.cleanup_orphans()

    # Set up static files serving — resolves correctly in both dev and bundle.
    static_dir = get_static_dir()
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    public_dir = Path(__file__).parents[2] / "public"
    if public_dir.exists():
        app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")

    @app.middleware("http")
    async def require_local_auth(request: Request, call_next):
        if (
            not app.state.auth_enabled
            or request.url.path in PUBLIC_AUTH_PATHS
            or request.url.path.startswith("/static/")
            or request.url.path.startswith("/public/")
            or request.url.path.startswith("/assets/")
        ):
            return await call_next(request)
        token = (
            _extract_bearer_token(request.headers.get("authorization"))
            or request.cookies.get("closedroom_session")
        )
        if not token or not hmac.compare_digest(token, app.state.api_token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/")
    def read_index() -> FileResponse:
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    # Include routers
    app.include_router(analysis.router)
    app.include_router(capture_admission.router)
    app.include_router(demo.router)
    app.include_router(recordings.router)
    app.include_router(settings.router)
    app.include_router(transcriptions.router)
    app.include_router(system.router)
    app.include_router(visual_jobs.router)
    app.include_router(workspace.router)

    # Mount root static files at the end so it doesn't override API routes
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="root_static")

    @app.on_event("shutdown")
    def shutdown_event():
        heavy_workloads.shutdown(cancel_pending=True, wait_timeout=2.0)
        print("Stopping local LLM sidecar...")
        logger.info("Stopping local LLM sidecar...")
        runtime_services.shutdown()

    return app


# Exposed for uvicorn --reload import string loading
app = create_app()
