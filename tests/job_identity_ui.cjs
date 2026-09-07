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
      document: {}, input: {job_id: '645de013-df1e-49e3-89f0-39c9bb3e299b', job_name: 'ä'.repeat(100), archive_prefix: 'test-backup'}, error: '',
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

function newJobWizardContext(language = 'en') {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const elements = new Map();
  const requests = [];
  function element(key) {
    if (!elements.has(key)) {
      const classes = new Set();
      elements.set(key, {id: key, value: '', style: {}, dataset: {}, checked: false,
        classList: {add: key => classes.add(key), remove: key => classes.delete(key),
          contains: key => classes.has(key), toggle(key, active) {active ? classes.add(key) : classes.delete(key);}},
        setAttribute() {}, removeAttribute() {}, addEventListener() {}, closest: () => null,
        querySelectorAll: () => [...elements.values()],
      });
    }
    return elements.get(key);
  }
  const context = vm.createContext({
    window: {BBUI: {components: {i18n: {t(key, params = {}) {
      const value = key.split('.').reduce((value, part) => value?.[part], labels) || key;
      return value.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '');
    }}}}, addEventListener() {}},
    document: {getElementById: element, body: element('body')},
    fetch(url, options) {return new Promise(resolve => requests.push({url, options, resolve}));},
    apiErrorMessage: data => data.message || 'Request failed',
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), context);
  // Keep identity lifecycle, form collection and navigation real; omit unrelated UI rendering.
  for (const name of ['wizardBindRuntimeControls', '_wizardSyncRiskAcknowledgement',
    'wizardCancelSourceSuggestRequest', 'wizardRenderSourcePaths', 'wizardCancelExcludeSuggestRequest',
    'wizardRenderExcludePaths', 'wizardUpdateRetentionManualLink', '_wizardScheduleApplyUI',
    'wizardSchedulePreview', 'wizardUpdateIconPreview', 'wizardRenderArchivePrefixSummary',
    'wizardAutoFill', 'wizardRenderRuntimeControls', 'wizardUpdateFinalRiskAcknowledgements']) {
    vm.runInContext(`${name} = () => {};`, context);
  }
  vm.runInContext(`
    wizardLoadStorageTargets = wizardLoadRepositories = wizardLoadRuntimeInventory = async () => {};
    wizardSelectedStorage = wizardSelectedRepository = () => ({});
    _wizardRuntimeMode = () => 'none';
    _wizardRiskAcknowledged = () => false;
  `, context);
  return {context, elements, requests, state: context.window.BBUI.wizardState};
}

test('new job shows one ID, preserves it during navigation, and discards it on cancel', async () => {
  const {context, elements, requests, state} = newJobWizardContext();
  const displayed = '645de013-df1e-49e3-89f0-39c9bb3e299b';
  vm.runInContext("openWizard({type: 'click'})", context);
  assert.equal(elements.get('wiz-job-id-group').hidden, false);
  assert.equal(elements.get('wizard-next-btn').disabled, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/wizard/new-job-id');
  assert.equal(requests[0].options.cache, 'no-store');
  requests[0].resolve({ok: true, json: async () => ({job_id: displayed})});
  await state.loadingPromise;
  assert.equal(elements.get('wiz-job-id').value, displayed);
  assert.equal(elements.get('wizard-next-btn').disabled, false);
  elements.get('wiz-job-name').value = 'New job';
  elements.get('wiz-archive-prefix').value = 'new-job-backup';
  await vm.runInContext('wizardNext()', context);
  assert.equal(state.step, 2);
  vm.runInContext('wizardBack()', context);
  assert.equal(state.jobId, displayed);
  assert.equal(vm.runInContext('_wizardCollectParams().job_id', context), displayed);
  vm.runInContext('closeWizard({force:true})', context);
  assert.equal(state.jobId, '');
  assert.equal(requests.length, 1); // Cancel sends no write or deletion request.
});

test('late ID replies cannot change a reopened wizard or an existing job', async () => {
  const {context, elements, requests, state} = newJobWizardContext();
  const oldId = '645de013-df1e-49e3-89f0-39c9bb3e299b';
  const newId = 'bc198590-b17b-4a30-a5c4-f721c45cdaea';
  vm.runInContext('openWizard()', context);
  const abandoned = state.loadingPromise;
  vm.runInContext('closeWizard({force:true}); openWizard()', context);
  requests[1].resolve({ok: true, json: async () => ({job_id: newId})});
  await state.loadingPromise;
  requests[0].resolve({ok: true, json: async () => ({job_id: oldId})});
  await abandoned;
  assert.equal(elements.get('wiz-job-id').value, newId);
  vm.runInContext('closeWizard({force:true}); openWizard()', context);
  const replaced = state.loadingPromise;
  vm.runInContext(`openWizard('${oldId}')`, context);
  assert.equal(requests.length, 3); // Edit initialization never generates a new ID.
  requests[2].resolve({ok: true, json: async () => ({job_id: newId})});
  await replaced;
  assert.equal(state.jobId, oldId);
  assert.equal(elements.get('wiz-job-id').value, oldId);
});

for (const language of ['de', 'en']) {
  test(`failed or invalid ID responses keep the wizard from continuing (${language})`, async () => {
    for (const response of [{ok:false, message:'Unavailable'}, {ok:true, job_id:'not-a-uuid'},
      {ok:true}, {ok:true, job_id:['645de013-df1e-49e3-89f0-39c9bb3e299b']}]) {
      const {context, elements, requests, state} = newJobWizardContext(language);
      vm.runInContext('openWizard()', context);
      requests[0].resolve({ok: response.ok, status:503, json: async () => response});
      await state.loadingPromise;
      assert.equal(state.jobId, '');
      assert.equal(elements.get('wizard-next-btn').disabled, true);
      assert.equal(elements.get('wizard-error-1').classList.contains('hidden'), false);
      assert.ok(elements.get('wizard-error-1').textContent.includes(language === 'de' ? 'erneut öffnen' : 'reopen'));
      assert.equal(vm.runInContext('_wizardValidate(9)', context), false);
    }
  });
}
