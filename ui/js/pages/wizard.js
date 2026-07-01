// JOB WIZARD
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.wizardState = window.BBUI.wizardState || {
  step: 1,
  passphraseExists: false,
  keepPassphrase: false,
  mode: 'create',
  existingJobKey: '',
  original: null,
  storageProfiles: [],
  selectedStorageProfileKey: '',
  usbProfiles: [],
  smbProfiles: [],
  selectedUsbProfileKey: '',
  selectedSmbProfileKey: '',
  sourcePaths: [],
  sourceSuggest: [],
  sourceSuggestIndex: -1,
  scrollHintBound: false,
  remoteRepoStatus: null,
  dockerContainers: [],
  vms: [],
  selectedDockerContainers: [],
  selectedVms: [],
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

function wizardUpdateStep2ScrollHint() {
  const modal = document.getElementById('wizard-modal');
  const body = modal?.querySelector('.wizard-body');
  const hint = modal?.querySelector('#wizard-step-2 .wizard-step-scroll-hint');
  const step2Visible = !document.getElementById('wizard-step-2')?.classList.contains('hidden');
  if (!body || !hint || !step2Visible) {
    if (hint) hint.classList.add('hidden');
    return;
  }
  const remaining = body.scrollHeight - (body.scrollTop + body.clientHeight);
  hint.classList.toggle('hidden', remaining <= 2);
}

function wizardEnsureScrollHintBinding() {
  if (wizardState.scrollHintBound) return;
  const modal = document.getElementById('wizard-modal');
  const body = modal?.querySelector('.wizard-body');
  if (!body) return;
  body.addEventListener('scroll', wizardUpdateStep2ScrollHint);
  wizardState.scrollHintBound = true;
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

async function wizardLoadStorageboxProfile() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const data = await res.json();
    const setup = data?.storagebox_setup || {};
    const rows = Array.isArray(data?.storage_profiles) ? data.storage_profiles : [];
    wizardState.storageProfiles = rows
      .map((r, idx) => ({
        key: String(r?.key || `storage-${idx + 1}`).trim(),
        name: String(r?.name || '').trim(),
        host: String(r?.host || '').trim(),
        port: String(r?.port || '23').trim() || '23',
        user: String(r?.user || '').trim(),
        base_path: String(r?.base_path || '/./backup').trim() || '/./backup',
        auth_ok: !!setup.auth_ok,
        setup_message: String(setup.message || '').trim(),
      }))
      .filter((r) => r.key && r.host && r.user && r.base_path);
    if (!wizardState.selectedStorageProfileKey) {
      wizardState.selectedStorageProfileKey = wizardState.storageProfiles[0]?.key || '';
    }
  } catch (_) {}
  wizardSetStorageProfileOptions();
}

function wizardStorageRepoBasePathForUri(rawBasePath) {
  let basePath = String(rawBasePath || '/./backup').trim() || '/./backup';
  if (basePath.startsWith('./')) {
    basePath = `/${basePath}`;
  } else if (!basePath.startsWith('/')) {
    basePath = `/${basePath}`;
  }
  if (basePath !== '/') {
    basePath = basePath.replace(/\/+$/, '');
  }
  return basePath || '/./backup';
}

function wizardSetUsbProfileOptions() {
  const sel = document.getElementById('wiz-usb-profile');
  if (!sel) return;
  const rows = Array.isArray(wizardState.usbProfiles) ? wizardState.usbProfiles : [];
  sel.innerHTML = rows.length
    ? rows.map((p) => `<option value="${escHtml(p.key || '')}">${escHtml(p.name || p.mount_path || '')} — ${escHtml(p.mount_path || '')}</option>`).join('')
    : `<option value="">${wizardT('wizard.noUsbProfile')}</option>`;
  if (rows.length) {
    const wanted = wizardState.selectedUsbProfileKey || rows[0].key;
    const found = rows.find((p) => String(p.key) === String(wanted));
    sel.value = found ? found.key : rows[0].key;
    wizardState.selectedUsbProfileKey = sel.value;
  } else {
    sel.value = '';
    wizardState.selectedUsbProfileKey = '';
  }
}

