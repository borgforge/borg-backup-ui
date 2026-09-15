const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function setup(language = 'en') {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const elements = new Map();
  let focus;
  let now = 0;
  let nextTimer = 0;
  const timers = new Map();
  const documentListeners = {};
  function tick(ms) {
    const end = now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, item]) => item.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      now = due[1].at;
      timers.delete(due[0]);
      due[1].callback();
    }
    now = end;
  }
  function element(id = '', dialog = false) {
    const el = {
      id, dialog, className: '', attrs: {}, listeners: {}, children: [], value: '',
      isConnected: true, disabled: false,
      get textContent() { return this.value || this.children.map(child => child.textContent).join(''); },
      set textContent(value) { this.value = value; this.children = []; },
      replaceChildren(...children) { this.value = ''; this.children = children; },
      setAttribute(key, value) { this.attrs[key] = value; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      removeEventListener(name, callback) { if (this.listeners[name] === callback) delete this.listeners[name]; },
      matches() { return !!this.hovered; },
      contains(other) { return !!other && (other === this || this.children.includes(other)); },
      closest() { return dialog ? {} : null; },
      getClientRects() { return [{}]; },
      focus() { focus = this; },
    };
    if (id) elements.set(id, el);
    return el;
  }
  const context = vm.createContext({window: {BBUI: {components: {i18n: {t: key => key.split('.').reduce((obj, part) => obj[part], labels)}}}},
    performance: {now: () => now},
    document: {
      hidden: false,
      addEventListener(name, callback) { documentListeners[name] = callback; },
      removeEventListener(name, callback) { if (documentListeners[name] === callback) delete documentListeners[name]; },
      getElementById: id => elements.get(id),
      createElement: () => element(),
      get activeElement() { return focus; },
      querySelectorAll: () => [...elements.values()].filter(el => el.className.split(' ').includes('page-feedback')),
    },
    setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {at: now + delay, callback}); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  vm.runInContext(fs.readFileSync('ui/js/utils/dom.js', 'utf8'), context);
  return {context, element, labels, focused: () => focus, tick, timers, documentListeners};
}

for (const language of ['de', 'en']) {
  test(`${language}: all severities share dismissible feedback, replacing previous messages`, () => {
    const {context, element, labels} = setup(language);
    const first = element('page-message');
    const second = element('subpage-message');
    for (const severity of ['info', 'success', 'warning', 'error']) {
      context.showMsg(first.id, severity, '<script>not executable</script>\n' + 'long line '.repeat(300));
      assert.equal(first.attrs.role, severity === 'error' ? 'alert' : 'status');
      assert.equal(first.children[0].textContent, labels.common.feedback[severity]);
      assert.equal(first.children[1].attrs['aria-label'], labels.common.feedback.dismiss);
      assert.match(first.children[2].textContent, /^<script>not executable<\/script>\n/);
      context.showMsg(second.id, severity, 'Next action result');
      assert.match(first.className, /hidden/);
      assert.match(second.className, /page-feedback/);
      context.hideEl(second.id);
      assert.equal(second.textContent, '');
    }
  });
}

test('dismissal returns keyboard focus and empty feedback clears the panel', () => {
  const {context, element, focused} = setup();
  const button = element('trigger'); button.focus();
  const message = element('page-message');
  context.showMsg(message.id, 'warn', 'Warning');
  assert.match(message.className, /warning-state/);
  const close = message.children[1]; close.focus(); close.listeners.click();
  assert.equal(focused(), button);
  assert.match(message.className, /hidden/);
  context.showMsg(message.id, 'error', 'Error');
  context.showMsg(message.id, 'error', '');
  assert.match(message.className, /hidden/);
});

test('navigation clearing does not remove contextual empty states or dialog validation', () => {
  const {context, element} = setup();
  const page = element('page-message');
  const empty = element('empty'); empty.className = 'status-message empty-state'; empty.textContent = 'No jobs';
  const dialog = element('dialog-message', true);
  context.showMsg(page.id, 'error', 'Page error');
  context.showMsg(dialog.id, 'error', 'Invalid form');
  assert.doesNotMatch(dialog.className, /page-feedback/);
  assert.equal(dialog.textContent, 'Invalid form');
  context.clearPageFeedback();
  assert.match(page.className, /hidden/);
  assert.equal(empty.textContent, 'No jobs');
  assert.equal(dialog.textContent, 'Invalid form');
});


test('late feedback from a hidden page or panel cannot dismiss the current error', () => {
  const {context, element} = setup();
  const current = element('current-message');
  const previous = element('previous-message');
  previous.parentElement = {getClientRects: () => []};
  context.showMsg(current.id, 'error', 'Current error');
  context.showMsg(previous.id, 'success', 'Previous page finished');
  assert.match(current.className, /page-feedback/);
  assert.equal(current.children[2].textContent, 'Current error');
  assert.doesNotMatch(previous.className, /page-feedback/);
});


test('short success/info close after 5 seconds and warnings after 12; errors stay', () => {
  const {context, element, tick, timers} = setup();
  const message = element('message');
  for (const [severity, duration] of [['success', 5000], ['info', 5000], ['warning', 12000]]) {
    context.showMsg(message.id, severity, 'Result');
    tick(duration - 1); assert.match(message.className, /page-feedback/);
    tick(1); assert.match(message.className, /hidden/);
    assert.equal(timers.size, 0);
  }
  context.showMsg(message.id, 'error', 'Error');
  tick(60000);
  assert.match(message.className, /page-feedback/);
  assert.equal(timers.size, 0);
});

test('long texts receive more reading time, capped at 30 seconds', () => {
  const {context, element, tick} = setup();
  const message = element('message');
  for (const [length, duration] of [[300, 15000], [10000, 30000]]) {
    context.showMsg(message.id, 'warning', 'x'.repeat(length));
    tick(duration - 1); assert.match(message.className, /page-feedback/);
    tick(1); assert.match(message.className, /hidden/);
  }
});

test('hover and keyboard focus pause remaining time without restarting it', () => {
  const {context, element, tick, timers} = setup();
  const message = element('message');
  context.showMsg(message.id, 'info', 'Result');
  tick(2000);
  message.listeners.mouseenter();
  tick(10000); assert.match(message.className, /page-feedback/);
  message.listeners.focusin();
  message.listeners.mouseleave();
  tick(10000); assert.equal(timers.size, 0);
  message.listeners.focusout({relatedTarget: message.children[1]});
  tick(10000); assert.equal(timers.size, 0);
  message.listeners.focusout({relatedTarget: null});
  tick(2999); assert.match(message.className, /page-feedback/);
  tick(1); assert.match(message.className, /hidden/);
});

test('a hidden browser tab pauses dismissal, including feedback first shown while hidden', () => {
  const {context, element, tick, documentListeners} = setup();
  const message = element('message');
  context.showMsg(message.id, 'warning', 'Result');
  tick(2000);
  context.document.hidden = true; documentListeners.visibilitychange();
  tick(60000); assert.match(message.className, /page-feedback/);
  context.document.hidden = false; documentListeners.visibilitychange();
  tick(9999); assert.match(message.className, /page-feedback/);
  tick(1); assert.match(message.className, /hidden/);
  context.document.hidden = true;
  context.showMsg(message.id, 'success', 'Result');
  tick(60000); assert.match(message.className, /page-feedback/);
  context.document.hidden = false; documentListeners.visibilitychange();
  tick(5000); assert.match(message.className, /hidden/);
});

test('replacement, dismissal and navigation remove old timers and listeners', () => {
  const {context, element, tick, timers, documentListeners} = setup();
  const message = element('message');
  context.showMsg(message.id, 'success', 'Old result');
  tick(4000);
  context.showMsg(message.id, 'warning', 'New result');
  tick(1000); assert.match(message.className, /page-feedback/);
  assert.equal(timers.size, 1);
  context.hideEl(message.id);
  assert.equal(timers.size, 0);
  assert.deepEqual(Object.keys(message.listeners), []);
  assert.deepEqual(Object.keys(documentListeners), []);
  context.showMsg(message.id, 'info', 'Result');
  const replacement = element('message'); // A settings re-render replaces the original DOM element.
  context.clearPageFeedback();
  assert.equal(timers.size, 0);
  assert.deepEqual(Object.keys(documentListeners), []);
  context.showMsg(replacement.id, 'error', 'New error');
  tick(60000); assert.match(replacement.className, /page-feedback/);
});

test('dialog feedback never dismisses automatically', () => {
  const {context, element, tick, timers} = setup();
  const dialog = element('dialog-message', true);
  for (const severity of ['info', 'success', 'warning', 'error']) {
    context.showMsg(dialog.id, severity, 'Form feedback');
    tick(60000);
    assert.equal(dialog.textContent, 'Form feedback');
    assert.equal(timers.size, 0);
  }
});
