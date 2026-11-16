"""macOS-only, best-effort handoff after the canonical profile lock rejects a second app.

This module never unlocks a profile, stops a peer, or derives ownership from a
port/health response. A running-app match is only a user-facing navigation hint.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

from local_asr_server.paths import APP_BUNDLE_ID

logger = logging.getLogger(__name__)


def _current_app_bundle() -> Path | None:
    executable = Path(sys.executable)
    if executable.parent.name != "MacOS" or executable.parent.parent.name != "Contents":
        return None
    return executable.parent.parent.parent.resolve()


def handle_existing_instance() -> str:
    """Focus a uniquely identified same-build app, or explain a version conflict.

    Do not assume that an app with the same bundle ID owns the profile lock:
    when evidence is ambiguous, provide instructions instead of taking action.
    """
    if sys.platform != "darwin":
        return "unavailable"
    try:
        import AppKit

        current = _current_app_bundle()
        running = [
            app for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            if app.bundleIdentifier() == APP_BUNDLE_ID
            and app.processIdentifier() != os.getpid()
            and not app.isTerminated()
        ]
        single = running[0] if len(running) == 1 else None
        other_bundle = None
        if single is not None:
            bundle_url = single.bundleURL()
            if bundle_url is not None and bundle_url.path():
                other_bundle = Path(str(bundle_url.path())).resolve()

        activation_options = getattr(
            AppKit, "NSRunningApplicationActivateIgnoringOtherApps", 1 << 1,
        )
        if single is not None and current is not None and other_bundle == current:
            if single.activateWithOptions_(activation_options):
                logger.info("Existing ClosedRoom app activated; shared profile remains locked")
                return "focused"

        alert = AppKit.NSAlert.alloc().init()
        alert.setAlertStyle_(getattr(AppKit, "NSAlertStyleInformational", 1))
        alert.setMessageText_("ClosedRoom è già aperto")
        if single is not None and other_bundle is not None and other_bundle != current:
            alert.setInformativeText_(
                "Un'altra versione di ClosedRoom sta usando i dati locali. "
                "Per aprire questa versione, termina normalmente l'altra dal menu "
                "ClosedRoom > Esci, dopo aver completato registrazioni ed elaborazioni. "
                "Nessun processo verrà chiuso automaticamente."
            )
        else:
            alert.setInformativeText_(
                "I dati locali sono già in uso. Apri l'istanza esistente oppure "
                "chiudila normalmente prima di riprovare. "
                "Le registrazioni non vengono interrotte automaticamente."
            )
        if single is not None:
            alert.addButtonWithTitle_("Mostra app aperta")
        else:
            alert.addButtonWithTitle_("OK")
        alert.addButtonWithTitle_("Annulla")
        selected = alert.runModal()
        if single is not None and selected == 1000:
            if single.activateWithOptions_(activation_options):
                logger.info("Existing ClosedRoom app activated after user choice")
                return "focused"
        return "explained"
    except Exception:
        logger.exception("Unable to present native ClosedRoom instance handoff")
        return "unavailable"
