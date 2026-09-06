'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const normal = { mode: 'normal', blocking: false, failures: [] };
const maintenance = { mode: 'maintenance', blocking: true, failures: [], failed_migrations: ['immutable_job_id_v1'] };
const required = { global_data_dir_set: false, ready: false, global_data_dir_suggestion: '/mnt/user/borg-backup-ui', setup: {} };
const migration = { maintenance_mode: true, startup_state: maintenance };

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function element(id, initialClass = '') {
  let classes = new Set(initialClass.split(/\s+/).filter(Boolean));
  return {
    id, innerHTML: '', textContent: '', dataset: {}, style: {}, value: '', disabled: false,
    get className() { return [...classes].join(' '); },
    set className(value) { classes = new Set(value.split(/\s+/).filter(Boolean)); },
    classList: {
      add(...values) { values.forEach(value => classes.add(value)); },
      remove(...values) { values.forEach(value => classes.delete(value)); },
      contains(value) { return classes.has(value); },
      toggle(value, force) {
        const enabled = force === undefined ? !classes.has(value) : force;
        if (enabled) classes.add(value); else classes.delete(value);
        return enabled;
      },
    },
    addEventListener() {}, setAttribute() {}, querySelector() { return null; },
  };
}

function harness({ setup = required, startup = normal, banner = true } = {}) {
  const elements = new Map();
  for (const id of ['setup-wizard-modal', 'setup-wizard-body', 'setup-wizard-save-dir-btn',
    'setup-wizard-skip-btn', 'setup-wizard-finish-btn', 'setup-wizard-close-btn',
    'dashboard-setup-actions', 'dashboard-data-dir-warning', 'dashboard-system-warning',
    'jobs-data-dir-warning', 'settings-setup-warning', 'mobile-backdrop', 'page-settings',
    'page-hilfe', 'page-dashboard', 'rt-run-btn', 'setup-wizard-data-dir-input']) {
    elements.set(id, element(id, 'hidden'));
  }
  if (banner) elements.set('startup-maintenance-banner', element('startup-maintenance-banner', 'hidden'));
  const sidebar = element('sidebar');
  const calls = [], events = new Map(), timers = [], externalFlows = [];
  let setupResponse = setup, discardPrompts = 0, dashboardRefreshes = 0;
  const document = {
    getElementById: id => elements.get(id) || null,
    querySelector: selector => selector === '.sidebar' ? sidebar : null,
    querySelectorAll: () => [], addEventListener() {}, body: null,
  };
  const window = {
    BBUI: { components: { i18n: { t: key => key }, modal: {
      formSnapshot: () => 'unchanged form',
      confirmDiscardIfDirty: dirty => { if (dirty) discardPrompts++; return !dirty; },
    } } },
    addEventListener: (name, callback) => events.set(name, callback),
    setTimeout: callback => { timers.push(callback); return timers.length; },
  };
  const context = vm.createContext({ window, document, console,
    fetch: async (url, options = {}) => {
      calls.push({ url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
      let data;
      if (url === '/api/setup-status') data = await setupResponse;
      else if (url === '/api/version') data = { version: 'integration-test', startup_state: await startup };
      else if (url === '/api/auth/status') data = { current_role: 'admin' };
      else if (url === '/api/settings' && options.method === 'PUT') {
        setupResponse = { ...required, global_data_dir_set: true, ready: true,
          global_data_dir: JSON.parse(options.body).updates.GLOBAL_DATA_DIR,
          setup: { show_optional_wizard: true, optional_incomplete: true, missing_optional: ['storage', 'repository', 'job'] } };
        data = { saved: true };
      }
      else throw new Error(`Unexpected request: ${options.method || 'GET'} ${url}`);
      return { ok: true, status: 200, json: async () => data };
    },
    escHtml: value => String(value ?? ''), escAttr: value => String(value ?? ''),
    apiMessage: () => '', showMsg() {}, hideEl() {}, _applyVersionInfo() {}, updateClock() {},
    refreshStatus: () => { dashboardRefreshes++; }, scheduleAutoRefresh() {}, runRestoreTestNow() {},
    activateSettingsTab: tab => externalFlows.push(`settings:${tab}`),
    openRepositoryManager: () => externalFlows.push('repository'), openWizard: () => externalFlows.push('job'),
    setInterval: () => 1, setTimeout: window.setTimeout,
  });
  for (const file of ['ui/js/core/app-core.js', 'ui/js/pages/setup-wizard.js', 'ui/js/components/app-bindings.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, { filename: file });
  }
  const core = window.BBUI.core, wizard = window.BBUI.setupWizard;
  return {
    core, wizard, calls, timers, externalFlows,
    get discardPrompts() { return discardPrompts; },
    get dashboardRefreshes() { return dashboardRefreshes; },
    element: id => elements.get(id),
    hidden: () => elements.get('setup-wizard-modal').classList.contains('hidden'),
    setSetup: value => { setupResponse = value; core.invalidateSetupStatusCache(); },
    start: () => window.BBUI.components.appBindings.init(),
    enterMaintenance: () => core.renderStartupMaintenanceBanner(maintenance),
    click: (action, extra = {}) => wizard.handleAction({ preventDefault() {},
      target: { closest: () => ({ dataset: { setupWizardAction: action, ...extra } }) } }),
  };
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const noWrites = app => assert.ok(app.calls.every(call => call.method === 'GET'), 'setup must not write while migration owns maintenance');

const scenarios = {
  async maintenance_response() {
    const app = harness({ setup: migration });
    await app.core.updateDataDirWarning();
    assert.equal(app.core.isStartupMaintenanceMode(), true, 'setup response establishes maintenance before version arrives');
    assert.equal(app.core.isSetupRequired(), false, 'missing setup fields are not an unconfigured data directory');
    assert.equal(app.core.isGlobalDataDirReady(), false);
    app.wizard.open(migration);
    await app.wizard.maybeOpen(true);
    app.wizard.renderDashboardPanel(migration);
    assert.equal(app.hidden(), true);
    assert.ok(app.element('dashboard-setup-actions').classList.contains('hidden'));
    for (const id of ['dashboard-data-dir-warning', 'dashboard-system-warning', 'jobs-data-dir-warning', 'settings-setup-warning']) {
      assert.ok(app.element(id).classList.contains('hidden'), `${id} does not request setup during migration`);
    }
    noWrites(app);
  },
  async status_markers() {
    for (const status of [{ maintenance_mode: true }, { startup_state: maintenance }]) {
      const app = harness();
      app.wizard.open(status);
      assert.equal(app.hidden(), true, 'either maintenance marker prevents a mandatory setup modal');
      app.wizard.renderDashboardPanel(status);
      assert.ok(app.element('dashboard-setup-actions').classList.contains('hidden'));
      noWrites(app);
    }
  },
  async stale_setup_response() {
    const pending = deferred(), app = harness({ setup: pending.promise });
    const warning = app.core.updateDataDirWarning();
    const opening = app.wizard.maybeOpen(true);
    assert.ok(app.calls.some(call => call.url === '/api/setup-status'));
    app.enterMaintenance();
    pending.resolve(required);
    await Promise.all([warning, opening]);
    assert.equal(app.hidden(), true, 'an older missing-directory response cannot reopen the setup modal');
    assert.equal(app.core.isSetupRequired(), false, 'a stale response cannot restore the setup navigation lock');
    assert.equal(app.core.isStartupMaintenanceMode(), true);
    noWrites(app);
  },
  async existing_mandatory_modal() {
    for (const banner of [true, false]) {
      const app = harness({ banner });
      app.wizard.open(required);
      assert.equal(app.hidden(), false);
      assert.equal(app.wizard.close(), false, 'first-run data directory remains mandatory in normal operation');
      app.enterMaintenance();
      assert.equal(app.core.isStartupMaintenanceMode(), true, 'maintenance state applies even without a banner element');
      assert.equal(app.hidden(), true, 'maintenance removes an already-open mandatory overlay');
      assert.equal(app.discardPrompts, 0, 'entering maintenance needs no dismiss or discard acknowledgement');
      app.wizard.open(required);
      assert.equal(app.hidden(), true, 'a stale explicit open cannot bring back the overlay');
      noWrites(app);
    }
  },
  async startup_response_order() {
    for (const first of ['setup', 'version']) {
      const setup = deferred(), version = deferred();
      const app = harness({ setup: setup.promise, startup: version.promise });
      app.start();
      if (first === 'setup') setup.resolve(required); else version.resolve(maintenance);
      await settle();
      if (first === 'setup') version.resolve(maintenance); else setup.resolve(required);
      await settle();
      assert.equal(app.hidden(), true, `${first} response first still gives migration precedence`);
      assert.equal(app.core.isSetupRequired(), false);
      assert.equal(app.core.getCurrentPage(), 'settings');
      assert.equal(app.dashboardRefreshes, 0, 'startup does not begin normal dashboard work in maintenance');
      noWrites(app);
    }
  },
  async pending_return_and_actions() {
    const app = harness({ setup: { ...required, global_data_dir_set: true, ready: true } });
    app.wizard.open({ ...required, global_data_dir_set: true, ready: true });
    await app.click('open-settings-tab', { settingsTabTarget: 'local' });
    assert.ok(app.wizard.returnContext, 'external setup flow arms return');
    app.enterMaintenance();
    assert.equal(app.wizard.returnContext, null, 'maintenance cancels automatic setup return');
    assert.equal(await app.wizard.resumeAfterExternalSave('storage'), false);
    for (const action of ['open', 'save-data-dir', 'dismiss-optional', 'open-repository-manager', 'open-job-wizard']) {
      await app.click(action);
    }
    for (const timer of app.timers) timer();
    await settle();
    assert.equal(app.hidden(), true);
    assert.equal(app.core.getCurrentPage(), 'settings');
    assert.deepEqual(app.externalFlows, [], 'delayed setup actions cannot open a different flow over migration');
    noWrites(app);
  },
  async normal_initial_setup() {
    const app = harness();
    app.start();
    await settle();
    assert.equal(app.core.isStartupMaintenanceMode(), false);
    assert.equal(app.core.isSetupRequired(), true);
    assert.equal(app.hidden(), false, 'normal first run still opens setup automatically');
    assert.equal(app.core.getCurrentPage(), 'settings');
    assert.ok(app.element('setup-wizard-body').innerHTML.includes('setup-wizard-data-dir-input'));
    assert.equal(app.element('setup-wizard-save-dir-btn').classList.contains('hidden'), false);
    assert.equal(app.element('setup-wizard-close-btn').classList.contains('hidden'), true);
    assert.equal(app.wizard.close(), false);
    noWrites(app);
  },
  async normal_optional_setup() {
    const app = harness({ setup: { ...required, global_data_dir_set: true, ready: true,
      setup: { show_optional_wizard: true, optional_incomplete: true, missing_optional: ['repository', 'job'] } } });
    app.start();
    await settle();
    assert.equal(app.core.isSetupRequired(), false);
    assert.equal(app.hidden(), false, 'normal optional setup still opens after the required step');
    assert.ok(app.element('setup-wizard-body').innerHTML.includes('open-repository-manager'));
    assert.equal(app.element('setup-wizard-close-btn').classList.contains('hidden'), false);
    assert.equal(app.element('setup-wizard-save-dir-btn').classList.contains('hidden'), true);
    assert.equal(app.wizard.close(), true);
    assert.equal(app.hidden(), true);
    noWrites(app);
  },
  async normal_save_data_dir() {
    const app = harness();
    app.start();
    await settle();
    app.element('setup-wizard-data-dir-input').value = '/mnt/user/fresh-install';
    await app.click('save-data-dir');
    await settle();
    assert.deepEqual(app.calls.filter(call => call.method !== 'GET'), [{ url: '/api/settings', method: 'PUT',
      body: { updates: { GLOBAL_DATA_DIR: '/mnt/user/fresh-install' }, profile_updates: {} } }]);
    assert.equal(app.core.isSetupRequired(), false);
    assert.equal(app.hidden(), false);
    assert.equal(app.element('setup-wizard-save-dir-btn').classList.contains('hidden'), true);
    assert.ok(app.element('setup-wizard-body').innerHTML.includes('open-repository-manager'), 'successful directory save advances to optional setup');
  },
};

const selected = process.argv[2];
assert.ok(Object.hasOwn(scenarios, selected), `Unknown scenario: ${selected}`);
scenarios[selected]().then(() => console.log(`${selected}: passed`)).catch(error => { console.error(error); process.exitCode = 1; });
