#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf';
const MEETING_ID = 'e2e-call-screenshot';
const SCREENSHOT_ID = 'shot-001';
const VIDEO_FPS = 4;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_CALL_SCREENSHOT_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-call-screenshot'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';
const counts = { active: 0, displays: 0, display_select: 0, screenshots_get: 0, screenshots_post: 0, stop: 0, open_meeting: 0, meeting: 0, visual_frames: 0 };
const checkpoints = [];
const sseClients = new Set();
let frameIndex = 0;
let active = true;
let screenshot = null;
let selectedDisplayId = null;

const recording = {
  id: MEETING_ID,
  title: 'Screenshot evidence review',
  project_name: 'Browser E2E',
  status: 'recorded',
  capture_backend: 'native',
  capture_mode: 'both',
  mime_type: 'audio/wav',
  audio_file: 'synthetic.wav',
  bytes_written: 4096,
  created_at: '2026-10-01T18:00:00Z',
  stopped_at: '2026-10-01T18:00:40Z',
  duration_seconds: 40,
  screenshot_count: 1,
};

function publicScreenshot() {
  return {
    screenshot_id: SCREENSHOT_ID, recording_id: MEETING_ID, request_id: 'browser-e2e-request',
    sequence: 0, capture_kind: 'manual', timestamp: 12, captured_wall_time: 1790877612,
    display_id: 7, display_title: 'Synthetic Display 1',
    width: 1440, height: 900, thumbnail_width: 640, thumbnail_height: 400,
    sha256: 'synthetic-sha', available: true, thumbnail_available: true,
    original_url: '/v1/recordings/' + MEETING_ID + '/screenshots/' + SCREENSHOT_ID + '/original',
    thumbnail_url: '/v1/recordings/' + MEETING_ID + '/screenshots/' + SCREENSHOT_ID + '/thumbnail',
  };
}

function structuredRun() {
  const sourceRef = {
    source_type: 'screenshot', source_id: 'screenshot:' + SCREENSHOT_ID,
    screenshot_id: SCREENSHOT_ID, timestamp: 12, confidence: 0.91,
    evidence_basis: 'visual_inference', machine_interpreted: true,
  };
  const result = {
    schema: { id: 'closedroom.meeting_notes', version: 2 },
    generated: {
      summary: { text: 'The roadmap image shows the launch milestone.', source_refs: [sourceRef], evidence_basis: 'visual' },
      actions: [], decisions: [], risks: [],
    },
    metrics: { visual_source_count: 1 },
    source_snapshot: { visual_sources: [{
      screenshot_id: SCREENSHOT_ID, sha256: 'synthetic-sha', timestamp: 12,
      content_type: 'slide', title: 'Launch roadmap', confidence: 0.91,
    }] },
    markdown: 'The roadmap image shows the launch milestone.',
  };
  return {
    id: 'analysis-shot-run', scope_type: 'transcription', scope_id: 'transcription-shot',
    transcription_id: 'transcription-shot', recording_id: MEETING_ID,
    analysis_type: 'meeting_brief', template_id: 'meeting_brief', template_version: 'v2',
    pipeline_run_id: 'pipeline-shot', provider: 'mock', model: 'synthetic',
    prompt_version: 'meeting_notes_shared_v2', input_hash: 'synthetic-input',
    status: 'completed', result, result_markdown: result.markdown,
    source_ids: [MEETING_ID, 'transcription-shot'], created_at: 1790877660, completed_at: 1790877670,
  };
}

