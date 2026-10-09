/** Exercise the shipped widget script with a controllable clock and cache endpoint. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync('plugin/borg-backup-ui-dashboard.page', 'utf8').split('<script>')[1].split('</script>')[0];

function snapshot() {
  return {schema_version: 1, cache_state: 'fresh', generated_at: '2026-10-09T20:00:00Z',
    jobs: {enabled: 2, successful: 1, skipped: 1, warnings: 0, failed: 0, running: 0, items: [
      {enabled: true, last_status: 'success', last_timestamp: '2026-10-09T20:00:00Z'},
      {enabled: true, last_status: 'skipped', last_timestamp: '2026-10-09T19:00:00Z'}]},
    repositories: {online: 2, total: 2},
    latest_backup: {name: 'Appdata', status: 'ok', timestamp: '2026-10-09T20:00:00Z', duration: '6m', detail: 'stale label'},
    next_backups: [{name: 'Appdata', scheduled_at: '2026-10-10T06:00:00Z', time: 'Tomorrow 06:00'}],
    restore_proof: {configured: 0}};
}

function setup(initial = snapshot()) {
  let now = Date.parse('2026-10-09T20:14:00Z');
  let response = initial;
  let requests = 0;
  let pending;
  let background = 'rgb(255, 255, 255)';
  const intervals = [], timeouts = [];
  function element() {
    return {attrs: {}, children: [], style: {}, listeners: {}, value: '',
      classList: {add() {}, remove() {}},
      get textContent() { return this.value + this.children.map(child => child.textContent).join(''); },
      set textContent(value) { this.value = String(value); this.children = []; },
      setAttribute(key, value) { this.attrs[key] = value; },
      getAttribute(key) { return this.attrs[key]; },
      addEventListener(key, fn) { this.listeners[key] = fn; },
      appendChild(node) { this.children.push(node); },
      querySelector() { return element(); }};
  }
  const fields = Object.fromEntries(['job_total','job_label','cache_note','success','skipped','warnings','failed','running','repos',
    'latest_icon','latest_name','latest_detail','latest_label','restore_label','restore_detail','overall_label','generated','fetched','next_rows']
    .map(key => {const node = element(); node.attrs['data-bbui'] = key; return [key, node];}));
  const root = element(), tile = element(), refresh = element(), collapse = element(), body = element();
  root.parentElement = tile;
  root.closest = () => tile;
  root.attrs['data-endpoint'] = '/plugins/borg-backup-ui/widget-status.php';
  tile.querySelectorAll = () => Object.values(fields);
  tile.querySelector = selector => ({'[data-bbui-body]': body, '[data-bbui-refresh]': refresh, '[data-bbui-collapse]': collapse}[selector]);
  const initialNode = {textContent: JSON.stringify(initial)};
  const context = vm.createContext({console, AbortController, SyntaxError,
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() {return now;} },
    document: {getElementById: id => id === 'bbui-widget' ? root : initialNode, createElement: element},
    window: {getComputedStyle: () => ({backgroundColor: background}), setInterval: fn => intervals.push(fn),
      setTimeout: fn => {timeouts.push(fn); return timeouts.length;}, clearTimeout() {}},
    fetch: async (_url, opts) => {
      requests++;
      if (response === 'pending') return new Promise((resolve, reject) => {
        pending = resolve;
        opts.signal.addEventListener('abort', () => reject(new Error('timeout')));
      });
      if (response instanceof Error) throw response;
      return {ok: response !== 'http-error', json: async () => response};
    },
  });
  vm.runInContext(source, context);
  return {fields, refresh, collapse, body, tile, timeouts,
    flush: () => new Promise(resolve => setImmediate(resolve)),
    advance: ms => {now += ms;}, tick: () => intervals[0](),
    respond: data => {response = data;}, requests: () => requests,
    background: value => {background = value;},
    resolve: data => pending({ok: true, json: async () => data}),
    click: () => refresh.listeners.click({preventDefault() {}})};
}

test('unchanged snapshots age labels while separating fetch time from data time', async () => {
  const ui = setup(); await ui.flush();
  assert.equal(ui.fields.latest_detail.textContent, '14m ago - Duration 6m');
  const generated = ui.fields.generated.textContent, fetched = ui.fields.fetched.textContent;
  ui.advance(120000); ui.tick(); await ui.flush();
  assert.equal(ui.fields.latest_detail.textContent, '16m ago - Duration 6m');
  assert.equal(ui.fields.generated.textContent, generated);
  assert.notEqual(ui.fields.fetched.textContent, fetched);
  assert.equal(ui.fields.skipped.textContent, '1');
  assert.equal(ui.fields.warnings.textContent, '0');
  assert.equal(ui.fields.overall_label.textContent, 'OK');
});

test('schedule labels cross midnight and do not advertise elapsed cached times as upcoming', async () => {
  const ui = setup(); await ui.flush();
  assert.match(ui.fields.next_rows.textContent, /Tomorrow/);
  ui.advance(4 * 3600000); ui.tick(); await ui.flush();
  assert.match(ui.fields.next_rows.textContent, /Today/);
  ui.advance(7 * 3600000); ui.tick(); await ui.flush();
  assert.match(ui.fields.next_rows.textContent, /Scheduled.*\(past\)/);
});

test('separate overdue condition preserves a warning for a skipped job', async () => {
  const data = snapshot(); data.jobs.items[1].backup_overdue_after = '2026-10-09T20:15:00Z';
  data.latest_backup.status = 'skipped';
  const ui = setup(data); await ui.flush();
  assert.equal(ui.fields.latest_label.textContent, 'Skipped');
  ui.advance(120000); ui.tick(); await ui.flush();
  assert.equal(ui.fields.skipped.textContent, '1');
  assert.equal(ui.fields.warnings.textContent, '1');
  assert.equal(ui.fields.overall_label.textContent, 'Warning');
});

test('new cache events replace counts, latest run and restore evidence on manual refresh', async () => {
  const ui = setup(); await ui.flush();
  const data = snapshot(); data.jobs.items[0].last_status = 'error';
  data.latest_backup = {name: 'New run', status: 'error', timestamp: '2026-10-09T20:14:00Z'};
  data.jobs.items[0].restore_verification_status = 'verified';
  ui.respond(data); ui.click(); await ui.flush();
  assert.equal(ui.fields.failed.textContent, '1');
  assert.equal(ui.fields.latest_name.textContent, 'New run');
  assert.match(ui.fields.restore_label.textContent, /1\/2 verified/);
});

for (const [name, response] of [['HTTP', 'http-error'], ['invalid JSON', new SyntaxError('bad JSON')],
  ['invalid schema', {}], ['null', null], ['invalid counts', {...snapshot(), jobs: {enabled: 'two'}}]]) {
  test(name + ' failures retain last evidence and show feedback through clock ticks', async () => {
    const ui = setup(); await ui.flush();
    const fetched = ui.fields.fetched.textContent;
    ui.respond(response); ui.click(); await ui.flush();
    assert.match(ui.fields.cache_note.textContent, /status cache|Status cache/);
    assert.equal(ui.fields.latest_name.textContent, 'Appdata');
    assert.equal(ui.fields.fetched.textContent, fetched);
    ui.advance(120000); ui.tick(); await ui.flush();
    assert.equal(ui.fields.latest_detail.textContent, '16m ago - Duration 6m');
    assert.notEqual(ui.fields.cache_note.textContent, '');
    ui.respond(snapshot()); ui.click(); await ui.flush();
    assert.equal(ui.fields.cache_note.textContent, '');
  });
}

test('pending requests cannot overlap and a timeout permits retry', async () => {
  const ui = setup(); await ui.flush();
  ui.respond('pending'); ui.click(); ui.tick(); ui.click();
  assert.equal(ui.requests(), 2);
  assert.equal(ui.refresh.attrs['aria-busy'], 'true');
  ui.timeouts.at(-1)(); await ui.flush();
  assert.match(ui.fields.cache_note.textContent, /not reachable/);
  assert.equal(ui.refresh.attrs['aria-busy'], 'false');
  ui.respond(snapshot()); ui.click(); await ui.flush();
  assert.equal(ui.requests(), 3);
});

test('legacy cache hides stale relative text, palettes follow host background, collapse is accessible', async () => {
  const data = snapshot(); delete data.latest_backup.timestamp; delete data.next_backups[0].scheduled_at;
  const ui = setup(data); await ui.flush();
  assert.equal(ui.fields.latest_detail.textContent, 'Duration 6m');
  assert.match(ui.fields.next_rows.textContent, /pending next update/);
  assert.equal(ui.tile.attrs['data-bbui-theme'], 'light');
  ui.background('rgb(30, 30, 30)'); ui.tick(); await ui.flush();
  assert.equal(ui.tile.attrs['data-bbui-theme'], 'dark');
  ui.collapse.listeners.click({preventDefault() {}});
  assert.equal(ui.body.style.display, 'none');
  assert.equal(ui.collapse.attrs['aria-expanded'], 'false');
});

test('missing initial evidence explicitly reports that no cached status is available', async () => {
  const ui = setup({}); await ui.flush();
  assert.match(ui.fields.cache_note.textContent, /No cached status available/);
});
