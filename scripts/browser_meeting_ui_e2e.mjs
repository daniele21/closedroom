#!/usr/bin/env node
import { spawn } from 'node:child_process';
import path from 'node:path';

const root = path.resolve(process.cwd());
const canonicalEvidenceRoot = path.resolve(
  process.env.CLOSEDROOM_BROWSER_E2E_EVIDENCE
    || path.join(root, 'dist/evidence/browser-meeting-ui'),
);

const journeys = [
  {
    script: 'scripts/browser_saved_meeting_e2e.mjs',
    env: {},
  },
  {
    script: 'scripts/browser_meeting_preparation_e2e.mjs',
    env: {
      CLOSEDROOM_PREPARATION_E2E_EVIDENCE:
        process.env.CLOSEDROOM_PREPARATION_E2E_EVIDENCE
        || path.join(canonicalEvidenceRoot, 'preparation'),
    },
  },
  {
    script: 'scripts/browser_meeting_note_edit_e2e.mjs',
    env: {
      CLOSEDROOM_NOTE_EDIT_E2E_EVIDENCE:
        process.env.CLOSEDROOM_NOTE_EDIT_E2E_EVIDENCE
        || path.join(canonicalEvidenceRoot, 'note-edit'),
    },
  },
];

async function runJourney({ script, env }) {
  const child = spawn(process.execPath, [script], {
    cwd: root,
    env: { ...process.env, ...env },
    stdio: 'inherit',
  });
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', resolve);
  });
  if (code !== 0) {
    throw new Error(`${script} exited with code ${code}`);
  }
}

for (const journey of journeys) {
  await runJourney(journey);
}
