"""Privacy-bounded live Korgis consumer probe against an already running local LLM.

An endpoint can claim any metadata: this proves only an observed end-to-end
call and schema validation, not model weights, a trusted binary or Apple Silicon
resource/capture qualification. Never log or persist the generated note.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

# Running from a source checkout or an installed ClosedRoom wheel both work.
from local_asr_server.llm import NemotronLocalProvider
from local_asr_server.runtime.local_ai import KorgisTextAdapter

_SYNTHETIC_TRANSCRIPT = (
    "Riunione del progetto Atlas. Il gruppo ha deciso di completare "
    "il prototipo entro venerdì. Laura preparerà il piano di test, "
    "mentre Marco rivedrà il documento di lancio."
)
_REQUIRED_STRINGS = ("title", "summary")
_REQUIRED_LISTS = ("key_points", "action_items")
_MODEL_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class ProbeFailure(RuntimeError):
    """A stable safe failure code, never a remote body or transcript."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _local_port(value: str) -> int:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ProbeFailure("invalid_endpoint") from None
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or port is None or not 1 <= port <= 65535 or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ProbeFailure("non_loopback_or_invalid_endpoint")
    return port


def _get_json(port: int, path: str) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        body = response.read(256 * 1024 + 1)
        if response.status != 200 or len(body) > 256 * 1024:
            raise ProbeFailure("endpoint_probe_failed")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProbeFailure("invalid_endpoint_json") from None
        if not isinstance(payload, dict):
            raise ProbeFailure("invalid_endpoint_payload")
        return payload
    except (OSError, TimeoutError, http.client.HTTPException):
        raise ProbeFailure("endpoint_unreachable") from None
    finally:
        conn.close()


def _verify_result(result: object) -> None:
    if not isinstance(result, dict):
        raise ProbeFailure("invalid_note_shape")
    if any(not isinstance(result.get(k), str) or not result[k].strip()
           for k in _REQUIRED_STRINGS):
        raise ProbeFailure("invalid_note_text")
    if any(not isinstance(result.get(k), list) or
           any(not isinstance(value, str) for value in result[k])
           for k in _REQUIRED_LISTS):
        raise ProbeFailure("invalid_note_lists")
    # This is deliberately format/structural validation, not semantic quality.


def run_probe(*, endpoint: str, model: str) -> dict:
    """Use existing local runtime; never launch, download or alter residency."""
    port = _local_port(endpoint)
    if not _MODEL_KEY.fullmatch(model):
        raise ProbeFailure("invalid_model_key")
    health = _get_json(port, "/health")
    if health.get("ok") is not True or health.get("server") != "local-llm-server":
        raise ProbeFailure("unexpected_server_identity_claim")
    models = _get_json(port, "/v1/models").get("data")
    if (not isinstance(models, list)
            or not any(isinstance(item, dict) and item.get("key") == model
                       for item in models)):
        raise ProbeFailure("requested_model_not_resident")
    start = time.monotonic()
    # Use the ClosedRoom port and the actual packaged consumer SDK.
    provider = NemotronLocalProvider(
        base_url=f"http://127.0.0.1:{port}",
        model=model, local_ai=KorgisTextAdapter(),
    )
    try:
        result = provider.analyze(_SYNTHETIC_TRANSCRIPT, language="it")
    except Exception:
        # Do not surface error messages that could contain a model response.
        raise ProbeFailure("local_inference_or_parse_failed") from None
    _verify_result(result)
    return {
        "status": "pass",
        "checks": {
            "reported_local_llm_runtime": "pass",
            "requested_model_resident": "pass",
            "real_sdk_http_inference": "pass",
            "closedroom_note_shape": "pass",
        },
        "latency_seconds": round(time.monotonic() - start, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Existing loopback Korgis URL")
    parser.add_argument("--model", required=True, help="Exact already-resident model key")
    parser.add_argument("--output", required=True, help="Local bounded evidence JSON destination")
    args = parser.parse_args(argv)
    evidence = {
        "schema_version": 1,
        "status": "fail",
        "check": "korgis_closedroom_attached_live_inference",
        "scope": "synthetic_text_only_no_capture_or_hardware_claim",
        "environment": {"os": platform.system(), "arch": platform.machine()},
        "endpoint": "127.0.0.1_only_no_address_persisted",
        "sdk_model_binding": "exact_requested_key",
        "runtime_identity": "self_reported_not_cryptographically_attested",
        "weights_identity": "unverified",
        "resource_and_thermal": "not_measured",
        "native_capture": "not_tested",
        "output_quality": "shape_only_not_semantically_judged",
        "cloud_fallback": "not_invoked_by_this_probe",
        "sensitive_content_saved": False,
        "failure_code": None,
    }
    try:
        result = run_probe(endpoint=args.endpoint, model=args.model)
        evidence.update(result)
    except ProbeFailure as exc:
        evidence["failure_code"] = exc.code
    except Exception:
        evidence["failure_code"] = "probe_execution_failed"
    try:
        destination = Path(args.output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        # No model-generated text, paths, prompts or raw exceptions persisted.
        destination.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8")
        os.chmod(destination, 0o600)
    except OSError:
        print("Korgis probe evidence write failed", file=sys.stderr)
        return 1
    print("Korgis live consumer probe: " + evidence["status"])
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
