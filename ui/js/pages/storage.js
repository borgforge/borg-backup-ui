// ══════════════════════════════════════════════════════════════════════════════
// STORAGE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.storageState = window.BBUI.storageState || {
  loaded: false,
  data: null,
  jobs: [],
  smbActionResults: {},
  selectedLocation: 'all',
  search: '',
};
const storageState = window.BBUI.storageState;

function storageT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function storageCount(count, singularKey, pluralKey) {
  return storageT(count === 1 ? singularKey : pluralKey, { count });
}

const STORAGE_LOCATION_ORDER = ['local', 'usb', 'smb', 'storagebox'];

function storageLocationIcon(key) {
  const icons = {
    all: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 6h16M4 12h16M4 18h16"/>
    </svg>`,
    local: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="2" y="2" width="20" height="8" rx="2"/>
      <rect x="2" y="14" width="20" height="8" rx="2"/>
      <line x1="6" y1="6" x2="6.01" y2="6" stroke-width="3"/>
      <line x1="6" y1="18" x2="6.01" y2="18" stroke-width="3"/>
    </svg>`,
    usb: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M17 8h1a4 4 0 0 1 0 8h-1"/>
      <path d="M3 8h11v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8z"/>
      <line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/>
      <line x1="8" y1="4" x2="8" y2="10"/>
    </svg>`,
    smb: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/>
    </svg>`,
    storagebox: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
    </svg>`,
  };
  return icons[key] || icons.all;
}

function storageLocationLabel(key) {
  return {
    all: storageT('storage.allLocations'),
    local: storageT('storage.local'),
    usb: storageT('storage.usbDrive'),
    smb: storageT('storage.smb'),
    storagebox: storageT('storage.storagebox'),
  }[key] || key;
}

function storageTypeLabel(repo) {
  return {
    flash: 'FLASH',
    appdata: 'APPDATA',
    photos: 'PHOTOS',
    VMs: 'VMs',
    vms: 'VMs',
    sonstiges: storageT('storage.typeOther'),
  }[repo.backup_type] || String(repo.backup_type || '').toUpperCase();
}

function storageRepositoryTitle(repo, job) {
  const raw = String(repo?.display_name || job?.name || storageTypeLabel(repo) || '').trim();
  const cleaned = raw
    .replace(/\s+-\s+Local$/i, '')
    .replace(/\s+-\s+USB$/i, '')
    .replace(/\s+-\s+SMB$/i, '')
    .replace(/\s+-\s+Storagebox$/i, '')
    .trim();
  const base = cleaned || String(job?.name || storageTypeLabel(repo) || repo?.repository_key || '').trim();
  const location = storageLocationLabel(repo?.location || '');
  return location ? `${base} - ${location}` : base;
}

function storageRepositoryName(repo) {
  const explicit = String(repo?.repository_name || '').trim();
  if (explicit) return explicit;
  const path = String(repo?.path_display || repo?.path_raw || repo?.repo_uri || repo?.repo_path || '').trim().replace(/\/+$/, '');
  if (!path) return String(repo?.repository_key || repo?.conf_key || '').trim();
  const pathOnly = path.includes('://') ? path.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]+/i, '') : path;
  const leaf = (pathOnly.split('/').filter(Boolean).pop() || path).trim();
  try {
    return decodeURIComponent(leaf);
  } catch (_) {
    return leaf;
  }
}

function storageJobName(repo, job) {
  return String(repo?.job_name || job?.name || repo?.display_name || repo?.used_by?.[0] || repo?.source_job_keys?.[0] || '').trim();
}

function storageName(repo) {
  const raw = String(repo?.storage_name || '').trim();
  const location = String(repo?.location || '').trim().toLowerCase();
  if (!raw || raw.toLowerCase() === location) return storageLocationLabel(location);
  if ({ local: true, usb: true, smb: true, storagebox: true }[raw.toLowerCase()]) return storageLocationLabel(raw.toLowerCase());
  return raw;
}

function storageRepositories(data) {
  const groups = data?.groups || {};
  return STORAGE_LOCATION_ORDER.flatMap((location) =>
    (Array.isArray(groups[location]) ? groups[location] : []).map((repo) => ({ ...repo, location }))
  );
}

function storageVisibleRepositories(data) {
  const location = storageState.selectedLocation || 'all';
  const query = String(storageState.search || '').trim().toLocaleLowerCase();
  return storageRepositories(data).filter((repo) => {
    if (location !== 'all' && repo.location !== location) return false;
    if (!query) return true;
    return [repo.backup_type, repo.conf_key, repo.repository_key, repo.path_display, storageLocationLabel(repo.location), ...(repo.used_by || [])]
      .some((value) => String(value || '').toLocaleLowerCase().includes(query));
  });
}

async function refreshStorage() {
  hideEl('storage-message');
  try {
    const [storageRes, jobsRes] = await Promise.all([
      fetch('/api/storage'),
      fetch('/api/jobs'),
    ]);
    if (!storageRes.ok) throw new Error(`HTTP ${storageRes.status}`);
    storageState.data = await storageRes.json();
    storageState.jobs = jobsRes.ok ? (await jobsRes.json()).jobs || [] : [];
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

  renderStorageLocationSidebar(data);
  const repos = storageVisibleRepositories(data);
  const title = storageLocationLabel(storageState.selectedLocation || 'all');
  const header = document.getElementById('storage-workspace-header');
  if (header) {
    header.innerHTML = `
      <div class="ui-workspace-header__title">
        <small>${storageT('storage.overview')}</small>
        <h2>${escHtml(title)}</h2>
        <span class="ui-workspace-header__subtitle">${storageT('storage.overviewHint')}</span>
      </div>
      <span class="badge neutral">${storageCount(repos.length, 'storage.repositoryCountOne', 'storage.repositoryCountMany')}</span>`;
  }

  const rows = repos.length
    ? renderStorageRepositoryRows(repos, data.smb_profiles || [])
    : `<tr><td colspan="5"><div class="storage-empty">${storageT('storage.noMatchingRepositories')}</div></td></tr>`;

  const showSmbProfiles = (storageState.selectedLocation || 'all') === 'smb';
  el.innerHTML = `
    <section class="storage-repository-panel ui-panel">
      <div class="storage-repository-tools">
        <strong>${storageT('storage.repositories')}</strong>
        <input id="storage-repo-search" class="form-input" type="search"
          value="${escHtml(storageState.search || '')}"
          placeholder="${storageT('storage.searchPlaceholder')}"
          aria-label="${storageT('storage.searchPlaceholder')}">
      </div>
      <div class="storage-table-wrap ui-table-wrap">
        <table class="storage-repository-table ui-table">
          <thead><tr>
            <th>${storageT('storage.repository')}</th>
            <th>${storageT('storage.location')}</th>
            <th>${storageT('storage.path')}</th>
            <th>${storageT('storage.status')}</th>
            <th>${storageT('storage.actions')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
    ${showSmbProfiles ? renderStorageSmbProfiles(data.smb_profiles || [], data.groups?.smb || []) : ''}`;
}

function storageLocationMeta(key, data) {
  if (key === 'local') {
    return data.groups?.local?.[0]?.path_display?.replace(/\/borg-backup-.*/, '') || storageT('storage.local');
  }
  if (key === 'usb') return data.usb_mount || storageT('storage.notConfigured');
  if (key === 'smb') {
    const profiles = data.smb_profiles || [];
    const mounted = profiles.filter((profile) => profile.is_mounted).length;
    return storageT('storage.smbProfileMeta', { profiles: profiles.length, mounted });
  }
  if (key === 'storagebox') {
    return data.storagebox_host
      ? `ssh ${data.storagebox_host}:${data.storagebox_port}`
      : storageT('storage.notConfigured');
  }
  return storageT('storage.overview');
}

function renderStorageLocationSidebar(data) {
  const nav = document.getElementById('storage-location-list');
  if (!nav) return;
  const groups = data.groups || {};
  const total = STORAGE_LOCATION_ORDER.reduce((sum, key) => sum + (groups[key] || []).length, 0);
  nav.innerHTML = ['all', ...STORAGE_LOCATION_ORDER].map((key) => {
    const count = key === 'all' ? total : (groups[key] || []).length;
    const active = (storageState.selectedLocation || 'all') === key;
    return `<button class="ui-context-nav__item storage-location-entry ${active ? 'is-active' : ''}"
      type="button" data-storage-location="${key}" ${active ? 'aria-current="page"' : ''}>
      <span class="location-nav-glyph ${key}">${storageLocationIcon(key)}</span>
      <span class="location-nav-copy">
        <strong>${escHtml(storageLocationLabel(key))}</strong>
        <small title="${escHtml(storageLocationMeta(key, data))}">${escHtml(storageLocationMeta(key, data))}</small>
      </span>
      <span class="badge neutral location-nav-count">${count}</span>
    </button>`;
  }).join('');
}

function onStorageLocationClick(event) {
  const button = event.target.closest('[data-storage-location]');
  if (!button || !storageState.data) return;
  storageState.selectedLocation = button.dataset.storageLocation || 'all';
  storageState.search = '';
  renderStorage(storageState.data);
}

function onStorageSearchInput(event) {
  if (event.target.id !== 'storage-repo-search' || !storageState.data) return;
  storageState.search = event.target.value || '';
  renderStorage(storageState.data);
  const input = document.getElementById('storage-repo-search');
  input?.focus();
  input?.setSelectionRange(storageState.search.length, storageState.search.length);
}

function renderStorageRepositoryRow(repo, profiles) {
  const resultId = `repo-test-${repo.conf_key}`;
  const detailsBtnId = `repo-test-details-${repo.conf_key}`;
  const profile = repo.location === 'smb' ? _findSmbProfileForRepo(repo, profiles) : null;
  const unavailable = repo.location === 'smb' && profile && !profile.is_mounted;
  const managed = !!repo.repository_key;
  const statusText = unavailable
    ? storageT('storage.notMounted')
    : (managed ? storageT('storage.managedRepository') : storageT('storage.configured'));
  const statusClass = unavailable ? 'warning' : 'success';
  const job = storageJobForRepository(repo);
  const icon = typeof resolveJobIcon === 'function' ? resolveJobIcon(job || repo) : repo.backup_type;
  const color = typeof resolveJobIconColor === 'function' ? resolveJobIconColor(job || repo) : '';
  const iconColorClass = color ? ` type-icon-color-${color}` : '';
  const usedBy = Array.isArray(repo.used_by) && repo.used_by.length
    ? repo.used_by.join(', ')
    : (Array.isArray(repo.source_job_keys) ? repo.source_job_keys.join(', ') : '');
  const repositoryKey = repo.repository_key || repo.conf_key || '';
  const title = storageRepositoryTitle(repo, job);
  const repositoryName = storageRepositoryName(repo);
  const jobName = storageJobName(repo, job);
  const metaTitle = [
    repositoryName ? `${storageT('storage.repositoryNameLabel')} ${repositoryName}` : '',
    jobName ? `${storageT('storage.jobNameLabel')} ${jobName}` : '',
  ].filter(Boolean).join(' · ');

  return `<tr>
    <td>
      <div class="storage-repository-main">
        <span class="type-icon type-icon-${escHtml(String(repo.backup_type || 'sonstiges').toLowerCase())}${iconColorClass}">${typeIcon(icon)}</span>
        <span>
          <strong title="${escHtml(title)}">${escHtml(title)}</strong>
          <small class="storage-repository-meta" title="${escHtml(metaTitle)}">
            ${repositoryName ? `<span><b>${storageT('storage.repositoryNameLabel')}</b>${escHtml(repositoryName)}</span>` : ''}
            ${jobName ? `<span><b>${storageT('storage.jobNameLabel')}</b>${escHtml(jobName)}</span>` : ''}
          </small>
        </span>
      </div>
    </td>
    <td><span class="badge info" title="${escHtml(storageLocationLabel(repo.location))}">${escHtml(storageName(repo))}</span></td>
    <td><span class="storage-repository-path" title="${escHtml(repo.path_display)}">${escHtml(repo.path_display)}</span></td>
    <td><span class="badge ${statusClass}">${escHtml(statusText)}</span></td>
    <td>
      <div class="storage-row-actions">
        <button class="btn btn-secondary btn-sm"
          data-storage-action="show-repo-details"
          data-repository-key="${escHtml(repositoryKey)}">${storageT('storage.details')}</button>
        <button class="btn btn-secondary btn-sm"
          data-storage-action="test-repo"
          data-repo-path="${escHtml(repo.path_display)}"
          data-repo-conf-key="${escHtml(repo.conf_key || '')}"
          data-result-id="${resultId}"
          ${unavailable ? `disabled title="${storageT('storage.mountFirst')}"` : ''}>${storageT('storage.test')}</button>
        <button class="btn btn-secondary btn-sm hidden"
          id="${detailsBtnId}"
          data-storage-action="show-test-details"
          data-result-id="${resultId}">${storageT('storage.details')}</button>
        <span class="test-result hidden" id="${resultId}"></span>
      </div>
    </td>
  </tr>`;
}

function storageJobForRepository(repo) {
  const jobs = Array.isArray(storageState.jobs) ? storageState.jobs : [];
  const confKey = String(repo?.conf_key || '');
  const jobKey = confKey.startsWith('JOB:') ? confKey.slice(4) : '';
  const usedBy = Array.isArray(repo?.used_by) ? repo.used_by.map((x) => String(x || '')) : [];
  const sourceJobKeys = Array.isArray(repo?.source_job_keys) ? repo.source_job_keys.map((x) => String(x || '')) : [];
  return jobs.find((job) => usedBy.includes(String(job.key || '')) || sourceJobKeys.includes(String(job.key || '')))
    || jobs.find((job) => jobKey && String(job.key || '') === jobKey)
    || jobs.find((job) =>
      String(job.backup_type || '').toLowerCase() === String(repo?.backup_type || '').toLowerCase()
      && String(job.location || '').toLowerCase() === String(repo?.location || '').toLowerCase()
    )
    || null;
}

function renderStorageRepositoryRows(repos, profiles) {
  if ((storageState.selectedLocation || 'all') !== 'all') {
    return repos.map((repo) => renderStorageRepositoryRow(repo, profiles)).join('');
  }
  return STORAGE_LOCATION_ORDER.map((location) => {
    const locationRepos = repos.filter((repo) => repo.location === location);
    if (!locationRepos.length) return '';
    return `<tr class="storage-location-group-row">
      <td colspan="5">
        <div class="storage-location-group">
          <span class="location-nav-glyph ${location}">${storageLocationIcon(location)}</span>
          <span>
            <strong>${escHtml(storageLocationLabel(location))}</strong>
            <small>${storageCount(locationRepos.length, 'storage.repositoryCountOne', 'storage.repositoryCountMany')}</small>
          </span>
        </div>
      </td>
    </tr>${locationRepos.map((repo) => renderStorageRepositoryRow(repo, profiles)).join('')}`;
  }).join('');
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
  if (action === 'show-repo-details') {
    return openStorageRepositoryDetails(el.dataset.repositoryKey || '');
  }
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

function renderStorageSmbProfiles(profiles, smbRepos) {
  const rows = Array.isArray(profiles) ? profiles : [];
  if (!rows.length) return '';
  return `<section class="storage-smb-panel ui-panel">
    <div class="ui-panel__header">
      <strong>${storageT('storage.smbProfiles')}</strong>
      <span>${storageT('storage.smbProfilesHint')}</span>
    </div>
    <div class="storage-smb-profile-list">${rows.map((profile, idx) => {
      const rid = `smb-profile-result-${idx}`;
      const repos = (smbRepos || []).filter((repo) => _findSmbProfileForRepo(repo, [profile]));
      const mountState = profile.is_mounted ? storageT('storage.mounted') : storageT('storage.notMounted');
      const cached = storageState.smbActionResults[String(profile.key || '')] || null;
      const actionClass = cached ? (cached.ok ? 'ok' : 'fail') : '';
      const cachedMessage = cached?.payload
        ? apiMessage(cached.payload, cached.ok ? 'OK' : storageT('storage.error'))
        : (cached?.message || storageT('storage.error'));
      const actionText = cached
        ? (cached.ok ? '✓ OK' : `✗ ${cachedMessage}`)
        : '';
      const endpoint = [profile.server, profile.share].filter(Boolean).join('/');
      return `<article class="storage-smb-profile">
        <div>
          <strong>${escHtml(profile.name || profile.key || 'SMB')}</strong>
          <small title="${escHtml(`${endpoint} -> ${profile.mount_path || ''}`)}">${escHtml(endpoint || profile.mount_path || '')}</small>
        </div>
        <span class="badge ${profile.is_mounted ? 'success' : 'warning'}">${mountState}</span>
        <span class="storage-smb-repo-count">${storageCount(repos.length, 'storage.repositoryCountOne', 'storage.repositoryCountMany')}</span>
        <div class="storage-row-actions">
            <button class="btn btn-secondary btn-sm" data-storage-action="smb-action" data-smb-action="mount" data-profile-key="${escHtml(profile.key || '')}" data-result-id="${rid}">${storageT('storage.mount')}</button>
            <button class="btn btn-secondary btn-sm" data-storage-action="smb-action" data-smb-action="unmount" data-profile-key="${escHtml(profile.key || '')}" data-result-id="${rid}">${storageT('storage.unmount')}</button>
            <span class="test-result ${actionClass}" id="${rid}">${escHtml(actionText)}</span>
        </div>
      </article>`;
    }).join('')}</div>
  </section>`;
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
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    if (el) {
      el.className = `test-result ${data.ok ? 'ok' : 'fail'}`;
      const message = apiMessage(data, data.ok ? 'OK' : storageT('storage.error'));
      el.textContent = data.ok ? '✓ OK' : `✗ ${message}`;
      el.title = message;
    }
    storageState.smbActionResults[String(profileKey || '')] = {
      ok: !!data.ok,
      message: apiMessage(data, data.ok ? 'OK' : storageT('storage.error')),
      payload: {
        message_code: data.message_code || '',
        message_params: data.message_params || {},
      },
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
      }
    }
    if (detailsBtn) detailsBtn.classList.remove('hidden');
  } catch (err) {
    if (el) { el.className = 'test-result fail'; el.textContent = `✗ ${storageT('storage.error')}`; el.title = String(err?.message || storageT('storage.unknownError')); }
    if (el) el.dataset.fullOutput = String(err?.message || storageT('storage.unknownError'));
    if (detailsBtn) detailsBtn.classList.remove('hidden');
  }
}

function openStorageModal(title, text) {
  const modal = document.getElementById('storage-test-modal');
  const output = document.getElementById('storage-test-modal-output');
  if (!modal || !output) return;
  const titleEl = modal.querySelector('.modal-header h3');
  if (titleEl) titleEl.textContent = title;
  output.textContent = String(text || '').trim() || storageT('storage.noDetails');
  modal.classList.remove('hidden');
}

function openStorageTestDetails(text) {
  openStorageModal(storageT('storage.testDetailsTitle'), text);
}

function openStorageRepositoryDetails(repositoryKey) {
  const repos = storageRepositories(storageState.data || {});
  const repo = repos.find((item) => String(item.repository_key || item.conf_key || '') === String(repositoryKey || ''));
  if (!repo) return openStorageModal(storageT('storage.repositoryDetailsTitle'), storageT('storage.noDetails'));
  const job = storageJobForRepository(repo);
  const values = [
    [storageT('storage.jobNameLabel'), storageJobName(repo, job)],
    [storageT('storage.jobIdLabel'), Array.isArray(repo.used_by) ? repo.used_by.join(', ') : ''],
    [storageT('storage.repositoryNameLabel'), storageRepositoryName(repo)],
    [storageT('storage.repositoryIdLabel'), repo.repository_key || repo.conf_key || ''],
    [storageT('storage.storageNameLabel'), storageName(repo)],
    [storageT('storage.storageIdLabel'), repo.storage_key || ''],
    [storageT('storage.location'), storageLocationLabel(repo.location)],
    [storageT('storage.path'), repo.path_display || repo.path_raw || repo.repo_uri || repo.repo_path || ''],
    [storageT('storage.repoConfKeyLabel'), repo.repo_conf_key || repo.conf_key || ''],
  ];
  const text = values
    .filter(([, value]) => String(value || '').trim())
    .map(([label, value]) => `${label} ${value}`)
    .join('\n');
  openStorageModal(storageT('storage.repositoryDetailsTitle'), text);
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
