# Footprint experiments — Git assets and packaged-app inventory

Status: **E1 IMAGES OPTIMIZED / VIDEO HELD FOR HDR / E2 REAL MAC PENDING**. Isolated branch `experiment/complexity-ablation` only. Do not merge into `dev`, alter PyInstaller exclusions, or remove media without new evidence.

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

## E2 — bundled dependency audit (not yet measured on a real app)

`ClosedRoom.spec` already excludes `torch`, `cv2`, `datasets`, `pyarrow`, `pandas`, `multiprocess`; packaging still collects local MLX and opt-in provider components. In `selective-efficiency.md`, SE-3 ONNX/VAD quality is BLOCKED, and SE-6 PyTorch frozen proof is ACTIVE. **Do not claim savings** from speculative dependency removal.

Run on the Mac from the exact checkout (no build in GitHub Actions):

```bash
mkdir -p dist/evidence/footprint
python3 scripts/audit_footprint.py repository > dist/evidence/footprint/git-tree.json
python3 scripts/audit_footprint.py bundle --app /Applications/ClosedRoom.app > dist/evidence/footprint/installed-app.json
```

For an exact locally finalized artifact, pass the `.app` path recorded in `dist/last-build.json` instead of assuming `/Applications` has the current revision. Reports contain only repo-relative or bundle-internal file paths and sizes, never audio/transcripts or full local file paths. Compare subsequent artifacts with `--compare <baseline-report.json>`.

**Measurement limitations:** logical file bytes, symlink targets skipped; excludes `.git` history, DMG compression, physical disk allocation, memory, CPU and start time. PyInstaller PYZ archives mask per-Python-package size, so a more granular module/TOC report is needed *before* excluding any additional dependency. No representative `.app` was available in this execution environment.

## Evidence and decisions

`scripts/audit_footprint.py` and `test/test_audit_footprint.py`: three synthetic standard-library `unittest` cases PASS locally, covering immutable HEAD vs dirty working tree, duplicated blob IDs, a fake `.app` with symlinks and incompatible baseline rejection. The separate image optimizer adds three pixel/link/threshold tests, PASS on run 38531940499. **Not** a bundled-app smoke, external package gate or real Mac test. The one-off docs-media job was run and removed; no production code, dependency or build metadata changed.

**HOLD E2 until real bundle report.** Candidate actions: E1 video fidelity/format experiment; E2 find oversized legitimate bundled packages, then choose narrowly-scoped exclusion with FULL package/import/MLX/Qwen smoke and target-Mac checks. Maintain `dev` unchanged.
