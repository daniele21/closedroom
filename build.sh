#!/usr/bin/env bash
# =============================================================================
# build.sh — ClosedRoom macOS App Build Script
#
# Produces:  dist/ClosedRoom-<version>.app   (self-contained .app bundle)
#            dist/ClosedRoom-<version>.dmg   (distributable disk image)
#
# Usage:
#   ./build.sh                           # full build (ad-hoc signed)
#   ./build.sh --no-dmg                  # skip DMG creation
#   ./build.sh --clean                   # clean build artifacts first
#   ./build.sh --install                 # copy to /Applications after build
#
# Code Signing (TCC/Privacy Permissions):
#   By default, the app is signed ad-hoc (--sign -), which causes macOS to
#   treat every new build as a different identity and reset TCC permissions
#   (microphone, screen recording) on each install.
#
#   To keep permissions stable across builds, set a real Apple signing identity:
#
#     export CLOSEDROOM_SIGN_IDENTITY="Apple Development: Your Name (TEAMID)"
#     ./build.sh --no-dmg
#
#   List available identities:
#     security find-identity -v -p codesigning
#
#   --install with ad-hoc signing is blocked to prevent TCC confusion.
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
APP_NAME="${CLOSEDROOM_APP_NAME:-ClosedRoom}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="$(python3 "$SCRIPT_DIR/scripts/product_version.py" --root "$SCRIPT_DIR")"
BUNDLE_ID="${CLOSEDROOM_APP_BUNDLE_ID:-com.closedroom.app}"
BUILD_PYTHON_VERSION="${CLOSEDROOM_BUILD_PYTHON_VERSION:-3.10}"
BUILD_ASSETS="$SCRIPT_DIR/build_assets"
# uv refuses to build a source tree when its cache lives inside that same tree.
# Keep the packaging cache outside the repository while still allowing callers
# to provide their own external cache location.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$HOME/Library/Caches/ClosedRoom/uv}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$SCRIPT_DIR/.cache/pyinstaller}"
DIST_DIR="$SCRIPT_DIR/dist"
APP_BUNDLE_BASENAME="${APP_NAME}-${APP_VERSION}"
APP_BUNDLE_NAME="${APP_BUNDLE_BASENAME}.app"
APP_PATH="$DIST_DIR/$APP_BUNDLE_NAME"
DMG_PATH="$DIST_DIR/${APP_BUNDLE_BASENAME}.dmg"
LEGACY_APP_PATH="$DIST_DIR/$APP_NAME.app"
CREATE_DMG=true
CLEAN_BUILD=false
INSTALL_TO_APPLICATIONS=false

# Derive the helper bundle ID to prevent permission conflicts
HELPER_BUNDLE_ID="${CLOSEDROOM_HELPER_BUNDLE_ID:-}"
if [[ -z "$HELPER_BUNDLE_ID" ]]; then
    if [[ "$BUNDLE_ID" == "com.closedroom.app" ]]; then
        HELPER_BUNDLE_ID="com.closedroom.nativecapture"
    else
        HELPER_BUNDLE_ID="${BUNDLE_ID}.nativecapture"
    fi
fi


# Code signing identity.
# Use a real Apple identity to keep TCC permissions stable across builds.
# Falls back to '-' (ad-hoc) when not set.
SIGN_IDENTITY="${CLOSEDROOM_SIGN_IDENTITY:-}"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}▸ $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# ── Parse arguments ───────────────────────────────────────────────────────────
for arg in "$@"; do
    case $arg in
        --no-dmg)   CREATE_DMG=false ;;
        --clean)    CLEAN_BUILD=true ;;
        --install)  INSTALL_TO_APPLICATIONS=true ;;
        --sign)     shift; SIGN_IDENTITY="$1" ;;
    esac
done

# Resolve empty identity to ad-hoc sentinel
if [[ -z "$SIGN_IDENTITY" ]]; then
    SIGN_IDENTITY="-"
fi

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ "$(uname)" == "Darwin" ]] || die "Build is only supported on macOS."
[[ "$(uname -m)" == "arm64" ]] || die "Build requires Apple Silicon (arm64)."

command -v uv       >/dev/null 2>&1 || die "uv not found. Install: curl -Ls https://astral.sh/uv | sh"
command -v swiftc   >/dev/null 2>&1 || die "swiftc not found. Install Xcode Command Line Tools: xcode-select --install"


