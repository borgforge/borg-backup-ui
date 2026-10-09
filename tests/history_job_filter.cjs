const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

test('History distinguishes same-name jobs and preserves IDs on refresh and language changes', async () => {
  const translations = Object.fromEntries(['de', 'en'].map(language =>
    [language, JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'))]));
  let language = 'de';
  const listeners = {};
  const filter = {
    value: '', html: '',
    get innerHTML() { return this.html; },
    set innerHTML(value) { this.html = value; this.value = ''; },
  };
  const jobs = ['local', 'usb', 'smb', 'storagebox'].map((location, index) => ({
    job_id: `6593fe79-1608-42df-917b-6e45f111160${index}`, name: 'Appdata', location,
  }));
  jobs.push({job_id: 'escaped', name: '<Docs & Photos>', location: 'usb'});
  const requests = [];
  const context = vm.createContext({
    URLSearchParams,
    window: {
      BBUI: {components: {i18n: {
        t: key => key.split('.').reduce((value, part) => value?.[part], translations[language]) || key,
        getLanguage: () => language,
      }}},
      addEventListener: (name, callback) => { listeners[name] = callback; },
    },
    document: {getElementById: id => id === 'history-filter-type' ? filter : null},
    fetch: async url => {
      requests.push(new URL(url, 'http://localhost'));
      return {ok: true, json: async () => ({jobs, entries: [], total: 0})};
    },
    hideEl() {},
    showMsg: (_id, _severity, message) => assert.fail(message),
  });
  vm.runInContext(fs.readFileSync('ui/js/utils/format.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('ui/js/pages/history.js', 'utf8'), context);

  await context.refreshHistory();
  assert.match(filter.innerHTML, />Alle Jobs<\/option>/);
  for (const [index, location] of ['Lokal', 'USB', 'SMB', 'Storagebox'].entries()) {
    assert.ok(filter.innerHTML.includes(`value="${jobs[index].job_id}">Appdata – ${location}</option>`));
  }
  assert.ok(filter.innerHTML.includes('&lt;Docs &amp; Photos&gt; – USB'));
  filter.value = jobs[1].job_id;
  await context.refreshHistory();
  assert.equal(requests.at(-1).searchParams.get('job_key'), jobs[1].job_id);
  assert.equal(filter.value, jobs[1].job_id);

  language = 'en';
  listeners['bbui:language-changed']();
  assert.match(filter.innerHTML, />All jobs<\/option>/);
  assert.ok(filter.innerHTML.includes('Appdata – Local'));
  assert.equal(filter.value, jobs[1].job_id);
  assert.equal(requests.length, 2);

  filter.value = '';
  await context.refreshHistory();
  assert.equal(requests.at(-1).searchParams.has('job_key'), false);
  assert.equal(filter.value, '');
});

for (const language of ['de', 'en']) {
  test(`History explains hook failures and retains safe legacy fallback (${language})`, () => {
    const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
    const context = vm.createContext({
      window: {BBUI: {components: {i18n: {
        t: (key, params = {}) => (key.split('.').reduce((v, part) => v?.[part], labels) || key)
          .replace(/\{(\w+)\}/g, (_, name) => params[name] ?? ''),
        getLanguage: () => language,
      }}}, addEventListener() {}},
    });
    vm.runInContext(fs.readFileSync('ui/js/utils/format.js', 'utf8'), context);
    vm.runInContext(fs.readFileSync('ui/js/pages/history.js', 'utf8'), context);
    const generic = {status: 'error', error_message: 'token=do-not-render'};
    assert.equal(context.historyRunDetailMessage(generic), labels.history.backupFailedDetails);
    assert.equal(context.historyRunDetailMessage({...generic, hook_results: {pre: {status: 'success'}}}), labels.history.backupFailedDetails);
    for (const [status, code] of [['failed', 41], ['timeout', 124], ['launch_failed', 2]]) {
      const pre = {...generic, exit_code: 2, hook_results: {pre: {name: '<img src=x onerror=alert(1)>', status, exit_code: code}}};
      const message = context.historyRunDetailMessage(pre);
      assert.ok(message.includes(labels.history.hookStates[status]));
      assert.ok(message.includes(String(code)));
      assert.ok(message.includes(labels.history.backupNotStarted));
      const html = context.renderHistoryRow(pre, 0);
      assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
      assert.ok(!html.includes('<img'));
      assert.ok(!html.includes('do-not-render'));
      assert.ok(html.includes(labels.history.exitCode));
      const both = {...pre, hook_results: {...pre.hook_results, post: {name: 'Cleanup', status: 'failed', exit_code: 42}}};
      const bothMessage = context.historyRunDetailMessage(both);
      assert.ok(bothMessage.includes('Pre') && bothMessage.includes('Post'));
      assert.ok(bothMessage.includes('42') && bothMessage.includes(labels.history.backupNotStarted));
    }
    const post = {...generic, backup_exit_code: 0, hook_results: {post: {name: 'Cleanup', status: 'failed', exit_code: 42}}};
    const postMessage = context.historyRunDetailMessage(post);
    assert.ok(postMessage.includes('Post') && postMessage.includes('42'));
    assert.ok(!postMessage.includes(labels.history.backupNotStarted));
    assert.ok(context.renderHistoryRow(post, 1).includes(labels.history.backupExitCode));
    assert.equal(context.historyRunDetailMessage({...post, status: 'success'}), '');
    assert.equal(context.historyRunDetailMessage({...post, status: 'cancelled'}), '');
  });
}
