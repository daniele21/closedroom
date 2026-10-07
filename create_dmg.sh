#!/usr/bin/env bash
# =============================================================================
# create_dmg.sh — Create a distributable DMG for ClosedRoom
#
# Usage:
#   ./create_dmg.sh <app-path> <dmg-path> <app-name> <version>
#
# Example:
#   ./create_dmg.sh dist/ClosedRoom.app dist/ClosedRoom-1.0.0.dmg ClosedRoom 1.0.0
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_VERSION="$(python3 "$SCRIPT_DIR/scripts/product_version.py" --root "$SCRIPT_DIR")"
APP_NAME="${3:-ClosedRoom}"
VERSION="${4:-$DEFAULT_VERSION}"
APP_PATH="${1:-$SCRIPT_DIR/dist/${APP_NAME}.app}"
DMG_PATH="${2:-$SCRIPT_DIR/dist/${APP_NAME}-${VERSION}.dmg}"
STAGING_DIR="$SCRIPT_DIR/dist/dmg_staging"
VOLUME_NAME="$APP_NAME $VERSION"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${BLUE}  ▸ $*${NC}"; }
ok()  { echo -e "${GREEN}  ✓ $*${NC}"; }
die() { echo -e "${RED}  ✗ $*${NC}" >&2; exit 1; }

[[ -d "$APP_PATH" ]] || die "App not found at $APP_PATH"

log "Preparing DMG staging directory..."
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# Copy the app into staging
cp -R "$APP_PATH" "$STAGING_DIR/"

# Create a symlink to /Applications for drag-install UX
ln -s /Applications "$STAGING_DIR/Applications"

# Remove old DMG if it exists
rm -f "$DMG_PATH"

log "Creating compressed DMG..."
hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH" \
    >/dev/null

# Clean up
rm -rf "$STAGING_DIR"

DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
ok "DMG created: $DMG_PATH ($DMG_SIZE)"
