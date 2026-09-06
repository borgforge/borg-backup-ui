const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const id = '11111111-1111-4111-8111-111111111111';
const secondId = '22222222-2222-4222-8222-222222222222';
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

async function run(lang) {
  const dictionary = JSON.parse(read(`ui/i18n/${lang}.json`));
  const t = (key, params = {}) => {
    const value = key.split('.').reduce((obj, part) => obj?.[part], dictionary);
    assert.equal(typeof value, 'string', `Missing ${lang} translation: ${key}`);
    return value.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ''));
  };
  const elements = new Map();
  const make = () => ({ value: '', innerHTML: '', textContent: '', style: {}, dataset: {},
    classList: { add() {}, remove() {} }, querySelectorAll: () => [], appendChild() {},
    append() {}, addEventListener() {}, setAttribute() {} });
  const element = id => { if (!elements.has(id)) elements.set(id, make()); return elements.get(id); };
  const calls = [];
  let response = {};
  const context = vm.createContext({
    window: { addEventListener() {}, BBUI: { core: { getSchedulesData: () => ({ [id]: { cron: '0 3 * * *', enabled: true } }) },
      components: { i18n: { t, getLanguage: () => lang } } } },
    document: { getElementById: element, createElement: make, createTextNode: text => ({ textContent: text }),
      addEventListener() {}, querySelectorAll: () => [] },
    URLSearchParams, Intl, Date, console,
    escHtml: text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    svg: () => '<svg></svg>', locationIcon: () => '<svg></svg>', isStaleDate: () => false,
    hideEl() {}, showMsg() {}, apiErrorMessage: () => 'Request error',
    fetch: async url => { calls.push(url); return { ok: true, json: async () => response }; },
  });
  for (const page of ['dashboard', 'history', 'reports']) vm.runInContext(read(`ui/js/pages/${page}.js`), context);
  vm.runInContext('resolveJobIcon=()=>"folder"; resolveJobIconColor=()=>""; repoCheckIcon=()=>"";', context);
  const job = { job_id: id, name: 'pfsense', display_name: 'pfsense', backup_type: 'config',
    archive_prefix: 'new-prefix', enabled: true, location: 'local', identity_scope: 'configured',
    running: true, status: 'error', backup_overdue: true, legacy_status: true };
  const row = context.renderDashboardInventoryRow(job);
  assert.ok(row.includes('>pfsense</strong>'));
  assert.ok(!row.includes(t('identity.migratedStatus')) && !row.includes(t('history.migratedStatus')));
  assert.ok(row.includes('badge running') && row.includes('0 3 * * *'));
  assert.ok(!row.includes('badge error') && !row.includes('badge warning'));
  assert.equal(context.dashboardRunStatus({ ...job, running: false }).cls, 'error');
  assert.equal(context.dashboardRunMessage({ ...job, running: false }).cls, 'error');
  assert.ok(context.renderDashboardRestoreVerificationBadge({ restore_verification_status: 'stale', restore_verification_reason: 'target_changed' }).includes(t('identity.target_changed')));
  assert.equal(context.dashboardRunStatus({ ...job, never_run: true }).cls, 'running');
  context.renderRestoreVerificationSummary([{ enabled: false, restore_verification_status: 'failed' },
    { enabled: true, restore_verification_status: 'verified' }]);
  assert.ok(element('restore-summary-bar').innerHTML.includes('1/1'));
  const proof = { restore_verification_status: 'stale', restore_verification_reason: 'target_unknown',
    restore_verification_last_test_date: '2026-09-04 13:40:05',
    restore_verification_valid_until: '2026-10-04 13:40:05' };
  for (const reason of ['target_unknown', 'target_changed', 'test_date_unknown']) {
    const badge = context.renderDashboardRestoreVerificationBadge({ ...proof, restore_verification_reason: reason });
    assert.ok(badge.includes(t('jobs.restoreOpen')) && !badge.includes(t('jobs.restoreStale')));
    assert.ok(badge.includes(t('dashboard.previousValidityLabel')) && badge.includes(proof.restore_verification_valid_until));
    assert.ok(badge.includes(`<span class="dashboard-cell-detail">${t('identity.' + reason)}</span>`));
  }
  const validProof = context.renderDashboardRestoreVerificationBadge({ ...proof,
    restore_verification_status: 'verified', restore_verification_reason: 'within_validity' });
  assert.ok(validProof.includes(t('jobs.restoreVerified')) && validProof.includes(t('dashboard.validUntilLabel')));
  context.renderRestoreVerificationSummary([proof, { ...proof, restore_verification_reason: 'target_changed' },
    { restore_verification_status: 'stale', restore_verification_reason: 'validity_expired' },
    { restore_verification_status: 'never' }, { restore_verification_status: 'verified' }]);
  const totals = [...element('restore-summary-bar').innerHTML.matchAll(/class="stat-value">([^<]+)/g)].map(m => m[1]);
  assert.deepEqual(totals, ['1/5', '1', '0', '3', '0']);
  const checkedJob = { ...job, running: false, repository_check_scope: 'historical_target_unknown',
    repository_check_status: 'ok', repository_check_date: '2026-08-18 15:13:33', repository_next_check: '2026-09-17' };
  context.isStaleDate = () => true;
  const historicalCheck = context.renderDashboardInventoryRow(checkedJob);
  assert.ok(historicalCheck.includes(t('dashboard.checkTargetUnknown')));
  assert.ok(historicalCheck.includes('2026-08-18') && historicalCheck.includes('2026-09-17'));
  assert.ok(historicalCheck.includes('repo-check unknown') && !historicalCheck.includes('repo-check ok')
    && !historicalCheck.includes('repo-check overdue'));
  context.isStaleDate = () => false;
  const currentCheck = context.renderDashboardInventoryRow({ ...checkedJob, repository_check_scope: 'current' });
  assert.ok(currentCheck.includes('repo-check ok') && !currentCheck.includes(t('dashboard.checkTargetUnknown')));
  assert.equal(context.historyLocationLabel('unknown'), t('history.unknownLocation'));
  const historical = { job_id: id, current_job_name: 'pfsense', historical_name: 'config', display_name: 'pfsense',
    archive_prefix_snapshot: 'old-prefix', repository_snapshot: '/old-repository', identity_scope: 'configured',
    date: '2026-09-01', time: '12:00:00', status: 'success' };
  const history = context.renderHistoryRow(historical, 0);
  for (const text of ['pfsense', 'config', 'old-prefix', '/old-repository', id]) assert.ok(history.includes(text), text);
  assert.ok(!history.includes(t('history.migratedStatus')));
  const migratedHistory = context.renderHistoryRow({ ...historical, legacy_status: true,
    archive_prefix_snapshot: '', repository_snapshot: '', run_id: '' }, 1);
  const [migratedSummary, migratedDetails] = migratedHistory.split('<tr id="hdetail-1"');
  for (const key of ['migratedStatus', 'migratedDescription']) {
    assert.ok(!migratedSummary.includes(t(`history.${key}`)));
    assert.ok(migratedDetails.includes(t(`history.${key}`)));
  }
  for (const key of ['currentName', 'runName', 'jobId']) assert.ok(migratedDetails.includes(t(`history.${key}`)));
  for (const key of ['runId', 'runPrefix', 'runRepository']) assert.ok(!migratedDetails.includes(t(`history.${key}`)));
  element('history-filter-type').value = id;
  element('history-filter-scope').value = 'configured';
  response = { jobs: [job], entries: [historical], total: 1, location_counts: {} };
  await context.refreshHistory();
  assert.ok(calls.at(-1).includes(`job_id=${id}`) && calls.at(-1).includes('scope=configured'));
  assert.ok(!calls.at(-1).includes('type='));
  vm.runInContext(`reportState.jobs = ${JSON.stringify([job, { job_id: secondId, name: 'Deleted', identity_scope: 'deleted' }, { identity_scope: 'unassigned' }])}`, context);
  element('bericht-job-sel').value = id;
  response = { ...job, runs: [], monthly_status: [], run_count: 0, success_count: 0 };
  await context.berichtLoad();
  assert.equal(calls.at(-1), `/api/reports/data?job_id=${id}`);
  assert.equal(element('report-selection-title').textContent, 'pfsense');
  assert.equal(element('bericht-borginfo-btn').disabled, false);
  element('bericht-job-sel').value = 'unassigned';
  response = { identity_scope: 'unassigned', runs: [historical], run_count: 1, success_count: 1, monthly_status: [] };
  await context.berichtLoad();
  assert.equal(calls.at(-1), '/api/reports/data?scope=unassigned');
  assert.equal(element('bericht-borginfo-btn').disabled, true);
  assert.equal(element('br-growth-last').textContent, '—');
  assert.ok(element('bericht-trend-body').innerHTML.includes(t('reports.noData')));
  assert.ok(context._berichtJobLabel({ name: 'Deleted', identity_scope: 'deleted' }).includes(t('reports.deleted')));
  context._berichtRenderGrowthCards([{ date: '2026-08-01', repository_size: 100, repository_snapshot: '/old' },
    { date: '2026-09-01', repository_size: 150, repository_snapshot: '/new' }]);
  assert.equal(element('br-growth-last').textContent, '—');
  assert.equal(context._berichtSameRepository({ repository_snapshot: '' }, { repository_snapshot: '' }), false);
}

