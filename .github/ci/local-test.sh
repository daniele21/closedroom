#!/usr/bin/env bash
set -euo pipefail

# ClosedRoom source-owned Mac validation entrypoint for local-runner-infra.
# Execute only the exact checkout pinned by central-ci.yml. Never build,
# sign, upload, or run production models in the shared CI runner.
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "ClosedRoom local Mac CI requires macOS ARM64" >&2
  exit 2
fi
if [[ -n "${SOURCE_SHA:-}" && "$(git rev-parse HEAD)" != "$SOURCE_SHA" ]]; then
  echo "Source revision does not match central dispatch request" >&2
  exit 2
fi
for prerequisite in uv pnpm node ffmpeg; do
  if ! command -v "$prerequisite" >/dev/null 2>&1; then
    echo "Missing Mac runner prerequisite: $prerequisite (no automatic host modification)" >&2
    exit 2
  fi
done

echo "Validating ClosedRoom source $(git rev-parse HEAD) on shared macOS ARM64"
uv sync --all-extras --frozen --python 3.12
(
  cd frontend
  pnpm install --frozen-lockfile
  pnpm run lint
  pnpm exec tsc --noEmit
)
UV_CACHE_DIR=.cache/uv uv run --frozen --python 3.12 python -m unittest discover -s test -v
source .github/ci/setup-browser.sh
E2E_SOURCE_REVISION="$(git rev-parse HEAD)" node scripts/browser_meeting_ui_e2e.mjs
echo "ClosedRoom Mac source and browser FULL_MEDIA checks passed"
