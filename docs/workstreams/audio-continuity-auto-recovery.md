# Audio Continuity & Auto-Recovery (ACR)

Status: ACTIVE — implementation draft PR #176; P0 recording reliability. Created 2026-11-03.
Base: dev 5767e5d985868a0d85b5df6b7de36bcd980af892 (refresh before implementation). Target: small convergent PRs to dev; dev -> main RELEASE.

## Product outcome and risk

**User/job:** recording a meeting must continue if Bluetooth headphones disconnect, USB microphone vanishes, default input switches or an individual audio stream is interrupted.
**Outcome:** same recording_id, same increasing capture clock, continued saving from every remaining permitted source, auto-recovery of the affected source without pressing REC. Preserve any captured speech and expose lost intervals truthfully.
**Default UX:** native macOS auto-recovery with nonblocking, accessible per-source status; explicit recovery action if no source remains.
**Non-goals:** synthesizing missing speech, literally gapless Bluetooth switches, new capture engine/session, cloud/network fallback, automatic output routing changes, changes to ASR/diarization, reboot-persistent live recording. Browser device-switch parity is out of scope; browser system-audio capture is not supported.
**Risks:** VALUE recording trust; USABILITY clear REC/degraded status; FEASIBILITY CoreAudio/AVCaptureSession/SCK, device changes, audio formats and PTS; VIABILITY bounded battery/CPU/disk use in long meetings.
**Quality:** privacy-first and local by default; no raw content/device IDs in ordinary telemetry; no overwrite of finalized or in-progress audio, no fabricated silence/gaps.
**Axes:** PRODUCT_FEATURE; DELIVERY ITERATION -> INTEGRATION (dev) -> RELEASE (main); VALIDATION LEAN planning, STRONG expected implementation (selector wins), FULL release; EXECUTION AGENT_LOCAL for deterministic, REMOTE_AUTOMATED for unavailable automatable gates, REAL_ENVIRONMENT for physical devices/TCC.

## Confirmed regression and canonical owners

Verified on dev at planning:
- src/local_asr_server/native_capture_helper/native_capture_helper.swift: MicrophoneCapture chooses AVCaptureDevice.default once; AVCaptureSessionRuntimeError invokes onFatalError -> NativeCaptureRun.stopAndExit. System SCK recovers only some interruptions.
- src/local_asr_server/native_capture.py: generic error sets session.stopped; start rejects existing audio; stop mixes mic.wav/system.wav and writes timeline.json.
- src/local_asr_server/routers/system.py: capture SSE closes on any error.
- src/local_asr_server/recordings.py: mark_capture_event maps error to recording-wide capture_status=error.
- frontend/src/hooks/useRecorder.ts: many native errors trigger cancel/reset; useAudioDevices.ts devicechange only refreshes browser enumeration.

**Owners:** Swift helper for physical capture; NativeCaptureManager for one child process and event interpretation; RecordingStore for recording artifacts/timeline/recovery; routers for API/SSE; useRecorder/recorderLifecycle for UI state; HeavyWorkloadArbiter for resource admission. No second recording store, scheduler or supervisor.
**Preserve:** one capture lease/ready epoch, mic/system dual tracks and canonical mic.wav/system.wav/recording.wav consumers, existing file reservations, immutable finalized artifacts, legacy checkpoint recovery, screenshot flow, explicit browser microphone-only fallback, auth/TCC and graceful Stop/Cancel.

## ACR-0 — Diagnose and freeze contract [SERIAL; ACTIVE]

1. Reproduce BT unplug, USB removal, default-input switch, SCK error and Stop during recovery. Record source-safe events, output sizes and missing intervals, not meeting audio in CI.
2. Inspect SampleBufferWavSink, PTS/format behavior, capture exit, existing recovery, transcription/mix consumers and PR overlap before picking segment strategy.
3. Select native default-device policy: follow macOS default; on disappearance use authorized available fallback with visible notice; debounce return to avoid oscillation. Explicitly pinned device behavior, if supported later, needs separate policy.
4. Freeze nonterminal source_interrupted/source_recovering/source_recovered/source_unavailable versus terminal capture_fatal/stopped. Define source/reason, event ordering, original ready-uptime offsets, idempotence, source-health states; mute or low dB does not imply device loss.
5. Freeze safe segment/manifest schema, normalized sample-rate/PTS, gaps and canonical export compatibility. No incompatible PCM appended to an open WAV, no overwrite and no silent audio fabrication.
6. Establish failing focused tests, measurable baseline timings, acceptable numeric targets and rollback/feature narrowing. If segment integrity cannot be proven, stage segmented persistence before auto-switch.

Exit: explicit, testable contract and actual failure evidence; physical feasibility still requires real Mac. NARROW_SCOPE rather than ship unsafe recovery.

## Dependency graph and parallel delivery

ACR-0 (serial contract) -> parallel ACR-1/2/3/4 -> ACR-5 convergence -> ACR-6 real Mac/rollout.