function meetingFixture() {
  const run = structuredRun();
  return {
    id: MEETING_ID,
    recording,
    transcription: {
      id: 'transcription-shot', timestamp: '2026-10-01T18:00:41Z', model: 'synthetic',
      language: 'en', audio_filename: 'synthetic.wav', recording_id: MEETING_ID,
      text: 'Alex reviews the launch roadmap and validation plan.',
      segments: [{ id: 10, start: 4, end: 24, text: 'Alex reviews the launch roadmap and validation plan.', speaker_label: 'SPEAKER_00' }],
      stats: { outcome_status: 'completed' },
    },
    analysis_runs: [run], latest_analysis: { meeting_brief: run }, jobs: [], status: 'ready',
    project_name: 'Browser E2E', created_at: recording.created_at, updated_at: recording.stopped_at,
  };
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function launch(command, args, options) {
  const child = spawn(command, args, options);
  child.startError = null;
  child.on('error', (error) => { child.startError = error; });
  return child;
}
async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}
async function portReady(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('error', () => resolve(false));
    socket.setTimeout(500, () => { socket.destroy(); resolve(false); });
  });
}
async function waitPort(port, timeoutMs, child) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child?.startError) throw child.startError;
    if (child && child.exitCode !== null) throw new Error('process exited before port readiness');
    if (await portReady(port)) return;
    await sleep(100);
  }
  throw new Error('port did not become ready: ' + port);
}
function json(res, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': body.length, 'cache-control': 'no-store' });
  res.end(body);
}
async function requestBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf-8');
}
function overlayPayload() {
  return active ? {
    active: true, recording_id: MEETING_ID, title: recording.title,
    capture_backend: 'native', capture_mode: 'both', started_at: '2026-10-01T18:00:00Z',
    bytes_written: 4096, mic_db: -20, system_db: -18, warnings: [],
    screenshot_count: screenshot ? 1 : 0, screenshot_display_id: selectedDisplayId,
  } : { active: false };
}
function sendOverlay(res) { res.write('data: ' + JSON.stringify(overlayPayload()) + '\n\n'); }

