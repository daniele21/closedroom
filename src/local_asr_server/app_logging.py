from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from local_asr_server.paths import get_service_log_file

APP_LOG_NAME = "closedroom"
APP_LOG_HANDLER_NAME = "closedroom-rotating-file"


def configure_application_logging(fallback_dir: Path | None = None) -> str:
    """Install the bounded persistent application log once per process."""
    try:
        log_file = get_service_log_file(APP_LOG_NAME)
    except OSError:
        if fallback_dir is None:
            raise
        fallback_dir.mkdir(parents=True, exist_ok=True)
        log_file = fallback_dir / f"{APP_LOG_NAME}.log"
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == APP_LOG_HANDLER_NAME and getattr(existing, "baseFilename", None) != str(log_file):
            root.removeHandler(existing)
            existing.close()
    if not any(getattr(handler, "baseFilename", None) == str(log_file) for handler in root.handlers):
        try:
            handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        except OSError:
            if fallback_dir is None:
                raise
            fallback_dir.mkdir(parents=True, exist_ok=True)
            log_file = fallback_dir / f"{APP_LOG_NAME}.log"
            handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.set_name(APP_LOG_HANDLER_NAME)
        root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    return str(log_file)
