# Korgis Consumer SDK — text-only integration preview

Status: experimental / explicit developer opt-in
Owner: local-asr-server runtime port and AnalysisService
Reference: https://github.com/daniele21/korgis

## Purpose and boundaries

ClosedRoom can opt into Korgis's separately installable consumer SDK for Nemotron **text-only** analysis. The port in runtime/local_ai.py translates the SDK's exact role/model-bound OpenAI-compatible chat result into the existing LocalAIClient contract. It does not use Korgis.managed(), change model loading/residency, create a second sidecar supervisor, alter meeting storage, switch cloud providers or change capture priority.

The canonical Korgis server/runtime remains the current pinned local-llm-server dependency. This preview does not upgrade it. RuntimeServiceManager and LocalLLMSidecar still own readiness, process lifecycle, model residency and admin API interactions. Korgis SDK attach requires the named model to be resident and visible through /v1/models. If that exact compatibility is not available on the pinned runtime, the preview fails closed; it does not silently substitute a model or service.

## Developer setup

The SDK is **not bundled** or a default ClosedRoom runtime dependency yet. In an isolated development environment, install the consumer wheel from the exact currently integrated Korgis revision, without changing ClosedRoom's pinned inference server:

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

Before making the SDK the default and including it in ClosedRoom.app, pin the SDK artifact in the lockfile, verify installed SDK↔server contract and actual model residency, confirm packaged import/native signed artifact, ensure admin/health identity and resource guards work across restarts, and run representative Apple Silicon real-environment capture/LLM contention, cleanup and privacy tests. Korgis SDK managed-session security is a separate owner and does not replace ClosedRoom's existing process supervisor.
