# ClosedRoom GitHub release productization

Status: ACTIVE
Owner: repository release metadata, version identity, publication automation and public release experience
Base: `dev@06bfefe66f38475589f86b51fe54850b2c452eba`

## Outcome

Make ClosedRoom look and behave like a mature GitHub-distributed macOS project: `main` is the stable source line, while a public GitHub Release is a deliberate distribution event from one exact `main` commit/tag with user-facing notes, immutable macOS artifacts, checksums/provenance and explicit Apple distribution evidence.

This workstream must not weaken ClosedRoom's local-first/privacy boundary or relabel ad-hoc local evidence as signed/notarized distribution evidence.

## Non-goals

- Do not add product features, change meeting/runtime behavior or create a second build owner.
- Do not make every `dev -> main` promotion publish a binary automatically.
- Do not silently publish an unsigned/unnotarized artifact as a normal stable macOS download.
- Do not derive product version independently in multiple files or workflows.
- Do not rebuild a release artifact after qualification and then publish the different bytes.

## Target lifecycle

```text
feature/fix branches
        ↓
       dev
        ↓  exact-head FULL + applicable REAL_ENVIRONMENT
       main                 ← stable source promotion
        ↓
  choose version/tag
        ↓
 distribution qualification
        ↓
 signed + notarized immutable artifact
        ↓
 draft GitHub Release
        ↓
 publish vX.Y.Z             ← public distribution event
```

`main` therefore means stable integrated source. A GitHub Release means a separately versioned and distribution-qualified publication from an exact `main` commit.

## Release surface contract

A normal public ClosedRoom release should expose:

- semantic tag `vX.Y.Z` and title `ClosedRoom vX.Y.Z`;
- user-oriented release notes grouped around observable changes rather than raw commits;
- `ClosedRoom-vX.Y.Z-macos-arm64.dmg` as the primary macOS asset when distribution authority is available;
- optional app archive only when it has the same qualified artifact lineage;
- `SHA256SUMS`;
- `build-manifest.json` with exact source/build identity;
- `BUILD_CHANGELOG.md` as the technical build delta;
- GitHub-provided source archives;
- explicit prerelease/latest state;
- concise known limitations and compatibility notes when material.

Release notes may use GitHub-generated PR/contributor sections, but the top section remains curated for users.

## Work graph

| ID | Observable outcome | State |
| --- | --- | --- |
| GRP-1 | Stable source promotion is explicitly separated from binary distribution | ACTIVE |
| GRP-2 | ClosedRoom has one canonical product version consumed by bundle/build/release metadata | READY |
| GRP-3 | Release notes/categories and public asset naming are repository contracts | READY |
| GRP-4 | A tag/main-bound workflow creates a draft GitHub Release from qualified immutable artifacts | READY |
| GRP-5 | Developer ID/notarization credentials can satisfy publication gates without changing product behavior | BLOCKED |
| GRP-6 | First public GitHub Release is published from an exact stable commit | BLOCKED |

GRP-5 is externally blocked until Apple Developer distribution authority exists. GRP-6 depends on GRP-1..5 and must never treat that external block as a reason to weaken signing/notarization truth.

## GRP-1 — separate stable source from distribution

### Outcome

Repository governance distinguishes:

- **stable source promotion**: `dev -> main`, exact-head FULL validation plus applicable target-Mac product evidence;
- **distribution release**: tagged publication from `main`, additionally requiring production artifact signing/notarization/stapling/Gatekeeper evidence and immutable asset publication.

Apple distribution authority must not block a truthful stable-source promotion when all product/integration release evidence required for that promotion is green. It continues to block public signed binary publication.

### Required owners

Update the existing owners instead of adding parallel policy:

- `.engineering/commands.json`;
- `.engineering/e2e.json` where stage/evidence wording requires it;
- `CONTRIBUTING.md` and `docs/current-state.md`;
- release/preflight automation only when implementation requires it.

### Acceptance

- no document simultaneously claims that `main` requires Apple distribution authority and that authority is a separate publication concern;
- stable-source promotion remains FULL and exact-head;
- physical/TCC/audio/MLX obligations remain explicit where they materially prove the stable candidate;
- unsigned/ad-hoc artifacts are never presented as public production downloads.

## GRP-2 — canonical ClosedRoom version