# ── TCC / signing guards ─────────────────────────────────────────────────────
if [[ "$SIGN_IDENTITY" == "-" ]]; then
    warn "Ad-hoc signing: macOS TCC permissions (microphone, screen recording) will"
    warn "reset on every install because macOS treats each build as a new identity."
    warn "Set CLOSEDROOM_SIGN_IDENTITY to a real Apple identity to avoid this."
    if $INSTALL_TO_APPLICATIONS; then
        die "--install is not allowed with ad-hoc signing to prevent TCC confusion.\n" \
            "  Use a real signing identity:\n" \
            "    export CLOSEDROOM_SIGN_IDENTITY=\"Apple Development: Name (TEAMID)\"\n" \
            "    ./build.sh --no-dmg --install"
    fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Building $APP_NAME v$APP_VERSION"
echo "  Artifact: $APP_BUNDLE_NAME"
if [[ "$SIGN_IDENTITY" == "-" ]]; then
    echo "  Signing:  ad-hoc (TCC permissions will reset on install)"
else
    echo "  Signing:  $SIGN_IDENTITY"
fi
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Clean ─────────────────────────────────────────────────────────────────────
if $CLEAN_BUILD; then
    log "Cleaning previous build artifacts..."
    rm -rf "$DIST_DIR" build/ __pycache__ build_venv
    ok "Cleaned"
fi

mkdir -p "$BUILD_ASSETS"

# ── Step 0: Build React frontend ──────────────────────────────────────────────
log "Step 0/5: Building React + Tailwind v4 frontend with pnpm..."
if ! command -v pnpm &> /dev/null; then
    die "pnpm not found. Please install it: npm install -g pnpm"
fi
cd "$SCRIPT_DIR/frontend"
CI=true pnpm install --frozen-lockfile --store-dir "$SCRIPT_DIR/.cache/pnpm-store"
pnpm run build
cd "$SCRIPT_DIR"
ok "React frontend built successfully"

# ── Step 1: Compile Swift audio helper ────────────────────────────────────────
log "Step 1/5: Compiling Swift audio helper..."

HELPER_CACHE="$SCRIPT_DIR/.cache/audio-helper/audio-helper"
HELPER_DEST="$BUILD_ASSETS/audio-helper"

if [[ -f "$HELPER_CACHE" ]] && [[ -f "$SCRIPT_DIR/.cache/audio-helper/source.sha256" ]]; then
    SOURCE_HASH=$(shasum -a 256 "$SCRIPT_DIR/src/local_asr_server/macos_audio_helper/audio_helper.swift" | awk '{print $1}')
    CACHED_HASH=$(cat "$SCRIPT_DIR/.cache/audio-helper/source.sha256")
    if [[ "$SOURCE_HASH" == "$CACHED_HASH" ]]; then
        ok "Audio helper binary is up-to-date (cache hit)"
        cp "$HELPER_CACHE" "$HELPER_DEST"
    else
        log "Source changed, recompiling..."
        uv run --no-sync local-asr setup-audio
        cp "$HELPER_CACHE" "$HELPER_DEST"
    fi
else
    log "Compiling for the first time..."
    uv run --no-sync local-asr setup-audio
    cp "$HELPER_CACHE" "$HELPER_DEST"
fi
chmod +x "$HELPER_DEST"
ok "Audio helper: $HELPER_DEST ($(du -sh "$HELPER_DEST" | cut -f1))"

NATIVE_HELPER_CACHE="$SCRIPT_DIR/.cache/native-capture-helper/native-capture-helper"
NATIVE_HELPER_DEST="$BUILD_ASSETS/native-capture-helper"
NATIVE_HELPER_APP="$BUILD_ASSETS/ClosedRoomNativeCapture.app"
NATIVE_HELPER_APP_EXE="$NATIVE_HELPER_APP/Contents/MacOS/ClosedRoomNativeCapture"
log "  Compiling native capture helper..."
uv run --no-sync python -c "from local_asr_server.native_capture_helper.compile import compile_helper; compile_helper(force=False)"
cp "$NATIVE_HELPER_CACHE" "$NATIVE_HELPER_DEST"
chmod +x "$NATIVE_HELPER_DEST"
ok "Native capture helper: $NATIVE_HELPER_DEST ($(du -sh "$NATIVE_HELPER_DEST" | cut -f1))"

