#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf';
const MEETING_ID = 'e2e-prepare-meeting';
const VIDEO_FPS = 4;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_PREPARATION_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-preparation'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';

const transcriptFixture = {
  id: 'e2e-preparation-transcription',
  timestamp: '2026-09-05T17:00:05Z',
  model: 'synthetic-fixture',
  language: 'en',
  audio_filename: 'synthetic.wav',
  recording_id: MEETING_ID,
  text: 'Transcript ready before notes. Decision: validate the release. Owner: Alex.',
  segments: [{
    id: 0,
    start: 0,
    end: 4.2,
    text: 'Transcript ready before notes. Decision: validate the release. Owner: Alex.',
    speaker_label: 'SPEAKER_00',
  }],
  stats: { outcome_status: 'completed', speaker_diarization: { status: 'disabled' } },
};

function analysisRun(type, markdown, index) {
  return {
    id: `analysis-run-${index}`,
    job_id: `analysis-job-${index}`,
    scope_type: 'transcription',
    scope_id: transcriptFixture.id,
    transcription_id: transcriptFixture.id,
    recording_id: MEETING_ID,
    analysis_type: type,
    template_id: type,
    template_version: 'v1',
    pipeline_run_id: 'pipeline-resumed',
    provider: 'mock',
    model: '',
    reasoning: 'auto',
    show_thinking: false,
    json_mode: true,
    prompt_version: `${type}_v1`,
    input_hash: 'synthetic-input',
    status: 'completed',
    result_markdown: markdown,
    source_ids: [MEETING_ID, transcriptFixture.id],
    created_at: 1788627600 + index,
    completed_at: 1788627610 + index,
  };
}

const completedRuns = [
  analysisRun('meeting_brief', '# Meeting brief\nRelease validation is the key decision.', 1),
  analysisRun('action_items', '# Actions\nAlex validates the release.', 2),
  analysisRun('decisions', '# Decisions\nValidate before shipping.', 3),
  analysisRun('risks_blockers', '# Risks\nValidation remains the blocker.', 4),
];

const state = {
  transcription: null,
  analysis_runs: [],
  latest_analysis: {},
  jobs: [],
  status: 'recorded',
};

const counts = {
  session: 0,
  health: 0,
  meeting: 0,
  prepare: 0,
  parent_events_first: 0,
  parent_events_resume: 0,
  asr_runs: 0,
  analysis_attempts: 0,
};
const checkpoints = [];
let frameIndex = 0;
let firstParentConnectionCount = 0;

function parentJob(id, status, currentStep, progress, error = null) {
  return {
    id,
    type: 'meeting_preparation',
    scope_type: 'recording',
    scope_id: MEETING_ID,
    recording_id: MEETING_ID,
    status,
    current_step: currentStep,
    progress,
    error,
    result: null,
    created_at: 1788627600,
    updated_at: 1788627600,
  };
}

function meetingFixture() {
  return {
    id: MEETING_ID,
    recording: {
      id: MEETING_ID,
      title: 'Prepare notes reconnect review',
      project_name: 'Browser E2E',
      status: 'completed',
      mime_type: 'audio/wav',
      audio_file: 'synthetic.wav',
      bytes_written: 524288,
      created_at: '2026-09-05T17:00:00Z',
      stopped_at: '2026-09-05T17:00:00Z',
      duration_seconds: 600,
    },
    transcription: state.transcription,
    analysis_runs: state.analysis_runs,
    latest_analysis: state.latest_analysis,
    jobs: state.jobs,
    status: state.status,
    project_name: 'Browser E2E',
    created_at: '2026-09-05T17:00:00Z',
    updated_at: '2026-09-05T17:00:05Z',
  };
}

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

function sseHeaders(res) {
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-store',
    connection: 'keep-alive',
  });
  res.flushHeaders?.();
}

function sse(res, snapshot, sequence) {
  res.write(`data: ${JSON.stringify({ ...snapshot, sequence })}\n\n`);
}

