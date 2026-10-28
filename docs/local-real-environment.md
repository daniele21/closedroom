# LOCAL REAL_ENVIRONMENT runbook

Use this path when ClosedRoom must be exercised on a representative Apple-Silicon Mac but Apple Developer Program distribution authority is unavailable.

This evidence is real target-environment evidence for packaged WKWebView, TCC-backed audio, local MLX, resource behavior, PRS-16 contention and the PRS-9 audio-strategy benchmark. It does **not** establish Developer ID distribution signing, notarization, stapling, distribution Gatekeeper acceptance or final release readiness.

## Preconditions

Use the exact current `dev` candidate and keep the checkout clean:

```bash
git checkout dev
git pull --ff-only
git status --short
```

`git status --short` must print nothing.

Required local tools:

```bash
uv --version
pnpm --version
ffmpeg -version
```

The test requires an Apple-Silicon Mac. During the first run macOS may request permissions for ClosedRoom and for the dedicated `closedroom-ax-helper` Accessibility client. Grant the requested permissions for:

- Microphone;
- Screen & System Audio Recording / system-audio capture;
- Accessibility for `closedroom-ax-helper` when requested by the UI automation path.

The Accessibility helper is compiled into a stable source-versioned path under `.cache/closedroom/macos-ax-helper/`. `AXIsProcessTrusted` applies to that helper process itself, not generically to Terminal. The helper requests the standard macOS Accessibility prompt; if the run is blocked, enable `closedroom-ax-helper` in System Settings > Privacy & Security > Accessibility and run the same command again. The stable cache path allows that grant to be reused across reruns of the same helper source.

If macOS asks you to quit/reopen an app after granting a permission, do so and run the same command again. The suite prefers reusing the exact finalized local app for that commit so TCC identity remains stable across reruns.

## Run

From the repository root:

```bash
python3 scripts/run_local_real_environment_suite.py
```

To test the **existing definitive app** at `/Applications/ClosedRoom.app` without installing or changing it, run from an **interactive Terminal**:

```bash
python3 scripts/run_local_real_environment_suite.py --use-installed-app
```

If `/Applications/ClosedRoom.app` is **not present**, you can explicitly build/install a definitive copy signed with your stable local signing certificate, and pause for permissions, in one command:

```bash
# Select your existing stable Code Signing certificate:
security find-identity -v -p codesigning
export CLOSEDROOM_SIGN_IDENTITY="ClosedRoom Local Development"
python3 scripts/run_local_real_environment_suite.py --install-main-app
```

Replace the example certificate name with the actual identity shown by `security`. This mode builds a **new exact-HEAD local artifact** with the chosen identified signature and creates `/Applications/ClosedRoom.app` **only when that path does not exist**. It never deletes, upgrades, renames, re-signs or silently overwrites an already installed main app. It validates the source/installed file fingerprints and code signature before testing. If an older `ClosedRoom.app` exists, this mode fails closed unless it is byte-identical to a finalized artifact of the current Git HEAD. Use the standard `--use-installed-app` flag for subsequent runs without rebuilding. An identified local signature is not distribution notarization.

The read-only `--use-installed-app` mode requires an installed `com.closedroom.app` that is byte-for-byte identical to a clean finalized build of the **current checkout** under `dist/artifacts` (ad-hoc or locally identified signing). It checks the codesign signature and source identity before running. If the installed app is older or differs, the run refuses to start, never overwrites `/Applications/ClosedRoom.app`, and reports the mismatch; it cannot qualify a different commit by pretending it is the current one. Before starting physical tests it **pauses indefinitely until you press Enter**: open the installed app to grant Microphone and Screen & System Audio Recording; allow the terminal application Screen & System Audio Recording for `screencapture`; grant the dedicated AX helper Accessibility; then quit the app completely and press Enter. The suite rechecks integrity after this checkpoint and launches the verified installed binary with an isolated temporary HOME. It never runs permission prompts or record tests against your personal meeting database. A new build/identity may still require granting permissions again. Identified local signing does **not** establish Developer ID notarization/release authority.

To run the physical checks from a separate test app located in **/Applications** instead of the build tree, opt in:

```bash
python3 scripts/run_local_real_environment_suite.py --install-to-applications
```

This copies (does not move or mutate) the exact finalized ad-hoc artifact into a separate `/Applications/ClosedRoom Test-<source>-<build>.app` and runs both tests from that verified installation. `/Applications/ClosedRoom.app` is never replaced. An existing exact matching test copy is reused; a different build gets a different name. The installed copy is fingerprint-checked against the original manifest, and code-sign verification is required. No automatic `sudo`, fallback directory, removal of other apps, or changes to bundle identifiers/signatures. You may need user-authorized write access to `/Applications`; on access failure the suite reports FAIL without altering another app. After installing, approve **Screen & System Audio Recording** and **Microphone** for the exact test app if macOS prompts; changing the app build may require new TCC grants. The original immutable artifact and report remain under `dist/`. This does not qualify a public release.