SPEAKER_DIARIZATION_HELPER_CACHE="$SCRIPT_DIR/.cache/speaker-diarization-helper/speaker-diarization-helper"
log "  Compiling FluidAudio speaker diarization helper..."
uv run --no-sync python -c "from local_asr_server.speaker_diarization_helper.compile import compile_helper; compile_helper(force=False)"
chmod +x "$SPEAKER_DIARIZATION_HELPER_CACHE"
ok "Speaker diarization helper: $SPEAKER_DIARIZATION_HELPER_CACHE ($(du -sh "$SPEAKER_DIARIZATION_HELPER_CACHE" | cut -f1))"

log "  Creating native capture helper app bundle..."
rm -rf "$NATIVE_HELPER_APP"
mkdir -p "$NATIVE_HELPER_APP/Contents/MacOS"
cp "$NATIVE_HELPER_CACHE" "$NATIVE_HELPER_APP_EXE"
chmod +x "$NATIVE_HELPER_APP_EXE"
cat > "$NATIVE_HELPER_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>$HELPER_BUNDLE_ID</string>
    <key>CFBundleName</key>
    <string>ClosedRoom Native Capture</string>
    <key>CFBundleDisplayName</key>
    <string>ClosedRoom Native Capture</string>
    <key>CFBundleExecutable</key>
    <string>ClosedRoomNativeCapture</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>$APP_VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$APP_VERSION</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>ClosedRoom uses the microphone to record your voice for local transcription.</string>
    <key>NSScreenCaptureUsageDescription</key>
    <string>ClosedRoom records screen and system audio to capture computer audio.</string>
    <key>NSAudioCaptureUsageDescription</key>
    <string>ClosedRoom records computer audio to transcribe meetings and local audio sources.</string>
</dict>
</plist>
PLIST
ok "Native capture helper app: $NATIVE_HELPER_APP ($(du -sh "$NATIVE_HELPER_APP" | cut -f1))"

# ── Step 2: Bundle ffmpeg ──────────────────────────────────────────────────────
log "Step 2/5: Bundling ffmpeg..."

FFMPEG_DEST="$BUILD_ASSETS/ffmpeg"
FFMPEG_LIB_DIR="$BUILD_ASSETS/lib"
mkdir -p "$FFMPEG_LIB_DIR"

FFMPEG_SRC=$(which ffmpeg 2>/dev/null || echo "")
if [[ -z "$FFMPEG_SRC" ]]; then
    die "ffmpeg not found. Install it with: brew install ffmpeg"
fi

# Resolve symlink
FFMPEG_SRC=$(python3 -c "import os; print(os.path.realpath('$FFMPEG_SRC'))")
rm -f "$FFMPEG_DEST"
cp "$FFMPEG_SRC" "$FFMPEG_DEST"
chmod 755 "$FFMPEG_DEST"


