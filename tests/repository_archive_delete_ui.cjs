const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function page() {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', disabled: false, innerHTML: '',
      classList: {add() {}, remove() {}}, focus() {},
      setAttribute() {}, removeAttribute() {},
      querySelectorAll: () => ['close-btn', 'cancel-btn', 'confirm-btn', 'phrase-input'].map(suffix => get(`repository-archive-delete-${suffix}`)),
    });
    return elements.get(id);
  };
  const requests = [];
  const context = vm.createContext({
    window: {BBUI: {}, addEventListener() {}}, document: {getElementById: get, querySelector: () => null},
    escHtml: value => String(value), hideEl() {}, showMsg() {},
    apiErrorMessage: result => result.message,
    fetch: async (url, options) => {
      requests.push({url, ...options});
      return {ok: false, status: 409, json: async () => ({message: 'Archive changed'})};
    },
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/storage.js', 'utf8'), context);
  context.storageFormatDateTime = value => value;
  const state = context.window.BBUI.storageState;
  state.data = {groups: {local: [{repository_key: 'repo1', display_name: 'Test', location: 'local'}]}};
  const inventory = {can_delete: true, repository_id: 'b'.repeat(64), archives: [
    {name: 'first', id: 'a'.repeat(64)}, {name: 'second', id: 'c'.repeat(64)},
  ]};
  state.archiveCache.repo1 = {data: inventory};
  const input = get('repository-archive-delete-phrase-input');
  const button = get('repository-archive-delete-confirm-btn');
  const type = value => { input.value = value; context.updateRepositoryArchiveDeleteConfirmation(); };
  return {context, state, requests, input, button, type, inventory};
}

test('only exact DELETE enables deletion, including calls bypassing the disabled button', async () => {
  const {context, requests, button, type} = page();
  context.openRepositoryArchiveDelete('repo1', 'first');
  assert.equal(button.disabled, true);
  for (const value of ['', 'delete', 'DELETE ', ' DELETE', 'first']) {
    type(value);
    assert.equal(button.disabled, true);
    await context.confirmRepositoryArchiveDelete();
  }
  assert.equal(requests.length, 0);
  type('DELETE');
  assert.equal(button.disabled, false);
  type('');
  assert.equal(button.disabled, true);
  type('DELETE');
  await context.confirmRepositoryArchiveDelete();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].method, 'DELETE');
  assert.deepEqual(JSON.parse(requests[0].body), {
    repository_key: 'repo1', archive: 'first', expected_archive_id: 'a'.repeat(64),
    expected_repository_id: 'b'.repeat(64), confirmed: true, confirmation_phrase: 'DELETE',
  });
});

test('closing and selecting another archive always clears the previous confirmation', () => {
  const {context, input, button, type} = page();
  context.openRepositoryArchiveDelete('repo1', 'first');
  type('DELETE');
  context.closeRepositoryArchiveDelete();
  assert.equal(input.value, '');
  assert.equal(button.disabled, true);
  context.openRepositoryArchiveDelete('repo1', 'second');
  assert.equal(input.value, '');
  assert.equal(button.disabled, true);
});

test('in-flight deletion locks the input and prevents duplicate requests; errors allow cancellation', async () => {
  const {context, state, input, button, type} = page();
  let complete, calls = 0;
  context.fetch = () => { calls++; return new Promise(resolve => { complete = resolve; }); };
  context.openRepositoryArchiveDelete('repo1', 'first');
  type('DELETE');
  const deletion = context.confirmRepositoryArchiveDelete();
  assert.equal(input.disabled, true);
  assert.equal(button.disabled, true);
  context.closeRepositoryArchiveDelete();
  assert.equal(state.archiveDeleteConfirmation.running, true);
  await context.confirmRepositoryArchiveDelete();
  assert.equal(calls, 1);
  complete({ok: false, status: 409, json: async () => ({message: 'Busy'})});
  await deletion;
  assert.equal(input.disabled, false);
  type('');
  assert.equal(button.disabled, true);
  context.closeRepositoryArchiveDelete();
  assert.equal(state.archiveDeleteConfirmation, null);
});

test('successful deletion cannot leave a confirmed dialog for the next archive', async () => {
  const {context, state, inventory, input, button, type} = page();
  context.fetch = async () => ({ok: true, json: async () => ({ok: true})});
  context.refreshStorage = async () => {};
  context.loadRepositoryArchives = async () => { state.archiveCache.repo1 = {data: inventory}; };
  context.openRepositoryArchiveDelete('repo1', 'first');
  type('DELETE');
  await context.confirmRepositoryArchiveDelete();
  assert.equal(state.archiveDeleteConfirmation, null);
  assert.equal(input.value, '');
  assert.equal(button.disabled, true);
  context.openRepositoryArchiveDelete('repo1', 'second');
  assert.equal(input.value, '');
  assert.equal(button.disabled, true);
});
