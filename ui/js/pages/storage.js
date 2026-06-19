// ══════════════════════════════════════════════════════════════════════════════
// STORAGE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.storageState = window.BBUI.storageState || { loaded: false, data: null, smbActionResults: {} };
const storageState = window.BBUI.storageState;

function storageT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function storageCount(count, singularKey, pluralKey) {
  return storageT(count === 1 ? singularKey : pluralKey, { count });
}

async function refreshStorage() {
  hideEl('storage-message');
  try {
    const res = await fetch('/api/storage');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    storageState.data = await res.json();
    storageState.loaded = true;
    renderStorage(storageState.data);
  } catch (err) {
    showMsg('storage-message', 'error', storageT('storage.errorPrefix', { message: err.message }));
  }
  checkLoadJobs();
}

function renderStorage(data) {
  const el = document.getElementById('storage-content');
  if (!el) return;

  const groups = data.groups || {};

  const sections = [
    {
      key: 'local',
      cssClass: 'local',
      title: storageT('storage.local'),
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="2" width="20" height="8" rx="2"/>
        <rect x="2" y="14" width="20" height="8" rx="2"/>
        <line x1="6" y1="6" x2="6.01" y2="6" stroke-width="3"/>
        <line x1="6" y1="18" x2="6.01" y2="18" stroke-width="3"/>
      </svg>`,
      meta: groups.local?.[0]?.path_display?.replace(/\/borg-backup-.*/, '') || '',
    },
    {
      key: 'usb',
      cssClass: 'usb',
      title: storageT('storage.usbDrive'),
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17 8h1a4 4 0 0 1 0 8h-1"/>
        <path d="M3 8h11v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8z"/>
        <line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/>
        <line x1="8" y1="4" x2="8" y2="10"/>
      </svg>`,
      meta: data.usb_mount || '',
    },
    {
      key: 'smb',
      cssClass: 'smb',
      title: storageT('storage.smb'),
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/>
      </svg>`,
      meta: storageCount(
        (data.smb_profiles || []).length,
        'storage.profileCountOne',
        'storage.profileCountMany',
      ),
    },
    {
      key: 'storagebox',
      cssClass: 'storagebox',
      title: storageT('storage.storagebox'),
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
      </svg>`,
      meta: data.storagebox_host
        ? `ssh ${data.storagebox_host}:${data.storagebox_port}`
        : storageT('storage.notConfigured'),
    },
  ];

  el.innerHTML = `<div class="storage-grid">
    ${sections.map(s => renderStorageCard(s, groups[s.key] || [])).join('')}
  </div>`;
}

function renderRepoListItem(repo) {
  const resultId = `repo-test-${repo.conf_key}`;
  const detailsBtnId = `repo-test-details-${repo.conf_key}`;

  const typeLabel = {
    flash: 'FLASH', appdata: 'APPDATA', photos: 'PHOTOS',
    VMs: 'VMs', sonstiges: storageT('storage.typeOther'),
  }[repo.backup_type] || repo.backup_type.toUpperCase();

  const displayPath = repo.path_display.length > 55
    ? '…' + repo.path_display.slice(-52)
    : repo.path_display;

  return `
    <li class="repo-list-item">
      <span class="type-mini-badge">${typeLabel}</span>

      <div class="repo-path-display">
        <span class="repo-path-text"
          title="${escHtml(repo.path_display)}">${escHtml(displayPath)}</span>
      </div>

      <div class="repo-item-actions">
        <button class="btn btn-secondary btn-sm"
          data-storage-action="test-repo"
          data-repo-path="${escHtml(repo.path_display)}"
          data-repo-conf-key="${escHtml(repo.conf_key || '')}"
          data-result-id="${resultId}">${storageT('storage.test')}</button>
        <button class="btn btn-secondary btn-sm hidden"
          id="${detailsBtnId}"
          data-storage-action="show-test-details"
          data-result-id="${resultId}">${storageT('storage.details')}</button>
        <span class="test-result" id="${resultId}"></span>
      </div>
    </li>`;
}

