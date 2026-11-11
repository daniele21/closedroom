#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
// Run pure speaker identity invariants before browser integration.
import './test_speaker_presentation.mjs';

const ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf';
const MEETING_ID = 'e2e-meeting';
const ALTERNATE_MEETING_ID = 'e2e-meeting-other';
const VIDEO_FPS = 4;
const DIAGNOSTICS_DELAY_MS = 1400;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_BROWSER_E2E_EVIDENCE || path.join(root, 'dist/evidence/browser-meeting-ui'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';

const meetingFixture = {
  id: MEETING_ID,
  recording: {
    id: MEETING_ID,
    title: 'Quarterly launch review',
    project_name: 'Browser E2E',
    status: 'completed',
    mime_type: 'audio/wav',
    audio_file: 'synthetic.wav',
    bytes_written: 524288,
    created_at: '2026-09-05T10:00:00Z',
    stopped_at: '2026-09-05T10:10:00Z',
    duration_seconds: 600,
    audio_tracks: [
      { id: 'mixed', source: 'mixed', label: 'Mixed', bytes_written: 524288, primary: true },
      { id: 'system', source: 'system', label: 'System track', bytes_written: 262144, primary: false },
    ],
    warnings: ['sync_duration_warning'],
    quality_report: { sync: { duration_delta_ms: 135 } },
  },
  transcription: {
    id: 'e2e-transcription',
    timestamp: '2026-09-05T10:10:05Z',
    model: 'synthetic-fixture',
    language: 'en',
    audio_filename: 'synthetic.wav',
    recording_id: MEETING_ID,
    text: 'Decision: ship the release after validation. Owner: Alex.',
    segments: [{
      id: 0,
      start: 0,
      end: 3.5,
      text: 'Decision: ship the release after validation. Owner: Alex.',
      speaker_label: 'SPEAKER_00',
    }],
    stats: { outcome_status: 'completed' },
  },
  analysis_runs: [],
  latest_analysis: {},
  jobs: [],
  status: 'ready',
  project_name: 'Browser E2E',
  created_at: '2026-09-05T10:00:00Z',
  updated_at: '2026-09-05T10:10:05Z',
};

const alternateMeetingFixture = {
  ...meetingFixture,
  id: ALTERNATE_MEETING_ID,
  recording: {
    ...meetingFixture.recording,
    id: ALTERNATE_MEETING_ID,
    title: 'Alternate pricing review',
  },
  transcription: {
    ...meetingFixture.transcription,
    id: 'e2e-other-transcription',
    recording_id: ALTERNATE_MEETING_ID,
    text: 'Pricing review belongs only to the alternate meeting.',
    segments: [{
      ...meetingFixture.transcription.segments[0],
      text: 'Pricing review belongs only to the alternate meeting.',
    }],
  },
};

const screenshotFixture = {
  screenshot_id: 'synthetic-shared-key',
  recording_id: MEETING_ID,
  request_id: 'synthetic-shot-request',
  sequence: 0,
  capture_kind: 'manual',
  timestamp: 50,
  display_id: 1,
  display_title: 'Launch screenshot A',
  width: 1200,
  height: 720,
  sha256: 'synthetic',
  available: false,
  thumbnail_available: false,
  original_url: '/fixture/screenshot-original.jpg',
  thumbnail_url: '/fixture/screenshot-thumbnail.jpg',
};

const diagnosticsFixture = {
  recording_id: MEETING_ID,
  outcome_status: 'completed',
  jobs: [],
  events: [],
  artifacts: { audio: true, transcript: true },
  log_file: null,
  log_lines: [],
  diagnostics: [{
    component: 'ASR',
    status: 'completed',
    requested_backend: 'synthetic',
    actual_backend: 'synthetic',
    fallback_used: false,
  }],
};

const counts = {
  session: 0, health: 0, meeting: 0, alternate_meeting: 0, held_meeting: 0,
  diagnostics: 0, visual_frames: 0, screenshots: 0, alternate_screenshots: 0, notes: 0, alternate_notes: 0,
  audio_intelligence: 0,
  alternate_visual_context: 0,
  metadata_title: 0, metadata_project: 0, metadata_projects_list: 0,
  benchmark_list: 0, benchmark_start: 0, benchmark_poll: 0, benchmark_window: 0,
  review_list: 0, review_start: 0, review_poll: 0, review_preview: 0,
  review_apply: 0, review_undo: 0,
  speaker_sample_list: 0, speaker_timeline: 0, speaker_merge: 0, speaker_restore: 0, speaker_undo: 0,
  speaker_turn_reassign: 0, speaker_audio_request: 0,
};
let benchmarkJob = null;
let benchmarkRequest = null;
let communityReviewJob = null;
let communityReviewApplied = false;
let speakerReviewFingerprint = 'a'.repeat(64);
let speakerReviewBefore = null;
let speakerReviewUnmerged = null;
let speakerReviewUndo = null;
let lastBenchmarkWindowStart = null;
const benchmarkWindowStarts = [];
let failNextAlternateScreenshots = false;
let failNextAlternateNotes = false;
let failNextMetadataUpdate = false;
let holdNextMeetingId = null;
const heldMeetingResponses = [];
const checkpoints = [];
let frameIndex = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function launch(command, args, options) {
  const child = spawn(command, args, options);
  child.startError = null;
  child.on('error', (error) => { child.startError = error; });
  return child;
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function portReady(port) {
  return await new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('error', () => resolve(false));
    socket.setTimeout(500, () => { socket.destroy(); resolve(false); });
  });
}

async function waitPort(port, timeoutMs = 15000, child = null) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child?.startError) throw child.startError;
    if (child && child.exitCode !== null) {
      throw new Error(`process exited before port ${port} was ready: ${child.exitCode}`);
    }
    if (await portReady(port)) return;
    await sleep(100);
  }
  throw new Error(`port ${port} did not become ready`);
}

function json(res, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': body.length,
    'cache-control': 'no-store',
  });
  res.end(body);
}

