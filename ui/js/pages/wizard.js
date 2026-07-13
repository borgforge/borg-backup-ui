// JOB WIZARD
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.wizardState = window.BBUI.wizardState || {
  step: 1,
  mode: 'create',
  existingJobKey: '',
  original: null,
  storages: [],
  selectedStorageKey: '',
  repositories: [],
  selectedRepositoryKey: '',
  loadingPromise: null,
  sourcePaths: [],
  sourceSuggest: [],
  sourceSuggestIndex: -1,
  sourceSuggestTimer: null,
  sourceSuggestController: null,
  sourceSuggestRequest: 0,
  excludePaths: [],
  excludeSuggest: [],
  excludeSuggestIndex: -1,
  excludeSuggestTimer: null,
  excludeSuggestController: null,
  excludeSuggestRequest: 0,
  remoteRepoStatus: null,
  dockerContainers: [],
  vms: [],
  selectedDockerContainers: [],
  selectedVms: [],
  unlockedStep: 1,
  originalSchedule: null,
};
const wizardState = window.BBUI.wizardState;

function wizardT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function wizardApiErrorMessage(payload, status = 0) {
  const data = payload && typeof payload === 'object' ? payload : {};
  for (const key of ['details', 'message', 'error']) {
    const value = String(data[key] || '').trim();
    if (value && value !== String(data.code || '').trim()) return value;
  }
  return apiErrorMessage(payload, status);
}

function _wizardUniqueList(values) {
  const out = [];
  const seen = new Set();
  (Array.isArray(values) ? values : []).forEach((raw) => {
    const val = String(raw || '').trim();
    if (!val || seen.has(val)) return;
    seen.add(val);
    out.push(val);
  });
  return out;
}

async function wizardLoadRuntimeInventory() {
  try {
    const res = await fetch('/api/wizard/runtime-inventory');
    if (!res.ok) return;
    const data = await res.json();
    wizardState.dockerContainers = Array.isArray(data?.docker_containers) ? data.docker_containers : [];
    wizardState.vms = Array.isArray(data?.vms) ? data.vms : [];
  } catch (_) {
    wizardState.dockerContainers = [];
    wizardState.vms = [];
  } finally {
    wizardRenderRuntimeControls();
  }
}

function _wizardRuntimeMode(kind) {
  const enabled = document.getElementById(kind === 'docker' ? 'wiz-use-docker' : 'wiz-use-vm')?.checked;
  if (!enabled) return 'none';
  return document.getElementById(kind === 'docker' ? 'wiz-docker-mode' : 'wiz-vm-mode')?.value || 'all';
}

function _wizardSetRuntimeControl(kind, control = {}) {
  const enabledEl = document.getElementById(kind === 'docker' ? 'wiz-use-docker' : 'wiz-use-vm');
  const modeEl = document.getElementById(kind === 'docker' ? 'wiz-docker-mode' : 'wiz-vm-mode');
  const mode = ['all', 'selected', 'none'].includes(String(control?.mode || '').toLowerCase())
    ? String(control.mode).toLowerCase()
    : 'none';
  if (enabledEl) enabledEl.checked = mode !== 'none';
  if (modeEl) modeEl.value = mode === 'selected' ? 'selected' : 'all';
  if (kind === 'docker') {
    wizardState.selectedDockerContainers = _wizardUniqueList(control?.selected || []);
    const ack = document.getElementById('wiz-ack-appdata-risk');
    if (ack) ack.checked = !!control?.ack_appdata_risk;
  } else {
    wizardState.selectedVms = _wizardUniqueList(control?.selected || []);
    const ack = document.getElementById('wiz-ack-domains-risk');
    if (ack) ack.checked = !!control?.ack_domains_risk;
  }
  wizardRenderRuntimeControls();
}

function wizardRenderRuntimeControls() {
  const dockerEnabled = !!document.getElementById('wiz-use-docker')?.checked;
  const vmEnabled = !!document.getElementById('wiz-use-vm')?.checked;
  document.getElementById('wstep-dot-3')?.classList.toggle('wizard-step-skipped', !dockerEnabled);
  document.getElementById('wstep-dot-4')?.classList.toggle('wizard-step-skipped', !vmEnabled);
  _wizardRenderRuntimeSelection('docker');
  _wizardRenderRuntimeSelection('vm');
  _wizardUpdateRuntimeCount('docker');
  _wizardUpdateRuntimeCount('vm');
  wizardUpdateRuntimeRiskWarnings();
}

function _wizardRenderRuntimeSelection(kind) {
  const mode = _wizardRuntimeMode(kind);
  const target = document.getElementById(kind === 'docker' ? 'wiz-docker-selection' : 'wiz-vm-selection');
  if (!target) return;
  target.classList.toggle('hidden', mode !== 'selected');
  if (mode !== 'selected') return;
  const rows = kind === 'docker' ? wizardState.dockerContainers : wizardState.vms;
  const selected = new Set(kind === 'docker' ? wizardState.selectedDockerContainers : wizardState.selectedVms);
  const emptyText = wizardT(kind === 'docker' ? 'wizard.noDockerContainers' : 'wizard.noVms');
  if (!Array.isArray(rows) || rows.length === 0) {
    target.innerHTML = `<div class="wizard-runtime-empty">${escHtml(emptyText)}</div>`;
    return;
  }
  target.innerHTML = rows.map((row) => {
    const name = String(row?.name || '').trim();
    if (!name) return '';
    const state = String(row?.state || row?.status || '').trim();
    const stateClass = _wizardRuntimeStateClass(state);
    const checked = selected.has(name) ? ' checked' : '';
    const selectedClass = selected.has(name) ? ' is-selected' : '';
    return `<label class="wizard-runtime-row${selectedClass}">
      <input type="checkbox" data-runtime-kind="${kind}" value="${escHtml(name)}"${checked}>
      <span class="wizard-runtime-name">${escHtml(name)}</span>
      <span class="wizard-runtime-state ${stateClass}">${escHtml(state || '—')}</span>
    </label>`;
  }).join('');
  target.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener('change', () => {
      const list = kind === 'docker' ? wizardState.selectedDockerContainers : wizardState.selectedVms;
      const next = new Set(list);
      const name = String(input.value || '').trim();
      if (input.checked) next.add(name);
      else next.delete(name);
      if (kind === 'docker') wizardState.selectedDockerContainers = Array.from(next);
      else wizardState.selectedVms = Array.from(next);
      input.closest('.wizard-runtime-row')?.classList.toggle('is-selected', input.checked);
      _wizardUpdateRuntimeCount(kind);
    });
  });
}

function _wizardUpdateRuntimeCount(kind) {
  const target = document.getElementById(kind === 'docker' ? 'wiz-docker-count' : 'wiz-vm-count');
  if (!target) return;
  const mode = _wizardRuntimeMode(kind);
  const rows = kind === 'docker' ? wizardState.dockerContainers : wizardState.vms;
  const selected = kind === 'docker' ? wizardState.selectedDockerContainers : wizardState.selectedVms;
  const total = Array.isArray(rows) ? rows.length : 0;
  if (mode === 'selected') {
    target.textContent = wizardT('wizard.runtimeSelectionCount', { selected: selected.length, total });
  } else if (mode === 'all') {
    target.textContent = wizardT('wizard.runtimeAllCount', { total });
  } else {
    target.textContent = '';
  }
}

