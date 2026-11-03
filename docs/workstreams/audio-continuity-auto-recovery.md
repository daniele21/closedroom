# Audio Continuity & Auto-Recovery (ACR)

Status: ACTIVE — PLAN ONLY; no implementation or validation claims.
Priority: P0 recording reliability. Created: 2026-11-03.
Base: dev at 5767e5d985868a0d85b5df6b7de36bcd980af892 (refresh before execution).
Target: small, convergent PRs into dev; dev -> main remains RELEASE.

## Product decision and measurable outcome

**User / job:** a person recording a meeting must not lose the remainder of the conversation when Bluetooth headphones disconnect, a USB mic is unplugged, the system default input changes, or the operating system briefly interrupts one capture source.

**Outcome:** one meeting identity, one increasing recording clock, and continuing capture from every still-available authorized source. The missing source reconnects to an eligible input automatically without a second REC, while any genuinely lost interval is visible in the saved recording and transcript timeline.

**Default UX:** automatic recovery for native macOS capture, with a nonblocking indication of changed/degraded input and an accessible recovery action. Never represent silence or an unavailable source as successfully captured speech.

**Non-goals:** recovering speech never received by any device, making Bluetooth handovers literally gapless, starting a second meeting or helper, silent cloud/network fallback, taking over macOS output routing, changing ASR/diarization quality, or resuming a terminated process across a Mac reboot. Browser/BlackHole capture parity is an explicit later deliverable rather than assumed native correctness.

**Axes:** PRODUCT_FEATURE (reliability/UX); DELIVERY ITERATION by lane -> INTEGRATION via PR to dev -> RELEASE on dev -> main; VALIDATION LEAN for this plan, STRONG for implementation (escalate if selector requires), FULL for release; EXECUTION AGENT_LOCAL for deterministic checks, REMOTE_AUTOMATED for unavailable macOS/build/E2E gates, REAL_ENVIRONMENT for real peripherals/TCC and interactive WKWebView.

**Risk framing:**
- VALUE: users trust REC; success means a single usable meeting after an unexpected disconnect, not merely a green indicator.
- USABILITY: recovery must be automatic, noticeable without interrupting the call, and explain audio gaps plainly.
- FEASIBILITY: device notifications may not imply actual usable samples; CoreAudio/AVCaptureSession reconfiguration, PTS discontinuity, and ScreenCaptureKit output changes require Mac evidence.
- VIABILITY: bounded listeners, retries, I/O, disk overhead and low CPU/battery impact on long meetings.
- Quality constraints: local-only, no content/device identity in ordinary telemetry, original audio retained, atomic filesystem operations, no hallucinated timestamps or guarantees of zero audio loss.

## Observed baseline and canonical owners

Verified on dev at plan creation:
- src/local_asr_server/native_capture_helper/native_capture_helper.swift: MicrophoneCapture opens AVCaptureDevice.default(for: .audio) once; AVCaptureSessionRuntimeError emits error and invokes onFatalError; NativeCaptureRun routes microphone fatal to stopAndExit(cancelled: true).
- Same Swift helper already retries some ScreenCaptureKit stream interruptions, but system-capture failures may leave the source unavailable without recovery; do not conflate audio-system recovery with microphone recovery.
- src/local_asr_server/native_capture.py: _read_events marks generic error as stopped; start rejects existing capture outputs; _terminate merges mic.wav/system.wav, writes timeline.json and validates tracks.
- src/local_asr_server/routers/system.py: /capture/events stops streaming on any error; /capture/stop owns normal finalization and arbiter release.
- src/local_asr_server/recordings.py: RecordingStore.mark_capture_event treats error as capture-wide terminal and persists timeline/metadata.
- frontend/src/hooks/useRecorder.ts: native error generally calls cancelNativeCapture and resets the recorder; an SSE transport error is handled differently depending on startup status.
- frontend/src/hooks/useAudioDevices.ts only refreshes enumerated devices on browser devicechange; it does not recover a running native capture.