function replaceParent(snapshot) {
  const history = state.jobs.filter((job) => job.type !== 'meeting_preparation' || job.id !== snapshot.id);
  state.jobs = [snapshot, ...history];
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
        server: 'preparation-browser-fixture',
        backend: 'synthetic',
        default_model: 'synthetic/model',
        status: 'idle',
        endpoints: [],
        recordings: true,
      });
    }
    if (pathname === `/v1/meetings/${MEETING_ID}` && req.method === 'GET') {
      counts.meeting += 1;
      return json(res, 200, meetingFixture());
    }
    if (pathname === `/v1/meetings/${MEETING_ID}/prepare` && req.method === 'POST') {
      counts.prepare += 1;
      if (counts.prepare === 1) {
        counts.asr_runs += 1;
        counts.analysis_attempts += 1;
        const parent = parentJob('prepare-parent-1', 'running', 'preparing_transcript', 5);
        state.status = 'recorded';
        replaceParent(parent);
        return json(res, 202, parent);
      }
      if (counts.prepare === 2) {
        counts.analysis_attempts += 1;
        const parent = parentJob('prepare-parent-2', 'running', 'preparing_notes', 60);
        state.status = 'transcribed';
        replaceParent(parent);
        return json(res, 202, parent);
      }
      const current = state.jobs.find((job) => job.id === 'prepare-parent-2') || state.jobs[0];
      return json(res, 202, { ...current, deduplicated: true });
    }
    if (pathname === '/v1/jobs/prepare-parent-1/events') {
      counts.parent_events_first += 1;
      firstParentConnectionCount += 1;
      sseHeaders(res);
      const current = state.jobs.find((job) => job.id === 'prepare-parent-1')
        || parentJob('prepare-parent-1', 'running', 'preparing_transcript', 5);
      sse(res, current, 1);
      if (firstParentConnectionCount === 1) {
        await sleep(450);
        if (res.destroyed) return;
        state.transcription = transcriptFixture;
        state.status = 'transcribed';
        const notesParent = parentJob('prepare-parent-1', 'running', 'preparing_notes', 60);
        replaceParent(notesParent);
        sse(res, notesParent, 2);
        return;
      }
      await sleep(650);
      if (res.destroyed) return;
      const failed = parentJob(
        'prepare-parent-1',
        'failed',
        'preparation_failed',
        60,
        'Synthetic notes model failure after transcript persistence',
      );
      replaceParent(failed);
      state.status = 'transcribed';
      sse(res, failed, 3);
      res.end();
      return;
    }
    if (pathname === '/v1/jobs/prepare-parent-2/events') {
      counts.parent_events_resume += 1;
      sseHeaders(res);
      const current = state.jobs.find((job) => job.id === 'prepare-parent-2')
        || parentJob('prepare-parent-2', 'running', 'preparing_notes', 60);
      sse(res, current, 1);
      await sleep(650);
      if (res.destroyed) return;
      state.analysis_runs = completedRuns;
      state.latest_analysis = Object.fromEntries(completedRuns.map((run) => [run.analysis_type, run]));
      state.status = 'ready';
      const completed = parentJob('prepare-parent-2', 'completed', 'completed', 100);
      replaceParent(completed);
      sse(res, completed, 2);
      res.end();
      return;
    }
    if (pathname === '/v1/jobs/prepare-parent-1' && req.method === 'GET') {
      const job = state.jobs.find((item) => item.id === 'prepare-parent-1');
      return job ? json(res, 200, job) : json(res, 404, { detail: 'Job not found' });
    }
    if (pathname === '/v1/jobs/prepare-parent-2' && req.method === 'GET') {
      const job = state.jobs.find((item) => item.id === 'prepare-parent-2');
      return job ? json(res, 200, job) : json(res, 404, { detail: 'Job not found' });
    }
    return json(res, 404, { detail: `fixture route not found: ${req.method} ${pathname}` });
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

  async refresh() {
    await webdriver(this.port, 'POST', this.p('/refresh'), {});
  }

  async execute(script) {
    return await webdriver(this.port, 'POST', this.p('/execute/sync'), { script, args: [] });
  }

  async text() {
    return String(await this.execute("return document.body ? document.body.innerText : '';"));
  }

  async clickButton(labels) {
    const clicked = await this.execute(`
      const labels = ${JSON.stringify(labels)};
      const button = Array.from(document.querySelectorAll('button')).find((candidate) => {
        const text = (candidate.innerText || candidate.textContent || '').trim();
        return labels.some((label) => text === label || text.includes(label));
      });
      if (!button || button.disabled) return false;
      button.click();
      return true;
    `);
    if (clicked !== true) throw new Error(`enabled button not found: ${labels.join(', ')}`);
  }

  async attr(selector, name) {
    return await this.execute(`
      const element = document.querySelector(${JSON.stringify(selector)});
      return element ? element.getAttribute(${JSON.stringify(name)}) : null;
    `);
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
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${needles.join(' | ')}; text=${last.slice(0, 1200)}`);
}

async function waitCount(key, minimum, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (counts[key] >= minimum) return;
    await sleep(50);
  }
  throw new Error(`timed out waiting for ${key} >= ${minimum}; counts=${JSON.stringify(counts)}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'prepare-notes.mp4');
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
  if (!stat.size) throw new Error('prepare-notes video is empty');
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
  const meetingUrl = `http://127.0.0.1:${vitePort}/#meeting/${MEETING_ID}`;
  await browser.navigate(meetingUrl);
  await waitText(browser, ['Prepare notes reconnect review'], 30000, true);
  await waitText(browser, ['Prepare notes', 'Prepara note']);
  await waitText(browser, ['Transcript only', 'Solo trascrizione']);
  await checkpoint(browser, '01-primary-action');

  await browser.clickButton(['Prepare notes', 'Prepara note']);
  await waitCount('prepare', 1);
  await waitText(
    browser,
    [
      'Preparing transcript',
      'Preparazione trascrizione',
      'Preparing notes',
      'Preparazione note',
      'Transcript ready · preparing notes',
      'Trascrizione pronta · preparazione note',
    ],
    5000,
    true,
  );
  await checkpoint(browser, '02-preparation-in-progress');

  await waitText(browser, ['Transcript ready before notes.'], 5000, true);
  await waitText(browser, ['Transcript ready · preparing notes', 'Trascrizione pronta · preparazione note']);
  if (counts.asr_runs !== 1 || counts.analysis_attempts !== 1) {
    throw new Error(`unexpected first-attempt work counts: ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '03-transcript-readable-notes-running');

  // Reload the same Meeting while the durable parent is still active. The new
  // document must reconstruct progress from persisted Meeting/job state and
  // attach to the same parent instead of starting new work.
  await browser.refresh();
  await waitText(browser, ['Transcript ready before notes.'], 5000, true);
  await waitText(browser, ['Transcript ready · preparing notes', 'Trascrizione pronta · preparazione note']);
  await waitCount('parent_events_first', 2);
  if (counts.prepare !== 1 || counts.asr_runs !== 1) {
    throw new Error(`reconnect duplicated preparation: ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '04-reconnected-same-parent');

  await waitText(browser, ['Resume preparation', 'Riprendi la preparazione'], 5000, true);
  await waitText(browser, ['Synthetic notes model failure'], 5000);
  await waitText(browser, ['Transcript ready before notes.']);
  await checkpoint(browser, '05-notes-failed-transcript-preserved');

  await browser.clickButton(['Resume', 'Riprendi']);
  await waitCount('prepare', 2);
  await waitText(browser, ['Transcript ready · preparing notes', 'Trascrizione pronta · preparazione note'], 5000, true);
  if (counts.asr_runs !== 1 || counts.analysis_attempts !== 2) {
    throw new Error(`resume reran ASR or missed analysis retry: ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '06-resume-notes-only');

  await waitText(browser, ['Release validation is the key decision.'], 7000, true);
  const analysisSelected = await browser.attr('#meeting-tab-analysis', 'aria-selected');
  if (analysisSelected !== 'true') {
    throw new Error(`notes did not open first after completion: aria-selected=${analysisSelected}`);
  }
  if (counts.prepare !== 2 || counts.asr_runs !== 1 || counts.analysis_attempts !== 2) {
    throw new Error(`unexpected final work counts: ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '07-notes-ready-default-view');
  video = await renderVideo();
} catch (caught) {
  error = `${caught?.name || 'Error'}: ${caught?.message || caught}`;
  if (browser) {
    try { await checkpoint(browser, '99-failure', 1); } catch {}
  }
} finally {
  if (browser) await browser.close();
  await stop(driver);
  await stop(vite);
  await new Promise((resolve) => server.close(resolve));
  fs.closeSync(viteLog);
  fs.closeSync(driverLog);
}

const manifest = {
  schema_version: 1,
  journey_id: 'meeting-preparation',
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
    'does not prove production ASR/LLM quality, latency, memory or Metal behavior',
  ],
  error,
};
await fsp.writeFile(
  path.join(evidenceRoot, 'manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
