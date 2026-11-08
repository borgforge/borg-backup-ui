'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness(lang = 'de') {
  const dict = JSON.parse(fs.readFileSync(`ui/i18n/${lang}.json`));
  const elements = new Map();
  for (const id of ['resource-activity', 'resource-active', 'resource-values', 'resource-live', 'resource-tests', 'resource-history', 'resource-history-toggle']) {
    elements.set(id, {innerHTML: '', textContent: '', hidden: false, attrs: {}, listeners: {},
      classList: {toggle() {}}, setAttribute(k, v) {this.attrs[k] = v;}, addEventListener(k, v) {this.listeners[k] = v;}});
  }
  const timers = new Map(); let timerId = 0;
  const listeners = {}; const requests = [];
  let next = () => Promise.resolve({ok: true, json: async () => sample()});
  const window = {BBUI: {components: {i18n: {
    t: (key, params = {}) => key.split('.').reduce((v, k) => v?.[k], dict).replace(/\{(\w+)\}/g, (_, k) => params[k] ?? ''),
    getLanguage: () => lang}}, core: {state: {currentPage: 'dashboard', data: {backups: [{key: 'appdata', name: '<img onerror="oops">'}]}}}},
    addEventListener: (key, callback) => {listeners[key] = callback;}};
  const document = {hidden: false, getElementById: id => elements.get(id), addEventListener: (key, callback) => {listeners[key] = callback;}};
  let graphs = [];
  elements.get('resource-history').querySelectorAll = () => {
    graphs = [...elements.get('resource-history').innerHTML.matchAll(/data-resource-plot-key="([^"]+)"/g)].map(match => {
      const marker = {style: {}, hidden: true};
      const readout = {textContent: ''};
      const canvas = {listeners: {}, attrs: {}, dataset: {resourceFocusKey: match[1]},
        getBoundingClientRect: () => ({left: 0, width: 400}),
        addEventListener(key, fn) {this.listeners[key] = fn;},
        setAttribute(key, value) {this.attrs[key] = value;},
        focus() {document.activeElement = this;}};
      return {marker, readout, canvas, querySelector: selector => ({'.resource-crosshair':marker, '.resource-readout':readout, '.resource-plot-canvas':canvas})[selector]};
    });
    return graphs;
  };
  const context = vm.createContext({window, document, Intl, AbortController,
    escHtml: s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c])),
    setTimeout: (fn, delay) => {timers.set(++timerId, {fn, delay}); return timerId;},
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => {requests.push({url, options}); return next();}});
  vm.runInContext(fs.readFileSync('ui/js/utils/format.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('ui/js/components/resource-monitor.js', 'utf8'), context);
  return {elements, timers, window, document, listeners, requests, get graphs() {return graphs;}, monitor: window.BBUI.resourceMonitor,
    setResponse: callback => {next = callback;}, tick: delay => {const [id, task] = [...timers].find(([, t]) => t.delay === delay); timers.delete(id); task.fn();}};
}
function sample(active = true) {
  const group = {id: 'one', job_key: 'appdata', cpu_percent: 12.5, memory_bytes: 1.3 * 1024**3, memory_limit_bytes: 2 * 1024**3};
  return {available: true, stale: false, host: {cpu_percent: 38, memory_available_bytes: 5.7 * 1024**3, memory_total_bytes: 32 * 1024**3},
    runs_available: true, runs: active ? [{job_key: 'appdata', operation: 'restore_test'}] : [],
    protected_tests: active ? [group] : [], configured_reserve_bytes: 1024**3,
    history: [{timestamp: 1000, host: {cpu_percent: null, memory_available_bytes: null}, protected_tests: []},
      {timestamp: 1005, host: {cpu_percent: 38, memory_available_bytes: 5.7 * 1024**3}, protected_tests: [group]}]};
}

for (const lang of ['de', 'en']) {
  test(`${lang}: render active values safely, preserve toggle and switch idle cadence`, async () => {
    const h = harness(lang); h.monitor.start(); h.monitor.start(); await flush();
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].url, '/api/system-resources');
    assert.match(h.elements.get('resource-values').innerHTML, /38 %/);
    assert.match(h.elements.get('resource-values').innerHTML, /resource-ram-capacity/);
    assert.equal(h.elements.get('resource-history').hidden, true);
    assert.equal(h.elements.get('resource-activity').hidden, false);
    assert.match(h.elements.get('resource-active').textContent, /1/);
    assert.doesNotMatch(h.elements.get('resource-tests').innerHTML, /<img/);
    assert.match(h.elements.get('resource-tests').innerHTML, /&lt;img/);
    assert.match(h.elements.get('resource-tests').innerHTML, /<progress/);
    const toggle = h.elements.get('resource-history-toggle'); toggle.listeners.click();
    assert.equal(toggle.attrs['aria-expanded'], 'true');
    assert.match(h.elements.get('resource-history').innerHTML, /resource-chart-large/);
    assert.match(h.elements.get('resource-history').innerHTML, /75 %/);
    assert.match(h.elements.get('resource-history').innerHTML, /24 GiB/);
    assert.doesNotMatch(h.elements.get('resource-history').innerHTML, /NaN|undefined/);
    h.setResponse(async () => ({ok: true, json: async () => ({...sample(), runs:[{job_key:'appdata',operation:'backup'}], protected_tests:[]})}));
    h.tick(2000); await flush();
    assert.equal(h.elements.get('resource-activity').hidden, true);
    assert.match(h.elements.get('resource-active').textContent, /1/);
    assert.ok([...h.timers.values()].some(t => t.delay === 2000));
    h.setResponse(async () => ({ok: true, json: async () => sample(false)}));
    h.tick(2000); await flush();
    assert.equal(h.elements.get('resource-tests').hidden, true);
    assert.equal(h.elements.get('resource-activity').hidden, true);
    assert.equal(toggle.attrs['aria-expanded'], 'true');
    assert.ok([...h.timers.values()].some(t => t.delay === 10000));
    h.monitor.stop(); assert.equal(h.timers.size, 0);
  });
}