No Apple Developer ID, notary profile or signing environment variables are required. The local build path explicitly removes `CLOSEDROOM_SIGN_IDENTITY` and produces a finalized ad-hoc artifact.

The macOS app bundle uses **Python 3.12** by default (distinct from the package's broader supported Python range), ensuring SciPy >=1.16 is used. This avoids a known SciPy 1.15.3 `_spropack` Mach-O import failure on macOS 27. The build checks actual SciPy/MLX Whisper imports *before* PyInstaller and fails closed if the native libraries cannot load. Do not patch or re-sign third-party wheels to bypass dyld errors. To diagnose a build failure, capture `bash scripts/build_artifact.sh --no-dmg` stdout/stderr locally; the aggregate suite only records the nonzero exit status.

A direct `./build.sh` or `bash scripts/build_artifact.sh --no-dmg` run restores tracked Vite output after packaging, including on ordinary build errors. A preexisting dirty `src/local_asr_server/static/` is rejected *before* Vite runs, to avoid overwriting work. If an earlier build left generated assets dirty, inspect them before explicitly restoring the tracked static files and cleaning untracked generated assets within that directory only. The REAL_ENVIRONMENT suite still requires the **whole checkout** clean.

Use `--rebuild` only when you intentionally want a fresh local artifact:

```bash
python3 scripts/run_local_real_environment_suite.py --rebuild
```

## What is automated

The local suite executes the same physical evidence owners used by the release workflow:

1. measured target-Mac evidence:
   - packaged WKWebView/window/accessibility/focus/keyboard journey;
   - native TCC `both` capture;
   - persisted non-empty microphone and system-audio tracks;
   - clean packaged-app lifecycle;
   - real local MLX transcription completion;
   - `HeavyWorkloadArbiter` activity;
   - CPU/RSS/runtime scheduler observations;
   - `pmset -g therm` thermal observation;
   - PRS-9 dual-track vs mixed-track benchmark.
2. PRS-16 AI-busy contention evidence:
   - managed local AI active before recording starts;
   - visible `Preparing recording` while AI owns the safe boundary;
   - no premature physical capture;
   - waiting -> recording FULL_MEDIA transition;
   - native microphone + system-audio persistence after the safe boundary.

The Accessibility driver treats the helper signal `closedroom_window_missing` as a bounded transient condition because WKWebView/window transitions can briefly expose no AX window. It retries only that exact condition within the existing action timeout; permission failures, action failures, invalid bounds and other UI automation errors remain terminal.

If that bounded retry is exhausted, the helper collects a privacy-safe diagnostic snapshot before failing. The snapshot compares raw AX window availability with WindowServer process-window counts plus running/active/hidden state. Only numeric/boolean process-window metadata is whitelisted into the aggregate: no window titles, UI labels, meeting text or transcript content is collected. This distinguishes an AX exposure gap from a genuinely hidden/closed window or missing process without weakening the failing gate.

## Result

A successful run ends with:

```text
LOCAL REAL_ENVIRONMENT: PASS
distribution authority............. BLOCKED (Apple Developer membership)
release qualification.............. NOT ESTABLISHED
```

The command returns exit code `0` when the local physical evidence passes. Distribution authority remains a separately classified blocker and therefore does not turn valid local evidence into a false test failure.

The aggregate JSON is written under:

```text
dist/evidence/local-real-environment/<source-revision>/local-real-environment-suite.json
```

The same directory contains the two detailed child reports and bounded media evidence. Each functional UI child owns independent `ui-media/<ui-report-stem>/meeting-recording-ui/` screenshots, video and manifest: measured-release and contention seeds must never reuse each other's media, and the media collector must never fall back to a different ClosedRoom executable when the exact app is known. The aggregate reports allowlisted `ui_smoke_status` and `ui_media_status` separately, so a macOS TCC permission blocker is not confused with incomplete screenshots. Neither status changes the required PASS criteria. The aggregate never copies arbitrary child error payloads, transcript or meeting text. For an exhausted `closedroom_window_missing` failure only, it may include the explicitly whitelisted non-content `ui_failure_diagnostic` process/window fields described above.

When a physical check fails the command returns non-zero and prints the failed check names. Rerun with `--keep-sandbox` only when diagnosing a failure.

## What remains blocked without Apple Developer membership

Even after `LOCAL REAL_ENVIRONMENT: PASS`, stable release qualification still lacks:

- Developer ID Application distribution signing;
- secure timestamp evidence;
- app/DMG notarization;
- stapling;
- distribution Gatekeeper assessment;
- any materially required subjective VoiceOver/usability observation.

Do not relabel LOCAL REAL_ENVIRONMENT evidence as full release evidence.
