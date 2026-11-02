# Native recording durability

## Scope and ownership

`RecordingStore` owns session metadata, recovery and catalog projection.
`NativeCaptureManager` owns helper lifecycle. Swift `SampleBufferWavSink` writes
the normal WAV plus independent recovery segments; `AudioRecoverySegments`
publishes checkpoints. `recording_audio_recovery.py` validates those checkpoints
and builds a separate derivative through the existing store/recover API.

This implementation is under iteration on the storage branch, not a qualified
installed-app release. Physical microphone/TCC, long-session performance and
storage exhaustion still require target-Mac evidence.

## Start and retention contract

- Native capture accepts only a recording session in `recording` state.
- Python refuses existing WAVs, nonempty `.part` files, prior run markers,
  recovery directories and symlinks before probing/starting the helper.
- The helper independently creates `.native-capture-run` with exclusive creation,
  persists it and checks existing outputs. Concurrent helpers cannot claim the
  same session. The marker remains after failures/stops; retries must recover or
  explicitly discard the old session, then create a new recording.
- Sink initialization and empty finalization never truncate an existing file.
  Capture error/cancel retains audio and visual evidence. Explicit session
  discard/delete remains the deletion owner.

## Checkpoints

Each native source has `.audio-recovery/<mic|system>/` containing numbered WAVs
and JSON manifests. Source presentation timestamps select nominal one-second
segments. Each WAV uses the same 16 kHz mono PCM output as the main writer.

A checkpoint is acknowledged only after finalizing the segment, syncing its
audio, publishing it without overwrite, syncing the directory, writing/syncing
the versioned checksum manifest, publishing that manifest without overwrite and
syncing the directory again. Manifests record source, sequence, size, SHA-256 and
source time range; no transcript or remote data is involved. Publication is
ordered even if individual writers finish out of order. Incomplete staging and
audio lacking a commit manifest remain on disk as evidence.

Pending sample storage is bounded to 8 MiB per sink, with at most four segment
finalizations in flight. Publication waiting is bounded to five seconds. Storage
or checkpoint failure stops capture visibly and retains the previous committed
prefix; it is never reported as a successful new checkpoint.

One second is a segmentation target, not a universal maximum loss window:
callback backlog, writer finalization, sync latency and device availability can
extend time since the last durable checkpoint. The normal full WAV is retained
too. Checkpoints add roughly another copy of each mic/system audio track plus
manifests; there is no automatic checkpoint eviction or disk-space quota yet.

## Recovery

For native sessions, startup classification recognizes checkpoint manifests even
without a final WAV. Stop/recover uses a normally closed WAV when it covers the verified checkpoint
sample count;
otherwise it reconstructs a contiguous verified checkpoint prefix into a new,
content-addressed `<source>.recovered-<digest>.wav` and updates the existing track
through `RecordingStore`. A recovered meeting is marked partial. If a mixed
track is absent, an available system/mic track becomes primary; both originals
remain on disk and independently accessible to their existing consumers.

Recovery validates bounded regular files, denies symlinks/path substitution,
checks manifest identities, checksums, PCM format, sample length and timing, and
refuses corrupt/missing intervals. It reads at most 4 MiB per checkpoint, caps a
source at one day/86,400 checkpoints and writes incrementally. The producer
refuses checkpoints beyond those same size/day bounds instead of acknowledging
unrecoverable data. Exclusive output
publication and identical-content verification make retries idempotent.
Original WAVs/checkpoints are never overwritten or deleted by reconstruction.
Failures retain them, including when sync or metadata/catalog updates fail.
An active native process must be stopped before API recovery is allowed.

## Evidence and remaining boundaries

`test_recording_audio_recovery.py` includes actual Swift/AVAssetWriter subprocess
tests with synthetic PCM: exclusive concurrent start, empty finish over existing
audio, SIGKILL during capture, exact recovered samples, normal finish, float
48 kHz input and checkpoint write-permission failure. Store tests cover restart,
repeated recovery, corrupt/truncated/gapped/symlink checkpoints and fsync failure.
API/native tests cover saved-session start rejection and live-helper recovery
rejection. These prove synthetic persistence, not physical-device continuity.

Still open: metadata/catalog orphan discovery, device reconnect/gap UX, durable
progress in Meeting, browser append/metadata crash reconciliation, low-space
preflight, representative long dual-source capture and packaged target-Mac fault
journeys. No guarantee covers samples never delivered by a disconnected device,
uncommitted buffers, or physical storage failure.