function onStorageContentClick(event) {
  const el = event.target.closest('[data-storage-action]');
  if (!el) return;
  const action = el.dataset.storageAction || '';
  if (action === 'test-repo') {
    return testRepo(el.dataset.repoPath || '', el.dataset.resultId || '', el.dataset.repoConfKey || '');
  }
  if (action === 'smb-action') {
    return runSmbAction(el.dataset.profileKey || '', el.dataset.smbAction || '', el.dataset.resultId || '');
  }
  if (action === 'show-test-details') {
    const resultEl = document.getElementById(el.dataset.resultId || '');
    if (!resultEl) return;
    return openStorageTestDetails(resultEl.dataset.fullOutput || storageT('storage.noDetails'));
  }
}

function renderStorageCard(section, repos) {
  if (section.key === 'smb') {
    return renderSmbCard(section, repos);
  }
  const repoCountBadge = repos.length > 0
    ? `<span class="storage-count-badge">${storageCount(repos.length, 'storage.repositoryCountOne', 'storage.repositoryCountMany')}</span>`
    : `<span class="storage-count-badge">–</span>`;

  const body = repos.length === 0
    ? `<div class="storage-empty">${storageT('storage.noRepositories')}</div>`
    : `<ul class="repo-list">${repos.map(r => renderRepoListItem(r)).join('')}</ul>`;

  return `
    <div class="storage-card ${section.cssClass}">
      <div class="storage-card-header">
        <div class="storage-card-title">
          <div class="storage-loc-icon">${section.icon}</div>
          <div>
            <div class="storage-card-name">${section.title}</div>
            ${section.meta ? `<div class="storage-card-meta" title="${escHtml(section.meta)}">${escHtml(section.meta)}</div>` : ''}
          </div>
        </div>
        ${repoCountBadge}
      </div>
      ${body}
    </div>`;
}

function _normPath(v) {
  return String(v || '').trim().replace(/\/+$/, '');
}

function _findSmbProfileForRepo(repo, profiles) {
  const candidates = [repo?.path_raw, repo?.path_display].map(_normPath).filter(Boolean);
  for (const p of (profiles || [])) {
    const mp = _normPath(p?.mount_path);
    if (!mp) continue;
    for (const c of candidates) {
      if (c === mp || c.startsWith(`${mp}/`)) return p;
    }
  }
  return null;
}

