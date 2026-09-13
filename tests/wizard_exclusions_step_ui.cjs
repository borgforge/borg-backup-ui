const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function wizard() {
  const fields = new Map();
  for (const [, id] of fs.readFileSync('ui/index.html', 'utf8').matchAll(/id="([^"]+)"/g)) {
    const classes = new Set();
    fields.set(id, {value: '', checked: false, style: {},
      setAttribute() {}, removeAttribute() {}, querySelectorAll: () => [],
      classList: {add: c => classes.add(c), remove: c => classes.delete(c),
        contains: c => classes.has(c),
        toggle(c, force) { if (force ?? !classes.has(c)) classes.add(c); else classes.delete(c); }}});
  }
  const context = vm.createContext({
    window: {addEventListener() {}},
    document: {getElementById: id => fields.get(id)},
    escHtml: String,
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), context);
  const state = vm.runInContext('wizardState', context);
  Object.assign(state, {jobId: 'test-id', sourcePaths: ['/mnt/user/data'],
    excludePaths: ['/mnt/user/data/cache'], excludeFile: {original_name: 'rules.txt', sha256: 'hash'},
    excludeFileError: false, unlockedStep: 9});
  for (const [id, value] of Object.entries({'wiz-job-name': 'Test', 'wiz-archive-prefix': 'test-backup',
    'wiz-retention-mode': 'tiered', 'wiz-keep-hourly': '0', 'wiz-keep-daily': '7',
    'wiz-keep-weekly': '4', 'wiz-keep-monthly': '6', 'wiz-keep-yearly': '3',
    'wiz-repository-key': 'repo', 'wiz-exclude-markers': '.nobackup\n.NOBACKUP',
    'wiz-docker-mode': 'all', 'wiz-vm-mode': 'all'})) fields.get(id).value = value;
  context.wizardSelectedStorage = () => ({storage_key: 'storage'});
  context.wizardSelectedRepository = () => ({repository_key: 'repo'});
  let previews = 0;
  context._wizardPreview = async () => { previews++; };
  return {context, state, fields, previews: () => previews};
}

test('all runtime combinations include exclusions and preserve values through next/back/preview', async () => {
  for (const docker of [false, true]) for (const vms of [false, true]) {
    const {context, state, fields, previews} = wizard();
    fields.get('wiz-use-docker').checked = docker;
    fields.get('wiz-use-vm').checked = vms;
    const before = JSON.stringify(context._wizardCollectParams());
    const steps = [1, 2, 3, ...(docker ? [4] : []), ...(vms ? [5] : []), 6, 7, 8, 9];
    context._renderWizardStep(1);
    for (const step of steps.slice(1)) {
      await context.wizardNext();
      assert.equal(state.step, step);
      assert.equal(fields.get(`wstep-dot-${step}`).disabled, false);
      assert.equal(fields.get(`wizard-step-${step}`).classList.contains('hidden'), false);
    }
    assert.equal(previews(), 1);
    for (const step of steps.slice(0, -1).reverse()) {
      context.wizardBack();
      assert.equal(state.step, step);
    }
    await context.wizardGoToStep(6);
    assert.equal(state.step, 6);
    await context.wizardGoToStep(3);
    assert.equal(state.step, 3);
    assert.equal(JSON.stringify(context._wizardCollectParams()), before);
  }
});

test('errors block navigation on the correct step after the insertion', async () => {
  const {context, state, fields} = wizard();
  state.excludeFileError = true;
  context._renderWizardStep(2);
  await context.wizardGoToStep(6);
  assert.equal(state.step, 3);
  assert.match(fields.get('wizard-error-3').textContent, /exclusionInvalid/);
  state.excludeFileError = false;
  fields.get('wiz-use-docker').checked = true;
  fields.get('wiz-docker-mode').value = 'selected';
  await context.wizardGoToStep(6);
  assert.equal(state.step, 4);
  assert.match(fields.get('wizard-error-4').textContent, /validationDockerSelection/);
  state.selectedDockerContainers = ['container'];
  fields.get('wiz-use-vm').checked = true;
  fields.get('wiz-vm-mode').value = 'selected';
  await context.wizardGoToStep(6);
  assert.equal(state.step, 5);
  assert.match(fields.get('wizard-error-5').textContent, /validationVmSelection/);
  state.selectedVms = ['vm'];
  fields.get('wiz-retention-mode').value = 'last';
  fields.get('wiz-keep-last').value = '0';
  await context.wizardGoToStep(9);
  assert.equal(state.step, 6);
  assert.match(fields.get('wizard-error-6').textContent, /validationRetentionInvalid/);
});