function wizardSetSmbProfileOptions() {
  const sel = document.getElementById('wiz-smb-profile');
  if (!sel) return;
  const rows = Array.isArray(wizardState.smbProfiles) ? wizardState.smbProfiles : [];
  sel.innerHTML = rows.length
    ? rows.map((p) => `<option value="${escHtml(p.key || '')}">${escHtml(p.name || p.mount_path || '')} — ${escHtml(p.server || '')}/${escHtml(p.share || '')}</option>`).join('')
    : `<option value="">${wizardT('wizard.noSmbProfile')}</option>`;
  if (rows.length) {
    const wanted = wizardState.selectedSmbProfileKey || rows[0].key;
    const found = rows.find((p) => String(p.key) === String(wanted));
    sel.value = found ? found.key : rows[0].key;
    wizardState.selectedSmbProfileKey = sel.value;
  } else {
    sel.value = '';
    wizardState.selectedSmbProfileKey = '';
  }
}

function wizardSetStorageProfileOptions() {
  const sel = document.getElementById('wiz-storage-profile');
  if (!sel) return;
  const rows = Array.isArray(wizardState.storageProfiles) ? wizardState.storageProfiles : [];
  sel.innerHTML = rows.length
    ? rows.map((p) => `<option value="${escHtml(p.key || '')}">${escHtml(p.name || p.host || '')} — ${escHtml(p.user || '')}@${escHtml(p.host || '')}:${escHtml(p.port || '23')}</option>`).join('')
    : `<option value="">${wizardT('wizard.noStorageProfile')}</option>`;
  if (rows.length) {
    const wanted = wizardState.selectedStorageProfileKey || rows[0].key;
    const found = rows.find((p) => String(p.key) === String(wanted));
    sel.value = found ? found.key : rows[0].key;
    wizardState.selectedStorageProfileKey = sel.value;
  } else {
    sel.value = '';
    wizardState.selectedStorageProfileKey = '';
  }
}

async function wizardLoadUsbProfiles() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const data = await res.json();
    const rows = Array.isArray(data?.usb_profiles) ? data.usb_profiles : [];
    wizardState.usbProfiles = rows
      .map((r, idx) => ({
        key: String(r?.key || `usb-${idx + 1}`).trim(),
        name: String(r?.name || '').trim(),
        mount_path: String(r?.mount_path || '').trim(),
      }))
      .filter((r) => r.key && r.mount_path);
  } catch (_) {
    wizardState.usbProfiles = [];
  }
  wizardSetUsbProfileOptions();
}

