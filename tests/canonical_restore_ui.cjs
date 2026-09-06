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
    window: { addEventListener() {}, BBUI: { components: { i18n: { t, getLanguage: () => lang } } } },
    document: { getElementById: element, createElement: make, createTextNode: text => ({ textContent: text }),
      addEventListener() {}, querySelectorAll: () => [], querySelector: () => null },
    URLSearchParams, Intl, Date, console, setTimeout: () => 0, clearTimeout() {}, CSS: { escape: s => s },
    escHtml: text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    svg: () => '<svg></svg>', locationIcon: () => '<svg></svg>', isStaleDate: () => false,
    hideEl() {}, showMsg() {}, apiErrorMessage: () => 'Request error',
    fetch: async (url, options) => { calls.push({url, options}); return { ok: true, json: async () => response }; },
  });
  for (const page of ['restore', 'restore-tests']) vm.runInContext(read(`ui/js/pages/${page}.js`), context);
  vm.runInContext('restoreJobIcon=()=>"folder"; restoreTestsJobIcon=()=>"folder";', context);
  const job = { job_id: id, name: 'New name', display_name: 'New name', location: 'local', enabled: true };
  vm.runInContext(`restoreState.jobs=${JSON.stringify([job])}; restoreState.job='${id}'; restoreTestsState.jobs=${JSON.stringify([job])};`, context);
  context.renderRestoreJobSidebar();
  assert.ok(element('restore-sidebar-job-list').innerHTML.includes(id));
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
