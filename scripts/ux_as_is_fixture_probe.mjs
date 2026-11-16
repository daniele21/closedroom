// Temporary UX field probe for deterministic synthetic browser fixtures.
// Not a product runtime feature; do not merge logging into the local-first app.
import { spawnSync } from 'node:child_process';

const selectedByJourney = {
  workspace: new Set([
    '01-wide-today', '02-meeting-child-of-today', '03-projects-container',
    '03c-activity-utility', '05-menubar-settings', '05-compact-window',
    '06-narrow-window',
  ]),
  meeting: new Set([
    '01-ready-core-only', '11-transcript-conversation-and-detail',
    '11a-speaker-review-ready', '20-stale-speaker-analysis',
    '23-empty-transcript-no-invented-turns',
    '26-compact-meeting-full-transcript-hydrated',
    '27a-analysis-outcomes-visible',
  ]),
  overlay: new Set([
    '01-overlay-recording', '03c-note-draft-resumed',
    '04-meeting-notes-cited', '04b-key-moment-group-stack',
    '07-screenshot-to-audio',
  ]),
  archive: new Set([
    '01-today-recent-only', '02-archive-hit',
    '06-full-library-archived-view-restored',
  ]),
  recording: new Set([
    '01-ready-before-start', '02-waiting-for-ai', '03-recording-active',
    '04-saved-and-ai-resumed', '06-recovery-actions',
  ]),
  preparation: new Set([
    '01-primary-action', '02-preparation-in-progress',
    '07-notes-ready-default-view',
  ]),
};

function inspectDom() {
  if (!['127.0.0.1', 'localhost'].includes(location.hostname))
    return { unexpectedHost: location.hostname };
  const viewport = { width: innerWidth, height: innerHeight };
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],[role="tab"],input,select,textarea'));
  const visible = nodes.filter(node => {
    const r = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.visibility !== 'hidden' && style.display !== 'none'
      && style.opacity !== '0' && r.width > 0 && r.height > 0
      && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
  });
  const label = node => (node.getAttribute('aria-label') || node.getAttribute('title')
    || node.innerText || node.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 62);
  const tiny = visible.filter(node => {
    const rect = node.getBoundingClientRect();
    return !node.disabled && (rect.width < 28 || rect.height < 28);
  });
  const unlabeled = visible.filter(node => !label(node));
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,[role="heading"]'))
    .filter(node => node.getBoundingClientRect().width > 0).slice(0, 10)
    .map(node => ({
      level: node.tagName,
      text: (node.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 72),
      y: Math.round(node.getBoundingClientRect().top),
    }));
  const sources = document.querySelector('[data-meeting-notes-sources="true"]');
  const gallery = document.querySelector('[data-meeting-screenshot-gallery="true"]');
  const rect = element => {
    const r = element?.getBoundingClientRect();
    return r ? { y: Math.round(r.top), height: Math.round(r.height) } : null;
  };
  const shell = document.querySelector('.workspace-shell');
  return {
    viewport, page: document.querySelector('.workspace-content')?.getAttribute('data-workspace-page') || null,
    hash: location.hash.slice(0, 50),
    documentWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    visibleControls: visible.length,
    smallControls: tiny.slice(0, 9).map(n => ({ label: label(n), size: [
      Math.round(n.getBoundingClientRect().width), Math.round(n.getBoundingClientRect().height),
    ]})),
    unlabeledControls: unlabeled.slice(0, 9).map(n => n.outerHTML.slice(0, 110)),
    headings,
    actionLabels: visible.slice(0, 16).map(label),
    screenshotSection: rect(sources), screenshotGallery: rect(gallery),
    transcriptTabVisible: Boolean(document.querySelector('#meeting-tab-transcript')?.getBoundingClientRect().width),
    shellHorizontalOverflow: Boolean(shell && shell.scrollWidth > shell.clientWidth + 1),
  };
}

export async function uxAuditCheckpoint(browser, journey, checkpoint, screenshot) {
  try {
    const metrics = await browser.execute('return (' + inspectDom.toString() + ')();');
    console.log('UX_AUDIT_METRICS ' + JSON.stringify({ journey, checkpoint, metrics }));
    if (!selectedByJourney[journey]?.has(checkpoint) || metrics.unexpectedHost) return;
    // The test browser uses loopback and synthetic fixtures only. Never call
    // this helper from live-meeting or user-data workflows.
    const ff = spawnSync('ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-i', screenshot,
      '-vf', 'scale=min(960\\,iw):-2', '-frames:v', '1',
      '-q:v', '12', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1',
    ], { encoding: null, maxBuffer: 2 * 1024 * 1024 });
    if (ff.status === 0 && ff.stdout?.length) {
      console.log('UX_AUDIT_IMAGE ' + journey + ' ' + checkpoint + ' '
        + Buffer.from(ff.stdout).toString('base64'));
    } else {
      console.log('UX_AUDIT_IMAGE_UNAVAILABLE ' + journey + ' ' + checkpoint + ' '
        + (ff.stderr ? String(ff.stderr).slice(0, 140) : ff.status));
    }
  } catch (e) {
    console.log('UX_AUDIT_DIAGNOSTIC_ERROR ' + journey + ' ' + checkpoint + ' ' + String(e));
  }
}
