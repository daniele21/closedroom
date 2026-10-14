# Footprint experiments — Git assets and packaged-app inventory

Status: **E1 AUDITED / E2 MEASUREMENT READY, REAL MAC PENDING**. Isolated branch `experiment/complexity-ablation` only. Do not merge into `dev`, alter PyInstaller exclusions, or remove media without new evidence.

## Goal and boundaries

Quantify the difference between (1) uncompressed content tracked in Git, (2) the current macOS `.app` file footprint, and (3) runtime CPU/RSS, which **this experiment does not measure**. Maintain local-first/privacy and preserve README images, demo links, current build/signing identities, model quality and app capabilities. PRODUCT_NONE / ITERATION / LEAN-SCOPED for the audit code; dependency/bundle changes would require FULL packaged validation; representative Mac evidence remains REAL_ENVIRONMENT.

## E1 — immutable Git inventory (measured)

Using GitHub's recursive tree for source commit `c62c2fcbaf8303ffc23ef1e9665029120612108f`:
- **506 Git-tracked blobs; 155,433,465 bytes** (~148.2 MiB) of **uncompressed blob content**, not `.git` history/clone size.
- `docs/assets/`: **16 files, 142,933,753 bytes** (~136.3 MiB; **92.0%**).
- `docs/assets/Closed-Room-demo.mov`: **60,206,568 bytes** (~57.4 MiB). Several linked README PNG screenshots are ~7–11 MiB each.
- `frontend/public/logo-{dark,light}.png` and `src/local_asr_server/static/logo-{dark,light}.png` have the same Git blob id (726,614 bytes per copy). Duplication ≠ removable asset: four URL paths may be consumed by separate dev/package entrypoints.
- Committed `src/local_asr_server/static/` is **2,496,242 bytes** of build/UI assets. Whether it can be generated only at packaging time depends on source installation/offline and WKWebView contracts.

**Next safe optimization candidate:** locally trial optimized screenshots/video with preserved visual/text legibility and README paths, then compare exact Git snapshots and validate every documentation reference. Do not rewrite history, delete linked media or change image format solely for the byte count. No media was modified in this experiment.

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

`scripts/audit_footprint.py` and `test/test_audit_footprint.py`: three synthetic standard-library `unittest` cases PASS locally, covering immutable HEAD vs dirty working tree, duplicated blob IDs, a fake `.app` with symlinks and incompatible baseline rejection. **Not** a bundled-app smoke, external package gate or real Mac test. No GitHub Actions started, and no production code, dependency or build metadata changed.

**HOLD E2 until real bundle report.** Candidate actions: E1 optimize reference media with fidelity checks; E2 find oversized legitimate bundled packages, then choose narrowly-scoped exclusion with FULL package/import/MLX/Qwen smoke and target-Mac checks. Maintain `dev` unchanged.
