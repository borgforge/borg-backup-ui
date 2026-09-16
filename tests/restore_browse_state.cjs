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
        value: '', checked: false, disabled: false, textContent: '', style: {}, html: '', dataset: {},
        setAttribute() {}, querySelector() { return null; },
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
    setTimeout() { return 1; }, clearTimeout() {},
    messages: [], hideEl() {}, showMsg() {}, escHtml: value => String(value),
    apiErrorMessage: data => labels.api.errors[data.code] || data.message || 'API error',
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/restore.js', 'utf8'), context);
  const renderers = {selection: context._restoreRenderSelectedBox, summary: context._restoreRenderSelectionSummary};
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
  return {context, get, state: context.window.BBUI.restoreState, labels, renderers};
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

for (const language of ['de', 'en']) test(`missing archives stop loading and allow reselection (${language})`, async () => {
  const {context, get, state, labels} = page(language);
  state.job = 'job-id'; state.archive = 'missing'; state.archives = [{name: 'missing'}];
  state.selectedPath = 'stale'; state.precheck = {ok: true};
  get('restore-archive-sel').value = 'missing';
  get('restore-source-path').value = 'stale'; get('restore-confirm-check').checked = true;
  context.fetch = async () => response({code: 'restore_archive_unavailable', error: 'Archive missing does not exist'}, 404);
  await context.restoreBrowse('');
  assert.equal(state.archive, '');
  assert.equal(state.archives.length, 0);
  assert.equal(state.files.length, 0);
  assert.equal(state.selectedPath, '');
  assert.equal(state.precheck, null);
  assert.equal(get('restore-confirm-check').checked, false);
  assert.ok(get('restore-filelist').innerHTML.includes(labels.api.errors.restore_archive_unavailable));
  assert.ok(get('restore-filelist').innerHTML.includes('role="alert"'));

  get('restore-job-sel').value = 'job-id';
  context.fetch = async () => response({archives: [{name: 'available'}]});
  await context.restoreLoadArchives();
  get('restore-archive-sel').value = 'available';
  context.fetch = async () => response({files: [{name: 'recovered.txt'}]});
  await context.restoreBrowse('');
  assert.equal(state.files[0].name, 'recovered.txt');
  assert.ok(get('restore-filelist').innerHTML.includes('recovered.txt'));
});

for (const failure of ['server', 'network', 'json', 'invalid-data']) test(`${failure} errors clear loading and allow retry`, async () => {
  const {context, get, state} = page();
  state.job = 'job-id'; state.archive = 'archive';
  state.selectedPath = 'stale'; state.precheck = {ok: true};
  get('restore-archive-sel').value = 'archive';
  context.fetch = async () => {
    if (failure === 'network') throw new Error('Failed to fetch');
    if (failure === 'json') return {ok: true, json: async () => { throw new Error('Invalid JSON'); }};
    return failure === 'server' ? response({code: 'internal_error'}, 500) : response(null);
  };
  await context.restoreBrowse('');
  assert.equal(state.selectedPath, 'stale'); // Navigation failures keep the selection, but invalidate precheck.
  assert.equal(state.precheck, null);
  assert.ok(get('restore-filelist').innerHTML.includes('role="alert"'));
  assert.equal(state.archive, 'archive');
  context.fetch = async () => response({files: [{name: 'retry.txt'}]});
  await context.restoreBrowse('');
  assert.equal(state.files[0].name, 'retry.txt');
});

test('a late missing-archive error cannot clear a newer successful selection', async () => {
  const {context, get, state} = page();
  state.job = 'job-id';
  const old = deferred();
  get('restore-archive-sel').value = 'old';
  context.fetch = () => old.promise;
  const pending = context.restoreBrowse('');
  get('restore-archive-sel').value = 'new';
  context.fetch = async () => response({files: [{name: 'current.txt'}]});
  await context.restoreBrowse('');
  const messageCount = context.messages.length;
  old.resolve(response({code: 'restore_archive_unavailable'}, 404));
  await pending;
  assert.equal(state.archive, 'new');
  assert.equal(state.files[0].name, 'current.txt');
  assert.equal(context.messages.length, messageCount);
});

