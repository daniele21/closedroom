# ClosedRoom GitHub release productization

Status: ACTIVE
Owner: repository release metadata, version identity, publication automation and public release experience
Base: `dev@685aad5e6040097631f0c9bb4562ae57c2dc72fa`

## Outcome

Make ClosedRoom behave like a mature GitHub-distributed macOS project: `main` is stable source, while a public GitHub Release is a separate distribution event from one exact `main` commit/tag with user-facing notes, immutable artifacts, checksums/provenance and explicit Apple distribution evidence.

Do not weaken the local-first/privacy boundary or relabel ad-hoc evidence as signed/notarized distribution evidence.

## Non-goals

- No product features, runtime behavior changes or second build owner.
- No automatic binary publication for every `dev -> main` promotion.
- No unsigned/unnotarized artifact presented as a stable download.
- No duplicate product-version owners or rebuilding after qualification.

## Target lifecycle

```text
feature/fix → dev
              ↓ exact-head FULL + applicable REAL_ENVIRONMENT
             main                 ← stable source
              ↓ exact tag/version
 distribution qualification
              ↓
 signed + notarized immutable artifact
              ↓
 draft GitHub Release
              ↓ explicit publication
          vX.Y.Z
```

A GitHub Release is separately versioned and distribution-qualified from stable source.

## Release surface contract

A public release exposes tag/title `vX.Y.Z` / `ClosedRoom vX.Y.Z`, curated notes, `ClosedRoom-vX.Y.Z-macos-arm64.dmg`, `SHA256SUMS`, `build-manifest.json`, `BUILD_CHANGELOG.md`, GitHub source archives, explicit prerelease/latest state, compatibility/privacy/known-limitations notes.

The public DMG is a byte-for-byte copy of the qualified production DMG. Staging may rename it, never rebuild or mutate it.

## Work graph

| ID | Observable outcome | State |
| --- | --- | --- |
| GRP-1 | Stable source promotion separated from binary distribution | DONE |
| GRP-2 | Canonical product version drives bundle/build/release identity | DONE |
| GRP-3 | Release notes/categories and public asset naming are contracts | DONE |
| GRP-4 | Tag/main-bound local command creates a draft Release from locally qualified artifacts | LOCAL COMMAND IMPLEMENTED |
| GRP-5 | Production build/sign/notarize is local-only on the release Mac | LOCAL TOOLING DONE; APPLE AUTHORITY BLOCKED |
| GRP-6 | First public GitHub Release from exact stable source | BLOCKED |

GRP-5 execution is externally blocked until the `production-release` environment and Apple Developer distribution authority are configured. GRP-6 depends on GRP-1..5; never weaken signing/notarization truth to bypass that block.

## GRP-1 — stable source vs distribution

Stable promotion is `dev -> main`, exact-head FULL plus applicable target-Mac evidence. Distribution is a tagged `main` publication requiring signing/notarization/stapling/Gatekeeper proof and immutable assets. `CONTRIBUTING.md`, current-state, release commands and E2E policy preserve this split. Apple authority blocks public binary distribution, not truthful stable source.

## GRP-2 — canonical ClosedRoom version

Root `VERSION` is the sole product-version owner (`0.2.0`). `scripts/product_version.py` validates `X.Y.Z`, maps `vX.Y.Z`, and rejects mismatches. macOS build/package consumers use it; the native helper inherits it. Runtime/install identity is deliberately independent from product version: local and packaged builds keep `ClosedRoom.app`, display name `ClosedRoom`, and bundle ID `com.closedroom.app` stable, while DMGs and immutable finalized artifacts carry product version plus build/source identity. `pyproject.toml` remains independent `local-asr-server` metadata (`0.1.0`). Tests prevent product build paths returning to package metadata or versioning the runtime app name.

## GRP-3 — release metadata and staging

`.github/release.yml` defines note categories and `docs/releases/v0.2.0.md` is the curated next-release source. `scripts/prepare_github_release.py` adapts one finalized production artifact and requires tag/version agreement, exact clean source, `macos/arm64/release/package` lineage, `developer-id-notarized` signing, complete Apple evidence and matching manifest/checksum/DMG bytes.

It copies unchanged DMG bytes to the public name, copies manifest/changelog, regenerates public checksums and emits `RELEASE_NOTES.md` + `release-plan.json`. `release_prepare` is canonical; fixture tests prove same-byte staging and fail closed. README download links remain unchanged until a release exists.

## GRP-4 — local draft GitHub Release publication

GitHub Actions intentionally does not run release builds, signing, notarization or asset uploads. Run `scripts/publish_local_draft_release.sh` **on the release Mac**, after GRP-3 has locally qualified the same immutable artifact. The script requires a clean exact tagged checkout in `main` history, matching `VERSION` and curated release notes. `scripts/prepare_github_release.py` checks the Developer-ID/notarization/stapling/Gatekeeper evidence and checksums, and stages unchanged DMG bytes.

The local command creates a **draft only**, refuses an existing release instead of overwriting it, and verifies staged inventory; publication remains an explicit separate action. Only public release assets are intentionally uploaded to GitHub Releases, never private meeting data or GitHub Actions artifacts.

## GRP-5 — local-only Apple distribution authority

`release_build` invokes the canonical `scripts/build_production_artifact.py` locally with the release Mac's Developer ID and notarytool profile. The retired `.github/workflows/production-release-artifact.yml` and `draft-release.yml` are not alternate build owners or distribution paths. Real Apple authority and representative target-Mac confirmation remain required for a public stable release; absence of that evidence is BLOCKED, not PASS.

## GRP-6 — first public release

Publish only after tag ↔ exact stable commit ↔ manifest ↔ checksums ↔ qualified DMG agree. The Release page must have curated notes and a signed/notarized primary DMG. Add README download links only after publication; keep source-build instructions. Move completed workstream truth to canonical owners.

## Parallel ownership with PRS-18

PRS-18 owns product/runtime evidence: WKWebView/TCC capture, local MLX/resource/thermal, PRS-9 benchmark and PRS-16 contention. This workstream owns version/release/publication mechanics. GRP consumes successful exact-candidate evidence; it never redefines a failing product observation as passing.

## Validation

Version/build/workflow changes are FULL because they touch release/build/CI identity. Apple signing/notarization is REAL_ENVIRONMENT / protected authority. GitHub publication mechanics are REMOTE_AUTOMATED.

## Resume checkpoint

- GRP-1..3 remain integrated; GRP-4/5 now use only local Mac build/staging and explicit draft upload rather than retired GitHub-hosted release workflows;
- real GRP-5 success remains blocked by local Apple Developer signing/notarization authority; source/contract tests are not distribution qualification;
- historical `v0.1.0` exists; no GitHub Release exists; next product line is `0.2.0` / `v0.2.0`;
- stable-source work is independent: complete PRS-18 exact-candidate target-Mac evidence, then promote `dev -> main` before any `v0.2.0` distribution run.
