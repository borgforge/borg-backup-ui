const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

function page(language = 'en') {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) {
      elements.set(id, {
        value: '', checked: false, disabled: false, textContent: '', style: {}, html: '',
        get innerHTML() { return this.html; },
        set innerHTML(value) { this.html = value; if (id.endsWith('-sel')) this.value = ''; },
        appendChild() {}, classList: {add() {}, remove() {}, toggle() {}},
      });
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    window: {BBUI: {components: {i18n: {t(key, params = {}) {
      const label = key.split('.').reduce((value, part) => value?.[part], labels) || key;
      return label.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '');
    }}}}, addEventListener() {}},
    document: {getElementById: get, createElement: () => ({})},
    messages: [], hideEl() {}, showMsg() {}, escHtml: value => String(value),
    apiErrorMessage: data => labels.api.errors[data.code] || data.message || 'API error',
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/restore.js', 'utf8'), context);
  for (const name of ['restoreSetLiveMode', 'restoreSwitchView', 'restoreSetStep',
    '_restoreBindTargetAutocomplete', '_restoreRenderSelectionSummary', '_restoreRenderSelectedBox',
    'restoreLoadRuns', 'restoreLoadHistory', 'renderRestoreJobSidebar', 'renderRestoreSelectedJob',
    'renderRestoreSourceContext', 'renderRestoreArchiveList', 'renderRestorePrecheck',
    '_restoreRenderBreadcrumb', '_setRestoreAssistBusy', 'restoreUpdateConfirmState']) context[name] = () => {};
  context.restoreLoadAllowedTargetRoots = async () => {};
  context._restorePrimaryAllowedRoot = () => '/mnt/user';
  context._isAllowedRestoreTarget = () => true;
  context._restoreMsg = (message, error) => context.messages.push({message, error});
  context._restoreRenderFiles = files => { get('restore-filelist').innerHTML = JSON.stringify(files); };
  return {context, get, state: context.window.BBUI.restoreState, labels};
}

test('returning after backups, repository switches and rename refreshes the same job', async () => {
  const {context, get, state} = page();
  const calls = [];
  let repository = 'repo1', name = 'Test';
  const archives = {repo1: [{name: 'first'}], repo2: [{name: 'other-repository'}]};
  context.fetch = async url => {
    calls.push(url);
    return response(url === '/api/jobs'
      ? {jobs: [{key: 'job-id', name, repository_key: repository}]}
      : {archives: archives[repository], archive_filters: []});
  };
  state.job = 'job-id';
  for (const stage of ['initial', 'backup', 'repo2', 'repo1', 'rename']) {
    if (stage === 'backup') archives.repo1.push({name: 'scheduled'});
    if (stage === 'repo2' || stage === 'repo1') repository = stage;
    if (stage === 'rename') name = 'Renamed';
    state.archive = 'stale'; state.files = [{name: 'old-file'}];
    state.selectedPath = 'old-file'; state.precheck = {ok: true};
    get('restore-source-path').value = 'old-file';
    get('restore-confirm-check').checked = true;
    await context.restoreInit();
    assert.equal(state.job, 'job-id');
    assert.equal(state.jobs[0].repository_key, repository);
    assert.equal(state.jobs[0].name, name);
    assert.equal(JSON.stringify(state.archives), JSON.stringify(archives[repository]));
    assert.equal(state.archive, '');
    assert.equal(state.selectedPath, '');
    assert.equal(state.precheck, null);
    assert.equal(state.files.length, 0);
    assert.equal(get('restore-source-path').value, '');
    assert.equal(get('restore-confirm-check').checked, false);
  }
  assert.equal(calls.filter(url => url.startsWith('/api/restore/archives')).length, 5);
});

test('late archive-list responses cannot restore the previous job selection', async () => {
  const {context, get, state} = page();
  const first = deferred();
  context.fetch = url => url.endsWith('job=first') ? first.promise : Promise.resolve(response({archives: [{name: 'second'}]}));
  get('restore-job-sel').value = 'first';
  const pending = context.restoreLoadArchives();
  get('restore-job-sel').value = 'second';
  await context.restoreLoadArchives();
  first.resolve(response({archives: [{name: 'obsolete'}]}));
  await pending;
  assert.equal(state.job, 'second');
  assert.equal(state.archives[0].name, 'second');
});

test('source changes discard in-flight file listings and precheck results', async () => {
  const {context, get, state} = page();
  state.job = 'job-id';
  get('restore-archive-sel').value = 'old';
  const files = deferred();
  context.fetch = () => files.promise;
  const browse = context.restoreBrowse('');
  get('restore-job-sel').value = 'job-id';
  context.fetch = async () => response({archives: [{name: 'new'}]});
  await context.restoreLoadArchives();
  files.resolve(response({files: [{name: 'obsolete'}]}));
  await browse;
  assert.equal(state.files.length, 0);
  assert.equal(get('restore-filelist').innerHTML, '');

  const check = deferred();
  state.archive = 'new'; state.selectedPath = 'data';
  get('restore-target-path').value = '/mnt/user/test';
  context.fetch = () => check.promise;
  const precheck = context.restoreRunPrecheck();
  context.fetch = async () => response({archives: []});
  await context.restoreLoadArchives();
  check.resolve(response({ok: true}));
  await precheck;
  assert.equal(state.precheck, null);
  assert.equal(state.selectedPath, '');
});

test('a removed job or failed archive refresh leaves no old selectable archive', async () => {
  const {context, get, state} = page();
  state.job = 'removed'; state.archive = 'old'; state.archives = [{name: 'old'}];
  context.fetch = async () => response({jobs: [{key: 'remaining'}]});
  await context.restoreInit();
  assert.equal(state.job, '');
  assert.equal(state.archives.length, 0);
  get('restore-job-sel').value = 'remaining';
  context.fetch = async () => response({code: 'internal_error'}, 500);
  await context.restoreLoadArchives();
  assert.equal(state.archive, '');
  assert.equal(state.archives.length, 0);
});