test('multi-selection persists across directories and removes overlapping children', async () => {
  const {context, get, state} = page();
  state.job = 'job-id'; state.archive = 'archive';
  get('restore-archive-sel').value = 'archive';
  context.restorePrepare('Backup/Test1/file.txt', 'file.txt', '-');
  context.restorePrepare('Backup/Test2', 'Test2', 'd');
  context.restorePrepare('Backup/Test1', 'Test1', 'd');
  assert.deepEqual(Array.from(state.selections, item => item.path), ['Backup/Test2', 'Backup/Test1']);
  context.fetch = async () => response({files: []});
  await context.restoreBrowse('Other');
  assert.equal(state.selections.length, 2);
  context.restorePrepare('Backup/Test1', 'Test1', 'd');
  assert.deepEqual(Array.from(state.selections, item => item.path), ['Backup/Test2']);
  assert.equal(get('restore-source-path').value, 'Backup/Test2');
});

test('changing only the second selected item invalidates an in-flight precheck', async () => {
  const {context, get, state} = page();
  state.job = 'job-id'; state.archive = 'archive';
  get('restore-target-path').value = '/mnt/user/test';
  context.restorePrepare('Backup/Test1', 'Test1', 'd');
  context.restorePrepare('Backup/Test2', 'Test2', 'd');
  const check = deferred();
  let body;
  context.fetch = (url, options) => { body = JSON.parse(options.body); return check.promise; };
  const pending = context.restoreRunPrecheck();
  assert.deepEqual(body.source_paths, ['Backup/Test1', 'Backup/Test2']);
  context.restorePrepare('Backup/Test2', 'Test2', 'd');
  check.resolve(response({ok: true}));
  await pending;
  assert.equal(state.precheck, null);
});

test('archive changes reset all selected paths', async () => {
  const {context, get, state} = page();
  state.job = 'job-id'; state.archive = 'old';
  context.restorePrepare('Backup/Test1', 'Test1', 'd');
  context.restorePrepare('Backup/Test2', 'Test2', 'd');
  get('restore-archive-sel').value = 'new';
  context.fetch = async () => response({files: []});
  await context.restoreBrowse('');
  assert.equal(state.selections.length, 0);
});

test('a pending folder response does not overwrite a path being entered', async () => {
  const {context, get, state} = page();
  state.job = 'job-id'; state.archive = 'archive';
  get('restore-archive-sel').value = 'archive';
  get('restore-archive-path').value = '/';
  const files = deferred();
  context.fetch = () => files.promise;
  const pending = context.restoreBrowse('');
  get('restore-archive-path').value = '/Backup/Test1';
  files.resolve(response({files: []}));
  await pending;
  assert.equal(get('restore-archive-path').value, '/Backup/Test1');
});

function directory(path) { return {name: path.split('/').pop(), path, type: 'd'}; }
function file(path) { return {name: path.split('/').pop(), path, type: '-'}; }
function treePage(listings) {
  const result = page();
  result.state.job = 'job-id';
  result.get('restore-archive-sel').value = 'archive';
  result.calls = [];
  result.context.fetch = async url => {
    const path = new URL(url, 'http://localhost').searchParams.get('path');
    result.calls.push(path);
    assert.ok(Object.hasOwn(listings, path), `Unexpected folder request: ${path}`);
    return response({files: listings[path]});
  };
  return result;
}

test('first archive opening reaches the first useful folder without selecting anything', async () => {
  const {context, state, get, calls} = treePage({
    '': [directory('mnt')], mnt: [directory('mnt/user')],
    'mnt/user': [directory('mnt/user/Documents')],
    'mnt/user/Documents': [directory('mnt/user/Documents/Backup'), file('mnt/user/Documents/Welcome.txt')],
  });
  await context.restoreBrowse('');
  assert.equal(state.path, 'mnt/user/Documents');
  assert.equal(get('restore-archive-path').value, '/mnt/user/Documents');
  assert.equal(state.selections.length, 0);
  assert.deepEqual(calls, ['', 'mnt', 'mnt/user', 'mnt/user/Documents']);
  assert.ok(state.folderTree.expanded.has('mnt/user'));
  assert.match(get('restore-folder-tree').innerHTML, /aria-current="location"[^>]*title="\/mnt\/user\/Documents"/);
  assert.match(get('restore-folder-tree').innerHTML, /Backup/);
  assert.doesNotMatch(get('restore-folder-tree').innerHTML, /Welcome.txt/);
  // Choosing the archive root later must really display its contents.
  await context.restoreBrowse('');
  assert.equal(state.path, '');
  assert.equal(calls.length, 5);
});

