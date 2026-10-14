#!/usr/bin/env node
// Deterministic UI evidence. This does not prove native audio, TCC or MLX/Metal.
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
const root = process.cwd();
const evidence = path.resolve(process.env.CLOSEDROOM_ACTIVITIES_EVIDENCE || 'dist/evidence/browser-activities');
const chrome = process.env.CHROME_BINARY || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const port = async () => { const s = net.createServer(); await new Promise((r) => s.listen(0, '127.0.0.1', r)); const p = s.address().port; await new Promise((r) => s.close(r)); return p; };
const [backendPort, vitePort, debugPort] = await Promise.all([port(), port(), port()]);
const fixture = (id, status, type = 'transcription') => ({ id, status, type, scope_type: 'recording', scope_id: id, source_label: `Synthetic ${id}`, current_step: status, progress: 50, created_at: 1791970000, updated_at: 1791970000 });
let jobs = [fixture('first', 'transcribing_mic'), fixture('second', 'queued')];
let offline = false;
let captureBlocked = false;
let cancelCount = 0;
let importCount = 0;
let importedJobCount = 0;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const json = (value, code = 200) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(value)); };
  if (url.pathname === '/health') return json({ ok: true, default_model: 'synthetic', status: 'idle' });
  if (req.method === 'POST' && url.pathname === '/v1/recordings/import-audio') {
    importCount++;
    // Keep the request open so navigation happens while the server is
    // receiving/publishing a local source. No imported audio is logged.
    req.resume();
    req.on('end', () => setTimeout(() => json({
      id: 'imported-source', title: 'local-clip', status: 'recorded',
      capture_backend: 'import', capture_status: 'stopped',
      mime_type: 'audio/wav', audio_file: 'recording.wav',
      bytes_written: 48, created_at: '2026-10-14T12:00:00Z',
    }, 201), 1200));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/v1/recordings/imported-source/transcription-jobs') {
    importedJobCount++;
    const job = { ...fixture('imported-job', 'queued'), scope_id: 'imported-source', source_label: 'local-clip' };
    jobs.push(job);
    return json(job, 202);
  }
  if (url.pathname === '/v1/transcription/source-data') return json({ recordings: [], projects: [], settings: {} });
  if (url.pathname === '/v1/activities') return offline ? json({ detail: 'offline' }, 503) : json({ items: jobs, capture_blocked: captureBlocked, active_count: jobs.some((j) => j.status === 'transcribing_mic') ? 1 : 0, queue_depth: jobs.filter((j) => j.status === 'queued').length });
  if (url.pathname === '/v1/meetings/first') return json({
    id: 'first', recording: { id: 'first', title: 'Synthetic Meeting progress', project_name: 'E2E', status: 'recorded', mime_type: 'audio/wav', audio_file: 'synthetic.wav', bytes_written: 100, created_at: '2026-10-14T10:00:00Z', stopped_at: '2026-10-14T10:05:00Z', duration_seconds: 300 },
    transcription: null, analysis_runs: [], latest_analysis: {}, jobs, status: 'recorded', project_name: 'E2E', created_at: '2026-10-14T10:00:00Z', updated_at: '2026-10-14T10:05:00Z',
  });
  if (/^\/v1\/jobs\/[^/]+\/events$/.test(url.pathname)) {
    const id = url.pathname.split('/')[3];
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    let sequence = 0;
    const send = () => { const item = jobs.find((j) => j.id === id); if (item) res.write(`data: ${JSON.stringify({ ...item, sequence: ++sequence })}\n\n`); };
    send();
    const interval = setInterval(send, 150);
    req.on('close', () => clearInterval(interval));
    return;
  }
  if (/^\/v1\/jobs\/[^/]+$/.test(url.pathname)) return json(jobs.find((j) => j.id === url.pathname.split('/')[3]) || {});
  if (url.pathname.includes('/screenshots') || url.pathname.includes('/notes')) return json({ items: [] });
  if (url.pathname.endsWith('/cancel')) { cancelCount++; jobs = jobs.map((j) => url.pathname.includes(j.id) ? { ...j, status: 'cancelled', current_step: 'cancelled' } : j); return json({}); }
  if (url.pathname === '/v1/session') return json({ ok: true });
  if (url.pathname === '/v1/projects' || url.pathname === '/v1/meetings') return json({ items: [] });
  if (url.pathname.startsWith('/brand/')) { res.writeHead(404); return res.end(); }
  return json({});
});
await new Promise((r) => server.listen(backendPort, '127.0.0.1', r));
await fs.mkdir(evidence, { recursive: true });
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'closedroom-activities-'));
const children = [];
let socket;
let timer;
let busyCapture = false;
let frame = 0;
const checkpoints = [];
let failed;
try {
  const vite = spawn('pnpm', ['exec', 'vite', '--host', '127.0.0.1', '--port', `${vitePort}`, '--strictPort'], { cwd: path.join(root, 'frontend'), env: { ...process.env, BACKEND_PORT: `${backendPort}` }, stdio: 'ignore' });
  children.push(vite);
  const browser = spawn(chrome, ['--headless=new', '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
  children.push(browser);
  const ready = async (url) => { for (let i = 0; i < 100; i++) { try { const r = await fetch(url); if (r.ok) return r; } catch {} await sleep(100); } throw new Error(`Not ready: ${url}`); };
  await ready(`http://127.0.0.1:${vitePort}`);
  const targets = await (await ready(`http://127.0.0.1:${debugPort}/json/list`)).json();
  socket = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r, reject) => { socket.addEventListener('open', r, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', ({ data }) => { const msg = JSON.parse(data); if (msg.id && pending.has(msg.id)) { const { resolve, reject, timeout } = pending.get(msg.id); clearTimeout(timeout); pending.delete(msg.id); msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result); } });
  const call = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 10000); pending.set(id, { resolve, reject, timeout }); socket.send(JSON.stringify({ id, method, params })); });
  const evaluate = async (expression) => { const value = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails)); return value.result.value; };
  const assert = async (expression, label) => { for (let i = 0; i < 80; i++) { if (await evaluate(expression)) return; await sleep(100); } throw new Error(label); };
  const screenshot = async (filename) => { const shot = await call('Page.captureScreenshot', { format: 'png' }); await fs.writeFile(path.join(evidence, filename), Buffer.from(shot.data, 'base64')); };
  const checkpoint = async (name) => { await screenshot(`${name}.png`); checkpoints.push(name); };
  const refresh = () => evaluate(`document.querySelector('[data-activities-page] header button').click()`);
  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', { width: 1200, height: 900, deviceScaleFactor: 1, mobile: false });
  await call('Page.navigate', { url: `http://127.0.0.1:${vitePort}/#activities` });
  await assert(`!!document.querySelector('[data-activities-page]') && document.querySelectorAll('[data-activity-id]').length === 2`, 'active legacy ASR plus queued job visible');
  await fs.mkdir(path.join(evidence, 'frames'), { recursive: true });
  timer = setInterval(async () => { if (busyCapture) return; busyCapture = true; try { await screenshot(`frames/frame-${String(frame++).padStart(4, '0')}.png`); } catch (error) { failed ||= String(error); } finally { busyCapture = false; } }, 250);
  await assert(`document.querySelector('[data-activity-id="first"] [role="progressbar"]').getAttribute('aria-valuenow') === null && !document.querySelector('[data-activity-id="second"] [role="progressbar"]')`, 'phase percentages never presented as measured');
  await checkpoint('01-running-and-queued');
  jobs[0].progress_detail = { kind: 'asr_track_progress', phase: 'transcribing', track_id: 'mic', track_label: 'Microphone', track_index: 1, track_count: 2, track_percent: 40, processed_audio_seconds: 120, audio_duration_seconds: 300, elapsed_seconds: 20, eta_seconds: 30 };
  await refresh();
  await assert(`document.querySelector('[data-activity-id="first"] [role="progressbar"]').getAttribute('aria-valuenow') === '40' && document.body.innerText.includes('2:00/5:00')`, 'measured audio progress displayed');
  await checkpoint('02-measured-progress');
  await evaluate(`location.hash = '#projects'`);
  await assert(`!document.querySelector('[data-activities-page]')`, 'navigation leaves activities');
  await evaluate(`location.hash = '#activities'`);
  await assert(`!!document.querySelector('[data-activity-id="first"]')`, 'jobs survive navigation');
  await call('Emulation.setDeviceMetricsOverride', { width: 680, height: 900, deviceScaleFactor: 1, mobile: false });
  await checkpoint('03-return-compact');
  captureBlocked = true;
  await refresh();
  await assert(`document.body.innerText.includes('recording to end') || document.body.innerText.includes('termini la registrazione')`, 'capture wait explained');
  await checkpoint('04-capture-wait');
  offline = true;
  await refresh();
  await assert(`!!document.querySelector('[data-activities-page] [role="alert"]') && !!document.querySelector('[data-activity-id="first"]')`, 'offline retains stale state');
  await checkpoint('05-offline');
  offline = false;
  captureBlocked = false;
  await refresh();
  await assert(`!document.querySelector('[data-activities-page] [role="alert"]')`, 'reconnect reconciles');
  await evaluate(`document.querySelector('[data-activity-id="second"] button.text-danger').click()`);
  await assert(`!document.querySelector('[data-activity-id="second"] [data-meeting-job-progress]')`, 'queued cancellation becomes terminal');
  if (cancelCount !== 1) throw new Error('cancel submitted more than once');
  jobs[0] = { ...jobs[0], status: 'completed', current_step: 'completed' };
  await refresh();
  await assert(`!document.querySelector('[data-activity-id="first"] [data-meeting-job-progress]')`, 'completed moves to history');
  await checkpoint('06-terminal-history');
  await evaluate(`document.querySelector('[data-activity-id="first"] button').click()`);
  await assert(`location.hash === '#meeting/first'`, 'open result navigates to source');
  const detail = { kind: 'asr_track_progress', phase: 'transcribing', track_id: 'mic', track_label: 'Microphone', track_index: 1, track_count: 2, track_percent: 40, processed_audio_seconds: 120, audio_duration_seconds: 300, elapsed_seconds: 20, eta_seconds: 30 };
  jobs = [{ ...fixture('first', 'transcribing_mic'), progress_detail: detail }];
  await evaluate(`location.hash = '#projects'`);
  await assert(`!document.querySelector('[data-meeting-job-progress]')`, 'leave result');
  await evaluate(`location.hash = '#meeting/first'`);
  await assert(`document.querySelector('[data-meeting-job-progress] [role="progressbar"]')?.getAttribute('aria-valuenow') === '40'`, 'Meeting shows legacy active status with measured progress');
  jobs[0] = { ...jobs[0], status: 'transcribing_system', current_step: 'transcribing_system', progress_detail: { ...detail, track_id: 'system', track_label: 'Computer', track_percent: 65, processed_audio_seconds: 195 } };
  await assert(`document.querySelector('[data-meeting-job-progress] [role="progressbar"]')?.getAttribute('aria-valuenow') === '65'`, 'Meeting follows phase transition via SSE');
  await checkpoint('07-meeting-measured-sse');
  jobs = [{ ...fixture('parent', 'running', 'meeting_preparation'), scope_id: 'first', current_step: 'preparing_transcript' }, { ...fixture('child', 'transcribing_mic'), scope_id: 'first', parent_job_id: 'parent', progress_detail: detail }];
  await evaluate(`location.hash = '#projects'`);
  await assert(`!document.querySelector('[data-meeting-job-progress]')`, 'leave standalone job');
  await evaluate(`location.hash = '#meeting/first'`);
  await assert(`document.querySelectorAll('[data-meeting-job-progress]').length === 1 && document.querySelector('[data-meeting-job-progress] [role="progressbar"]')?.getAttribute('aria-valuenow') === '40'`, 'Preparation presents measured child once');
  jobs[1].progress_detail = { ...detail, track_percent: 70, processed_audio_seconds: 210 };
  await assert(`document.querySelector('[data-meeting-job-progress] [role="progressbar"]')?.getAttribute('aria-valuenow') === '70'`, 'Preparation follows measured child SSE');
  await checkpoint('08-parent-child-progress');

  // A file import belongs to MainApp, so routing away cannot lose the
  // upload->job handoff. This is a deterministic simulated local backend.
  await evaluate(`location.hash = '#transcription'`);
  await assert(`document.querySelectorAll('button').length > 5 && document.body.innerText.includes('Sorgente')`, 'transcription source view ready');
  await evaluate(`Array.from(document.querySelectorAll('button')).find((b) => /^(File audio|Audio file|File)$/i.test(b.innerText.trim()))?.click()`);
  await assert(`!!document.querySelector('input[type=file]')`, 'audio import source input present');
  await evaluate(`(() => {
    const input = document.querySelector('input[type=file]');
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array(48)], 'local-clip.wav', { type: 'audio/wav' }));
    Object.defineProperty(input, 'files', { configurable: true, value: transfer.files });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await assert(`document.querySelector('audio[controls]') && document.querySelector('button.w-full.mt-4')`, 'file config view ready');
  await evaluate(`document.querySelector('button.w-full.mt-4').click()`);
  await assert(`location.hash === '#activities' && !!document.querySelector('[data-audio-import]')`, 'upload visible globally while in progress');
  await checkpoint('09-importing-audio');
  await evaluate(`location.hash = '#projects'`);
  await assert(`!document.querySelector('[data-audio-import]')`, 'navigating away unmounts only the import view');
  await sleep(1600);
  await evaluate(`location.hash = '#activities'`);
  await assert(`!!document.querySelector('[data-activity-id="imported-job"]')`, 'job survives navigation and follows persisted discovery');
  if (importCount !== 1 || importedJobCount !== 1) throw new Error('upload or ASR job admitted more than once');
  await checkpoint('10-imported-job-after-navigation');

} catch (error) { failed = String(error.stack || error); }
finally {
  clearInterval(timer);
  while (busyCapture) await sleep(50);
  socket?.close();
  for (const child of children.reverse()) { child.kill('SIGTERM'); await Promise.race([new Promise((r) => child.once('exit', r)), sleep(3000)]); if (child.exitCode === null) child.kill('SIGKILL'); }
  await new Promise((r) => server.close(r));
  await fs.rm(profile, { recursive: true, force: true });
}
if (frame > 0) {
  const ffmpeg = spawn('ffmpeg', ['-y', '-framerate', '4', '-i', path.join(evidence, 'frames/frame-%04d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', path.join(evidence, 'activities.mp4')], { stdio: 'ignore' });
  const code = await new Promise((r) => ffmpeg.once('exit', r));
  if (code !== 0) failed ||= 'Media encoding failed';
}
await fs.writeFile(path.join(evidence, 'manifest.json'), JSON.stringify({ status: failed ? 'FAIL' : 'PASS', source_revision: process.env.E2E_SOURCE_REVISION || 'working-tree', fidelity: 'host_or_fake', evidence_mode: 'full_media', checkpoints, video: frame > 0 ? 'activities.mp4' : null, error: failed, known_gaps: ['WKWebView', 'physical audio/TCC', 'MLX/Metal'] }, null, 2));
if (failed) { console.error(failed); process.exitCode = 1; } else console.log(`PASS Activities UI; ${checkpoints.length} checkpoints: ${evidence}`);