function renderSmbCard(section, smbRepos) {
  const profiles = Array.isArray(storageState.data?.smb_profiles) ? storageState.data.smb_profiles : [];
  const repoRows = Array.isArray(smbRepos) ? smbRepos : [];
  const grouped = new Map();
  profiles.forEach((p) => grouped.set(String(p.key || ''), { profile: p, repos: [] }));
  const unassigned = [];
  repoRows.forEach((r) => {
    const hit = _findSmbProfileForRepo(r, profiles);
    if (!hit) {
      unassigned.push(r);
      return;
    }
    const k = String(hit.key || '');
    if (!grouped.has(k)) grouped.set(k, { profile: hit, repos: [] });
    grouped.get(k).repos.push(r);
  });

  const body = !profiles.length
    ? `<div class="storage-empty">${storageT('storage.noSmbProfiles')}</div>`
    : `<div class="smb-profile-list">${profiles.map((p, idx) => {
      const rid = `smb-profile-result-${idx}`;
      const entry = grouped.get(String(p.key || '')) || { profile: p, repos: [] };
      const repos = entry.repos || [];
      const mountState = p.is_mounted ? storageT('storage.mounted') : storageT('storage.notMounted');
      const cached = storageState.smbActionResults[String(p.key || '')] || null;
      const actionClass = cached ? (cached.ok ? 'ok' : 'fail') : '';
      const actionText = cached
        ? (cached.ok ? '✓ OK' : `✗ ${cached.message || storageT('storage.error')}`)
        : '';
      const reposHtml = repos.length
        ? `<ul class="repo-list smb-repo-sublist">${repos.map((repo) => {
            const resultId = `repo-test-${repo.conf_key}`;
            const detailsBtnId = `repo-test-details-${repo.conf_key}`;
            const typeLabel = {
              flash: 'FLASH', appdata: 'APPDATA', photos: 'PHOTOS',
              VMs: 'VMs', sonstiges: storageT('storage.typeOther'),
            }[repo.backup_type] || String(repo.backup_type || '').toUpperCase();
            const displayPath = String(repo.path_display || '').length > 55
              ? '…' + String(repo.path_display || '').slice(-52)
              : String(repo.path_display || '');
            return `<li class="repo-list-item">
              <span class="type-mini-badge">${typeLabel}</span>
              <div class="repo-path-display">
                <span class="repo-path-text" title="${escHtml(repo.path_display)}">${escHtml(displayPath)}</span>
              </div>
              <div class="repo-item-actions">
                <button class="btn btn-secondary btn-sm"
                  data-storage-action="test-repo"
                  data-repo-path="${escHtml(repo.path_display)}"
                  data-repo-conf-key="${escHtml(repo.conf_key || '')}"
                  data-result-id="${resultId}"
                  ${p.is_mounted ? '' : `disabled title="${storageT('storage.mountFirst')}"`}>${storageT('storage.test')}</button>
                <button class="btn btn-secondary btn-sm hidden"
                  id="${detailsBtnId}"
                  data-storage-action="show-test-details"
                  data-result-id="${resultId}">${storageT('storage.details')}</button>
                <span class="test-result" id="${resultId}"></span>
              </div>
            </li>`;
          }).join('')}</ul>`
        : `<div class="storage-empty smb-empty-sublist">${storageT('storage.noRepositoriesForProfile')}</div>`;

      return `<section class="smb-profile-item">
        <div class="smb-profile-head">
          <span class="type-mini-badge">${escHtml(p.name || p.key || 'SMB')}</span>
          <div class="repo-path-display smb-profile-path">
            <span class="repo-path-text" title="${escHtml(`${p.server}/${p.share} -> ${p.mount_path}`)}">${escHtml(`${p.server}/${p.share}`)}</span>
            <span class="smb-mount-badge ${p.is_mounted ? 'ok' : 'off'}">${mountState}</span>
          </div>
          <div class="repo-item-actions">
            <button class="btn btn-secondary btn-sm" data-storage-action="smb-action" data-smb-action="mount" data-profile-key="${escHtml(p.key || '')}" data-result-id="${rid}">${storageT('storage.mount')}</button>
            <button class="btn btn-secondary btn-sm" data-storage-action="smb-action" data-smb-action="unmount" data-profile-key="${escHtml(p.key || '')}" data-result-id="${rid}">${storageT('storage.unmount')}</button>
            <span class="test-result ${actionClass}" id="${rid}">${escHtml(actionText)}</span>
          </div>
        </div>
        ${reposHtml}
      </section>`;
    }).join('')}
    ${unassigned.length ? `<div class="repo-list-item"><span class="type-mini-badge">${storageT('storage.withoutProfile')}</span><div class="repo-path-display"><span class="repo-path-text">${storageT('storage.unassignedRepositories')}</span></div></div>` : ''}
    </div>`;

  const repoCount = repoRows.length;
  return `
    <div class="storage-card ${section.cssClass}">
      <div class="storage-card-header">
        <div class="storage-card-title">
          <div class="storage-loc-icon">${section.icon}</div>
          <div>
            <div class="storage-card-name">${section.title}</div>
            ${section.meta ? `<div class="storage-card-meta">${escHtml(section.meta)}</div>` : ''}
          </div>
        </div>
        <span class="storage-count-badge">${storageCount(repoCount, 'storage.repositoryCountOne', 'storage.repositoryCountMany')}</span>
      </div>
      ${body}
    </div>`;
}

