#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf';
const MEETING_ID = 'e2e-meeting';
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

const counts = { session: 0, health: 0, meeting: 0, diagnostics: 0, visual_frames: 0 };
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
    if (pathname === `/v1/meetings/${MEETING_ID}`) {
      counts.meeting += 1;
      return json(res, 200, meetingFixture);
    }
    if (pathname === `/v1/meetings/${MEETING_ID}/diagnostics`) {
      counts.diagnostics += 1;
      if (counts.diagnostics === 1) {
        await sleep(DIAGNOSTICS_DELAY_MS);
        return json(res, 503, { detail: 'synthetic diagnostics outage' });
      }
      return json(res, 200, diagnosticsFixture);
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
    throw new Error(`normal open fetched accessories: ${JSON.stringify(counts)}`);
  }
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
  await browser.clickButton(['Retry', 'Riprova']);
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
  await browser.clickButton(['Retry', 'Riprova']);
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