| Lane | State | Exclusive write boundary | Observable result |
| --- | --- | --- | --- |
| ACR-1 / A | ACTIVE | native_capture_helper/*.swift and Swift probes | Device events, independent source recovery and safe audio segment writer; no helper restart. |
| ACR-2 / B | ACTIVE | native_capture.py, routers/system.py, recordings.py and Python tests | Nonfatal event propagation, persistent timeline/segments, composition and recovery. Coordinate RecordingStore with AC-4 workstream. |
| ACR-3 / C | ACTIVE | frontend/src/hooks/useRecorder.ts, recorder UI/overlay, i18n/tests | Same REC/clock, honest source health and accessible auto-recovery notice. Coordinate AC-1/AC-2. |
| ACR-4 / D | ACTIVE | new fixtures and harness scripts only | Deterministic device-change storm, source failure, gap/format/clock fixtures and privacy-safe probes. |
| ACR-5 / integrator | ACTIVE | integrated contract + affected docs/E2E | One end-to-end native path; separate browser parity backlog item. |
| ACR-6 / target Mac | BLOCKED | real-machine evidence | Exact-candidate peripheral/TCC proof and rollout decision. |

Worktrees/branches must not write the same file. Freeze JSON event/segment contract first and converge early; no conflicting long-lived stacks.

**ACR-1 native:** observe input/default connectivity and AVCaptureSession interruptions; corroborate device status with actual samples, not audio silence. Reconfigure mic on a serialized queue, generation-guard callbacks, debounce changes, retry with bounded backoff, stop retrying after Stop/Cancel. Preserve system audio if mic fails and mic if SCK fails. Keep visual/screenshot capture alive. Rotate segments for PTS/rate/channel changes; do not append incompatible WAV data. Sink/disk failures terminate safely and keep recoverable bytes.

**ACR-2 backend/store:** source events cannot set CaptureSession.stopped, RecordingStore error, close SSE, cancel UI or release arbiter lease. Only true terminal events or helper exit may do so. Persist ordered local event/gap/segment metadata idempotently; source-safe diagnostics only. On Stop compose independently recoverable segments into aligned, playable canonical tracks/mix and keep old readers/ASR timestamps correct; make partial finalization recoverable atomically. Helper crash without terminal event becomes interrupted/recoverable, never stale REC; Stop/Cancel drains retries and releases exactly once. Permission revocation never triggers unauthorized fallback.

**ACR-3 UX:** show healthy recording, reconnecting source, recording with reduced audio and no-audio states. Keep meeting elapsed time; make meters reflect real samples. One deduplicated nonmodal switch/recovery notice across main UI/overlay/menu-bar, no focus theft. Expose source gaps in saved meeting diagnostics without rewriting transcript text or speaker labels. Browser MediaStreamTrack.ended/devicechange, per-source graph/MediaRecorder rebuilding and upload sequencing are follow-up, not v1 native acceptance.

## ACR-4 — Deterministic falsification matrix

Extend test/test_native_capture.py, test/test_recording_api.py, RecordingStore/frontend recorder tests and affected browser E2E. Assert session status AND playable artifact for:
1. Normal both/mic_only/pc_only and legacy recovery, stop, cancel, existing API/ASR readers.
2. Mic loss midmeeting: system samples continue; mic comes back; one ID/clock and explicit gap. Mirror for SCK loss.
3. A -> B -> A, reconnect storm, duplicate events and Stop during retry: no flapping, stale writes, listener leaks or infinite retries.
4. Zero live sources: no false healthy REC; earlier audio preserved; restore or explicit Stop succeeds.
5. Format/PTS/rate changes, delayed/duplicated events: non-overlapping aligned segments, playable mix, correct ASR/diarization offsets.
6. Disk full, TCC denied, helper crash, SSE disconnect, backend restart, partial finalize and duplicate stop/cancel: recoverable files, no overwrite/lease leak.
7. Screenshot/visual capture and heavy-AI priority unaffected; browser fallback remains microphone-only, explicitly chosen.

Mock evidence proves contracts, never physical Bluetooth/CoreAudio or TCC reliability.

## ACR-5/6 — Integration, hardware and release

- Refresh exact head/base; review complete diff and downstream ASR cache, diarization, mix, transcript timeline, audio export and screenshots. Keep browser parity a separately qualified change; never silently switch native to browser midmeeting.
- Run scripts/select_validation_profile.py for the diff/stage. ITERATION: focused tests. INTEGRATION: selected repo gates, authenticated API + affected automated E2E, FULL_MEDIA for material UI; packaged-app smoke if selected. Use central daniele21/local-runner-infra local-ci/mac only when required; dispatch alone is not PASS. Actions do not build/upload packaged apps.
- REAL_ENVIRONMENT on exact installed macOS candidate with TCC: AirPods disconnect/reconnect/low battery, USB unplug, built-in input fallback, default input switch, Teams/Zoom with system audio, no input, sleep/wake, Stop during recovery. Listen to separate/mixed WAV, verify actual gaps, clock/ASR alignment and resumed mic samples.
- Measure detection/recovery p50/p95, gap lengths, duplicate/missing samples, retry counts, 60-minute CPU/RSS, Stop latency. Numeric thresholds chosen from measured ACR-0 baseline, not promises. Store only redacted event codes/counts/timings; never publish private audio.
- Update docs/features.md and impacted architecture, design/ux-contract.json, privacy/recovery and docs/current-state.md only when corresponding behavior ships. RELEASE requires FULL and applicable real-device proof at exact candidate; ad-hoc proof does not establish signed/notarized distribution.
- Rollback option: disable auto-device migration while keeping honest degraded status, stored audio and recovery; no hiding losses. Completion requires implementation, contracts, evidence and durable docs aligned; then transfer truth and delete workstream.

## Resume checkpoint

Draft PR #176: ACR-1..5 code and fixtures staged; ACR-0 physical evidence, automated gates and release proof PENDING.
Source dev at planning: 5767e5d985868a0d85b5df6b7de36bcd980af892; refresh dev/head/tree/base/related PRs at resume.
Confirmed: native mic runtime error ends capture; generic error terminates manager/SSE; UI cancellation; limited SCK retry.
Unknown: actual sink/manifest feasibility, physical device event fidelity, latency/gap and browser parity.
Next: resolve exact-head CI, compile Swift on Mac runner and reproduce BT unplug with system capture; validate segmented timing and recovery against physical audio.
STRONG automated integration and REAL_ENVIRONMENT evidence: PENDING.
