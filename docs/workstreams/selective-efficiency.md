# Selective efficiency hardening

Status: active
Owner: transcription / audio intelligence / packaging
Read when: deciding whether to remove heavyweight runtime dependencies or reduce repeated post-meeting I/O

## Goal

Make further ClosedRoom efficiency changes only when measured evidence shows a worthwhile benefit without reducing meeting quality or weakening the local-first boundary.

## Invariants

- Silero/ONNX is not removed solely to reduce bundle size.
- Representative audio quality evidence is separate from deterministic correctness.
- RecordingStore remains the canonical owner of finalized recording identity.
- No transcript text, audio bytes or local paths are retained in benchmark reports.
- Cache optimizations must invalidate when finalized audio identity changes.
- Existing ASR/VAD fallbacks and model-selection semantics remain unchanged until an evidence-backed decision explicitly changes them.

## Work graph

| ID | Outcome | State |
| --- | --- | --- |
| SE-1 | Reuse persisted finalized-track SHA-256 for repeated ASR cache lookup | ACTIVE |
| SE-2 | Privacy-safe Silero-vs-RMS timing/agreement benchmark | ACTIVE |
| SE-3 | Representative target-Mac VAD quality run and ONNX keep/remove decision | BLOCKED |
| SE-4 | Audit large VLM transitive packages against the real ClosedRoom visual path | READY |
| SE-5 | Add explicit ephemeral cache budget only if storage evidence shows unbounded growth | READY |

## Acceptance

SE-1: first lookup hashes the finalized track exactly as before; subsequent lookup reuses the persisted hash while size/mtime identity matches; mutation invalidates it; internal hash metadata is not projected through the public recording API.

SE-2: one command accepts local audio paths and emits only aggregate duration/bytes/timing/window/agreement metrics. It retains no filenames, paths, transcript or audio-derived content.

SE-3: do not remove ONNX Runtime until representative meetings show acceptable speech-boundary quality, not just synthetic agreement. Bundle-size benefit is material (~17 MB arm64 wheel before transitive effects) but quality dominates.

## Validation

SE-1 touches RecordingStore and transcription cache identity: STRONG.
SE-2 is deterministic tooling/tests. Representative benchmark execution is REAL_ENVIRONMENT evidence, not a hosted-CI substitute for production meeting quality.