function fixtureServer(port) {
  return http.createServer(async (req, res) => {
    const pathname = new URL(req.url, `http://127.0.0.1:${port}`).pathname;
    if (pathname === '/v1/session') {
      counts.session += 1;
      return json(res, 200, { ok: true });
    }
    if (pathname === '/health') {
      counts.health += 1;
      return json(res, 200, {
        ok: true,
        server: 'browser-fixture',
        backend: 'synthetic',
        default_model: 'synthetic/model',
        status: 'idle',
        endpoints: [],
        recordings: true,
      });
    }
    if ([MEETING_ID, ALTERNATE_MEETING_ID].some((id) => pathname === `/v1/meetings/${id}`)) {
      const requestedId = pathname.slice('/v1/meetings/'.length);
      if (requestedId === MEETING_ID) counts.meeting += 1;
      else counts.alternate_meeting += 1;
      if (holdNextMeetingId === requestedId) {
        holdNextMeetingId = null;
        counts.held_meeting += 1;
        const gate = await new Promise((resolve) => heldMeetingResponses.push(resolve));
        if (gate === 'error') return json(res, 503, { detail: 'stale_meeting_fetch_failed' });
      }
      return json(res, 200, requestedId === MEETING_ID ? meetingFixture : alternateMeetingFixture);
    }
    if (pathname === '/v1/projects') {
      counts.metadata_projects_list += 1;
      return json(res, 200, { items: [
        { name: 'Browser E2E', is_unassigned: false },
        { name: 'User Success', is_unassigned: false },
      ] });
    }
    if (pathname === `/v1/recordings/${MEETING_ID}` && req.method === 'PATCH') {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (failNextMetadataUpdate) {
        failNextMetadataUpdate = false;
        return json(res, 503, { detail: 'synthetic metadata outage' });
      }
      if (Object.prototype.hasOwnProperty.call(payload, 'title')) {
        counts.metadata_title += 1;
        meetingFixture.recording.title = payload.title;
      }
      if (Object.prototype.hasOwnProperty.call(payload, 'project_name')) {
        counts.metadata_project += 1;
        meetingFixture.recording.project_name = payload.project_name;
        meetingFixture.project_name = payload.project_name;
      }
      return json(res, 200, meetingFixture.recording);
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/intelligence`) {
      counts.audio_intelligence += 1;
      return json(res, 200, {
        version: 1, backend: 'synthetic', mode: 'shadow', mock: true,
        channels: {}, conversation_metrics: {
          speaking_time_pct: { mic: 48, system: 36 },
          speaking_time_seconds: { mic: 288, system: 216 },
          speech_rate_wpm: { mic: 118, system: 105 },
          long_pauses: [], overlaps: [], high_energy_moments: [],
        },
        insight_candidates: [],
      });
    }
    if (pathname === `/v1/meetings/${MEETING_ID}/diagnostics`) {
      counts.diagnostics += 1;
      if (counts.diagnostics === 1) {
        await sleep(DIAGNOSTICS_DELAY_MS);
        return json(res, 503, { detail: 'synthetic diagnostics outage' });
      }
      return json(res, 200, diagnosticsFixture);
    }
    if (pathname === `/v1/recordings/${ALTERNATE_MEETING_ID}/screenshots`) {
      counts.alternate_screenshots += 1;
      if (failNextAlternateScreenshots) {
        failNextAlternateScreenshots = false;
        return json(res, 503, { detail: 'synthetic screenshot failure' });
      }
      return json(res, 200, { items: [{
        ...screenshotFixture,
        recording_id: ALTERNATE_MEETING_ID,
        display_title: 'Pricing screenshot B',
      }], total: 1 });
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/screenshots`) {
      counts.screenshots += 1;
      return json(res, 200, { items: [screenshotFixture], total: 1 });
    }

    if (pathname === '/v1/transcriptions/e2e-transcription' && req.method === 'GET') {
      return json(res, 200, meetingFixture.transcription);
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/speaker-review' && req.method === 'GET') {
      return json(res, 200, {
        fingerprint: speakerReviewFingerprint,
        undo: speakerReviewUndo ? { revision_id: speakerReviewUndo } : null,
      });
    }
    if (pathname === '/v1/recordings/e2e-meeting' && req.method === 'GET') {
      return json(res, 200, meetingFixture.recording);
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/speaker-review/timeline' && req.method === 'GET') {
      counts.speaker_timeline += 1;
      const url = new URL(req.url, `http://127.0.0.1:${port}`);
      const start = Number(url.searchParams.get('start') || 0);
      const end = Number(url.searchParams.get('end') || 300);
      const all = [
        { cluster: 'system:S1', track_id: 'system', start: 0, end: 3.5,
          origin: 'diarization', overlap: false, playable: true },
        // Deliberately straddles the first one-minute zoom boundary.
        { cluster: 'system:S2', track_id: 'system', start: 55, end: 65,
          origin: 'diarization', overlap: false, playable: true },
        { cluster: 'system:S3', track_id: 'system', start: 1515, end: 1522,
          origin: 'diarization', overlap: true, playable: true },
      ];
      return json(res, 200, {
        recording_id: MEETING_ID, transcription_id: 'e2e-transcription',
        start, end, intervals: all.filter((row) => row.end > start && row.start < end),
        duration_seconds: meetingFixture.recording.duration_seconds,
        duration_source: 'recording',
        max_evidence_end_seconds: 1522,
        total_interval_count: all.length, overview_bucket_count: 120,
        overview: ['system:S1', 'system:S2', 'system:S3'].map((cluster) => {
          const rows = all.filter((row) => row.cluster === cluster);
          return {
            cluster, interval_count: rows.length, first_start: rows[0]?.start ?? null,
            playable_count: rows.length,
            bins: rows.flatMap((row) => {
              const first = Math.floor(row.start / 1800 * 120);
              const last = Math.floor((row.end - 0.00001) / 1800 * 120);
              return Array.from({ length: last - first + 1 }, (_, n) => first + n);
            }),
          };
        }),
        coverage: 'diarization',
        window_coverage: all.some((row) => row.end > start && row.start < end) ? 'diarization' : 'none',
        truncated: false, has_audio: true,
      });
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/speaker-review/samples' && req.method === 'GET') {
      counts.speaker_sample_list += 1;
      return json(res, 200, {
        recording_id: MEETING_ID, transcription_id: 'e2e-transcription',
        speakers: [
          { speaker_cluster: 'system:S1', samples: [
            { track_id: 'system', start: 0, end: 3.5, kind: 'transcript', overlap: false },
          ] },
          { speaker_cluster: 'system:S2', samples: [
            { track_id: 'system', start: 55, end: 65, kind: 'diarization', overlap: false },
          ] },
          { speaker_cluster: 'system:S3', samples: [
            { track_id: 'system', start: 1515, end: 1522, kind: 'diarization', overlap: true },
          ] },
        ],
      });
    }
    if (pathname.startsWith('/v1/recordings/e2e-meeting/tracks/') && pathname.endsWith('/audio')) {
      counts.speaker_audio_request += 1;
      return json(res, 404, { detail: 'fixture does not play synthetic audio' });
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/speaker-review' && req.method === 'POST') {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (body.expected_fingerprint !== speakerReviewFingerprint) {
        return json(res, 409, { detail: 'stale review' });
      }
      speakerReviewBefore = structuredClone(meetingFixture.transcription);
      if (body.action === 'reassign_turn' && body.cluster === 'system:S1' &&
        body.segment_id === 0 && body.target === 'system:S2') {
        counts.speaker_turn_reassign += 1;
        meetingFixture.transcription = {
          ...meetingFixture.transcription,
          segments: meetingFixture.transcription.segments.map((segment) =>
            segment.id === 0 ? {
              ...segment, speaker_group: 'system:S2', speaker_name: 'Speaker 2', speaker_label: 'Speaker 2',
            } : segment),
          stats: {
            ...meetingFixture.transcription.stats,
            speaker_review: { segment_assignments: { '0': 'system:S2' } },
          },
        };
      } else if (body.action === 'merge' && body.cluster === 'system:S1' && body.target === 'system:S2') {
        counts.speaker_merge += 1;
        speakerReviewUnmerged = structuredClone(speakerReviewBefore);
        meetingFixture.transcription = {
          ...meetingFixture.transcription,
          segments: meetingFixture.transcription.segments.map((s) => ({
            ...s, speaker_group: 'system:S2', speaker_name: 'Speaker 2',
          })),
          stats: {
            ...meetingFixture.transcription.stats,
            speaker_attribution: {
              mappings: [
                { speaker_cluster: 'system:S1', speaker_group: 'system:S2',
                  display_name: 'Speaker 2', status: 'merged', merged_into: 'system:S2',
                  transcript_segment_count: 1 },
                { speaker_cluster: 'system:S2', speaker_group: 'system:S2',
                  display_name: 'Speaker 2', status: 'unassigned',
                  transcript_segment_count: 0 },
                ...speakerReviewBefore.stats.speaker_attribution.mappings.filter(
                  (entry) => !['system:S1', 'system:S2'].includes(entry.speaker_cluster)),
              ],
            },
          },
        };
      } else if (body.action === 'restore' && body.cluster === 'system:S1' && speakerReviewUnmerged) {
        counts.speaker_restore += 1;
        meetingFixture.transcription = structuredClone(speakerReviewUnmerged);
      } else {
        return json(res, 409, { detail: 'Unexpected speaker review test action' });
      }
      speakerReviewFingerprint = 'b'.repeat(64);
      speakerReviewUndo = 'synthetic-speaker-undo';
      return json(res, 200, {
        transcription: meetingFixture.transcription,
        revision_id: speakerReviewUndo,
      });
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/speaker-review/undo' && req.method === 'POST') {
      if (!speakerReviewUndo || !speakerReviewBefore) return json(res, 409, { detail: 'No undo' });
      counts.speaker_undo += 1;
      meetingFixture.transcription = speakerReviewBefore;
      speakerReviewFingerprint = 'c'.repeat(64);
      speakerReviewUndo = null;
      return json(res, 200, { transcription: meetingFixture.transcription });
    }

    if (pathname === '/v1/transcriptions/e2e-transcription/diarization-reviews') {
      if (req.method === 'GET') {
        counts.review_list += 1;
        return json(res, 200, {
          items: communityReviewJob ? [communityReviewJob] : [],
          undo: communityReviewApplied ? { revision_id: 'synthetic-undo-token' } : null,
        });
      }
      if (req.method === 'POST') {
        counts.review_start += 1;
        counts.review_poll = 0;
        communityReviewJob = {
          id: 'e2e-community-review', type: 'diarization_review',
          recording_id: MEETING_ID, scope_type: 'transcription', scope_id: 'e2e-transcription',
          status: 'running', current_step: 'comparing', progress: 15,
        };
        return json(res, 202, communityReviewJob);
      }
    }
    if (pathname === '/v1/jobs/e2e-community-review' && req.method === 'GET') {
      counts.review_poll += 1;
      if (counts.review_poll === 1) {
        return json(res, 200, { ...communityReviewJob, status: 'running', progress: 65 });
      }
      communityReviewJob = {
        ...communityReviewJob, status: 'completed', progress: 100, current_step: 'completed',
      };
      return json(res, 200, communityReviewJob);
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/diarization-reviews/e2e-community-review/preview') {
      counts.review_preview += 1;
      return json(res, 200, {
        engine: 'fluidaudio-community-1', assigned_segments: 1,
        changed_segments: 1, cluster_count: 1,
        examples: [{
          start: 0, end: 3.5,
          text: meetingFixture.transcription.segments[0].text,
          before: 'SPEAKER_00', after: 'Speaker 1',
        }],
      });
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/diarization-reviews/e2e-community-review/apply'
        && req.method === 'POST') {
      counts.review_apply += 1;
      communityReviewApplied = true;
      return json(res, 200, {
        revision_id: 'synthetic-undo-token',
        transcription: {
          ...meetingFixture.transcription,
          segments: [{ ...meetingFixture.transcription.segments[0],
            provider_speaker: 'system:S1', speaker_label: 'Speaker 1',
            speaker_name: 'Speaker 1' }],
        },
      });
    }
    if (pathname === '/v1/transcriptions/e2e-transcription/diarization-reviews/undo'
        && req.method === 'POST') {
      counts.review_undo += 1;
      communityReviewApplied = false;
      return json(res, 200, { transcription: meetingFixture.transcription });
    }

    if (pathname === `/v1/recordings/${MEETING_ID}/diarization-benchmarks`) {
      if (req.method === 'GET') {
        counts.benchmark_list += 1;
        return json(res, 200, { items: benchmarkJob ? [benchmarkJob] : [] });
      }
      if (req.method === 'POST') {
        const chunks = [];
        for await (const part of req) chunks.push(part);
        benchmarkRequest = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        counts.benchmark_start += 1;
        counts.benchmark_poll = 0;
        benchmarkJob = {
          id: 'e2e-diarization-benchmark', type: 'diarization_benchmark',
          recording_id: MEETING_ID, scope_type: 'recording', scope_id: MEETING_ID,
          status: 'running', current_step: 'comparing', progress: 10,
          progress_detail: { engine: 'community-1', index: 1, total: 3 },
        };
        return json(res, 202, benchmarkJob);
      }
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/diarization-benchmarks/e2e-diarization-benchmark/timeline`) {
      counts.benchmark_window += 1;
      const params = new URL(req.url, `http://127.0.0.1:${port}`).searchParams;
      const start = Number(params.get('start_seconds'));
      const end = Number(params.get('end_seconds'));
      lastBenchmarkWindowStart = start;
      benchmarkWindowStarts.push(start);
      const sourceStart = benchmarkRequest.scope === 'range' ? benchmarkRequest.start_seconds : 0;
      const sourceEnd = benchmarkRequest.scope === 'range' ? benchmarkRequest.end_seconds
        : benchmarkRequest.scope === 'full' ? 600 : 300;
      const event = benchmarkRequest.scope === 'full'
        ? { speaker: 'B', start: 450, end: 470 }
        : { speaker: 'A', start: sourceStart + 30, end: sourceStart + 60 };
      return json(res, 200, {
        schema_version: 1, start_seconds: start, end_seconds: end,
        range_start_seconds: sourceStart, range_end_seconds: sourceEnd,
        runs: [{ key: 'community-1', status: 'completed', partial: false,
          segments: event.end > start && event.start < end ? [event] : [],
          speakers: benchmarkRequest.scope === 'full'
            ? [{ speaker: 'A', first_start: 30, in_window: start <= 30 && end > 30 },
               { speaker: 'B', first_start: 450, in_window: start <= 450 && end > 450 }]
            : [{ speaker: 'A', first_start: sourceStart + 30,
                 in_window: event.end > start && event.start < end }] }],
      });
    }
    if (pathname === '/v1/jobs/e2e-diarization-benchmark' && req.method === 'GET') {
      counts.benchmark_poll += 1;
      if (counts.benchmark_poll === 1) {
        return json(res, 200, { ...benchmarkJob, progress: 55,
          progress_detail: { engine: 'nemotron3-fast128', index: 2, total: 3 } });
      }
      benchmarkJob = {
        ...benchmarkJob, status: 'completed', current_step: 'completed', progress: 100,
        result: {
          schema_version: 1, scope: benchmarkRequest.scope, track_id: 'system',
          range_start_seconds: benchmarkRequest.scope === 'range' ? benchmarkRequest.start_seconds : 0,
          range_end_seconds: benchmarkRequest.scope === 'range' ? benchmarkRequest.end_seconds :
            benchmarkRequest.scope === 'full' ? 600 : 300,
          audio_seconds: benchmarkRequest.scope === 'range' ?
            benchmarkRequest.end_seconds - benchmarkRequest.start_seconds :
            benchmarkRequest.scope === 'full' ? 600 : 300,
          preview_seconds: 300, reference_scored: false,
          runs: [
            { key: 'community-1', engine: 'fluidaudio-community-1', preset: null, status: 'completed',
              elapsed_seconds: 15, speed_vs_realtime: 20, clusters: 2,
              preview: [{ speaker: 'A', start: 0, end: 65 }, { speaker: 'B', start: 61, end: 170 }] },
            { key: 'nemotron3-fast128', engine: 'nemotron3-coreml', preset: 'fast128', status: 'completed',
              elapsed_seconds: 12, speed_vs_realtime: 25, clusters: 2,
              preview: [{ speaker: '0', start: 0, end: 55 }, { speaker: '1', start: 50, end: 150 }] },
            { key: 'nemotron3-compact', engine: 'nemotron3-coreml', preset: 'c128-split-w8a8', status: 'completed',
              elapsed_seconds: 10, speed_vs_realtime: 30, clusters: 2,
              preview: [{ speaker: '0', start: 0, end: 70 }] },
          ],
        },
      };
      return json(res, 200, benchmarkJob);
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/notes`) {
      counts.notes += 1;
      return json(res, 200, { items: [], total: 0 });
    }
    if (pathname === `/v1/recordings/${ALTERNATE_MEETING_ID}/notes`) {
      counts.alternate_notes += 1;
      if (failNextAlternateNotes) {
        failNextAlternateNotes = false;
        return json(res, 503, { detail: 'synthetic note failure' });
      }
      return json(res, 200, { items: [], total: 0 });
    }
    if (pathname === `/v2/recordings/${ALTERNATE_MEETING_ID}/visual-intelligence`) {
      counts.alternate_visual_context += 1;
      return json(res, 200, {
        schema_version: 2,
        summary: {},
        source_validity: { status: 'current', manual_screenshot_count: 1,
          missing_screenshot_ids: [], unavailable_screenshot_ids: [], changed_screenshot_ids: [] },
        document: {
          schema_version: 2, observations: [], manual_screenshot_groups: [], speaker_intervals: [],
          meeting_state_events: [], share_sessions: [], unassigned_share_keyframes: [],
          semantic_links: [], routing_summary: {}, model: 'fixture-only', prompt_version: 1,
        },
      });
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/visual-frames`) {
      counts.visual_frames += 1;
      if (counts.visual_frames === 1) {
        return json(res, 503, { detail: 'synthetic visual-frame outage' });
      }
      return json(res, 200, {
        total: 3,
        items: [0, 1, 2].map((sequence) => ({
          sequence,
          timestamp: sequence + 1,
          url: `/fixture/frame-${sequence}.jpg`,
        })),
      });
    }
    return json(res, 404, { detail: `fixture route not found: ${pathname}` });
  });
}

