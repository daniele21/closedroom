# Recording durability — active implementation plan

Status: ACTIVE — retention fix integrated in dev; crash-durability work READY.

## Observable outcome and contract

An acquisition, device, helper, API, WebView, post-processing or catalog error must
never delete or overwrite audio already committed to storage. The original audio
survives failed stop/finalization, cancellation caused by an error, restart and
repeated recovery attempts. Only a separate, explicit user deletion may remove it.

This is a software retention guarantee for committed data. It cannot guarantee
audio that a disconnected microphone never delivered, unwritten buffers at power
loss, or survival of physical storage failure. The UI must distinguish recording
time, last durable audio checkpoint and any missing interval. Never advertise an
unmeasured zero-loss guarantee.

## Owners and invariants

- Native sample persistence: `native_capture_helper/`; process lifecycle:
  `native_capture.py`; canonical session/recovery/catalog: `RecordingStore`.
- Existing API and frontend recorder consume those owners; no parallel catalog,
  independent cleanup policy or implicit cloud backup.
- Mic and system tracks remain independent originals. Mixing, resampling and
  transcription produce replaceable derivatives, never destructive rewrites.
- Run-owned devices/processes/resources remain bounded and cleaned up; retaining
  captured audio is separate from keeping a capture process alive.
- Persist technical error classifications and timing, not meeting content in logs.

## Findings confirmed in source

- Native capture uses one `AVAssetWriter` WAV per source and finishes it on stop;
  it has no independent periodic recovery journal or durable checkpoint protocol.
- Before PR #173, fatal native completion deleted sink WAVs.
  Frontend error handling also called `capture/cancel`, which discarded the whole
  session. Both automatic deletion paths are removed in dev through PR #173.
- Browser chunk ingestion already flushes and fsyncs the audio before metadata;
  a crash between audio and metadata needs reconciliation before an upload retry
  can append the same chunk twice.
- Native sink construction removes its destination before starting. A duplicate
  or retried start must never reach that destructive initialization for existing
  audio. Restart must create a new run/segment, not truncate an original.
- Existing restart discovery depends on readable `metadata.json`; a damaged
  metadata/catalog entry must not make surviving audio undiscoverable.

## Work and acceptance criteria

| ID | Observable outcome | State | Required evidence |
| --- | --- | --- | --- |
| RD-1 | Error/cancel retains native audio, visual evidence and recovery metadata | DONE | PR #173 merged in dev as `ceb8f82`. Exact-head Mac/source/browser gates and clean packaged build/smoke/retention probe PASS. Actual device failure and installed-app proof remain release obligations. |
| RD-2 | Native capture has periodic durable recovery data independent of final WAV closure | READY | Select and implement an append-only PCM journal with reconstructible framing, or independent finalized segments. Durability means write + fsync + atomic checkpoint publication, including directory sync where applicable. Benchmark a proposed one-second checkpoint target; measure the actual unsaved window and I/O cost. Reject disk-write failure visibly and keep all earlier checkpoints. |
| RD-3 | Duplicate start, stop and retry cannot truncate or delete original audio | READY | Exclusive destination creation, run identity, idempotent stop/cancel, repeated start with stale/failed process, concurrent stop and late error; byte-for-byte preservation. |
| RD-4 | Crash/restart reconstructs the committed recording without trusting a final WAV header or SQLite alone | READY | `RecordingStore` discovers checkpoints/orphan audio, repairs or rebuilds into a new temporary derivative, validates it and atomically publishes it; original data stays intact on every failure. Recovery must be bounded, cancellable and safe to repeat. |
| RD-5 | Browser retries after a crash neither duplicate nor silently omit audio | READY | Inject crashes between append/fsync, metadata replace and catalog update; reconcile acknowledged offsets/checksums before retry. Preserve the original tail as evidence if reconciliation is ambiguous. |
| RD-6 | Device loss affects only the unavailable source and is visible immediately | READY | Existing healthy source continues where supported; keep the failed source's prefix and record the gap. Reconnection/new source uses a new segment. No silent device substitution or new permission grant. Hardware verification required. |
| RD-7 | User sees saved duration, interruption/gaps and recovered recording | READY | Recovery cannot depend solely on a localStorage ID. Scan/reconcile at restart, list incomplete sessions, expose playable recovered audio, retained error and an explicit retry/export action. Use existing Meeting/recording UI owners. |
| RD-8 | Storage exhaustion and downstream processing cannot destroy acquired audio | READY | Low-space preflight and ongoing write-failure handling; no success without durable acknowledgement, no automatic deletion of recovery data, finalization/mixing/ASR/catalog failures leave originals available. |
| RD-9 | Updated installed app meets the durability contract under injected failures | READY | Coherent integration diff/docs/gates; build/finalize a new immutable artifact; exact artifact/head proof, FULL_MEDIA for affected material UI journeys and real target-Mac fault tests before release. |

