# REAL_ENVIRONMENT release runbook

Use this runbook only for the frozen ClosedRoom `dev -> main` release candidate on a representative Apple-Silicon Mac. Hosted CI is not a substitute for TCC, physical audio, packaged WKWebView or representative MLX evidence.

## 1. Preconditions

- Check out the exact candidate commit and keep the checkout clean.
- Install repository prerequisites (`uv`, `pnpm`, `ffmpeg`, Xcode command-line tools).
- Configure a valid **Developer ID Application** identity in `CLOSEDROOM_SIGN_IDENTITY`.
- Configure a `notarytool` keychain profile in `CLOSEDROOM_NOTARY_KEYCHAIN_PROFILE`.
- Allow the packaged ClosedRoom app the microphone, system-audio/screen-recording and accessibility permissions requested by macOS during the run.

The runner never enables cloud fallback. Production evidence must remain local and bound to the exact artifact revision.

## 2. Build the immutable production artifact

```bash
python3 scripts/build_production_artifact.py
```

The command fails closed unless the app and DMG are Developer-ID signed, securely timestamped, notarized, stapled and accepted by Gatekeeper. Its final stdout contains the exact `app` path to use below.

Example shape:

```json
{
  "status": "pass",
  "artifact_dir": "...",
  "app": ".../ClosedRoom-<version>-<build-id>-<revision>.app",
  "dmg": ".../ClosedRoom-<version>-<build-id>-<revision>.dmg"
}
```

## 3. Run all automated target-Mac evidence

```bash
python3 scripts/run_real_environment_release_suite.py \
  --app "<exact-production-app>"
```

The suite executes the existing evidence owners against that same app:

1. `measured_release_target_mac.py`
   - packaged WKWebView/window/accessibility/focus/keyboard journey;
   - native TCC `both` capture with non-empty microphone + system tracks;
   - clean lifecycle;
   - real local MLX transcription completion and `HeavyWorkloadArbiter` activity;
   - bounded CPU/RSS/runtime scheduler observations and `pmset -g therm` evidence;
   - PRS-9 `dual_track_vs_mixed_asr` benchmark on the representative recording.
2. `record_while_ai_busy_target_mac.py`
   - managed local MLX active before Start;
   - truthful `Preparing recording` state while MLX still owns the safe boundary;
   - no premature capture;
   - FULL_MEDIA waiting -> recording transition;
   - native `both` mic/system persistence after the safe boundary.

Default aggregate report:

```text
dist/evidence/measured-release/<source-revision>/real-environment-suite.json
```

Child reports and media stay under the same revision-scoped evidence directory.

## 4. Interpret the result

Successful automated evidence prints a summary ending with:

```text
AUTOMATED REAL_ENVIRONMENT: PASS
```

A failure returns a non-zero exit code and the aggregate JSON lists the failed child runner/check names and bounded errors. It does not copy transcript or meeting text into the aggregate.

A PASS proves only the automated REAL_ENVIRONMENT portion for that exact source/artifact identity. Before stable promotion, still record any materially required subjective VoiceOver/usability observation and recheck candidate/base freshness plus the full `dev -> main` diff.

## 5. Useful options

Use `--output <path>` to choose the aggregate JSON path and `--keep-sandbox` only when diagnosing a failed run. Timing and benchmark repeat options are exposed by `--help`; release defaults should normally remain unchanged so evidence stays comparable.