function fixtureServer(port) {
  return http.createServer(async (req, res) => {
    const pathname = new URL(req.url, 'http://127.0.0.1:' + port).pathname;
    if (pathname === '/v1/session') return json(res, 200, { ok: true });
    if (pathname === '/health') return json(res, 200, {
      ok: true, server: 'call-screenshot-fixture', backend: 'synthetic',
      default_model: 'synthetic/model', status: active ? 'recording' : 'idle', endpoints: [], recordings: true,
    });
    if (pathname === '/v1/recordings/active') {
      counts.active += 1;
      return json(res, 200, overlayPayload());
    }
    if (pathname === '/v1/capture/displays') {
      counts.displays += 1;
      return json(res, 200, { displays: [
        { display_id: 7, source_id: -7, title: 'Synthetic Display 1', width: 1440, height: 900 },
        { display_id: 8, source_id: -8, title: 'Synthetic Display 2', width: 1920, height: 1080 },
      ] });
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/screenshot-display' && req.method === 'PUT') {
      counts.display_select += 1;
      const parsed = JSON.parse(await requestBody(req) || '{}');
      const displays = [
        { display_id: 7, source_id: -7, title: 'Synthetic Display 1', width: 1440, height: 900 },
        { display_id: 8, source_id: -8, title: 'Synthetic Display 2', width: 1920, height: 1080 },
      ];
      const display = displays.find((item) => item.display_id === Number(parsed.display_id));
      if (!display) return json(res, 409, { detail: 'selected_display_unavailable' });
      selectedDisplayId = display.display_id;
      for (const client of sseClients) sendOverlay(client);
      return json(res, 200, { recording_id: MEETING_ID, display_id: display.display_id, display });
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/overlay/events') {
      res.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache, no-store', connection: 'keep-alive' });
      res.flushHeaders?.();
      sseClients.add(res);
      sendOverlay(res);
      req.on('close', () => sseClients.delete(res));
      return;
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/screenshots' && req.method === 'POST') {
      counts.screenshots_post += 1;
      const parsed = JSON.parse(await requestBody(req) || '{}');
      if (parsed.display_id !== 7) return json(res, 409, { detail: 'selected_display_unavailable' });
      screenshot = publicScreenshot();
      for (const client of sseClients) sendOverlay(client);
      return json(res, 201, screenshot);
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/screenshots' && req.method === 'GET') {
      counts.screenshots_get += 1;
      const items = screenshot ? [screenshot] : [];
      return json(res, 200, { items, total: items.length });
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/control/stop' && req.method === 'POST') {
      counts.stop += 1;
      active = false;
      for (const client of sseClients) { sendOverlay(client); client.end(); }
      sseClients.clear();
      return json(res, 202, { recording: { ...recording, screenshot_count: screenshot ? 1 : 0 } });
    }
    if (pathname === '/v1/system/window/main/meeting/' + MEETING_ID && req.method === 'POST') {
      counts.open_meeting += 1;
      return json(res, 200, { success: false, error: 'synthetic browser fallback' });
    }
    if (pathname === '/v1/meetings/' + MEETING_ID) {
      counts.meeting += 1;
      return json(res, 200, meetingFixture());
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/visual-frames') {
      counts.visual_frames += 1;
      return json(res, 200, { items: [], total: 0 });
    }
    if (pathname === '/v1/recordings/' + MEETING_ID + '/audio') {
      const body = Buffer.alloc(44);
      res.writeHead(200, { 'content-type': 'audio/wav', 'content-length': body.length });
      return res.end(body);
    }
    if (pathname.includes('/screenshots/' + SCREENSHOT_ID + '/')) {
      const body = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400"><rect width="100%" height="100%" fill="#111827"/><text x="40" y="90" fill="white" font-size="32">Launch roadmap</text><text x="40" y="150" fill="#67e8f9" font-size="24">Synthetic screenshot evidence</text></svg>');
      res.writeHead(200, { 'content-type': 'image/svg+xml', 'content-length': body.length, 'cache-control': 'no-store' });
      return res.end(body);
    }
    return json(res, 404, { detail: 'fixture route not found: ' + pathname });
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
  throw new Error('chromedriver executable not found');
}
async function webdriver(port, method, pathname, payload) {
  const response = await fetch('http://127.0.0.1:' + port + pathname, {
    method, headers: { 'content-type': 'application/json; charset=utf-8' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const parsed = await response.json();
  if (!response.ok || parsed?.value?.error) throw new Error('WebDriver failure: ' + JSON.stringify(parsed).slice(0, 1000));
  return parsed.value;
}
class Browser {
  constructor(port) { this.port = port; this.sessionId = null; }
  p(suffix) { return '/session/' + this.sessionId + suffix; }
  async start() {
    const value = await webdriver(this.port, 'POST', '/session', { capabilities: { alwaysMatch: {
      browserName: 'chrome',
      'goog:chromeOptions': { args: ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--window-size=1280,900', '--force-device-scale-factor=1', '--disable-background-networking', '--disable-default-apps'] },
    } } });
    this.sessionId = value.sessionId;
  }
  async close() { if (this.sessionId) { try { await webdriver(this.port, 'DELETE', this.p('')); } catch {} } }
  async navigate(url) { await webdriver(this.port, 'POST', this.p('/url'), { url }); }
  async execute(script) { return webdriver(this.port, 'POST', this.p('/execute/sync'), { script, args: [] }); }
  async text() { return String(await this.execute("return document.body ? document.body.innerText : '';")); }
  async clickCss(selector) {
    const value = await webdriver(this.port, 'POST', this.p('/element'), { using: 'css selector', value: selector });
    await webdriver(this.port, 'POST', this.p('/element/' + value[ELEMENT_KEY] + '/click'), {});
  }
  async screenshot(destination) {
    const data = await webdriver(this.port, 'GET', this.p('/screenshot'));
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await fsp.writeFile(destination, Buffer.from(data, 'base64'));
  }
}
async function frame(browser, source) {
  const destination = path.join(evidenceRoot, 'frames', 'frame-' + String(frameIndex++).padStart(4, '0') + '.png');
  await fsp.mkdir(path.dirname(destination), { recursive: true });
  if (source) await fsp.copyFile(source, destination); else await browser.screenshot(destination);
}
async function checkpoint(browser, name, holdFrames = VIDEO_FPS) {
  const destination = path.join(evidenceRoot, 'screenshots', name + '.png');
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
    await sleep(150);
  }
  throw new Error('timed out waiting for ' + needles.join(' | ') + '; text=' + last.slice(0, 1200));
}
async function waitSelector(browser, selector, timeoutMs = 8000, record = false) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await browser.execute(`return Boolean(document.querySelector(${JSON.stringify(selector)}));`);
    if (found) return;
    if (record) await frame(browser);
    await sleep(150);
  }
  throw new Error('timed out waiting for selector ' + selector);
}
async function waitHash(browser, expected, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await browser.execute('return window.location.hash;') === expected) return;
    await frame(browser);
    await sleep(150);
  }
  throw new Error('timed out waiting for hash ' + expected);
}
async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'call-screenshot.mp4');
  await fsp.mkdir(path.dirname(videoPath), { recursive: true });
  const child = launch('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y', '-framerate', String(VIDEO_FPS),
    '-i', path.join(evidenceRoot, 'frames', 'frame-%04d.png'),
    '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', videoPath,
  ], { stdio: 'inherit' });
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve); });
  if (code !== 0) throw new Error('ffmpeg exited ' + code);
  if (!(await fsp.stat(videoPath)).size) throw new Error('video is empty');
  return path.relative(evidenceRoot, videoPath);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  child.kill('SIGTERM');
  await Promise.race([new Promise((resolve) => child.once('exit', resolve)), sleep(5000)]);
  if (child.exitCode === null) child.kill('SIGKILL');
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
let vite, driver, browser, video = null, error = null;

