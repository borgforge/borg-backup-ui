const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

for (const language of ['de', 'en']) {
  test(`maintenance confirmation uses the selected job's name and full prefix (${language})`, async () => {
    const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
    const elements = new Map();
    const context = vm.createContext({
      window: {BBUI: {components: {i18n: {t(key, params = {}) {
        const label = key.split('.').reduce((value, part) => value?.[part], labels) || key;
        return label.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '');
      }}}}, addEventListener() {}},
      document: {getElementById(key) {
        if (!elements.has(key)) elements.set(key, {value: '', innerHTML: '',
          classList: {add() {}, remove() {}, contains() {return false;}}});
        return elements.get(key);
      }},
      escHtml: value => String(value),
    });
    vm.runInContext(fs.readFileSync('ui/js/pages/storage.js', 'utf8'), context);
    const alpha = {key: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name: 'Zulu',
      archive_prefix: 'Flash-Config', backup_type: 'old_type', location: 'local',
      retention: {daily: '14', weekly: '4', monthly: '6', yearly: '3'}};
    const zulu = {key: 'ffffffff-ffff-4fff-8fff-ffffffffffff', name: 'Alpha',
      archive_prefix: 'testdata-backup', backup_type: 'old_type', location: 'local',
      retention: {daily: '7', weekly: '4', monthly: '6', yearly: '3'}};
    const repo = {repository_key: 'shared', display_name: 'Repository title',
      job_name: 'Old repository job label', used_by: [alpha.key, zulu.key]};
    const state = context.window.BBUI.storageState;
    state.data = {groups: {local: [repo]}};
    state.jobs = [alpha, zulu];
    const confirmation = vm.runInContext("openStorageMaintenanceConfirm('shared', 'prune', 'quick')", context);
    const html = elements.get('storage-maintenance-confirm-info').innerHTML;
    assert.ok(html.includes('testdata-backup-*'));
    assert.ok(html.includes('Flash-Config-*'));
    assert.ok(html.includes('Repository title'));
    assert.ok(!html.includes('Old repository job label'));
    assert.ok(!html.includes(alpha.key + '-backup'));
    assert.ok(!html.includes(zulu.key + '-backup'));
    assert.ok(html.indexOf(`value="${zulu.key}"`) < html.indexOf(`value="${alpha.key}"`));
    context.document.getElementById('storage-maintenance-retention-job').value = alpha.key;
    vm.runInContext('updateStorageMaintenanceRetentionPreview()', context);
    const preview = elements.get('storage-maintenance-retention-preview').innerHTML;
    assert.ok(preview.includes('Zulu'));
    assert.ok(preview.includes('Flash-Config-*'));
    assert.ok(preview.includes('14'));
    assert.ok(!preview.includes('testdata-backup-*'));
    vm.runInContext('closeStorageMaintenanceConfirm(true)', context);
    const result = await confirmation;
    assert.equal(result.jobKey, alpha.key);
    assert.equal(result.confirmed, true);
    // An unlinked job with the same former type/location must not become a source.
    context.unlinked = {backup_type: 'old_type', location: 'local'};
    assert.equal(vm.runInContext('storageJobsForRepository(unlinked).length', context), 0);
    context.missingPrefix = {key: alpha.key};
    assert.equal(vm.runInContext('storageArchiveFilterFromJob(missingPrefix)', context), '');
  });
}

for (const language of ['de', 'en']) {
  test(`wizard accepts 100 characters and rejects longer names (${language})`, () => {
    const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
    const context = vm.createContext({
      window: {BBUI: {components: {i18n: {t(key) {
        return key.split('.').reduce((value, part) => value?.[part], labels) || key;
      }}}}, addEventListener() {}},
      document: {}, input: {job_name: 'ä'.repeat(100), archive_prefix: 'test-backup'}, error: '',
    });
    vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), context);
    vm.runInContext(`
      wizardClearError = () => { error = ''; };
      _wizardCollectParams = () => input;
      _wizardShowError = (step, message) => { error = message; };
    `, context);
    assert.equal(vm.runInContext('_wizardValidate(1)', context), true);
    context.input.job_name += 'ä';
    assert.equal(vm.runInContext('_wizardValidate(1)', context), false);
    assert.equal(context.error, labels.wizard.validationJobNameLength);
    assert.equal(vm.runInContext("wizardApiErrorMessage({code:'job_name_too_long'})", context), context.error);
  });
}

test('wizard schedules the saved UUID and retries without creating another job', async () => {
  const id = '645de013-df1e-49e3-89f0-39c9bb3e299b';
  const elements = new Map();
  const requests = [];
  let failSchedule = true;
  let closed = false;
  const context = vm.createContext({
    window: {BBUI: {core: {getSchedulesData: () => ({}), setSchedulesData() {}}}, addEventListener() {}},
    document: {getElementById(key) {
      if (!elements.has(key)) elements.set(key, {checked: true, classList: {add() {}, remove() {}}});
      return elements.get(key);
    }},
    jobsState: {},
    apiErrorMessage: data => data.error || '',
    refreshJobs: async () => {}, showMsg() {},
    fetch: async (url, options) => {
      requests.push({url, body: JSON.parse(options.body)});
      return url === '/api/wizard/save'
        ? {ok: true, json: async () => ({job_id: id, job_key: id})}
        : {ok: !failSchedule, status: failSchedule ? 500 : 200,
           json: async () => failSchedule ? {error: 'crontab failed'} : {saved: true}};
    },
    closePreview: () => {closed = true;},
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), context);
  vm.runInContext(`
    _wizardValidate = () => true;
    _wizardCollectParams = () => ({job_name: 'My job', archive_prefix: 'flash-config',
      existing_job_key: wizardState.existingJobKey, location: 'local'});
    _wizardBuildCron = () => '0 9 * * *';
    closeWizard = closePreview;
  `, context);
  assert.equal(vm.runInContext("_wizardArchivePrefix('flash-config')", context), 'flash-config');
  assert.equal(vm.runInContext("_wizardArchivePrefix('Flash-Config')", context), 'Flash-Config');
  await vm.runInContext('saveWizardJob()', context);
  assert.equal(requests[0].body.existing_job_key, '');
  assert.equal(requests[1].body.job_key, id);
  assert.equal(closed, false);
  assert.equal(context.window.BBUI.wizardState.existingJobKey, id);
  failSchedule = false;
  await vm.runInContext('saveWizardJob()', context);
  assert.equal(requests[2].body.existing_job_key, id);
  assert.equal(requests[3].body.job_key, id);
  assert.equal(closed, true);
});