async function wizardLoadSmbProfiles() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const data = await res.json();
    const rows = Array.isArray(data?.smb_profiles) ? data.smb_profiles : [];
    wizardState.smbProfiles = rows
      .map((r, idx) => ({
        key: String(r?.key || `smb-${idx + 1}`).trim(),
        name: String(r?.name || '').trim(),
        server: String(r?.server || '').trim(),
        share: String(r?.share || '').trim(),
        mount_path: String(r?.mount_path || '').trim(),
      }))
      .filter((r) => r.key && r.mount_path);
  } catch (_) {
    wizardState.smbProfiles = [];
  }
  wizardSetSmbProfileOptions();
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
  wizardEnsureScrollHintBinding();
  wizardBindRuntimeControls();
  wizardState.mode = 'create';
  wizardState.existingJobKey = '';
  wizardState.original = null;
  wizardState.step = 1;
  const title = document.getElementById('wizard-modal-title');
  if (title) title.textContent = wizardT('wizard.newTitle');
  document.getElementById('wiz-job-name').value = '';
  document.getElementById('wiz-type-id').value = '';
  document.getElementById('wiz-icon').value = '';
  document.getElementById('wiz-icon-color').value = '';
  document.getElementById('wiz-description').value = '';
  document.getElementById('wiz-location').value = 'local';
  wizardState.selectedUsbProfileKey = '';
  wizardState.selectedSmbProfileKey = '';
  wizardState.selectedStorageProfileKey = '';
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
  wizardState.sourcePaths = [];
  wizardState.sourceSuggest = [];
  wizardState.sourceSuggestIndex = -1;
  wizardRenderSourcePaths();
  document.getElementById('wiz-repo-path').value = '';
  document.getElementById('wiz-repo-path').readOnly = false;
  document.getElementById('wiz-compression').value = 'lz4';
  document.getElementById('wiz-encryption').value = 'repokey-blake2';
  document.getElementById('wiz-keep-daily').value = '7';
  document.getElementById('wiz-keep-weekly').value = '4';
  document.getElementById('wiz-keep-monthly').value = '6';
  document.getElementById('wiz-keep-yearly').value = '3';
  wizardState.passphraseExists = false;
  wizardState.keepPassphrase = false;
  document.getElementById('wiz-passphrase').value = '';
  document.getElementById('wiz-passphrase-toggle').textContent = wizardT('wizard.show');
  document.getElementById('wiz-passphrase').type = 'password';
  document.getElementById('wiz-copy-btn').disabled = true;
  document.getElementById('wizard-passphrase-conflict').classList.add('hidden');
  document.getElementById('wizard-passphrase-replace-warning').classList.add('hidden');
  document.getElementById('wizard-passphrase-form').classList.remove('hidden');
  document.getElementById('wizard-preview-wrap').classList.add('hidden');
  document.getElementById('wizard-preview-loading').classList.add('hidden');
  const remoteConfirmWrap = document.getElementById('wizard-remote-init-confirm-wrap');
  const remoteConfirm = document.getElementById('wiz-remote-init-confirm');
  if (remoteConfirmWrap) remoteConfirmWrap.classList.add('hidden');
  if (remoteConfirm) remoteConfirm.checked = false;
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
  Promise.all([wizardLoadStorageboxProfile(), wizardLoadUsbProfiles(), wizardLoadSmbProfiles(), wizardLoadRuntimeInventory()]).finally(() => wizardAutoFill());
  [1,2,3,4,5,6,7,8,9].forEach(n => wizardClearError(n));
  wizardRenderRuntimeControls();
  _renderWizardStep(1);
  document.getElementById('wizard-modal').classList.remove('hidden');
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
  document.getElementById('wiz-repo-path').value = job.repo_path || '';
  const smbMountBefore = document.getElementById('wiz-smb-mount-before-run');
  const smbUnmountAfter = document.getElementById('wiz-smb-unmount-after-run');
  if (smbMountBefore) smbMountBefore.checked = job.mount_before_run !== false;
  if (smbUnmountAfter) smbUnmountAfter.checked = job.unmount_after_run !== false;
  const metaUsbKey = String(job.usb_profile_key || '').trim();
  const metaSmbKey = String(job.smb_profile_key || '').trim();
  const metaStorageKey = String(job.storage_profile_key || '').trim();
  if (metaUsbKey) wizardState.selectedUsbProfileKey = metaUsbKey;
  if (metaSmbKey) wizardState.selectedSmbProfileKey = metaSmbKey;
  if (metaStorageKey) wizardState.selectedStorageProfileKey = metaStorageKey;
  if ((job.location || 'local') === 'usb') {
    const repoPath = String(job.repo_path || '');
    let hit = (wizardState.usbProfiles || []).find((p) => String(p.key) === String(metaUsbKey));
    if (!hit) {
      hit = (wizardState.usbProfiles || []).find((p) => {
        const mp = String(p.mount_path || '').replace(/\/+$/, '');
        return mp && repoPath.startsWith(`${mp}/`);
      });
    }
    if (hit) {
      wizardState.selectedUsbProfileKey = hit.key;
      const usbSel = document.getElementById('wiz-usb-profile');
      if (usbSel) usbSel.value = hit.key;
    }
  }
  if ((job.location || 'local') === 'smb') {
    const repoPath = String(job.repo_path || '');
    let hit = (wizardState.smbProfiles || []).find((p) => String(p.key) === String(metaSmbKey));
    if (!hit) {
      hit = (wizardState.smbProfiles || []).find((p) => {
        const mp = String(p.mount_path || '').replace(/\/+$/, '');
        return mp && repoPath.startsWith(`${mp}/`);
      });
    }
    if (hit) {
      wizardState.selectedSmbProfileKey = hit.key;
      const smbSel = document.getElementById('wiz-smb-profile');
      if (smbSel) smbSel.value = hit.key;
    }
  }
  if ((job.location || 'local') === 'storagebox') {
    const hit = (wizardState.storageProfiles || []).find((p) => String(p.key) === String(metaStorageKey));
    if (hit) wizardState.selectedStorageProfileKey = hit.key;
  }
  document.getElementById('wiz-compression').value = job.compression || 'lz4';
  document.getElementById('wiz-encryption').value = job.encryption || 'repokey-blake2';
  document.getElementById('wiz-keep-daily').value = job.keep_daily || '7';
  document.getElementById('wiz-keep-weekly').value = job.keep_weekly || '4';
  document.getElementById('wiz-keep-monthly').value = job.keep_monthly || '6';
  document.getElementById('wiz-keep-yearly').value = job.keep_yearly || '3';
  wizardUpdateIconPreview();
  wizardAutoFill();
}