try {
  vite = launch('pnpm', ['exec', 'vite', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], {
    cwd: path.join(root, 'frontend'), env: { ...process.env, BACKEND_PORT: String(backendPort) }, stdio: ['ignore', viteLog, viteLog],
  });
  await waitPort(vitePort, 15000, vite);
  driver = launch(findChromeDriver(), ['--port=' + driverPort, '--allowed-ips=127.0.0.1'], { cwd: root, stdio: ['ignore', driverLog, driverLog] });
  await waitPort(driverPort, 10000, driver);
  browser = new Browser(driverPort);
  await browser.start();
  await browser.navigate('http://127.0.0.1:' + vitePort + '/#overlay');
  await waitText(browser, ['Synthetic Display 1'], 30000, true);
  await checkpoint(browser, '01-overlay-recording');

  const expanded = await browser.execute(`
    const button = Array.from(document.querySelectorAll('button')).find((node) => node.title === 'Dettagli' || node.title === 'Details');
    if (!button) return false; button.click(); return true;
  `);
  if (!expanded) throw new Error('overlay details control not found');
  await waitText(browser, ['Screenshot evidence review'], 5000, true);

  const pickerOpened = await browser.execute(`
    const button = document.querySelector('button[data-display-selector="true"]');
    if (!button || button.disabled) return false; button.click(); return true;
  `);
  if (!pickerOpened) throw new Error('display picker control unavailable');
  await waitText(browser, ['Screenshot screen'], 3000, true);

  const selected = await browser.execute(`
    const picker = document.querySelector('[data-display-picker="true"]');
    if (!picker) return false;
    const option = Array.from(picker.querySelectorAll('[role="option"]'))
      .find((node) => (node.innerText || '').includes('Synthetic Display 1'));
    if (!option || option.disabled) return false; option.click(); return true;
  `);
  if (!selected) throw new Error('display selection failed');
  const selectionDeadline = Date.now() + 3000;
  while (counts.display_select < 1 && Date.now() < selectionDeadline) await sleep(50);
  if (counts.display_select !== 1) throw new Error('unexpected display selection count: ' + counts.display_select);
  await waitText(browser, ['Synthetic Display 1'], 3000, true);
  await checkpoint(browser, '02-display-selected');

  const clickedShot = await browser.execute(`
    const button = document.querySelector('button[data-screenshot-action="true"]');
    if (!button || button.disabled) return false; button.click(); return true;
  `);
  if (!clickedShot) throw new Error('screenshot button unavailable');
  await waitText(browser, ['Saved', 'Screenshots 1'], 8000, true);
  await waitSelector(browser, 'button[data-screenshot-undo="true"]', 3000, true);
  if (counts.screenshots_post !== 1) throw new Error('unexpected screenshot POST count: ' + counts.screenshots_post);
  await checkpoint(browser, '03-screenshot-persisted');

  await browser.clickCss('button[aria-label="Stop recording"]');
  await waitHash(browser, '#meeting/' + MEETING_ID, 10000);
  await waitText(browser, ['Screenshot evidence review'], 30000, true);
  if (counts.stop !== 1 || counts.open_meeting !== 1) throw new Error('stop/open counts unexpected: ' + JSON.stringify(counts));
  await waitText(browser, ['Key moments'], 10000, true);
  await waitSelector(browser, '[data-key-moment-id="shot-001"]', 5000, true);
  await waitText(browser, ['Alex reviews the launch roadmap and validation plan.'], 5000, true);
  await waitText(browser, ['The roadmap image shows the launch milestone.'], 10000, true);
  await waitText(browser, ['Screenshot · 00:12'], 10000);
  await checkpoint(browser, '04-meeting-notes-cited');

  const noteEvidenceClicked = await browser.execute(`
    const button = Array.from(document.querySelectorAll('button')).find((node) => (node.innerText || '').includes('Screenshot · 00:12'));
    if (!button) return false; button.click(); return true;
  `);
  if (!noteEvidenceClicked) throw new Error('structured-note screenshot citation not clickable');
  await waitText(browser, ['Synthetic Display 1'], 3000);
  await checkpoint(browser, '05-note-evidence-original');
  const closeModal = await browser.execute(`
    const labels = ['Chiudi screenshot', 'Close screenshot'];
    const button = Array.from(document.querySelectorAll('button')).find((node) => labels.includes(node.getAttribute('aria-label')));
    if (!button) return false; button.click(); return true;
  `);
  if (!closeModal) throw new Error('screenshot modal close control missing');

  await browser.clickCss('#meeting-tab-transcript');
  await waitText(browser, ['Alex reviews the launch roadmap and validation plan.'], 5000, true);
  await waitSelector(browser, 'button[data-screenshot-id="shot-001"]', 5000, true);
  const anchored = await browser.execute(`
    const marker = document.querySelector('button[data-screenshot-id="shot-001"]');
    if (!marker) return false;
    const segment = marker.closest('[class*="border-l-4"]');
    return Boolean(segment && segment.innerText.includes('Alex reviews the launch roadmap'));
  `);
  if (!anchored) throw new Error('screenshot marker was not anchored inside the long transcript turn');
  await checkpoint(browser, '06-transcript-marker-in-turn');

  await browser.clickCss('button[data-screenshot-id="shot-001"]');
  await waitText(browser, ['Synthetic Display 1'], 3000);
  const seekClicked = await browser.execute(`
    const button = Array.from(document.querySelectorAll('button')).find((node) => {
      const text = (node.innerText || '').trim();
      return text.includes("Vai all'audio") || text.includes('Seek audio');
    });
    if (!button) return false; button.click(); return true;
  `);
  if (!seekClicked) throw new Error('screenshot-to-audio action missing');
  await checkpoint(browser, '07-screenshot-to-audio');
  video = await renderVideo();
} catch (caught) {
  error = (caught?.name || 'Error') + ': ' + (caught?.message || caught);
  if (browser) { try { await checkpoint(browser, '99-failure', 1); } catch {} }
} finally {
  if (browser) await browser.close();
  await stop(driver);
  await stop(vite);
  for (const client of sseClients) { try { client.end(); } catch {} }
  await new Promise((resolve) => server.close(resolve));
  fs.closeSync(viteLog);
  fs.closeSync(driverLog);
}

const manifest = {
  schema_version: 1, journey_id: 'call-overlay-screenshot-evidence',
  execution_environment: 'browser-macos-arm64-ci', fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision, result: error ? 'FAIL' : 'PASS', requests: counts,
  checkpoints, video,
  privacy_boundary: 'Synthetic meeting, transcript, notes and screenshot content only; evidence is restricted to the headless Chrome viewport.',
  residual_fidelity_gaps: [
    'does not prove real ScreenCaptureKit pixels, display withdrawal, TCC prompts or ClosedRoom overlay exclusion',
    'does not exercise the packaged WKWebView process boundary or global shortcut delivery from another foreground app',
    'does not prove physical audio devices, production local-VLM quality, latency or Metal resource pressure',
  ],
  error,
};
await fsp.writeFile(path.join(evidenceRoot, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