Implementation order: RD-3, RD-2, RD-4/RD-5, RD-6/RD-7/RD-8, RD-9. Validate the
recording-storage protocol before extending UI claims. Do not ship the current
small deletion fix as proof that crash/power-loss durability is complete.

## Fault-injection matrix

- Kill the helper and API with SIGKILL during acquisition and each checkpoint
  commit boundary; restart, recover twice and compare known samples/duration.
- Fail write, flush, fsync, rename and catalog operations independently, including
  disk full/permission loss, malformed or missing metadata and incomplete journal
  tails. Never modify fixtures outside the test-owned temporary directory.
- Remove the input device, stop only one source, revoke a permission and close or
  reload the WebView while capturing. Keep healthy-source audio and expose gaps.
- Fail mixing, finalization, transcription and cancellation; duplicate start/stop
  requests and race late error events against successful stop/recovery.
- Verify retained originals and recovery checkpoints after every failure, not
  merely API status or existence of a nonempty output file. Check content,
  duration, continuity, deduplication and bounded cleanup/resource release.
- Representative TCC/physical audio and interactive macOS behavior need genuine
  target-Mac evidence; generated tones and fake capture managers prove only the
  deterministic persistence paths.

## Resume checkpoint — 2026-11-02

- GCS branch synchronized with remote `1d427b3` and dev via local merge `b3ffeae`.
  Refresh head/tree/live base before resuming; this checkpoint precedes its own
  documentation commit and is not exact-head proof for the combined GCS branch.
- RD-1: PR [#173](https://github.com/daniele21/closedroom/pull/173), source head
  `b41390f02974f23d512d841d0715b062c7678c7c`, base `e9a2a82`, merged in dev as
  `ceb8f820f59beaee2c2024a51a772d5b9e3ff19d`; merge tree equals tested source tree
  `af8852872ae7c840181f7f873dd39681868ec3e1`.
- INTEGRATION/STRONG: 83 focused tests; exact-head `local-ci/mac` PASS with 826
  Python tests, frontend lint/typecheck and browser FULL_MEDIA; repository/docs
  guards PASS. CI: `daniele21/local-runner-infra/actions/runs/41456530915` and
  `daniele21/closedroom/actions/runs/41456446268`.
- Clean canonical artifact `local-20261102T135006Z-5f0962` build/smoke PASS.
  Packaged authenticated API probe retained an identical synthetic 32,044-byte
  WAV through cancel, recovery, service restart and retry; no residual listener.
  This is synthetic API/storage evidence, not physical native-audio proof.
- Local JSON/test evidence: `.cache/integration-evidence/recording-retention/b41390f/`.
  Finalized artifact remains unchanged under the isolated checkout
  `/private/tmp/closedroom-recording-fix/dist/artifacts/`; temporary files may expire.
- Incident: session `74b5b151-7789-4930-b5fe-87c870e91fb4`, started 12:02;
  exact helper PID 44981 reports input `Device 115 died` at 12:40:33, then exits.
  Session directory and catalog entry absent; no audio copies found in inspected
  ClosedRoom folders, no local Time Machine snapshots or matching open unlinked
  files found. Original application error/request is not retained, so the exact
  runtime deletion sequence is inferred, not proven from an access log.
- Existing installed `/Applications/ClosedRoom.app` has NOT been updated. Physical
  device failure/reconnection, disk-full and hard-crash guarantees remain unproven.
- Next action: implement RD-3 with an exclusive-output regression; then choose the
  RD-2 storage protocol using an actual write/kill/recover experiment before
  changing the live recording path.

Before completion transfer implemented behavior to the canonical feature and
architecture documentation and target-Mac obligations to current-state/release
owners, then remove this active plan following `finalize-workstream`.
