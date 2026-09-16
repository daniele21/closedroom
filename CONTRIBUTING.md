# Contributing to ClosedRoom

ClosedRoom combines Python/FastAPI, React/TypeScript, macOS native helpers, local AI runtimes and a packaged desktop application. Changes should preserve the repository's existing ownership boundaries rather than adding parallel mechanisms.

## Before changing code

Read `AGENTS.md`, then the smallest relevant architecture/feature/design sources. Use `.engineering/commands.json` for canonical operations and `.engineering/e2e.json` when a complete workflow or environment-dependent claim is involved.

For meaningful changes use the repo-local `structured-change` skill. For meaningful UX/UI semantics also use `design-product-experience`.

## Development principles

- Keep local-first behavior and explicit provider trust boundaries.
- Extend the owning service/runtime/store/configuration rather than duplicating state.
- Keep public API/schema/frontend consumers synchronized.
- Keep expensive local model loads out of cheap tests; use deterministic fixtures/mocks when they prove the invariant.
- Preserve cancellation, shutdown, failure recovery and cleanup for run-owned processes, listeners, devices, jobs and temporary files.
- Do not hand-edit generated Vite assets when the frontend source can regenerate them.

## Branch strategy

ClosedRoom uses `dev -> main` as the canonical flow.

- `dev` is the integration/development branch. Feature, fix, refactor, UX/UI and engineering work should branch from the latest `dev` and open a pull request back to `dev`.
- `main` is the stable **source** branch. It should receive changes only through a promotion pull request from `dev` after exact-head RELEASE / FULL automation and every applicable target-Mac product/runtime evidence gate are green.
- A public GitHub Release is a separate distribution event from an exact `main` commit/tag. It additionally requires the production artifact distribution contract (Developer ID signing, secure timestamp, notarization/stapling, Gatekeeper evidence and immutable release assets) before a macOS binary is published as stable.
- Missing Apple distribution authority therefore blocks binary publication, not a truthful stable-source promotion whose product/runtime release evidence is otherwise complete.
- Direct feature branches to `main` are non-canonical and fail the repository branch-flow preflight.
- `speaker_detection` is retained only as historical context for the earlier product line; it is not a canonical development or release target.
- Keep `dev` rebased/merged from the latest accepted work before opening `dev -> main`; do not maintain independent product changes directly on `main`.

## Validation

Use the narrowest sufficient iteration checks, then `preflight-change` before publication. Canonical commands and current availability are defined in `.engineering/commands.json`.

Repository health checks are intentionally zero-dependency and run on pull requests. Python tests, frontend lint/typecheck, package/build and real macOS evidence are separate evidence layers; do not treat one as proof of another.

When an E2E claim depends on macOS permissions/audio hardware, packaged app behavior or production local-model performance, report the actual environment and residual gaps from `.engineering/e2e.json`.

Stable-source promotion remains a RELEASE / FULL boundary. GitHub binary publication adds distribution qualification on top; it does not replace or weaken the product/runtime evidence required for `main`.

## Pull requests

Keep one coherent outcome per PR. Describe the owning boundary, user-visible/contract impact, selected validation profile, executed evidence, pending remote/real-environment evidence and documentation/design-contract changes. Never mark a known-red or unexecuted gate as passing.

Before opening a PR, verify the target branch explicitly: ordinary work targets `dev`; only stable-source promotion uses `dev -> main`. Public binary publication starts from an exact stable `main` commit/tag rather than from an ordinary feature branch.
