#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf';
const ARCHIVE_ID = 'archive-source-meeting';
const VIDEO_FPS = 4;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_ARCHIVE_SEARCH_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-ui/archive-search'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';
const checkpoints = [];
const counts = { session: 0, health: 0, recent: 0, search: 0, detail: 0 };
let frameIndex = 0;

function meeting(id, title, createdAt, transcript = '') {
  return {
    id,
    recording: {
      id,
      title,
      project_name: 'Archive E2E',
      status: 'completed',
      mime_type: 'audio/wav',
      audio_file: 'synthetic.wav',
      bytes_written: 1024,
      created_at: createdAt,
      stopped_at: createdAt,
      duration_seconds: 300,
    },
    transcription: transcript ? {
      id: `${id}-transcript`,
      timestamp: createdAt,
      model: 'synthetic-fixture',
      language: 'en',
      audio_filename: 'synthetic.wav',
      recording_id: id,
      text: transcript,
      segments: [],
      stats: { outcome_status: 'completed' },
    } : null,
    analysis_runs: [],
    latest_analysis: {},
    jobs: [],
    status: transcript ? 'transcribed' : 'recorded',
    project_name: 'Archive E2E',
    created_at: createdAt,
    updated_at: createdAt,
  };
}

const recentMeetings = [
  meeting('recent-1', 'Weekly planning', '2026-09-06T08:00:00Z'),
  meeting('recent-2', 'Product sync', '2026-09-05T08:00:00Z'),
  meeting('recent-3', 'Hiring review', '2026-09-04T08:00:00Z'),
];
const archiveMeeting = meeting(
  ARCHIVE_ID,
  'Archive source meeting',
  '2025-01-15T09:00:00Z',
  'The historical decision used the unique keyword sequoia and must remain discoverable.',
);

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
  return http.createServer((req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    if (url.pathname === '/v1/session') {
      counts.session += 1;
      return json(res, 200, { ok: true });
    }
    if (url.pathname === '/health') {
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
    if (url.pathname === `/v1/meetings/${ARCHIVE_ID}`) {
      counts.detail += 1;
      return json(res, 200, archiveMeeting);
    }
    if (url.pathname === '/v1/meetings') {
      if (url.searchParams.has('q')) {
        counts.search += 1;
        const query = (url.searchParams.get('q') || '').toLowerCase();
        const page = Number(url.searchParams.get('page') || '1');
        const limit = Number(url.searchParams.get('limit') || '25');
        const items = query.includes('sequoia') ? [archiveMeeting] : recentMeetings;
        return json(res, 200, {
          items: items.slice((page - 1) * limit, page * limit),
          total: query.includes('sequoia') ? 1 : 130,
          page,
          limit,
          has_more: !query.includes('sequoia') && page === 1,
        });
      }
      counts.recent += 1;
      return json(res, 200, { items: recentMeetings });
    }
    if (url.pathname.startsWith(`/v1/recordings/${ARCHIVE_ID}/visual-frames`)) {
      return json(res, 200, { items: [], total: 0 });
    }
    return json(res, 404, { detail: `fixture route not found: ${url.pathname}` });
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

  async commandK() {
    await this.execute(`
      window.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'k', code: 'KeyK', metaKey: true, bubbles: true,
      }));
      return true;
    `);
  }

  async typeSearch(value) {
    const changed = await this.execute(`
      const input = document.querySelector('#dashboard-meeting-search');
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    `);
    if (changed !== true) throw new Error('dashboard search input not found');
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

async function waitText(browser, needles, timeoutMs = 6000, record = false) {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = await browser.text();
    if (needles.some((needle) => last.includes(needle))) return last;
    if (record) await frame(browser);
    await sleep(180);
  }
  throw new Error(`timed out waiting for ${needles.join(' | ')}; text=${last.slice(0, 1200)}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'archive-search.mp4');
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
  if (!(await fsp.stat(videoPath)).size) throw new Error('archive search video is empty');
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
  await browser.navigate(`http://127.0.0.1:${vitePort}/`);
  await waitText(browser, ['Weekly planning'], 30000, true);
  if ((await browser.text()).includes('Archive source meeting')) {
    throw new Error('archive-only meeting leaked into the recent Today preview');
  }
  await checkpoint(browser, '01-today-recent-only');

  await browser.commandK();
  await waitText(browser, ['Search all meetings', 'Cerca in tutti i meeting']);
  await browser.typeSearch('sequoia');
  await waitText(browser, ['Archive source meeting'], 8000, true);
  if (counts.search < 1) throw new Error(`server-side archive search was not requested: ${JSON.stringify(counts)}`);
  await checkpoint(browser, '02-archive-hit');

  await browser.clickButton(['Archive source meeting']);
  await waitText(browser, ['historical decision used the unique keyword sequoia'], 10000, true);
  // Vite runs the app under React StrictMode, which may mount the Meeting view twice.
  // Keep the journey strict about bounded loading while accepting that development-only
  // double mount; more than two core detail requests still signals a reload loop.
  if (counts.detail < 1 || counts.detail > 2) {
    throw new Error(`expected one bounded archive detail load (up to two under StrictMode): ${JSON.stringify(counts)}`);
  }
  await checkpoint(browser, '03-source-open');

  await browser.execute('window.history.back(); return true;');
  await waitText(browser, ['Weekly planning'], 8000, true);
  await browser.commandK();
  await waitText(browser, ['Archive source meeting'], 8000, true);
  const restored = await browser.execute("return document.querySelector('#dashboard-meeting-search')?.value || ''; ");
  if (restored !== 'sequoia') throw new Error(`search query was not restored after back navigation: ${restored}`);
  await checkpoint(browser, '04-back-restores-search');

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
  journey_id: 'meeting-archive-search',
  execution_environment: 'browser-macos-arm64-ci',
  fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision,
  result: error ? 'FAIL' : 'PASS',
  requests: counts,
  checkpoints,
  video,
  privacy_boundary: 'Synthetic meeting content only; captures are restricted to the headless Chrome viewport.',
  residual_fidelity_gaps: [
    'deterministic browser fixtures do not prove SQLite FTS5 or assembled CatalogStore persistence',
    'does not exercise the packaged WKWebView process boundary',
    'does not prove TCC/native capture or production MLX/Metal behavior',
  ],
  error,
};
await fsp.writeFile(path.join(evidenceRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;