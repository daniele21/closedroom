#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

const MEETING_ID = 'e2e-note-edit-meeting';
const TRANSCRIPTION_ID = 'e2e-note-edit-transcription';
const VIDEO_FPS = 4;
const root = path.resolve(process.cwd());
const evidenceRoot = path.resolve(
  process.env.CLOSEDROOM_NOTE_EDIT_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-note-edit'),
);
const sourceRevision = process.env.E2E_SOURCE_REVISION || 'unknown';

const counts = {
  session: 0,
  health: 0,
  meeting: 0,
  edit: 0,
  regenerate: 0,
  diagnostics: 0,
  visual_frames: 0,
  audio: 0,
};
const checkpoints = [];
let frameIndex = 0;

const sourceRef = { segment_id: 1, start: 5, end: 12, speaker: 'Alex' };
const decisionRef = { segment_id: 2, start: 12, end: 20, speaker: 'Sam' };
const initialEditText = 'Alex validates release readiness';
const regeneratedText = 'Alex validates the release with QA';

const state = {
  revision: 1,
  edit: null,
  conflict: false,
};

function structuredResult() {
  const generatedAction = {
    item_id: 'action_e2e_release',
    generated_hash: state.revision === 1 ? 'generated-hash-v1' : 'generated-hash-v2',
    text: state.revision === 1 ? 'Alex validates the release' : regeneratedText,
    owner: 'Alex',
    due: 'Friday',
    status: null,
    source_refs: [sourceRef],
  };
  const generatedDecision = {
    item_id: 'decision_e2e_ship',
    generated_hash: 'decision-generated-hash-v1',
    text: 'Ship only after validation',
    rationale: 'Validation protects release quality',
    impact: null,
    source_refs: [decisionRef],
  };
  const generated = {
    summary: {
      text: 'Release validation review',
      source_refs: [{ segment_id: 0, start: 0, end: 5, speaker: 'Sam' }],
    },
    actions: [generatedAction],
    decisions: [generatedDecision],
    risks: [],
  };
  const editRecord = state.edit ? {
    item_kind: 'action',
    item_id: generatedAction.item_id,
    base_generated_hash: state.edit.base_generated_hash,
    base_run_id: state.edit.base_run_id,
    fields: { text: state.edit.text, owner: 'Alex', due: 'Friday', status: null },
    updated_at: 1788627605,
  } : null;
  const conflict = state.conflict && editRecord ? {
    item_kind: 'action',
    item_id: generatedAction.item_id,
    reason: 'generated_changed',
    retained_edit: editRecord,
    generated: generatedAction,
  } : null;
  const effectiveAction = state.edit && !state.conflict
    ? { ...generatedAction, text: state.edit.text, user_edited: true }
    : generatedAction;
  return {
    schema: { id: 'closedroom.meeting_notes', version: 2 },
    generated,
    effective: { ...generated, actions: [effectiveAction] },
    revision: {
      number: state.revision,
      run_id: `structured-run-${state.revision}`,
      supersedes_run_id: state.revision === 1 ? null : 'structured-run-1',
    },
    user_edits: editRecord ? [editRecord] : [],
    conflicts: conflict ? [conflict] : [],
    markdown: `# Meeting notes\n${effectiveAction.text}`,
  };
}

function analysisRun() {
  const result = structuredResult();
  return {
    id: `structured-run-${state.revision}`,
    job_id: `analysis-job-${state.revision}`,
    scope_type: 'transcription',
    scope_id: TRANSCRIPTION_ID,
    transcription_id: TRANSCRIPTION_ID,
    recording_id: MEETING_ID,
    analysis_type: 'meeting_brief',
    template_id: 'meeting_notes_shared',
    template_version: 'v2',
    pipeline_run_id: `pipeline-${state.revision}`,
    provider: 'mock',
    model: '',
    temperature: 0,
    reasoning: 'auto',
    show_thinking: false,
    max_output_tokens: 1024,
    json_mode: true,
    llm_options: {},
    prompt_version: 'meeting_notes_shared_v2',
    input_hash: 'synthetic-input',
    status: 'completed',
    result,
    result_markdown: result.markdown,
    source_ids: [MEETING_ID, TRANSCRIPTION_ID],
    source_run_id: `structured-run-${state.revision}`,
    created_at: 1788627600 + state.revision,
    completed_at: 1788627610 + state.revision,
  };
}

