#!/usr/bin/env bash
# Fast, no-dependency ClosedRoom source-owned contract smoke.
# Full media, pnpm browser and GCS workflows stay separately governed.
set -euo pipefail
python3 scripts/verify_repository.py
python3 scripts/verify_agent_context.py