test('sample inspection distinguishes gaps from zero and preserves keyboard selection across refresh', async () => {
  const h = harness(); h.monitor.start(); await flush();
  h.elements.get('resource-history-toggle').listeners.click();
  const first = h.graphs[0];
  assert.match(first.readout.textContent, /38 %/);
  first.canvas.listeners.pointermove({clientX: 0});
  assert.match(first.readout.textContent, /Keine Messung/);
  assert.equal(first.marker.hidden, true);
  first.canvas.listeners.pointermove({clientX: 400});
  assert.match(first.readout.textContent, /38 %/);
  assert.equal(first.marker.hidden, false);
  first.canvas.focus();
  first.canvas.listeners.keydown({key: 'Home', preventDefault() {}});
  assert.match(first.readout.textContent, /Keine Messung/);
  h.tick(2000); await flush();
  assert.notEqual(h.graphs[0].canvas, first.canvas);
  assert.equal(h.document.activeElement, h.graphs[0].canvas);
  assert.match(h.graphs[0].readout.textContent, /Keine Messung/);
  h.graphs[0].canvas.listeners.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.match(h.graphs[0].readout.textContent, /38 %/);
  h.setResponse(async () => ({ok:true, json:async () => {
    const data = sample(); data.host.cpu_percent = 0; data.history[1].host.cpu_percent = 0; return data;
  }}));
  h.tick(2000); await flush();
  assert.match(h.graphs[0].readout.textContent, /· 0 %/);
  h.monitor.stop();
});

test('failed and stale samples do not display old numbers as live', async () => {
  const h = harness(); h.monitor.start(); await flush();
  h.setResponse(async () => {throw new Error('offline');}); h.tick(2000); await flush();
  assert.doesNotMatch(h.elements.get('resource-values').innerHTML, /38 %/);
  assert.match(h.elements.get('resource-values').innerHTML, /—/);
  assert.match(h.elements.get('resource-live').textContent, /nicht verfügbar/);
  h.setResponse(async () => ({ok: true, json: async () => ({...sample(), stale: true})}));
  h.tick(10000); await flush();
  assert.doesNotMatch(h.elements.get('resource-values').innerHTML, /38 %/);
  h.monitor.stop();
});

test('visibility/navigation abort in-flight requests and discard obsolete responses', async () => {
  const h = harness(); let resolve;
  h.setResponse(() => new Promise(done => {resolve = done;}));
  h.monitor.start();
  h.document.hidden = true; h.listeners.visibilitychange();
  assert.equal(h.requests[0].options.signal.aborted, true);
  resolve({ok: true, json: async () => sample()}); await flush();
  assert.doesNotMatch(h.elements.get('resource-values').innerHTML, /38 %/);
  assert.equal(h.timers.size, 0);
  h.setResponse(async () => ({ok: true, json: async () => sample()}));
  h.document.hidden = false; h.listeners.visibilitychange(); await flush();
  assert.equal(h.requests.length, 2);
  h.window.BBUI.core.state.currentPage = 'jobs'; h.monitor.stop();
  h.monitor.start(); await flush(); assert.equal(h.requests.length, 2);
  assert.equal(h.timers.size, 0);
});

for (const lang of ['de', 'en']) test(`${lang}: queue summary survives missing cgroup measurements and transitions`, async () => {
  const h = harness(lang);
  const data = sample();
  data.runs = ['running', 'waiting', 'waiting', 'waiting'].map((activity_state, i) => ({job_key: `test-${i}`, operation: 'restore_test', activity_state}));
  data.protected_tests = [];
  h.setResponse(async () => ({ok: true, json: async () => data}));
  h.monitor.start(); await flush();
  assert.equal(h.elements.get('resource-active').textContent, lang === 'de' ? '1 läuft · 3 warten' : '1 running · 3 waiting');
  assert.equal(h.elements.get('resource-tests').hidden, true);
  data.runs.shift(); data.runs[0].activity_state = 'running';
  h.tick(2000); await flush();
  assert.equal(h.elements.get('resource-active').textContent, lang === 'de' ? '1 läuft · 2 warten' : '1 running · 2 waiting');
  delete data.runs[0].activity_state;
  h.tick(2000); await flush();
  assert.equal(h.elements.get('resource-active').textContent, lang === 'de' ? '2 warten · 1 Status unbekannt' : '2 waiting · 1 status unknown');
  h.monitor.stop();
});
