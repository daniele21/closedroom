#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const VIDEO_FPS = 4;
const RECORDING_ID = 'record-while-ai-busy-e2e';
const RESERVATION_ID = 'capture-reservation-e2e';
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_RECORD_WHILE_AI_BUSY_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-ui/record-while-ai-busy'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';
const checkpoints = [];
const counts = {
  session: 0,
  health: 0,
  reservationCreate: 0,
  reservationPoll: 0,
  reservationRelease: 0,
  createRecording: 0,
  startCapture: 0,
  stopCapture: 0,
  detail: 0,
};
let frameIndex = 0;
let aiBusy = true;
let captureStarted = false;
let captureStopped = false;
let reservationActive = false;
let aiResumed = false;

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

function empty(res, status = 204) {
  res.writeHead(status, { 'cache-control': 'no-store' });
  res.end();
}

function recording(status = 'recording') {
  const stopped = status !== 'recording';
  return {
    id: RECORDING_ID,
    title: 'Busy AI capture proof',
    project_name: '',
    status,
    error: null,
    partial: false,
    capture_backend: 'native',
    capture_status: stopped ? 'stopped' : 'recording',
    quality_report: null,
    warnings: [],
    mime_type: 'audio/wav',
    audio_file: stopped ? 'synthetic.wav' : null,
    capture_mode: 'both',
    primary_track_id: 'mixed',
    audio_tracks: [],
    bytes_written: stopped ? 4096 : 0,
    created_at: '2026-09-06T12:00:00Z',
    stopped_at: stopped ? '2026-09-06T12:02:00Z' : null,
    duration_seconds: stopped ? 120 : null,
  };
}

function meeting() {
  return {
    id: RECORDING_ID,
    recording: recording('recorded'),
    transcription: null,
    analysis_runs: [],
    latest_analysis: {},
    jobs: [],
    status: 'recorded',
    project_name: '',
    created_at: '2026-09-06T12:00:00Z',
    updated_at: '2026-09-06T12:02:00Z',
  };
}

