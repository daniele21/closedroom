#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CREATE_DMG=false
CLEAN_TRANSIENT=false
INSTALL=false
for arg in "$@"; do
  case "$arg" in
    --dmg) CREATE_DMG=true ;;
    --no-dmg) CREATE_DMG=false ;;
    --clean) CLEAN_TRANSIENT=true ;;
    --install) INSTALL=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

[[ "$(uname -s)" == "Darwin" ]] || { echo "Canonical artifact build requires macOS" >&2; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "Canonical artifact build requires Apple Silicon arm64" >&2; exit 1; }
command -v uv >/dev/null 2>&1 || { echo "uv is required" >&2; exit 1; }

APP_NAME="${CLOSEDROOM_APP_NAME:-ClosedRoom}"
APP_VERSION="$(python3 scripts/product_version.py --root "$ROOT")"
SOURCE_REVISION="${CLOSEDROOM_SOURCE_REVISION:-$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)}"
if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then DIRTY=true; else DIRTY=false; fi
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then DEFAULT_CHANNEL="ci"; else DEFAULT_CHANNEL="local"; fi
CHANNEL="${CLOSEDROOM_BUILD_CHANNEL:-$DEFAULT_CHANNEL}"
VARIANT="app"
$CREATE_DMG && VARIANT="package"

if [[ -n "${CLOSEDROOM_BUILD_ID:-}" ]]; then
  BUILD_ID="$CLOSEDROOM_BUILD_ID"
elif [[ -n "${GITHUB_RUN_ID:-}" ]]; then
  BUILD_ID="gh-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
else
  BUILD_ID="local-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import secrets; print(secrets.token_hex(3))')"
fi
BUILD_ID="$(printf '%s' "$BUILD_ID" | tr -cs 'A-Za-z0-9._-' '-')"
LINEAGE="macos-arm64-${CHANNEL}-${VARIANT}"
ARTIFACT_DIR="$ROOT/dist/artifacts/$LINEAGE/$BUILD_ID"
STAGING_APP="$ROOT/dist/${APP_NAME}-${APP_VERSION}.app"
STAGING_DMG="$ROOT/dist/${APP_NAME}-${APP_VERSION}.dmg"
FINAL_BASENAME="${APP_NAME}-${APP_VERSION}-${BUILD_ID}-${SOURCE_REVISION}"
FINAL_APP="$ARTIFACT_DIR/${FINAL_BASENAME}.app"
FINAL_DMG="$ARTIFACT_DIR/${FINAL_BASENAME}.dmg"

cleanup_failed() {
  status=$?
  if [[ $status -ne 0 ]]; then
    rm -rf "$ARTIFACT_DIR"
  fi
  exit $status
}
trap cleanup_failed EXIT

if $CLEAN_TRANSIENT; then
  rm -rf build build_venv dist/wheels .cache/pyinstaller
fi
rm -rf "$STAGING_APP"
rm -f "$STAGING_DMG"
mkdir -p "$ARTIFACT_DIR"

# Build.sh invokes two compile helpers through `uv run --no-sync` and historically
# called the user-facing setup-audio command when the audio-helper cache was cold.
# Prepare a minimal no-dependency editable environment and compile the audio helper
# directly so packaging never installs BlackHole or mutates system audio setup.
if [[ ! -x .venv/bin/python ]]; then
  uv venv .venv --python "${CLOSEDROOM_BUILD_PYTHON_VERSION:-3.10}"
fi
uv pip install --python .venv -e . --no-deps >/dev/null
PYTHONPATH="$ROOT/src" python3 -c 'from local_asr_server.macos_audio_helper.compile import compile_helper; compile_helper(force=False)'

build_args=()
if $CREATE_DMG; then
  build_args+=( )
else
  build_args+=(--no-dmg)
fi
$INSTALL && build_args+=(--install)
./build.sh "${build_args[@]}"

[[ -d "$STAGING_APP" ]] || { echo "Expected staging app missing: $STAGING_APP" >&2; exit 1; }
mv "$STAGING_APP" "$FINAL_APP"
if $CREATE_DMG; then
  [[ -f "$STAGING_DMG" ]] || { echo "Expected staging DMG missing: $STAGING_DMG" >&2; exit 1; }
  mv "$STAGING_DMG" "$FINAL_DMG"
fi

signing="ad-hoc"
[[ -n "${CLOSEDROOM_SIGN_IDENTITY:-}" ]] && signing="identified"
finalize_args=(
  --root "$ROOT"
  --artifact-dir "$ARTIFACT_DIR"
  --app "$FINAL_APP"
  --product "$APP_NAME"
  --version "$APP_VERSION"
  --build-id "$BUILD_ID"
  --source-revision "$SOURCE_REVISION"
  --dirty "$DIRTY"
  --bundle-id "${CLOSEDROOM_APP_BUNDLE_ID:-com.closedroom.app}"
  --signing "$signing"
  --channel "$CHANNEL"
  --variant "$VARIANT"
  --keep "${CLOSEDROOM_LOCAL_ARTIFACT_KEEP:-2}"
)
$CREATE_DMG && finalize_args+=(--dmg "$FINAL_DMG")
python3 scripts/finalize_build_artifact.py "${finalize_args[@]}"

printf '{"build_id":"%s","lineage":"%s","artifact_dir":"%s","app":"%s"}\n' \
  "$BUILD_ID" "$LINEAGE" "$ARTIFACT_DIR" "$FINAL_APP" > "$ROOT/dist/last-build.json"

echo "Canonical artifact finalized: $ARTIFACT_DIR"
trap - EXIT