async function runSmbAction(profileKey, action, resultId) {
  const el = document.getElementById(resultId);
  if (el) { el.className = 'test-result testing'; el.textContent = '...'; el.title = ''; }
  try {
    const res = await fetch('/api/storage/smb-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_key: profileKey, action }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (el) {
      el.className = `test-result ${data.ok ? 'ok' : 'fail'}`;
      el.textContent = data.ok ? '✓ OK' : `✗ ${data.message || storageT('storage.error')}`;
      el.title = String((data && (data.message || data.output || '')) || '');
    }
    storageState.smbActionResults[String(profileKey || '')] = {
      ok: !!data.ok,
      message: data.message || '',
      ts: Date.now(),
    };
    await refreshStorage();
  } catch (err) {
    if (el) { el.className = 'test-result fail'; el.textContent = `✗ ${err.message}`; el.title = String(err.message || ''); }
    storageState.smbActionResults[String(profileKey || '')] = {
      ok: false,
      message: err.message,
      ts: Date.now(),
    };
  }
}

async function testRepo(repoPath, resultId, repoConfKey = '') {
  const el = document.getElementById(resultId);
  const detailsBtn = document.getElementById(`repo-test-details-${repoConfKey}`);
  if (el) { el.className = 'test-result testing'; el.textContent = storageT('storage.checking'); el.title = ''; }
  if (detailsBtn) detailsBtn.classList.add('hidden');
  try {
    const res = await fetch('/api/storage/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: repoPath, repo_conf_key: repoConfKey }),
    });
    const data = await res.json();
    if (el) {
      el.className = `test-result ${data.success ? 'ok' : 'fail'}`;
      if (data.success) {
        el.textContent = '✓ OK';
        el.dataset.fullOutput = String(data.output || '');
        el.title = String((data.output || '').trim() || 'OK');
      } else {
        const out = String(data.output || '').trim();
        const first = out.split('\n')[0] || `Exit ${data.exit_code}`;
        el.textContent = `✗ ${first}`;
        el.dataset.fullOutput = out || `Exit ${data.exit_code}`;
        el.title = out || `Exit ${data.exit_code}`;
        if (detailsBtn) detailsBtn.classList.remove('hidden');
      }
    }
  } catch (err) {
    if (el) { el.className = 'test-result fail'; el.textContent = `✗ ${storageT('storage.error')}`; el.title = String(err?.message || storageT('storage.unknownError')); }
    if (el) el.dataset.fullOutput = String(err?.message || storageT('storage.unknownError'));
    if (detailsBtn) detailsBtn.classList.remove('hidden');
  }
}

function openStorageTestDetails(text) {
  const modal = document.getElementById('storage-test-modal');
  const output = document.getElementById('storage-test-modal-output');
  if (!modal || !output) return;
  output.textContent = String(text || '').trim() || storageT('storage.noDetails');
  modal.classList.remove('hidden');
}

function closeStorageTestDetails() {
  document.getElementById('storage-test-modal')?.classList.add('hidden');
}