function findChromeDriver() {
  const candidates = [
    process.env.CHROMEWEBDRIVER,
    '/usr/local/share/chromedriver-mac-arm64/chromedriver',
    '/usr/local/share/chromedriver-mac-x64/chromedriver',
  ].filter(Boolean);
  for (const candidate of candidates) {
    for (const option of [candidate, path.join(candidate, 'chromedriver')]) {
      try {
        if (!fs.statSync(option).isFile()) continue;
        fs.accessSync(option, fs.constants.X_OK);
        return option;
      } catch {}
    }
  }
  throw new Error('chromedriver executable not found on browser-macos-arm64-ci runner');
}

async function webdriver(port, method, pathname, payload) {
  const response = await fetch(`http://127.0.0.1:${port}${pathname}`, {
    method,
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const parsed = await response.json();
  if (!response.ok || parsed?.value?.error) {
    throw new Error(`WebDriver ${response.status}: ${JSON.stringify(parsed).slice(0, 1000)}`);
  }
  return parsed.value;
}

class Browser {
  constructor(port) {
    this.port = port;
    this.sessionId = null;
  }

  async start() {
    const value = await webdriver(this.port, 'POST', '/session', {
      capabilities: {
        alwaysMatch: {
          browserName: 'chrome',
          'goog:chromeOptions': {
            ...(process.env.CI_CHROME_BINARY ? { binary: process.env.CI_CHROME_BINARY } : {}),
            args: [
              '--headless=new',
              '--disable-gpu',
              '--hide-scrollbars',
              '--window-size=1440,1000',
              '--force-device-scale-factor=1',
              '--disable-background-networking',
              '--disable-default-apps',
            ],
          },
        },
      },
    });
    this.sessionId = value.sessionId;
  }

  p(suffix) {
    return `/session/${this.sessionId}${suffix}`;
  }

  async close() {
    if (!this.sessionId) return;
    try { await webdriver(this.port, 'DELETE', this.p('')); } catch {}
    this.sessionId = null;
  }

  async navigate(url) {
    await webdriver(this.port, 'POST', this.p('/url'), { url });
  }

  async execute(script) {
    return await webdriver(this.port, 'POST', this.p('/execute/sync'), { script, args: [] });
  }

  async text() {
    return String(await this.execute("return document.body ? document.body.innerText : '';"));
  }

  async clickCss(selector) {
    const value = await webdriver(this.port, 'POST', this.p('/element'), {
      using: 'css selector',
      value: selector,
    });
    await webdriver(this.port, 'POST', this.p(`/element/${value[ELEMENT_KEY]}/click`), {});
  }

  async clickButton(labels) {
    const clicked = await this.execute(`
      const labels = ${JSON.stringify(labels)};
      const button = Array.from(document.querySelectorAll('button')).find((candidate) => {
        const text = (candidate.innerText || candidate.textContent || '').trim();
        return labels.some((label) => text === label || text.includes(label));
      });
      if (!button) return false;
      button.click();
      return true;
    `);
    if (clicked !== true) throw new Error(`button not found: ${labels.join(', ')}`);
  }

  async clickStatusButton(statusLabels, buttonLabels) {
    const clicked = await this.execute(`
      const statusLabels = ${JSON.stringify(statusLabels)};
      const buttonLabels = ${JSON.stringify(buttonLabels)};
      const status = Array.from(document.querySelectorAll('[role="status"]')).find((candidate) => {
        const text = (candidate.innerText || candidate.textContent || '').trim();
        return statusLabels.some((label) => text.includes(label));
      });
      if (!status) return false;
      const button = Array.from(status.querySelectorAll('button')).find((candidate) => {
        const text = (candidate.innerText || candidate.textContent || '').trim();
        return buttonLabels.some((label) => text === label || text.includes(label));
      });
      if (!button) return false;
      button.click();
      return true;
    `);
    if (clicked !== true) {
      throw new Error(
        `button not found in status ${statusLabels.join(' | ')}: ${buttonLabels.join(', ')}`,
      );
    }
  }

  async screenshot(destination) {
    const data = await webdriver(this.port, 'GET', this.p('/screenshot'));
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await fsp.writeFile(destination, Buffer.from(data, 'base64'));
  }
}

async function frame(browser, source) {
  const destination = path.join(
    evidenceRoot,
    'frames',
    `frame-${String(frameIndex++).padStart(4, '0')}.png`,
  );
  await fsp.mkdir(path.dirname(destination), { recursive: true });
  if (source) await fsp.copyFile(source, destination);
  else await browser.screenshot(destination);
}

async function checkpoint(browser, name, holdFrames = VIDEO_FPS) {
  const destination = path.join(evidenceRoot, 'screenshots', `${name}.png`);
  await browser.screenshot(destination);
  checkpoints.push({ name, screenshot: path.relative(evidenceRoot, destination) });
  for (let index = 0; index < holdFrames; index += 1) await frame(browser, destination);
}

async function waitText(browser, needles, timeoutMs = 5000, record = false) {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = await browser.text();
    if (needles.some((needle) => last.includes(needle))) return last;
    if (record) await frame(browser);
    await sleep(200);
  }
  throw new Error(`timed out waiting for ${needles.join(' | ')}; text=${last.slice(0, 1000)}`);
}

// WebDriver's actual pointer action is authoritative. A custom elementFromPoint
// center heuristic can report the enclosing Section instead of its child button
// in Radix drawer content, despite a visible and actionable target.
async function clickWhenPointerReady(browser, selector, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      // Never substitute HTMLElement.click(): this must exercise pointer interaction.
      await browser.clickCss(selector);
      return;
    } catch (error) {
      lastError = String(error?.message || error);
      await sleep(100);
    }
  }
  const details = await browser.execute(`
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return { reason: 'missing', lastError: ${JSON.stringify(lastError)} };
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    const dialog = element.closest('[role="dialog"]');
    const section = element.closest('section');
    const samplePoints = [
      [0.5, 0.5], [0.1, 0.5], [0.9, 0.5], [0.5, 0.15], [0.5, 0.85],
    ].map(([rx, ry]) => {
      const stack = document.elementsFromPoint(rect.left + rect.width * rx, rect.top + rect.height * ry);
      return { point: [rx, ry], hits: stack.slice(0, 4).map((node) => node.tagName + ':' + (node.className?.baseVal || node.className || '').toString().slice(0, 50)) };
    });
    const style = getComputedStyle(element);
    const sectionStyle = section ? getComputedStyle(section) : null;
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      target: element.tagName, hit: hit?.tagName || null,
      hitIsOwnSection: hit === section, hitClass: typeof hit?.className === 'string' ? hit.className.slice(0, 120) : null,
      samplePoints,
      button: {
        disabled: element.disabled, inert: element.inert, hidden: element.hidden,
        clientRects: element.getClientRects().length, visibility: style.visibility, display: style.display,
        opacity: style.opacity, pointerEvents: style.pointerEvents, zIndex: style.zIndex,
        position: style.position, transform: style.transform, clipPath: style.clipPath,
        contentVisibility: style.contentVisibility,
      },
      section: {
        inert: section?.inert, pointerEvents: sectionStyle?.pointerEvents,
        position: sectionStyle?.position, zIndex: sectionStyle?.zIndex,
        before: section ? getComputedStyle(section, '::before').content : null,
        after: section ? getComputedStyle(section, '::after').content : null,
      },
      inertAncestors: Array.from((function* () { for (let node = element; node; node = node.parentElement) if (node.inert || node.hasAttribute('inert')) yield node.tagName; })()),
      dialogTransform: dialog ? getComputedStyle(dialog).transform : null,
    };
  `);
  throw new Error(`WebDriver pointer click unavailable for ${selector}: ${lastError}; ${JSON.stringify(details)}`);
}

