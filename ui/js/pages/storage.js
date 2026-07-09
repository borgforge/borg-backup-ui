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
            <th>${storageT('storage.storageTargetColumn')}</th>
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

function storageFormatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function renderRepositoryStats(repo) {
  const stats = repo?.repository_stats && typeof repo.repository_stats === 'object' ? repo.repository_stats : {};
  if (!Object.keys(stats).length) return '';
  const total = Number(stats.total_size || 0);
  const unique = Number(stats.unique_csize || 0);
  const saving = total > 0 ? `${Math.max(0, (1 - (unique / total)) * 100).toFixed(0)}%` : '—';
  return `<div class="storage-repository-stats">
    ${storageDetailItem('storage.repositoryTotalSize', storageFormatBytes(total))}
    ${storageDetailItem('storage.repositoryCompressedSize', storageFormatBytes(stats.total_csize))}
    ${storageDetailItem('storage.repositoryDeduplicatedSize', storageFormatBytes(unique))}
    ${storageDetailItem('storage.repositorySaving', saving)}
    ${storageDetailItem('storage.repositoryArchiveCount', String(stats.archives_count ?? '—'))}
  </div>`;
}

function storageRepositoryEncryption(repo, job) {
  return String(repo?.encryption || job?.encryption || '').trim() || storageT('storage.unknown');
}

