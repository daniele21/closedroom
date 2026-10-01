#!/usr/bin/env python3
"""Update the local-llm-server dependency from a reproducible GitHub source."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
LOCK_PATH = PROJECT_ROOT / "uv.lock"
DEFAULT_REPOSITORY_URL = "https://github.com/daniele21/local-llm-server.git"
DEFAULT_BRANCH = "main"
TAG_PATTERN = re.compile(r"refs/tags/v?(\d+)\.(\d+)\.(\d+)$")
DEPENDENCY_PATTERN = re.compile(
    r'(?P<prefix>"local-llm-server(?:\[[A-Za-z0-9_,.-]+\])?\s*@\s*)'
    r'(?P<source>[^"\n]+)(?P<suffix>")'
)
RELEASE_WHEEL_PATTERN = re.compile(
    r"/releases/download/v(?P<version>\d+\.\d+\.\d+)/"
    r"local_llm_server-(?P=version)-py3-none-any\.whl(?:#sha256=(?P<sha>[0-9a-f]{64}))?$"
)
FILE_WHEEL_PATTERN = re.compile(
    r"^file://.+/local_llm_server-(?P<version>\d+\.\d+\.\d+)-py3-none-any\.whl$"
)
GIT_SOURCE_PATTERN = re.compile(r"^git\+(?P<url>.+)@(?P<revision>[0-9a-f]{40})$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        return f"v{self}"


@dataclass(frozen=True)
class DependencyIdentity:
    kind: str
    version: Version | None = None
    revision: str | None = None
    source: str = ""

    def display(self) -> str:
        if self.revision:
            return f"{self.kind}:{self.revision}"
        if self.version:
            return f"{self.kind}:{self.version}"
        return self.kind


def latest_version_from_ls_remote(output: str) -> Version:
    versions = []
    for line in output.splitlines():
        match = TAG_PATTERN.search(line.strip())
        if match:
            versions.append(Version(*(int(value) for value in match.groups())))
    if not versions:
        raise RuntimeError("Nessun tag semver stabile trovato nel repository local-llm-server")
    return max(versions)


def revision_from_ls_remote(output: str, *, ref: str) -> str:
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1] == ref and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            return parts[0]
    raise RuntimeError(f"Impossibile risolvere la revisione Git per {ref}")


def dependency_identity(pyproject: str) -> DependencyIdentity:
    match = DEPENDENCY_PATTERN.search(pyproject)
    if not match:
        raise RuntimeError("Dipendenza local-llm-server non trovata in pyproject.toml")
    source = match.group("source")
    git_match = GIT_SOURCE_PATTERN.match(source)
    if git_match:
        return DependencyIdentity(kind="git", revision=git_match.group("revision"), source=source)
    release_match = RELEASE_WHEEL_PATTERN.search(source)
    if release_match:
        version = Version(*(int(value) for value in release_match.group("version").split(".")))
        return DependencyIdentity(kind="release", version=version, source=source)
    file_match = FILE_WHEEL_PATTERN.match(source)
    if file_match:
        version = Version(*(int(value) for value in file_match.group("version").split(".")))
        return DependencyIdentity(kind="file", version=version, source=source)
    return DependencyIdentity(kind="unknown", source=source)


def dependency_version(pyproject: str) -> Version | None:
    return dependency_identity(pyproject).version


def replace_dependency_source(pyproject: str, source: str) -> str:
    updated, count = DEPENDENCY_PATTERN.subn(
        lambda match: f"{match.group('prefix')}{source}{match.group('suffix')}",
        pyproject,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Impossibile aggiornare la dipendenza local-llm-server")
    return updated


def replace_dependency(pyproject: str, wheel_path: Path) -> str:
    """Backward-compatible helper used by older tooling/tests."""
    return replace_dependency_source(pyproject, f"file://{wheel_path.resolve()}")


def git_dependency_source(repository_url: str, revision: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full 40-character Git SHA")
    url = repository_url.strip()
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.removeprefix("git@github.com:")
    if not url.startswith(("https://", "http://")):
        raise RuntimeError(f"Remote Git non supportato per dependency source: {repository_url}")
    return f"git+{url}@{revision}"


def release_dependency_source(repository_url: str, version: Version, sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("sha256 must be a lowercase 64-character digest")
    slug = github_repository_slug(repository_url)
    wheel_name = f"local_llm_server-{version}-py3-none-any.whl"
    return (
        f"https://github.com/{slug}/releases/download/{version.tag}/{wheel_name}"
        f"#sha256={sha256}"
    )


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"Comando fallito ({result.returncode}): {' '.join(command)}\n{detail}")
    return result.stdout if capture else ""


def atomic_write(path: Path, contents: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def resolve_repository_url(local_repo: Path) -> str:
    override = os.environ.get("LOCAL_LLM_SERVER_GITHUB_URL")
    if override:
        return override
    if (local_repo / ".git").exists():
        try:
            remote = run(["git", "remote", "get-url", "origin"], cwd=local_repo, capture=True).strip()
            if remote:
                return remote
        except RuntimeError:
            pass
    return DEFAULT_REPOSITORY_URL


def github_repository_slug(repository_url: str) -> str:
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", repository_url)
    if not match:
        raise RuntimeError(f"Remote GitHub non riconosciuto: {repository_url}")
    return f"{match.group(1)}/{match.group(2)}"


def ensure_release_wheel(version: Version, repository_url: str) -> Path:
    gh = shutil.which("gh")
    if gh is None:
        raise RuntimeError("GitHub CLI (gh) non trovato: necessario per scaricare il wheel della release")
    temporary = Path(tempfile.mkdtemp(prefix="closedroom-local-llm-wheel-"))
    wheel = temporary / f"local_llm_server-{version}-py3-none-any.whl"
    run([
        gh,
        "release",
        "download",
        version.tag,
        "--repo",
        github_repository_slug(repository_url),
        "--pattern",
        wheel.name,
        "--dir",
        str(temporary),
    ])
    if not wheel.exists():
        raise RuntimeError(f"La release {version.tag} non pubblica il wheel atteso {wheel.name}")
    return wheel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_lock(pyproject_original: bytes, lock_original: bytes | None) -> None:
    try:
        run([shutil.which("uv") or "uv", "lock"], cwd=PROJECT_ROOT)
    except Exception:
        atomic_write(PYPROJECT_PATH, pyproject_original)
        if lock_original is None:
            LOCK_PATH.unlink(missing_ok=True)
        else:
            atomic_write(LOCK_PATH, lock_original)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Mostra la revisione/versione target senza modificare file")
    parser.add_argument(
        "--source",
        choices=("main", "release"),
        default="main",
        help="main: pin a exact source SHA and let uv build it; release: pin published wheel + sha256",
    )
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch local-llm-server da risolvere con --source main")
    parser.add_argument("--revision", help="SHA esatto da usare con --source main invece di risolvere il branch")
    parser.add_argument(
        "--local-repo",
        type=Path,
        default=PROJECT_ROOT.parent / "local-llm-server",
        help="Worktree locale usato solo per risolvere il remote origin quando disponibile",
    )
    args = parser.parse_args()

    local_repo = args.local_repo.expanduser().resolve()
    repository_url = resolve_repository_url(local_repo)
    pyproject_original = PYPROJECT_PATH.read_bytes()
    pyproject_text = pyproject_original.decode("utf-8")
    current = dependency_identity(pyproject_text)

    if args.source == "main":
        if args.revision:
            revision = args.revision.lower()
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise RuntimeError("--revision deve essere uno SHA Git completo di 40 caratteri")
        else:
            ref = f"refs/heads/{args.branch}"
            remote = run(["git", "ls-remote", repository_url, ref], capture=True)
            revision = revision_from_ls_remote(remote, ref=ref)
        target_source = git_dependency_source(repository_url, revision)
        target_display = f"git:{revision}"
    else:
        tags = run(["git", "ls-remote", "--tags", "--refs", repository_url], capture=True)
        version = latest_version_from_ls_remote(tags)
        wheel = ensure_release_wheel(version, repository_url)
        try:
            target_source = release_dependency_source(repository_url, version, sha256_file(wheel))
        finally:
            shutil.rmtree(wheel.parent, ignore_errors=True)
        target_display = f"release:{version}"

    print(f"local-llm-server: corrente={current.display()} target={target_display}")
    if args.check:
        if args.source == "main":
            return 0 if current.kind == "git" and current.revision == revision else 1
        return 0 if current.kind == "release" and current.version == version else 1

    updated = replace_dependency_source(pyproject_text, target_source)
    if updated == pyproject_text:
        print("Nessun aggiornamento necessario")
        return 0

    lock_original = LOCK_PATH.read_bytes() if LOCK_PATH.exists() else None
    atomic_write(PYPROJECT_PATH, updated.encode("utf-8"))
    update_lock(pyproject_original, lock_original)
    print(f"Aggiornato local-llm-server a {target_display}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"errore: {error}", file=sys.stderr)
        raise SystemExit(2)