function _wizardRuntimeStateClass(state) {
  const normalized = String(state || '').trim().toLowerCase();
  if (['running', 'active'].includes(normalized)) return 'is-running';
  if (['paused', 'pmsuspended', 'blocked'].includes(normalized)) return 'is-warning';
  if (['exited', 'created', 'shut off', 'shutoff', 'inactive'].includes(normalized)) return 'is-stopped';
  return 'is-unknown';
}

function _wizardHasExactSourcePath(path) {
  const normalized = String(path || '').replace(/\/+$/, '');
  return (wizardState.sourcePaths || []).some((raw) => String(raw || '').replace(/\/+$/, '') === normalized);
}

function wizardUpdateRuntimeRiskWarnings() {
  const appdataRisk = _wizardHasExactSourcePath('/mnt/user/appdata') && _wizardRuntimeMode('docker') !== 'all';
  const domainsRisk = _wizardHasExactSourcePath('/mnt/user/domains') && _wizardRuntimeMode('vm') !== 'all';
  document.getElementById('wiz-appdata-risk')?.classList.toggle('hidden', !appdataRisk);
  document.getElementById('wiz-domains-risk')?.classList.toggle('hidden', !domainsRisk);
  if (!appdataRisk) document.getElementById('wiz-appdata-risk')?.classList.remove('wizard-runtime-attention');
  if (!domainsRisk) document.getElementById('wiz-domains-risk')?.classList.remove('wizard-runtime-attention');
}

function wizardBindRuntimeControls() {
  ['wiz-use-docker', 'wiz-use-vm', 'wiz-docker-mode', 'wiz-vm-mode', 'wiz-ack-appdata-risk', 'wiz-ack-domains-risk'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.runtimeBound === '1') return;
    el.dataset.runtimeBound = '1';
    el.addEventListener('change', () => {
      el.closest('.status-message')?.classList.remove('wizard-runtime-attention');
      wizardRenderRuntimeControls();
    });
  });
}

async function wizardLoadRepositories() {
  try {
    const res = await fetch('/api/repositories');
    if (!res.ok) return;
    const data = await res.json();
    wizardState.repositories = Array.isArray(data?.repositories) ? data.repositories : [];
  } catch (_) {
    wizardState.repositories = [];
  }
  wizardSetRepositoryOptions();
}

async function wizardLoadStorageTargets() {
  try {
    const res = await fetch('/api/storage');
    if (!res.ok) return;
    const data = await res.json();
    wizardState.storages = Array.isArray(data?.storages) ? data.storages : [];
  } catch (_) {
    wizardState.storages = [];
  }
  wizardSetStorageOptions();
}

function wizardStorageLabel(storage) {
  const name = String(storage?.display_name || storage?.storage_key || '').trim();
  const path = String(storage?.base_path || storage?.mount_path || storage?.endpoint || '').trim();
  return [name, path].filter(Boolean).join(' — ');
}

function wizardSetStorageOptions() {
  const sel = document.getElementById('wiz-storage-key');
  if (!sel) return;
  const location = String(document.getElementById('wiz-location')?.value || 'local').trim().toLowerCase();
  const rows = (Array.isArray(wizardState.storages) ? wizardState.storages : [])
    .filter((storage) => String(storage?.location || storage?.storage_type || '').trim().toLowerCase() === location);
  sel.innerHTML = rows.length
    ? rows.map((storage) => `<option value="${escHtml(storage.storage_key || '')}">${escHtml(wizardStorageLabel(storage))}</option>`).join('')
    : `<option value="">${wizardT('wizard.noStorageTargetsForLocation')}</option>`;
  const wanted = wizardState.selectedStorageKey || '';
  const found = rows.find((storage) => String(storage.storage_key || '') === wanted);
  sel.value = found ? wanted : (rows[0]?.storage_key || '');
  wizardState.selectedStorageKey = sel.value;
  wizardSetRepositoryOptions();
}

function wizardSelectedStorage() {
  const key = String(document.getElementById('wiz-storage-key')?.value || wizardState.selectedStorageKey || '').trim();
  wizardState.selectedStorageKey = key;
  return (Array.isArray(wizardState.storages) ? wizardState.storages : [])
    .find((storage) => String(storage.storage_key || '') === key) || null;
}

function wizardRepositoryPath(repo) {
  return String(repo?.path_raw || '').trim();
}

function wizardRepositoryLabel(repo) {
  const name = String(repo?.display_name || repo?.repository_name || repo?.repository_key || '').trim();
  const path = wizardRepositoryPath(repo);
  return path ? `${name} (${path})` : name;
}

function wizardRepositoryMatchesSelection(repo, location) {
  if (String(repo?.location || '').trim().toLowerCase() !== location) return false;
  const storageKey = String(document.getElementById('wiz-storage-key')?.value || wizardState.selectedStorageKey || '').trim();
  return !!storageKey && String(repo?.storage_key || '').trim() === storageKey;
}

function wizardSetRepositoryOptions() {
  const sel = document.getElementById('wiz-repository-key');
  if (!sel) return;
  const location = String(document.getElementById('wiz-location')?.value || 'local').trim().toLowerCase();
  const rows = (Array.isArray(wizardState.repositories) ? wizardState.repositories : [])
    .filter((repo) => wizardRepositoryMatchesSelection(repo, location));
  sel.innerHTML = rows.length
    ? rows.map((repo) => `<option value="${escHtml(repo.repository_key || '')}">${escHtml(wizardRepositoryLabel(repo))}</option>`).join('')
    : `<option value="">${wizardT('wizard.noRepositoriesForLocation')}</option>`;
  const wanted = wizardState.selectedRepositoryKey || '';
  const found = rows.find((repo) => String(repo.repository_key || '') === wanted);
  sel.value = found ? wanted : (rows[0]?.repository_key || '');
  wizardState.selectedRepositoryKey = sel.value;
  wizardApplySelectedRepository();
}

function wizardSelectedRepository() {
  const key = String(document.getElementById('wiz-repository-key')?.value || wizardState.selectedRepositoryKey || '').trim();
  wizardState.selectedRepositoryKey = key;
  return (Array.isArray(wizardState.repositories) ? wizardState.repositories : [])
    .find((repo) => String(repo.repository_key || '') === key) || null;
}

function wizardApplySelectedRepository() {
  const repo = wizardSelectedRepository();
  const hintEl = document.getElementById('wiz-repository-hint');
  if (hintEl) {
    if (repo) {
      hintEl.textContent = '';
      hintEl.hidden = true;
      hintEl.classList.remove('status-message', 'warning-state');
      hintEl.classList.add('form-hint');
    } else {
      hintEl.hidden = false;
      hintEl.textContent = wizardT('wizard.noRepositorySelectedHint');
      hintEl.classList.remove('form-hint');
      hintEl.classList.add('status-message', 'warning-state');
    }
  }
}

function _setWizardFormDisabled(disabled) {
  const modal = document.getElementById('wizard-modal');
  if (!modal) return;
  modal.querySelectorAll('input, textarea, select, button').forEach((el) => {
    const id = el.id || '';
    // keep close button usable while loading fails/finishes
    if (id === 'wizard-close-btn') return;
    el.disabled = !!disabled;
  });
}

