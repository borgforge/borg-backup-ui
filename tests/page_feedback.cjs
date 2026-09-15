const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function setup(language = 'en') {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  const elements = new Map();
  let focus;
  function element(id = '', dialog = false) {
    const el = {
      id, dialog, className: '', attrs: {}, listeners: {}, children: [], value: '',
      isConnected: true, disabled: false,
      get textContent() { return this.value || this.children.map(child => child.textContent).join(''); },
      set textContent(value) { this.value = value; this.children = []; },
      replaceChildren(...children) { this.value = ''; this.children = children; },
      setAttribute(key, value) { this.attrs[key] = value; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      closest() { return dialog ? {} : null; },
      getClientRects() { return [{}]; },
      focus() { focus = this; },
    };
    if (id) elements.set(id, el);
    return el;
  }
  const context = vm.createContext({window: {BBUI: {components: {i18n: {t: key => key.split('.').reduce((obj, part) => obj[part], labels)}}}},
    document: {
      getElementById: id => elements.get(id),
      createElement: () => element(),
      get activeElement() { return focus; },
      querySelectorAll: () => [...elements.values()].filter(el => el.className.split(' ').includes('page-feedback')),
    },
    setTimeout: () => { throw new Error('Feedback must not disappear on a timer'); },
  });
  vm.runInContext(fs.readFileSync('ui/js/utils/dom.js', 'utf8'), context);
  return {context, element, labels, focused: () => focus};
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
