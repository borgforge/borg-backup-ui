// ══════════════════════════════════════════════════════════════════════════════
// STORAGE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.storageState = window.BBUI.storageState || {
  loaded: false,
  data: null,
  jobs: [],
  smbActionResults: {},
  expandedRepositories: {},
  selectedLocation: 'all',
  search: '',
};
const storageState = window.BBUI.storageState;
storageState.expandedRepositories = storageState.expandedRepositories || {};

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

function storageTargetLabel(storage) {
  const name = String(storage?.display_name || storage?.storage_key || '').trim();
  const meta = String(storage?.base_path || storage?.mount_path || storage?.endpoint || storage?.identity || '').trim();
  return meta ? `${name} — ${meta}` : name;
}

function storageTargets(data) {
  const rows = Array.isArray(data?.storages) ? data.storages : [];
  return rows
    .filter((row) => String(row?.storage_key || '').trim())
    .sort((a, b) => {
      const ai = STORAGE_LOCATION_ORDER.indexOf(String(a.location || a.storage_type || '').toLowerCase());
      const bi = STORAGE_LOCATION_ORDER.indexOf(String(b.location || b.storage_type || '').toLowerCase());
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
        || String(a.display_name || '').localeCompare(String(b.display_name || ''));
    });
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
    return [
      repo.backup_type,
      repo.conf_key,
      repo.repository_key,
      repo.repository_name,
      repo.display_name,
      repo.storage_name,
      repo.path_display,
      storageLocationLabel(repo.location),
      ...(repo.used_by || []),
    ]
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
        <button class="btn btn-primary btn-sm" type="button" data-storage-action="open-repository-manager">
          ${storageT('storage.addRepository')}
        </button>
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
  const resultKey = String(repositoryKey || repo.path_display || repo.path_raw || repo.repo_uri || repo.repo_path || '').replace(/[^A-Za-z0-9_-]/g, '_');
  const repositoryDetailsId = `repo-details-${resultKey}`;
  const expanded = !!storageState.expandedRepositories[resultKey];
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
          data-details-id="${escHtml(repositoryDetailsId)}"
          data-result-key="${escHtml(resultKey)}">${storageT(expanded ? 'storage.hideDetails' : 'storage.details')}</button>
      </div>
    </td>
  </tr>
  <tr id="${repositoryDetailsId}" class="storage-repository-details-row ${expanded ? '' : 'hidden'}">
    <td colspan="5">${renderStorageRepositoryDetailsPanel(repo, job)}</td>
  </tr>`;
}

function storageDetailValue(value) {
  const text = String(value || '').trim();
  return text ? escHtml(text) : '—';
}

function storageDetailItem(labelKey, value, extraClass = '') {
  return `<div class="storage-repository-detail-item ${extraClass}">
    <span>${escHtml(storageT(labelKey))}</span>
    <strong>${storageDetailValue(value)}</strong>
  </div>`;
}

function storageRepositoryEncryption(repo, job) {
  return String(repo?.encryption || job?.encryption || '').trim() || storageT('storage.unknown');
}

function renderStorageRepositoryDetailsPanel(repo, job) {
  const path = repo.path_display || repo.path_raw || repo.repo_uri || repo.repo_path || '';
  return `<div class="storage-repository-detail-card">
    <div class="storage-repository-detail-grid">
      ${storageDetailItem('storage.repositoryNameLabel', storageRepositoryName(repo))}
      ${storageDetailItem('storage.storageNameLabel', storageName(repo))}
      ${storageDetailItem('storage.jobNameLabel', storageJobName(repo, job))}
      ${storageDetailItem('storage.location', storageLocationLabel(repo.location))}
      ${storageDetailItem('storage.path', path, 'span-2')}
      ${storageDetailItem('storage.repositoryEncryption', storageRepositoryEncryption(repo, job))}
      ${storageDetailItem('storage.repositoryRelativePath', repo.relative_path || '')}
    </div>
  </div>`;
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
  if (action === 'smb-action') {
    return runSmbAction(el.dataset.profileKey || '', el.dataset.smbAction || '', el.dataset.resultId || '');
  }
  if (action === 'show-repo-details') {
    return toggleStorageRepositoryDetails(el.dataset.detailsId || '', el.dataset.resultKey || '', el);
  }
  if (action === 'open-repository-manager') {
    return openRepositoryManager();
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

function toggleStorageRepositoryDetails(detailsId, resultKey, button) {
  const row = document.getElementById(detailsId);
  if (!row) return;
  const willOpen = row.classList.contains('hidden');
  row.classList.toggle('hidden', !willOpen);
  if (resultKey) storageState.expandedRepositories[resultKey] = willOpen;
  if (button) button.textContent = storageT(willOpen ? 'storage.hideDetails' : 'storage.details');
}

function repositoryManagerSetMessage(type, message) {
  const el = document.getElementById('repository-manager-message');
  if (!el) return;
  if (!message) {
    el.className = 'status-message hidden';
    el.textContent = '';
    return;
  }
  el.className = `status-message ${type || 'info'}`;
  el.textContent = message;
}

function repositoryManagerSyncFields() {
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const encryption = document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2';
  document.getElementById('repository-manager-passphrase-group')
    ?.classList.toggle('hidden', encryption === 'none');
  ['repository-manager-storage-quota', 'repository-manager-append-only', 'repository-manager-make-parent-dirs'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = action !== 'create';
  });
  repositoryManagerUpdateSummary();
}

function repositoryManagerFillStorages() {
  const sel = document.getElementById('repository-manager-storage');
  if (!sel) return;
  const rows = storageTargets(storageState.data || {});
  sel.innerHTML = rows.length
    ? rows.map((storage) => `<option value="${escHtml(storage.storage_key || '')}">${escHtml(storageTargetLabel(storage))}</option>`).join('')
    : `<option value="">${storageT('storage.noStorageTargets')}</option>`;
  repositoryManagerUpdateSummary();
}

function repositoryManagerSelectedStorageLabel() {
  const sel = document.getElementById('repository-manager-storage');
  if (!sel) return '';
  return String(sel.options?.[sel.selectedIndex]?.textContent || sel.value || '').trim();
}

function repositoryManagerSelectedActionLabel() {
  const sel = document.getElementById('repository-manager-action');
  if (!sel) return '';
  return String(sel.options?.[sel.selectedIndex]?.textContent || sel.value || '').trim();
}

function repositoryManagerSummaryRow(labelKey, value) {
  return `<div>
    <span>${escHtml(storageT(labelKey))}</span>
    <strong>${escHtml(String(value || '').trim() || '—')}</strong>
  </div>`;
}

function repositoryManagerUpdateSummary() {
  const el = document.getElementById('repository-manager-summary');
  if (!el) return;
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const encryption = String(document.getElementById('repository-manager-encryption')?.value || '').trim();
  const passphrase = String(document.getElementById('repository-manager-passphrase')?.value || '').trim();
  const repositoryName = String(document.getElementById('repository-manager-repository-name')?.value || '').trim();
  const displayName = String(document.getElementById('repository-manager-display-name')?.value || '').trim();
  const relativePath = String(document.getElementById('repository-manager-relative-path')?.value || '').trim();
  const passphraseState = encryption === 'none'
    ? storageT('storage.repositorySummaryPassphraseNone')
    : (passphrase
      ? storageT('storage.repositorySummaryPassphraseStored')
      : storageT('storage.repositorySummaryPassphraseNone'));
  const hint = action === 'create'
    ? storageT('storage.repositorySummaryCreateHint')
    : storageT('storage.repositorySummaryImportHint');
  el.innerHTML = `
    <div class="repository-manager-summary-list">
      ${repositoryManagerSummaryRow('storage.repositorySummaryAction', repositoryManagerSelectedActionLabel())}
      ${repositoryManagerSummaryRow('storage.repositorySummaryStorage', repositoryManagerSelectedStorageLabel())}
      ${repositoryManagerSummaryRow('storage.repositorySummaryRepository', displayName || repositoryName)}
      ${repositoryManagerSummaryRow('storage.repositorySummaryPath', relativePath || repositoryName)}
      ${repositoryManagerSummaryRow('storage.repositorySummaryEncryption', encryption || '—')}
      ${repositoryManagerSummaryRow('storage.repositorySummaryPassphrase', passphraseState)}
    </div>
    <p>${escHtml(hint)}</p>`;
}

function openRepositoryManager() {
  const modal = document.getElementById('repository-manager-modal');
  if (!modal) return;
  repositoryManagerSetMessage('', '');
  repositoryManagerFillStorages();
  const defaults = {
    'repository-manager-action': 'create',
    'repository-manager-display-name': '',
    'repository-manager-repository-name': '',
    'repository-manager-relative-path': '',
    'repository-manager-encryption': 'repokey-blake2',
    'repository-manager-passphrase': '',
    'repository-manager-storage-quota': '',
  };
  Object.entries(defaults).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  const relative = document.getElementById('repository-manager-relative-path');
  if (relative) relative.dataset.autofilled = 'false';
  const appendOnly = document.getElementById('repository-manager-append-only');
  const parentDirs = document.getElementById('repository-manager-make-parent-dirs');
  if (appendOnly) appendOnly.checked = false;
  if (parentDirs) parentDirs.checked = true;
  repositoryManagerSyncFields();
  modal.classList.remove('hidden');
}

function closeRepositoryManager() {
  document.getElementById('repository-manager-modal')?.classList.add('hidden');
}

function repositoryManagerSlug(value) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^A-Za-z0-9._/-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function repositoryManagerNameChanged() {
  const repoName = document.getElementById('repository-manager-repository-name');
  const relative = document.getElementById('repository-manager-relative-path');
  if (!repoName || !relative) return;
  if (!relative.value || relative.dataset.autofilled === 'true') {
    relative.value = repositoryManagerSlug(repoName.value);
    relative.dataset.autofilled = 'true';
  }
  repositoryManagerUpdateSummary();
}

async function saveRepositoryManager() {
  repositoryManagerSetMessage('', '');
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const payload = {
    action,
    storage_key: document.getElementById('repository-manager-storage')?.value || '',
    display_name: document.getElementById('repository-manager-display-name')?.value || '',
    repository_name: document.getElementById('repository-manager-repository-name')?.value || '',
    relative_path: document.getElementById('repository-manager-relative-path')?.value || '',
    encryption: document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2',
    passphrase: document.getElementById('repository-manager-passphrase')?.value || '',
    storage_quota: action === 'create' ? (document.getElementById('repository-manager-storage-quota')?.value || '') : '',
    append_only: action === 'create' && !!document.getElementById('repository-manager-append-only')?.checked,
    make_parent_dirs: action === 'create' && !!document.getElementById('repository-manager-make-parent-dirs')?.checked,
  };
  const btn = document.getElementById('repository-manager-save-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/repositories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    closeRepositoryManager();
    await refreshStorage();
    showMsg('storage-message', 'success', storageT('storage.repositorySaved'));
  } catch (err) {
    repositoryManagerSetMessage('error', err.message || storageT('storage.error'));
  } finally {
    if (btn) btn.disabled = false;
  }
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