function fixtureServer(port) {
  return http.createServer((req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);

    if (url.pathname === '/__e2e/finish-ai' && req.method === 'POST') {
      aiBusy = false;
      return json(res, 200, { ok: true });
    }
    if (url.pathname === '/__e2e/state') {
      return json(res, 200, {
        aiBusy,
        captureStarted,
        captureStopped,
        reservationActive,
        aiResumed,
        counts,
      });
    }
    if (url.pathname === '/v1/session') {
      counts.session += 1;
      return json(res, 200, { auth_enabled: false, token: null });
    }
    if (url.pathname === '/health') {
      counts.health += 1;
      return json(res, 200, {
        ok: true,
        server: 'browser-fixture',
        backend: 'synthetic',
        default_model: 'synthetic/model',
        status: captureStarted && !captureStopped ? 'recording' : 'idle',
        endpoints: [],
        recordings: true,
      });
    }
    if (url.pathname === '/v1/settings' && req.method === 'GET') {
      return json(res, 200, { recordings_dir: '/tmp/closedroom-e2e' });
    }
    if (url.pathname === '/v1/projects' && req.method === 'GET') {
      return json(res, 200, { items: [] });
    }
    if (url.pathname === '/v1/system/audio/status' && req.method === 'GET') {
      return json(res, 200, {
        ready_to_record: true,
        routing_active: false,
        auto_routing: true,
        physical_output: 'Synthetic Output',
        missing: [],
      });
    }
    if (url.pathname === '/v1/capture/capabilities' && req.method === 'GET') {
      return json(res, 200, {
        default_backend: 'native',
        native: {
          available: true,
          backend: 'native',
          modes: ['both', 'mic_only', 'pc_only'],
          minimum_macos: '14',
        },
        fallbacks: ['browser_blackhole'],
      });
    }
    if (url.pathname === '/v1/capture/permissions' && req.method === 'GET') {
      return json(res, 200, {
        ok: true,
        microphone: 'authorized',
        screen_capture: 'granted',
        modes: {
          mic_only: { ok: true },
          pc_only: { ok: true },
          both: { ok: true },
        },
      });
    }
    if (url.pathname === '/v1/capture/ensure-permissions' && req.method === 'POST') {
      return json(res, 200, {
        ok: true,
        requested: false,
        permissions: {
          ok: true,
          microphone: 'authorized',
          screen_capture: 'granted',
          modes: {
            mic_only: { ok: true },
            pc_only: { ok: true },
            both: { ok: true },
          },
        },
        diagnostics: {
          bundle_identifier: 'com.closedroom.nativecapture',
          code_signature: 'signed',
          identifier: 'com.closedroom.nativecapture',
        },
      });
    }
    if (url.pathname === '/v1/capture/reservations' && req.method === 'POST') {
      counts.reservationCreate += 1;
      if (reservationActive) return json(res, 409, { detail: 'another capture reservation is already active' });
      reservationActive = true;
      return json(res, 202, {
        reservation_id: RESERVATION_ID,
        status: aiBusy ? 'waiting' : 'granted',
        active_workloads: aiBusy ? 1 : 0,
        queued_workloads: 1,
        waited_seconds: 0,
      });
    }
    if (url.pathname === `/v1/capture/reservations/${RESERVATION_ID}` && req.method === 'GET') {
      counts.reservationPoll += 1;
      if (!reservationActive) return json(res, 404, { detail: 'capture reservation is not active' });
      return json(res, 200, {
        reservation_id: RESERVATION_ID,
        status: aiBusy ? 'waiting' : 'granted',
        active_workloads: aiBusy ? 1 : 0,
        queued_workloads: 1,
        waited_seconds: Math.max(0.2, counts.reservationPoll * 0.2),
      });
    }
    if (
      url.pathname === `/v1/capture/reservations/${RESERVATION_ID}`
      && req.method === 'DELETE'
    ) {
      counts.reservationRelease += 1;
      if (!reservationActive) return json(res, 404, { detail: 'capture reservation is not active' });
      reservationActive = false;
      aiResumed = true;
      return empty(res);
    }
    if (
      url.pathname === `/v1/capture/reservations/${RESERVATION_ID}/release`
      && req.method === 'POST'
    ) {
      counts.reservationRelease += 1;
      reservationActive = false;
      aiResumed = true;
      return empty(res);
    }
    if (url.pathname === '/v1/recordings' && req.method === 'POST') {
      counts.createRecording += 1;
      return json(res, 201, recording('recording'));
    }
    if (url.pathname === `/v1/recordings/${RECORDING_ID}/capture/start` && req.method === 'POST') {
      counts.startCapture += 1;
      if (aiBusy) return json(res, 409, { detail: 'capture started before AI reservation was granted' });
      captureStarted = true;
      captureStopped = false;
      return json(res, 202, {
        recording_id: RECORDING_ID,
        backend: 'native',
        mode: 'both',
        status: 'starting',
      });
    }
    if (url.pathname === `/v1/recordings/${RECORDING_ID}/capture/events` && req.method === 'GET') {
      res.writeHead(200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      });
      setTimeout(() => {
        if (!res.destroyed) res.write(`data: ${JSON.stringify({ type: 'ready' })}\n\n`);
      }, 120);
      return;
    }
    if (url.pathname === `/v1/recordings/${RECORDING_ID}/capture/stop` && req.method === 'POST') {
      counts.stopCapture += 1;
      captureStopped = true;
      return json(res, 202, {
        capture: { recording_id: RECORDING_ID, backend: 'native', status: 'stopped', events: [] },
        recording: recording('recorded'),
      });
    }
    if (url.pathname === `/v1/recordings/${RECORDING_ID}/capture/cancel` && req.method === 'POST') {
      captureStopped = true;
      return json(res, 202, { recording_id: RECORDING_ID, backend: 'native', status: 'cancelled' });
    }
    if (url.pathname === '/v1/system/window/overlay' && req.method === 'POST') {
      return json(res, 200, { success: true });
    }
    if (url.pathname === `/v1/meetings/${RECORDING_ID}` && req.method === 'GET') {
      counts.detail += 1;
      return json(res, 200, meeting());
    }
    if (url.pathname === `/v1/meetings/${RECORDING_ID}/diagnostics` && req.method === 'GET') {
      return json(res, 200, {
        recording_id: RECORDING_ID,
        outcome_status: 'recorded',
        diagnostics: [],
        jobs: [],
        events: [],
        artifacts: {},
        log_lines: [],
      });
    }
    if (url.pathname === `/v1/recordings/${RECORDING_ID}/visual-frames` && req.method === 'GET') {
      return json(res, 200, { items: [], total: 0 });
    }
    if (
      (url.pathname === `/v1/recordings/${RECORDING_ID}/visual-intelligence`
        || url.pathname === `/v2/recordings/${RECORDING_ID}/visual-intelligence`)
      && req.method === 'GET'
    ) {
      return json(res, 404, { detail: 'No visual intelligence in synthetic fixture' });
    }

    return json(res, 404, { detail: `fixture route not found: ${req.method} ${url.pathname}` });
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

async function waitText(browser, needles, timeoutMs = 8000, record = false) {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = await browser.text();
    if (needles.some((needle) => last.includes(needle))) return last;
    if (record) await frame(browser);
    await sleep(180);
  }
  throw new Error(`timed out waiting for ${needles.join(' | ')}; text=${last.slice(0, 1600)}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'record-while-ai-busy.mp4');
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
  if (!(await fsp.stat(videoPath)).size) throw new Error('record-while-ai-busy video is empty');
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
  await browser.navigate(`http://127.0.0.1:${vitePort}/#recording`);
  await waitText(browser, ['Pronto per registrare', 'Ready to record'], 30000, true);
  await checkpoint(browser, '01-ready-before-start');

  await browser.clickButton(['Avvia Registrazione', 'Start Recording']);
  await waitText(browser, ['Preparazione registrazione', 'Preparing recording'], 8000, true);
  if (counts.reservationCreate !== 1 || counts.startCapture !== 0) {
    throw new Error(`capture was not held behind the AI reservation: ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '02-waiting-for-ai');

  const waitingText = await browser.text();
  if (!waitingText.includes('Annulla') && !waitingText.includes('Cancel')) {
    throw new Error('waiting state does not expose an explicit cancel action');
  }

  const finishAi = await fetch(`http://127.0.0.1:${backendPort}/__e2e/finish-ai`, { method: 'POST' });
  if (!finishAi.ok) throw new Error(`failed to release synthetic AI phase: ${finishAi.status}`);

  await waitText(browser, ['Registrazione in corso', 'Recording in progress'], 10000, true);
  if (counts.startCapture !== 1 || !captureStarted || !reservationActive) {
    throw new Error(`recording did not start under the granted reservation: ${JSON.stringify({ counts, captureStarted, reservationActive })}`);
  }
  await checkpoint(browser, '03-recording-active');

  await browser.clickButton(['Termina e salva', 'Stop and Save']);
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && (!captureStopped || !aiResumed)) {
    await frame(browser);
    await sleep(180);
  }
  if (!captureStopped || !aiResumed || reservationActive) {
    throw new Error(`stop did not release capture priority and resume AI: ${JSON.stringify({ captureStopped, aiResumed, reservationActive, counts })}`);
  }
  if (counts.stopCapture !== 1 || counts.reservationRelease !== 1) {
    throw new Error(`unexpected stop/release calls: ${JSON.stringify(counts)}`);
  }
  await waitText(browser, ['Busy AI capture proof'], 10000, true);
  await checkpoint(browser, '04-saved-and-ai-resumed');

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
  journey_id: 'record-while-ai-busy',
  execution_environment: 'browser-macos-arm64-ci',
  fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision,
  result: error ? 'FAIL' : 'PASS',
  requests: counts,
  checkpoints,
  video,
  privacy_boundary: 'Synthetic workload, meeting and capture state only; captures are restricted to the headless Chrome viewport.',
  proven_outcomes: [
    'Start meeting remains truthful while managed AI is active: the UI shows preparation rather than recording.',
    'Capture does not start until the reservation is granted.',
    'The user can cancel while waiting for the active AI phase.',
    'The reservation remains held during recording and is released after Stop.',
    'Releasing the reservation allows queued managed AI work to resume; scheduler ordering itself is covered by source-contract tests.',
  ],
  residual_fidelity_gaps: [
    'deterministic browser fixtures do not prove physical microphone/system-audio capture or TCC behavior',
    'does not exercise production MLX/Metal resource pressure or thermal behavior',
    'does not exercise the packaged WKWebView process boundary',
  ],
  error,
};
await fsp.writeFile(path.join(evidenceRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