function openWizard() {
  wizardBindRuntimeControls();
  wizardState.mode = 'create';
  wizardState.existingJobKey = '';
  wizardState.original = null;
  wizardState.step = 1;
  wizardState.unlockedStep = 1;
  wizardState.originalSchedule = null;
  const title = document.getElementById('wizard-modal-title');
  if (title) title.textContent = wizardT('wizard.newTitle');
  document.getElementById('wiz-job-name').value = '';
  document.getElementById('wiz-type-id').value = '';
  document.getElementById('wiz-icon').value = '';
  document.getElementById('wiz-icon-color').value = '';
  document.getElementById('wiz-description').value = '';
  document.getElementById('wiz-location').value = 'local';
  wizardState.selectedStorageKey = '';
  wizardState.selectedRepositoryKey = '';
  wizardState.remoteRepoStatus = null;
  wizardState.selectedDockerContainers = [];
  wizardState.selectedVms = [];
  document.getElementById('wiz-use-docker').checked = false;
  document.getElementById('wiz-use-vm').checked = false;
  document.getElementById('wiz-docker-mode').value = 'all';
  document.getElementById('wiz-vm-mode').value = 'all';
  document.getElementById('wiz-ack-appdata-risk').checked = false;
  document.getElementById('wiz-ack-domains-risk').checked = false;
  // Ensure feature toggles are visible even if stale DOM/CSS state hid them before.
  const dockerGroup = document.getElementById('wiz-use-docker')?.closest('.form-group');
  const vmGroup = document.getElementById('wiz-use-vm')?.closest('.form-group');
  if (dockerGroup) dockerGroup.style.display = '';
  if (vmGroup) vmGroup.style.display = '';
  document.getElementById('wiz-source-paths').value = '';
  document.getElementById('wiz-source-path-input').value = '';
  wizardCancelSourceSuggestRequest();
  wizardState.sourcePaths = [];
  wizardState.sourceSuggest = [];
  wizardState.sourceSuggestIndex = -1;
  wizardRenderSourcePaths();
  document.getElementById('wiz-exclude-paths').value = '';
  document.getElementById('wiz-exclude-path-input').value = '';
  wizardCancelExcludeSuggestRequest();
  wizardState.excludePaths = [];
  wizardState.excludeSuggest = [];
  wizardState.excludeSuggestIndex = -1;
  wizardRenderExcludePaths();
  document.getElementById('wiz-compression').value = 'lz4';
  document.getElementById('wiz-keep-daily').value = '7';
  document.getElementById('wiz-keep-weekly').value = '4';
  document.getElementById('wiz-keep-monthly').value = '6';
  document.getElementById('wiz-keep-yearly').value = '3';
  document.getElementById('wizard-preview-wrap').classList.add('hidden');
  document.getElementById('wizard-preview-loading').classList.add('hidden');
  // Reset schedule step
  document.getElementById('wiz-sched-enabled').checked = false;
  document.getElementById('wiz-sched-hour').value = 3;
  document.getElementById('wiz-sched-minute').value = 0;
  document.getElementById('wiz-sched-dom').value = 1;
  document.getElementById('wiz-sched-cron-custom').value = '0 3 * * *';
  const smbMountBefore = document.getElementById('wiz-smb-mount-before-run');
  const smbUnmountAfter = document.getElementById('wiz-smb-unmount-after-run');
  if (smbMountBefore) smbMountBefore.checked = true;
  if (smbUnmountAfter) smbUnmountAfter.checked = true;
  wizardSchedState.frequency = 'daily';
  wizardSchedState.dow = 1;
  _wizardScheduleApplyUI('daily');
  wizardSchedulePreview();
  wizardUpdateIconPreview();
  wizardState.loadingPromise = Promise.all([
    wizardLoadStorageTargets(),
    wizardLoadRepositories(),
    wizardLoadRuntimeInventory(),
  ]).finally(() => wizardAutoFill());
  [1,2,3,4,5,6,7,8,9].forEach(n => wizardClearError(n));
  wizardRenderRuntimeControls();
  _renderWizardStep(1);
  document.getElementById('wizard-modal').classList.remove('hidden');
  document.body.classList.add('wizard-modal-open');
}

function _wizardFillFromJob(job) {
  wizardState.remoteRepoStatus = null;
  document.getElementById('wiz-job-name').value = job.job_name || '';
  document.getElementById('wiz-type-id').value = (job.type_id || '').toLowerCase();
  document.getElementById('wiz-icon').value = (job.icon || '').toLowerCase();
  document.getElementById('wiz-icon-color').value = (job.icon_color || '').toLowerCase();
  document.getElementById('wiz-description').value = job.description || '';
  document.getElementById('wiz-location').value = job.location || 'local';
  _wizardSetRuntimeControl('docker', job.docker_control || { mode: job.use_docker ? 'all' : 'none' });
  _wizardSetRuntimeControl('vm', job.vm_control || { mode: job.use_vm ? 'all' : 'none' });
  const parsedPaths = (job.source_paths || '').split(' ').filter(Boolean);
  document.getElementById('wiz-source-paths').value = parsedPaths.join('\n');
  wizardState.sourcePaths = parsedPaths;
  wizardRenderSourcePaths();
  wizardState.excludePaths = _wizardUniqueList(job.exclude_paths || []);
  wizardRenderExcludePaths();
  wizardState.selectedRepositoryKey = String(job.repository_key || '').trim();
  const smbMountBefore = document.getElementById('wiz-smb-mount-before-run');
  const smbUnmountAfter = document.getElementById('wiz-smb-unmount-after-run');
  if (smbMountBefore) smbMountBefore.checked = job.mount_before_run !== false;
  if (smbUnmountAfter) smbUnmountAfter.checked = job.unmount_after_run !== false;
  const selectedRepo = (wizardState.repositories || []).find((repo) => String(repo.repository_key || '') === wizardState.selectedRepositoryKey);
  wizardState.selectedStorageKey = String(selectedRepo?.storage_key || job.storage_key || '').trim();
  document.getElementById('wiz-compression').value = job.compression || 'lz4';
  document.getElementById('wiz-keep-daily').value = job.keep_daily || '7';
  document.getElementById('wiz-keep-weekly').value = job.keep_weekly || '4';
  document.getElementById('wiz-keep-monthly').value = job.keep_monthly || '6';
  document.getElementById('wiz-keep-yearly').value = job.keep_yearly || '3';
  _wizardApplySchedule(job.schedule);
  wizardUpdateIconPreview();
  wizardAutoFill();
  if (job.repository_assignment_error) {
    _wizardShowError(2, wizardT('wizard.repositoryAssignmentRepair', {
      job: job.job_name || job.job_key || '',
      message: job.repository_assignment_error,
    }));
  }
}

