#!/usr/bin/env bash
set -euo pipefail

# Initial shared Mac lane. Deterministic repository contracts only:
# no models, application builds, native permissions, deployment or releases.
[[ "$(uname -s)" == "Darwin" ]] || { echo "Local CI requires macOS" >&2; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "Local CI requires Apple Silicon" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Local CI requires python3" >&2; exit 1; }
command -v git >/dev/null || { echo "Local CI requires git" >&2; exit 1; }

python3 -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 14), "Python 3.10–3.13 required"'
# SOURCE_SHA is a confirmation only; never select, fetch or execute code
# from a payload path. The central workflow owns the exact checkout.
if [[ -n "${SOURCE_SHA:-}" ]]; then
  [[ "$(git rev-parse HEAD)" == "$SOURCE_SHA" ]] || {
    echo "Checked-out revision does not match expected source SHA" >&2
    exit 1
  }
fi

python3 scripts/verify_repository.py
python3 scripts/verify_operations.py
python3 scripts/verify_e2e.py
python3 scripts/verify_stage_environment_policy.py
python3 scripts/verify_product_experience.py
python3 scripts/verify_docs.py
python3 scripts/verify_agent_context.py
python3 -m unittest test.test_validation_profile_selector test.test_build_artifact_metadata -v
