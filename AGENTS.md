# ClosedRoom — Coding Agent Guide

ClosedRoom is a privacy-first macOS meeting workspace built around a loopback FastAPI service, native audio helpers, local AI runtimes and a React UI in WKWebView.

## Durable invariants

- Local-first by default: no implicit cloud fallback and no sensitive meeting content in ordinary telemetry.
- Loopback/auth/origin restrictions and canonical persistence owners remain explicit.
- Recording/job/model/native-capture lifecycles are bounded, cancellable and restore run-owned state on every applicable exit path.
- Paths resolve through settings/path owners; Cocoa/WebKit mutations remain on the main thread.
- Model/resource telemetry stays truthful; deterministic fixtures never become representative MLX/Metal, TCC, physical-audio or interactive target-Mac evidence.
- `frontend/src/` is the UI source of truth; finalized artifacts are immutable.

## Ownership

| Change | Owner | Inspect / prove |
| --- | --- | --- |
| API | `server.py`, routers/schemas/services | clients + API tests |
| Persistence | recordings/catalog/transcriptions/jobs | migration/recovery tests |
| ASR/LLM | runtime/service owners | lifecycle/resource tests |
| Native audio | capture/helpers/router/permissions | TCC/audio lifecycle evidence |
| Frontend | `frontend/src/` + `design/*` | browser/UI journeys |
| Packaging | `scripts/build_artifact.sh`, `ClosedRoom.spec` | finalizer/smoke/artifact evidence |
| CI | selector + `.github/workflows/preflight.yml` | exact-head/base evidence |

Follow the closest scoped `AGENTS.md`. Extend one canonical owner before introducing state/policy; inspect material consumers when a shared boundary changes.

## Read by task

| Task | Read now |
| --- | --- |
| Pure docs/copy | affected source/links; `docs/README.md` only if ownership unclear |
| Behavior/bug/contract | `skills/structured-change/SKILL.md`, `skills/validate-change/SKILL.md`, relevant commands |
| Material UI | above + `skills/design-product-experience/SKILL.md`, relevant `design/*` |
| Integration/release | `skills/preflight-change/SKILL.md`, commands, affected `.engineering/e2e.json` |
| Missing deterministic remote gate | `skills/remote-preflight/SKILL.md` |
| Persistent multi-session work | `skills/plan-workstream/SKILL.md` + active plan; finalize with `skills/finalize-workstream/SKILL.md` |

## Delivery and evidence

- **ITERATION**: focused owner-local falsification; no exact-head/full-diff/docs/publication ceremony per edit.
- **INTEGRATION** (`PR -> dev`): coherent observable outcome, exact head/base, complete diff, affected durable docs, required automated gates and affected automated E2E. Material UI/UX integration journeys require `FULL_MEDIA`. Genuine TCC, physical-audio, representative MLX/Metal or interactive target-Mac gaps are `DEFERRED_TO_RELEASE`.
- **RELEASE** (`dev -> main`): `FULL` plus release-critical artifact/E2E and every applicable required target-Mac confirmation.

The selector resolves risks -> concrete gates -> profile. Profiles are shorthand. `.github/workflows/preflight.yml` owns remote deterministic validation; missing local tooling never makes the user the fallback runner. Reuse evidence only when head/tree/base/gates/profile/material E2E identity remain equivalent.

## Context, diagnosis and completion

`.engineering/documentation-policy.json` owns bounded context routes. Use `python3 scripts/verify_agent_context.py --route bug --format json`, optionally with `--path`/`--workstream`; routes estimate context cost, not validation scope.

For meaningful work state observable outcome, owner, invariants and proof. Classify failures before patching. Each failed repair needs a falsifiable hypothesis; after two failed repairs with the same signature, change diagnostic strategy and obtain new discriminating evidence before a third. On resume refresh head/tree/base; checkpoint evidence is a pointer, not current-source proof.

Before integration update affected canonical docs. Transfer durable truth and deferred release obligations before deleting completed plans. Never weaken privacy/auth/migration/resource cleanup, mutate finalized artifacts, create a second owner or overclaim hosted macOS evidence as target-Mac proof.