for (const contents of [[], [file('readme.txt')], [directory('A'), directory('B')]]) {
  test(`initial auto-navigation stops at empty, file or branching folder: ${JSON.stringify(contents)}`, async () => {
    const {context, state, calls} = treePage({'': contents});
    await context.restoreBrowse('');
    assert.equal(state.path, '');
    assert.deepEqual(calls, ['']);
  });
}

test('expanding a branch keeps the file view and selection, and reuses known folders', async () => {
  const {context, state, get, calls} = treePage({
    '': [directory('A'), directory('B')], A: [directory('A/Documents')],
    'A/Documents': [directory('A/Documents/One'), directory('A/Documents/Two')],
  });
  await context.restoreBrowse('');
  context.restorePrepare('B', 'B', 'd');
  const filesHtml = get('restore-filelist').innerHTML;
  await context.restoreToggleFolder('A');
  assert.deepEqual(calls, ['', 'A', 'A/Documents']);
  assert.equal(state.path, '');
  assert.equal(get('restore-filelist').innerHTML, filesHtml);
  assert.deepEqual(Array.from(state.selections, item => item.path), ['B']);
  assert.match(get('restore-folder-tree').innerHTML, /One/);
  await context.restoreToggleFolder('A');
  assert.doesNotMatch(get('restore-folder-tree').innerHTML, />Documents</);
  await context.restoreToggleFolder('A');
  assert.equal(calls.length, 3);
  assert.match(get('restore-folder-tree').innerHTML, />Documents</);
});

test('a pending expansion cannot reopen a collapsed folder', async () => {
  const {context, state} = treePage({'': [directory('A'), directory('B')]});
  await context.restoreBrowse('');
  const first = deferred();
  context.fetch = () => first.promise;
  const pending = context.restoreToggleFolder('A');
  await context.restoreToggleFolder('A');
  first.resolve(response({files: [directory('A/Child')]}));
  await pending;
  assert.equal(state.folderTree.expanded.has('A'), false);
  assert.equal(state.folderTree.expanded.has('A/Child'), false);
});

test('tree load failure stays retryable, and source changes discard pending branches', async () => {
  const {context, state, get} = treePage({'': [directory('A'), directory('B')]});
  await context.restoreBrowse('');
  context.fetch = async () => response({code: 'internal_error'}, 500);
  await context.restoreToggleFolder('A');
  assert.match(get('restore-folder-tree').innerHTML, /data-restore-action="tree-retry"/);
  context.fetch = async () => response({files: [file('A/ok.txt')]});
  await context.restoreToggleFolder('A', true);
  assert.doesNotMatch(get('restore-folder-tree').innerHTML, /tree-retry/);
  const old = deferred();
  context.fetch = () => old.promise;
  const pending = context.restoreToggleFolder('B');
  get('restore-archive-sel').value = 'new';
  context.fetch = async () => response({files: [file('current.txt')]});
  await context.restoreBrowse('');
  old.resolve(response({code: 'restore_archive_unavailable'}, 404));
  await pending;
  assert.equal(state.archive, 'new');
  assert.equal(state.folderTree.nodes.has('B'), false);
  assert.equal(state.files[0].name, 'current.txt');
});

test('direct path entry reveals ancestors and opens their complete listing on demand', async () => {
  const {context, state, get, calls} = treePage({
    'A/Documents': [file('A/Documents/file.txt')],
    A: [directory('A/Documents'), directory('A/Other')],
  });
  await context.restoreBrowse('A/Documents');
  assert.equal(state.path, 'A/Documents');
  assert.equal(state.folderTree.nodes.get('A').loaded, false);
  assert.match(get('restore-folder-tree').innerHTML, /Documents/);
  await context.restoreToggleFolder('A');
  await context.restoreToggleFolder('A');
  assert.deepEqual(calls, ['A/Documents', 'A']);
  assert.match(get('restore-folder-tree').innerHTML, /Other/);
});

