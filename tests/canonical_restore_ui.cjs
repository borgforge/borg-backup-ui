const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const id = '11111111-1111-4111-8111-111111111111';
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
    classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll: () => [], appendChild() {},
    append() {}, addEventListener() {}, setAttribute() {} });
  const element = id => { if (!elements.has(id)) elements.set(id, make()); return elements.get(id); };
  const calls = [];
  let response = {};
  const context = vm.createContext({
    window: { addEventListener() {}, BBUI: { core: { getSchedulesData: () => ({}) },
      components: { i18n: { t, getLanguage: () => lang } } } },
    document: { getElementById: element, createElement: make, createTextNode: text => ({ textContent: text }),
      addEventListener() {}, querySelectorAll: () => [], querySelector: () => null },
    URLSearchParams, Intl, Date, console, setTimeout: () => 0, clearTimeout() {}, CSS: { escape: s => s },
    escHtml: text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    svg: () => '<svg></svg>', locationIcon: () => '<svg></svg>', isStaleDate: () => false,
    hideEl() {}, showMsg() {}, apiErrorMessage: () => 'Request error',
    fetch: async (url, options) => { calls.push({url, options}); return { ok: true, json: async () => response }; },
  });
  for (const page of ['dashboard', 'jobs', 'restore', 'restore-tests', 'reports', 'storage']) {
    vm.runInContext(read(`ui/js/pages/${page}.js`), context);
  }
  const iconRenderers = [
    context.renderDashboardInventoryRow, context.restoreJobIcon, context.restoreTestsJobIcon,
    context._berichtJobIcon, job => context.storageRepositoryIcon({}, job),
  ];
  const iconCases = [
    ['appdata', 'M21 16V8'], ['photos', 'M23 19a2'], ['vms', 'M2 2h20v8H2z'], ['flash', 'M13 2 3 14'],
  ];
  for (const [icon, svgPath] of iconCases) {
    for (const legacyType of [undefined, 'legacy-unrelated']) {
      const canonicalJob = { job_id: id, name: icon, icon, icon_color: '',
        backup_type: legacyType, archive_prefix: `${icon}-backup`, location: 'local', enabled: true };
      for (const render of iconRenderers) {
        const iconHTML = render(canonicalJob);
        assert.match(iconHTML, new RegExp(`class="type-icon type-icon-${icon}(?:[ "])`));
        assert.ok(iconHTML.includes(`<path d="${svgPath}`), `${lang}: ${icon} keeps its SVG`);
        assert.ok(!iconHTML.includes('type-icon-color-') && !iconHTML.includes('type-icon-legacy-unrelated'));
      }
    }
  }
  for (const render of iconRenderers) {
    const customized = render({ job_id: id, name: 'Photos', location: 'local', enabled: true,
      backup_type: 'photos', icon: 'database', icon_color: 'rose', archive_prefix: 'photos-backup' });
    assert.match(customized, /class="type-icon type-icon-database(?:[ "])/);
    assert.ok(customized.includes('type-icon-color-rose') && customized.includes('<path d="M12 5c-4.4'));
    assert.ok(!customized.includes('type-icon-photos'));
  }
  const job = { job_id: id, name: 'New name', display_name: 'New name', location: 'local', enabled: true,
    archive_prefix: 'new-name-backup' };
  vm.runInContext(`restoreState.jobs=${JSON.stringify([job])}; restoreState.job='${id}'; restoreTestsState.jobs=${JSON.stringify([job])};`, context);
  context.renderRestoreJobSidebar();
  assert.ok(element('restore-sidebar-job-list').innerHTML.includes(id));
  const choices = [job,
    { ...job, job_id: '22222222-2222-4222-8222-222222222222', display_name: 'AAA USB', location: 'usb', archive_prefix: '', archive_prefixes: ['usb-backup'] },
    { ...job, job_id: '33333333-3333-4333-8333-333333333333', display_name: 'Appdata 10', archive_prefix: '', description: 'Source description' },
    { ...job, job_id: '44444444-4444-4444-8444-444444444444', display_name: 'appdata 2', name: 'Different internal name', archive_prefix: 'appdata-backup' }];
  const expected = [choices[3].job_id, choices[2].job_id, id, choices[1].job_id];
  vm.runInContext(`restoreState.jobs=${JSON.stringify(choices)}; restoreTestsState.jobs=${JSON.stringify(choices)};`, context);
  context.renderRestoreJobSidebar();
  context.renderRestoreSelectedJob();
  context.renderRestoreTestsSidebar();
  for (const [listId, attribute] of [['restore-sidebar-job-list', 'data-restore-sidebar-job'], ['rt-sidebar-job-list', 'data-rt-sidebar-job']]) {
    const sidebar = element(listId).innerHTML;
    const ids = [...sidebar.matchAll(new RegExp(`${attribute}="([^"]+)"`, 'g'))].map(match => match[1]).filter(value => value !== 'all');
    assert.deepEqual(ids, expected);
    for (const subtitle of ['new-name-backup', 'usb-backup', 'Source description', 'appdata-backup']) assert.ok(sidebar.includes(`<small>${subtitle}</small>`));
    for (const choice of choices) assert.ok(!sidebar.includes(`<small>${choice.job_id}</small>`));
  }
  const selectedCard = element('restore-selected-job-card').innerHTML;
  assert.ok(selectedCard.includes('new-name-backup') && !selectedCard.includes(id));
  element('rt-select-all-jobs').checked = false;
  element('rt-location-select').value = 'all';
  context.refreshRestoreTestJobsForSelection();
  assert.deepEqual([...element('rt-job-selector-list').innerHTML.matchAll(/class="rt-job-checkbox" value="([^"]+)"/g)].map(match => match[1]), expected);
  vm.runInContext(`restoreState.jobs=${JSON.stringify([job])}; restoreTestsState.jobs=${JSON.stringify([job])};`, context);
  element('restore-job-sel').value=id;
  response={archives:[{name:'old-2026',start:'2026-09-06'}],archive_filters:[{prefix:'new',filter:'new-*',current:true},{prefix:'old',filter:'old-*',current:false}]};
  await context.restoreLoadArchives();
  assert.equal(calls.at(-1).url,`/api/restore/archives?job_id=${id}`);
  const history={restore_id:'old-run',job_id:id,current_job_name:'New name',job_name_snapshot:'Original <name>',repository_snapshot:'/old-repo',archive:'old-2026',state:'done',identity_scope:'configured'};
  context.renderRestoreHistory({runs:[history],total:1});
  const html=element('restore-history-content').innerHTML;
  for(const value of ['New name','Original &lt;name&gt;','/old-repo']) assert.ok(html.includes(value), value);
  context.renderRestoreHistory({runs:[{...history,identity_scope:'deleted',current_job_name:''}],total:1});
  assert.ok(element('restore-history-content').innerHTML.includes(t('restore.identityDeleted')));
  context.renderRestoreHistory({runs:[{restore_id:'legacy',state:'done',identity_scope:'unassigned'}],total:1});
  assert.ok(element('restore-history-content').innerHTML.includes(t('restore.identityUnassigned')));
  const report={...history,report_id:'run-uuid',test_result:'success',test_date:'2026-09-06',test_level:1,location:'local',tested_archive:'old-2026',archive_prefix_snapshot:'old'};
  const reportHTML=context.renderRTReportRow(report,0);
  for(const value of ['New name','Original &lt;name&gt;','/old-repo','old-2026']) assert.ok(reportHTML.includes(value),value);
  assert.ok(context.renderRTReportRow({...report,identity_scope:'deleted'},1).includes(t('restoreTests.identityDeleted')));
  assert.ok(context.renderRTReportRow({identity_scope:'unassigned'},2).includes(t('restoreTests.identityUnassigned')));
  response={started:true};
  // Action binding must pass the UUID; avoid unrelated refresh/live-log transport in this contract test.
  vm.runInContext('refreshRestorePlan=async()=>{}; resumeRestoreTestLiveLog=()=>{}; _openRTLogPanel=()=>{}; startRTLogStream=()=>{};',context);
  await context.runRestorePlanJob(id);
  const post=calls.find(c=>c.url==='/api/restore-tests/run-job');
  assert.deepEqual(JSON.parse(post.options.body),{job_id:id});
}
(async()=>{for(const lang of ['de','en']) await run(lang);console.log('Canonical restore UI: DE and EN passed');})().catch(error=>{console.error(error);process.exit(1);});