### Outcome

One repository-owned product version drives the macOS bundle/build identity, artifact filenames, manifest, release tag/title and visible application version.

### Direction

Prefer a small canonical text/JSON owner dedicated to the product version rather than treating the legacy Python package version (`local-asr-server`) as the ClosedRoom product version. Existing package metadata may remain independently versioned if it is an implementation package rather than the distributed product.

### Acceptance

- one edit changes the intended ClosedRoom release version everywhere through deterministic consumers;
- build fails on mismatched explicit tag/version rather than silently publishing inconsistent identities;
- `vX.Y.Z` maps deterministically to product version `X.Y.Z`;
- version resolution is covered by cheap tests.

## GRP-3 — release metadata and notes

### Outcome

The repository defines a predictable public release page comparable to mature GitHub projects.

### Deliverables

- `.github/release.yml` for generated-note categories/contributors where useful;
- a concise release-note template/generator that keeps a curated user-facing summary first;
- canonical asset naming and required-asset validation;
- compatibility/known-limitations section when material;
- README distribution section updated only when the first downloadable release actually exists.

### Acceptance

A dry-run can produce the complete title/body/asset inventory for `vX.Y.Z` without publishing anything.

## GRP-4 — draft GitHub Release automation

### Outcome

A repository-owned workflow creates or updates a **draft** GitHub Release for an exact tag/commit, attaches the already-qualified immutable assets and refuses to publish incomplete or mismatched evidence.

### Invariants

- build once, qualify those exact bytes, publish those exact bytes;
- tag commit must be on `main` and match manifest source identity;
- workflow permissions are minimal and publication requires explicit release authority;
- failed/missing signing, checksums, manifest or expected assets fail closed;
- no cloud processing of meeting/user content is introduced; release automation handles source/build metadata only.

### Publication model

Automatic draft creation is acceptable. Final publication should remain an explicit release action until repeated releases demonstrate that fully automatic publication is safer and useful.

## GRP-5 — Apple distribution authority

### Outcome

The existing production build path can run with repository/environment secrets for Developer ID signing, secure timestamp, app + DMG notarization/stapling and Gatekeeper assessment.

### Boundary

This is an execution/authority requirement, not a product implementation requirement. Missing membership/credentials is reported as `BLOCKED`, never as product failure and never bypassed with an unsigned artifact labeled stable.

## GRP-6 — first public release

### Outcome

Publish the first ClosedRoom GitHub Release from an exact stable `main` commit with a version chosen deliberately for project maturity (likely pre-1.0 while compatibility/product contracts are still evolving).

### Final acceptance

- exact tag ↔ commit ↔ manifest ↔ checksums ↔ DMG agree;
- GitHub Release page has curated user-facing notes, installation expectations and known limitations;
- primary downloadable asset is signed/notarized and passes the repository distribution checks;
- README links to the release/download path only after publication;
- previous source-built instructions remain available for contributors;
- release evidence is durable and the completed workstream is deleted after truth transfers to canonical owners.

## Parallel ownership with PRS-18

PRS-18 continues to own measured product/runtime release evidence: packaged WKWebView/TCC capture, local MLX/resource/thermal observations, PRS-9 benchmark and PRS-16 contention.

This workstream owns public release/version/publication mechanics. It must not edit runtime/audio/meeting behavior to satisfy publication mechanics.

The two converge at the publication boundary: GRP consumes successful exact-candidate evidence; it does not redefine a failing product observation as passing.

## Validation

Initial planning/governance changes are LEAN. Version/build/workflow changes are FULL because they touch release/build/CI identity. Apple signing/notarization execution is REAL_ENVIRONMENT / protected authority. GitHub Actions publication mechanics are REMOTE_AUTOMATED.

## Resume checkpoint

- base: `dev@06bfefe66f38475589f86b51fe54850b2c452eba`;
- confirmed: no GitHub Releases currently exist and no dedicated release-publication workflow exists;
- confirmed: existing production tooling already owns immutable manifests/checksums/build delta and signed/notarized artifact qualification;
- confirmed: README currently describes ClosedRoom as source-built with no public binary release;
- external block: Apple Developer distribution authority;
- next action: implement GRP-1 in canonical governance/command owners, then GRP-2 canonical version identity before adding publication automation.
