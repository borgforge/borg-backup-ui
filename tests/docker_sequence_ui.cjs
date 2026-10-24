'use strict';
// Sequential Docker backups: wizard payload/preview text and job-card progress without a browser.
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

for (const language of ['de', 'en']) {
  const t = translator(language);

  const dom = fakeDocument();
  const wizard = vm.createContext({
    window: {BBUI: {components: {i18n: {t, getLanguage: () => language}}}, addEventListener() {}},
    document: dom.document,
    escHtml: value => String(value ?? ''),
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js', 'utf8'), wizard);

  dom.node('wiz-use-docker').checked = true;
  dom.node('wiz-docker-mode').value = 'all';
  dom.node('wiz-docker-sequential').checked = true;
  // JSON round trip: objects from the VM realm have foreign prototypes.
  assert.deepEqual(JSON.parse(JSON.stringify(wizard._wizardCollectParams().docker_control)),
    {mode: 'all', selected: [], ack_appdata_risk: false, sequential: true});
  dom.node('wiz-use-docker').checked = false;
  assert.equal(wizard._wizardCollectParams().docker_control.sequential, false,
    'Disabled Docker control never stores the sequential option');

  wizard._wizardSetRuntimeControl('docker', {mode: 'except_selected', selected: ['plex'], sequential: true});
  assert.equal(dom.node('wiz-docker-sequential').checked, true);
  assert.equal(dom.node('wiz-docker-mode').value, 'except_selected');
  wizard._wizardSetRuntimeControl('docker', {mode: 'all'});
  assert.equal(dom.node('wiz-docker-sequential').checked, false, 'Older jobs keep the all-at-once behavior');

  const enabled = t('wizard.dockerSequentialEnabled');
  assert.ok(wizard._wizardRuntimePreviewText('docker', {docker_mode: 'all', docker_sequential: true}).endsWith(`(${enabled})`));
  assert.ok(wizard._wizardRuntimePreviewText('docker', {docker_mode: 'except_selected', docker_selected: ['plex'],
    docker_sequential: true}).includes('plex'));
  assert.ok(!wizard._wizardRuntimePreviewText('docker', {docker_mode: 'all', docker_sequential: false}).includes(enabled));
  for (const code of ['dockerSequence', 'dockerSequenceRuntime', 'dockerSequenceGroup', 'dockerSequenceIdle',
    'borgCreateMain', 'borgCreateMainSkipped', 'borgMaintenanceSeries']) {
    assert.notEqual(t(`wizard.flowSteps.${code}`), `wizard.flowSteps.${code}`, `${language}: ${code} is translated`);
  }

  const jobs = vm.createContext({
    window: {addEventListener() {}, BBUI: {components: {i18n: {t}}}},
    document: {addEventListener() {}, getElementById: () => null, querySelectorAll: () => []},
    EventSource: class {addEventListener() {} close() {}},
    escHtml: value => String(value ?? '').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  });
  vm.runInContext(fs.readFileSync('ui/js/pages/jobs.js', 'utf8'), jobs);
  const running = {id: 'docker_sequence', status: 'running', started_at: 100,
    details: {target_count: 3, completed_count: 1, current: 'nextcloud',
      groups: [{containers: ['mariadb'], status: 'success'}, {containers: ['nextcloud'], status: 'running'}]}};
  const job = {key: 'demo', running: true, run_job_steps: [running, {id: 'create', status: 'pending'}]};
  assert.deepEqual([...jobs.jobWorkflowSteps(job)].map(step => step.id), ['docker_sequence', 'create']);
  const view = jobs.jobStepView(running, job, 130);
  assert.equal(view.label, t('jobs.workflow.names.docker_sequence'));
  const details = jobs.jobStepDetails(running, view);
  assert.ok(details.includes(t('jobs.workflow.sequenceProgress', {done: 1, total: 3})));
  assert.ok(details.includes(t('jobs.workflow.sequenceCurrent', {name: 'nextcloud'})));
  assert.ok(!details.includes('mariadb'), 'Successful groups are summarized, not listed');
  assert.match(jobs.renderJobOperation(job, 130), new RegExp(`${t('jobs.workflow.names.docker_sequence')}: nextcloud`));

  const failed = {id: 'docker_sequence', status: 'error', duration_seconds: 40,
    details: {target_count: 3, completed_count: 1, current: '',
      groups: [{containers: ['mariadb'], status: 'success'}, {containers: ['radarr', 'sonarr'], status: 'error'}]}};
  const finished = {key: 'demo', running: false, last_job_steps: [failed]};
  const failedText = jobs.jobStepDetails(failed, jobs.jobStepView(failed, finished, 200));
  assert.ok(failedText.includes(`radarr + sonarr: ${t('jobs.borgStep.error')}`));

  for (const reason of ['no_container_paths', 'no_main_archive']) {
    const skipped = {id: reason === 'no_main_archive' ? 'create' : 'docker_sequence', status: 'skipped', reason};
    assert.equal(jobs.jobStepView(skipped, finished, 200).status, t(`jobs.borgStep.${reason}`));
  }
}
console.log('Sequential Docker mode: wizard payload, preview text and job-card progress passed.');
