// Focused E4 proof: execute the actual shared TypeScript helper via local compiler.
// No app build, external service or test framework.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const requireFrontend = createRequire(path.join(root, 'frontend', 'package.json'));
const ts = requireFrontend('typescript');
const helperPath = path.join(root, 'frontend/src/utils/capturePermissionMessages.ts');
const compiled = ts.transpileModule(fs.readFileSync(helperPath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
vm.runInNewContext(compiled.outputText, { exports }, { filename: helperPath });
const { getNativeCaptureUnavailableMessage, capturePermissionFailureMessage } = exports;
assert.equal(typeof getNativeCaptureUnavailableMessage, 'function');
assert.equal(typeof capturePermissionFailureMessage, 'function');
const t = (key) => key;

const reasonCases = [
  ['screen_capture_stream_pending', 'recording.nativeCapturePendingReason'],
  ['helper_missing', 'recording.nativeCaptureHelperMissingReason'],
  ['macos_required', 'recording.nativeCaptureMacosRequiredReason'],
  ['macos_14_required', 'recording.nativeCaptureMacosRequiredReason'],
  ['screen_recording_permission_required', 'recording.nativeCaptureScreenPermissionReason'],
  ['microphone_permission_required', 'recording.nativeCaptureMicPermissionReason'],
  ['', 'recording.nativeCaptureUnavailableUnknown'],
  ['new_future_capability_reason', 'new_future_capability_reason'],
];
for (const [reason, expected] of reasonCases) {
  assert.equal(getNativeCaptureUnavailableMessage(reason, t), expected, reason);
}
const diagnosticCases = [
  [{ code_signature: 'unsigned', bundle_identifier: 'other.bundle' }, 'recording.permissionsUnsignedHelper'],
  [{ code_signature: 'signed', bundle_identifier: 'other.bundle' }, 'recording.permissionsInvalidHelper'],
  [{ code_signature: 'signed', bundle_identifier: 'com.closedroom.nativecapture' }, 'recording.permissionsRequired'],
  [{ code_signature: '', bundle_identifier: '' }, 'recording.permissionsRequired'],
  [undefined, 'recording.permissionsRequired'],
  [null, 'recording.permissionsRequired'],
];
for (const [diagnostics, expected] of diagnosticCases) {
  assert.equal(capturePermissionFailureMessage(diagnostics, t), expected);
}
// Only the UI copy is shared: permission requests, capture mode and recorder
// lifecycle remain page-owned.
for (const page of ['NewRecordingPage', 'RecordingPage']) {
  const source = fs.readFileSync(path.join(root, 'frontend/src/pages', page + '.tsx'), 'utf8');
  assert.match(source, /getNativeCaptureUnavailableMessage\(nativeCaptureUnavailableReason, t\)/);
  assert.match(source, /capturePermissionFailureMessage\(result\.diagnostics, t\)/);
  assert.match(source, /ApiClient\.ensureCapturePermissions\(/);
  assert.match(source, /recorder\.refreshCapturePermissions\(\)/);
  assert.doesNotMatch(source, /result\.diagnostics\?\.code_signature/);
}
console.log('PASS E4 shared messages: ' + (reasonCases.length + diagnosticCases.length) + ' behavior cases and both screens');
