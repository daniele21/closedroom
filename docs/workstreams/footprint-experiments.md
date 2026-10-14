# Footprint experiments — Git assets and packaged-app inventory

Status: **E1 IMAGES OPTIMIZED / VIDEO HELD FOR HDR / E2 READ-ONLY BUNDLE AUDITOR VALIDATED; REAL MAC MEASUREMENT PENDING**. Isolated branch `experiment/complexity-ablation` only. Do not merge into `dev`, alter PyInstaller exclusions, or remove media without new evidence.

## Goal and boundaries

Quantify the difference between (1) uncompressed content tracked in Git, (2) the current macOS `.app` file footprint, and (3) runtime CPU/RSS, which **this experiment does not measure**. Maintain local-first/privacy and preserve README images, demo links, current build/signing identities, model quality and app capabilities. PRODUCT_NONE / ITERATION / LEAN-SCOPED for the audit code; dependency/bundle changes would require FULL packaged validation; representative Mac evidence remains REAL_ENVIRONMENT.

## E1 — immutable Git inventory (measured)

Using GitHub's recursive tree for source commit `c62c2fcbaf8303ffc23ef1e9665029120612108f`:
- **506 Git-tracked blobs; 155,433,465 bytes** (~148.2 MiB) of **uncompressed blob content**, not `.git` history/clone size.
- `docs/assets/`: **16 files, 142,933,753 bytes** (~136.3 MiB; **92.0%**).
- `docs/assets/Closed-Room-demo.mov`: **60,206,568 bytes** (~57.4 MiB). Several linked README PNG screenshots are ~7–11 MiB each.
- `frontend/public/logo-{dark,light}.png` and `src/local_asr_server/static/logo-{dark,light}.png` have the same Git blob id (726,614 bytes per copy). Duplication ≠ removable asset: four URL paths may be consumed by separate dev/package entrypoints.
- Committed `src/local_asr_server/static/` is **2,496,242 bytes** of build/UI assets. Whether it can be generated only at packaging time depends on source installation/offline and WKWebView contracts.

