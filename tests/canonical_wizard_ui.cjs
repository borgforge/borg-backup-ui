// Executable wizard contract tests (#473), without a backend or production data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'ui/js/pages/wizard.js'), 'utf8');
const jobId = '11111111-1111-4111-8111-111111111111';

async function run(lang) {
  const dictionary = JSON.parse(fs.readFileSync(path.join(root, `ui/i18n/${lang}.json`), 'utf8'));
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { value: '', checked: false, hidden: false, textContent: '', innerHTML: '',
      classList: { add() {}, remove() {}, contains() { return false; } } });
    return elements.get(id);
  };
  const translate = (key, params = {}) => {
    const value = key.split('.').reduce((v, k) => v?.[k], dictionary);
    assert.equal(typeof value, 'string', `Missing ${lang} translation: ${key}`);
    return value.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
  };
  const calls = [];
  let failSchedule = true;
  const context = vm.createContext({
    window: { BBUI: { components: { i18n: { t: translate } }, core: { getSchedulesData: () => ({}), setSchedulesData() {} } }, addEventListener() {} },
    document: { getElementById: element },
    escHtml: (s) => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    apiErrorMessage: () => 'Synthetic failure', jobsState: {}, refreshJobs: async () => {}, showMsg() {},
    fetch: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: url === '/api/wizard/save' || !failSchedule, status: 400,
        json: async () => url === '/api/wizard/save' ? { job_id: jobId, revision: 'new-revision', job_name: 'Display name' } : {} };
    },
  });
  vm.runInContext(script, context);
  const evalJs = (s) => vm.runInContext(s, context);
  element('wiz-job-name').value = 'Meine schöne Daten';
  evalJs('wizardSuggestArchivePrefix()');
  assert.equal(element('wiz-archive-prefix').value, 'meine-schone-daten-backup');
  element('wiz-archive-prefix').value = 'Exact.Prefix_1';
  evalJs('wizardState.prefixEdited = true; wizardSuggestArchivePrefix()');
  assert.equal(element('wiz-archive-prefix').value, 'Exact.Prefix_1');
  evalJs("wizardState.archivePrefixes = ['old-prefix', 'Exact.Prefix_1']; wizardRenderArchivePrefixSummary()");
  const html = element('wiz-archive-prefix-summary').innerHTML;
  assert.ok(html.includes('Exact.Prefix_1-YYYY-MM-DD_HH-mm-ss'));
  assert.ok(!html.includes('Exact.Prefix_1-backup'));
  assert.ok(html.includes('old-prefix-*'));
  assert.ok(html.includes(dictionary.wizard.archivePrefixHistoryHint));
  assert.ok(html.includes('role="tooltip"'));
  for (const invalid of ['', '.', '..', 'a/b', 'a b', 'a*', ' a', 'a\n', '<script>']) {
    assert.equal(context.wizardValidArchivePrefix(invalid), false);
  }
  element('wiz-archive-prefix').value = '<img src=x>';
  evalJs('wizardRenderArchivePrefixSummary()');
  assert.equal(element('wiz-archive-prefix-summary').hidden, true);
  element('wiz-archive-prefix').value = 'Exact.Prefix_1';
  assert.equal(context.wizardApiErrorMessage({ code: 'job_edit_conflict' }), dictionary.wizard.jobEditConflict);
  // Exercise the actual collector with unrelated DOM controls stubbed.
  evalJs(`wizardSelectedStorage = () => ({storage_key:'local'});
    wizardSelectedRepository = () => ({encryption:'none'});
    _wizardRuntimeMode = () => 'none'; _wizardRiskAcknowledged = () => false;
    wizardState.sourcePaths = ['/synthetic']; wizardState.jobId = '${jobId}';
    wizardState.revision = 'revision'; wizardState.mode = 'edit';`);
  const params = JSON.parse(JSON.stringify(context._wizardCollectParams()));
  assert.equal(params.job_id, jobId);
  assert.equal(params.expected_revision, 'revision');
  assert.equal(params.archive_prefix, 'Exact.Prefix_1');
  for (const field of ['type_id', 'job_key', 'existing_job_key', 'backup_type', 'location']) assert.ok(!(field in params));
  // Saving a new job then failing to save its schedule must retry by returned ID.
  evalJs("wizardState.mode='create'; wizardState.jobId=''; _wizardValidate=()=>true; _wizardBuildCron=()=> '0 3 * * *'; closeWizard=()=>{};");
  element('wiz-sched-enabled').checked = true;
  await context.saveWizardJob();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].body.job_id, jobId);
  assert.equal(evalJs('wizardState.mode'), 'edit');
  assert.equal(evalJs('wizardState.jobId'), jobId);
  assert.ok(element('wizard-error-9').textContent.includes(dictionary.wizard.saveError.split('{')[0]));
  failSchedule = false;
  await context.saveWizardJob();
  assert.equal(calls[2].body._wizard_mode, 'edit');
  assert.equal(calls[2].body.job_id, jobId);
  assert.equal(calls[2].body.expected_revision, 'new-revision');
  assert.equal(calls[3].body.job_id, jobId);
}

(async () => { await run('de'); await run('en'); console.log('Canonical wizard UI: DE/EN passed'); })().catch((err) => {
  console.error(err); process.exitCode = 1;
});
