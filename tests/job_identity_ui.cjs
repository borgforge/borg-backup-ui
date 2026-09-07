const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

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
