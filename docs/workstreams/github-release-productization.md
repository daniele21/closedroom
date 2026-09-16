# ClosedRoom GitHub release productization

Status: ACTIVE
Owner: repository release metadata, version identity, publication automation and public release experience
Base: `dev@7041779f1841e80db4145a113ee8d60ef14d5ae3`

## Outcome

Make ClosedRoom behave like a mature GitHub-distributed macOS project: `main` is stable source, while a public GitHub Release is a separate distribution event from one exact `main` commit/tag with user-facing notes, immutable artifacts, checksums/provenance and explicit Apple distribution evidence.

Do not weaken the local-first/privacy boundary or relabel ad-hoc evidence as signed/notarized distribution evidence.

## Non-goals

- No product features, runtime behavior changes or second build owner.
- No automatic binary publication for every `dev -> main` promotion.
- No unsigned/unnotarized artifact presented as a normal stable download.
- No duplicate product-version owners.
- No rebuilding after qualification.

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

`main` means stable integrated source. A GitHub Release is separately versioned and distribution-qualified.

## Release surface contract

A normal public release exposes:

- tag `vX.Y.Z` and title `ClosedRoom vX.Y.Z`;
- user-oriented release notes;
- `ClosedRoom-vX.Y.Z-macos-arm64.dmg` when distribution authority is available;
- `SHA256SUMS` against public asset names;
- `build-manifest.json` and `BUILD_CHANGELOG.md`;
- GitHub source archives;
- explicit prerelease/latest state;
- concise compatibility, privacy and known-limitations notes.

The public DMG is a byte-for-byte copy of the qualified production DMG. Staging may rename it, never rebuild or mutate it.

## Work graph

| ID | Observable outcome | State |
| --- | --- | --- |
| GRP-1 | Stable source promotion is separated from binary distribution | DONE |
| GRP-2 | One canonical product version drives bundle/build/release identity | DONE |
| GRP-3 | Release notes/categories and public asset naming are contracts | DONE |
| GRP-4 | Tag/main-bound workflow creates a draft Release from qualified artifacts | READY |
| GRP-5 | Developer ID/notarization credentials satisfy publication gates | BLOCKED |
| GRP-6 | First public GitHub Release is published from exact stable source | BLOCKED |

GRP-5 is externally blocked until Apple Developer distribution authority exists. GRP-6 depends on GRP-1..5; that external block must never weaken signing/notarization truth.

## GRP-1 — separate stable source from distribution

### Outcome

Repository governance distinguishes:

- **stable source promotion**: `dev -> main`, exact-head FULL plus applicable target-Mac product evidence;
- **distribution release**: tagged publication from `main`, additionally requiring signing/notarization/stapling/Gatekeeper proof and immutable asset publication.

Apple authority does not block truthful stable-source promotion when required product/runtime evidence is green. It blocks public signed binary publication.

### Implementation

- `CONTRIBUTING.md` defines `main` as stable source and GitHub Release as a separate event.
- `docs/current-state.md` separates stable-candidate evidence from distribution-only Apple obligations.
- `dev -> main` selects RELEASE/FULL; production signing/notarization stays in `release_build` / `release_evidence`.
- `.engineering/e2e.json` keeps applicable REAL_ENVIRONMENT product/runtime evidence release-blocking.

### Acceptance

- Apple authority is not claimed as a prerequisite merely for stable source;
- stable-source promotion remains FULL and exact-head;
- physical/TCC/audio/MLX obligations remain explicit where material;
- ad-hoc artifacts are never presented as public production downloads.

## GRP-2 — canonical ClosedRoom version

### Outcome

One repository-owned product version drives macOS bundle/build identity, artifact names, manifest, tag/title and visible app version.

### Implementation

- root `VERSION` is the sole product-version owner; current value `0.2.0`;
- `scripts/product_version.py` validates `X.Y.Z`, derives `vX.Y.Z`, and rejects tag mismatch;
- `build.sh`, `ClosedRoom.spec`, `scripts/build_artifact.sh` and `scripts/build_production_artifact.py` consume it;
- native-capture helper inherits the same product version;
- `pyproject.toml` remains independent `local-asr-server` package metadata (`0.1.0`);
- cheap contract tests prevent build paths from returning to package metadata.

### Acceptance