function widget() {
  const source = read('plugin/borg-backup-ui-dashboard.page');
  const start = source.indexOf('  function canonicalWidgetItems(');
  const end = source.indexOf('  function setText(', start);
  const context = vm.createContext({ get: (data, key, fallback) => key.split('.').reduce((obj, part) => obj?.[part], data) ?? fallback,
    isPast: () => false });
  vm.runInContext(source.slice(start, end), context);
  const data = { identity_schema_version: 1, jobs: { successful: 99, items: [
    { job_id: id, running: true, last_status: 'error' },
    { job_id: id, last_status: 'success' },
    { job_id: 'old_name_local', last_status: 'success' },
    { job_id: secondId, last_status: 'error', backup_overdue: true },
  ] } };
  const counts = context.adjustedJobCounts(data, new Date());
  assert.equal(counts.total, 2); assert.equal(counts.running, 1); assert.equal(counts.failed, 1);
  assert.equal(counts.successful, 0); assert.equal(counts.warnings, 0);
  assert.equal(context.overallStateFromCounts(counts, {}, 'fresh', true), 'error');
  assert.equal(context.adjustedJobCounts({ ...data, identity_schema_version: 0 }, new Date()).total, 0);
  assert.equal(context.jobStatusEvidence({ ...data, identity_schema_version: 0 }), false);
  context.isPast = () => true;
  const restoreItems = [
    { job_id: id, restore_verification_status: 'stale', restore_verification_reason: 'target_unknown',
      restore_verification_is_overdue: true, restore_verification_valid_until: '2020-01-01' },
    { job_id: secondId, restore_verification_status: 'stale', restore_verification_reason: 'target_changed' },
    { job_id: '33333333-3333-4333-8333-333333333333', restore_verification_status: 'stale',
      restore_verification_reason: 'validity_expired' },
  ];
  const restoreProof = context.adjustedRestoreProof({ identity_schema_version: 1, jobs: { items: restoreItems } }, new Date());
  assert.equal(restoreProof.configured, 3); assert.equal(restoreProof.open, 2);
  assert.equal(restoreProof.overdue, 1); assert.equal(restoreProof.verified, 0);
}
(async () => { await run('de'); await run('en'); widget(); console.log('Canonical dashboard/history/reports DE/EN and Unraid counters passed'); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
