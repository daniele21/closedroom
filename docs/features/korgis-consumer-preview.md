# Korgis Consumer SDK — text-only integration preview

Status: experimental / explicit developer opt-in
Owner: local-asr-server runtime port and AnalysisService
Reference: https://github.com/daniele21/korgis

## Purpose and boundaries

ClosedRoom can opt into Korgis's separately installable consumer SDK for Nemotron **text-only** analysis. The port in runtime/local_ai.py translates the SDK's exact role/model-bound OpenAI-compatible chat result into the existing LocalAIClient contract. It does not use Korgis.managed(), change model loading/residency, create a second sidecar supervisor, alter meeting storage, switch cloud providers or change capture priority.

The canonical Korgis server/runtime remains the current pinned local-llm-server dependency. This preview does not upgrade it. RuntimeServiceManager and LocalLLMSidecar still own readiness, process lifecycle, model residency and admin API interactions. Korgis SDK attach requires the named model to be resident and visible through /v1/models. If that exact compatibility is not available on the pinned runtime, the preview fails closed; it does not silently substitute a model or service.

## Developer setup

The SDK is pinned as the **optional** `korgis-sdk` extra in `pyproject.toml` and `uv.lock`, without changing the separately pinned inference runtime. Normal source installations can omit this extra; the macOS artifact builder installs the wheel with `[app,speechmatics,korgis-sdk]` explicitly and PyInstaller collects the SDK. Development CI can use `uv sync --all-extras --frozen`. The default transport remains `legacy`. Install the optional extra into your development environment with:

    uv sync --extra korgis-sdk --locked

The exact dependency refers to Korgis commit `99681516a4955ce40e919971b0820a48d840c356`. For isolated wheel testing, the equivalent direct installation is:

    python -m pip install "korgis-client @ git+https://github.com/daniele21/korgis.git@99681516a4955ce40e919971b0820a48d840c356#subdirectory=sdk/python"

To opt in for text analysis, set in ClosedRoom's normal application settings.json (through the existing settings store, not a new standalone config):

    "llm_provider": "nemotron_local",
    "local_llm_client_transport": "korgis_sdk"

Default is "legacy"; no UI toggle is shipped in this preview. An unsupported value returns HTTP 422. Voxtral with korgis_sdk returns 422 rather than silently redirecting audio through legacy; explicit Gemini/mock selection is unchanged. To revert, set "local_llm_client_transport": "legacy".

The first supported operations are Nemotron custom prompt chat and default transcript analysis. ClosedRoom retains the existing transcript prompt and legacy narrow JSON-object parsing semantics; app-level structured note validation and source citations remain unchanged. Audio and visual providers continue their existing legacy consumer adapters and are not part of this preview.

If the SDK package is missing, the named model is not resident, Korgis responds with an unsupported contract or the server is unreachable, the integration reports an error. It **never** falls back to Gemini, another model or a new sidecar.

## Verification and promotion gates

Deterministic regression: UV_CACHE_DIR=.cache/uv uv run python -m unittest test.test_korgis_consumer_adapter test.test_local_ai_runtime_port -v, plus the repository-selected validation and affected analysis pipeline tests.

The regression fixtures exercise exact role/model keys, prompt/temperature preservation, JSON error sanitation, absent SDK, unavailable server, explicit provider choices and unsupported audio/vision. This verifies the consumer boundary with a fake Korgis class; it is **not** evidence of an installed Korgis wheel communicating with the currently pinned inference server.

A separate CI workflow, `.github/workflows/korgis-consumer-contract.yml`, checks out exact Korgis commit `99681516a4955ce40e919971b0820a48d840c356` and installs its **actual standalone SDK package**, then exercises the ClosedRoom adapter over an actual loopback TCP HTTP server. The server supplies deterministic fake text completion payloads, so this verifies exact role/model binding, HTTP compatibility, prompts, output parsing, failure-to-attach and no unintended process launching **without proving the pinned inference server, real weights, Metal or packaged binary**. It is a targeted supplement to the canonical preflight, not a replacement.

Packaged builds explicitly collect `korgis_sdk` and check its import through the frozen `bundle-runtime-smoke` command. This proves bundle inclusion/import, not authenticated runtime ownership or working LLM inference.

Before making the SDK the default or claiming release readiness, verify end-to-end SDK↔**actual pinned inference runtime with real weights**, resident-model identity, per-request privacy and admin/health behavior over restarts, and representative Apple Silicon TCC/capture/LLM contention, resource/thermal and cleanup evidence. Source-built ad-hoc app proof is not a Developer-ID-signed and notarized distribution artifact. Korgis SDK managed-session security is a separate owner and does not replace ClosedRoom's existing process supervisor.
