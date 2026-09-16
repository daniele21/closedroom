# ClosedRoom GitHub release productization

Status: ACTIVE
Owner: repository release metadata, version identity, publication automation and public release experience
Base: `dev@7041779f1841e80db4145a113ee8d60ef14d5ae3`

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

A normal public ClosedRoom release exposes:

- semantic tag `vX.Y.Z` and title `ClosedRoom vX.Y.Z`;
- user-oriented release notes grouped around observable changes rather than raw commits;
- `ClosedRoom-vX.Y.Z-macos-arm64.dmg` as the primary macOS asset when distribution authority is available;
- `SHA256SUMS` generated against the public asset names;
- `build-manifest.json` with exact source/build identity;
- `BUILD_CHANGELOG.md` as the technical build delta;
- GitHub-provided source archives;
- explicit prerelease/latest state;
- concise known limitations, privacy and compatibility notes.

The public DMG is a byte-for-byte copy of the already-qualified immutable production DMG. Publication staging may rename it, but must never rebuild or mutate it.

## Work graph

| ID | Observable outcome | State |
| --- | --- | --- |
| GRP-1 | Stable source promotion is explicitly separated from binary distribution | DONE |
| GRP-2 | ClosedRoom has one canonical product version consumed by bundle/build/release metadata | DONE |
| GRP-3 | Release notes/categories and public asset naming are repository contracts | DONE |
| GRP-4 | A tag/main-bound workflow creates a draft GitHub Release from qualified immutable artifacts | READY |
| GRP-5 | Developer ID/notarization credentials can satisfy publication gates without changing product behavior | BLOCKED |
| GRP-6 | First public GitHub Release is published from an exact stable commit | BLOCKED |

GRP-5 is externally blocked until Apple Developer distribution authority exists. GRP-6 depends on GRP-1..5 and must never treat that external block as a reason to weaken signing/notarization truth.

## GRP-1 — separate stable source from distribution

### Outcome

Repository governance distinguishes:

- **stable source promotion**: `dev -> main`, exact-head FULL validation plus applicable target-Mac product evidence;
- **distribution release**: tagged publication from `main`, additionally requiring production artifact signing/notarization/stapling/Gatekeeper evidence and immutable asset publication.

Apple distribution authority does not block a truthful stable-source promotion when all product/runtime release evidence required for that promotion is green. It continues to block public signed binary publication.

### Implementation

- `CONTRIBUTING.md` defines `main` as stable source and GitHub Release as a separate distribution event.
- `docs/current-state.md` separates stable candidate evidence from distribution-only Developer ID/notary/Gatekeeper obligations.
- Existing automation supports the split: `dev -> main` selects RELEASE / FULL automated gates, while production signing/notarization is executed through the separate `release_build` / `release_evidence` commands rather than the hosted preflight workflow.
- `.engineering/e2e.json` continues to require applicable REAL_ENVIRONMENT product/runtime evidence at stable promotion; no target-Mac product evidence was downgraded.

### Acceptance

- no canonical documentation claims Apple distribution authority is required merely to make source stable on `main`;
- stable-source promotion remains FULL and exact-head;
- physical/TCC/audio/MLX obligations remain explicit where they materially prove the stable candidate;
- unsigned/ad-hoc artifacts are never presented as public production downloads.

## GRP-2 — canonical ClosedRoom version

### Outcome

One repository-owned product version drives the macOS bundle/build identity, artifact filenames, manifest, release tag/title and visible application version.

### Implementation

- root `VERSION` is the sole product-version data owner; current product version is `0.2.0`;
- `scripts/product_version.py` validates numeric `X.Y.Z`, derives `vX.Y.Z`, and fails closed when an explicit release tag disagrees with the product version;
- `build.sh`, `ClosedRoom.spec`, `scripts/build_artifact.sh` and `scripts/build_production_artifact.py` consume that canonical owner;
- the nested native-capture helper bundle inherits the same product version;
- `pyproject.toml` remains the independent `local-asr-server` implementation-package identity (`0.1.0`) and is no longer a product-version source;
- cheap contract tests verify tag/version behavior and prevent product build paths from silently returning to package metadata.

### Acceptance

- one `VERSION` edit changes the intended ClosedRoom release version everywhere through deterministic consumers;
- build/release tooling fails on invalid or mismatched explicit tag/version rather than silently publishing inconsistent identities;
- `vX.Y.Z` maps deterministically to product version `X.Y.Z`;
- version resolution and its direct build consumers are covered by cheap tests.

## GRP-3 — release metadata and notes

### Outcome

The repository defines a deterministic, dry-runnable public release surface without introducing a second build owner.

### Implementation

- `.github/release.yml` defines generated-note categories for features, fixes, performance/reliability, engineering/documentation and a catch-all category;
- `docs/releases/v0.2.0.md` is the curated source for the next release and must contain Highlights, Compatibility, Installation, Privacy and Known limitations sections;
- `scripts/prepare_github_release.py` is a publication adapter over one already-finalized production artifact;
- the adapter requires tag ↔ root `VERSION` agreement, exact clean source revision, `macos/arm64/release/package` lineage, `developer-id-notarized` manifest signing, complete production notarization/stapling/Gatekeeper evidence and matching manifest/checksum/DMG bytes;
- staging copies the exact qualified DMG bytes to `ClosedRoom-vX.Y.Z-macos-arm64.dmg`, copies `build-manifest.json` and `BUILD_CHANGELOG.md`, regenerates `SHA256SUMS` against public names, and emits `RELEASE_NOTES.md` plus an internal `release-plan.json`;
- release state is explicit (`stable` or `prerelease`) in the plan rather than inferred from the version number;
- `.engineering/commands.json` registers `release_prepare` as the canonical preparation command;
- fixture tests prove same-byte staging and fail closed on version mismatch, weak signing, modified DMG, incomplete production evidence or incomplete user-facing notes.

### Acceptance

A dry-run can produce the complete title/body/public asset inventory for `vX.Y.Z` without contacting GitHub or changing the qualified artifact. README distribution links remain unchanged until a downloadable release actually exists.

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

Version/build/workflow changes are FULL because they touch release/build/CI identity. Apple signing/notarization execution is REAL_ENVIRONMENT / protected authority. GitHub Actions publication mechanics are REMOTE_AUTOMATED.

## Resume checkpoint

- base refreshed to `dev@7041779f1841e80db4145a113ee8d60ef14d5ae3` after GRP-2 integrated through PR #66;
- GRP-1: integrated stable-source/distribution separation;
- GRP-2: integrated root `VERSION=0.2.0`; FULL source, packaging and packaged-app smoke evidence passed before merge;
- GRP-3: implemented deterministic release notes/asset staging over immutable production evidence without a second build path;
- confirmed: historical tag `v0.1.0` already exists but no GitHub Release currently exists, so the next ClosedRoom product line is `0.2.0` / `v0.2.0`;
- external block: Apple Developer distribution authority affects GRP-5/6 only;
- next action: implement GRP-4 workflow-dispatch automation that binds tag/main/source/artifact identities and creates or updates a draft GitHub Release from GRP-3 output.