**E1.1 executed — pixel-identical reference images.** On isolated [PR #124](https://github.com/daniele21/closedroom/pull/124), `scripts/optimize_reference_media.py` converted all **15 documentation PNGs** to lossless WebP: **82,727,185 → 28,323,780 bytes**, saving **54,403,405 bytes (65.76%; ~51.9 MiB)** on media payloads alone. Pillow decoded both versions and checked exact RGBA bytes, dimensions and preserved ICC metadata before any write. `README.md` and `design/ux-contract.json` references were rewritten. No stale README image path remains; all 15 WebPs exist, no PNG remains in `docs/assets/`.

[Source-only run 38531940499](https://github.com/daniele21/closedroom/actions/runs/38531940499) **PASS**: three synthetic tests, pixel-exact conversion, reference guard, 15 image transformations and push. Earlier one-off attempts **38531547001/38531752703** failed for test-discovery and an over-restrictive changed-file guard respectively, then were diagnosed/corrected; they were **not** product regressions. No macOS app was built or media artifact uploaded. PR #124 merged **into experiment only**, not `dev`; one-shot workflow removed.

After changes, experiment tree `d69aee89b46448b535c664ff24f52ce007dd4353`: **511 tracked blobs, 101,054,403 bytes** (~96.4 MiB), of which `docs/assets/` is **88,530,348 bytes** (~84.4 MiB). The total-tree net change relative to pre-audit commit `c62c2fc` is **−54,379,062 bytes**, differing from media-only saving because new scripts/tests/docs were added. No Git history rewrite, no bundle-size or download-size claim. Original demo video remains **60,206,568 bytes**, byte-identical.

**E1.2 — demo video codec audit: DO_NOT_BUILD without HDR evidence (2026-10-14).** FFprobe of the original public `docs/assets/Closed-Room-demo.mov` reports HEVC / `yuv420p10le`, 2990×1582, **40.918333 s**, average `17370/307` fps, **60,206,568 bytes**. The full metadata also indicates an HDR transfer function; our fidelity guard correctly rejected conversion before encoding. Re-encoding to 8-bit SDR would change the color boundary, and generic SSIM alone cannot certify HDR/color metadata or UI text quality. This is a **negative experiment, not a compression PASS**. Source blob `14094632acbed9b6cc819617e6ba60721ba0e89c` remains unchanged.

One-off [PR #125](https://github.com/daniele21/closedroom/pull/125) targeted experiment only and was **closed unmerged**; temporary video script/tests/workflow removed from the experiment branch. Last [run 38539599858](https://github.com/daniele21/closedroom/actions/runs/38539599858): **2 synthetic tests PASS**, video trial intentionally **BLOCKED** on HDR preservation. Earlier runs had runner ffmpeg absence, stale disposable validation head, and a fixture assertion mismatch; these were gate/environment issues, not product regressions. No .app build, uploaded artifact, video file replacement or change to `dev`.

Revisit only with a dedicated HDR-preserving HEVC Main10 trial that explicitly proves `color_primaries`, `color_transfer`, `color_space`, mastering/side data metadata as applicable, timing, exact audio and readable small text using representative visual playback. Without this, **KEEP the video as-is**.

## E2 — finalized .app and optional PyInstaller COLLECT-TOC attribution (synthetic PASS; real Mac pending)

`ClosedRoom.spec` already excludes `torch`, `cv2`, `datasets`, `pyarrow`, `pandas`, `multiprocess`; packaging still collects local MLX and opt-in provider components. In `selective-efficiency.md`, SE-3 ONNX/VAD quality is BLOCKED, and SE-6 PyTorch frozen proof is ACTIVE. **Do not claim savings** from speculative dependency removal.

The canonical read-only auditor `scripts/audit_footprint.py` can resolve the **latest successful finalized local artifact** using `dist/artifacts/*/*/build-manifest.json`; no guessed path to `/Applications`, no build and no change to the finalized artifact:

```bash
mkdir -p dist/evidence/footprint
python3 scripts/audit_footprint.py repository > dist/evidence/footprint/git-tree.json
python3 scripts/audit_footprint.py bundle --latest-finalized --root . > dist/evidence/footprint/finalized-app.json
# If measuring an installed app rather than a locally finalized artifact:
python3 scripts/audit_footprint.py bundle --app /Applications/ClosedRoom.app > dist/evidence/footprint/installed-app.json
# Optional: ONLY if this TOC was produced by the relevant local PyInstaller build.
python3 scripts/audit_footprint.py bundle --latest-finalized --root . \
  --pyinstaller-toc build/ClosedRoom/COLLECT-00.toc \
  > dist/evidence/footprint/collect-breakdown.json
# For a later comparable build:
python3 scripts/audit_footprint.py bundle --latest-finalized --compare dist/evidence/footprint/finalized-app.json
```

Report fields include: full logical file-byte totals, `Contents` groups, complete `component_groups`, 25 largest file/directory groups, non-overlapping physical `file_roles`, opaque archive bytes and top individual files. Adjacent finalized manifest is checked against app filename, file count (including symlinks), and total logical bytes. Only then are source revision, build ID, version, channel, signing and optional DMG byte count reported. **This is size/count identity, not a cryptographic manifest checksum check.** When no manifest is adjacent, identity is `absent` rather than inferred. `--compare` emits deltas by section/role/component.

**Optional TOC evidence:** `--pyinstaller-toc` parses a literal `COLLECT-00.toc` (max 32 MiB) using Python's safe literal parser, never evaluating it. It maps only unambiguous relative destination paths to actual bundle files. It aggregates counted bytes by destination-directory prefix and PyInstaller entry type (`DATA`, `BINARY`, `EXTENSION`, `ZIPFILE`); missing, duplicate, or multi-root matches remain unattributed. Absolute original source paths in the TOC are **never emitted or accessed**. A TOC can be stale or belong to a different build: **the audit does not verify TOC-to-bundle revision**, and destination directory prefixes are not authoritative Python package names. Pure Python modules in EXE/PYZ remain opaque; no dependency is safe to remove based on this alone.

Privacy: data outside the selected `.app` and the repository Git tree is not scanned; no meeting data, arbitrary absolute local paths, binary content, model weights or private user recordings appear in the JSON report. File paths within the bundle are reported because they are necessary for attribution.

**Limitations:** logical file sizes excluding symlink targets, not disk allocation, compressed DMG, RAM/CPU or startup. Directory groups are physical location only, **not complete Python distribution sizes**. PyInstaller executable/PYZ/ZIP internals can hide modules; don't infer that unlisted dependencies are absent. Changes to `ClosedRoom.spec` or runtime dependencies remain BLOCKED pending FULL packaged-app/import/Qwen/MLX tests and applicable REAL_ENVIRONMENT checks. No representative `.app` was available to measure here.

## Evidence and decisions

`scripts/audit_footprint.py` and `test/test_audit_footprint.py`: **10 synthetic standard-library tests PASS** in source-only [38543632241](https://github.com/daniele21/closedroom/actions/runs/38543632241) (previous 6-case baseline: [38542371392](https://github.com/daniele21/closedroom/actions/runs/38542371392)) (syntax/py_compile PASS too). Covers immutable Git inventory, symlink-safe bundle sizes, physical component/archive accounting, privacy of unrelated paths, latest finalized selection, manifest mismatch, comparison deltas and manifest path traversal. Temporary PRs #126 and #127 closed **unmerged**, both one-shot workflows deleted. Earlier image compression tests PASS in [38531940499](https://github.com/daniele21/closedroom/actions/runs/38531940499). New cases prove unambiguous TOC physical matching, ambiguity rejection, traversal/literal safety and private-source-path non-disclosure. **Not** a real packaged-app/TOC measurement or target-Mac evidence. No app build or media artifacts uploaded, no production/dependency/build-spec changes.

**HOLD dependency removal until real bundle report.** Next E2 decision is based on measured largest physical components, matched/unmatched COLLECT destinations and explicitly unattributed PyInstaller archives, then source-owned dependency evidence and FULL package/import/MLX/Qwen smoke. Video stays unchanged pending HDR-grade evidence. Maintain `dev` unchanged.