**Owners/boundaries:** Swift native helper owns device/sample lifecycle; NativeCaptureManager owns its one subprocess and event interpretation; RecordingStore owns persisted recording/timeline/artifacts; routers adapt authenticated API/SSE; useRecorder/recorderLifecycle own app recording orchestration and the UI projects per-source health; HeavyWorkloadArbiter alone owns recording priority. Do not introduce a parallel session store, scheduler, helper supervisor, or copy of recording state.

**Compatibility invariants:** keep recording_id, capture lease, original ready epoch and stop/cancel semantics; preserve mic/system dual-track identity, canonical mic.wav/system.wav/recording.wav readers, finalized-artifact immutability, capture output reservation and recovery checks; avoid rewriting existing captured bytes or auto-finalizing because one source disappeared. The browser fallback and menu-bar/overlay must keep working.

## ACR-0 — Diagnose, choose contract, establish regression baseline [SERIAL; READY]

1. Reproduce disconnected mic, default-input change, and system-only capture failure in the current native app; capture privacy-safe helper events plus recording status and artifact sizes. Keep physical proof separate from deterministic mocks.
2. Inspect the existing SampleBufferWavSink implementation, timestamp/PTS normalization, native process exit paths, source/device notification capabilities, metadata recovery, dual-track mix and transcription consumers before choosing a file format. Verify closest scoped guides and active PR conflicts again on resume.
3. Freeze source policies: v1 follows the macOS default input when native capture is using its default; on unexpected disappearance, choose a usable authorized default/alternate without prompting; do not automatically switch back and forth on noisy reconnection. Explicit user-selected routing, if supported in a future native flow, must not be silently discarded; document a deterministic fallback priority.
4. Freeze error taxonomy: source_interrupted/source_recovering/source_recovered/source_unavailable (nonterminal) versus capture_fatal (storage, unrepairable process/resource integrity) and stopped (terminal). Terminal before ready is distinct from degraded after ready. Define stable reason codes, source identity, event ordinal and monotonic offsets; do not put raw mic labels, meeting content or device IDs in ordinary logs.
5. Define one monotonic recording epoch; segment intervals, verified samples, gaps and resampling rules. Pick whether segment composition is required for P0 after inspecting sink/consumer contracts; no WAV truncation, overwrite or fabricated audio.
6. Record the initial implementation decision, performance budget, roll-back strategy and deterministic failing tests in this plan before lane writes. If recovery cannot be made safe with the current sink, narrow to segmented writing before enabling auto-switch.

**Acceptance:** an unambiguous contract and reproducible failing regression for each core failure mode; no claim of device feasibility from synthetic tests alone.

## Parallel work after ACR-0 contract freeze