test('clicking a folder while its expansion loads shares one request', async () => {
  const {context, state} = treePage({'': [directory('A'), directory('B')]});
  await context.restoreBrowse('');
  const listing = deferred();
  let calls = 0;
  context.fetch = () => { calls++; return listing.promise; };
  const expand = context.restoreToggleFolder('A');
  const browse = context.restoreBrowse('A');
  listing.resolve(response({files: [file('A/current.txt')]}));
  await Promise.all([expand, browse]);
  assert.equal(calls, 1);
  assert.equal(state.path, 'A');
  assert.equal(state.files[0].name, 'current.txt');
});

for (const language of ['de', 'en']) test(`restore plan table distinguishes actions and simulation (${language})`, () => {
  const {context, get, labels} = page(language);
  const data = {conflict_mode: 'overwrite', items: [
    {path: 'Backup/Folder', type: 'd', destination_path: '/target/Folder', destination_exists: true},
    {path: 'Backup/file.txt', type: '-', destination_path: '/target/file.txt', destination_exists: true},
    {path: 'Backup/new.txt', type: '-', destination_path: '/target/new.txt', destination_exists: false},
  ]};
  context._restoreRenderDestinationMap(data);
  let html = get('restore-destination-map').innerHTML;
  assert.match(html, /<table aria-labelledby="restore-mapping-title">/);
  assert.equal((html.match(/<th scope="col">/g) || []).length, 3);
  for (const key of ['mappingWhat', 'mappingHow', 'mappingWhere', 'mappingMerge', 'mappingReplace', 'mappingRestore']) assert.ok(html.includes(labels.restore[key]));
  assert.match(html, /\/target\/Folder/);
  assert.match(html, /Backup\/Folder/);
  data.conflict_mode = 'rename';
  context._restoreRenderDestinationMap(data);
  html = get('restore-destination-map').innerHTML;
  assert.ok(html.includes(labels.restore.mappingRename));
  assert.ok(html.includes(labels.restore.mappingRenameHint));
  get('restore-dry-run').checked = true;
  data.conflict_mode = 'skip'; data.items[0].skipped = true;
  context._restoreRenderDestinationMap(data);
  html = get('restore-destination-map').innerHTML;
  assert.ok(html.includes(labels.restore.mappingSkip));
  assert.ok(html.includes(labels.restore.mappingSimulate));
  assert.ok(html.includes(labels.restore.mappingNoChanges));
  assert.ok(!html.includes(labels.restore.mappingReplace));
  context._restoreRenderDestinationMap(null);
  assert.equal(get('restore-destination-map').innerHTML, '');
});

test('single matching folder shows the timestamped child destination for rename only', () => {
  const {context, get, labels} = page();
  const data = {conflict_mode: 'rename', items: [
    {path: 'Backup/Test1', type: 'd', destination_path: '/target/Test1', direct_contents: true},
  ]};
  context._restoreRenderDestinationMap(data);
  assert.match(get('restore-destination-map').innerHTML, /class="restore-mapping-target"><span class="mono">\/target\/Test1\/Test1<\/span>/);
  assert.ok(get('restore-destination-map').innerHTML.includes(labels.restore.mappingRenameHint));
  data.conflict_mode = 'overwrite';
  context._restoreRenderDestinationMap(data);
  assert.match(get('restore-destination-map').innerHTML, /class="restore-mapping-target"><span class="mono">\/target\/Test1<\/span>/);
  assert.ok(!get('restore-destination-map').innerHTML.includes(labels.restore.mappingRenameHint));
});

