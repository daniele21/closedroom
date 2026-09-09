# ClosedRoom documentation

Use documentation by ownership, not chronology.

- README identity sections — what ClosedRoom is, why it exists, its primary audience/outcome and stable positioning.
- README usage sections — current prerequisites, setup, run/start, configuration and public usage/examples.
- `architecture.md` — current detailed architecture, ownership and system boundaries.
- `features.md` — existing aggregate registry of current product behavior and verification hints.
- `current-state.md` — short operational/maturity ledger and current gaps.
- `real-environment-release.md` — operator runbook for the frozen PRS-18 Apple-Silicon candidate and automated target-Mac release evidence.
- `local-real-environment.md` — one-command target-Mac evidence path for a finalized ad-hoc artifact when Apple Developer distribution authority is unavailable.
- `features/` — bounded feature documents only when splitting durable behavior reduces context or duplication.
- `adr/` — accepted durable decisions whose rationale remains useful.
- `workstreams/` — active implementation plans only; completed plans are deleted by default after durable truth is transferred.
- `assets/` — bounded reference/demo assets; generated test evidence should live in CI artifacts instead.

Older implementation/refactoring plans in this directory are historical inputs, not automatically current truth. Validate them against code, `architecture.md`, `features.md` and current tests before using them for implementation decisions.

## Documentation impact contract

Code and durable documentation ship together. A meaningful change is not complete until every affected canonical owner describes the system as it exists after that change. Do not update every document mechanically: update only affected owners and record plausible-but-unaffected owners as `N/A` during preflight.

Treat the README as two semantic owners:

- **Identity** changes only when ClosedRoom's purpose, primary audience/outcome or positioning changes. Do not opportunistically rewrite it for implementation, feature, command or configuration changes.
- **Usage** changes whenever prerequisites, setup, run/start, configuration, public API/UI workflow or copy-paste examples would otherwise become incomplete, incorrect or misleading.

A change may therefore legitimately report `README_IDENTITY: N/A` and `README_USAGE: UPDATED`.

Use this routing for other durable impact: feature behavior -> `features.md` or its bounded `features/` owner; architecture/ownership -> `architecture.md`; durable rationale -> ADR; trust/privacy/data lifecycle -> `SECURITY.md` and/or the owning architecture/feature doc; canonical command semantics -> `.engineering/commands.json`; product-experience contracts -> `design/*`; integrated/blocker/next truth -> `current-state.md`.

## Lifecycle

Assess documentation impact from observable behavior, not filenames. Search for the existing owner first. Existing feature documentation must be updated in the same change when the behavior it describes changes. Create a new feature document only when durable non-obvious behavior is not sufficiently discoverable from code, public contracts, tests or the existing aggregate registry.

Active work remains disposable:

`plan -> implement -> validate -> transfer durable knowledge -> delete plan`

Do not create documentation merely to record that a PR or task completed.