async function copyStorageTestDetails() {
  const output = document.getElementById('storage-test-modal-output');
  const text = String(output?.textContent || '').trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// BORG CHECK (Storage Page)
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI.storageCheckState = window.BBUI.storageCheckState || { es: null };
const checkState = window.BBUI.storageCheckState;

function _checkModeLabel(mode) {
  if (mode === 'verbose') return storageT('storage.check.modeVerbose');
  if (mode === 'verify_data') return storageT('storage.check.modeVerifyData');
  return storageT('storage.check.modeQuick');
}

function checkUpdateModeHint() {
  const sel = document.getElementById('check-level-select');
  const hint = document.getElementById('check-mode-hint');
  const badge = document.getElementById('check-mode-badge');
  if (!sel || !hint) return;
  if (sel.value === 'verify_data') {
    sel.classList.add('warn');
    if (badge) badge.classList.remove('hidden');
    hint.dataset.i18n = 'storage.check.verifyDataHint';
    hint.textContent = storageT(hint.dataset.i18n);
    return;
  }
  sel.classList.remove('warn');
  if (badge) badge.classList.add('hidden');
  if (sel.value === 'verbose') {
    hint.dataset.i18n = 'storage.check.verboseHint';
    hint.textContent = storageT(hint.dataset.i18n);
    return;
  }
  hint.dataset.i18n = 'storage.check.quickHint';
  hint.textContent = storageT(hint.dataset.i18n);
}

function _appendCheckLog(rawLine) {
  const logEl = document.getElementById('check-log-output');
  if (!logEl) return;
  const normalized = String(rawLine ?? '').replace(/\r/g, '\n');
  logEl.append(document.createTextNode(`${normalized}\n`));
  logEl.scrollTop = logEl.scrollHeight;
}

async function checkLoadJobs() {
  try {
    const res = await fetch('/api/storage/check/jobs');
    if (!res.ok) return;
    const data = await res.json();
    const sel = document.getElementById('check-job-select');
    if (!sel) return;
    const selected = sel.value;
    sel.innerHTML = `<option value="">${storageT('storage.check.selectJob')}</option>` +
      (data.jobs || []).map(j => `<option value="${escHtml(j.key)}">${escHtml(j.name)}</option>`).join('');
    sel.value = selected;
  } catch (_) {}
  checkUpdateModeHint();
}

async function checkRun() {
  const sel = document.getElementById('check-job-select');
  const jobKey = sel ? sel.value : '';
  if (!jobKey) { showMsg('check-message', 'error', storageT('storage.check.chooseJob')); return; }
  const modeSel = document.getElementById('check-level-select');
  const mode = modeSel ? modeSel.value : 'quick';

  const btn = document.getElementById('check-run-btn');
  if (btn) btn.disabled = true;
  hideEl('check-message');
  const logPanel = document.getElementById('check-log-panel');
  if (logPanel) logPanel.classList.remove('hidden');
  const logEl = document.getElementById('check-log-output');
  const statusEl = document.getElementById('check-log-status');
  if (logEl) logEl.textContent = '';
  if (statusEl) {
    statusEl.textContent = storageT('storage.check.running', { mode: _checkModeLabel(mode) });
    statusEl.className = 'check-log-status running';
  }

  if (checkState.es) { checkState.es.close(); checkState.es = null; }

  try {
    const res = await fetch('/api/storage/check/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: jobKey, mode }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      showMsg('check-message', 'error', err.error || `HTTP ${res.status}`);
      if (btn) btn.disabled = false;
      return;
    }
  } catch (err) {
    showMsg('check-message', 'error', storageT('storage.errorPrefix', { message: err.message }));
    if (btn) btn.disabled = false;
    return;
  }

  const es = new EventSource('/api/storage/check/stream');
  checkState.es = es;

  es.onmessage = (e) => {
    _appendCheckLog(e.data);
  };

  es.addEventListener('done', (e) => {
    const code = parseInt(e.data, 10);
    if (statusEl) {
      statusEl.textContent = code === 0
        ? storageT('storage.check.successful')
        : storageT('storage.check.failedExit', { code: e.data });
      statusEl.className = `check-log-status ${code === 0 ? 'success' : 'error'}`;
    }
    es.close(); checkState.es = null;
    if (btn) btn.disabled = false;
  });

  es.addEventListener('error', (e) => {
    if (e.data) _appendCheckLog(storageT('storage.check.logError', { message: e.data }));
    if (statusEl) { statusEl.textContent = storageT('storage.error'); statusEl.className = 'check-log-status error'; }
    es.close(); checkState.es = null;
    if (btn) btn.disabled = false;
  });
}

function checkClearLog() {
  const logEl = document.getElementById('check-log-output');
  if (logEl) logEl.textContent = '';
}

function checkCloseLog() {
  const panel = document.getElementById('check-log-panel');
  if (panel) panel.classList.add('hidden');
  if (checkState.es) {
    checkState.es.close();
    checkState.es = null;
  }
  const btn = document.getElementById('check-run-btn');
  if (btn) btn.disabled = false;
}

window.addEventListener('bbui:language-changed', () => {
  if (storageState.loaded && storageState.data) renderStorage(storageState.data);
  checkUpdateModeHint();
  checkLoadJobs();
});
