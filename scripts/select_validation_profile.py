#!/usr/bin/env python3
"""Select ClosedRoom validation depth, risks and required gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

RANK = {"lean": 0, "scoped": 1, "strong": 2, "full": 3}
STAGES = ("iteration", "integration", "release")
FULL_EXACT = {
    ".engineering/baseline.json", ".engineering/commands.json",
    ".github/workflows/preflight.yml", ".github/workflows/repository-health.yml",
    "ClosedRoom.spec", "build.sh", "create_dmg.sh", "pyproject.toml", "setup.sh", "uv.lock",
    "scripts/finalize_build_artifact.py", "scripts/select_validation_profile.py",
    "scripts/verify_operations.py", "scripts/verify_repository.py", "scripts/verify_e2e.py",
    "scripts/verify_stage_environment_policy.py",
}
FULL_PREFIXES = (".github/workflows/", "build_assets/")
STRONG_EXACT = {
    ".engineering/e2e.json", "scripts/macos_ax_helper.swift", "scripts/macos_ui_driver.py",
    "scripts/real_environment_smoke.py", "scripts/real_environment_ui_evidence.py",
    "scripts/smoke_packaged_app.py", "src/local_asr_server/catalog.py",
    "src/local_asr_server/recordings.py", "src/local_asr_server/server.py",
    "src/local_asr_server/settings.py",
}
STRONG_PREFIXES = (
    "src/local_asr_server/jobs/", "src/local_asr_server/macos_audio_helper/",
    "src/local_asr_server/native_capture", "src/local_asr_server/runtime/",
    "src/local_asr_server/services/", "src/local_asr_server/speaker_",
    "src/local_asr_server/visual_intelligence/",
)
MEETING_BROWSER_E2E_EXACT = {
    "frontend/src/pages/MeetingDetailPage.tsx",
    "frontend/src/hooks/useMeetingJobEvents.ts",
    "frontend/src/hooks/useVisualIntelligence.ts",
    "scripts/browser_archive_search_e2e.mjs",
    "scripts/browser_meeting_note_edit_e2e.mjs",
    "scripts/browser_meeting_preparation_e2e.mjs",
    "scripts/browser_meeting_ui_e2e.mjs",
    "scripts/browser_record_while_ai_busy_e2e.mjs",
    "scripts/browser_saved_meeting_e2e.mjs",
    "scripts/browser_workspace_coherence_e2e.mjs",
}
MEETING_BROWSER_E2E_RELEVANT_EXACT = MEETING_BROWSER_E2E_EXACT | {
    "src/local_asr_server/analysis_jobs.py",
    "src/local_asr_server/meeting_preparation.py",
    "src/local_asr_server/routers/helpers.py",
    "src/local_asr_server/services/analysis_service.py",
    "src/local_asr_server/structured_notes.py",
    "src/local_asr_server/structured_notes_projection.py",
}
LEAN_EXACT = {
    ".editorconfig", ".gitignore", ".github/pull_request_template.md",
    "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "README.md", "SECURITY.md",
}
LEAN_PREFIXES = ("design/", "docs/", "skills/")
SCOPED_PREFIXES = ("frontend/", "src/", "test/", "scripts/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--stage", choices=STAGES, default="integration")
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    return parser.parse_args()


def _git_changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], check=True, capture_output=True, text=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def classify_path(path: str) -> tuple[str, str, str]:
    normalized = Path(path).as_posix()
    if normalized in FULL_EXACT or normalized.startswith(FULL_PREFIXES):
        return "full", "global_validation_build", "validation/build/dependency machinery changed"
    if normalized in STRONG_EXACT or normalized.startswith(STRONG_PREFIXES):
        return "strong", "runtime_native_persistence_e2e", "runtime/native/persistence/E2E boundary changed"
    if normalized in MEETING_BROWSER_E2E_EXACT:
        return "scoped", "meeting_ui_integration", "saved-Meeting browser journey behavior changed"
    if normalized in LEAN_EXACT or normalized.startswith(LEAN_PREFIXES):
        return "lean", "governance", "documentation/governance-only path"
    if normalized.startswith(SCOPED_PREFIXES):
        return "scoped", "contained_implementation", "contained implementation/test/frontend path"
    return "full", "unknown_executable_or_owner", "unclassified path fails safe to full"


def gates_for(profile: str, risks: list[str], stage: str) -> list[str]:
    gates = ["governance"]
    if stage == "iteration":
        return gates
    if profile != "lean":
        gates.append("source-tests")
    if "meeting_ui_integration" in risks:
        gates.append("browser-e2e")
    if profile in {"strong", "full"} or "runtime_native_persistence_e2e" in risks:
        gates.append("packaged-app")
    if stage == "release":
        for gate in ("source-tests", "packaged-app"):
            if gate not in gates:
                gates.append(gate)
        gates.append("release-critical")
    return gates


def select_profile(paths: list[str], stage: str = "integration") -> dict[str, object]:
    unique_paths = sorted(set(paths))
    classifications: list[dict[str, str]] = []
    selected = "lean"
    reasons: list[str] = []
    risks: list[str] = []
    if not unique_paths:
        reasons = ["no changed paths detected; cheapest structural validation"]
    for path in unique_paths:
        normalized = Path(path).as_posix()
        profile, risk, reason = classify_path(path)
        classifications.append({"path": path, "profile": profile, "risk": risk, "reason": reason})
        if risk not in risks:
            risks.append(risk)
        if normalized in MEETING_BROWSER_E2E_RELEVANT_EXACT and "meeting_ui_integration" not in risks:
            risks.append("meeting_ui_integration")
        if RANK[profile] > RANK[selected]:
            selected = profile
            reasons = [f"{path}: {reason}"]
        elif RANK[profile] == RANK[selected]:
            reasons.append(f"{path}: {reason}")
    if stage == "release":
        selected = "full"
        if "release_boundary" not in risks:
            risks.append("release_boundary")
        reasons.insert(0, "release boundary requires full validation")
    return {
        "stage": stage,
        "profile": selected,
        "reason": "; ".join(reasons[:4]),
        "risk_dimensions": risks,
        "required_gates": gates_for(selected, risks, stage),
        "changed_files": unique_paths,
        "classifications": classifications,
    }


def main() -> int:
    args = parse_args()
    try:
        paths = args.changed_file or (_git_changed_files(args.base, args.head) if args.base else [])
    except subprocess.CalledProcessError as exc:
        print(f"validation profile selection failed: {exc.stderr or exc}", file=sys.stderr)
        return 2
    result = select_profile(paths, args.stage)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.format == "github":
        print(f"stage={result['stage']}")
        print(f"profile={result['profile']}")
        print(f"reason={str(result['reason']).replace(chr(10), ' ')}")
        print(f"risk_dimensions={','.join(result['risk_dimensions'])}")
        print(f"required_gates={','.join(result['required_gates'])}")
        print(f"changed_count={len(result['changed_files'])}")
    else:
        print(f"STAGE={str(result['stage']).upper()}")
        print(f"PROFILE={str(result['profile']).upper()}")
        print(f"RISKS={','.join(result['risk_dimensions'])}")
        print(f"REQUIRED_GATES={','.join(result['required_gates'])}")
        print(f"REASON={result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())