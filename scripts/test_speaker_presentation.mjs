#!/usr/bin/env node
// Contract tests execute the actual TypeScript source, with type-only imports
// stripped by the same TypeScript dependency used to build the UI.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const requireFrontend = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = requireFrontend('typescript');
const source = readFileSync(new URL('../frontend/src/utils/speakerPresentation.ts', import.meta.url), 'utf8');
const transpiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { speakerDisplay, canJoinConversationTurns } = await import(
  'data:text/javascript;base64,' + Buffer.from(transpiled).toString('base64')
);

const legacy = { id: 1, start: 4, end: 8, text: 'Hello', source: 'system', speaker_label: 'Computer' };
const old = structuredClone(legacy);
assert.deepEqual(speakerDisplay(legacy, [], ['Computer']), {
  key: null, label: 'Audio non attribuito', needsIdentification: false,
});
assert.equal(speakerDisplay(legacy, [], ['Computer'], 'en').label, 'Unattributed audio');
assert.deepEqual(legacy, old, 'read projection cannot mutate the original segment');
assert.equal(canJoinConversationTurns(legacy, { ...legacy, id: 2, start: 8, end: 10 },
  [], ['Computer']), false, 'unattributed source cannot imply a shared person');

const mappings = [{ speaker_cluster: 'system:S1', speaker_group: 'system:S1',
  display_name: 'Computer', status: 'unassigned' }];
const voice = { ...legacy, provider_speaker: 'system:S1' };
assert.equal(speakerDisplay(voice, mappings, ['Computer']).label, 'Voce da identificare');
assert.equal(speakerDisplay(voice, mappings, ['Computer']).key, 'system:S1');
assert.equal(speakerDisplay(voice, mappings, ['Computer']).needsIdentification, true);
assert.equal(speakerDisplay(voice, [{ ...mappings[0], status: 'accepted' }], ['Computer']).label,
  'Computer', 'an explicitly confirmed person must not be silently renamed');

const group = [
  { speaker_cluster: 'system:S1', speaker_group: 'system:S1', display_name: 'Giuseppe', status: 'accepted' },
  { speaker_cluster: 'system:S2', speaker_group: 'system:S1', display_name: 'Giuseppe', status: 'merged' },
];
const first = { id: 1, start: 0, end: 4, text: 'First', provider_speaker: 'system:S1' };
const next = { id: 2, start: 5, end: 8, text: 'Second', provider_speaker: 'system:S2' };
assert.equal(canJoinConversationTurns(first, next, group), true, 'explicit merged voice should group');
assert.equal(speakerDisplay(next, group).needsIdentification, false,
  'confirmed canonical person means merged clusters are not pending');
assert.equal(canJoinConversationTurns(first, { ...next, overlap: true }, group), false);
assert.equal(canJoinConversationTurns(first, { ...next, start: 20 }, group), false);
assert.equal(canJoinConversationTurns(first, { ...next, start: 3 }, group), false);
assert.equal(canJoinConversationTurns(first, next, [
  { ...group[0], speaker_group: 'system:S1' }, { ...group[1], speaker_group: 'system:S2' },
]), false, 'same displayed name does not imply same speaker identity');

// A source-track label can be "Tu", but it is not a human confirmation.
const selfVoice = { id: 42, start: 52, end: 54, text: 'Ciao',
  track_id: 'mic', provider_speaker: 'mic:S1', speaker_label: 'Tu' };
const pendingSelf = [{ speaker_cluster: 'mic:S1', speaker_group: 'mic:S1',
  display_name: 'Tu', status: 'unassigned' }];
assert.equal(speakerDisplay(selfVoice, pendingSelf, ['Tu']).label, 'Voce da identificare');
assert.equal(speakerDisplay(selfVoice, pendingSelf, ['Tu']).needsIdentification, true);
const confirmedSelf = [{ ...pendingSelf[0], status: 'accepted' }];
assert.deepEqual(speakerDisplay(selfVoice, confirmedSelf, ['Tu']), {
  key: 'mic:S1', label: 'Tu', needsIdentification: false,
});
assert.equal(speakerDisplay(selfVoice, confirmedSelf, ['Tu'], 'en').label, 'Tu');

console.log('Speaker presentation and grouping contracts PASS');