# Collect all Homebrew dylibs that ffmpeg depends on (excluding system libs)
log "  Collecting ffmpeg dylibs..."
collect_dylibs() {
    local binary="$1"
    local visited=""
    local -a queue=("$binary")

    while [[ ${#queue[@]} -gt 0 ]]; do
        local current="${queue[0]}"
        queue=("${queue[@]:1}")

        # Skip if already visited
        if [[ "$visited" == *"$current"* ]]; then
            continue
        fi
        visited="$visited|$current"

        # Get dependencies
        while IFS= read -r dep; do
            dep=$(echo "$dep" | awk '{print $1}' | xargs 2>/dev/null || echo "")
            [[ -z "$dep" ]] && continue
            # Only collect Homebrew libs (not system)
            if [[ "$dep" == /opt/homebrew/* ]] || [[ "$dep" == /usr/local/* ]]; then
                local dest_name
                dest_name=$(basename "$dep")
                if [[ -f "$dep" ]] && [[ ! -f "$FFMPEG_LIB_DIR/$dest_name" ]]; then
                    cp "$dep" "$FFMPEG_LIB_DIR/$dest_name"
                    queue+=("$dep")
                fi
            fi
        done < <(otool -L "$current" 2>/dev/null | tail -n +2)
    done
}

collect_dylibs "$FFMPEG_SRC"
DYLIB_COUNT=$(ls "$FFMPEG_LIB_DIR" | wc -l | tr -d ' ')

# Fix the rpath inside ffmpeg to find its dylibs relative to itself
# All dylibs will be placed next to ffmpeg in the bundle (Contents/MacOS/)
for dylib in "$FFMPEG_LIB_DIR"/*.dylib; do
    dylib_name=$(basename "$dylib")
    install_name_tool -change \
        "/opt/homebrew/Cellar/ffmpeg/"* \
        "@executable_path/$dylib_name" \
        "$FFMPEG_DEST" 2>/dev/null || true
done

ok "ffmpeg bundled with $DYLIB_COUNT dylibs"

# ── Step 3: Generate icon.icns ────────────────────────────────────────────────
log "Step 3/5: Generating icon.icns..."

ICNS_PATH="$BUILD_ASSETS/icon.icns"
SVG_SOURCE="$SCRIPT_DIR/src/local_asr_server/static/logo-dark.svg"
ICONSET_DIR="$BUILD_ASSETS/ClosedRoom.iconset"

if [[ -f "$SVG_SOURCE" ]]; then
    mkdir -p "$ICONSET_DIR"

    # Convert SVG → PNG at various sizes using sips + rsvg-convert (if available) or qlmanage
    if command -v rsvg-convert >/dev/null 2>&1; then
        CONVERT_CMD="rsvg-convert"
    else
        warn "rsvg-convert not found (install: brew install librsvg). Using qlmanage fallback."
        CONVERT_CMD="qlmanage"
    fi

    declare -a SIZES=(16 32 64 128 256 512 1024)
    for size in "${SIZES[@]}"; do
        out="$ICONSET_DIR/icon_${size}x${size}.png"
        if [[ "$CONVERT_CMD" == "rsvg-convert" ]]; then
            rsvg-convert -w "$size" -h "$size" "$SVG_SOURCE" -o "$out" 2>/dev/null || true
        else
            # Fallback: use sips on a large PNG placeholder
            sips -s format png "$SVG_SOURCE" --out "$out" --resampleWidth "$size" 2>/dev/null || true
        fi
    done

    # Create @2x versions
    for size in 16 32 128 256 512; do
        double=$((size * 2))
        src="$ICONSET_DIR/icon_${double}x${double}.png"
        dst="$ICONSET_DIR/icon_${size}x${size}@2x.png"
        if [[ -f "$src" ]]; then
            cp "$src" "$dst"
        fi
    done

    # iconutil requires valid PNGs — if generation failed, create a placeholder
    VALID_PNGS=$(find "$ICONSET_DIR" -maxdepth 1 -type f -name '*.png' | wc -l | tr -d ' ')
    if [[ "$VALID_PNGS" -gt 0 ]]; then
        iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH" 2>/dev/null && ok "icon.icns generated" || warn "iconutil failed, using no icon"
    else
        warn "Could not generate PNG icons — building without custom icon"
    fi
    rm -rf "$ICONSET_DIR"
else
    warn "Logo SVG not found at $SVG_SOURCE — building without custom icon"
fi

# ── Step 4: PyInstaller ───────────────────────────────────────────────────────
log "Step 4/5: Running PyInstaller..."

cd "$SCRIPT_DIR"

log "  Removing stale app artifacts..."
rm -rf "$APP_PATH"
if [[ "$LEGACY_APP_PATH" != "$APP_PATH" ]]; then
    rm -rf "$LEGACY_APP_PATH"
fi

log "  Building python wheel..."
rm -rf dist/wheels
uv build --wheel --out-dir dist/wheels/

log "  Creating clean build virtual environment with Python $BUILD_PYTHON_VERSION..."
rm -rf build_venv
uv venv build_venv --python "$BUILD_PYTHON_VERSION" --color always

log "  Installing wheel and dependencies into build_venv..."
# The packaged app exposes Speechmatics ASR and diarization from the UI, so the
# cloud SDK must be bundled together with the native app dependencies.
WHEEL_FILE=$(ls dist/wheels/local_asr_server-*.whl)
uv pip install --python build_venv "${WHEEL_FILE}[app,speechmatics]" "pyinstaller>=6.0"

log "  Running PyInstaller from build_venv..."
CLOSEDROOM_APP_NAME="$APP_NAME" \
CLOSEDROOM_APP_BUNDLE_ID="$BUNDLE_ID" \
CLOSEDROOM_APP_DISPLAY_NAME="$APP_BUNDLE_BASENAME" \
CLOSEDROOM_APP_BUNDLE_NAME="$APP_BUNDLE_NAME" \
build_venv/bin/pyinstaller \
    --clean \
    --noconfirm \
    ClosedRoom.spec



if [[ ! -d "$APP_PATH" ]]; then
    die "PyInstaller did not produce $APP_PATH"
fi
ok "App bundle: $APP_PATH"

log "  Embedding native capture helper app..."
HELPERS_DIR="$APP_PATH/Contents/Helpers"
NATIVE_HELPER_APP_IN_APP="$HELPERS_DIR/ClosedRoomNativeCapture.app"
rm -rf "$NATIVE_HELPER_APP_IN_APP"
mkdir -p "$HELPERS_DIR"
ditto "$NATIVE_HELPER_APP" "$NATIVE_HELPER_APP_IN_APP"
NATIVE_HELPER_IN_APP="$NATIVE_HELPER_APP_IN_APP/Contents/MacOS/ClosedRoomNativeCapture"
chmod +x "$NATIVE_HELPER_IN_APP"
if find "$APP_PATH" -name "*__dot__app*" -print -quit | grep -q .; then
    die "Invalid packaged .app found as __dot__app"
fi
if [[ ! -x "$NATIVE_HELPER_IN_APP" ]]; then
    die "ClosedRoomNativeCapture helper app missing"
fi
ok "Embedded native capture helper app: $NATIVE_HELPER_APP_IN_APP"

# ── Post-processing: fix permissions & ad-hoc code sign ──────────────────────
log "  Fixing permissions..."
find "$APP_PATH" -name "*.dylib" -exec chmod 755 {} \;
find "$APP_PATH" -name "*.so" -exec chmod 755 {} \;
chmod +x "$APP_PATH/Contents/MacOS/$APP_NAME"

find_bundled_binary() {
    local name="$1"
    local path

    for path in \
        "$APP_PATH/Contents/MacOS/$name" \
        "$APP_PATH/Contents/Frameworks/$name" \
        "$APP_PATH/Contents/Resources/$name"; do
        if [[ -f "$path" ]]; then
            echo "$path"
            return 0
        fi
    done

    find "$APP_PATH/Contents" -type f -name "$name" -print -quit
}

AUDIO_HELPER_IN_APP="$(find_bundled_binary "audio-helper")"
SPEAKER_DIARIZATION_HELPER_IN_APP="$(find_bundled_binary "speaker-diarization-helper")"
FFMPEG_IN_APP="$(find_bundled_binary "ffmpeg")"

[[ -n "$AUDIO_HELPER_IN_APP" ]] || die "audio-helper not found in app bundle"
[[ -n "$SPEAKER_DIARIZATION_HELPER_IN_APP" ]] || die "speaker-diarization-helper not found in app bundle"
[[ -f "$NATIVE_HELPER_IN_APP" ]] || die "ClosedRoomNativeCapture executable not found in helper app"
[[ -n "$FFMPEG_IN_APP" ]] || die "ffmpeg not found in app bundle"

chmod +x "$AUDIO_HELPER_IN_APP"
chmod +x "$SPEAKER_DIARIZATION_HELPER_IN_APP"
chmod +x "$NATIVE_HELPER_IN_APP"
chmod +x "$FFMPEG_IN_APP"

if [[ "$SIGN_IDENTITY" == "-" ]]; then
    log "  Applying ad-hoc code signatures..."
else
    log "  Applying code signatures with identity: $SIGN_IDENTITY"
fi
ENTITLEMENTS="$BUILD_ASSETS/entitlements.plist"

is_macho() {
    file "$1" | grep -q "Mach-O"
}

# sign_plain: sign a binary without entitlements (frameworks, dylibs, .so files).
# Uses the global SIGN_IDENTITY so the entire bundle shares one identity.
sign_plain() {
    local target="$1"
    if is_macho "$target"; then
        codesign --force \
            --sign "$SIGN_IDENTITY" \
            --timestamp=none \
            "$target" \
            || die "codesign failed for $target"
    fi
}

# sign_entitled: sign a binary or .app bundle with the app entitlements.
# Must be called in dependency order (inner → outer) so the outer signature
# covers all already-signed nested content.
sign_entitled() {
    local target="$1"
    codesign --force \
        --sign "$SIGN_IDENTITY" \
        --timestamp=none \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$target" \
        || die "codesign failed for $target"
}

while IFS= read -r -d '' target; do
    sign_plain "$target"
done < <(
    find "$APP_PATH/Contents/Frameworks" \
        -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) \
        -print0
)

# Sign inner binaries first, then their parent bundles (inside-out order).
sign_entitled "$AUDIO_HELPER_IN_APP"
sign_entitled "$SPEAKER_DIARIZATION_HELPER_IN_APP"
sign_entitled "$NATIVE_HELPER_IN_APP"
sign_entitled "$NATIVE_HELPER_APP_IN_APP"
sign_entitled "$FFMPEG_IN_APP"
sign_entitled "$APP_PATH/Contents/MacOS/$APP_NAME"
sign_entitled "$APP_PATH"
codesign --verify --strict --verbose=2 "$APP_PATH" \
    || die "codesign verification failed for $APP_PATH"

log "  Verifying native capture helper diagnostics..."
HELPER_DIAG="$("$NATIVE_HELPER_IN_APP" diagnostics || true)"
CLOSEDROOM_HELPER_BUNDLE_ID="$HELPER_BUNDLE_ID" HELPER_DIAG="$HELPER_DIAG" python3 -c '
import json
import os

payload = json.loads(os.environ.get("HELPER_DIAG") or "{}")
errors = []

expected_helper_id = os.environ.get("CLOSEDROOM_HELPER_BUNDLE_ID")
if payload.get("bundle_identifier") != expected_helper_id:
    errors.append("bad bundle_identifier: {} (expected {})".format(payload.get("bundle_identifier"), expected_helper_id))
if payload.get("code_signature") != "signed":
    errors.append("bad code_signature: {}".format(payload.get("code_signature")))
if payload.get("screen_capture") not in {"granted", "required"}:
    errors.append("bad screen_capture: {}".format(payload.get("screen_capture")))

if errors:
    raise SystemExit("Native helper diagnostics failed: " + "; ".join(errors))
'
if [[ "$SIGN_IDENTITY" == "-" ]]; then
    ok "Ad-hoc signed (TCC permissions will reset on every install)"
else
    ok "Signed with identity: $SIGN_IDENTITY"
fi


APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)
ok "$APP_BUNDLE_NAME ($APP_SIZE)"

# ── Step 5: Create DMG ────────────────────────────────────────────────────────
if $CREATE_DMG; then
    log "Step 5/5: Creating DMG..."
    ./create_dmg.sh "$APP_PATH" "$DMG_PATH" "$APP_NAME" "$APP_VERSION"
else
    log "Step 5/5: Skipping DMG (--no-dmg)"
    if [[ -f "$DMG_PATH" ]]; then
        rm -f "$DMG_PATH"
        warn "Removed stale DMG: $DMG_PATH"
    fi
fi

# ── Optional: install to /Applications ───────────────────────────────────────
# Guarded above: only reachable when SIGN_IDENTITY is not ad-hoc.
if $INSTALL_TO_APPLICATIONS; then
    log "Installing to /Applications..."
    rm -rf "/Applications/$APP_BUNDLE_NAME"
    ditto "$APP_PATH" "/Applications/$APP_BUNDLE_NAME"
    # Remove quarantine so macOS does not gate the app on first open.
    xattr -dr com.apple.quarantine "/Applications/$APP_BUNDLE_NAME" 2>/dev/null || true
    ok "Installed: /Applications/$APP_BUNDLE_NAME"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
ok "$APP_NAME v$APP_VERSION built successfully!"
echo ""
echo "  App:  $APP_PATH"
$CREATE_DMG && echo "  DMG:  $DMG_PATH" || true
echo ""
if [[ "$SIGN_IDENTITY" == "-" ]]; then
    echo "  To test locally:"
    echo "    open $APP_PATH"
    echo ""
    echo "  To install (TCC permissions will reset):"
    echo "    ditto $APP_PATH /Applications/$APP_BUNDLE_NAME"
    echo ""
    echo "  ⚠  For stable TCC permissions across builds, use a real Apple identity:"
    echo "    export CLOSEDROOM_SIGN_IDENTITY=\"Apple Development: Name (TEAMID)\""
    echo "    security find-identity -v -p codesigning  # list available identities"
    echo "    ./build.sh --no-dmg --install"
else
    echo "  To test locally:"
    echo "    open $APP_PATH"
    echo ""
    echo "  To install with stable TCC permissions:"
    echo "    ./build.sh --no-dmg --install"
    echo "  or manually:"
    echo "    ditto $APP_PATH /Applications/$APP_BUNDLE_NAME"
fi
echo "═══════════════════════════════════════════════════════════"
