const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function fixture(language = 'en') {
  const elements = new Map(['restore-tests-plan-summary', 'restore-tests-plan-content', 'rt-run-btn']
    .map(id => [id, { innerHTML: '', classList: { toggle() {} } }]));
  const translations = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const requests = [];
  let snapshot = { running: false, runs: [], active_job_keys: [] };
  let failed = false;
  let posted = false;
  let confirmed = true;
  let cancelError = false;
  const messages = [];
  const withRuns = value => ({...value, active_jobs: value.active_jobs || (value.active_job_keys || []).map(job_key => ({job_key, run_id: 'run-' + job_key, run_key: 'restore_test_' + job_key, cancel_allowed: true, cancel_requested: false, activity_state: 'running'}))});
  const plan = { jobs: ['alpha', 'beta', 'disabled'].map(job_key => ({
    job_key, name: job_key, display_name: job_key, location: job_key === 'beta' ? 'usb' : 'local',
    enabled: job_key !== 'disabled', scheduler_state: 'active', policy: { mode: 'scheduled', level: 2 },
  })) };
  const context = vm.createContext({
    window: { BBUI: { components: { i18n: {
      t: key => key.split('.').reduce((v, part) => v?.[part], translations) || key,
      getLanguage: () => language,
    } } } },
    document: { getElementById: id => elements.get(id) || null },
    patchJobMarkup: (el, html) => { el.innerHTML = html; },
    resolveJobIcon: job => job.icon || 'archive', resolveJobIconColor: job => job.icon_color || '',
    setInterval: () => 1, clearInterval() {}, showMsg: (...args) => messages.push(args), apiErrorMessage: () => 'error',
    fetch: async (url, options = {}) => {
      requests.push([url, options.method || 'GET', options.body && JSON.parse(options.body)]);
      if (url.endsWith('/cancel')) {
        if (!cancelError) snapshot.active_jobs.forEach(run => { if (run.run_id === JSON.parse(options.body).run_id) run.cancel_requested = true; });
        return {ok: !cancelError, status: cancelError ? 409 : 200, json: async () => ({cancel_requested: !cancelError})};
      }
      if (options.method === 'POST') {
        posted = true;
        snapshot = withRuns({ running: true, active_job_keys: ['alpha'], run_key: 'restore_test_alpha' });
        return { ok: true, json: async () => snapshot };
      }
      if (url.includes('/running')) {
        if (failed === 'network') throw new Error('offline');
        return { ok: !failed, json: async () => {
          if (failed === 'json') throw new SyntaxError('invalid JSON');
          return snapshot;
        } };
      }
      return { ok: true, json: async () => url.endsWith('/plan') ? plan : { tests: [] } };
    },
  });
  vm.runInContext(fs.readFileSync('ui/js/utils/format.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('ui/js/pages/dashboard.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('ui/js/pages/restore-tests.js', 'utf8'), context);
  // Isolate the plan from unrelated report/sidebar/log rendering.
  vm.runInContext(`
    _openRTLogPanel = () => {};
    renderRTReportFilterOptions = renderRestoreTests = renderRestoreTestsSubtab =
      _updateRTScheduleBtn = refreshRestoreTestJobsForSelection = renderRestoreTestsSidebar =
      updateRestoreTestsWorkspace = () => {};
  `, context);
  context.window.BBUI.core = { getSchedulesData: () => ({}), setSchedulesData() {} };
  context._openRTStartConfirmModal = async () => confirmed;
  const state = context.window.BBUI.restoreTestsState;
  state.plan = plan;
  return { context, state, requests, plan, setSnapshot: value => { snapshot = withRuns(value); },
    confirm: value => {confirmed = value;}, cancelError: () => {cancelError = true;}, messages,
    fail: value => { failed = value; }, posted: () => posted,
    row: key => elements.get('restore-tests-plan-content').innerHTML.match(new RegExp(`<article[^>]*data-rt-job-key="${key}"[\\s\\S]*?</article>`))?.[0],
  };
}

for (const language of ['de', 'en']) test(`opening plan restores parallel run labels (${language})`, async () => {
  const f = fixture(language);
  f.setSnapshot({ running: true, run_key: 'restore_test_alpha', active_job_keys: ['alpha', 'beta'] });
  await f.context.refreshRestoreTests();
  for (const key of ['alpha', 'beta']) {
    assert.match(f.row(key), /rt-plan-running/);
    assert.match(f.row(key), /btn-danger[^>]*data-rt-plan-action="cancel"[^>]*aria-busy="false"/);
    assert.match(f.row(key), language === 'de' ? /Läuft/ : /Running/);
  }
  assert.doesNotMatch(f.row('disabled'), /rt-plan-running/);
  assert.ok(f.state.pollingTimer);
});

test('polling detects scheduled starts, batch transitions and completion without affecting other jobs', async () => {
  const f = fixture();
  await f.context.refreshRestoreTests();
  f.setSnapshot({ active_job_keys: ['alpha'] });
  await f.context._pollRTRunning();
  assert.match(f.row('alpha'), /btn-danger/);
  assert.match(f.row('beta'), /btn-primary[^>]*aria-busy="false"[^>]*>/);
  f.state.selectedLocation = 'usb';
  f.setSnapshot({ active_job_keys: ['beta'] });
  await f.context._pollRTRunning();
  assert.equal(f.row('alpha'), undefined);
  assert.match(f.row('beta'), /btn-danger/);
  f.setSnapshot({ active_job_keys: [] });
  await f.context._pollRTRunning();
  assert.doesNotMatch(f.row('beta'), /rt-plan-running/);
  assert.match(f.row('beta'), /btn-primary[^>]*aria-busy="false"[^>]*>/);
  assert.ok(f.state.pollingTimer, 'keep watching for externally started tests');
});

test('failed polling retains the last known running status', async () => {
  const f = fixture();
  f.setSnapshot({ active_job_keys: ['alpha'] });
  await f.context.refreshRestorePlanOnly();
  for (const error of [true, 'network', 'json']) {
    f.fail(error);
    await f.context._pollRTRunning();
    assert.match(f.row('alpha'), /btn-danger/);
  }
});

test('manual start stays marked after request busy state clears and prevents duplicate starts', async () => {
  const f = fixture();
  await f.context.runRestorePlanJob('alpha');
  assert.ok(f.posted());
  assert.equal(f.state.rowBusy.alpha, false);
  assert.match(f.row('alpha'), /btn-danger/);
  await f.context.runRestorePlanJob('alpha');
  assert.equal(f.requests.filter(([, method]) => method === 'POST').length, 1);
});

test('managed run snapshots match exact job keys and ignore completed or global runs', () => {
  const f = fixture();
  f.context.updateRTRunningJobs({ runs: [
    { running: true, run_key: 'restore_test_alpha' },
    { running: false, run_key: 'restore_test_beta' },
    { running: true, run_key: 'restore_test' },
  ] });
  f.context.renderRestorePlan(f.plan);
  assert.match(f.row('alpha'), /btn-danger/);
  assert.doesNotMatch(f.row('beta'), /btn-danger/);
});


test('cancel sends the exact selected run and stays pending until it disappears', async () => {
  const f = fixture();
  f.setSnapshot({active_job_keys: ['alpha', 'beta']});
  await f.context.refreshRestoreTests();
  f.confirm(false);
  await f.context.cancelRestorePlanJob('alpha');
  assert.equal(f.requests.filter(([, method]) => method === 'POST').length, 0);
  f.confirm(true);
  await f.context.cancelRestorePlanJob('alpha');
  const writes = f.requests.filter(([, method]) => method === 'POST');
  assert.equal(writes.length, 1);
  assert.equal(writes[0][0], '/api/restore-tests/cancel');
  assert.deepEqual(writes[0][2], {job_key: 'alpha', run_id: 'run-alpha'});
  assert.match(f.row('alpha'), /aria-busy="true" disabled/);
  assert.match(f.row('alpha'), /Cancelling/);
  assert.doesNotMatch(f.row('beta'), /disabled/);
  await f.context.cancelRestorePlanJob('alpha');
  assert.equal(f.requests.filter(([, method]) => method === 'POST').length, 1);
  f.setSnapshot({active_job_keys: ['beta']});
  await f.context._pollRTRunning();
  assert.match(f.row('alpha'), /data-rt-plan-action="run"/);
  assert.match(f.row('beta'), /data-rt-plan-action="cancel"/);
});

test('a stale cancellation reports an error and does not target a replacement run', async () => {
  const f = fixture();
  f.setSnapshot({active_job_keys: ['alpha']});
  await f.context.refreshRestoreTests();
  f.context._openRTStartConfirmModal = async () => {
    f.setSnapshot({active_job_keys: ['alpha'], active_jobs: [{job_key:'alpha', run_id:'replacement', run_key:'restore_test_alpha', cancel_allowed:true}]});
    await f.context._pollRTRunning();
    return true;
  };
  f.cancelError();
  await f.context.cancelRestorePlanJob('alpha');
  const request = f.requests.find(([url]) => url.endsWith('/cancel'));
  assert.equal(request[2].run_id, 'run-alpha');
  assert.equal(f.state.runningRuns[0].run_id, 'replacement');
  assert.ok(f.messages.some(([, type]) => type === 'error'));
  assert.doesNotMatch(f.row('alpha'), /disabled/);
});

test('cancelled reports are labelled explicitly and older runners cannot receive unsafe cancellation', async () => {
  const f = fixture();
  f.setSnapshot({active_job_keys:['alpha'],active_jobs:[]});
  await f.context.refreshRestoreTests();
  assert.match(f.row('alpha'), /disabled/);
  await f.context.cancelRestorePlanJob('alpha');
  assert.equal(f.requests.filter(([, method]) => method === 'POST').length,0);
  assert.equal(f.context._rtStatus({test_result:'failed',failure_code:'RT_CANCELLED'}).label,'Cancelled');
});

for (const language of ['de', 'en']) test(`cancelled attempt is explicit in planning (${language})`, () => {
  const f = fixture(language);
  f.plan.jobs[0].last_test_date = '2026-10-27 10:14:22';
  f.plan.jobs[0].last_test_result = 'cancelled';
  f.context.renderRestorePlan(f.plan);
  assert.match(f.row('alpha'), language === 'de' ? /Abgebrochen/ : /Cancelled/);
  assert.match(f.row('alpha'), /2026-10-27 10:14:22/);
});

for (const language of ['de', 'en']) test(`evidence distinguishes attempts and cumulative levels (${language})`, () => {
  const f = fixture(language);
  f.context.isStaleDate = () => false;
  const t = {job_key:'alpha', test_result:'success', test_date:'2026-10-26 12:00:00', test_level:3,
    tested_archive:'archive<script>alert(1)</script>', steps:[
      ...['repo_reachable','archive_readable','metadata_check','restore_probe','integrity_check'].map(step_id=>({step_id,status:'passed'}))
    ], level3_details:{enabled:true,success_count:10}};
  let levels = f.context.renderRTLevelEvidence(t, t.steps);
  assert.equal((levels.match(/rt-attempt-status success/g)||[]).length, 3);
  levels = f.context.renderRTLevelEvidence({...t,test_level:2}, t.steps);
  assert.equal((levels.match(/rt-attempt-status success/g)||[]).length, 2);
  assert.equal((levels.match(/rt-attempt-status neutral/g)||[]).length, 1);
  levels = f.context.renderRTLevelEvidence({...t,test_level:1}, t.steps);
  assert.equal((levels.match(/rt-attempt-status success/g)||[]).length, 1);
  levels = f.context.renderRTLevelEvidence(t, []);
  assert.doesNotMatch(levels, /rt-attempt-status success/);
  assert.equal(f.context.rtReportIdentity({...t,time_ago:'just now'}), f.context.rtReportIdentity({...t,time_ago:'1 minute ago'}));
  const html = f.context.renderRTReportRow(t,0);
  assert.match(html, /rt-proof-document/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  const cancel = {...t,test_result:'failed',failure_code:'RT_CANCELLED'};
  assert.equal(f.context.rtAttemptStatus(cancel).className, 'neutral');
  assert.doesNotMatch(f.context.renderRTReportRow(cancel,1), /rt-proof-document/);
  assert.equal(f.context.rtAttemptStatus({...t,test_date:'2001-01-01 12:00:00'}).className, 'success');
  assert.equal(f.context.rtAttemptStatus({test_date:'2026-10-26'}).className, 'neutral');
});

test('cancelled report links only to server-confirmed retained evidence, never an older success behind failure', () => {
  const f=fixture(); f.context.isStaleDate=()=>false;
  const success={job_key:'alpha',test_result:'success',test_date:'2026-10-25 12:00:00'};
  const cancelled={job_key:'alpha',test_result:'cancelled',test_date:'2026-10-27 12:00:00'};
  f.state.data=[success,cancelled];
  Object.assign(f.plan.jobs[0],{verification_status:'verified',verification_evidence_date:success.test_date});
  assert.match(f.context.renderRTReportRow(cancelled,0),/data-rt-action="evidence"/);
  f.plan.jobs[0].verification_status='failed';
  assert.doesNotMatch(f.context.renderRTReportRow(cancelled,0),/data-rt-action="evidence"/);
  f.plan.jobs[0].verification_status='stale';
  assert.doesNotMatch(f.context.renderRTReportRow(cancelled,0),/data-rt-action="evidence"/);
  f.plan.jobs[0].verification_status='verified';
  assert.doesNotMatch(f.context.renderRTReportRow({...cancelled,test_date:'2026-10-01 12:00:00'},0),/data-rt-action="evidence"/);
  f.state.data=[cancelled];
  assert.doesNotMatch(f.context.renderRTReportRow(cancelled,0),/data-rt-action="evidence"/);
});

for (const language of ['de', 'en']) test(`${language}: waiting test keeps cancellation and changes to running`, async () => {
  const f = fixture(language);
  const run = {job_key: 'alpha', run_id: 'run-alpha', run_key: 'restore_test_alpha', cancel_allowed: true, activity_state: 'waiting'};
  f.setSnapshot({active_job_keys: ['alpha'], active_jobs: [run]});
  await f.context.refreshRestoreTests();
  assert.match(f.row('alpha'), language === 'de' ? /Wartet auf Testplatz/ : /Waiting for test slot/);
  assert.match(f.row('alpha'), /data-rt-plan-action="cancel"/);
  assert.match(f.row('alpha'), /rt-plan-running-label waiting/);
  f.setSnapshot({active_job_keys: ['alpha'], active_jobs: [{...run, activity_state: 'running'}]});
  await f.context._pollRTRunning();
  assert.match(f.row('alpha'), /rt-plan-running-label running/);
  f.setSnapshot({active_job_keys: ['alpha'], active_jobs: [{...run, activity_state: undefined}]});
  await f.context._pollRTRunning();
  assert.match(f.row('alpha'), language === 'de' ? /Status unbekannt/ : /Status unknown/);
  assert.doesNotMatch(f.row('alpha'), /rt-plan-running-label waiting/);
});