for (const language of ['de', 'en']) for (const simulation of [false, true]) {
  test(`technical precheck lists every selection and the requested operation (${language}, simulation=${simulation})`, async () => {
    const {context, get, state, labels} = page(language);
    state.job = 'job-id'; state.archive = 'archive';
    get('restore-target-path').value = '/mnt/user/test';
    get('restore-dry-run').checked = simulation;
    context.restorePrepare('Backup/Test1', 'Test1', 'd');
    context.restorePrepare('Backup/Test2', 'Test2', 'd');
    const data = {ok: true, archive: 'archive', source_path: 'Backup/Test1',
      target_dir: '/mnt/user/test', conflict_mode: 'skip', target_mountpoint: '/mnt/user',
      target_free_bytes: 1024, dry_run: false, dry_run_exit_code: 0,
      dry_run_stdout: 'Precheck is metadata-only (no extraction).', items: [
        {path: 'Backup/Test1', type: 'd', destination_path: '/mnt/user/test/Test1', destination_exists: true, skipped: true},
        {path: 'Backup/Test2', type: 'd', destination_path: '/mnt/user/test/Test2', destination_exists: false, skipped: false},
      ]};
    context.fetch = async (_, request) => {
      const body = JSON.parse(request.body);
      assert.deepEqual(body.source_paths, ['Backup/Test1', 'Backup/Test2']);
      assert.equal(body.dry_run, simulation);
      return response(data);
    };
    await context.restoreRunPrecheck();
    const output = get('restore-precheck-output').textContent;
    assert.ok(output.includes(labels.restore.metadataPrecheckDetail));
    assert.ok(output.includes(labels.restore.metadataPrecheckScope));
    assert.ok(output.includes(labels.restore[simulation ? 'plannedSimulation' : 'plannedRestore']));
    for (const item of data.items) {
      assert.ok(output.includes(item.path));
      assert.ok(output.includes(item.destination_path));
    }
    assert.ok(output.includes(labels.restore.mappingSkip));
    assert.ok(output.includes(labels.restore[simulation ? 'mappingSimulate' : 'mappingRestore']));
    assert.ok(!output.includes('(Exit 0)'));
    assert.ok(!output.includes(labels.restore.dryRunOutput));
    assert.equal(get('restore-confirm-check').checked, false);

    get('restore-conflict-mode').value = 'rename';
    data.conflict_mode = 'rename';
    data.target_mountpoint = '';
    data.items = [{path: 'Backup/Test1', type: 'd', destination_path: '/mnt/user/test/Test1', direct_contents: true}];
    await context.restoreRunPrecheck();
    assert.ok(get('restore-precheck-output').textContent.includes('/mnt/user/test/Test1/Test1'));
    assert.ok(get('restore-precheck-output').textContent.includes(labels.restore.mappingTimestamp));
    assert.ok(get('restore-precheck-output').textContent.includes(labels.restore.mountpointUnknown));
  });
}

for (const language of ['de', 'en']) test(`searching a large selection preserves hidden items (${language})`, () => {
  const {context, get, state, labels, renderers} = page(language);
  context._restoreRenderSelectedBox = renderers.selection;
  state.job = 'job-id'; state.archive = 'archive';
  state.selections = Array.from({length: 180}, (_, index) => ({path: `Documents/Folder-${index}/notes.txt`, name: 'notes.txt', type: '-'}));
  state.selectedPath = state.selections[0].path;
  get('restore-selection-filter').value = 'folder-179';
  renderers.selection();
  assert.equal((get('restore-selected-list').innerHTML.match(/<tr>/g) || []).length, 1);
  assert.match(get('restore-selected-list').innerHTML, /Folder-179/);
  assert.equal(state.selections.length, 180);
  assert.match(get('restore-selection-name').textContent, /180/);
  assert.equal(get('restore-clear-selection-btn').disabled, false);
  // Removing the visible match leaves the other 179 selections intact.
  context.restorePrepare('Documents/Folder-179/notes.txt', 'notes.txt', '-');
  assert.equal(state.selections.length, 179);
  assert.ok(get('restore-selected-list').innerHTML.includes(labels.restore.selectionNoMatches));
  get('restore-selection-filter').value = '';
  renderers.selection();
  assert.equal((get('restore-selected-list').innerHTML.match(/<tr>/g) || []).length, 179);
  // Archive changes clear both the selection and its filter/expanded view.
  get('restore-selection-details').open = true;
  get('restore-selection-filter').value = 'old';
  context.restoreClearFileSelection();
  assert.equal(get('restore-selection-filter').value, '');
  assert.equal(get('restore-selection-details').open, false);
  assert.equal(get('restore-clear-selection-btn').disabled, true);
});

