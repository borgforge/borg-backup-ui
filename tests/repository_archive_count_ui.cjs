const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function page() {
  const context = vm.createContext({
    window: {BBUI: {components: {i18n: {t: (key, params) => `${key}${params?.count !== undefined ? `:${params.count}` : ''}`}}}, addEventListener() {}},
    document: {getElementById: () => null},
    escHtml: value => String(value), hideEl() {}, showMsg() {},
    apiErrorMessage: result => result.message,
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/storage.js', 'utf8'), context);
  context.storageFormatDateTime = value => value;
  const repo = {repository_key: 'repo1', display_name: 'Test', last_info_refresh_at: '2026-09-13T10:54:00',
    repository_stats: {archives_count: 8, total_size: 100, total_csize: 80, unique_csize: 50}};
  const state = context.window.BBUI.storageState;
  state.data = {groups: {local: [repo]}};
  state.selectedRepositoryKey = 'repo1';
  state.selectedTab = 'archives';
  let renders = 0;
  context.renderStorage = () => { renders++; };
  const inventory = (count, names = ['latest']) => ({archive_count: count,
    archives: names.map(name => ({name, id: name, start: '2026-09-13T16:07:00'}))});
  const reply = data => ({ok: true, json: async () => data});
  return {context, state, repo, inventory, reply, renders: () => renders};
}

test('tab, list and overview use the live total, including a limited list and zero', async () => {
  const {context, state, repo, inventory, reply} = page();
  const original = JSON.stringify(repo);
  assert.equal(context.storageRepositoryArchiveCount(repo), 8);
  for (const count of [9, 150, 0]) {
    context.fetch = async () => reply(inventory(count, count ? ['latest'] : []));
    await context.loadRepositoryArchives('repo1', true);
    const workspace = context.renderStorageRepositoryWorkspace(repo, null);
    assert.ok(workspace.includes(`storage.repositoryTabArchives <b>${count}</b>`));
    assert.ok(context.renderRepositoryStats(repo).includes(`<strong>${count}</strong>`));
    if (count) assert.ok(workspace.includes(`storage.archiveCountMany:${count}`));
    else assert.ok(workspace.includes('storage.repositoryNoArchives'));
  }
  assert.equal(JSON.stringify(repo), original, 'live count must not rewrite stored info or its timestamp');
  assert.equal(context.storageRepositoryArchiveCount({repository_key: 'repo2', repository_stats: {archives_count: 4}}), 4);
  assert.equal(context.storageRepositoryArchiveCount({repository_key: 'unknown'}), null);
  assert.equal(state.archiveCache.repo1.data.archive_count, 0);
});

test('late archive responses cannot replace a newer list; failed refreshes retain a count and can be retried', async () => {
  const {context, state, repo, inventory, reply, renders} = page();
  const pending = [];
  context.fetch = () => new Promise(resolve => pending.push(resolve));
  const oldRequest = context.loadRepositoryArchives('repo1', true);
  const newRequest = context.loadRepositoryArchives('repo1', true);
  pending[1](reply(inventory(9, ['new'])));
  await newRequest;
  const rendered = renders();
  pending[0](reply(inventory(8, ['old'])));
  await oldRequest;
  assert.equal(renders(), rendered);
  assert.equal(state.archiveCache.repo1.data.archives[0].name, 'new');
  assert.equal(context.storageRepositoryArchiveCount(repo), 9);
  const failure = context.loadRepositoryArchives('repo1', true);
  assert.equal(context.storageRepositoryArchiveCount(repo), 9);
  pending[2]({ok: false, status: 503, json: async () => ({message: 'Unavailable'})});
  await failure;
  assert.equal(context.storageRepositoryArchiveCount(repo), 9);
  assert.equal(state.archiveCache.repo1.error, 'Unavailable');
  context.fetch = async () => reply(inventory(7));
  await context.loadRepositoryArchives('repo1');
  assert.equal(context.storageRepositoryArchiveCount(repo), 7);
  assert.equal(state.archiveCache.repo1.error, undefined);
});

test('page refresh reloads the visible list once and info refresh invalidates its old inventory', async () => {
  const {context, state, repo, inventory, reply} = page();
  const calls = [];
  let count = 9;
  context.fetch = async url => {
    calls.push(url);
    if (url === '/api/storage') return reply(state.data);
    if (url === '/api/jobs') return reply({jobs: []});
    if (url === '/api/storage/check/state') return reply({running: false});
    if (url === '/api/repositories/info') {
      repo.repository_stats.archives_count = count;
      return reply({ok: true});
    }
    if (url.startsWith('/api/repositories/archives?')) return reply(inventory(count));
    assert.fail(`Unexpected request: ${url}`);
  };
  await context.refreshStorage();
  assert.equal(context.storageRepositoryArchiveCount(repo), 9);
  assert.equal(calls.filter(url => url.startsWith('/api/repositories/archives?')).length, 1);
  state.selectedTab = 'overview';
  count = 7;
  await context.refreshRepositoryInfo('repo1');
  assert.equal(state.archiveCache.repo1, undefined);
  assert.equal(context.storageRepositoryArchiveCount(repo), 7);
  assert.equal(calls.filter(url => url.startsWith('/api/repositories/archives?')).length, 1,
    'refreshing overview must not add an archive scan');
  await context.loadRepositoryArchives('repo1');
  assert.equal(context.storageRepositoryArchiveCount(repo), 7);
});
