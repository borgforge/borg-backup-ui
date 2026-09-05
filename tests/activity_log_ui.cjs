const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

class Element {
  constructor() {
    this.children = [];
    this.listeners = new Map();
    this.scrollTop = 0;
    this.clientHeight = 400;
    this.offsetTop = 0;
    this.value = '';
    this.style = {};
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  get textContent() { return this.children.length ? this.children.map(child => child.textContent).join('') : this.text || ''; }
  set textContent(value) { this.text = value; this.children = []; }
  get scrollHeight() { return Math.max(400, this.textContent.split('\n').length * 20); }
  append(child) { child.parent = this; this.children.push(child); }
  appendChild(child) { this.append(child); }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  replaceChildren(...children) { this.text = ''; this.children = []; children.forEach(child => this.append(child)); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  addEventListener(event, handler) { this.listeners.set(event, handler); }
  removeEventListener(event) { this.listeners.delete(event); }
}

function fixture() {
  const elements = new Map();
  const timers = new Map();
  let timerId = 0;
  let source = Buffer.from('A first.stl\n');
  let hold;
  const requests = [];
  const statuses = [];
  const document = {
    hidden: false,
    addEventListener: () => {},
    getElementById: id => {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    createElement: () => new Element(),
    createTextNode: text => Object.assign(new Element(), { textContent: text }),
  };
  const context = vm.createContext({
    window: { BBUI: { components: { i18n: { t: key => key } } } },
    document, URLSearchParams, AbortController, TextEncoder, TextDecoder,
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id),
    requestAnimationFrame: fn => { queueMicrotask(fn); return 1; },
    cancelAnimationFrame: () => {},
    apiErrorMessage: data => data.error,
    fetch: async (url, options) => {
      const params = new URL(url, 'http://localhost').searchParams;
      requests.push({ params, signal: options.signal });
      if (hold) return new Promise(resolve => { hold.resolve = resolve; });
      let start = params.has('start') ? Number(params.get('start')) : Math.max(0, source.length - 65536);
      let end = Math.min(source.length, start + 65536);
      if (params.has('before')) { end = Number(params.get('before')); start = Math.max(0, end - 65536); }
      const data = { start, end, text: source.subarray(start, end).toString(), size: source.length, running: true, exit_code: null, run_id: 'run-original', file_id: '1:2' };
      if (params.has('status')) delete data.text;
      if (params.has('search')) {
        const query = params.get('search');
        const match = source.indexOf(query, start);
        Object.assign(data, { match: match < 0 ? null : match, next: match < 0 ? source.length : match + Buffer.byteLength(query), search_end: source.length, search_done: true });
        if (match >= 0) {
          data.start = Math.max(0, match - 1024);
          data.end = Math.min(source.length, data.start + 65536);
          data.text = source.subarray(data.start, data.end).toString();
        }
      }
      return { ok: true, json: async () => data };
    },
  });
  vm.runInContext(fs.readFileSync('ui/js/components/activity-log.js', 'utf8'), context);
  const output = document.getElementById('log-output');
  const viewer = context.window.BBUI.components.activityLog.create({ job: 'files', run: 'run-original', output, onStatus: data => statuses.push(data), onFollow: () => {} });
  return { viewer, output, elements, timers, requests, statuses, context,
    setSource: value => { source = Buffer.from(value); },
    hold: () => { hold = {}; return hold; },
  };
}

async function settle() { for (let i = 0; i < 12; i++) await Promise.resolve(); }

test('complete history is recoverable while the rendered window stays bounded', async () => {
  const f = fixture();
  await settle();
  const content = Array.from({ length: 100000 }, (_, i) => `A ${String(i).padStart(7, '0')}.stl\n`).join('');
  f.setSource(content);
  await f.viewer.load({ start: 0 }, 'replace-start', false);
  let cursor = 0;
  let collected = '';
  while (cursor < content.length) {
    const last = f.viewer.windows.at(-1);
    collected += last.node.textContent;
    cursor = last.end;
    assert.ok(f.output.children.length <= 3);
    assert.ok(Buffer.byteLength(f.output.textContent) <= 3 * 65536);
    if (cursor < content.length) await f.viewer.load({ start: cursor }, 'append', false);
  }
  assert.equal(collected, content);
  await f.viewer.load({ before: f.viewer.start }, 'prepend', false);
  assert.equal(f.output.textContent, content.slice(f.viewer.start, f.viewer.end));
  assert.equal(f.viewer.follow, false);
  f.viewer.close();
  assert.equal(f.timers.size, 0);
});

test('a late response cannot change a closed or switched log', async () => {
  const f = fixture();
  await settle();
  const held = f.hold();
  const pending = f.viewer.load({}, 'replace-end');
  f.viewer.close();
  f.output.textContent = 'Different job';
  held.resolve({ ok: true, json: async () => ({ text: 'stale', run_id: 'old', start: 0, end: 5 }) });
  await pending;
  assert.equal(f.output.textContent, 'Different job');
  assert.equal(f.requests.at(-1).signal.aborted, true);
  assert.equal(f.timers.size, 0);
});

test('search finds old entries and marks the requested occurrence safely', async () => {
  const f = fixture();
  await settle();
  f.setSource('A <script>old</script>\nA second.stl\n' + 'A newest.stl\n'.repeat(10000));
  await f.viewer.load({}, 'replace-end');
  assert.ok(!f.output.textContent.includes('<script>'));
  f.viewer.searchInput.value = '<script>old</script>';
  await f.viewer.search();
  assert.ok(f.output.textContent.startsWith('A <script>old</script>'));
  assert.equal(f.viewer.windows[0].node.children[1].textContent, '<script>old</script>');
  assert.equal(f.viewer.follow, false);
  await f.viewer.load({ status: 1 }, 'status');
  assert.ok(f.output.textContent.startsWith('A <script>old</script>'));
  f.viewer.close();
});

test('scrolling back aborts an incoming live block and preserves the viewport', async () => {
  const f = fixture();
  await settle();
  f.setSource('A file.stl\n'.repeat(10000));
  await f.viewer.load({}, 'replace-end');
  await settle();
  const held = f.hold();
  const before = f.output.textContent;
  const pending = f.viewer.load({ start: f.viewer.end }, 'append');
  f.output.scrollTop = 500;
  f.viewer.onScroll();
  assert.equal(f.viewer.follow, false);
  assert.equal(f.requests.at(-1).signal.aborted, true);
  held.resolve({ ok: true, json: async () => ({ text: 'stale', start: f.viewer.end, end: f.viewer.end + 5 }) });
  await pending;
  assert.equal(f.output.textContent, before);
  f.viewer.close();
});

test('normal runs keep SSE and scheduled runs select their effective mode', () => {
  const f = fixture();
  vm.runInContext(fs.readFileSync('ui/js/pages/jobs.js', 'utf8'), f.context);
  assert.equal(vm.runInContext("jobRuntimeState({run_id: 'new'}, {run_file_activity: true}).run_file_activity", f.context), false);
  assert.equal(vm.runInContext("jobRuntimeState({run_id: 'scheduled', file_activity: true}).run_file_activity", f.context), true);
  f.context.window.BBUI.jobsState.jobs = [{ key: 'normal', run_file_activity: false }];
  f.context.jobsLocationKey = () => 'local';
  f.context.EventSource = class {
    constructor(url) { this.url = url; }
    addEventListener() {}
  };
  vm.runInContext("openLogPanel('normal')", f.context);
  assert.equal(f.context.window.BBUI.jobsState.activeEventSource.url, '/api/jobs/log/stream?job=normal');
  assert.equal(f.context.window.BBUI.jobsState.activityLog, null);
  const oldStream = f.context.window.BBUI.jobsState.activeEventSource;
  f.context.window.BBUI.jobsState.activeEventSource = null;
  f.output.textContent = 'Current activity log';
  oldStream.onmessage({ data: 'late normal-job output' });
  assert.equal(f.output.textContent, 'Current activity log');
  f.viewer.close();
});