| ID / lane | State | Exclusive write area | Deliverable / proof |
| --- | --- | --- | --- |
| ACR-1 / A — native source continuity | READY | native_capture_helper/*.swift only; own Swift test/probe files | Device/disconnect/default notifications plus bounded per-source recovery, serialized stop/reconfigure, no duplicate delegates/outputs and no capture-wide exit for recoverable loss. Source samples resume under same run. |
| ACR-2 / B — backend and recording durability | READY | native_capture.py, routers/system.py, recordings.py and their Python tests (coordinate RecordingStore with AC-4 workstream) | Per-source event contract through manager/SSE/store; terminal-only stream closure; persistent segment/gap timeline and safe finalization/recovery preserving old consumers. |
| ACR-3 / C — in-meeting UX | READY | frontend/src/hooks/useRecorder.ts, recorderLifecycle integration, recording/overlay components, i18n and frontend tests (coordinate AC-1/AC-2 workstream) | REC remains session-level; per-source health shown in-app/overlay; automatic transition notification, no focus theft/modal; accessible states and truthful signal meters. |
| ACR-4 / D — contract and fixture evidence | READY | new deterministic test fixtures / harness scripts only; no writes to A/B/C owners | Two-source fake helper, event races, timed fixture gaps, no-content diagnostics and browser critical-journey assertions reusable at integration. |

Parallel lanes must not edit the same file. New Swift sink support belongs to lane A and new Python artifact projection belongs to lane B; reconcile their segment manifest schema in ACR-0. Land cohesive results early; do not stack long-lived PRs or merge incompatible partial contracts.

### ACR-1 — Native capture behavior (lane A)

- Observe changes to the default input, connection/disconnection and AVCaptureSession interruptions/runtime failures. Treat transient silence/mute as audio, not automatically as unplugged hardware; corroborate device state with missing samples only when appropriate.
- Keep the system stream and its writing independent of microphone rebuild. Reopen input on a controlled serial queue; debounce device churn, cancel stale attempts by generation, exponential bounded backoff while source is absent, and never retry after Stop.
- Continue the system track if mic fails; continue mic if system fails. System ScreenCaptureKit restart attempts must not dispose of the microphone or duplicate output callbacks. Preserve visual capture/one-shot screenshots.
- Keep track/sample epoch anchored to first ready. If input format changes (channels/rate/clock), rotate a segment and make canonical output conversion explicit; do not append incompatible PCM to an open WAV header.
- Fatal sink/disk I/O errors stop safely, preserve recoverable bytes, and emit one terminal signal. Source recovery never starts a second native helper process.

### ACR-2 — Backend, persistence and timeline (lane B)

- Model source health orthogonally to overall recording lifecycle; a recoverable source event must neither set CaptureSession.stopped nor cause SSE to end, RecordingStore.capture_status=error, immediate cancel, or HeavyWorkloadArbiter lease release.
- Persist bounded ordered events/segments with source, monotonic start/end offsets, gap reason and sequence; keep only source-safe metadata in telemetry. Repeated/out-of-order events must be idempotent or rejected by the owner, not duplicate audio.
- Keep existing canonical track outputs and transcription/audio-path consumers working. Compose available segments with verified timeline alignment on Stop; maintain independently recoverable originals for crash/partial finalization, with atomic manifest/status updates.
- Preserve previously finalized files. A real helper exit without a terminal event must synthesize an explicit interrupted state and offer existing recovery, not leave an infinite live REC.
- Stop/cancel during recovery must be bounded, join workers, reject callbacks after closure, finalize available audio and release the capture reservation exactly once. Permission revocation and unrecoverable storage failure must never silently retry through an unauthorized source.

### ACR-3 — UI, browser boundary and user truth (lane C)

- Display Recording (all requested sources healthy), Recording with reduced audio (one source missing), Reconnecting input, and Audio unavailable (no captured source). Do not present a healthy mic meter without samples.
- Surface one lightweight, deduplicated status change with source type and optional safe local device label; overlay, main UI and menu bar reconcile from the same recording status. No interruptive confirmation for default recovery, but retain an explicit change-input / settings recovery path.
- Mark timeline gaps and source changes in meeting review/quality diagnostics, without modifying transcript text or speaker labels. Keep elapsed time continuous and distinguish missing audio from diarization silence.
- Keep browser fallback unchanged until ACR-5; explicit later browser parity must watch MediaStreamTrack.ended/devicechange, rebuild only the affected source/MediaRecorder graph and retain existing chunk sequence/backpressure guarantees. Never describe browser parity as shipped with native-only validation.

### ACR-4 — Falsification and automated acceptance (lane D + integration owner)

Deterministic scenarios (assert both session status and playable final artifact):
1. Normal both/mic_only/pc_only recordings remain byte-/duration-compatible with existing consumers.
2. AirPods disconnect after recording ready: mic source enters recovery, system track continues, one recording_id/clock, new input samples resume, gap explicitly marked.
3. Reconnect storms, default route A -> B -> A, duplicate notifications and Stop during restart: no concurrent session, no stale callback writes, no leaked listeners or infinite retry.
4. No input available: one source degraded with visible status; if both disappear, no false healthy REC; reconnect restores source; explicit Stop preserves what was acquired.
5. ScreenCaptureKit interruption and mic interruption together: independently bounded recovery; no duplicate sample intervals; fallback only among local, permitted devices.
6. Source format or sample rate change and late/out-of-order events: playable aligned mic/system/mix; honest missing intervals; stable ASR timestamps/diarization alignment.
7. Sink/disk failure, permission denied, helper crash/exits without event, SSE disconnect/reconnect, backend restart, duplicate Stop/cancel: no silent data loss, no accidental overwrite, recoverable artifacts preserved.
8. Legacy session recovery and already-finalized immutable outputs remain unchanged.

Reuse/extend test/test_native_capture.py, test/test_recording_api.py, recording-store and frontend recorder tests; add focused continuity fixtures/tests and affected browser UI journey. Avoid mocks that silently assume macOS device behavior.

## ACR-5 — Single-owner convergence and browser follow-up [BLOCKED on ACR-1..4]

- Integrate native capture/SSE/persistence/UI at one exact contract revision and check real downstream consumers (ASR cache keys, transcription merge offsets, diarization and quality reports, screenshots, archive/playback).
- Choose browser parity as a separate scoped work item after native native-app acceptance; prove equivalent session/clock/track behavior before enabling it by default. No automatic native-to-browser fallback while a meeting is recording.
- Update durable owners only for actually shipped behavior: docs/features.md (audio capture registry), docs/architecture.md (event/segment ownership if changed), design/ux-contract.json or UI owner if material, docs/current-state.md, and privacy/recovery documentation where applicable. Transfer facts and delete this workstream when complete.

## Validation and rollout gates

- ITERATION: run local focused Python/Swift/frontend tests per owning lane; choose gates via scripts/select_validation_profile.py, never downgrade the resolved profile.
- INTEGRATION (STRONG expected, selector authoritative): refreshed exact head/base and full diff; required repository checks, exact-head local-ci/mac PASS from central runner dispatch when selected, affected authenticated API and browser E2E, UI FULL_MEDIA for material UX, packaged-app smoke if selected. No GitHub Actions app-build artifacts.
- REAL_ENVIRONMENT: install the exact candidate on representative Apple Silicon macOS with TCC permissions; test Bluetooth headphones (disconnect/reconnect/low battery), USB mic unplug, built-in mic fallback, system default change during Teams/Zoom, both-source loss, sleep/wake and Stop during recovery. Listen to mic/system/mix, inspect waveform/gaps, compare actual wall-clock/timeline offsets and transcript timestamps. Collect redacted event codes, timings, audio lengths and gap counts only; never publish meeting audio.
- Proposed metrics to measure, not currently proven SLOs: detection latency, recovery latency p50/p95, gap duration by source, missed/duplicated samples, event retry count, 60-minute CPU/RAM impact, capture failures and Stop latency. Select acceptable numeric thresholds from baseline measurements in ACR-0, not arbitrary promises.
- RELEASE (FULL): exact candidate/base, all mandated automated gates plus applicable real peripheral/TCC/product proof. Target-Mac evidence is blocking for stable promotion; CI, simulations or an ad-hoc build never prove public notarization/distribution.
- Rollout: prefer narrow native-only enablement after all native proofs. If a regression is found, disable automatic device migration while retaining durable data and honest source-loss warnings; do not revert artifact recovery guarantees or mask loss. Roll back only before affected work is irreversibly persisted.

## Resume checkpoint (single authoritative checkpoint)

- Phase: PLAN ONLY / ACR-0 READY. No code changed; no test or physical evidence collected for this feature.
- Source at planning: dev 5767e5d985868a0d85b5df6b7de36bcd980af892. Refresh dev head, workstream branch head/tree, base, related PRs and tests at resume; prior evidence is not exact-head validation.
- Confirmed: mic error -> native stopAndExit; generic error -> manager stopped/SSE closed/recording error; frontend cancellation for native mic error. Native system reconnection exists only for a subset of ScreenCaptureKit failures.
- Not established: physical failure taxonomy, sink continuity/recovery format, default-input change notification reliability, reconnection latency, device-selection UX on native or browser parity.
- Next discriminating action: inspect actual SampleBufferWavSink/timeline and reproduce one Bluetooth disconnect using packaged native app while the system track remains active; freeze ACR-0 event/segment contract before parallel implementation.
- Deferred proof: STRONG integration automated gates and representative REAL_ENVIRONMENT are PENDING, never PASS by plan publication alone.