test('target summary describes planned operation, conflict behavior and configured roots', () => {
  const {get, state, labels, renderers} = page('de');
  state.selections = [{path: 'Backup/Test1', name: 'Test1', type: 'd'}, {path: 'Backup/file', name: 'file', type: '-'}];
  state.allowedTargetRoots = ['/mnt/cache/restore'];
  get('restore-dry-run').checked = true;
  for (const mode of ['skip', 'overwrite', 'rename']) {
    get('restore-conflict-mode').value = mode;
    renderers.summary();
    assert.equal(get('restore-conflict-help').textContent, labels.restore[`${mode}Help`]);
    assert.match(get('restore-target-roots-hint').textContent, /\/mnt\/cache\/restore/);
    assert.ok(!get('restore-target-roots-hint').textContent.includes('{roots}'));
    assert.equal(get('restore-mode-badge').textContent, labels.restore.dryRunActive);
    assert.equal(get('restore-summary-dry-run').textContent, labels.restore.plannedSimulation);
  }
  get('restore-dry-run').checked = false;
  renderers.summary();
  assert.equal(get('restore-mode-badge').textContent, labels.restore.restoreActive);
  assert.equal(get('restore-summary-dry-run').textContent, labels.restore.plannedRestore);
});


for (const language of ['de', 'en']) {
  test(`compact restore status and accurate results in ${language}`, () => {
    const {context, get, labels} = page(language);
    const run = {state: 'running', phase: 'extract', archive: 'demo', source_paths: ['Backup/Test1'],
      target_dir: '/restore', conflict_mode: 'skip', staging_path: '/restore/.bbui-restore-stage-test',
      duration_seconds: 61, lines: ['hundreds of file paths should not appear']};
    context.renderRestoreRunStatus(run);
    let html = get('restore-run-status').innerHTML;
    assert.ok(html.includes(labels.restore.phaseExtract));
    assert.ok(html.includes('/restore/.bbui-restore-stage-test'));
    assert.ok(!html.includes(run.lines[0]));
    context.renderRestoreRunStatus({...run, state: 'done', counts_complete: true,
      counts: {files: 123, directories: 4, symlinks: 0, other: 0}});
    html = get('restore-run-status').innerHTML;
    assert.ok(html.includes(labels.restore.runCompleted));
    assert.ok(html.includes('123'));
    assert.ok(html.includes(labels.restore.restoredDirectories));
    assert.ok(!html.includes('restore-run-stage'));
    context.renderRestoreRunStatus({...run, state: 'done', dry_run: true, counts_complete: true,
      counts: {files: 0, directories: 0}});
    html = get('restore-run-status').innerHTML;
    assert.ok(html.includes(labels.restore.simulationNoWrites));
    assert.ok(!html.includes('restore-result-counts'));
    context.renderRestoreRunStatus(run, false);
    assert.ok(get('restore-run-status').innerHTML.includes(labels.restore.connectionWaiting));
    assert.ok(!get('restore-run-status').innerHTML.includes('restore-run-banner running'));
  });
}

test('a failed restore response is terminal even though its error field is populated', async () => {
  const {context, state, get, labels} = page();
  state.activeRestoreId = 'failed-run';
  context.fetch = async () => response({state: 'error', error: 'Destination full', source_paths: ['folder'],
    counts: {files: 1, directories: 0}, counts_complete: false});
  await context._pollRestoreState('failed-run');
  assert.equal(state.completed, true);
  assert.ok(get('restore-run-status').innerHTML.includes('Destination full'));
  assert.ok(!get('restore-run-status').innerHTML.includes(labels.restore.restoredFiles));
});

test('old history without counts does not invent a zero-file summary', () => {
  const {context} = page();
  assert.equal(context.restoreCountSummary({state: 'done'}), '');
});


test('successful polling updates the header and completion controls', async () => {
  const {context, state, get, labels} = page();
  state.activeRestoreId = 'complete-run';
  context.fetch = async () => response({state: 'done', source_paths: ['folder'],
    counts: {files: 3, directories: 1}, counts_complete: true});
  await context._pollRestoreState('complete-run');
  assert.equal(state.completed, true);
  assert.equal(get('restore-precheck-badge').textContent, labels.restore.restoreSuccessfulShort);
  assert.ok(get('restore-run-status').innerHTML.includes(labels.restore.runCompleted));
});


test('failed history entries retain their technical details', async () => {
  const {context, get} = page();
  context.renderRestoreHistory = () => {};
  context.fetch = async () => response({restore_id: 'failed-history', state: 'error',
    error: 'Destination full', lines: ['Borg diagnostic'], source_paths: ['folder']});
  await context.restoreLoadHistoryDetail('failed-history');
  const html = get('restore-history-detail-failed-history').innerHTML;
  assert.ok(html.includes('Destination full'));
  assert.ok(html.includes('Borg diagnostic'));
});