function renderStorageRepositoryDetailsPanel(repo, job) {
  const path = repo.path_display || repo.path_raw || repo.repo_uri || repo.repo_path || '';
  const repositoryKey = String(repo.repository_key || '').trim();
  const pruneDisabled = !job ? ' disabled' : '';
  return `<div class="storage-repository-detail-card">
    <div class="storage-repository-detail-grid">
      ${storageDetailItem('storage.repositoryNameLabel', storageRepositoryName(repo))}
      ${storageDetailItem('storage.storageNameLabel', storageName(repo))}
      ${storageDetailItem('storage.jobNameLabel', storageJobName(repo, job))}
      ${storageDetailItem('storage.path', path, 'span-2')}
      ${storageDetailItem('storage.repositoryEncryption', storageRepositoryEncryption(repo, job))}
      ${storageDetailItem('storage.repositoryRelativePath', repo.relative_path || '')}
    </div>
    ${renderRepositoryStats(repo)}
    <div class="storage-repository-maintenance">
      <div>
        <strong>${escHtml(storageT('storage.repositoryMaintenance'))}</strong>
        <small>${escHtml(storageT('storage.repositoryMaintenanceHint'))}</small>
      </div>
      <div class="storage-row-actions">
        <button class="btn btn-secondary btn-sm" data-storage-action="repository-info" data-repository-key="${escHtml(repositoryKey)}">${escHtml(storageT('storage.repositoryRefreshInfo'))}</button>
        <button class="btn btn-secondary btn-sm" data-storage-action="repository-maintenance" data-repository-key="${escHtml(repositoryKey)}" data-repository-action="check" data-check-mode="quick">${escHtml(storageT('storage.repositoryCheck'))}</button>
        <button class="btn btn-secondary btn-sm" data-storage-action="repository-maintenance" data-repository-key="${escHtml(repositoryKey)}" data-repository-action="check" data-check-mode="verify_data">${escHtml(storageT('storage.repositoryVerifyData'))}</button>
        <button class="btn btn-secondary btn-sm" data-storage-action="repository-maintenance" data-repository-key="${escHtml(repositoryKey)}" data-repository-action="prune"${pruneDisabled}>${escHtml(storageT('storage.repositoryPrune'))}</button>
        <button class="btn btn-secondary btn-sm" data-storage-action="repository-maintenance" data-repository-key="${escHtml(repositoryKey)}" data-repository-action="compact">${escHtml(storageT('storage.repositoryCompact'))}</button>
      </div>
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
  if (action === 'repository-maintenance') {
    return checkRun(
      el.dataset.repositoryKey || '',
      el.dataset.repositoryAction || 'check',
      el.dataset.checkMode || 'quick',
    );
  }
  if (action === 'repository-info') {
    return refreshRepositoryInfo(el.dataset.repositoryKey || '', el);
  }
}

async function refreshRepositoryInfo(repositoryKey, button) {
  if (!repositoryKey) return;
  if (button) button.disabled = true;
  try {
    const response = await fetch('/api/repositories/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository_key: repositoryKey }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
    await refreshStorage();
    showMsg('storage-message', 'success', storageT('storage.repositoryInfoUpdated'));
  } catch (error) {
    showMsg('storage-message', 'error', error.message || storageT('storage.error'));
  } finally {
    if (button) button.disabled = false;
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

window.BBUI.repositoryManagerState = window.BBUI.repositoryManagerState || {
  step: 1,
  storageKey: '',
};
const repositoryManagerState = window.BBUI.repositoryManagerState;

function repositoryManagerRenderStep(step) {
  const target = Math.max(1, Math.min(3, Number(step) || 1));
  repositoryManagerState.step = target;
  [1, 2, 3].forEach((number) => {
    document.getElementById(`repository-manager-step-${number}`)?.classList.toggle('hidden', number !== target);
    const dot = document.getElementById(`repository-manager-dot-${number}`);
    dot?.classList.toggle('is-active', number === target);
    dot?.classList.toggle('is-complete', number < target);
  });
  document.getElementById('repository-manager-back-btn')?.classList.toggle('hidden', target === 1);
  document.getElementById('repository-manager-next-btn')?.classList.toggle('hidden', target === 3);
  document.getElementById('repository-manager-save-btn')?.classList.toggle('hidden', target !== 3);
  if (target === 3) repositoryManagerUpdateSummary();
}

function repositoryManagerStorageModeChanged() {
  const isNew = document.getElementById('repository-manager-storage-mode')?.value === 'new';
  document.getElementById('repository-manager-existing-storage-group')?.classList.toggle('hidden', isNew);
  document.getElementById('repository-manager-new-storage')?.classList.toggle('hidden', !isNew);
  repositoryManagerStorageTypeChanged();
}

function repositoryManagerStorageTypeChanged() {
  const type = document.getElementById('repository-manager-storage-type')?.value || 'local';
  document.querySelectorAll('[data-storage-fields]').forEach((el) => {
    el.classList.toggle('hidden', el.dataset.storageFields !== type);
  });
}

async function repositoryManagerLoadPathOptions() {
  const target = document.getElementById('repository-manager-path-options');
  if (!target) return;
  try {
    const responses = await Promise.all(['/mnt', '/mnt/disks'].map((prefix) =>
      fetch(`/api/wizard/source-dirs?prefix=${encodeURIComponent(prefix)}&limit=100`)
        .then((response) => response.ok ? response.json() : { dirs: [] })
        .catch(() => ({ dirs: [] }))));
    const paths = Array.from(new Set(responses.flatMap((payload) =>
      (Array.isArray(payload?.dirs) ? payload.dirs : []).map((row) => String(row?.path || '').trim()).filter(Boolean))));
    target.innerHTML = paths.map((path) => `<option value="${escHtml(path)}"></option>`).join('');
  } catch (_) {
    target.innerHTML = '';
  }
}

function repositoryManagerSyncFields() {
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const encryption = document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2';
  document.getElementById('repository-manager-encryption-group')?.classList.toggle('hidden', action !== 'create');
  document.getElementById('repository-manager-passphrase-group')
    ?.classList.toggle('hidden', action === 'create' && encryption === 'none');
  ['repository-manager-storage-quota', 'repository-manager-append-only', 'repository-manager-make-parent-dirs'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = action !== 'create';
  });
  document.getElementById('repository-manager-storage-quota')?.closest('.form-group')?.classList.toggle('hidden', action !== 'create');
  document.querySelector('.repository-manager-checks')?.classList.toggle('hidden', action !== 'create');
  const encryptionDescription = document.getElementById('repository-manager-encryption-description');
  if (encryptionDescription) {
    const family = encryption.startsWith('keyfile')
      ? 'Keyfile'
      : (encryption.startsWith('authenticated') ? 'Authenticated' : (encryption === 'none' ? 'None' : 'Repokey'));
    encryptionDescription.textContent = storageT(`storage.repositoryEncryption${family}Hint`);
  }
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

function repositoryManagerSelectedStorageKey() {
  return String(repositoryManagerState.storageKey || document.getElementById('repository-manager-storage')?.value || '').trim();
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
  const encryption = action === 'import'
    ? storageT('storage.repositoryEncryptionAutomatic')
    : String(document.getElementById('repository-manager-encryption')?.value || '').trim();
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
    'repository-manager-storage-mode': 'existing',
    'repository-manager-storage-type': 'local',
    'repository-manager-storage-name': '',
    'repository-manager-local-path': '/mnt/backup',
    'repository-manager-usb-path': '',
    'repository-manager-smb-server': '',
    'repository-manager-smb-share': '',
    'repository-manager-smb-user': '',
    'repository-manager-smb-password': '',
    'repository-manager-smb-version': '3.0',
    'repository-manager-ssh-host': '',
    'repository-manager-ssh-port': '23',
    'repository-manager-ssh-user': '',
    'repository-manager-ssh-base': './backup',
    'repository-manager-ssh-key': '/root/.ssh/id_rsa',
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
  const appendOnly = document.getElementById('repository-manager-append-only');
  const parentDirs = document.getElementById('repository-manager-make-parent-dirs');
  if (appendOnly) appendOnly.checked = false;
  if (parentDirs) parentDirs.checked = true;
  repositoryManagerState.storageKey = '';
  repositoryManagerLoadPathOptions();
  repositoryManagerStorageModeChanged();
  repositoryManagerSyncFields();
  repositoryManagerRenderStep(1);
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

function repositoryManagerNameFromRelativePath(value) {
  const path = repositoryManagerSlug(value);
  const parts = path.split('/').map((part) => part.trim()).filter(Boolean);
  return parts[parts.length - 1] || path;
}

function repositoryManagerPathChanged() {
  const repoName = document.getElementById('repository-manager-repository-name');
  const relative = document.getElementById('repository-manager-relative-path');
  if (!repoName || !relative) return;
  relative.value = repositoryManagerSlug(relative.value);
  repoName.value = repositoryManagerNameFromRelativePath(relative.value);
  repositoryManagerUpdateSummary();
}

function repositoryManagerNewStoragePayload() {
  const type = document.getElementById('repository-manager-storage-type')?.value || 'local';
  const payload = {
    storage_type: type,
    display_name: document.getElementById('repository-manager-storage-name')?.value || '',
  };
  if (type === 'local') payload.base_path = document.getElementById('repository-manager-local-path')?.value || '';
  if (type === 'usb') payload.mount_path = document.getElementById('repository-manager-usb-path')?.value || '';
  if (type === 'smb') Object.assign(payload, {
    server: document.getElementById('repository-manager-smb-server')?.value || '',
    share: document.getElementById('repository-manager-smb-share')?.value || '',
    username: document.getElementById('repository-manager-smb-user')?.value || '',
    password: document.getElementById('repository-manager-smb-password')?.value || '',
    vers: document.getElementById('repository-manager-smb-version')?.value || '3.0',
  });
  if (type === 'storagebox') Object.assign(payload, {
    host: document.getElementById('repository-manager-ssh-host')?.value || '',
    port: document.getElementById('repository-manager-ssh-port')?.value || '23',
    user: document.getElementById('repository-manager-ssh-user')?.value || '',
    base_path: document.getElementById('repository-manager-ssh-base')?.value || './backup',
    ssh_key_path: document.getElementById('repository-manager-ssh-key')?.value || '/root/.ssh/id_rsa',
  });
  return payload;
}

async function repositoryManagerPrepareStorage() {
  const mode = document.getElementById('repository-manager-storage-mode')?.value || 'existing';
  let storageKey = document.getElementById('repository-manager-storage')?.value || '';
  if (mode === 'new') {
    const createResponse = await fetch('/api/storages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(repositoryManagerNewStoragePayload()),
    });
    const created = await createResponse.json();
    if (!createResponse.ok) throw new Error(apiErrorMessage(created, createResponse.status));
    storageKey = String(created?.storage?.storage_key || '').trim();
    if (!storageKey) throw new Error(storageT('storage.storageTargetCreateFailed'));
    await refreshStorage();
    repositoryManagerFillStorages();
    const select = document.getElementById('repository-manager-storage');
    if (select) select.value = storageKey;
    repositoryManagerState.storageKey = storageKey;
    const modeSelect = document.getElementById('repository-manager-storage-mode');
    if (modeSelect) modeSelect.value = 'existing';
    repositoryManagerStorageModeChanged();
  }
  if (!storageKey) throw new Error(storageT('storage.storageTargetRequired'));
  const testResponse = await fetch('/api/storages/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ storage_key: storageKey }),
  });
  const tested = await testResponse.json();
  if (!testResponse.ok || !tested.ok) {
    throw new Error(apiMessage(tested?.details || tested, storageT('storage.storageTargetTestFailed')));
  }
  repositoryManagerState.storageKey = storageKey;
  return storageKey;
}

async function repositoryManagerNext() {
  repositoryManagerSetMessage('', '');
  const button = document.getElementById('repository-manager-next-btn');
  if (button) button.disabled = true;
  try {
    if (repositoryManagerState.step === 1) {
      await repositoryManagerPrepareStorage();
      repositoryManagerRenderStep(2);
      return;
    }
    repositoryManagerPathChanged();
    const action = document.getElementById('repository-manager-action')?.value || 'create';
    const displayName = String(document.getElementById('repository-manager-display-name')?.value || '').trim();
    const relativePath = String(document.getElementById('repository-manager-relative-path')?.value || '').trim();
    const encryption = document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2';
    const passphrase = String(document.getElementById('repository-manager-passphrase')?.value || '').trim();
    if (!displayName || !relativePath) throw new Error(storageT('storage.repositoryIdentityRequired'));
    if (action === 'create' && encryption !== 'none' && !passphrase) {
      throw new Error(storageT('storage.repositoryPassphraseRequired'));
    }
    repositoryManagerRenderStep(3);
  } catch (err) {
    repositoryManagerSetMessage('error', err.message || storageT('storage.error'));
  } finally {
    if (button) button.disabled = false;
  }
}

function repositoryManagerBack() {
  repositoryManagerSetMessage('', '');
  repositoryManagerRenderStep(repositoryManagerState.step - 1);
}

async function saveRepositoryManager() {
  repositoryManagerSetMessage('', '');
  repositoryManagerPathChanged();
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const payload = {
    action,
    storage_key: repositoryManagerSelectedStorageKey(),
    display_name: document.getElementById('repository-manager-display-name')?.value || '',
    repository_name: document.getElementById('repository-manager-repository-name')?.value || '',
    relative_path: document.getElementById('repository-manager-relative-path')?.value || '',
    encryption: action === 'import' ? 'auto' : (document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2'),
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

function _checkModeLabel(mode, action = 'check') {
  if (action === 'prune') return storageT('storage.repositoryPrune');
  if (action === 'compact') return storageT('storage.repositoryCompact');
  if (mode === 'verbose') return storageT('storage.check.modeVerbose');
  if (mode === 'verify_data') return storageT('storage.check.modeVerifyData');
  return storageT('storage.check.modeQuick');
}

function _appendCheckLog(rawLine) {
  const logEl = document.getElementById('check-log-output');
  if (!logEl) return;
  const normalized = String(rawLine ?? '').replace(/\r/g, '\n');
  logEl.append(document.createTextNode(`${normalized}\n`));
  logEl.scrollTop = logEl.scrollHeight;
}

async function checkRun(repositoryKey, action = 'check', mode = 'quick') {
  if (!repositoryKey) return;
  if (['prune', 'compact', 'verify_data'].includes(action === 'check' ? mode : action)) {
    const confirmKey = action === 'prune'
      ? 'storage.repositoryPruneConfirm'
      : (action === 'compact' ? 'storage.repositoryCompactConfirm' : 'storage.repositoryVerifyConfirm');
    if (!window.confirm(storageT(confirmKey))) return;
  }
  hideEl('check-message');
  const logPanel = document.getElementById('check-log-panel');
  if (logPanel) logPanel.classList.remove('hidden');
  const logEl = document.getElementById('check-log-output');
  const statusEl = document.getElementById('check-log-status');
  if (logEl) logEl.textContent = '';
  if (statusEl) {
    statusEl.textContent = storageT('storage.check.running', { mode: _checkModeLabel(mode, action) });
    statusEl.className = 'check-log-status running';
  }

  if (checkState.es) { checkState.es.close(); checkState.es = null; }

  try {
    const res = await fetch('/api/storage/check/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository_key: repositoryKey, action, mode }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      showMsg('check-message', 'error', err.error || `HTTP ${res.status}`);
      return;
    }
  } catch (err) {
    showMsg('check-message', 'error', storageT('storage.errorPrefix', { message: err.message }));
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
  });

  es.addEventListener('error', (e) => {
    if (e.data) _appendCheckLog(storageT('storage.check.logError', { message: e.data }));
    if (statusEl) { statusEl.textContent = storageT('storage.error'); statusEl.className = 'check-log-status error'; }
    es.close(); checkState.es = null;
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
}

window.addEventListener('bbui:language-changed', () => {
  if (storageState.loaded && storageState.data) renderStorage(storageState.data);
});