function meetingFixture() {
  const run = analysisRun();
  return {
    id: MEETING_ID,
    recording: {
      id: MEETING_ID,
      title: 'Verified notes review',
      project_name: 'Browser E2E',
      status: 'completed',
      mime_type: 'audio/wav',
      audio_file: 'synthetic.wav',
      bytes_written: 524288,
      created_at: '2026-09-05T18:00:00Z',
      stopped_at: '2026-09-05T18:10:00Z',
      duration_seconds: 600,
    },
    transcription: {
      id: TRANSCRIPTION_ID,
      timestamp: '2026-09-05T18:10:00Z',
      model: 'synthetic-fixture',
      language: 'en',
      audio_filename: 'synthetic.wav',
      recording_id: MEETING_ID,
      text: 'Release validation review. Alex validates the release. Ship only after validation.',
      stats: { outcome_status: 'completed', speaker_diarization: { status: 'disabled' } },
    },
    analysis_runs: [run],
    latest_analysis: { meeting_brief: run },
    jobs: [],
    status: 'ready',
    project_name: 'Browser E2E',
    created_at: '2026-09-05T18:00:00Z',
    updated_at: '2026-09-05T18:10:05Z',
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

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
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
        server: 'note-edit-browser-fixture',
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
    if (pathname === `/v1/meetings/${MEETING_ID}/diagnostics` && req.method === 'GET') {
      counts.diagnostics += 1;
      return json(res, 200, {
        recording_id: MEETING_ID,
        outcome_status: 'completed',
        diagnostics: [],
        jobs: [],
        events: [],
        artifacts: {},
        log_file: null,
        log_lines: [],
      });
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/visual-frames` && req.method === 'GET') {
      counts.visual_frames += 1;
      return json(res, 200, { items: [], total: 0 });
    }
    if (pathname === `/v1/recordings/${MEETING_ID}/audio` && req.method === 'GET') {
      counts.audio += 1;
      const body = Buffer.from('RIFF0000WAVEfmt ');
      res.writeHead(200, {
        'content-type': 'audio/wav',
        'content-length': body.length,
        'cache-control': 'no-store',
      });
      res.end(body);
      return;
    }
    const itemMatch = pathname.match(/^\/v1\/analysis-runs\/([^/]+)\/items\/(action|decision)\/([^/]+)$/);
    if (itemMatch && req.method === 'PATCH') {
      counts.edit += 1;
      const [, runId, itemKind, itemId] = itemMatch;
      const body = await readJson(req);
      if (itemKind !== 'action' || itemId !== 'action_e2e_release') {
        return json(res, 404, { detail: 'Structured note item not found' });
      }
      const expectedHash = state.revision === 1 ? 'generated-hash-v1' : 'generated-hash-v2';
      if (body.base_generated_hash !== expectedHash) {
        return json(res, 409, { detail: 'Structured note item changed; reload before saving the edit' });
      }
      state.edit = {
        text: body.fields?.text || initialEditText,
        base_generated_hash: expectedHash,
        base_run_id: decodeURIComponent(runId),
      };
      state.conflict = false;
      return json(res, 200, analysisRun());
    }
    const discardMatch = pathname.match(/^\/v1\/analysis-runs\/([^/]+)\/items\/(action|decision)\/([^/]+)\/edit$/);
    if (discardMatch && req.method === 'DELETE') {
      state.edit = null;
      state.conflict = false;
      return json(res, 200, analysisRun());
    }
    if (pathname === '/v1/analysis-pipelines' && req.method === 'POST') {
      counts.regenerate += 1;
      state.revision = 2;
      state.conflict = Boolean(state.edit);
      return json(res, 202, {
        pipeline_run_id: 'pipeline-2',
        pipeline_id: 'meeting_default',
        status: 'queued',
        jobs: [{ job_id: 'analysis-job-2', analysis_run_id: 'structured-run-2', status: 'queued' }],
      });
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

  async setValue(selector, value) {
    const changed = await this.execute(`
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      const setter = Object.getOwnPropertyDescriptor(element.constructor.prototype, 'value')?.set;
      if (setter) setter.call(element, ${JSON.stringify(value)});
      else element.value = ${JSON.stringify(value)};
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    `);
    if (changed !== true) throw new Error(`input not found: ${selector}`);
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

async function waitAbsent(browser, needles, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = await browser.text();
    if (needles.every((needle) => !last.includes(needle))) return last;
    await sleep(150);
  }
  throw new Error(`timed out waiting for absence of ${needles.join(' | ')}; text=${last.slice(0, 1200)}`);
}

async function renderVideo() {
  const videoPath = path.join(evidenceRoot, 'video', 'verified-note-edit.mp4');
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
  if (!stat.size) throw new Error('verified-note-edit video is empty');
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
  await waitText(browser, ['Verified notes review'], 30000, true);
  await waitText(browser, ['Alex validates the release']);
  await waitText(browser, ['Revision 1', 'Revisione 1']);
  await checkpoint(browser, '01-evidence-ready');

  await browser.clickButton(['00:05 · Alex']);
  await waitText(browser, ['Audio']);
  await checkpoint(browser, '02-evidence-opens-audio');

  await browser.clickButton(['Edit', 'Modifica']);
  await browser.setValue('textarea', initialEditText);
  await checkpoint(browser, '03-editing-action');
  await browser.clickButton(['Save', 'Salva']);
  await waitText(browser, [initialEditText], 5000, true);
  await waitText(browser, ['Edited by you', 'Modificato da te']);
  await checkpoint(browser, '04-edit-saved');

  await browser.refresh();
  await waitText(browser, ['Verified notes review'], 5000, true);
  await waitText(browser, [initialEditText]);
  await waitText(browser, ['Edited by you', 'Modificato da te']);
  await checkpoint(browser, '05-restart-edit-persisted');

  await browser.clickButton(['Details', 'Dettagli']);
  await waitText(browser, ['Regenerate analysis only', 'Rigenera solo analisi']);
  await browser.clickButton(['Regenerate analysis only', 'Rigenera solo analisi']);
  await waitText(browser, [regeneratedText], 7000, true);
  await waitText(browser, ['Regeneration changed this item', 'La rigenerazione ha cambiato questa voce']);
  await waitText(browser, [initialEditText]);
  await waitText(browser, ['Revision 2', 'Revisione 2']);
  await checkpoint(browser, '06-regeneration-conflict');

  await browser.clickButton(['Keep my edit', 'Mantieni la mia modifica']);
  await waitText(browser, [initialEditText], 5000, true);
  await waitText(browser, ['Edited by you', 'Modificato da te']);
  await waitAbsent(browser, ['Regeneration changed this item', 'La rigenerazione ha cambiato questa voce']);
  await checkpoint(browser, '07-conflict-resolved-explicitly');

  if (counts.edit !== 2 || counts.regenerate !== 1) {
    throw new Error(`unexpected edit/regenerate counts: ${JSON.stringify(counts)}`);
  }
  if (!state.edit || state.edit.base_generated_hash !== 'generated-hash-v2' || state.conflict) {
    throw new Error(`final edit was not explicitly rebased: ${JSON.stringify(state)}`);
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
  journey_id: 'meeting-note-edit-revision',
  execution_environment: 'browser-macos-arm64-ci',
  fidelity_class: 'simulated_or_emulated',
  source_revision: sourceRevision,
  result: error ? 'FAIL' : 'PASS',
  requests: counts,
  checkpoints,
  video,
  assertions: {
    evidence_opens_audio: counts.audio >= 1,
    edit_persisted_across_reload: counts.edit >= 1,
    regeneration_created_revision: state.revision === 2,
    conflict_required_explicit_resolution: counts.edit === 2 && state.edit?.base_generated_hash === 'generated-hash-v2',
  },
  privacy_boundary: 'Synthetic fixture content only; captures are restricted to the headless Chrome viewport.',
  residual_fidelity_gaps: [
    'does not exercise the packaged WKWebView process boundary',
    'deterministic API fixtures do not prove the assembled FastAPI/CatalogStore persistence path',
    'does not prove TCC/native capture or production ASR/LLM quality, latency, memory or Metal behavior',
  ],
  error,
};
await fsp.writeFile(path.join(evidenceRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest, null, 2));
if (error) process.exitCode = 1;
