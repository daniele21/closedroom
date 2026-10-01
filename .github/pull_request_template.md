## Outcome

Describe the user/system outcome and the owning boundary changed.

## Branch flow

- Target branch: `dev` for ordinary work / `main` only for `dev -> main` stable promotion
- Source branch:
- [ ] This PR follows the canonical `feature|fix|chore -> dev` or `dev -> main` flow

## Scope and contracts

- Owning source(s):
- Public/persistence/security/runtime/UI contract impact:

## Documentation impact

Classify each owner as `UPDATED` or `N/A`; give a short reason when impact was plausible but is `N/A`.

- README_IDENTITY:
- README_USAGE:
- FEATURE_DOCS:
- ARCHITECTURE:
- ADR:
- SECURITY_DATA:
- OPERATIONS:
- PRODUCT_EXPERIENCE:
- CURRENT_STATE:
- DOCS_CURRENT_WITH_IMPLEMENTATION: PASS / FAIL

README identity means purpose/audience/outcome/positioning. README usage means prerequisites/setup/run/configuration/public API/UI/examples. A usage-only change must not trigger an opportunistic mission rewrite.

## Validation

- Selected profile: LEAN / SCOPED / STRONG / FULL
- Profile reason:
- AGENT_LOCAL gates and result:
- REMOTE_AUTOMATED gates and result/pending:
- REAL_ENVIRONMENT evidence and result/pending:

If E2E applies, record the journey, `.engineering/e2e.json` environment ID, fidelity class and residual gaps. Do not promote source/emulator evidence into packaged/physical target evidence.

## Readiness

- [ ] Material ambiguity resolved
- [ ] Intended target base/head identity checked
- [ ] Complete diff reviewed for unrelated/generated/private residue
- [ ] Documentation impact assessed and every affected canonical owner is current
- [ ] Required deterministic gates for the selected profile passed or are explicitly routed
- [ ] Failure root causes were diagnosed rather than suppressed
- [ ] Cleanup/residue expectations are satisfied for executed runtime/E2E/build work
- [ ] Sensitive audio/transcript/credentials are absent from the diff and evidence
