# Recording durability — active implementation plan

Status: ACTIVE — retention and native checkpoints integrated in dev; remaining recovery/release work open.

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

- Native capture now keeps the long-running WAV plus independently finalized,
  synced one-second WAV/checksum pairs. See `../features/recording-durability.md`
  for the protocol, recovery bounds and remaining qualification gaps.
- Before PR #173, fatal native completion deleted sink WAVs.
  Frontend error handling also called `capture/cancel`, which discarded the whole
  session. Both automatic deletion paths are removed in dev through PR #173.
- Browser chunk ingestion already flushes and fsyncs the audio before metadata;
  a crash between audio and metadata needs reconciliation before an upload retry
  can append the same chunk twice.
- Native initialization no longer deletes its destination; Python output guards,
  exclusive persistent Swift run claims and API state checks block reuse. Empty
  finish is non-destructive. Recovery refuses an actually live helper, including
  after an error event has marked the session stopped.
- Existing restart discovery depends on readable `metadata.json`; a damaged
  metadata/catalog entry must not make surviving audio undiscoverable.

## Work and acceptance criteria

| ID | Observable outcome | State | Required evidence |
| --- | --- | --- | --- |
| RD-1 | Error/cancel retains native audio, visual evidence and recovery metadata | DONE | PR #173 merged in dev as `ceb8f82`. Exact-head Mac/source/browser gates and clean packaged build/smoke/retention probe PASS. Actual device failure and installed-app proof remain release obligations. |
| RD-2 | Native capture has periodic durable recovery data independent of final WAV closure | DONE | PR #174: synced WAV/checksum pairs, bounded producer, verified sample counts and synthetic native/frozen-API recovery PASS. Physical/long-session qualification belongs to RD-9. |
| RD-3 | Duplicate start, stop and retry cannot truncate or delete original audio | DONE | Source/native subprocess/API tests PASS for concurrent exclusive claims, preserved prior bytes, empty finish and saved-session start rejection.  Exclusive destination creation, run identity, idempotent stop/cancel, repeated start with stale/failed process, concurrent stop and late error; byte-for-byte preservation. |
| RD-4 | Crash/restart reconstructs the committed recording without trusting a final WAV header or SQLite alone | ACTIVE | File-backed checkpoint recovery implemented and tested; missing metadata, legacy native track discovery and cancellation remain open.  `RecordingStore` discovers checkpoints/orphan audio, repairs or rebuilds into a new temporary derivative, validates it and atomically publishes it; original data stays intact on every failure. Recovery must be bounded, cancellable and safe to repeat. |
| RD-5 | Browser retries after a crash neither duplicate nor silently omit audio | READY | Inject crashes between append/fsync, metadata replace and catalog update; reconcile acknowledged offsets/checksums before retry. Preserve the original tail as evidence if reconciliation is ambiguous. |
| RD-6 | Device loss affects only the unavailable source and is visible immediately | READY | Existing healthy source continues where supported; keep the failed source's prefix and record the gap. Reconnection/new source uses a new segment. No silent device substitution or new permission grant. Hardware verification required. |
| RD-7 | User sees saved duration, interruption/gaps and recovered recording | READY | Recovery cannot depend solely on a localStorage ID. Scan/reconcile at restart, list incomplete sessions, expose playable recovered audio, retained error and an explicit retry/export action. Use existing Meeting/recording UI owners. |
| RD-8 | Storage exhaustion and downstream processing cannot destroy acquired audio | ACTIVE | Writer/checkpoint errors preserve earlier commits; low-space preflight and broader downstream fault matrix remain open.  Low-space preflight and ongoing write-failure handling; no success without durable acknowledgement, no automatic deletion of recovery data, finalization/mixing/ASR/catalog failures leave originals available. |
| RD-9 | Updated installed app meets the durability contract under injected failures | ACTIVE | PR #174 INTEGRATION/STRONG and canonical build/smoke/assembled recovery PASS. Stable-signed main app installed; actual audio/disconnect, long dual-source/storage pressure and power-loss confirmation remain required. |

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

