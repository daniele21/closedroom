#!/usr/bin/env bash
# Source from .github/ci/local-test.sh; exports portable browser locations.
# Downloads only official Chrome for Testing binaries into this run's private
# temporary directory. Never install apps, casks or executables globally.
set -euo pipefail
for cmd in curl jq unzip mktemp; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "Missing Mac browser prerequisite: $cmd" >&2
    return 2
  }
done
CLOSEDROOM_CI_BROWSER_DIR=$(mktemp -d "$RUNNER_TEMP/closedroom-browser.XXXXXXXX")
trap 'rm -rf "$CLOSEDROOM_CI_BROWSER_DIR"' EXIT

manifest=$(curl -fsSL --retry 2 --connect-timeout 15 --max-time 60 \
  "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json")
version=$(jq -er '.channels.Stable.version' <<<"$manifest")
for kind in chrome chromedriver; do
  url=$(jq -er --arg kind "$kind" '.channels.Stable.downloads[$kind][] | select(.platform == "mac-arm64") | .url' <<<"$manifest")
  case "$url" in
    https://storage.googleapis.com/chrome-for-testing-public/*) ;;
    *) echo "Unexpected Chrome for Testing download host: $url" >&2; return 2 ;;
  esac
  curl -fsSL --retry 2 --connect-timeout 20 --max-time 360 \
    "$url" -o "$CLOSEDROOM_CI_BROWSER_DIR/$kind.zip"
  unzip -q "$CLOSEDROOM_CI_BROWSER_DIR/$kind.zip" -d "$CLOSEDROOM_CI_BROWSER_DIR"
  rm "$CLOSEDROOM_CI_BROWSER_DIR/$kind.zip"
done
export CHROMEWEBDRIVER="$CLOSEDROOM_CI_BROWSER_DIR/chromedriver-mac-arm64/chromedriver"
export CI_CHROME_BINARY="$CLOSEDROOM_CI_BROWSER_DIR/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
export CHROME_BINARY="$CI_CHROME_BINARY"
chmod +x "$CHROMEWEBDRIVER" "$CI_CHROME_BINARY"
[[ -x "$CHROMEWEBDRIVER" && -x "$CI_CHROME_BINARY" ]] || {
  echo "Portable Chrome for Testing setup incomplete" >&2
  return 2
}
echo "Using ephemeral Chrome for Testing $version + matching ChromeDriver (Mac ARM64)"
