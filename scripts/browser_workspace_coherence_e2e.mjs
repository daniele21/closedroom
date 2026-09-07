#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';

const VIDEO_FPS = 4;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_WORKSPACE_COHERENCE_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-ui/workspace-coherence'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';
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
    if (child && child.exitCode !== null) throw new Error(`process exited before port ${port} was ready: ${child.exitCode}`);
    if (await portReady(port)) return;
    await sleep(100);
  }
  throw new Error(`port ${port} did not become ready`);
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

  async setWindow(width, height) {
    await webdriver(this.port, 'POST', this.p('/window/rect'), { width, height });
  }

  async click(selector) {
    const clicked = await this.execute(`
      const node = document.querySelector(${JSON.stringify(selector)});
      if (!node) return false;
      node.click();
      return true;
    `);
    if (clicked !== true) throw new Error(`element not found: ${selector}`);
  }

  async clickMeetingCardContaining(titleFragment) {
    const clicked = await this.execute(`
      const titleFragment = ${JSON.stringify(titleFragment)};
      const article = Array.from(document.querySelectorAll('article')).find((candidate) =>
        (candidate.innerText || candidate.textContent || '').includes(titleFragment)
      );
      if (!article) return false;
      const buttons = Array.from(article.querySelectorAll('button')).filter((button) => !button.disabled);
      const action = buttons.find((button) => /apri|open|analizza|analyze|trascrivi|transcribe/i.test(
        (button.innerText || button.textContent || '').trim(),
      )) || buttons.at(-1);
      if (!action) return false;
      action.click();
      return true;
    `);
    if (clicked !== true) throw new Error(`meeting card action not found: ${titleFragment}`);
  }

  async clickMenuItemContaining(labels) {
    const clicked = await this.execute(`
      const labels = ${JSON.stringify(labels)};
      const node = Array.from(document.querySelectorAll('#app-settings-menu [role="menuitem"]')).find((candidate) => {
        const text = (candidate.innerText || candidate.textContent || '').trim();
        return labels.some((label) => text.includes(label));
      });
      if (!node) return false;
      node.click();
      return true;
    `);
    if (clicked !== true) throw new Error(`menu item not found: ${labels.join(', ')}`);
  }

  async screenshot(destination) {
    const data = await webdriver(this.port, 'GET', this.p('/screenshot'));
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await fsp.writeFile(destination, Buffer.from(data, 'base64'));
  }
}