Native checkpoint integration and local main-app upgrade completed; refresh live source on resume:

- Installed/started `/Applications/ClosedRoom.app`, final display name `ClosedRoom`,
  from clean identified build `local-20261102T151925Z-5708fd` (`b17780b3a250`).
  Same `ClosedRoom Local Development` authority as prior app; canonical upgrade
  kept the previous bundle as backup and verified exact installed bytes/signature.
  Live UI/API online, mic authorized and screen capture granted. No real recording
  performed: these checks do not prove physical audio continuity or power-loss safety.
  Local backup/install/live evidence: `.cache/installation/closedroom/20261102/`.

- PR [#174](https://github.com/daniele21/closedroom/pull/174) merged in dev as
  `5767e5d985868a0d85b5df6b7de36bcd980af892`. Tested head `b17780b3a250`,
  base `ceb8f82`; dev merge tree equals tested tree
  `d47f7ca19cb169854d279de6c0c44b0ec1cb7526`.
- Exact-head `local-ci/mac` PASS: 843 Python tests, frontend lint/typecheck,
  browser FULL_MEDIA. Central run `41467979111`; preflight `41467889105`.
  Focused native/API/persistence suite: 100 tests PASS. Guards/docs/context PASS.
- Clean canonical build `local-20261102T150347Z-75b84c` and packaged smoke PASS.
  An actual synthetic Swift writer was killed with SIGKILL; the frozen packaged
  API recovered 32,000 exact PCM samples (2 seconds) after restart, retained the
  original WAV/checkpoints, denied session reuse and survived another restart.
  This proves synthetic producer/API/storage, not bundled physical capture/TCC.
- Immutable app delivered under `dist/artifacts/macos-arm64-local-app/` and indexed
  by `dist/last-build.json` at integration; copied bytes/signature verified. The
  index now points to the stable-signed main-app build noted above.
  Evidence: `.cache/integration-evidence/native-checkpoints/b17780b/`.
- GCS branch merged dev as `4e85fc9`; overlapping source/docs copies resolved to
  canonical dev. All 17 native integration paths match dev. This is not blanket
  integration readiness for the combined GCS branch.
- Earlier iteration full GCS+native suite: 933 PASS, 6 optional SDK/model skips.
  `1264e21` fixes a GCS test's `/var` versus `/private/var` expected path, no
  cloud behavior change. Synthetic benchmark remains informational in
  `.cache/recording-durability/20261102/checkpoint-benchmark.json`.
- Next: RD-4 orphan/legacy metadata and cancellation, RD-5 browser append crash
  reconciliation, RD-6 device recovery, RD-7 durable progress/recovery UX and
  RD-8 low-space preflight. Actual device/long-session/storage-pressure and
  power-loss confirmation remain RD-9 release obligations.

Prior RD-1 evidence remains in [PR #173](https://github.com/daniele21/closedroom/pull/173)
(merged `ceb8f82`; exact-head Mac/source/browser and packaged retention checks PASS)
and `.cache/integration-evidence/recording-retention/b41390f/`.

- Incident: session `74b5b151-7789-4930-b5fe-87c870e91fb4`, started 12:02;
  exact helper PID 44981 reports input `Device 115 died` at 12:40:33, then exits.
  Session directory and catalog entry absent; no audio copies found in inspected
  ClosedRoom folders, no local Time Machine snapshots or matching open unlinked
  files found. Original application error/request is not retained, so the exact
  runtime deletion sequence is inferred, not proven from an access log.
- `/Applications/ClosedRoom.app` now includes the checkpoint implementation. Physical
  device failure/reconnection, disk-full and hard-crash guarantees remain unproven.
- RD-1 installed-app/device evidence remains separate from the new synthetic
  checkpoint tests. No new INTEGRATION or RELEASE readiness is claimed.

Before completion transfer implemented behavior to the canonical feature and
architecture documentation and target-Mac obligations to current-state/release
owners, then remove this active plan following `finalize-workstream`.
