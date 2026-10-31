'use strict';
// Per-job Docker start order in the wizard: default list, moves, scope and payload without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function translator(language) {
  const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
  return (key, params = {}) => {
    const label = key.split('.').reduce((value, part) => value?.[part], labels);
    return typeof label === 'string' ? label.replace(/\{(\w+)\}/g, (all, name) => params[name] ?? all) : key;
  };
}

/** Minimal DOM: every ID resolves to a stable form-like element. */
function fakeDocument() {
  const nodes = new Map();
  const classList = () => ({add() {}, remove() {}, toggle() {}, contains: () => false});
  const node = id => {
    if (!nodes.has(id)) {
      nodes.set(id, {id, value: '', checked: false, innerHTML: '', textContent: '', hidden: false, disabled: false,
        dataset: {}, style: {}, classList: classList(), addEventListener() {}, closest: () => null,
        querySelectorAll: () => [], querySelector: () => null, setAttribute() {}, removeAttribute() {}});
    }
    return nodes.get(id);
  };
  return {node, document: {getElementById: node, querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, body: {classList: classList()}}};
}

// VM-realm arrays have foreign prototypes; compare plain copies.
const plain = value => JSON.parse(JSON.stringify(value));

for (const language of ['de', 'en']) {
  const t = translator(language);
  const dom = fakeDocument();
  const wizard = vm.createContext({
    window: {BBUI: {components: {i18n: {t, getLanguage: () => language}}}, addEventListener() {}},
    document: dom.document,
    escHtml: value => String(value ?? '').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), wizard);
  const state = wizard.window.BBUI.wizardState;
  state.dockerContainers = [
    {name: 'plex', priority: 3}, {name: 'mariadb', priority: 1}, {name: 'nextcloud', priority: 2}, {name: 'whoami'},
  ];
  dom.node('wiz-use-docker').checked = true;
  dom.node('wiz-docker-mode').value = 'all';

  // Untouched: label priority, then name; the job stores no order.
  assert.deepEqual(plain(wizard._wizardDockerOrderNames()), ['mariadb', 'nextcloud', 'plex', 'whoami']);
  assert.deepEqual(plain(wizard._wizardCollectParams().docker_control.order), []);
  wizard._wizardRenderDockerOrder();
  const list = dom.node('wiz-docker-order-list').innerHTML;
  assert.equal((list.match(/class="wizard-order-row"/g) || []).length, 4);
  assert.match(list, /draggable="true"/);
  assert.match(list, new RegExp(`aria-label="${t('wizard.dockerOrderUp', {name: 'mariadb'})}" disabled`));
  assert.equal(dom.node('wiz-docker-order-state').textContent, t('wizard.dockerOrderDefault'));

  // Moving creates a custom order for the whole scope.
  wizard.wizardMoveDockerOrder(3, 0);
  assert.deepEqual(plain(wizard._wizardCollectParams().docker_control.order), ['whoami', 'mariadb', 'nextcloud', 'plex']);
  assert.equal(dom.node('wiz-docker-order-state').textContent, t('wizard.dockerOrderCustom'));
  wizard.wizardMoveDockerOrder(1, 2);
  assert.deepEqual(plain(state.dockerOrder), ['whoami', 'nextcloud', 'mariadb', 'plex']);
  wizard.wizardMoveDockerOrder(0, -1);
  assert.deepEqual(plain(state.dockerOrder), ['whoami', 'nextcloud', 'mariadb', 'plex'], 'Out-of-range moves are ignored');

  // The scope filters the saved order; new scope members follow by priority.
  dom.node('wiz-docker-mode').value = 'selected';
  state.selectedDockerContainers = ['plex', 'mariadb'];
  assert.deepEqual(plain(wizard._wizardDockerOrderNames()), ['mariadb', 'plex']);
  dom.node('wiz-docker-mode').value = 'except_selected';
  state.selectedDockerContainers = ['nextcloud'];
  assert.deepEqual(plain(wizard._wizardDockerOrderNames()), ['whoami', 'mariadb', 'plex']);

  // Loading a saved job restores its order; a disabled control stores none.
  wizard._wizardSetRuntimeControl('docker', {mode: 'all', order: ['plex', 'mariadb']});
  assert.deepEqual(plain(wizard._wizardDockerOrderNames()), ['plex', 'mariadb', 'nextcloud', 'whoami']);
  assert.deepEqual(plain(wizard._wizardCollectParams().docker_control.order), ['plex', 'mariadb', 'nextcloud', 'whoami']);
  dom.node('wiz-use-docker').checked = false;
  assert.deepEqual(plain(wizard._wizardCollectParams().docker_control.order), []);

  for (const key of ['wizard.previewDockerOrder', 'wizard.flowSteps.dockerStopOrder', 'wizard.flowSteps.dockerStartOrdered',
    'wizard.dockerOrderReset', 'wizard.dockerOrderEmpty', 'wizard.dockerOrderHint', 'wizard.dockerOrderNote']) {
    assert.notEqual(t(key), key, `${language}: ${key} is translated`);
  }
}
console.log('Docker start order: default list, moves, scope filtering and payload passed.');
