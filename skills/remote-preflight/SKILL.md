---
name: remote-preflight
description: Reuse equivalent ClosedRoom preflight evidence first, then run only missing deterministic integration/release gates.
---
# Remote Preflight
Resolve exact PR head/tree/base, risks/gates/profile and material E2E identity. Reuse trusted sufficient evidence before dispatching missing/stale/invalidated deterministic gates through `.github/workflows/preflight.yml`. Post-merge tree reuse requires equivalent final tree/base/gates/E2E. Never delegate automatable work to the user or convert deferred target-Mac evidence into PASS. Report bounded source/gate/evidence/gap fields.