- one `VERSION` edit changes intended product version through deterministic consumers;
- invalid/mismatched explicit tag/version fails closed;
- `vX.Y.Z` maps deterministically to `X.Y.Z`;
- direct consumers are covered by tests.

## GRP-3 — release metadata and notes

### Outcome

Define a deterministic, dry-runnable public release surface without a second build owner.

### Implementation

- `.github/release.yml` defines generated-note categories;
- `docs/releases/v0.2.0.md` is the curated next-release source with Highlights, Compatibility, Installation, Privacy and Known limitations;
- `scripts/prepare_github_release.py` adapts one finalized production artifact;
- it requires tag ↔ `VERSION`, exact clean source, `macos/arm64/release/package` lineage, `developer-id-notarized` signing, complete notarization/stapling/Gatekeeper evidence and matching manifest/checksum/DMG bytes;
- staging copies the exact DMG to `ClosedRoom-vX.Y.Z-macos-arm64.dmg`, copies manifest/changelog, regenerates public `SHA256SUMS`, and emits `RELEASE_NOTES.md` plus `release-plan.json`;
- release state is explicit (`stable` or `prerelease`);
- `.engineering/commands.json` registers `release_prepare`;
- fixture tests prove same-byte staging and fail closed on mismatches or incomplete evidence/notes.

### Acceptance

A dry-run produces title/body/public asset inventory for `vX.Y.Z` without contacting GitHub or changing the qualified artifact. README download links stay unchanged until a release exists.

## GRP-4 — draft GitHub Release automation

### Outcome

A repository-owned workflow creates or updates a **draft** GitHub Release for an exact tag/commit, attaches already-qualified immutable assets and rejects incomplete/mismatched evidence.

### Invariants

- build once, qualify once, publish those same bytes;
- tag commit must be on `main` and match manifest source identity;
- workflow permissions are minimal and release authority explicit;
- missing signing/checksums/manifest/assets fail closed;
- automation handles source/build metadata only, never meeting/user content.

### Publication model

Automatic draft creation is acceptable. Final publication remains explicit until repeated releases justify further automation.

## GRP-5 — Apple distribution authority

### Outcome

Existing production build tooling can use protected Developer ID/notary authority for signed, timestamped, notarized/stapled app + DMG and Gatekeeper proof.

### Boundary

This is an execution/authority requirement, not product implementation. Missing authority is `BLOCKED`, never product failure and never bypassed with an unsigned artifact labeled stable.

## GRP-6 — first public release

### Outcome

Publish the first release from an exact stable `main` commit with a deliberate pre-1.0 product version while compatibility contracts still evolve.

### Final acceptance

- tag ↔ commit ↔ manifest ↔ checksums ↔ DMG agree;
- Release page has curated notes, installation expectations and known limitations;
- primary DMG is signed/notarized and passes distribution checks;
- README links to downloads only after publication;
- source-build instructions remain available;
- durable evidence exists and completed workstream truth moves to canonical owners.

## Parallel ownership with PRS-18

PRS-18 owns measured product/runtime evidence: WKWebView/TCC capture, local MLX/resource/thermal, PRS-9 benchmark and PRS-16 contention.

This workstream owns version/release/publication mechanics and must not edit runtime/audio/meeting behavior. At publication, GRP consumes successful exact-candidate evidence; it never redefines a failing product observation as passing.

## Validation

Version/build/workflow changes are FULL because they touch release/build/CI identity. Apple signing/notarization is REAL_ENVIRONMENT / protected authority. GitHub publication mechanics are REMOTE_AUTOMATED.

## Resume checkpoint

- base: `dev@7041779f1841e80db4145a113ee8d60ef14d5ae3` after GRP-2 / PR #66;
- GRP-1 integrated stable-source/distribution separation;
- GRP-2 integrated root `VERSION=0.2.0`; FULL source, packaging and app-smoke evidence passed before merge;
- GRP-3 implemented deterministic release notes/asset staging over immutable production evidence;
- historical tag `v0.1.0` exists but no GitHub Release exists; next product line is `0.2.0` / `v0.2.0`;
- Apple Developer distribution authority blocks GRP-5/6 only;
- next: GRP-4 workflow-dispatch automation bound to tag/main/source/artifact identities and draft Release creation from GRP-3 output.