async function openWizardForJob(jobKey, mode = 'edit') {
  openWizard();
  wizardState.mode = mode;
  wizardState.existingJobKey = jobKey;
  const title = document.getElementById('wizard-modal-title');
  if (title) title.textContent = wizardT('wizard.editTitle');
  _setWizardFormDisabled(true);
  try {
    await wizardState.loadingPromise;
    const res = await fetch(`/api/wizard/job?job_key=${encodeURIComponent(jobKey)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));
    const job = data.job || {};
    _wizardFillFromJob(job);
    wizardState.original = {
      type_id: (job.type_id || '').toLowerCase(),
      location: job.location || 'local',
      repository_key: String(job.repository_key || '').trim(),
      use_docker: !!job.use_docker,
      use_vm: !!job.use_vm,
      docker_control: job.docker_control || { mode: job.use_docker ? 'all' : 'none', selected: [] },
      vm_control: job.vm_control || { mode: job.use_vm ? 'all' : 'none', selected: [] },
    };
    wizardState.originalSchedule = job.schedule && typeof job.schedule === 'object'
      ? { cron: String(job.schedule.cron || '').trim(), enabled: !!job.schedule.enabled }
      : null;
    wizardState.unlockedStep = 9;
    _renderWizardStep(wizardState.step);
  } catch (err) {
    closeWizard();
    showMsg('jobs-message', 'error', wizardT('wizard.loadFailed', { message: err.message }));
  } finally {
    _setWizardFormDisabled(false);
    _wizardUpdateStepNavigation();
  }
}

function wizardNeedsScriptRegeneration(params) {
  if ((wizardState.mode || 'create') === 'create') return true;
  const orig = wizardState.original;
  if (!orig) return true;
  if (params.type_id !== orig.type_id) return true;
  if (params.location !== orig.location) return true;
  if (params.repository_key !== orig.repository_key) return true;
  if (!!params.use_docker !== !!orig.use_docker) return true;
  if (!!params.use_vm !== !!orig.use_vm) return true;
  if (JSON.stringify(params.docker_control || {}) !== JSON.stringify(orig.docker_control || {})) return true;
  if (JSON.stringify(params.vm_control || {}) !== JSON.stringify(orig.vm_control || {})) return true;
  return false;
}

function closeWizard() {
  document.getElementById('wizard-modal').classList.add('hidden');
  document.body.classList.remove('wizard-modal-open');
}

function _renderWizardStep(n) {
  [1,2,3,4,5,6,7,8,9].forEach(i => {
    document.getElementById(`wizard-step-${i}`)?.classList.toggle('hidden', i !== n);
    const dot = document.getElementById(`wstep-dot-${i}`);
    if (dot) {
      dot.classList.toggle('active', i <= n);
      dot.classList.toggle('wizard-step-current', i === n);
      if (i === n) dot.setAttribute('aria-current', 'step');
      else dot.removeAttribute('aria-current');
    }
  });
  const backBtn = document.getElementById('wizard-back-btn');
  const nextBtn = document.getElementById('wizard-next-btn');
  const saveBtn = document.getElementById('wizard-save-btn');
  backBtn.style.display = n > 1 ? '' : 'none';
  nextBtn.classList.toggle('hidden', n === 9);
  saveBtn.classList.toggle('hidden', n !== 9);
  wizardState.step = n;
  _wizardUpdateStepNavigation();
}

function _wizardUpdateStepNavigation() {
  [1,2,3,4,5,7,8,9].forEach((step) => {
    const dot = document.getElementById(`wstep-dot-${step}`);
    if (!dot) return;
    const skipped = !_wizardStepEnabled(step);
    const locked = step > Number(wizardState.unlockedStep || 1);
    dot.disabled = skipped || locked;
    dot.setAttribute('aria-disabled', String(skipped || locked));
    dot.classList.toggle('wizard-step-skipped', skipped);
  });
}

function _wizardStepEnabled(step) {
  if (step === 3) return _wizardRuntimeMode('docker') !== 'none';
  if (step === 4) return _wizardRuntimeMode('vm') !== 'none';
  if (step === 6) return false;
  return true;
}

function _wizardNextStepFrom(step) {
  for (let next = step + 1; next <= 9; next += 1) {
    if (_wizardStepEnabled(next)) return next;
  }
  return 9;
}

function _wizardPreviousStepFrom(step) {
  for (let prev = step - 1; prev >= 1; prev -= 1) {
    if (_wizardStepEnabled(prev)) return prev;
  }
  return 1;
}

function wizardAutoFill() {
  const location = document.getElementById('wiz-location').value;
  const iconEl = document.getElementById('wiz-icon');
  const smbMountOptionsEl = document.getElementById('wiz-smb-mount-options-group');
  if (smbMountOptionsEl) smbMountOptionsEl.classList.toggle('hidden', location !== 'smb');
  wizardSetStorageOptions();
  const storage = wizardSelectedStorage();
  const hint = document.getElementById('wiz-storage-target-hint');
  if (hint) {
    hint.textContent = storage ? '' : wizardT('wizard.noStorageTargetSelectedHint');
    hint.hidden = !!storage;
    hint.classList.toggle('warning-state', !storage);
  }
  // If icon not explicitly chosen, keep "auto" (empty) and let rendering
  // derive it from backup_type/type_id.
  if (iconEl && iconEl.value === '') iconEl.value = '';
  wizardUpdateIconPreview();
}

function wizardIconMarkup(kind) {
  const t = String(kind || '').toLowerCase();
  return typeIcon(t || 'sonstiges');
}

function wizardEffectiveIcon() {
  const chosen = (document.getElementById('wiz-icon')?.value || '').trim().toLowerCase();
  if (chosen) return chosen;
  const typeId = (document.getElementById('wiz-type-id')?.value || '').trim().toLowerCase();
  return typeId || 'sonstiges';
}

function wizardUpdateIconPreview() {
  const box = document.getElementById('wiz-icon-preview-box');
  const label = document.getElementById('wiz-icon-preview-label');
  if (!box || !label) return;
  const iconKey = wizardEffectiveIcon();
  const colorKey = (document.getElementById('wiz-icon-color')?.value || '').trim().toLowerCase();
  box.innerHTML = wizardIconMarkup(iconKey);
  const knownColor = new Set([
    'blue', 'indigo', 'purple', 'pink',
    'green', 'lime', 'violet',
    'amber', 'orange',
    'red', 'rose',
    'teal', 'cyan', 'gray',
  ]);
  box.className = `type-icon type-icon-${iconKey || 'sonstiges'}${knownColor.has(colorKey) ? ` type-icon-color-${colorKey}` : ''}`;
  label.textContent = iconKey || wizardT('wizard.automatic');
}

function wizardClearError(step) {
  const el = document.getElementById(`wizard-error-${step}`);
  if (el) el.classList.add('hidden');
}

function _wizardShowError(step, msg) {
  const el = document.getElementById(`wizard-error-${step}`);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}

function _wizardFocusRuntimeRisk(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('wizard-runtime-attention');
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function _wizardCollectParams() {
  const rawPaths = (wizardState.sourcePaths || []).map((s) => String(s || '').trim()).filter(Boolean).join(' ');
  const storage = wizardSelectedStorage();
  const repository = wizardSelectedRepository();
  const dockerMode = _wizardRuntimeMode('docker');
  const vmMode = _wizardRuntimeMode('vm');
  return {
    type_id:      (document.getElementById('wiz-type-id').value || '').trim().toLowerCase(),
    icon:         (document.getElementById('wiz-icon').value || '').trim().toLowerCase(),
    icon_color:   (document.getElementById('wiz-icon-color').value || '').trim().toLowerCase(),
    job_name:     (document.getElementById('wiz-job-name').value || '').trim(),
    description:  (document.getElementById('wiz-description').value || '').trim(),
    location:     document.getElementById('wiz-location').value,
    storage_key: String(storage?.storage_key || '').trim(),
    mount_before_run: !!document.getElementById('wiz-smb-mount-before-run')?.checked,
    unmount_after_run: !!document.getElementById('wiz-smb-unmount-after-run')?.checked,
    use_docker:   dockerMode !== 'none',
    use_vm:       vmMode !== 'none',
    docker_control: {
      mode: dockerMode,
      selected: dockerMode === 'selected' ? _wizardUniqueList(wizardState.selectedDockerContainers) : [],
      ack_appdata_risk: !!document.getElementById('wiz-ack-appdata-risk')?.checked,
    },
    vm_control: {
      mode: vmMode,
      selected: vmMode === 'selected' ? _wizardUniqueList(wizardState.selectedVms) : [],
      ack_domains_risk: !!document.getElementById('wiz-ack-domains-risk')?.checked,
    },
    source_paths: rawPaths,
    exclude_paths: _wizardUniqueList(wizardState.excludePaths || []),
    repository_key: (document.getElementById('wiz-repository-key')?.value || wizardState.selectedRepositoryKey || '').trim(),
    compression:  document.getElementById('wiz-compression').value,
    encryption: String(repository?.encryption || '').trim(),
    passphrase: '',
    keep_daily:   document.getElementById('wiz-keep-daily').value,
    keep_weekly:  document.getElementById('wiz-keep-weekly').value,
    keep_monthly: document.getElementById('wiz-keep-monthly').value,
    keep_yearly:  document.getElementById('wiz-keep-yearly').value,
    _wizard_mode: wizardState.mode || 'create',
    existing_job_key: wizardState.existingJobKey || '',
  };
}

function wizardSyncSourcePathsTextarea() {
  const ta = document.getElementById('wiz-source-paths');
  if (!ta) return;
  ta.value = (wizardState.sourcePaths || []).join('\n');
}

function wizardRenderSourcePaths() {
  wizardSyncSourcePathsTextarea();
  wizardUpdateRuntimeRiskWarnings();
  const list = document.getElementById('wiz-source-path-list');
  if (!list) return;
  const items = wizardState.sourcePaths || [];
  if (!items.length) {
    list.innerHTML = `<div class="form-hint">${wizardT('wizard.noSourcePaths')}</div>`;
    return;
  }
  list.innerHTML = items.map((p, idx) => `
    <div class="wizard-path-chip">
      <span class="wizard-path-chip-text">${escHtml(p)}</span>
      <button type="button" class="wizard-path-chip-del" data-wiz-src-del="${idx}" title="${wizardT('wizard.removeSource')}" aria-label="${wizardT('wizard.removeSource')}">×</button>
    </div>
  `).join('');
}

function wizardRenderExcludePaths() {
  const hidden = document.getElementById('wiz-exclude-paths');
  if (hidden) hidden.value = (wizardState.excludePaths || []).join('\n');
  const list = document.getElementById('wiz-exclude-path-list');
  if (!list) return;
  const items = wizardState.excludePaths || [];
  list.innerHTML = items.length ? items.map((path, index) => `
    <div class="wizard-path-chip">
      <span class="wizard-path-chip-text">${escHtml(path)}</span>
      <button type="button" class="wizard-path-chip-del" data-wiz-exclude-del="${index}" title="${wizardT('wizard.removeExclude')}" aria-label="${wizardT('wizard.removeExclude')}">×</button>
    </div>`).join('') : `<div class="form-hint">${wizardT('wizard.noExcludePaths')}</div>`;
}

function wizardCancelExcludeSuggestRequest() {
  if (wizardState.excludeSuggestTimer) clearTimeout(wizardState.excludeSuggestTimer);
  wizardState.excludeSuggestTimer = null;
  if (wizardState.excludeSuggestController) wizardState.excludeSuggestController.abort();
  wizardState.excludeSuggestController = null;
  wizardState.excludeSuggestRequest += 1;
}

function wizardHideExcludeSuggest() {
  const box = document.getElementById('wiz-exclude-path-suggest');
  if (box) {
    box.classList.add('hidden');
    box.innerHTML = '';
  }
  wizardState.excludeSuggest = [];
  wizardState.excludeSuggestIndex = -1;
}

function wizardRenderExcludeSuggest() {
  const box = document.getElementById('wiz-exclude-path-suggest');
  const rows = wizardState.excludeSuggest || [];
  if (!box || !rows.length) return wizardHideExcludeSuggest();
  box.innerHTML = rows.map((row, index) => `<button type="button" class="wizard-suggest-item ${index === wizardState.excludeSuggestIndex ? 'active' : ''}" data-wiz-exclude-sel="${index}">${escHtml(row.path || '')}</button>`).join('');
  box.classList.remove('hidden');
}

function wizardExcludePathInputChanged() {
  const input = document.getElementById('wiz-exclude-path-input');
  const prefix = String(input?.value || '').trim();
  wizardCancelExcludeSuggestRequest();
  if (!prefix.startsWith('/mnt')) return wizardHideExcludeSuggest();
  const requestId = wizardState.excludeSuggestRequest;
  wizardState.excludeSuggestTimer = setTimeout(async () => {
    const controller = new AbortController();
    wizardState.excludeSuggestController = controller;
    try {
      const res = await fetch(`/api/wizard/source-dirs?prefix=${encodeURIComponent(prefix)}&limit=100`, { signal: controller.signal });
      const data = await res.json();
      if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));
      if (requestId !== wizardState.excludeSuggestRequest) return;
      wizardState.excludeSuggest = Array.isArray(data?.dirs) ? data.dirs : [];
      wizardState.excludeSuggestIndex = wizardState.excludeSuggest.length ? 0 : -1;
      wizardRenderExcludeSuggest();
    } catch (error) {
      if (error?.name !== 'AbortError') wizardHideExcludeSuggest();
    }
  }, 180);
}

function wizardExcludeBelowSource(path) {
  const candidate = String(path || '').replace(/\/+$/, '');
  return (wizardState.sourcePaths || []).some((source) => candidate.startsWith(String(source || '').replace(/\/+$/, '') + '/'));
}

function wizardAddExcludePath(value) {
  const path = String(value || '').trim().replace(/\/+$/, '');
  if (!path || !wizardIsAllowedSourcePath(path)) {
    _wizardShowError(2, wizardT('wizard.validationExcludeAbsolute'));
    return false;
  }
  if (!wizardExcludeBelowSource(path)) {
    _wizardShowError(2, wizardT('wizard.validationExcludeBelowSource'));
    return false;
  }
  wizardClearError(2);
  if (!(wizardState.excludePaths || []).includes(path)) wizardState.excludePaths.push(path);
  document.getElementById('wiz-exclude-path-input').value = '';
  wizardCancelExcludeSuggestRequest();
  wizardHideExcludeSuggest();
  wizardRenderExcludePaths();
  return true;
}

function wizardExcludePathKeydown(event) {
  const rows = wizardState.excludeSuggest || [];
  if (event.key === 'ArrowDown' && rows.length) {
    event.preventDefault();
    wizardState.excludeSuggestIndex = (wizardState.excludeSuggestIndex + 1) % rows.length;
    return wizardRenderExcludeSuggest();
  }
  if (event.key === 'ArrowUp' && rows.length) {
    event.preventDefault();
    wizardState.excludeSuggestIndex = (wizardState.excludeSuggestIndex - 1 + rows.length) % rows.length;
    return wizardRenderExcludeSuggest();
  }
  if (event.key === 'ArrowRight' && rows.length) {
    const selected = rows[wizardState.excludeSuggestIndex]?.path;
    if (selected) {
      event.preventDefault();
      document.getElementById('wiz-exclude-path-input').value = selected;
      wizardHideExcludeSuggest();
      wizardExcludePathInputChanged();
    }
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    wizardAddExcludePath(rows[wizardState.excludeSuggestIndex]?.path || event.target.value);
  }
}

function wizardExcludePathsClick(event) {
  const remove = event.target.closest('[data-wiz-exclude-del]');
  if (remove) {
    const index = Number(remove.dataset.wizExcludeDel);
    if (index >= 0) wizardState.excludePaths.splice(index, 1);
    return wizardRenderExcludePaths();
  }
  const select = event.target.closest('[data-wiz-exclude-sel]');
  if (select) wizardAddExcludePath(wizardState.excludeSuggest[Number(select.dataset.wizExcludeSel)]?.path);
}

function wizardHideSourceSuggest() {
  const box = document.getElementById('wiz-source-path-suggest');
  if (!box) return;
  box.classList.add('hidden');
  box.innerHTML = '';
  wizardState.sourceSuggest = [];
  wizardState.sourceSuggestIndex = -1;
}

function wizardCancelSourceSuggestRequest() {
  if (wizardState.sourceSuggestTimer) {
    clearTimeout(wizardState.sourceSuggestTimer);
    wizardState.sourceSuggestTimer = null;
  }
  if (wizardState.sourceSuggestController) {
    wizardState.sourceSuggestController.abort();
    wizardState.sourceSuggestController = null;
  }
  wizardState.sourceSuggestRequest += 1;
}

function wizardRenderSourceSuggest() {
  const box = document.getElementById('wiz-source-path-suggest');
  const rows = wizardState.sourceSuggest || [];
  if (!box) return;
  if (!rows.length) {
    wizardHideSourceSuggest();
    return;
  }
  box.innerHTML = rows.map((r, idx) => `
    <button type="button" class="wizard-suggest-item ${idx === wizardState.sourceSuggestIndex ? 'active' : ''}" data-wiz-src-sel="${idx}">
      ${escHtml(r.path || '')}
    </button>
  `).join('');
  box.classList.remove('hidden');
  const activeEl = box.querySelector('.wizard-suggest-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function wizardIsAllowedSourcePath(path) {
  const v = String(path || '').trim();
  return v.startsWith('/mnt') || v.startsWith('/boot');
}

function wizardSourcePathInputChanged() {
  const input = document.getElementById('wiz-source-path-input');
  if (!input) return;
  const prefix = String(input.value || '').trim();
  wizardCancelSourceSuggestRequest();
  if (prefix.startsWith('/boot')) {
    // /boot is allowed as free text source path, but autocomplete remains /mnt-based.
    wizardHideSourceSuggest();
    return;
  }
  if (!prefix.startsWith('/mnt')) {
    wizardHideSourceSuggest();
    return;
  }
  const requestId = wizardState.sourceSuggestRequest;
  wizardState.sourceSuggestTimer = setTimeout(async () => {
    wizardState.sourceSuggestTimer = null;
    const controller = new AbortController();
    wizardState.sourceSuggestController = controller;
    try {
      const res = await fetch(`/api/wizard/source-dirs?prefix=${encodeURIComponent(prefix)}&limit=100`, {
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));
      if (requestId !== wizardState.sourceSuggestRequest) return;
      wizardState.sourceSuggest = Array.isArray(data?.dirs) ? data.dirs : [];
      wizardState.sourceSuggestIndex = wizardState.sourceSuggest.length ? 0 : -1;
      wizardRenderSourceSuggest();
    } catch (error) {
      if (error?.name !== 'AbortError' && requestId === wizardState.sourceSuggestRequest) {
        wizardHideSourceSuggest();
      }
    } finally {
      if (requestId === wizardState.sourceSuggestRequest) {
        wizardState.sourceSuggestController = null;
      }
    }
  }, 180);
}

function wizardAddSourcePath(value) {
  const v = String(value || '').trim();
  if (!v) return false;
  if (!wizardIsAllowedSourcePath(v)) return false;
  if ((wizardState.sourcePaths || []).includes(v)) return false;
  wizardCancelSourceSuggestRequest();
  wizardState.sourcePaths.push(v);
  wizardRenderSourcePaths();
  const input = document.getElementById('wiz-source-path-input');
  if (input) input.value = '';
  wizardHideSourceSuggest();
  return true;
}

function wizardSourcePathKeydown(event) {
  const rows = wizardState.sourceSuggest || [];
  if (event.key === 'ArrowDown' && rows.length) {
    event.preventDefault();
    wizardState.sourceSuggestIndex = (wizardState.sourceSuggestIndex + 1) % rows.length;
    wizardRenderSourceSuggest();
    return;
  }
  if (event.key === 'ArrowUp' && rows.length) {
    event.preventDefault();
    wizardState.sourceSuggestIndex = (wizardState.sourceSuggestIndex - 1 + rows.length) % rows.length;
    wizardRenderSourceSuggest();
    return;
  }
  if (event.key === 'ArrowRight' && rows.length) {
    const input = document.getElementById('wiz-source-path-input');
    const selected = rows[wizardState.sourceSuggestIndex]?.path;
    if (!input || !selected) return;
    event.preventDefault();
    input.value = selected;
    wizardHideSourceSuggest();
    wizardSourcePathInputChanged();
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    const input = document.getElementById('wiz-source-path-input');
    if (!input) return;
    const selected = rows[wizardState.sourceSuggestIndex]?.path;
    wizardAddSourcePath(selected || input.value);
  }
}

function wizardSourcePathsClick(event) {
  const delBtn = event.target.closest('[data-wiz-src-del]');
  if (delBtn) {
    const idx = parseInt(delBtn.dataset.wizSrcDel || '-1', 10);
    if (idx >= 0 && idx < (wizardState.sourcePaths || []).length) {
      wizardState.sourcePaths.splice(idx, 1);
      wizardRenderSourcePaths();
    }
    return;
  }
  const selBtn = event.target.closest('[data-wiz-src-sel]');
  if (selBtn) {
    const idx = parseInt(selBtn.dataset.wizSrcSel || '-1', 10);
    const row = wizardState.sourceSuggest[idx];
    if (row?.path) wizardAddSourcePath(row.path);
  }
}

function _wizardValidate(step) {
  wizardClearError(step);
  const p = _wizardCollectParams();
  if (step === 1) {
    if (!p.job_name) { _wizardShowError(1, wizardT('wizard.validationJobName')); return false; }
    if (!p.type_id)  { _wizardShowError(1, wizardT('wizard.validationTypeId')); return false; }
    if (!/^[a-z0-9_]+$/.test(p.type_id)) {
      _wizardShowError(1, wizardT('wizard.validationTypeFormat'));
      return false;
    }
  }
  if (step === 2) {
    if (!p.source_paths) { _wizardShowError(2, wizardT('wizard.validationSource')); return false; }
    if (!p.storage_key) { _wizardShowError(2, wizardT('wizard.validationStorageTarget')); return false; }
    if (!p.repository_key) { _wizardShowError(2, wizardT('wizard.validationRepositorySelect')); return false; }
  }
  if (step === 3) {
    if (p.docker_control.mode === 'selected' && !p.docker_control.selected.length) {
      _wizardShowError(3, wizardT('wizard.validationDockerSelection'));
      return false;
    }
    if (_wizardHasExactSourcePath('/mnt/user/appdata') && p.docker_control.mode !== 'all' && !p.docker_control.ack_appdata_risk) {
      _wizardFocusRuntimeRisk('wiz-appdata-risk');
      return false;
    }
  }
  if (step === 4) {
    if (p.vm_control.mode === 'selected' && !p.vm_control.selected.length) {
      _wizardShowError(4, wizardT('wizard.validationVmSelection'));
      return false;
    }
    if (_wizardHasExactSourcePath('/mnt/user/domains') && p.vm_control.mode !== 'all' && !p.vm_control.ack_domains_risk) {
      _wizardFocusRuntimeRisk('wiz-domains-risk');
      return false;
    }
  }
  return true;
}

async function wizardNext() {
  const cur = wizardState.step;
  if (!_wizardValidate(cur)) return;
  if (cur < 8) {
    const next = _wizardNextStepFrom(cur);
    wizardState.unlockedStep = Math.max(Number(wizardState.unlockedStep || 1), next);
    _renderWizardStep(next);
    return;
  }
  // Step 8 -> 9: load preview
  wizardState.unlockedStep = 9;
  _renderWizardStep(9);
  await _wizardPreview();
}

function wizardBack() {
  const cur = wizardState.step;
  if (cur <= 1) return;
  _renderWizardStep(_wizardPreviousStepFrom(cur));
}

async function wizardGoToStep(target) {
  const next = Number(target || 0);
  const current = Number(wizardState.step || 1);
  if (!next || next === current || !_wizardStepEnabled(next)) return;
  if (next > Number(wizardState.unlockedStep || 1)) return;
  if (next > current) {
    let cursor = current;
    while (cursor < next) {
      if (!_wizardValidate(cursor)) {
        _renderWizardStep(cursor);
        return;
      }
      const following = _wizardNextStepFrom(cursor);
      if (following <= cursor) return;
      cursor = following;
    }
  }
  _renderWizardStep(next);
  if (next === 9) await _wizardPreview();
}

async function _wizardPreview() {
  const loading = document.getElementById('wizard-preview-loading');
  const wrap    = document.getElementById('wizard-preview-wrap');
  const errEl   = document.getElementById('wizard-error-9');
  const repoStatusEl = document.getElementById('wizard-remote-repo-status');
  loading.classList.remove('hidden');
  wrap.classList.add('hidden');
  errEl.classList.add('hidden');
  if (repoStatusEl) {
    repoStatusEl.className = 'status-message hidden';
    repoStatusEl.textContent = '';
  }

  const params = _wizardCollectParams();
  const modeInfoEl = document.getElementById('wizard-preview-mode-info');
  if (modeInfoEl) {
    modeInfoEl.textContent = wizardT('wizard.scriptlessInfo');
  }

  try {
    const res  = await fetch('/api/wizard/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));

    const flow = data.flow || {};
    const fallbackSteps = Array.isArray(flow.steps) ? flow.steps : [];
    const stepCodes = Array.isArray(flow.step_codes) ? flow.step_codes : [];
    const steps = stepCodes.length
      ? stepCodes.map((step, index) => {
        const code = String(step?.code || '').trim();
        if (!code) return fallbackSteps[index] || '-';
        const key = `wizard.flowSteps.${code}`;
        const translated = wizardT(key, step?.params || {});
        return translated === key ? (fallbackSteps[index] || code) : translated;
      })
      : fallbackSteps;
    const summary = flow.summary || {};
    const remoteRepo = flow.remote_repo && typeof flow.remote_repo === 'object' ? flow.remote_repo : null;
    wizardState.remoteRepoStatus = remoteRepo;
    const lines = [];
    lines.push(wizardT('wizard.previewJob', { value: flow.job_key || '-' }));
    lines.push(wizardT('wizard.previewLocation', { value: summary.location || '-' }));
    lines.push(wizardT('wizard.previewRepository', { value: summary.repo || '-' }));
    if (summary.location === 'storagebox' && remoteRepo) {
      const repoState = remoteRepo.exists
        ? wizardT('wizard.repoExists')
        : (remoteRepo.checked ? wizardT('wizard.repoUnavailable') : wizardT('wizard.repoUnchecked'));
      lines.push(wizardT('wizard.previewRepositoryStatus', {
        value: `${repoState} (${apiMessage(remoteRepo, repoState)})`,
      }));
    }
    lines.push(wizardT('wizard.previewEncryption', { value: summary.encryption || '-' }));
    lines.push(wizardT('wizard.previewSources', { value: summary.sources_count ?? '-' }));
    lines.push(wizardT('wizard.previewExclusions', {
      value: Array.isArray(summary.exclude_paths) && summary.exclude_paths.length ? summary.exclude_paths.join(', ') : wizardT('wizard.none'),
    }));
    lines.push(wizardT('wizard.previewFeatures', {
      docker: wizardT(summary.docker ? 'wizard.yes' : 'wizard.no'),
      vm: wizardT(summary.vm ? 'wizard.yes' : 'wizard.no'),
    }));
    lines.push(wizardT('wizard.previewDockerControl', { value: _wizardRuntimePreviewText('docker', summary) }));
    lines.push(wizardT('wizard.previewVmControl', { value: _wizardRuntimePreviewText('vm', summary) }));
    lines.push('');
    lines.push(wizardT('wizard.previewFlow'));
    steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));

    document.getElementById('wizard-preview-filename').textContent = flow.runner || 'scriptless-wizard-runner';
    document.getElementById('wizard-preview-code').textContent = lines.join('\n');
    if (repoStatusEl && summary.location === 'storagebox' && remoteRepo) {
      const repoState = remoteRepo.exists
        ? wizardT('wizard.remoteRepoExists')
        : (remoteRepo.checked ? wizardT('wizard.remoteRepoUnavailable') : wizardT('wizard.remoteRepoUnchecked'));
      repoStatusEl.className = `status-message ${remoteRepo.exists ? 'success-state' : 'warning-state'}`;
      repoStatusEl.textContent = `${repoState} ${apiMessage(remoteRepo, repoState)}`;
    } else if (repoStatusEl) {
      repoStatusEl.className = 'status-message hidden';
      repoStatusEl.textContent = '';
    }
    wrap.classList.remove('hidden');
  } catch (err) {
    wizardState.remoteRepoStatus = null;
    errEl.textContent = wizardT('wizard.previewError', { message: err.message });
    errEl.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
  }
}

function _wizardRuntimePreviewText(kind, summary) {
  const mode = String(summary?.[`${kind}_mode`] || 'none');
  if (mode === 'all') {
    return wizardT(kind === 'docker' ? 'wizard.runtimeAllDocker' : 'wizard.runtimeAllVms');
  }
  if (mode === 'selected') {
    const selected = Array.isArray(summary?.[`${kind}_selected`]) ? summary[`${kind}_selected`] : [];
    const label = wizardT(kind === 'docker' ? 'wizard.runtimeSelectedDocker' : 'wizard.runtimeSelectedVms');
    return `${label}: ${selected.length ? selected.join(', ') : '-'}`;
  }
  return wizardT('wizard.runtimeNone');
}

async function saveWizardJob() {
  const btn   = document.getElementById('wizard-save-btn');
  const errEl = document.getElementById('wizard-error-9');
  btn.classList.add('loading');
  errEl.classList.add('hidden');

  try {
    const params = _wizardCollectParams();
    const res  = await fetch('/api/wizard/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));

    // Save schedule changes and surface crontab/application failures.
    const schedEnabled = document.getElementById('wiz-sched-enabled').checked;
    if (schedEnabled || wizardState.originalSchedule) {
      const jobKey = `${params.type_id}_${params.location}`;
      const cron   = _wizardBuildCron();
      const sRes = await fetch('/api/schedules', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_key: jobKey, cron, enabled: schedEnabled }),
      });
      const sData = await sRes.json().catch(() => ({}));
      if (!sRes.ok) {
        throw new Error(wizardT('wizard.scheduleSaveError', {
          message: wizardApiErrorMessage(sData, sRes.status),
        }));
      }
      const schedules = window.BBUI.core.getSchedulesData();
      schedules[jobKey] = { cron, enabled: schedEnabled };
      window.BBUI.core.setSchedulesData(schedules);
    }

    closeWizard();
    jobsState.loaded = false;
    await refreshJobs();
    showMsg('jobs-message', 'success', wizardT('wizard.saved', { key: `${params.type_id}_${params.location}` }));
  } catch (err) {
    errEl.textContent = wizardT('wizard.saveError', { message: err.message });
    errEl.classList.remove('hidden');
  } finally {
    btn.classList.remove('loading');
  }
}

// ── Wizard Schedule Step ──────────────────────────────────────────────────────

window.BBUI.wizardSchedState = window.BBUI.wizardSchedState || { frequency: 'daily', dow: 1 };
const wizardSchedState = window.BBUI.wizardSchedState;

function _wizardApplySchedule(schedule) {
  const data = schedule && typeof schedule === 'object' ? schedule : null;
  const cron = String(data?.cron || '0 3 * * *').trim();
  document.getElementById('wiz-sched-enabled').checked = !!data?.enabled;
  document.getElementById('wiz-sched-cron-custom').value = cron;
  const parts = cron.split(/\s+/);
  let frequency = 'custom';
  if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
    document.getElementById('wiz-sched-minute').value = Number(parts[0]);
    document.getElementById('wiz-sched-hour').value = Number(parts[1]);
    if (parts[2] === '*' && parts[3] === '*' && parts[4] === '*') frequency = 'daily';
    else if (parts[2] === '*' && parts[3] === '*' && /^[0-6]$/.test(parts[4])) {
      frequency = 'weekly';
      wizardSchedState.dow = Number(parts[4]);
    } else if (/^(?:[1-9]|1\d|2[0-8])$/.test(parts[2]) && parts[3] === '*' && parts[4] === '*') {
      frequency = 'monthly';
      document.getElementById('wiz-sched-dom').value = Number(parts[2]);
    }
  }
  wizardSchedState.frequency = frequency;
  _wizardScheduleApplyUI(frequency);
  document.querySelectorAll('[data-wiz-dow]').forEach((button) => {
    button.classList.toggle('active', Number(button.dataset.wizDow) === wizardSchedState.dow);
  });
  wizardSchedulePreview();
}

function _wizardScheduleApplyUI(freq) {
  document.querySelectorAll('[data-wiz-freq]').forEach(b =>
    b.classList.toggle('active', b.dataset.wizFreq === freq));
  document.getElementById('wiz-sched-time-row').classList.toggle('hidden', freq === 'custom');
  document.getElementById('wiz-sched-dow-row').classList.toggle('hidden', freq !== 'weekly');
  document.getElementById('wiz-sched-dom-row').classList.toggle('hidden', freq !== 'monthly');
  document.getElementById('wiz-sched-custom-row').classList.toggle('hidden', freq !== 'custom');
}

function wizardScheduleFreq(freq) {
  wizardSchedState.frequency = freq;
  _wizardScheduleApplyUI(freq);
  if (freq !== 'custom') wizardSchedulePreview();
}

function wizardScheduleSelectDow(dow) {
  wizardSchedState.dow = dow;
  document.querySelectorAll('[data-wiz-dow]').forEach(b =>
    b.classList.toggle('active', parseInt(b.dataset.wizDow, 10) === dow));
  wizardSchedulePreview();
}

function _wizardBuildCron() {
  const freq   = wizardSchedState.frequency;
  const hour   = parseInt(document.getElementById('wiz-sched-hour').value, 10)   || 0;
  const minute = parseInt(document.getElementById('wiz-sched-minute').value, 10) || 0;
  const dom    = parseInt(document.getElementById('wiz-sched-dom').value, 10)    || 1;
  const dow    = wizardSchedState.dow;
  const h = Math.min(23, Math.max(0, hour));
  const m = Math.min(59, Math.max(0, minute));
  const d = Math.min(28, Math.max(1, dom));
  if (freq === 'daily')   return `${m} ${h} * * *`;
  if (freq === 'weekly')  return `${m} ${h} * * ${dow}`;
  if (freq === 'monthly') return `${m} ${h} ${d} * *`;
  return document.getElementById('wiz-sched-cron-custom').value.trim();
}

function wizardSchedulePreview() {
  const cron = _wizardBuildCron();
  const next = calcNextRun(cron);
  const el   = document.getElementById('wiz-sched-next-run-text');
  if (!el) return;
  el.textContent = next
    ? wizardT('schedule.nextRun', { date: fmtDateShort(next) })
    : (cron ? wizardT('schedule.invalid') : '—');
}

window.addEventListener?.('bbui:language-changed', () => {
  const title = document.getElementById('wizard-modal-title');
  if (title) {
    const titleKey = wizardState.mode === 'edit' ? 'wizard.editTitle' : 'wizard.newTitle';
    title.textContent = wizardT(titleKey);
  }
  wizardSetStorageOptions();
  wizardRenderSourcePaths();
  wizardRenderExcludePaths();
  wizardUpdateIconPreview();
  wizardAutoFill();
  wizardRenderRuntimeControls();
  wizardSchedulePreview();
});

function openWizardDescriptionHelp() {
  document.getElementById('wizard-help-modal')?.classList.remove('hidden');
}

function closeWizardDescriptionHelp() {
  document.getElementById('wizard-help-modal')?.classList.add('hidden');
}
