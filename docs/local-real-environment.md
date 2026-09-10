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

The test requires an Apple-Silicon Mac. During the first run macOS may request permissions for ClosedRoom and/or the terminal automation process. Grant the requested permissions for:

- Microphone;
- Screen & System Audio Recording / system-audio capture;
- Accessibility when requested by the UI automation path.

If macOS asks you to quit/reopen an app after granting a permission, do so and run the same command again. The suite prefers reusing the exact finalized local app for that commit so TCC identity remains stable across reruns.

## Run

From the repository root:

```bash
python3 scripts/run_local_real_environment_suite.py
```

No Apple Developer ID, notary profile or signing environment variables are required. The local build path explicitly removes `CLOSEDROOM_SIGN_IDENTITY` and produces a finalized ad-hoc artifact.

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

The same directory contains the two detailed child reports and bounded media evidence. The aggregate never copies arbitrary child error payloads, transcript or meeting text. For an exhausted `closedroom_window_missing` failure only, it may include the explicitly whitelisted non-content `ui_failure_diagnostic` process/window fields described above.

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