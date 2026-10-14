#!/usr/bin/env bash
# Portable repository-contract checks; native app/UI/E2E gates remain in preflight.yml.
set -euo pipefail

python3 scripts/verify_repository.py
python3 scripts/verify_operations.py
python3 scripts/verify_e2e.py
python3 scripts/verify_stage_environment_policy.py
python3 scripts/verify_product_experience.py
python3 scripts/verify_docs.py
python3 scripts/verify_agent_context.py
