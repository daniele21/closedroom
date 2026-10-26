#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

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
  alternate_visual_context: 0,
  benchmark_list: 0, benchmark_start: 0, benchmark_poll: 0, benchmark_window: 0,
  review_list: 0, review_start: 0, review_poll: 0, review_preview: 0,
  review_apply: 0, review_undo: 0,
};
let benchmarkJob = null;
let benchmarkRequest = null;
let communityReviewJob = null;
let communityReviewApplied = false;
let lastBenchmarkWindowStart = null;
let failNextAlternateScreenshots = false;
let failNextAlternateNotes = false;
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

async function waitCount(key, minimum, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (counts[key] >= minimum) return;
    await sleep(50);
  }
  throw new Error(`timed out waiting for ${key} >= ${minimum}; counts=${JSON.stringify(counts)}`);
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
  if (counts.diagnostics !== 0 || counts.visual_frames !== 0) {
    throw new Error(`normal open fetched disclosure-driven accessories: ${JSON.stringify(counts)}`);
  }
  await waitCount('screenshots', 1);
  await checkpoint(browser, '01-ready-core-only');

  await browser.clickButton(['Details', 'Dettagli']);
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


  // Comparison is an explicit advanced action on a saved meeting. It must
  // not run during the normal read/analysis flows, or mutate transcript text.
  if (counts.benchmark_start !== 0) {
    throw new Error('meeting speaker comparison started without user consent');
  }
  await setMeetingHash(MEETING_ID);
  await expectCurrentMeeting('Quarterly launch review', 'Alternate pricing review', alternateMeetingFixture.transcription.text);
  await browser.clickCss('#meeting-tab-speakers');
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
  await waitCount('benchmark_window', 4);
  if (lastBenchmarkWindowStart < 300) {
    throw new Error('full-meeting navigation did not fetch a window beyond minute five');
  }
  await checkpoint(browser, '14-comparison-full-timeline-next');
  const canFindSpeaker = await browser.execute(`
    const button = document.querySelector('[data-benchmark-jump="B"]');
    return Boolean(button && button.getAttribute('aria-label')?.includes('7:30'));
  `);
  if (!canFindSpeaker) throw new Error('whole-meeting speaker locator missing for off-window cluster');
  // After Next, the window is 5:00–10:00: A is absent there.
  await browser.clickCss('[data-benchmark-jump="A"]');
  await waitCount('benchmark_window', 5);
  if (lastBenchmarkWindowStart !== 0) throw new Error('speaker locator did not return to first occurrence');
  // B is now absent from the first five minutes.
  await browser.clickCss('[data-benchmark-jump="B"]');
  await waitCount('benchmark_window', 6);
  if (lastBenchmarkWindowStart < 300) throw new Error('speaker locator did not find the later cluster');
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
