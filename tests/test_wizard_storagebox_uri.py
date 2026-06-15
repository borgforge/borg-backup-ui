from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_wizard_storagebox_relative_base_path_becomes_uri_path():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('ui/js/pages/wizard.js', 'utf8');
const context = {
  window: { BBUI: {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  navigator: {},
  fetch: async () => ({ ok: false }),
};
vm.createContext(context);
vm.runInContext(code, context);
const cases = [
  ['./backup', '/./backup'],
  ['/./backup', '/./backup'],
  ['volume1/backup/', '/volume1/backup'],
];
for (const [raw, expected] of cases) {
  const actual = context.wizardStorageRepoBasePathForUri(raw);
  if (actual !== expected) {
    throw new Error(`${raw} -> ${actual}, expected ${expected}`);
  }
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
