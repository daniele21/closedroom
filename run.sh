#!/usr/bin/env bash

set -euo pipefail

llm_log_file="$(uv run python -c 'from local_asr_server.paths import get_service_log_file; print(get_service_log_file("llm-server", create_parent=False))')"
mkdir -p "$(dirname "$llm_log_file")"
touch "$llm_log_file"

# The managed LLM is a sidecar, so its stdout/stderr goes to its persistent log
# rather than the API process. Follow only new entries to keep this terminal run readable.
tail -n 0 -F "$llm_log_file" &
llm_log_tail_pid=$!

cleanup() {
  kill "$llm_log_tail_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run local-asr serve --port 1230 --llm-port 1231