async function frame(browser, source) {
  const destination = path.join(evidenceRoot, 'frames', `frame-${String(frameIndex++).padStart(4, '0')}.png`);
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

async function waitUntil(browser, description, script, timeoutMs = 8000, record = false) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await browser.execute(script)) return;
    if (record) await frame(browser);
    await sleep(160);
  }
  throw new Error(`timed out waiting for ${description}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'workspace-coherence.mp4');
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
  if (!(await fsp.stat(videoPath)).size) throw new Error('workspace coherence video is empty');
  return path.relative(evidenceRoot, videoPath);
}

async function stop(process) {
  if (!process || process.exitCode !== null) return;
  process.kill('SIGTERM');
  await Promise.race([new Promise((resolve) => process.once('exit', resolve)), sleep(5000)]);
  if (process.exitCode === null) process.kill('SIGKILL');
}

await fsp.rm(evidenceRoot, { recursive: true, force: true });
await fsp.mkdir(path.join(evidenceRoot, 'logs'), { recursive: true });
const vitePort = await freePort();
const driverPort = await freePort();
const viteLog = fs.openSync(path.join(evidenceRoot, 'logs/vite.log'), 'w');
const driverLog = fs.openSync(path.join(evidenceRoot, 'logs/chromedriver.log'), 'w');
let vite;
let driver;
let browser;
let video = null;
let error = null;
const observations = {};

try {
  vite = launch(
    'pnpm',
    ['exec', 'vite', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
    { cwd: path.join(root, 'frontend'), env: { ...process.env }, stdio: ['ignore', viteLog, viteLog] },
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
  await browser.navigate(`http://127.0.0.1:${vitePort}/?demo=true#home`);
  await waitUntil(
    browser,
    'Today demo workspace',
    "return document.querySelector('[data-workspace-page=\"home\"]') && document.body.innerText.includes('Product sync');",
    30000,
    true,
  );

  observations.wideHome = await browser.execute(`
    const rail = document.querySelector('.workspace-rail');
    const home = document.querySelector('[data-tour="nav-home"]');
    const projects = document.querySelector('[data-tour="nav-projects"]');
    const shell = document.querySelector('.workspace-shell');
    const railRect = rail?.getBoundingClientRect();
    return {
      page: document.querySelector('.workspace-content')?.getAttribute('data-workspace-page'),
      homeCurrent: home?.getAttribute('aria-current'),
      projectsCurrent: projects?.getAttribute('aria-current'),
      railWidth: railRect?.width || 0,
      railHeight: railRect?.height || 0,
      shellColumns: shell ? getComputedStyle(shell).gridTemplateColumns : '',
      railPosition: rail ? getComputedStyle(rail).position : '',
    };
  `);
  if (observations.wideHome.page !== 'home' || observations.wideHome.homeCurrent !== 'page') {
    throw new Error(`Today navigation hierarchy is not active: ${JSON.stringify(observations.wideHome)}`);
  }
  if (observations.wideHome.railWidth < 200 || !String(observations.wideHome.shellColumns).includes('236px')) {
    throw new Error(`wide workspace rail is not stable: ${JSON.stringify(observations.wideHome)}`);
  }
  await checkpoint(browser, '01-wide-today');

  await browser.clickMeetingCardContaining('Product sync');
  await waitUntil(
    browser,
    'Meeting workspace',
    "return document.querySelector('.workspace-content')?.getAttribute('data-workspace-page') === 'meeting';",
    10000,
    true,
  );
  observations.meeting = await browser.execute(`
    return {
      page: document.querySelector('.workspace-content')?.getAttribute('data-workspace-page'),
      homeCurrent: document.querySelector('[data-tour="nav-home"]')?.getAttribute('aria-current'),
      hasTranscriptTab: Boolean(document.querySelector('#meeting-tab-transcript')),
      hasAnalysisTab: Boolean(document.querySelector('#meeting-tab-analysis')),
    };
  `);
  if (observations.meeting.homeCurrent !== 'page' || !observations.meeting.hasTranscriptTab || !observations.meeting.hasAnalysisTab) {
    throw new Error(`Meeting did not remain inside Today workspace: ${JSON.stringify(observations.meeting)}`);
  }
  await checkpoint(browser, '02-meeting-child-of-today');

  await browser.click('[data-tour="nav-projects"]');
  await waitUntil(
    browser,
    'Projects workspace',
    "return document.querySelector('.workspace-content')?.getAttribute('data-workspace-page') === 'projects' && document.body.innerText.includes('ClosedRoom Beta Launch');",
    10000,
    true,
  );
  observations.projects = await browser.execute(`
    return {
      projectsCurrent: document.querySelector('[data-tour="nav-projects"]')?.getAttribute('aria-current'),
      homeCurrent: document.querySelector('[data-tour="nav-home"]')?.getAttribute('aria-current'),
      hasProjectSidebar: Boolean(document.querySelector('[data-tour="project-sidebar"]')),
    };
  `);
  if (observations.projects.projectsCurrent !== 'page' || observations.projects.homeCurrent === 'page') {
    throw new Error(`Projects navigation hierarchy is not exclusive: ${JSON.stringify(observations.projects)}`);
  }
  await checkpoint(browser, '03-projects-container');

  const themeBefore = await browser.execute("return document.documentElement.getAttribute('data-theme');");
  await browser.click('.workspace-settings-trigger');
  await waitUntil(browser, 'workspace utility menu', "return Boolean(document.querySelector('#app-settings-menu'));", 5000);
  await browser.clickMenuItemContaining(['Tema', 'Theme']);
  const themeAfter = await browser.execute("return document.documentElement.getAttribute('data-theme');");
  if (themeBefore === themeAfter) throw new Error(`theme utility did not change theme: ${themeBefore}`);
  await checkpoint(browser, '04-theme-continuity');

  await browser.setWindow(780, 900);
  await sleep(350);
  observations.compact = await browser.execute(`
    const rail = document.querySelector('.workspace-rail');
    const railRect = rail?.getBoundingClientRect();
    return {
      width: window.innerWidth,
      railWidth: railRect?.width || 0,
      railHeight: railRect?.height || 0,
      railPosition: rail ? getComputedStyle(rail).position : '',
      newMeetingVisible: Boolean(document.querySelector('[data-tour="new-meeting-btn"]')),
      settingsVisible: Boolean(document.querySelector('.workspace-settings-trigger')),
    };
  `);
  if (observations.compact.width > 800 || observations.compact.railHeight > 100 || observations.compact.railPosition !== 'sticky') {
    throw new Error(`compact workspace did not become a bounded top bar: ${JSON.stringify(observations.compact)}`);
  }
  if (!observations.compact.newMeetingVisible || !observations.compact.settingsVisible) {
    throw new Error(`compact workspace lost primary/utility actions: ${JSON.stringify(observations.compact)}`);
  }
  await checkpoint(browser, '05-compact-window');

  await browser.setWindow(560, 820);
  await sleep(300);
  observations.narrow = await browser.execute(`
    const nav = document.querySelector('.workspace-primary-nav');
    const newMeeting = document.querySelector('[data-tour="new-meeting-btn"]');
    const settings = document.querySelector('.workspace-settings-trigger');
    const navRect = nav?.getBoundingClientRect();
    const newMeetingRect = newMeeting?.getBoundingClientRect();
    const settingsRect = settings?.getBoundingClientRect();
    const overlaps = (left, right) => Boolean(left && right)
      && left.left < right.right
      && left.right > right.left
      && left.top < right.bottom
      && left.bottom > right.top;
    return {
      width: window.innerWidth,
      navOverflow: nav ? getComputedStyle(nav).overflowX : '',
      newMeetingWidth: newMeetingRect?.width || 0,
      hasHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      navNewMeetingOverlap: overlaps(navRect, newMeetingRect),
      newMeetingSettingsOverlap: overlaps(newMeetingRect, settingsRect),
    };
  `);
  if (
    observations.narrow.hasHorizontalOverflow
    || observations.narrow.newMeetingWidth > 60
    || observations.narrow.navNewMeetingOverlap
    || observations.narrow.newMeetingSettingsOverlap
  ) {
    throw new Error(`narrow workspace is not bounded and non-overlapping: ${JSON.stringify(observations.narrow)}`);
  }
  await checkpoint(browser, '06-narrow-window');

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
  fs.closeSync(viteLog);
  fs.closeSync(driverLog);
}

const manifest = {
  schema_version: 1,
  journey_id: 'coherent-macos-workspace',
  execution_environment: 'browser-macos-arm64-ci',
  fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision,
  result: error ? 'FAIL' : 'PASS',
  observations,
  checkpoints,
  video,
  privacy_boundary: 'Deterministic in-app demo data only; captures are restricted to the headless Chrome viewport.',
  residual_fidelity_gaps: [
    'headless Chrome proves responsive workspace semantics but not the packaged WKWebView window chrome',
    'does not prove VoiceOver spoken-output quality or real macOS focus-ring rendering',
    'does not exercise TCC/native capture or production MLX/Metal behavior',
  ],
  error,
};
await fsp.writeFile(path.join(evidenceRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