async function waitCount(key, minimum, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (counts[key] >= minimum) return;
    await sleep(50);
  }
  throw new Error(`timed out waiting for ${key} >= ${minimum}; counts=${JSON.stringify(counts)}`);
}

/** Synchronize both the requested API window and the React-rendered slider.
 * Request counters alone can advance on an obsolete/stale fetch. */
async function waitBenchmarkWindow(browser, expectedStart, minimumRequests, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  let observed = null;
  while (Date.now() < deadline) {
    observed = await browser.execute(`
      const root = document.querySelector('[data-diarization-benchmark="true"]');
      const slider = Array.from(root?.querySelectorAll('input[type="range"]') || [])
        .find((el) => /Timeline position|Posizione della timeline/.test(el.getAttribute('aria-label') || ''));
      return { slider: slider ? Number(slider.value) : null, exists: Boolean(root) };
    `);
    if (counts.benchmark_window >= minimumRequests
      && lastBenchmarkWindowStart === expectedStart
      && observed?.slider === expectedStart) return;
    await sleep(75);
  }
  throw new Error(`Benchmark window never stabilized at ${expectedStart}s: ${JSON.stringify({
    observed, requests: counts.benchmark_window, windowStarts: benchmarkWindowStarts
  })}`);
}

async function waitAbsent(browser, needles, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const text = await browser.text();
    if (!needles.some((needle) => text.includes(needle))) return;
    await frame(browser);
    await sleep(200);
  }
  throw new Error(`text did not disappear: ${needles.join(' | ')}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'recovery.mp4');
  await fsp.mkdir(path.dirname(videoPath), { recursive: true });
  const process = launch(
    'ffmpeg',
    [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-framerate', String(VIDEO_FPS),
      '-i', path.join(evidenceRoot, 'frames', 'frame-%04d.png'),
      '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
      videoPath,
    ],
    { stdio: 'inherit' },
  );
  const code = await new Promise((resolve, reject) => {
    process.once('error', reject);
    process.once('exit', resolve);
  });
  if (code !== 0) throw new Error(`ffmpeg exited ${code}`);
  const stat = await fsp.stat(videoPath);
  if (!stat.size) throw new Error('recovery video is empty');
  return path.relative(evidenceRoot, videoPath);
}

async function stop(process) {
  if (!process || process.exitCode !== null) return;
  process.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => process.once('exit', resolve)),
    sleep(5000),
  ]);
  if (process.exitCode === null) process.kill('SIGKILL');
}

await fsp.rm(evidenceRoot, { recursive: true, force: true });
await fsp.mkdir(path.join(evidenceRoot, 'logs'), { recursive: true });

const backendPort = await freePort();
const vitePort = await freePort();
const driverPort = await freePort();
const server = fixtureServer(backendPort);
await new Promise((resolve) => server.listen(backendPort, '127.0.0.1', resolve));
const viteLog = fs.openSync(path.join(evidenceRoot, 'logs/vite.log'), 'w');
const driverLog = fs.openSync(path.join(evidenceRoot, 'logs/chromedriver.log'), 'w');
let vite;
let driver;
let browser;
let video = null;
let error = null;

try {
  vite = launch(
    'pnpm',
    ['exec', 'vite', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
    {
      cwd: path.join(root, 'frontend'),
      env: { ...process.env, BACKEND_PORT: String(backendPort) },
      stdio: ['ignore', viteLog, viteLog],
    },
  );
  await waitPort(vitePort, 15000, vite);

  driver = launch(
    findChromeDriver(),
    [`--port=${driverPort}`, '--allowed-ips=127.0.0.1'],
    { cwd: root, stdio: ['ignore', driverLog, driverLog] },
  );
  await waitPort(driverPort, 10000, driver);

  browser = new Browser(driverPort);
  await browser.start();
  await browser.navigate(`http://127.0.0.1:${vitePort}/#meeting/${MEETING_ID}`);
  await waitText(browser, ['Quarterly launch review'], 30000, true);
  await waitText(browser, ['Decision: ship the release after validation.']);
  if (counts.diagnostics !== 0 || counts.visual_frames !== 0 || counts.audio_intelligence !== 0) {
    throw new Error(`normal open fetched disclosure-driven accessories: ${JSON.stringify(counts)}`);
  }
  await waitCount('screenshots', 1);
  await checkpoint(browser, '01-ready-core-only');

  await browser.clickButton(['Details', 'Dettagli']);
  if (counts.audio_intelligence !== 0) throw new Error('Opening Meeting Details fetched audio metrics without user disclosure');
  await waitCount('diagnostics', 1);
  await waitText(
    browser,
    ['Loading detailed diagnostics', 'Caricamento diagnostica dettagliata'],
    3000,
    true,
  );
  await checkpoint(browser, '02-partial-diagnostics-loading');
  await waitText(
    browser,
    ['Detailed diagnostics unavailable', 'Diagnostica dettagliata non disponibile'],
    DIAGNOSTICS_DELAY_MS + 5000,
    true,
  );
  await waitText(browser, ['Quarterly launch review']);
  await checkpoint(browser, '03-diagnostics-error-core-preserved');
  await browser.clickStatusButton(
    ['Detailed diagnostics unavailable', 'Diagnostica dettagliata non disponibile'],
    ['Retry', 'Riprova'],
  );
  await waitCount('diagnostics', 2);
  await waitAbsent(
    browser,
    ['Detailed diagnostics unavailable', 'Diagnostica dettagliata non disponibile'],
  );
  await checkpoint(browser, '04-diagnostics-recovered');

  const audioControls = await browser.execute(`
    const section = document.querySelector('[data-meeting-recording-details="true"]');
    return Boolean(section && /Tracce e qualità audio|Audio tracks and quality/.test(section.querySelector('button[aria-expanded]')?.textContent || ''));
  `);
  if (!audioControls) throw new Error('Canonical Meeting lost recording quality and source track access');
  await clickWhenPointerReady(browser, '[data-meeting-recording-details="true"] button[aria-expanded]');
  await waitText(browser, ['System track'], 5000, true);
  await clickWhenPointerReady(browser, '[data-meeting-audio-intelligence="true"] button[aria-expanded]');
  const expanded = await browser.execute(`
    return document.querySelector('[data-meeting-audio-intelligence="true"] button[aria-expanded]')?.getAttribute('aria-expanded') === 'true';
  `);
  if (!expanded) throw new Error('Audio Intelligence disclosure did not open through pointer interaction');
  await waitCount('audio_intelligence', 1);
  await waitText(browser, ['48%'], 5000, true);
  await checkpoint(browser, '04a-audio-metrics-on-demand');

  await browser.clickCss('button[aria-label="Chiudi"]');
  await browser.clickCss('#meeting-tab-analysis');
  await waitCount('visual_frames', 1);
  await waitText(
    browser,
    ['Screen context unavailable', 'Contesto schermo non disponibile'],
    5000,
    true,
  );
  await waitText(browser, ['Quarterly launch review']);
  await checkpoint(browser, '05-visual-error-core-preserved');
  await browser.clickStatusButton(
    ['Screen context unavailable', 'Contesto schermo non disponibile'],
    ['Retry', 'Riprova'],
  );
  await waitCount('visual_frames', 2);
  await waitText(
    browser,
    ['Screen context available', 'Contesto schermo disponibile'],
    5000,
    true,
  );
  await checkpoint(browser, '06-visual-recovered');

  if (counts.diagnostics !== 2 || counts.visual_frames !== 2) {
    throw new Error(`unexpected retry counts: ${JSON.stringify(counts)}`);
  }

  // Same React component, different recordingId prop: late responses from an
  // earlier Meeting must not overwrite the currently selected Meeting.
  const setMeetingHash = async (id) => {
    const changed = await browser.execute(`
      window.location.hash = ${JSON.stringify('#meeting/')} + ${JSON.stringify(id)};
      return true;
    `);
    if (!changed) throw new Error('could not update the Meeting route');
  };
  const expectCurrentMeeting = async (title, forbiddenTitle, forbiddenTranscript) => {
    await waitText(browser, [title], 5000, true);
    const visible = await browser.execute(`
      const body = document.body.innerText;
      return body.includes(${JSON.stringify(title)})
        && !body.includes(${JSON.stringify(forbiddenTitle)})
        && !body.includes(${JSON.stringify(forbiddenTranscript)});
    `);
    if (!visible) throw new Error('stale Meeting content leaked into ' + title);
  };

  // E4: selection is owned by the current list and recording identity.
  // Both fixtures intentionally share an ID so a stale selection would
  // accidentally rebind to an unrelated Meeting unless scoped.
  await browser.clickCss('[data-key-moment-id="synthetic-shared-key"]');
  const opened = await browser.execute(`
    return Array.from(document.querySelectorAll('[role="dialog"]')).some((node) =>
      (node.innerText || '').includes('Launch screenshot A'));
  `);
  if (!opened) throw new Error('original Meeting key-moment modal did not open');
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  await waitCount('alternate_screenshots', 1);
  const leaked = await browser.execute(`
    return Array.from(document.querySelectorAll('[role="dialog"]')).some((node) =>
      ['Screenshot della riunione', 'Meeting screenshot'].includes(node.getAttribute('aria-label')));
  `);
  if (leaked) throw new Error('stale key-moment modal carried into alternate Meeting');
  await checkpoint(browser, '07-meeting-key-moment-scope');

  holdNextMeetingId = MEETING_ID;
  await setMeetingHash(MEETING_ID);
  await waitCount('held_meeting', 1);
  const alternateRequestsBeforeReturn = counts.alternate_meeting;
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitCount('alternate_meeting', alternateRequestsBeforeReturn + 1);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  if (heldMeetingResponses.length !== 1) throw new Error('expected one delayed original Meeting response');
  heldMeetingResponses.shift()('success');
  await sleep(500);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  await checkpoint(browser, '07-late-success-ignored');

  await setMeetingHash(MEETING_ID);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  holdNextMeetingId = ALTERNATE_MEETING_ID;
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitCount('held_meeting', 2);
  const originalRequestsBeforeReturn = counts.meeting;
  await setMeetingHash(MEETING_ID);
  await waitCount('meeting', originalRequestsBeforeReturn + 1);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  if (heldMeetingResponses.length !== 1) throw new Error('expected one delayed alternate Meeting response');
  heldMeetingResponses.shift()('error');
  await sleep(500);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  const staleErrorVisible = await browser.execute(`
    return document.body.innerText.includes('stale_meeting_fetch_failed');
  `);
  if (staleErrorVisible) throw new Error('stale Meeting request error leaked into current view');
  await checkpoint(browser, '08-late-error-ignored');

  // List requests have independent error and retry lifecycles even though
  // screenshots and notes now share the list-loading implementation.
  failNextAlternateScreenshots = true;
  failNextAlternateNotes = true;
  const screenshotsBeforeFailure = counts.alternate_screenshots;
  const notesBeforeFailure = counts.alternate_notes;
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  await waitCount('alternate_screenshots', screenshotsBeforeFailure + 1);
  await waitCount('alternate_notes', notesBeforeFailure + 1);
  await waitText(browser, ['Screenshots unavailable', 'Screenshot non disponibili'], 5000, true);
  await waitText(browser, ['Meeting notes unavailable', 'Note del meeting non disponibili'], 5000, true);

  const retryAccessory = async (messages) => {
    const clicked = await browser.execute(`
      const messages = ${JSON.stringify(messages)};
      const heading = Array.from(document.querySelectorAll('section p'))
        .find((node) => messages.some((message) => (node.textContent || '').trim() === message));
      const button = Array.from(heading?.closest('section')?.querySelectorAll('button') || [])
        .find((node) => ['Retry', 'Riprova'].includes((node.textContent || '').trim()));
      if (!button || button.disabled) return false;
      button.click();
      return true;
    `);
    if (!clicked) throw new Error('Could not retry ' + messages.join(' / '));
  };
  await retryAccessory(['Screenshots unavailable', 'Screenshot non disponibili']);
  await waitCount('alternate_screenshots', screenshotsBeforeFailure + 2);
  await waitAbsent(browser, ['Screenshots unavailable', 'Screenshot non disponibili'], 5000);
  await waitText(browser, ['Meeting notes unavailable', 'Note del meeting non disponibili']);

  await retryAccessory(['Meeting notes unavailable', 'Note del meeting non disponibili']);
  await waitCount('alternate_notes', notesBeforeFailure + 2);
  await waitAbsent(browser, ['Meeting notes unavailable', 'Note del meeting non disponibili'], 5000);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  await checkpoint(browser, '09-independent-list-recovery');

  // E4: visual context fetch belongs to a visible key-moment dialog, not a
  // sticky boolean that survives closing it. Switch the existing synthetic
  // meeting to visual V2 only after the previous recovery assertions.
  await browser.clickCss('#meeting-tab-transcript');
  alternateMeetingFixture.transcription.stats = {
    ...alternateMeetingFixture.transcription.stats,
    visual_intelligence: { version: 2 },
  };
  await setMeetingHash(MEETING_ID);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  const alternateLoadsBeforeVisual = counts.alternate_meeting;
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitCount('alternate_meeting', alternateLoadsBeforeVisual + 1);
  await expectCurrentMeeting('Alternate pricing review', 'Quarterly launch review', meetingFixture.transcription.text);
  await waitCount('alternate_screenshots', screenshotsBeforeFailure + 3);
  await sleep(300);
  if (counts.alternate_visual_context !== 0) {
    throw new Error('closed key-moment dialog preloaded visual context');
  }
  await browser.clickCss('[data-key-moment-id="synthetic-shared-key"]');
  await waitCount('alternate_visual_context', 1);
  await browser.clickCss('button[aria-label="Chiudi screenshot"], button[aria-label="Close screenshot"]');
  const dialogStillOpen = await browser.execute(`
    return Array.from(document.querySelectorAll('[role="dialog"]')).some((node) =>
      ['Screenshot della riunione', 'Meeting screenshot'].includes(node.getAttribute('aria-label')));
  `);
  if (dialogStillOpen) throw new Error('key-moment dialog did not close');
  await browser.clickCss('[data-key-moment-id="synthetic-shared-key"]');
  await waitCount('alternate_visual_context', 2);
  await checkpoint(browser, '10-visual-context-demand-not-sticky');


  // Synthetic browser evidence: a 30-minute meeting with a speaker whose
  // only verified interval starts at 25:15 (zero ASR-attributed phrases).
  meetingFixture.recording.duration_seconds = 1800;
  meetingFixture.recording.stopped_at = '2026-09-05T10:30:00Z';
  meetingFixture.transcription.source_tracks = [{ id: 'system', label: 'Computer' }];
  meetingFixture.transcription.segments[0].track_id = 'system';
  meetingFixture.transcription.segments[0].provider_speaker = 'system:S1';
  meetingFixture.transcription.stats.speaker_attribution = {
    mappings: [
      { speaker_cluster: 'system:S1', speaker_group: 'system:S1',
        display_name: 'Speaker 1', status: 'unassigned', transcript_segment_count: 1 },
      { speaker_cluster: 'system:S2', speaker_group: 'system:S2',
        display_name: 'Speaker 2', status: 'unassigned', transcript_segment_count: 0 },
      { speaker_cluster: 'system:S3', speaker_group: 'system:S3',
        display_name: 'Giulia', status: 'accepted', transcript_segment_count: 0 },
      { speaker_cluster: 'Computer', speaker_group: 'Computer',
        display_name: 'Computer', status: 'unassigned', transcript_segment_count: 0 },
    ],
  };

  // Comparison is an explicit advanced action on a saved meeting. It must
  // not run during the normal read/analysis flows, or mutate transcript text.
  if (counts.benchmark_start !== 0) {
    throw new Error('meeting speaker comparison started without user consent');
  }
  await setMeetingHash(MEETING_ID);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  await browser.clickCss('#meeting-tab-transcript');
  const readableTranscript = await browser.execute(`
    const root = document.getElementById('meeting-panel-transcript');
    const mode = root?.querySelector('[data-transcript-mode-control="true"]');
    return Boolean(mode &&
      ['Conversazione', 'Conversation'].some((word) =>
        mode.querySelector('button[aria-pressed="true"]')?.textContent?.includes(word)) &&
      root.querySelectorAll('[data-transcript-turn="conversation"]').length >= 1);
  `);
  if (!readableTranscript) throw new Error('Meeting must default to readable conversation with audio diagnostics hidden');
  // A scoped correction must not rename every utterance or alter the raw provider.
  await browser.clickCss('#meeting-panel-transcript [data-transcript-turn="conversation"] [data-turn-correction-open="true"]');
  const correctionAvailable = await browser.execute(`
    const panel = document.querySelector('#meeting-panel-transcript [data-turn-correction="true"]');
    const target = panel?.querySelector('[data-turn-target-select="true"]');
    const turn = panel?.querySelector('[data-turn-segment-select="true"]');
    if (!target || !turn || Number(turn.value) !== 0) return false;
    target.value = 'system:S2';
    target.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  `);
  if (!correctionAvailable) throw new Error('single-turn correction controls not reachable');
  await sleep(100);
  await browser.clickCss('#meeting-panel-transcript [data-turn-save="true"]');
  await waitCount('speaker_turn_reassign', 1);
  await waitText(browser, ['Undo last speaker correction', 'Annulla ultima correzione'], 5000, true);
  if (meetingFixture.transcription.segments[0].provider_speaker !== 'system:S1' ||
    meetingFixture.transcription.segments[0].speaker_group !== 'system:S2' ||
    meetingFixture.transcription.text !== 'Decision: ship the release after validation. Owner: Alex.') {
    throw new Error('scoped correction mutated raw cluster or immutable transcript text');
  }
  await checkpoint(browser, '11a-single-turn-corrected');
  await browser.clickButton(['Undo last speaker correction', 'Annulla ultima correzione']);
  await waitCount('speaker_undo', 1);
  if (meetingFixture.transcription.segments[0].speaker_group === 'system:S2') {
    throw new Error('single-turn undo did not restore original attribution');
  }
  const switchedToDetails = await browser.execute(`
    const buttons = document.querySelectorAll('#meeting-panel-transcript [data-transcript-mode-control="true"] button');
    const details = [...buttons].find((button) =>
      ['Dettagli', 'Details'].some((word) => button.textContent.includes(word)));
    if (!details) return false;
    details.click();
    return true;
  `);
  if (!switchedToDetails) throw new Error('Detailed transcript mode is not selectable');
  const detailMode = await browser.execute(`
    const root = document.getElementById('meeting-panel-transcript');
    const selected = root?.querySelector('[data-transcript-mode-control="true"] button[aria-pressed="true"]');
    return Boolean(['Dettagli', 'Details'].some((word) => selected?.textContent?.includes(word)) &&
      !root.querySelector('[data-transcript-turn="conversation"]'));
  `);
  if (!detailMode) throw new Error('Detailed transcript view did not replace grouped conversation');
  await checkpoint(browser, '11-transcript-conversation-and-detail');
  await browser.clickCss('#meeting-tab-speakers');
  await waitText(browser, ['Voices', 'Voci']);
  await waitCount('speaker_sample_list', 1);
  if (counts.speaker_audio_request !== 0) {
    throw new Error('Speaker review loaded private audio before user pressed Play');
  }
  const sampleReady = await browser.execute(`
    const root = document.querySelector('[data-speaker-review-workspace]');
    return Boolean(root && [...root.querySelectorAll('button')].some((b) =>
      (b.innerText || '').includes('Ascolta campione') ||
      (b.innerText || '').includes('Play sample') && !b.disabled));
  `);
  if (!sampleReady) throw new Error('Speaker sample control absent');
  await waitCount('speaker_timeline', 1);
  let initialTimeline = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    initialTimeline = await browser.execute(`
    const view = document.querySelector('[data-speaker-review-timeline]');
    return Boolean(view &&
      view.querySelector('[data-speaker-overview]') &&
      view.querySelector('[data-speaker-lane="system:S1"] button[aria-label^="Explore"], [data-speaker-lane="system:S1"] button[aria-label^="Esplora"]') &&
      view.querySelector('[data-speaker-lane="system:S2"] button[aria-label^="Explore"], [data-speaker-lane="system:S2"] button[aria-label^="Esplora"]') &&
      view.querySelector('[data-speaker-lane="system:S3"] button[aria-label^="Explore"], [data-speaker-lane="system:S3"] button[aria-label^="Esplora"]') &&
      !view.querySelector('[data-speaker-lane="Computer"]') &&
      view.querySelector('[data-timeline-coverage="diarization"]') &&
      (view.textContent || '').includes('30:00'));
  `);
    if (initialTimeline) break;
    await sleep(100);
  }
  if (!initialTimeline) throw new Error('speaker timeline did not show 30-minute overview and audio-only voice');
  // Audio-only speakers must not be displayed as zero speaking turns.
  // Counted intervals and transcript-linked text are distinct evidence.
  let linkedEvidence = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    linkedEvidence = await browser.execute(`
      const evidence = document.querySelector('[data-speaker-evidence="system:S1"]');
      return Boolean(evidence && /1 (intervento collegato al testo|transcript-linked turn)/.test(evidence.textContent || '') &&
        /1 (intervallo nella timeline|interval on timeline)/.test(evidence.textContent || ''));
    `);
    if (linkedEvidence) break;
    await sleep(100);
  }
  if (!linkedEvidence) throw new Error('transcript-linked speaker did not show separately sourced counts');
  await browser.clickCss('[data-speaker-lane="system:S2"] button[title="Speaker 2"]');
  await waitText(browser, ['Testo non collegato a questa voce', 'No transcript text linked to this voice'], 5000, true);
  const audioOnlyEvidence = await browser.execute(`
    const evidence = document.querySelector('[data-speaker-evidence="system:S2"]');
    return Boolean(evidence && /1 (intervallo nella timeline|interval on timeline)/.test(evidence.textContent || '') &&
      !/0 (interventi|turns)/.test(evidence.textContent || ''));
  `);
  if (!audioOnlyEvidence) throw new Error('audio-only speaker was mislabeled as having zero speaking turns');
  await browser.clickCss('[data-speaker-lane="system:S3"] button[title="Giulia"]');
  await waitText(browser, ['Testo non collegato a questa voce', 'No transcript text linked to this voice'], 5000, true);
  const lateAudioOnlyEvidence = await browser.execute(`
    const evidence = document.querySelector('[data-speaker-evidence="system:S3"]');
    return Boolean(evidence && /1 (intervallo nella timeline|interval on timeline)/.test(evidence.textContent || ''));
  `);
  if (!lateAudioOnlyEvidence) throw new Error('late audio-only speaker was not represented accurately');
  await browser.clickCss('[data-speaker-lane="system:S1"] button[title="Speaker 1"]');
  if (counts.speaker_audio_request !== 0) {
    throw new Error('speaker evidence summary caused eager private audio retrieval');
  }
  const located = await browser.execute(`
    const lane = document.querySelector('[data-speaker-lane="system:S3"]');
    const bin = lane?.querySelector('button[title*="25:"]');
    if (!bin) return false;
    bin.click(); return true;
  `);
  if (!located) throw new Error('audio-only voice at 25:15 not navigable from overview');
  await waitCount('speaker_timeline', 2);
  let lateSegment = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    lateSegment = await browser.execute(`
      return Boolean(document.querySelector(
        '[data-speaker-lane="system:S3"] [data-interval-origin="diarization"]'
      ));
    `);
    if (lateSegment) break;
    await sleep(100);
  }
  if (!lateSegment) throw new Error('native speaker interval at 25:15 was not shown after zoom');
  await browser.execute(`
    const timeline = document.querySelector('[data-speaker-review-timeline]');
    [...timeline.querySelectorAll('button')].find((button) =>
      ['All', 'Tutto'].includes((button.textContent || '').trim()))?.click();
  `);
  await waitCount('speaker_timeline', 3);
  if (counts.speaker_audio_request !== 0) throw new Error('timeline downloaded private audio without Play');
  const zoomed = await browser.execute(`
    const timeline = document.querySelector('[data-speaker-review-timeline]');
    const button = Array.from(timeline?.querySelectorAll('button') || [])
      .find((item) => (item.textContent || '').trim() === '1 min');
    if (!button) return false;
    button.click();
    return true;
  `);
  if (!zoomed) throw new Error('speaker timeline zoom unavailable');
  await waitCount('speaker_timeline', 4);
  const zoomStatus = await browser.execute(`
    return document.querySelector('[data-speaker-review-timeline] button[aria-pressed="true"]')?.textContent?.trim() === '1 min';
  `);
  if (!zoomStatus) throw new Error('speaker zoom button did not reflect selection');
  // An interval spanning 0:55–1:05 must occupy only the last five
  // seconds of the 0:00–1:00 viewport, not run beyond its right edge.
  let clippedBoundary = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    clippedBoundary = await browser.execute(`
      const interval = document.querySelector(
        '[data-speaker-lane="system:S2"] [data-speaker-interval][title*="0:55"]'
      );
      if (!interval) return false;
      const left = Number.parseFloat(interval.style.left);
      const width = Number.parseFloat(interval.style.width);
      return Math.abs(left - (55 / 60 * 100)) < 0.1 &&
        Math.abs(width - (5 / 60 * 100)) < 0.1 &&
        left + width <= 100.001;
    `);
    if (clippedBoundary) break;
    await sleep(100);
  }
  if (!clippedBoundary) throw new Error('speaker interval crossing zoom edge was not visually clipped');

  const restoredAll = await browser.execute(`
    const timeline = document.querySelector('[data-speaker-review-timeline]');
    const button = Array.from(timeline?.querySelectorAll('button') || [])
      .find((item) => ['Tutto', 'All'].includes((item.textContent || '').trim()));
    if (!button) return false;
    button.click();
    return true;
  `);
  if (!restoredAll) throw new Error('cannot restore full-meeting speaker timeline');
  await waitCount('speaker_timeline', 5);
  await checkpoint(browser, '11a-speaker-review-ready');
  await browser.clickCss('[data-speaker-review-workspace] button[aria-label="Manage this voice"], [data-speaker-review-workspace] button[aria-label="Gestisci questa voce"]');
  await browser.clickButton(['Merge voice', 'Unisci voce']);
  const targetChanged = await browser.execute(`
    const select = document.querySelector('[data-speaker-review-workspace] select');
    if (!select) return false;
    select.value = 'system:S2';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  `);
  if (!targetChanged) throw new Error('Speaker merge target selection unavailable');
  await sleep(120);
  await browser.clickButton(['Confirm merge', 'Conferma unione']);
  await waitCount('speaker_merge', 1);
  await waitText(browser, ['Undo last correction', 'Annulla ultima modifica'], 6000, true);
  if (meetingFixture.transcription.text !== 'Decision: ship the release after validation. Owner: Alex.') {
    throw new Error('Speaker merge changed canonical text in fixture');
  }
  let mergedTimeline = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    mergedTimeline = await browser.execute(`
    const timeline = document.querySelector('[data-speaker-review-timeline]');
    // The two source intervals are in distinct overview bins. The merged
    // group must retain both, rather than requiring a single contiguous bar.
    return Boolean(timeline &&
      timeline.querySelectorAll('[data-speaker-lane="system:S2"] button[aria-label^="Explore"], [data-speaker-lane="system:S2"] button[aria-label^="Esplora"]').length === 2 &&
      !timeline.querySelector('[data-speaker-lane="system:S1"]'));
  `);
    if (mergedTimeline) break;
    await sleep(100);
  }
  if (!mergedTimeline) throw new Error('merged speaker timeline did not regroup raw intervals');
  let mergedEvidence = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    mergedEvidence = await browser.execute(`
      const evidence = document.querySelector('[data-speaker-evidence="system:S2"]');
      return Boolean(evidence && /2 (intervalli nella timeline|intervals on timeline)/.test(evidence.textContent || '') &&
        /1 (intervento collegato al testo|transcript-linked turn)/.test(evidence.textContent || ''));
    `);
    if (mergedEvidence) break;
    await sleep(100);
  }
  if (!mergedEvidence) throw new Error('merging speaker identities did not regroup audio and text evidence independently');
  await checkpoint(browser, '11b-speaker-review-merged');
  await browser.clickButton(['Undo last correction', 'Annulla ultima modifica']);
  await waitCount('speaker_undo', 2);
  let undoTimeline = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    undoTimeline = await browser.execute(`
    const timeline = document.querySelector('[data-speaker-review-timeline]');
    return Boolean(
      timeline?.querySelector('[data-speaker-lane="system:S1"] button[aria-label^="Explore"], [data-speaker-lane="system:S1"] button[aria-label^="Esplora"]') &&
      timeline?.querySelector('[data-speaker-lane="system:S2"] button[aria-label^="Explore"], [data-speaker-lane="system:S2"] button[aria-label^="Esplora"]'));
  `);
    if (undoTimeline) break;
    await sleep(100);
  }
  if (!undoTimeline) {
    const lanes = await browser.execute(`
      return [...document.querySelectorAll('[data-speaker-lane]')].map((row) => ({
        cluster: row.getAttribute('data-speaker-lane'),
        buttons: [...row.querySelectorAll('button')].map((button) => button.getAttribute('aria-label')),
      }));
    `);
    throw new Error('undo failed to restore separate speaker lanes: ' + JSON.stringify(lanes));
  }
  await checkpoint(browser, '11c-speaker-review-undo');

  // Undo and later restore are distinct recovery paths. A merged voice must
  // remain actionable from the minimal UI without showing a duplicate lane.
  await browser.clickCss('[data-speaker-lane="system:S1"] button[title="Speaker 1"]');
  await browser.clickCss('[data-speaker-review-workspace] button[aria-label="Manage this voice"], [data-speaker-review-workspace] button[aria-label="Gestisci questa voce"]');
  await browser.clickButton(['Merge voice', 'Unisci voce']);
  const secondTarget = await browser.execute(`
    const select = document.querySelector('[data-speaker-review-workspace] select');
    if (!select) return false;
    select.value = 'system:S2';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  `);
  if (!secondTarget) throw new Error('second merge target selection unavailable');
  await sleep(120);
  await browser.clickButton(['Confirm merge', 'Conferma unione']);
  await waitCount('speaker_merge', 2);
  await browser.clickButton(['Show merged and excluded voices', 'Mostra voci unite ed escluse']);
  await browser.clickCss('[data-speaker-merged-restore="system:S1"]');
  await waitCount('speaker_restore', 1);
  let restoredMergedVoice = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    restoredMergedVoice = await browser.execute(`
      return Boolean(document.querySelector('[data-speaker-lane="system:S1"]') &&
        document.querySelector('[data-speaker-lane="system:S2"]') &&
        !document.querySelector('[data-speaker-merged-restore="system:S1"]'));
    `);
    if (restoredMergedVoice) break;
    await sleep(100);
  }
  if (!restoredMergedVoice) throw new Error('restored merged voice did not regain its own lane');
  if (meetingFixture.transcription.text !== 'Decision: ship the release after validation. Owner: Alex.') {
    throw new Error('Restoring a merged voice changed the canonical transcript text');
  }
  await checkpoint(browser, '11d-speaker-review-restored');

  // Advanced engine controls stay reachable without dominating voice review.
  await browser.clickCss('[data-speaker-advanced-tools="true"] summary');
  await waitText(browser, ['Compare diarization engines', 'Confronta motori di diarizzazione']);
  await browser.clickButton(['Compare engines', 'Confronta motori']);
  await waitText(browser, ['Start comparison', 'Avvia confronto']);
  await checkpoint(browser, '11-comparison-opt-in');
  await browser.clickButton(['Start comparison', 'Avvia confronto']);
  await waitText(browser, ['Comparison finished', 'Confronto completato'], 20000, true);
  if (counts.benchmark_start !== 1 || counts.benchmark_poll < 2) {
    throw new Error(`benchmark request/poll mismatch: ${JSON.stringify(counts)}`);
  }
  await waitText(browser, ['FluidAudio Community-1']);
  await waitText(browser, ['Nemotron 3 · fast128']);
  await waitCount('benchmark_window', 1);
  await checkpoint(browser, '12-comparison-results');

  // Exercise a nonzero original-media range from the saved Meeting UI.
  const rangeReady = await browser.execute(`
    const label = Array.from(document.querySelectorAll('[data-diarization-benchmark] label'))
      .find((node) => (node.textContent || '').includes('Custom time range') ||
        (node.textContent || '').includes('Intervallo personalizzato'));
    if (!label) return false;
    label.querySelector('input[type="radio"]')?.click();
    return true;
  `);
  if (!rangeReady) throw new Error('range selector unavailable in speaker comparison');
  await sleep(150);
  const inputsReady = await browser.execute(`
    const from = document.querySelector('input[aria-label="Range start"], input[aria-label="Inizio intervallo"]');
    const to = document.querySelector('input[aria-label="Range end"], input[aria-label="Fine intervallo"]');
    if (!from || !to) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(from, '2:00'); from.dispatchEvent(new Event('input', { bubbles: true }));
    setter.call(to, '4:00'); to.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  if (!inputsReady) throw new Error('range inputs unavailable in speaker comparison');
  await sleep(100);
  await browser.clickButton(['Start comparison', 'Avvia confronto']);
  await waitCount('benchmark_start', 2);
  if (benchmarkRequest.scope !== 'range' || benchmarkRequest.start_seconds !== 120 ||
      benchmarkRequest.end_seconds !== 240) {
    throw new Error('range selection was not submitted with absolute meeting offsets');
  }
  await waitText(browser, ['Comparison finished', 'Confronto completato'], 20000, true);
  await waitCount('benchmark_window', 2);
  await checkpoint(browser, '13-comparison-range-and-window');

  // A completed full run must navigate beyond five minutes without rerunning AI.
  const fullSelected = await browser.execute(`
    const label = Array.from(document.querySelectorAll('[data-diarization-benchmark] label'))
      .find((node) => (node.textContent || '').includes('Full meeting') ||
        (node.textContent || '').includes('Meeting completo'));
    if (!label) return false;
    label.querySelector('input[type="radio"]')?.click();
    return true;
  `);
  if (!fullSelected) throw new Error('full-meeting comparison scope unavailable');
  await sleep(100);
  await browser.clickButton(['Start comparison', 'Avvia confronto']);
  await waitCount('benchmark_start', 3);
  await waitText(browser, ['Comparison finished', 'Confronto completato'], 20000, true);
  await waitCount('benchmark_window', 3);
  await browser.clickButton(['Next', 'Successiva']);
  // Wait for the request AND the rendered slider to land on 5:00.
  // An obsolete request from the prior scope can increment the shared
  // counter after Next; it must not be confused with completed navigation.
  await waitBenchmarkWindow(browser, 300, 4);
  await checkpoint(browser, '14-comparison-full-timeline-next');
  const canFindSpeaker = await browser.execute(`
    const button = document.querySelector('[data-benchmark-jump="B"]');
    return Boolean(button && button.getAttribute('aria-label')?.includes('7:30'));
  `);
  if (!canFindSpeaker) throw new Error('whole-meeting speaker locator missing for off-window cluster');
  // After Next, the window is 5:00–10:00: A is absent there.
  await browser.clickCss('[data-benchmark-jump="A"]');
  await waitBenchmarkWindow(browser, 0, 5);
  // The HTTP fixture counter increments before React renders the next
  // window. Wait for the actual UI control, not merely the response request.
  let speakerReady = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    speakerReady = await browser.execute(`
      const button = document.querySelector('[data-benchmark-jump="B"]');
      const label = button?.getAttribute('aria-label') || '';
      return label.includes('not in this window') || label.includes('non presente qui');
    `);
    if (speakerReady) break;
    await sleep(100);
  }
  if (!speakerReady) throw new Error('speaker jump control did not reappear after changing windows');
  // B is now absent from the first five minutes.
  await browser.clickCss('[data-benchmark-jump="B"]');
  await waitBenchmarkWindow(browser, 300, 6);
  await checkpoint(browser, '15-comparison-locate-speaker');

  // Review may only start from an explicit user action. The synthetic
  // result must show attribution changes before a separate Apply confirmation.
  if (counts.review_start || counts.review_apply) {
    throw new Error('speaker review or apply ran without user consent');
  }
  await browser.clickButton(['Choose engine', 'Scegli motore']);
  await waitText(browser, ['Calculate preview', 'Calcola anteprima']);
  await browser.clickButton(['Calculate preview', 'Calcola anteprima']);
  await waitCount('review_start', 1);
  await waitCount('review_preview', 1);
  await waitText(browser, ['Preview ready', 'Anteprima pronta'], 20000, true);
  if (counts.review_apply !== 0) throw new Error('review applied without confirmation');
  await checkpoint(browser, '16-community-review-preview');
  await browser.clickButton(['Confirm and apply to transcript', 'Conferma e applica alla trascrizione']);
  await waitCount('review_apply', 1);
  await waitText(browser, ['Restore previous speakers', 'Ripristina speaker precedenti'], 5000, true);
  await checkpoint(browser, '17-community-review-applied');
  await browser.clickButton(['Restore previous speakers', 'Ripristina speaker precedenti']);
  await waitCount('review_undo', 1);
  await checkpoint(browser, '18-community-review-undo');

  // Canonical Meeting retains metadata edits formerly isolated in the legacy Recording detail.
  if (counts.metadata_title || counts.metadata_project || counts.metadata_projects_list) {
    throw new Error('saved Meeting fetched or mutated metadata before an explicit edit');
  }
  await browser.clickCss('[data-meeting-rename="true"]');
  const titleInput = await browser.execute(`
    const input = document.querySelector('[data-meeting-title-input="true"]');
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, 'Quarterly launch review revised');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  if (!titleInput) throw new Error('saved Meeting title editor not available');
  failNextMetadataUpdate = true;
  await browser.clickCss('form:has([data-meeting-title-input="true"]) button[type="submit"]');
  await waitText(browser, ['synthetic metadata outage'], 5000, true);
  const retained = await browser.execute(`
    return document.querySelector('[data-meeting-title-input="true"]')?.value === 'Quarterly launch review revised';
  `);
  if (!retained) throw new Error('metadata error discarded title edit');
  await browser.clickCss('form:has([data-meeting-title-input="true"]) button[type="submit"]');
  await waitCount('metadata_title', 1);
  await waitText(browser, ['Quarterly launch review revised'], 5000, true);

  await browser.clickCss('[data-meeting-project-edit="true"]');
  await waitCount('metadata_projects_list', 1);
  const projectInput = await browser.execute(`
    const input = document.querySelector('div.fixed.inset-0.z-50 form input');
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, 'User Success');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  if (!projectInput) throw new Error('saved Meeting project editor not available');
  await browser.clickCss('div.fixed.inset-0.z-50 form button[type="submit"]');
  await waitCount('metadata_project', 1);
  let projectShown = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    projectShown = await browser.execute(`
      const edit = document.querySelector('[data-meeting-project-edit="true"]');
      return Boolean(edit?.textContent?.includes('User Success') &&
        !document.querySelector('div.fixed.inset-0.z-50 form'));
    `);
    if (projectShown) break;
    await sleep(100);
  }
  if (!projectShown || meetingFixture.project_name !== 'User Success') {
    throw new Error('saved Meeting project update failed to render persistent metadata');
  }
  await checkpoint(browser, '19-metadata-edit');

  // Previously generated notes remain intact; a changed speaker assignment
  // is disclosed in the canonical Meeting analysis view without auto-regeneration.
  meetingFixture.latest_analysis = { meeting_brief: {
    id: 'e2e-before-speaker-correction', analysis_type: 'meeting_brief',
    status: 'completed', result: { markdown: 'Old notes preserved for manual review.' },
    speaker_source_validity: { status: 'stale', reason: 'speaker_attribution_changed' },
  } };
  meetingFixture.analysis_runs = [meetingFixture.latest_analysis.meeting_brief];
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitText(browser, ['Alternate pricing review'], 5000, true);
  await setMeetingHash(MEETING_ID);
  await waitText(browser, ['Quarterly launch review revised'], 5000, true);
  await browser.clickCss('#meeting-tab-analysis');
  await waitText(browser, ['Review speakers in these notes', 'Verifica gli speaker nelle note'], 5000, true);
  const speakerProvenanceWarning = await browser.execute(`
    const notice = document.querySelector('[data-speaker-analysis-source-warning="true"]');
    const text = notice?.textContent || '';
    return Boolean(notice && notice.getAttribute('role') === 'status' &&
      (text.includes('Rigenera solo analisi') || text.includes('Regenerate analysis only')) &&
      document.body.innerText.includes('Old notes preserved for manual review.'));
  `);
  if (!speakerProvenanceWarning) {
    throw new Error('Stale speaker-attributed notes must show a review notice without rewriting content');
  }
  await checkpoint(browser, '20-stale-speaker-analysis');

  // Long/legacy speaker evidence: 5,005 synthetic turns, bounded pagination
  // and search beyond page 200, and a source-only "Computer" that is not a
  // detected person. This must not start AI, fetch clips or mutate transcript.
  const audioRequestsBeforeLongRead = counts.speaker_audio_request;
  const benchmarkRequestsBeforeLongRead = counts.benchmark_start;
  meetingFixture.latest_analysis = {};
  meetingFixture.analysis_runs = [];
  meetingFixture.recording.duration_seconds = 7800;
  meetingFixture.recording.stopped_at = '2026-09-05T12:10:00Z';
  meetingFixture.transcription.text = 'Synthetic 5,005-turn meeting; original audio not required for transcript reading.';
  meetingFixture.transcription.segments = Array.from({ length: 5005 }, (_, index) => ({
    id: index, start: index * 1.5, end: index * 1.5 + 1.2,
    text: `needle-${index}: synthetic local transcript segment.`,
    track_id: 'system', source: 'system',
    ...(index === 0
      ? { speaker_label: 'Computer' }
      : { provider_speaker: 'system:S1', speaker_group: 'system:S1',
          speaker_label: 'Speaker 1', speaker_name: 'Speaker 1' }),
    overlap: index === 2,
  }));
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitText(browser, ['Alternate pricing review'], 5000, true);
  await setMeetingHash(MEETING_ID);
  await waitText(browser, ['Quarterly launch review revised'], 5000, true);
  await browser.clickCss('#meeting-tab-transcript');
  let longFirstPage = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    longFirstPage = await browser.execute(`
      const root = document.querySelector('#meeting-panel-transcript');
      const content = root?.textContent || '';
      return Boolean(root &&
        root.querySelector('[data-transcript-segment-id="0"]') &&
        root.querySelector('[data-transcript-segment-id="24"]') &&
        !root.querySelector('[data-transcript-segment-id="25"]') &&
        root.querySelectorAll('[data-transcript-turn="conversation"]').length >= 3 &&
        (content.includes('Audio non attribuito') || content.includes('Unattributed audio')) &&
        !root.querySelector('button[aria-pressed="true"]')?.textContent?.includes('Dettagli'));
    `);
    if (longFirstPage) break;
    await sleep(100);
  }
  if (!longFirstPage) {
    throw new Error('long Meeting must show bounded conversation and mark legacy Computer as an audio source');
  }
  const jumpToLast = await browser.execute(`
    const root = document.querySelector('#meeting-panel-transcript');
    const button = [...(root?.querySelectorAll('button') || [])]
      .find((item) => item.textContent.trim() === '201');
    if (!button) return false;
    button.click();
    return true;
  `);
  if (!jumpToLast) throw new Error('last page of 5,005-segment transcript not reachable');
  let lastPage = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    lastPage = await browser.execute(`
      const root = document.querySelector('#meeting-panel-transcript');
      return Boolean(root &&
        root.querySelector('[data-transcript-segment-id="5004"]') &&
        !root.querySelector('[data-transcript-segment-id="4974"]') &&
        root.querySelectorAll('[data-transcript-segment-id]').length === 5);
    `);
    if (lastPage) break;
    await sleep(100);
  }
  if (!lastPage) throw new Error('last page does not restrict the DOM to its five ASR turns');
  const searched = await browser.execute(`
    const input = document.querySelector('#meeting-panel-transcript input[placeholder="Cerca nel testo..."]');
    if (!input) return false;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    set.call(input, 'needle-4990');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  if (!searched) throw new Error('search field missing in very long transcript');
  let matchingSearch = false;
  for (let attempt = 0; attempt < 35; attempt += 1) {
    matchingSearch = await browser.execute(`
      const root = document.querySelector('#meeting-panel-transcript');
      const counter = [...(root?.querySelectorAll('span') || [])]
        .find((item) => item.textContent.trim() === '1/1');
      const next = counter?.parentElement?.querySelectorAll('button')[1];
      if (!next) return false;
      next.click();
      return true;
    `);
    if (matchingSearch) break;
    await sleep(100);
  }
  if (!matchingSearch) throw new Error('search result navigator not reachable across 201 pages');
  let searchedPage = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    searchedPage = await browser.execute(`
      const root = document.querySelector('#meeting-panel-transcript');
      return Boolean(root?.querySelector('[data-transcript-segment-id="4990"]') &&
        !root.querySelector('[data-transcript-segment-id="5004"]') &&
        root.querySelectorAll('[data-transcript-segment-id]').length <= 25);
    `);
    if (searchedPage) break;
    await sleep(100);
  }
  if (!searchedPage) throw new Error('search did not reveal matching segment on page 200');
  if (counts.speaker_audio_request !== audioRequestsBeforeLongRead ||
      counts.benchmark_start !== benchmarkRequestsBeforeLongRead) {
    throw new Error('reading a long transcript triggered unrequested audio or inference');
  }
  await checkpoint(browser, '21-long-legacy-conversation-5005');

  // Historical imports may retain the complete raw transcript but no ASR
  // segmentation. Reading must preserve the text, without creating imaginary
  // speaker turns, timestamp buttons, or an implicit analysis/audio request.
  const audioRequestsBeforeEmptyRead = counts.speaker_audio_request;
  const benchmarkRequestsBeforeEmptyRead = counts.benchmark_start;
  const legacyPlainText = 'Historical imported transcript: original words are still available without ASR segments.';
  meetingFixture.transcription.segments = [];
  meetingFixture.transcription.text = legacyPlainText;
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitText(browser, ['Alternate pricing review'], 5000, true);
  await setMeetingHash(MEETING_ID);
  await waitText(browser, ['Quarterly launch review revised'], 5000, true);
  await browser.clickCss('#meeting-tab-transcript');
  await waitText(browser, [legacyPlainText], 5000, true);
  const plainTextOnly = await browser.execute(`
    const panel = document.querySelector('#meeting-panel-transcript');
    return Boolean(panel &&
      panel.textContent.includes(${JSON.stringify(legacyPlainText)}) &&
      !panel.querySelector('[data-transcript-turn]') &&
      !panel.querySelector('[data-transcript-segment-id]') &&
      !panel.querySelector('[data-turn-correction-open]'));
  `);
  if (!plainTextOnly) throw new Error('legacy raw text without ASR segments was hidden or given invented speaker turns');
  await checkpoint(browser, '22-legacy-import-plain-text-without-segments');

  // A genuinely empty transcription is different from an imported text-only
  // transcript: show a truthful empty state, not the last long meeting page.
  meetingFixture.transcription.text = '';
  await setMeetingHash(ALTERNATE_MEETING_ID);
  await waitText(browser, ['Alternate pricing review'], 5000, true);
  await setMeetingHash(MEETING_ID);
  await waitText(browser, ['Quarterly launch review revised'], 5000, true);
  await browser.clickCss('#meeting-tab-transcript');
  await waitText(browser, [
    'Qui troverai il testo della chiamata',
    'Your call transcript will appear here',
  ], 5000, true);
  const zeroSegmentsEmpty = await browser.execute(`
    const panel = document.querySelector('#meeting-panel-transcript');
    const text = panel?.textContent || '';
    return Boolean(panel &&
      (text.includes('Qui troverai il testo della chiamata') ||
       text.includes('Your call transcript will appear here')) &&
      !text.includes('needle-5004') &&
      !panel.querySelector('[data-transcript-turn]') &&
      !panel.querySelector('[data-transcript-segment-id]'));
  `);
  if (!zeroSegmentsEmpty) throw new Error('empty legacy meeting showed stale transcript or invented speaker labels');
  if (counts.speaker_audio_request !== audioRequestsBeforeEmptyRead ||
      counts.benchmark_start !== benchmarkRequestsBeforeEmptyRead) {
    throw new Error('reading text-only/empty legacy transcript triggered audio or inference');
  }
  await checkpoint(browser, '23-empty-transcript-no-invented-turns');

  video = await renderVideo();
} catch (caught) {
  error = `${caught?.name || 'Error'}: ${caught?.message || caught}`;
  if (browser) {
    try { await checkpoint(browser, '99-failure', 1); } catch {}
  }
} finally {
  while (heldMeetingResponses.length) heldMeetingResponses.shift()('error');
  if (browser) await browser.close();
  await stop(driver);
  await stop(vite);
  await new Promise((resolve) => server.close(resolve));
  fs.closeSync(viteLog);
  fs.closeSync(driverLog);
}

const manifest = {
  schema_version: 1,
  journey_id: 'saved-meeting-fast-open',
  execution_environment: 'browser-macos-arm64-ci',
  fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision,
  result: error ? 'FAIL' : 'PASS',
  requests: counts,
  checkpoints,
  video,
  privacy_boundary: 'Synthetic fixture content only; captures are restricted to the headless Chrome viewport.',
  residual_fidelity_gaps: [
    'does not exercise the packaged WKWebView process boundary',
    'does not prove TCC/native capture or physical audio-device behavior',
    'does not prove production MLX/Metal inference behavior',
  ],
  error,
};
await fsp.writeFile(
  path.join(evidenceRoot, 'manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
