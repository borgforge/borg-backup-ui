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