async function openWizardForJob(jobKey, mode = 'edit') {
  openWizard();
  wizardState.mode = mode;
  wizardState.existingJobKey = jobKey;
  const title = document.getElementById('wizard-modal-title');
  if (title) title.textContent = wizardT(mode === 'adopt' ? 'wizard.adoptTitle' : 'wizard.editTitle');
  _setWizardFormDisabled(true);
  try {
    const res = await fetch(`/api/wizard/job?job_key=${encodeURIComponent(jobKey)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));
    const job = data.job || {};
    _wizardFillFromJob(job);
    wizardState.original = {
      type_id: (job.type_id || '').toLowerCase(),
      location: job.location || 'local',
      use_docker: !!job.use_docker,
      use_vm: !!job.use_vm,
      docker_control: job.docker_control || { mode: job.use_docker ? 'all' : 'none', selected: [] },
      vm_control: job.vm_control || { mode: job.use_vm ? 'all' : 'none', selected: [] },
    };
    // In edit/adopt default to existing passphrase handling.
    wizardState.keepPassphrase = true;
    document.getElementById('wizard-passphrase-conflict').classList.add('hidden');
    document.getElementById('wizard-passphrase-replace-warning').classList.add('hidden');
    document.getElementById('wizard-passphrase-keep-confirm').classList.add('hidden');
    document.getElementById('wizard-passphrase-form').classList.add('hidden');
  } catch (err) {
    closeWizard();
    showMsg('jobs-message', 'error', wizardT('wizard.loadFailed', { message: err.message }));
  } finally {
    _setWizardFormDisabled(false);
  }
}

function wizardNeedsScriptRegeneration(params) {
  if ((wizardState.mode || 'create') === 'create') return true;
  const orig = wizardState.original;
  if (!orig) return true;
  if (params.type_id !== orig.type_id) return true;
  if (params.location !== orig.location) return true;
  if (!!params.use_docker !== !!orig.use_docker) return true;
  if (!!params.use_vm !== !!orig.use_vm) return true;
  if (JSON.stringify(params.docker_control || {}) !== JSON.stringify(orig.docker_control || {})) return true;
  if (JSON.stringify(params.vm_control || {}) !== JSON.stringify(orig.vm_control || {})) return true;
  return false;
}

function adoptLegacyJob(jobKey) {
  return openWizardForJob(jobKey, 'adopt');
}

function closeWizard() {
  document.getElementById('wizard-modal').classList.add('hidden');
}

function _renderWizardStep(n) {
  [1,2,3,4,5,6,7,8,9].forEach(i => {
    document.getElementById(`wizard-step-${i}`).classList.toggle('hidden', i !== n);
    const dot = document.getElementById(`wstep-dot-${i}`);
    if (dot) dot.classList.toggle('active', i <= n);
  });
  const backBtn = document.getElementById('wizard-back-btn');
  const nextBtn = document.getElementById('wizard-next-btn');
  const saveBtn = document.getElementById('wizard-save-btn');
  backBtn.style.display = n > 1 ? '' : 'none';
  nextBtn.classList.toggle('hidden', n === 9);
  saveBtn.classList.toggle('hidden', n !== 9);
  wizardState.step = n;
  requestAnimationFrame(wizardUpdateStep2ScrollHint);
}

function _wizardStepEnabled(step) {
  if (step === 3) return _wizardRuntimeMode('docker') !== 'none';
  if (step === 4) return _wizardRuntimeMode('vm') !== 'none';
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
  const typeId   = (document.getElementById('wiz-type-id').value || '').trim().toLowerCase();
  const location = document.getElementById('wiz-location').value;
  const iconEl = document.getElementById('wiz-icon');
  const repoEl = document.getElementById('wiz-repo-path');
  const hintEl = document.getElementById('wiz-storagebox-profile-hint');
  const usbGroupEl = document.getElementById('wiz-usb-profile-group');
  const usbSel = document.getElementById('wiz-usb-profile');
  const usbHintEl = document.getElementById('wiz-usb-profile-hint');
  const smbGroupEl = document.getElementById('wiz-smb-profile-group');
  const storageGroupEl = document.getElementById('wiz-storage-profile-group');
  const smbMountOptionsEl = document.getElementById('wiz-smb-mount-options-group');
  const smbSel = document.getElementById('wiz-smb-profile');
  const smbHintEl = document.getElementById('wiz-smb-profile-hint');
  const storageSel = document.getElementById('wiz-storage-profile');
  const storageHintEl = document.getElementById('wiz-storage-profile-hint');
  if (!typeId) return;
  if (!repoEl) return;
  if (usbGroupEl) usbGroupEl.classList.toggle('hidden', location !== 'usb');
  if (smbGroupEl) smbGroupEl.classList.toggle('hidden', location !== 'smb');
  if (storageGroupEl) storageGroupEl.classList.toggle('hidden', location !== 'storagebox');
  if (smbMountOptionsEl) smbMountOptionsEl.classList.toggle('hidden', location !== 'smb');

  if (location === 'storagebox') {
    const rows = Array.isArray(wizardState.storageProfiles) ? wizardState.storageProfiles : [];
    const chosen = rows.find((p) => String(p.key) === String(storageSel?.value || wizardState.selectedStorageProfileKey)) || rows[0] || {};
    if (chosen?.key) wizardState.selectedStorageProfileKey = chosen.key;
    if (storageSel && storageSel.value !== wizardState.selectedStorageProfileKey) {
      storageSel.value = wizardState.selectedStorageProfileKey;
    }
    const profile = chosen;
    const host = String(profile.host || '').trim();
    const port = String(profile.port || '23').trim() || '23';
    const user = String(profile.user || '').trim();
    const basePath = wizardStorageRepoBasePathForUri(profile.base_path);
    const complete = !!(host && user && basePath);

    repoEl.readOnly = true;
    if (hintEl) {
      hintEl.classList.remove('hidden');
      hintEl.textContent = complete
        ? wizardT('wizard.activeStorageProfile', {
          name: profile.name || profile.key || 'Storagebox',
          target: `${user}@${host}:${port}${basePath}`,
          status: profile.auth_ok ? ' (SSH ok)' : (profile.setup_message ? ` — ${profile.setup_message}` : ''),
        })
        : wizardT('wizard.storageProfileIncomplete');
    }
    if (storageHintEl) {
      storageHintEl.classList.remove('hidden');
      storageHintEl.textContent = complete
        ? `${profile.name || profile.key || 'Storagebox'} (${user}@${host}:${port})`
        : wizardT('wizard.selectedProfileIncomplete');
    }

    // Storagebox repo path is managed centrally by profile settings.
    // Always rebuild it here so UI + saved metadata stay consistent.
    repoEl.value = complete
      ? `ssh://${user}@${host}:${port}${basePath}/borg-backup-${typeId}`
      : `ssh://<user>@<host>:${port}${basePath}/borg-backup-${typeId}`;
    repoEl.dataset.autofilled = 'true';
  } else {
    repoEl.readOnly = location === 'usb';
    if (hintEl) hintEl.classList.add('hidden');
    if (storageHintEl) storageHintEl.classList.add('hidden');
    if (location === 'usb') {
      const rows = Array.isArray(wizardState.usbProfiles) ? wizardState.usbProfiles : [];
      if (usbSel && rows.length) {
        const chosen = rows.find((p) => p.key === (usbSel.value || wizardState.selectedUsbProfileKey));
        if (chosen) wizardState.selectedUsbProfileKey = chosen.key;
        const active = chosen || rows[0];
        if (usbSel.value !== active.key) usbSel.value = active.key;
        if (usbHintEl) {
          usbHintEl.classList.remove('status-message', 'warning-state');
          usbHintEl.classList.add('form-hint');
          usbHintEl.classList.remove('hidden');
          usbHintEl.textContent = wizardT('wizard.activeUsbProfile', {
            name: active.name || active.key,
            path: active.mount_path,
          });
        }
        repoEl.value = `${active.mount_path.replace(/\/+$/, '')}/borg-backup-${typeId}`;
        repoEl.dataset.autofilled = 'true';
      } else {
        if (usbHintEl) {
          usbHintEl.classList.remove('form-hint');
          usbHintEl.classList.add('status-message', 'warning-state');
          usbHintEl.classList.remove('hidden');
          usbHintEl.textContent = wizardT('wizard.usbProfileRequired');
        }
        repoEl.value = '';
        repoEl.dataset.autofilled = 'true';
      }
    } else if (location === 'smb') {
      const rows = Array.isArray(wizardState.smbProfiles) ? wizardState.smbProfiles : [];
      repoEl.readOnly = true;
      if (smbSel && rows.length) {
        const chosen = rows.find((p) => p.key === (smbSel.value || wizardState.selectedSmbProfileKey));
        if (chosen) wizardState.selectedSmbProfileKey = chosen.key;
        const active = chosen || rows[0];
        if (smbSel.value !== active.key) smbSel.value = active.key;
        if (smbHintEl) {
          smbHintEl.classList.remove('status-message', 'warning-state');
          smbHintEl.classList.add('form-hint');
          smbHintEl.classList.remove('hidden');
          smbHintEl.textContent = wizardT('wizard.activeSmbProfile', {
            name: active.name || active.key,
            target: `${active.server}/${active.share}`,
          });
        }
        repoEl.value = `${active.mount_path.replace(/\/+$/, '')}/borg-backup-${typeId}`;
        repoEl.dataset.autofilled = 'true';
      } else {
        if (smbHintEl) {
          smbHintEl.classList.remove('form-hint');
          smbHintEl.classList.add('status-message', 'warning-state');
          smbHintEl.classList.remove('hidden');
          smbHintEl.textContent = wizardT('wizard.smbProfileRequired');
        }
        repoEl.value = '';
        repoEl.dataset.autofilled = 'true';
      }
    } else {
      if (smbHintEl) {
        smbHintEl.classList.remove('status-message', 'warning-state');
        smbHintEl.classList.add('form-hint');
        smbHintEl.classList.add('hidden');
      }
      if (usbHintEl) {
        usbHintEl.classList.remove('status-message', 'warning-state');
        usbHintEl.classList.add('form-hint');
        usbHintEl.classList.add('hidden');
      }
      if (!repoEl.value || repoEl.dataset.autofilled === 'true') {
        const prefix = '/mnt/backup';
        repoEl.value = `${prefix}/borg-backup-${typeId}`;
        repoEl.dataset.autofilled = 'true';
      }
    }
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
  const storageProfileKey = (document.getElementById('wiz-storage-profile')?.value || wizardState.selectedStorageProfileKey || '').trim();
  wizardState.selectedStorageProfileKey = storageProfileKey;
  const dockerMode = _wizardRuntimeMode('docker');
  const vmMode = _wizardRuntimeMode('vm');
  return {
    type_id:      (document.getElementById('wiz-type-id').value || '').trim().toLowerCase(),
    icon:         (document.getElementById('wiz-icon').value || '').trim().toLowerCase(),
    icon_color:   (document.getElementById('wiz-icon-color').value || '').trim().toLowerCase(),
    job_name:     (document.getElementById('wiz-job-name').value || '').trim(),
    description:  (document.getElementById('wiz-description').value || '').trim(),
    location:     document.getElementById('wiz-location').value,
    storage_profile_key: storageProfileKey,
    usb_profile_key: (document.getElementById('wiz-usb-profile')?.value || '').trim(),
    smb_profile_key: (document.getElementById('wiz-smb-profile')?.value || '').trim(),
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
    repo_path:    (document.getElementById('wiz-repo-path').value || '').trim(),
    compression:  document.getElementById('wiz-compression').value,
    encryption:   document.getElementById('wiz-encryption').value,
    passphrase:   wizardState.keepPassphrase ? '' : (document.getElementById('wiz-passphrase').value || '').trim(),
    keep_daily:   document.getElementById('wiz-keep-daily').value,
    keep_weekly:  document.getElementById('wiz-keep-weekly').value,
    keep_monthly: document.getElementById('wiz-keep-monthly').value,
    keep_yearly:  document.getElementById('wiz-keep-yearly').value,
    _wizard_mode: wizardState.mode || 'create',
    existing_job_key: wizardState.existingJobKey || '',
    remote_init_confirmed: !!document.getElementById('wiz-remote-init-confirm')?.checked,
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

function wizardHideSourceSuggest() {
  const box = document.getElementById('wiz-source-path-suggest');
  if (!box) return;
  box.classList.add('hidden');
  box.innerHTML = '';
  wizardState.sourceSuggest = [];
  wizardState.sourceSuggestIndex = -1;
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

async function wizardSourcePathInputChanged() {
  const input = document.getElementById('wiz-source-path-input');
  if (!input) return;
  const prefix = String(input.value || '').trim();
  if (prefix.startsWith('/boot')) {
    // /boot is allowed as free text source path, but autocomplete remains /mnt-based.
    wizardHideSourceSuggest();
    return;
  }
  if (!prefix.startsWith('/mnt')) {
    wizardHideSourceSuggest();
    return;
  }
  try {
    const res = await fetch(`/api/wizard/source-dirs?prefix=${encodeURIComponent(prefix)}&limit=100`);
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));
    wizardState.sourceSuggest = Array.isArray(data?.dirs) ? data.dirs : [];
    wizardState.sourceSuggestIndex = wizardState.sourceSuggest.length ? 0 : -1;
    wizardRenderSourceSuggest();
  } catch (_) {
    wizardHideSourceSuggest();
  }
}

function wizardAddSourcePath(value) {
  const v = String(value || '').trim();
  if (!v) return false;
  if (!wizardIsAllowedSourcePath(v)) return false;
  if ((wizardState.sourcePaths || []).includes(v)) return false;
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
    if (!p.repo_path)    { _wizardShowError(2, wizardT('wizard.validationRepository')); return false; }
    if (p.location === 'usb') {
      const rows = Array.isArray(wizardState.usbProfiles) ? wizardState.usbProfiles : [];
      if (!rows.length) {
        _wizardShowError(2, wizardT('wizard.usbProfileRequired'));
        return false;
      }
    }
    if (p.location === 'smb') {
      const rows = Array.isArray(wizardState.smbProfiles) ? wizardState.smbProfiles : [];
      if (!rows.length) {
        _wizardShowError(2, wizardT('wizard.smbProfileRequired'));
        return false;
      }
      if (!p.smb_profile_key) {
        _wizardShowError(2, wizardT('wizard.validationSelectSmb'));
        return false;
      }
    }
    if (p.location === 'storagebox') {
      const rows = Array.isArray(wizardState.storageProfiles) ? wizardState.storageProfiles : [];
      if (!rows.length) {
        _wizardShowError(2, wizardT('wizard.validationStorageRequired'));
        return false;
      }
      if (!p.storage_profile_key) {
        _wizardShowError(2, wizardT('wizard.validationSelectStorage'));
        return false;
      }
    }
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
  if (step === 6) {
    if (p.encryption !== 'none' && !wizardState.keepPassphrase && !p.passphrase) {
      _wizardShowError(6, wizardT('wizard.validationPassphrase'));
      return false;
    }
  }
  return true;
}

async function wizardNext() {
  const cur = wizardState.step;
  if (!_wizardValidate(cur)) return;
  const enc = document.getElementById('wiz-encryption').value;
  const params = _wizardCollectParams();
  const isEditLikeNoRegeneration =
    wizardState.mode !== 'create' &&
    wizardState.mode !== 'adopt' &&
    !wizardNeedsScriptRegeneration(params);
  // skip passphrase step when no encryption
  if (cur === 5 && (enc === 'none' || isEditLikeNoRegeneration)) {
    _renderWizardStep(7);
    return;
  }
  // step 5 -> 6: check if passphrase file already exists
  if (cur === 5 && enc !== 'none') {
    await _wizardCheckPassphrase();
    _renderWizardStep(6);
    return;
  }
  if (cur < 8) {
    _renderWizardStep(_wizardNextStepFrom(cur));
    return;
  }
  // Step 8 -> 9: load preview
  _renderWizardStep(9);
  await _wizardPreview();
}

async function _wizardCheckPassphrase() {
  const typeId = (document.getElementById('wiz-type-id').value || '').trim().toLowerCase();
  wizardState.passphraseExists = false;
  wizardState.keepPassphrase = false;
  document.getElementById('wizard-passphrase-conflict').classList.add('hidden');
  document.getElementById('wizard-passphrase-replace-warning').classList.add('hidden');
  document.getElementById('wizard-passphrase-keep-confirm').classList.add('hidden');
  document.getElementById('wizard-passphrase-form').classList.remove('hidden');
  if (!typeId) return;
  try {
    const location = (document.getElementById('wiz-location').value || '').trim().toLowerCase();
    const res  = await fetch(`/api/wizard/passphrase-check?type_id=${encodeURIComponent(typeId)}&location=${encodeURIComponent(location)}`);
    const data = await res.json();
    if (data.exists) {
      wizardState.passphraseExists = true;
      wizardState.keepPassphrase = true;
      document.getElementById('wizard-passphrase-conflict-path').textContent = data.path;
      document.getElementById('wizard-passphrase-conflict').classList.remove('hidden');
      document.getElementById('wizard-passphrase-form').classList.add('hidden');
    }
  } catch (_) { /* ignore – treat as no existing file */ }
}

function wizardBack() {
  const cur = wizardState.step;
  if (cur <= 1) return;
  const enc = document.getElementById('wiz-encryption').value;
  const params = _wizardCollectParams();
  const isEditLikeNoRegeneration =
    wizardState.mode !== 'create' &&
    wizardState.mode !== 'adopt' &&
    !wizardNeedsScriptRegeneration(params);
  // skip passphrase step going back from Beschreibung when no encryption
  if (cur === 7 && (enc === 'none' || isEditLikeNoRegeneration)) {
    _renderWizardStep(5);
    return;
  }
  _renderWizardStep(_wizardPreviousStepFrom(cur));
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
    const confirmWrap = document.getElementById('wizard-remote-init-confirm-wrap');
    const needsRemoteConfirm = params.location === 'storagebox' && (!remoteRepo || remoteRepo.needs_init_confirm !== false);
    if (confirmWrap) confirmWrap.classList.toggle('hidden', !needsRemoteConfirm);
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
    const remoteRepo = wizardState.remoteRepoStatus;
    const needsRemoteConfirm = params.location === 'storagebox' && (!remoteRepo || remoteRepo.needs_init_confirm !== false);
    if (needsRemoteConfirm && !params.remote_init_confirmed) {
      throw new Error(wizardT('wizard.confirmRemoteRequired'));
    }
    const res  = await fetch('/api/wizard/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(wizardApiErrorMessage(data, res.status));

    // Save schedule if enabled
    const schedEnabled = document.getElementById('wiz-sched-enabled').checked;
    if (schedEnabled) {
      const jobKey = `${params.type_id}_${params.location}`;
      const cron   = _wizardBuildCron();
      try {
        const sRes = await fetch('/api/schedules', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_key: jobKey, cron, enabled: true }),
        });
        if (sRes.ok) {
          const schedules = window.BBUI.core.getSchedulesData();
          schedules[jobKey] = { cron, enabled: true };
          window.BBUI.core.setSchedulesData(schedules);
        }
      } catch (_) { /* schedule save failure is non-fatal */ }
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

function wizardGeneratePassphrase() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*';
  const arr = new Uint8Array(32);
  crypto.getRandomValues(arr);
  const pw = Array.from(arr, b => chars[b % chars.length]).join('');
  const el = document.getElementById('wiz-passphrase');
  el.value = pw;
  el.type = 'text';
  document.getElementById('wiz-passphrase-toggle').textContent = wizardT('wizard.hide');
  document.getElementById('wiz-copy-btn').disabled = false;
  wizardClearError(4);
}

function wizardCopyPassphrase() {
  const pw = document.getElementById('wiz-passphrase').value;
  if (!pw) return;
  const btn = document.getElementById('wiz-copy-btn');
  const markCopied = () => {
    if (!btn) return;
    btn.textContent = wizardT('wizard.copied');
    setTimeout(() => { btn.textContent = wizardT('wizard.copy'); }, 2000);
  };

  const fallbackCopy = () => {
    const ta = document.createElement('textarea');
    ta.value = pw;
    ta.setAttribute('readonly', 'readonly');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    document.body.removeChild(ta);
    if (ok) markCopied();
  };

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(pw).then(markCopied).catch(() => fallbackCopy());
  } else {
    fallbackCopy();
  }
}

function wizardTogglePassphrase() {
  const el = document.getElementById('wiz-passphrase');
  const btn = document.getElementById('wiz-passphrase-toggle');
  if (el.type === 'password') {
    el.type = 'text';
    btn.textContent = wizardT('wizard.hide');
  } else {
    el.type = 'password';
    btn.textContent = wizardT('wizard.show');
  }
}

function wizardKeepPassphrase() {
  wizardState.keepPassphrase = true;
  document.getElementById('wizard-passphrase-form').classList.add('hidden');
  document.getElementById('wizard-passphrase-replace-warning').classList.add('hidden');
  document.getElementById('wiz-passphrase').value = '';
  document.getElementById('wizard-passphrase-keep-confirm').classList.remove('hidden');
  document.getElementById('wiz-keep-btn').classList.add('active');
  document.getElementById('wiz-replace-btn').classList.remove('active');
  wizardClearError(4);
}

function wizardReplacePassphrase() {
  wizardState.keepPassphrase = false;
  document.getElementById('wizard-passphrase-form').classList.remove('hidden');
  document.getElementById('wizard-passphrase-replace-warning').classList.remove('hidden');
  document.getElementById('wizard-passphrase-keep-confirm').classList.add('hidden');
  document.getElementById('wiz-keep-btn').classList.remove('active');
  document.getElementById('wiz-replace-btn').classList.add('active');
  wizardClearError(4);
}

// ── Wizard Schedule Step ──────────────────────────────────────────────────────

window.BBUI.wizardSchedState = window.BBUI.wizardSchedState || { frequency: 'daily', dow: 1 };
const wizardSchedState = window.BBUI.wizardSchedState;

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
    const titleKey = wizardState.mode === 'adopt'
      ? 'wizard.adoptTitle'
      : (wizardState.mode === 'edit' ? 'wizard.editTitle' : 'wizard.newTitle');
    title.textContent = wizardT(titleKey);
  }
  const passphrase = document.getElementById('wiz-passphrase');
  const passphraseToggle = document.getElementById('wiz-passphrase-toggle');
  if (passphrase && passphraseToggle) {
    passphraseToggle.textContent = wizardT(passphrase.type === 'password' ? 'wizard.show' : 'wizard.hide');
  }
  wizardSetUsbProfileOptions();
  wizardSetSmbProfileOptions();
  wizardSetStorageProfileOptions();
  wizardRenderSourcePaths();
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
