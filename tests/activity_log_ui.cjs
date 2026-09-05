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
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  appendData(text) { this.textContent += text; }
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

test('small live updates retain a filled viewport and coalesce within the byte budget', async () => {
  const f = fixture();
  await settle();
  let content = 'A /mnt/user/3D/Modell-Größe.stl\n'.repeat(10000);
  f.setSource(content);
  await f.viewer.load({}, 'replace-end');
  const first = f.output.children[0];
  let evicted = false;
  for (let i = 0; i < 1200; i++) {
    const line = `INFO ${i} <script>literal</script> ${'Größe/'.repeat(24)}.stl\n`;
    content += line;
    f.setSource(content);
    await f.viewer.load({ start: f.viewer.end }, 'append');
    if (i < 4) assert.equal(f.output.children[0], first, 'a few lines must not evict a full block');
    if (f.output.children[0] !== first) evicted = true;
    assert.ok(f.output.scrollHeight >= f.output.clientHeight * 2, 'the viewport must not empty during slow output');
    assert.ok(f.output.children.length <= 3);
    assert.ok(Buffer.byteLength(f.output.textContent) <= 3 * (65536 + 4));
    assert.ok(f.output.textContent.endsWith(line));
    const source = Buffer.from(content);
    assert.equal(f.output.textContent, source.subarray(f.viewer.start, f.viewer.end).toString());
  }
  assert.ok(evicted, 'exercise trimming after the display budget fills');
  const nodes = [...f.output.children];
  const before = f.output.textContent;
  await f.viewer.load({ start: f.viewer.end }, 'append');
  assert.deepEqual(f.output.children, nodes, 'an empty poll must preserve existing nodes');
  assert.equal(f.output.textContent, before);
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

test('completed activity runs distinguish Borg warnings from failures', () => {
  const f = fixture();
  vm.runInContext(fs.readFileSync('ui/js/pages/jobs.js', 'utf8'), f.context);
  let onStatus;
  f.context.window.BBUI.components.activityLog.create = options => { onStatus = options.onStatus; return { close() {} }; };
  f.context.window.BBUI.jobsState.jobs = [{ key: 'files', run_file_activity: true }];
  f.context.jobsLocationKey = () => 'local';
  vm.runInContext("openLogPanel('files')", f.context);
  const badge = f.elements.get('log-status-badge');
  onStatus({ running: false, exit_code: 1, phase: 'completed' });
  assert.equal(badge.className, 'badge warning');
  assert.equal(badge.textContent, 'jobs.logWarning');
  onStatus({ running: false, exit_code: 1, phase: 'failed' });
  assert.equal(badge.className, 'badge error');
  onStatus({ running: false, exit_code: 2, phase: 'failed' });
  assert.equal(badge.className, 'badge error');
  onStatus({ running: false, exit_code: 2, phase: 'skipped' });
  assert.equal(badge.className, 'badge skipped');
  onStatus({ running: false, exit_code: 0, phase: 'completed' });
  assert.equal(badge.className, 'badge success');
  f.viewer.close();
});
