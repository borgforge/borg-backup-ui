'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

/** Load the shipped dashboard with controlled API metadata and translation resources. */
function dashboard(language = 'de') {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const t = (key, params = {}) => {
    const label = key.split('.').reduce((v, k) => v?.[k], labels);
    return typeof label === 'string' ? label.replace(/\{(\w+)\}/g, (all, key) => params[key] ?? all) : key;
  };
  const elements = new Map();
  for (const id of ['summary-bar', 'restore-summary-bar', 'dashboard-attention', 'backup-grid', 'dashboard-location-list']) {
    elements.set(id, {innerHTML: '', querySelector: () => null, querySelectorAll: () => []});
  }
  const context = vm.createContext({
    window: {addEventListener() {}, BBUI: {components: {i18n: {t, getLanguage: () => language}}, core: {state: {}, getSchedulesData: () => ({})}}},
    document: {getElementById: id => elements.get(id), activeElement: null, querySelector: () => null},
    escHtml: value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    patchJobMarkup: (target, html) => { target.innerHTML = html; },
    locationIcon: location => `<svg data-location-icon="${location}"></svg>`,
    resolveJobIcon: job => job.icon || 'archive',
    resolveJobIconColor: job => job.icon_color || '',
    isStaleDate: () => false,
    calcNextRun: () => new Date('2026-10-25T10:00:00Z'),
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/dashboard.js', 'utf8'), context);
  return {context, elements, t};
}

for (const language of ['de', 'en']) {
  test(`${language}: latest outcomes count once, overdue remains independent`, () => {
    const {context: c, elements} = dashboard(language);
    const backups = [...Array.from({length: 11}, (_, i) => ({key: `ok${i}`, status: 'success', backup_overdue: i === 0})),
      {key: 'error', status: 'error'}, {key: 'skip', status: 'skipped'}];
    const summary = c.dashboardBackupSummary(backups);
    assert.equal(summary.total, 13);
    assert.equal(summary.counts.success, 11);
    assert.equal(summary.counts.error, 1);
    assert.equal(summary.counts.skipped, 1);
    assert.equal(summary.counts.warning, 0);
    assert.equal(summary.overdue, 1);
    assert.equal(c.dashboardRunStatus(backups[0]).cls, 'success');
    c.renderSummaryBar(backups);
    const html = elements.get('summary-bar').innerHTML;
    assert.match(html, /<strong>11<\/strong><small>\/13<\/small>/);
    assert.match(html, language === 'de' ? /1 Backup überfällig/ : /1 backup overdue/);
    assert.doesNotMatch(html, /<details|<summary|<ul|ok0/);
    assert.equal(c.dashboardAttentionItems(backups).filter(i => i.backup.key === 'ok0').length, 1);
  });

  test(`${language}: restore coverage includes every job and separately counts known plans`, () => {
    const {context: c, elements, t} = dashboard(language);
    c.renderRestoreVerificationSummary([
      ...Array.from({length: 6}, () => ({restore_verification_status: 'verified'})),
      ...Array.from({length: 7}, () => ({restore_verification_status: 'not_required'})),
    ]);
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restoreCoverageTotal', {total: 13})));
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restorePlansVerified', {count: 6, total: 6})));
    assert.equal((elements.get('restore-summary-bar').innerHTML.match(/class="success"/g) || []).length, 6);
    assert.equal((elements.get('restore-summary-bar').innerHTML.match(/class="neutral"/g) || []).length, 7);
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restoreUnplannedCount', {count: 7})));
    c.renderRestoreVerificationSummary([{restore_verification_status: 'verified'}, {}, {restore_verification_status: 'failed'}, {restore_verification_status: 'stale'}, {restore_verification_status: 'never'}]);
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restoreCoverageTotal', {total: 5})));
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restorePlansVerified', {count: 1, total: 4})));
    assert.ok(elements.get('restore-summary-bar').innerHTML.includes(t('dashboard.restoreUnknownCount', {count: 1})));
  });

  test(`${language}: empty and never-run data cannot produce false success`, () => {
    const {context: c, elements} = dashboard(language);
    c.renderSummaryBar([]);
    c.renderRestoreVerificationSummary([]);
    for (const id of ['summary-bar', 'restore-summary-bar']) {
      assert.match(elements.get(id).innerHTML, /<strong>0<\/strong>/);
      assert.doesNotMatch(elements.get(id).innerHTML, /NaN|Infinity|undefined/);
    }
    const counts = c.dashboardBackupSummary([{never_run: true, status: 'success'}, {status: 'future'}, {status: 'cancelled'}]).counts;
    assert.equal(counts.success, 0);
    assert.equal(counts.unknown, 2);
    assert.equal(counts.cancelled, 1);
    assert.equal(c.dashboardRunStatus({status: 'bad" onclick="x'}).cls, 'unknown');
  });

  test(`${language}: real failures, skip reasons and overdue remain discoverable`, () => {
    const {context: c, elements} = dashboard(language);
    const backups = [{key: 'bad', name: '<img src=x onerror=alert(1)>', status: 'error', error_message: '<script>fail()</script>', location: 'storagebox'},
      {key: 'usb', name: 'Flash', status: 'skipped', skip_reason_code: 'usb_not_mounted', location: 'usb'},
      {key: 'late', status: 'success', backup_overdue: true, restore_verification_status: 'stale'}];
    const items = c.dashboardAttentionItems(backups);
    assert.equal(items.length, 4);
    assert.equal(c.dashboardRunMessage({status: 'skipped', skip_reason_code: 'resource_busy', skip_reason_text: 'Repository is locked'}).text, 'Repository is locked');
    assert.equal(items[0].backup.key, 'bad');
    assert.equal(items.find(i => i.backup.key === 'usb').message, c.dashboardRunMessage(backups[1]).text);
    c.renderDashboardAttention(backups);
    assert.equal(elements.get('dashboard-attention').hidden, false);
    assert.match(elements.get('dashboard-attention').innerHTML, /&lt;script&gt;/);
    assert.doesNotMatch(elements.get('dashboard-attention').innerHTML, /<script>|<img/);
    c.renderDashboardAttention([]);
    assert.equal(elements.get('dashboard-attention').hidden, true);
  });

  test(`${language}: icons, archive identity, storage and group schedules survive disclosure`, () => {
    const {context: c} = dashboard(language);
    const job = {key: 'app"<', name: 'Appdata', icon: 'photos', icon_color: 'purple', status: 'success', archive_name: 'latest-archive-<unsafe>', location: 'local',
      original_size: 10, original_size_formatted: '87.2 GB', compressed_size_formatted: '45.0 GB', deduplicated_size_formatted: '1.0 GB', repository_size_formatted: '161.7 GB',
      growth_bytes: 20, growth_formatted: '+1.4 GB', borg_steps: {check: {status: 'success', duration_seconds: 4}},
      repository_check_status: 'ok', repository_check_date: '2026-10-23', restore_verification_status: 'verified',
      restore_verification_last_test_date: '2026-10-20', restore_verification_valid_until: '2026-11-20',
      groups: [{name: 'Daily', schedule: {enabled: true, cron: '0 10 * * *'}}]};
    const html = c.renderDashboardInventoryRow(job);
    assert.match(html, /type-icon-color-purple/);
    assert.ok(html.includes(c.typeIcon('photos')));
    assert.match(html, /title="latest-archive-&lt;unsafe&gt;"/);
    assert.match(html, /data-dashboard-details="app&quot;&lt;"/);
    assert.match(html, /aria-expanded="false"/);
    for (const fact of ['87.2 GB', '45.0 GB', '1.0 GB', '161.7 GB', '+1.4 GB', '2026-10-20', '2026-11-20', '25.10.2026', '25/10/2026']) {
      if (fact === '25.10.2026' && language === 'en' || fact === '25/10/2026' && language === 'de') continue;
      assert.ok(html.includes(fact), fact);
    }
    assert.doesNotMatch(html, /<unsafe>/);
    assert.equal(c.dashboardBorgCheckResult({}), c.dashboardT('dashboard.unknown'));
    assert.ok(c.dashboardBorgCheckResult({borg_steps: {check: {status: 'skipped', reason: 'not_due'}}}).includes(c.dashboardT('jobs.borgStep.not_due')));
    assert.equal(c.dashboardBorgCheckResult({borg_steps: {check: {status: 'pending'}}}), c.dashboardT('dashboard.notExecuted'));
    assert.equal(c.dashboardBorgCheckResult({borg_steps: {check: {status: 'skipped'}}, repository_check_status: 'ok'}), c.dashboardT('dashboard.skipped'));
  });

  test(`${language}: All locations stays grouped and omits locations without jobs`, () => {
    const {context: c, elements} = dashboard(language);
    const backups = [{key: '1', location: 'local', status: 'error', backup_overdue: true}, {key: '2', location: 'usb', status: 'success'}, {key: '3', location: 'storagebox', status: 'cancelled'}];
    c.renderBackupGrid(backups);
    assert.equal((elements.get('backup-grid').innerHTML.match(/class="dashboard-location-group-row"/g) || []).length, 3);
    assert.doesNotMatch(elements.get('dashboard-location-list').innerHTML, /data-dashboard-location="smb"/);
    for (const location of ['local', 'usb', 'storagebox']) assert.match(elements.get('dashboard-location-list').innerHTML, new RegExp(`data-location-icon="${location}"`));
    vm.runInContext("dashboardSelectedLocation = 'usb'; dashboardExpandedJobs.add('2')", c);
    c.renderBackupGrid(backups);
    assert.match(elements.get('backup-grid').innerHTML, /aria-expanded="true"/);
    assert.match(elements.get('summary-bar').innerHTML, /<strong>1<\/strong><small>\/1<\/small>/);
    assert.match(elements.get('summary-bar').innerHTML, /USB/);
    assert.doesNotMatch(elements.get('summary-bar').innerHTML, /dashboard-summary-overdue/);
    assert.ok(!elements.get('summary-bar').innerHTML.includes(c.dashboardT('jobs.statusCancelled')));
    c.renderDashboard({backups}, null);
    assert.match(elements.get('summary-bar').innerHTML, /<strong>1<\/strong><small>\/1<\/small>/);

    c.renderBackupGrid(backups.slice(0, 1));
    assert.equal(vm.runInContext('dashboardSelectedLocation', c), 'all');
    assert.match(elements.get('summary-bar').innerHTML, /<strong>0<\/strong><small>\/1<\/small>/);
    assert.match(elements.get('summary-bar').innerHTML, /dashboard-summary-overdue/);
    assert.equal(vm.runInContext('dashboardExpandedJobs.size', c), 0);
    c.renderBackupGrid([]);
    assert.doesNotMatch(elements.get('backup-grid').innerHTML, /dashboard-inventory-row/);
    assert.match(elements.get('summary-bar').innerHTML, /<strong>0<\/strong><small>\/0<\/small>/);
    assert.doesNotMatch(elements.get('summary-bar').innerHTML, /dashboard-summary-overdue/);
  });
}

test('management history discards obsolete responses and clears statistics on failure', async () => {
  const {context: c, elements} = dashboard('en');
  elements.set('dashboard-trends', {innerHTML: ''});
  const pending = [];
  c.fetch = () => new Promise(resolve => pending.push(resolve));
  const first = c.refreshDashboardOverview();
  vm.runInContext('dashboardPeriod = 7', c);
  const second = c.refreshDashboardOverview();
  const payload = days => ({days, location:'all', from:'2026-10-21', to:'2026-10-27', counts:{success:0,warning:0,error:0,skipped:0,cancelled:0,unknown:0},daily:[{date:'2026-10-27',success:0,warning:0,error:0,skipped:0,cancelled:0,unknown:0,measured_repositories:0,repository_bytes:null}], repository_count:0, unassigned_jobs:0, run_count:0, success_rate:null});
  pending[1]({ok:true, json:async()=>payload(7)}); await second;
  pending[0]({ok:true, json:async()=>payload(30)}); await first;
  assert.equal(vm.runInContext('dashboardOverview.days', c),7);
  assert.match(elements.get('dashboard-trends').innerHTML,/No complete measurement/);
  assert.doesNotMatch(elements.get('dashboard-trends').innerHTML,/NaN|Infinity/);
  const previous = elements.get('dashboard-trends').innerHTML;
  const background = c.refreshDashboardOverview();
  assert.equal(elements.get('dashboard-trends').innerHTML, previous, 'Same-scope refresh retains the chart while pending');
  pending[2]({ok:true, json:async()=>payload(7)}); await background;
  vm.runInContext("dashboardSelectedLocation = 'usb'", c);
  const changedScope = c.refreshDashboardOverview();
  assert.match(elements.get('dashboard-trends').innerHTML, /Loading/);
  assert.doesNotMatch(elements.get('dashboard-trends').innerHTML, /management-trends-grid/);
  pending[3]({ok:true, json:async()=>({...payload(7), location:'usb'})}); await changedScope;
  assert.equal(vm.runInContext('dashboardOverview.location', c), 'usb');
  c.fetch = async () => ({ok:false});
  await c.refreshDashboardOverview();
  assert.equal(vm.runInContext('dashboardOverview', c),null);
  assert.match(elements.get('dashboard-trends').innerHTML,/could not be loaded/);
});
