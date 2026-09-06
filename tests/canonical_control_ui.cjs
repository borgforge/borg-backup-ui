const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const jobId = '11111111-1111-4111-8111-111111111111';

async function run(lang) {
  const dictionary = JSON.parse(fs.readFileSync(path.join(root, `ui/i18n/${lang}.json`)));
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: '', checked: true, textContent: '', innerHTML: '',
      classList: { add() {}, remove() {}, contains() { return false; } } });
    return elements.get(id);
  };
  let schedules = {};
  const calls = [];
  const context = vm.createContext({
    window: { addEventListener() {}, BBUI: { core: {
      getSchedulesData: () => schedules, setSchedulesData: value => { schedules = value; },
    }, components: { i18n: { t: (key, params = {}) => {
      const text = key.split('.').reduce((obj, part) => obj?.[part], dictionary);
      assert.equal(typeof text, 'string', `Missing ${lang} translation ${key}`);
      return text.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
    } } } } },
    document: { getElementById: element, addEventListener() {}, querySelectorAll: () => [] },
    escHtml: text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    showMsg() {}, apiErrorMessage: () => 'Synthetic failure',
    fetch: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({}) };
    },
  });
  for (const file of ['jobs', 'storage']) vm.runInContext(fs.readFileSync(path.join(root, `ui/js/pages/${file}.js`), 'utf8'), context);
  const evaluate = code => vm.runInContext(code, context);
  evaluate(`refreshJobs=async()=>{}; buildCronExpression=()=> '0 2 * * *'; closeScheduleModal=()=>{}; _onScheduleChanged=()=>{};
    jobsState.jobs=[{job_id:'${jobId}',name:'Current label',archive_prefix:'pfsense-backup',archive_prefixes:['pfsense-backup','config-backup'],repository_key:'repo',location:'local'}];
    storageState.jobs=jobsState.jobs; scheduleModalState.jobKey='${jobId}';`);
  await context.setJobEnabled(jobId, false);
  assert.deepEqual(calls.at(-1).body, { job_id: jobId, enabled: false });
  await context.saveScheduleAction();
  assert.deepEqual(calls.at(-1).body, { job_id: jobId, cron: '0 2 * * *', enabled: true });
  assert.ok(schedules[jobId]);
  await context.deleteScheduleAction();
  assert.deepEqual(calls.at(-1).body, { job_id: jobId });
  assert.ok(!schedules[jobId]);
  evaluate("scheduleModalState.jobKey='restore_test'");
  await context.saveScheduleAction();
  assert.deepEqual(calls.at(-1).body, { service: 'restore_test', cron: '0 2 * * *', enabled: true });
  await context.deleteScheduleAction();
  assert.deepEqual(calls.at(-1).body, { service: 'restore_test' });
  context._updateScheduleModalTitle(jobId);
  assert.ok(element('schedule-modal-title').textContent.includes('Current label'));
  const repo = { repository_key: 'repo', job_ids: [jobId], job_name: 'Stale name', display_name: 'Repository' };
  const jobs = context.storageJobsForRepository(repo);
  assert.equal(jobs.length, 1);
  assert.equal(context.storageJobName(repo, jobs[0]), 'Current label');
  assert.equal(context.storageArchiveFilterFromJob(jobs[0]), 'pfsense-backup-* | config-backup-*');
  assert.equal(context.storageJobsForRepository({ ...repo, job_ids: [], used_by: [jobId] }).length, 0);
  assert.equal(context.storageJobsForRepository({ ...repo, repository_key: 'other' }).length, 0);
  const details = context.storageMaintenancePruneDetailsHtml(repo, jobs[0]);
  assert.ok(details.includes('Current label') && details.includes('pfsense-backup-* | config-backup-*'));
}
(async () => { await run('de'); await run('en'); console.log('Canonical control UI: DE/EN passed'); })().catch(error => { console.error(error); process.exitCode=1; });
