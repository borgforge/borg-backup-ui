// ══════════════════════════════════════════════════════════════════════════════
// STORAGE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.storageState = window.BBUI.storageState || {
  loaded: false,
  data: null,
  jobs: [],
  selectedRepositoryKey: '',
  selectedTab: 'overview',
  archiveCache: {},
  lifecycleCache: {},
  maintenanceState: { running: false },
  search: '',
};
const storageState = window.BBUI.storageState;
storageState.archiveCache = storageState.archiveCache || {};
storageState.lifecycleCache = storageState.lifecycleCache || {};
storageState.maintenanceState = storageState.maintenanceState || { running: false };
storageState.maintenanceConfirmation = null;
storageState.lifecycleConfirmation = null;

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
  return String(
    repo?.display_name
    || repo?.repository_name
    || job?.name
    || storageTypeLabel(repo)
    || repo?.repository_key
    || '',
  ).trim();
}

function storageRepositoryName(repo) {
  const explicit = String(repo?.repository_name || '').trim();
  if (explicit) return explicit;
  const path = String(repo?.path_display || repo?.path_raw || '').trim().replace(/\/+$/, '');
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
  const query = String(storageState.search || '').trim().toLocaleLowerCase();
  return storageRepositories(data).filter((repo) => {
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
    const [storageRes, jobsRes, maintenanceRes] = await Promise.all([
      fetch('/api/storage'),
      fetch('/api/jobs'),
      fetch('/api/storage/check/state'),
    ]);
    if (!storageRes.ok) throw new Error(`HTTP ${storageRes.status}`);
    storageState.data = await storageRes.json();
    storageState.jobs = jobsRes.ok ? (await jobsRes.json()).jobs || [] : [];
    storageState.maintenanceState = maintenanceRes.ok ? await maintenanceRes.json() : { running: false };
    storageState.loaded = true;
    renderStorage(storageState.data);
    if (storageState.selectedTab === 'management' && storageState.selectedRepositoryKey) {
      await loadRepositoryLifecycle(storageState.selectedRepositoryKey, true);
    }
  } catch (err) {
    showMsg('storage-message', 'error', storageT('storage.errorPrefix', { message: err.message }));
  }
}

function renderStorage(data) {
  const el = document.getElementById('storage-content');
  if (!el) return;
  const visible = storageVisibleRepositories(data);
  if (!visible.some((repo) => String(repo.repository_key || '') === storageState.selectedRepositoryKey)) {
    storageState.selectedRepositoryKey = String(visible[0]?.repository_key || '');
  }
  renderStorageLocationSidebar(data, visible);
  const repo = visible.find((row) => String(row.repository_key || '') === storageState.selectedRepositoryKey) || null;
  const job = repo ? storageJobForRepository(repo) : null;
  renderStorageWorkspaceHeader(repo, job);
  el.innerHTML = repo
    ? renderStorageRepositoryWorkspace(repo, job)
    : `<section class="ui-panel storage-empty">${storageT('storage.noMatchingRepositories')}</section>`;
}

function storageRepositoryKey(repo) {
  return String(repo?.repository_key || repo?.conf_key || repo?.path_raw || '').trim();
}

function storageRepositoryStatus(repo) {
  const running = storageState.maintenanceState?.running
    && String(storageState.maintenanceState?.target_key || '') === storageRepositoryKey(repo);
  if (running) return { className: 'info', label: storageT('storage.repositoryStatusRunning') };
  const results = Object.values(repo?.maintenance_results || {}).filter((row) => row && typeof row === 'object');
  const latest = results.sort((a, b) => String(b.finished_at || '').localeCompare(String(a.finished_at || '')))[0];
  if (latest?.status === 'error') return { className: 'error', label: storageT('storage.repositoryStatusError') };
  if (latest?.status === 'warning') return { className: 'warning', label: storageT('storage.repositoryStatusWarning') };
  if (String(repo?.last_info_refresh_status || '').toLowerCase() === 'busy') {
    return { className: 'info', label: storageT('storage.repositoryStatusBusy') };
  }
  if (String(repo?.last_info_refresh_status || '').toLowerCase() === 'error') {
    return { className: 'warning', label: storageT('storage.repositoryStatusWarning') };
  }
  return { className: 'success', label: storageT('storage.repositoryStatusReady') };
}

function storageRepositoryIcon(repo, job, large = false) {
  const icon = typeof resolveJobIcon === 'function' ? resolveJobIcon(job || repo) : repo?.backup_type;
  const color = typeof resolveJobIconColor === 'function' ? resolveJobIconColor(job || repo) : '';
  const colorClass = color ? ` type-icon-color-${color}` : '';
  return `<span class="type-icon type-icon-${escHtml(String(repo?.backup_type || 'sonstiges').toLowerCase())}${colorClass}${large ? ' storage-repository-icon-large' : ''}">${typeIcon(icon)}</span>`;
}

function storageGroupRows(data, repos) {
  const targets = storageTargets(data);
  const groups = [];
  targets.forEach((target) => {
    const rows = repos.filter((repo) => String(repo.storage_key || '') === String(target.storage_key || ''));
    if (rows.length) groups.push({ target, rows });
  });
  const assigned = new Set(groups.flatMap((group) => group.rows.map((repo) => storageRepositoryKey(repo))));
  STORAGE_LOCATION_ORDER.forEach((location) => {
    const rows = repos.filter((repo) => repo.location === location && !assigned.has(storageRepositoryKey(repo)));
    if (rows.length) groups.push({ target: { display_name: storageLocationLabel(location), location }, rows });
  });
  return groups;
}

function renderStorageLocationSidebar(data, repos) {
  const nav = document.getElementById('storage-location-list');
  if (!nav) return;
  const groups = storageGroupRows(data, repos);
  nav.innerHTML = `
    <div class="storage-repository-search">
      <input id="storage-sidebar-search" class="form-input" type="search"
        value="${escHtml(storageState.search || '')}"
        placeholder="${escHtml(storageT('storage.searchPlaceholder'))}"
        aria-label="${escHtml(storageT('storage.searchPlaceholder'))}">
    </div>
    ${groups.map(({ target, rows }) => {
      const location = String(target.location || target.storage_type || rows[0]?.location || 'local').toLowerCase();
      const targetName = String(target.display_name || storageLocationLabel(location));
      return `<section class="storage-repository-nav-group">
        <header>
          <span class="location-nav-glyph ${escHtml(location)}">${storageLocationIcon(location)}</span>
          <strong>${escHtml(targetName)}</strong>
          <span class="badge neutral">${rows.length}</span>
        </header>
        ${rows.map((repo) => {
          const key = storageRepositoryKey(repo);
          const job = storageJobForRepository(repo);
          const active = key === storageState.selectedRepositoryKey;
          const status = storageRepositoryStatus(repo);
          return `<button class="storage-repository-nav-item ${active ? 'is-active' : ''}"
            type="button" data-storage-repository-key="${escHtml(key)}" ${active ? 'aria-current="page"' : ''}>
            ${storageRepositoryIcon(repo, job)}
            <span><strong>${escHtml(storageRepositoryTitle(repo, job))}</strong><small>${escHtml(storageRepositoryName(repo))}</small></span>
            <i class="storage-repository-status-dot ${status.className}" title="${escHtml(status.label)}"></i>
          </button>`;
        }).join('')}
      </section>`;
    }).join('')}`;
}

function onStorageLocationClick(event) {
  const button = event.target.closest('[data-storage-repository-key]');
  if (!button || !storageState.data) return;
  storageState.selectedRepositoryKey = button.dataset.storageRepositoryKey || '';
  storageState.selectedTab = 'overview';
  renderStorage(storageState.data);
}

function onStorageSearchInput(event) {
  if (event.target.id !== 'storage-sidebar-search' || !storageState.data) return;
  storageState.search = event.target.value || '';
  renderStorage(storageState.data);
  const input = document.getElementById('storage-sidebar-search');
  input?.focus();
  input?.setSelectionRange(storageState.search.length, storageState.search.length);
}

function renderStorageWorkspaceHeader(repo, job) {
  const header = document.getElementById('storage-workspace-header');
  if (!header) return;
  if (!repo) {
    header.innerHTML = `<div class="ui-workspace-header__title"><small>${storageT('storage.overview')}</small><h2>${storageT('storage.repositories')}</h2><span class="ui-workspace-header__subtitle">${storageT('storage.noMatchingRepositories')}</span></div>`;
    return;
  }
  const status = storageRepositoryStatus(repo);
  const infoUpdatedAt = repo.last_info_refresh_at || repo.last_seen_at || '';
  const infoState = infoUpdatedAt
    ? storageT('storage.repositoryInfoLastUpdated', { date: storageFormatDateTime(infoUpdatedAt) })
    : storageT('storage.repositoryInfoPending');
  header.innerHTML = `
    <div class="storage-repository-workspace-identity">
      ${storageRepositoryIcon(repo, job, true)}
      <span><small>${storageT('storage.repository')}</small><h2>${escHtml(storageRepositoryTitle(repo, job))}</h2><span><b>${escHtml(storageT('storage.repositoryPathLabel'))}:</b> ${escHtml(repo.path_display || repo.path_raw || '')}</span></span>
    </div>
    <div class="storage-repository-workspace-status"><span class="badge ${status.className}">${escHtml(status.label)}</span><small>${escHtml(infoState)}</small></div>`;
}

function storageFormatDateTime(value) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString(document.documentElement.lang === 'en' ? 'en-GB' : 'de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function storageFormatDuration(value, startedAt = '', finishedAt = '') {
  const seconds = Math.max(0, Number(value || 0));
  const started = startedAt ? new Date(startedAt) : null;
  const finished = finishedAt ? new Date(finishedAt) : null;
  if (started && finished && !Number.isNaN(started.getTime()) && !Number.isNaN(finished.getTime()) && finished < started) {
    return '—';
  }
  if (seconds === 0 && started && finished) return storageT('storage.durationLessThanSecond');
  if (seconds < 60) return storageT('storage.durationSeconds', { count: Math.round(seconds) });
  return storageT('storage.durationMinutes', { count: Math.round(seconds / 60) });
}

function storageMaintenanceResult(repo, key) {
  const value = repo?.maintenance_results?.[key];
  return value && typeof value === 'object' ? value : null;
}

function storageMaintenanceRunning(repo, key) {
  const state = storageState.maintenanceState || {};
  if (!state.running || String(state.target_key || '') !== storageRepositoryKey(repo)) return false;
  const activeKey = state.action === 'check' && state.mode === 'verify_data' ? 'verify_data' : state.action;
  return activeKey === key;
}

function storageMaintenanceTitle(key) {
  return {
    check: storageT('storage.repositoryCheck'),
    verify_data: storageT('storage.repositoryVerifyData'),
    prune: storageT('storage.repositoryPrune'),
    compact: storageT('storage.repositoryCompact'),
  }[key] || key;
}

function storageMaintenanceSummary(key, result) {
  if (!result) return storageT('storage.repositoryNotRun');
  if (result.failure_code === 'borg_ssh_connection_interrupted') {
    return storageT('storage.repositorySshInterrupted');
  }
  if (result.status === 'error') return storageT('storage.repositoryActionFailed');
  if (result.status === 'warning') return storageT('storage.repositoryActionWarning');
  if (key === 'prune') {
    return storageT('storage.repositoryPruneResult', { count: Number(result.deleted_archives_count || 0) });
  }
  if (key === 'compact') {
    return result.freed_space
      ? storageT('storage.repositoryCompactResult', { value: result.freed_space })
      : storageT('storage.repositoryCompactDone');
  }
  return storageT('storage.repositoryCheckSuccessful');
}

function renderStorageMaintenanceCard(repo, key, { withAction = false, job = null } = {}) {
  const running = storageMaintenanceRunning(repo, key);
  const result = storageMaintenanceResult(repo, key);
  const status = running ? 'running' : (result?.status || 'idle');
  const repositoryKey = storageRepositoryKey(repo);
  const action = key === 'verify_data' ? 'check' : key;
  const mode = key === 'verify_data' ? 'verify_data' : 'quick';
  const disabled = key === 'prune' && !job ? ' disabled' : '';
  const details = Array.isArray(result?.details) ? result.details : [];
  const deletedArchives = Array.isArray(result?.deleted_archives) ? result.deleted_archives : [];
  const userHint = result?.failure_code === 'borg_ssh_connection_interrupted'
    ? `<p class="storage-maintenance-user-hint">${escHtml(storageT('storage.repositorySshInterruptedHint'))}</p>`
    : '';
  const resultDetails = details.length
    ? `<details class="storage-maintenance-result-details status-error"><summary>${escHtml(storageT('storage.repositoryErrorDetails'))}</summary><pre>${escHtml(details.join('\n'))}</pre></details>`
    : (key === 'prune' && deletedArchives.length
      ? `<details class="storage-maintenance-result-details"><summary>${escHtml(storageT('storage.repositoryPruneDetails', { count: deletedArchives.length }))}</summary><ul>${deletedArchives.map((archive) => `<li>${escHtml(archive)}</li>`).join('')}</ul></details>`
      : '');
  return `<article class="storage-maintenance-card status-${escHtml(status)}">
    <span class="storage-maintenance-icon">${running ? '…' : (status === 'success' ? '✓' : (status === 'error' ? '!' : (status === 'warning' ? '!' : '·')))}</span>
    <div class="storage-maintenance-copy">
      <small>${escHtml(storageMaintenanceTitle(key))}</small>
      <strong>${escHtml(running ? storageT('storage.repositoryActionRunning') : storageMaintenanceSummary(key, result))}</strong>
      <span>${running ? storageT('storage.repositoryPleaseWait') : (result ? `${storageFormatDateTime(result.finished_at)} · ${storageFormatDuration(result.duration_seconds, result.started_at, result.finished_at)}` : storageT('storage.repositoryNoResult'))}</span>
      ${userHint}
      ${resultDetails}
    </div>
    ${withAction ? `<button class="btn btn-secondary btn-sm" data-storage-action="repository-maintenance" data-repository-key="${escHtml(repositoryKey)}" data-repository-action="${escHtml(action)}" data-check-mode="${escHtml(mode)}"${disabled}>${escHtml(running ? storageT('storage.repositoryRunning') : storageT('storage.repositoryStartAction'))}</button>` : ''}
  </article>`;
}

function renderStorageRepositoryOverview(repo, job) {
  const infoError = String(repo?.last_info_refresh_error || '').trim();
  const infoBusy = String(repo?.last_info_refresh_status || '').toLowerCase() === 'busy';
  const stats = renderRepositoryStats(repo) || `<div class="storage-repository-empty-state"><p>${storageT(infoBusy ? 'storage.repositoryInfoBusy' : 'storage.repositoryInfoMissing')}</p>${!infoBusy && infoError ? `<small>${escHtml(infoError)}</small>` : ''}<button class="btn btn-secondary btn-sm" data-storage-action="repository-info" data-repository-key="${escHtml(storageRepositoryKey(repo))}">${storageT('storage.repositoryRefreshInfo')}</button></div>`;
  return `<div class="storage-repository-overview">
    ${stats}
    <div class="storage-section-heading"><div><h3>${storageT('storage.repositoryHealth')}</h3><p>${storageT('storage.repositoryHealthHint')}</p></div><button class="btn btn-secondary btn-sm" data-storage-action="repository-info" data-repository-key="${escHtml(storageRepositoryKey(repo))}">${storageT('storage.repositoryRefreshInfo')}</button></div>
    <div class="storage-maintenance-summary-grid">
      ${renderStorageMaintenanceCard(repo, 'check')}
      ${renderStorageMaintenanceCard(repo, 'prune', { job })}
      ${renderStorageMaintenanceCard(repo, 'compact')}
    </div>
    <div class="storage-section-heading"><div><h3>${storageT('storage.repositoryDetails')}</h3><p>${storageT('storage.repositoryDetailsHint')}</p></div></div>
    <div class="storage-repository-detail-grid storage-repository-facts">
      ${storageDetailItem('storage.repositoryDisplayNameLabel', storageRepositoryTitle(repo, job))}
      ${storageDetailItem('storage.repositoryDirectoryLabel', storageRepositoryName(repo))}
      ${storageDetailItem('storage.storageNameLabel', storageName(repo))}
      ${storageDetailItem('storage.jobNameLabel', storageJobName(repo, job))}
      ${storageDetailItem('storage.repositoryEncryption', storageRepositoryEncryption(repo, job))}
      ${storageDetailItem('storage.repositoryPathLabel', repo.path_display || repo.path_raw || '', 'span-3')}
    </div>
  </div>`;
}

function renderStorageRepositoryArchives(repo) {
  const key = storageRepositoryKey(repo);
  const cache = storageState.archiveCache[key];
  if (!cache || cache.loading) return `<div class="storage-repository-loading"><div class="spinner"></div><span>${storageT('storage.repositoryArchivesLoading')}</span></div>`;
  if (cache.error) return `<div class="status-message error">${escHtml(cache.error)}</div>`;
  const archives = Array.isArray(cache.data?.archives) ? cache.data.archives : [];
  if (!archives.length) return `<div class="storage-repository-empty-state"><p>${storageT('storage.repositoryNoArchives')}</p></div>`;
  return `<div class="storage-archive-toolbar"><strong>${storageCount(cache.data.archive_count || archives.length, 'storage.archiveCountOne', 'storage.archiveCountMany')}</strong><button class="btn btn-secondary btn-sm" data-storage-action="refresh-repository-archives" data-repository-key="${escHtml(key)}">${storageT('storage.refresh')}</button></div>
    <div class="storage-archive-list"><header><span></span><strong>${storageT('storage.repositoryArchiveName')}</strong><strong>${storageT('storage.repositoryArchiveCreated')}</strong></header>${archives.map((archive) => `<article><span class="storage-archive-dot"></span><div><strong>${escHtml(archive.name || '—')}</strong><small>${escHtml(archive.id || '')}</small></div><time>${escHtml(storageFormatDateTime(archive.start))}</time></article>`).join('')}</div>`;
}

function renderStorageRepositoryMaintenance(repo, job) {
  return `<div class="storage-maintenance-page">
    <div class="storage-section-heading"><div><h3>${storageT('storage.repositoryMaintenance')}</h3><p>${storageT('storage.repositoryMaintenanceHint')}</p></div></div>
    <div class="storage-maintenance-action-grid">
      ${renderStorageMaintenanceCard(repo, 'check', { withAction: true, job })}
      ${renderStorageMaintenanceCard(repo, 'verify_data', { withAction: true, job })}
      ${renderStorageMaintenanceCard(repo, 'prune', { withAction: true, job })}
      ${renderStorageMaintenanceCard(repo, 'compact', { withAction: true, job })}
    </div>
  </div>`;
}

function storageLifecycleJobLabel(jobKey) {
  const job = (storageState.jobs || []).find((row) => String(row.key || '') === String(jobKey || ''));
  return String(job?.display_name || job?.name || jobKey || '').trim();
}

function renderStorageRepositoryManagement(repo) {
  const key = storageRepositoryKey(repo);
  const state = storageState.lifecycleCache[key];
  if (!state || state.loading) {
    return `<div class="storage-repository-loading"><div class="spinner"></div><span>${storageT('storage.repositoryManagementLoading')}</span></div>`;
  }
  if (state.error) {
    return `<div class="status-message error">${escHtml(state.error)}</div><button class="btn btn-secondary btn-sm" data-storage-action="refresh-repository-lifecycle" data-repository-key="${escHtml(key)}">${storageT('storage.refresh')}</button>`;
  }
  const jobs = Array.isArray(state.job_keys) ? state.job_keys : [];
  const blockers = Array.isArray(state.blockers) ? state.blockers : [];
  const blocked = !state.allowed;
  const jobList = jobs.length
    ? `<div class="storage-lifecycle-jobs"><strong>${storageT('storage.repositoryLinkedJobs')}</strong><div>${jobs.map((jobKey) => `<span>${escHtml(storageLifecycleJobLabel(jobKey))}</span>`).join('')}</div></div>`
    : `<div class="status-message success">${storageT('storage.repositoryNoLinkedJobs')}</div>`;
  const blockerText = blockers.length
    ? `<p class="storage-lifecycle-blocker">${escHtml(storageT('storage.repositoryLifecycleBlocked'))}</p>`
    : '';
  return `<div class="storage-repository-management">
    <div class="storage-section-heading"><div><h3>${storageT('storage.repositoryManagement')}</h3><p>${storageT('storage.repositoryManagementHint')}</p></div><button class="btn btn-secondary btn-sm" data-storage-action="refresh-repository-lifecycle" data-repository-key="${escHtml(key)}">${storageT('storage.refresh')}</button></div>
    ${jobList}
    ${blockerText}
    <section class="storage-lifecycle-card">
      <div><h4>${storageT('storage.repositoryRemoveFromUi')}</h4><p>${storageT('storage.repositoryRemoveFromUiHint')}</p></div>
      <button class="btn btn-secondary" data-storage-action="repository-lifecycle" data-lifecycle-mode="remove" data-repository-key="${escHtml(key)}"${blocked ? ' disabled' : ''}>${storageT('storage.repositoryRemoveFromUi')}</button>
    </section>
    <section class="storage-lifecycle-card danger">
      <div><h4>${storageT('storage.repositoryDangerZone')}</h4><p>${storageT('storage.repositoryDeletePermanentHint')}</p></div>
      <dl><div><dt>${storageT('storage.repositoryPathLabel')}</dt><dd>${escHtml(state.repository_path || repo.path_display || repo.path_raw || '')}</dd></div><div><dt>${storageT('storage.repositoryArchiveCount')}</dt><dd>${Number(state.archive_count || 0)}</dd></div><div><dt>${storageT('storage.repositoryDeduplicatedSize')}</dt><dd>${storageFormatBytes(state.deduplicated_size)}</dd></div></dl>
      <button class="btn-danger" data-storage-action="repository-lifecycle" data-lifecycle-mode="delete" data-repository-key="${escHtml(key)}"${blocked ? ' disabled' : ''}>${storageT('storage.repositoryDeletePermanent')}</button>
    </section>
  </div>`;
}

function renderStorageRepositoryWorkspace(repo, job) {
  const selected = ['overview', 'archives', 'maintenance', 'management'].includes(storageState.selectedTab)
    ? storageState.selectedTab
    : 'overview';
  storageState.selectedTab = selected;
  const archiveCount = Number(repo?.repository_stats?.archives_count || 0);
  const tabs = [
    ['overview', storageT('storage.repositoryTabOverview')],
    ['archives', `${storageT('storage.repositoryTabArchives')} ${archiveCount ? `<b>${archiveCount}</b>` : ''}`],
    ['maintenance', storageT('storage.repositoryTabMaintenance')],
    ['management', storageT('storage.repositoryTabManagement')],
  ];
  const content = selected === 'archives'
    ? renderStorageRepositoryArchives(repo)
    : (selected === 'maintenance'
      ? renderStorageRepositoryMaintenance(repo, job)
      : (selected === 'management'
        ? renderStorageRepositoryManagement(repo)
        : renderStorageRepositoryOverview(repo, job)));
  return `<section class="storage-repository-master-detail ui-panel">
    <nav class="storage-repository-tabs">${tabs.map(([key, label]) => `<button class="${selected === key ? 'is-active' : ''}" data-storage-action="select-repository-tab" data-repository-tab="${key}">${label}</button>`).join('')}</nav>
    <div class="storage-repository-tab-content">${content}</div>
  </section>`;
}

async function loadRepositoryArchives(repositoryKey, force = false) {
  const key = String(repositoryKey || '').trim();
  if (!key || (!force && storageState.archiveCache[key])) return;
  storageState.archiveCache[key] = { loading: true };
  if (storageState.data && storageState.selectedRepositoryKey === key) renderStorage(storageState.data);
  try {
    const response = await fetch(`/api/repositories/archives?repository_key=${encodeURIComponent(key)}&limit=100`);
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
    storageState.archiveCache[key] = { loading: false, data };
  } catch (error) {
    storageState.archiveCache[key] = { loading: false, error: error.message || storageT('storage.error') };
  }
  if (storageState.data && storageState.selectedRepositoryKey === key && storageState.selectedTab === 'archives') renderStorage(storageState.data);
}

async function loadRepositoryLifecycle(repositoryKey, force = false) {
  const key = String(repositoryKey || '').trim();
  if (!key || (!force && storageState.lifecycleCache[key])) return;
  storageState.lifecycleCache[key] = { loading: true };
  if (storageState.data && storageState.selectedRepositoryKey === key) renderStorage(storageState.data);
  try {
    const response = await fetch('/api/repositories/lifecycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository_key: key, mode: 'remove' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
    storageState.lifecycleCache[key] = { loading: false, ...data };
  } catch (error) {
    storageState.lifecycleCache[key] = { loading: false, error: error.message || storageT('storage.error') };
  }
  if (storageState.data && storageState.selectedRepositoryKey === key && storageState.selectedTab === 'management') renderStorage(storageState.data);
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

function onStorageContentClick(event) {
  const el = event.target.closest('[data-storage-action]');
  if (!el) return;
  const action = el.dataset.storageAction || '';
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
  if (action === 'select-repository-tab') {
    storageState.selectedTab = el.dataset.repositoryTab || 'overview';
    renderStorage(storageState.data);
    if (storageState.selectedTab === 'archives') loadRepositoryArchives(storageState.selectedRepositoryKey);
    if (storageState.selectedTab === 'management') loadRepositoryLifecycle(storageState.selectedRepositoryKey);
  }
  if (action === 'refresh-repository-archives') {
    return loadRepositoryArchives(el.dataset.repositoryKey || storageState.selectedRepositoryKey, true);
  }
  if (action === 'refresh-repository-lifecycle') {
    return loadRepositoryLifecycle(el.dataset.repositoryKey || storageState.selectedRepositoryKey, true);
  }
  if (action === 'repository-lifecycle') {
    return openRepositoryLifecycle(
      el.dataset.repositoryKey || storageState.selectedRepositoryKey,
      el.dataset.lifecycleMode || 'remove',
    );
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
    if (!response.ok) {
      if (data?.code === 'repository_busy') {
        await refreshStorage();
        showMsg('storage-message', 'warning', storageT('storage.repositoryInfoBusy'));
        return;
      }
      throw new Error(apiErrorMessage(data, response.status));
    }
    await refreshStorage();
    showMsg('storage-message', 'success', storageT('storage.repositoryInfoUpdated'));
  } catch (error) {
    showMsg('storage-message', 'error', error.message || storageT('storage.error'));
  } finally {
    if (button) button.disabled = false;
  }
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
  browserPath: '',
  browserVisible: false,
};
const repositoryManagerState = window.BBUI.repositoryManagerState;
repositoryManagerState.browserPath = repositoryManagerState.browserPath || '';
repositoryManagerState.browserVisible = false;
repositoryManagerState.browserController = null;

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

function repositoryManagerSyncFields() {
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  const encryption = document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2';
  document.getElementById('repository-manager-encryption-group')?.classList.toggle('hidden', action !== 'create');
  document.getElementById('repository-manager-key-data-group')?.classList.toggle('hidden', action !== 'import');
  document.getElementById('repository-manager-passphrase-group')
    ?.classList.toggle('hidden', action === 'create' && encryption === 'none');
  ['repository-manager-storage-quota', 'repository-manager-append-only', 'repository-manager-make-parent-dirs'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = action !== 'create';
  });
  document.getElementById('repository-manager-storage-quota')?.closest('.form-group')?.classList.toggle('hidden', action !== 'create');
  document.querySelector('.repository-manager-checks')?.classList.toggle('hidden', action !== 'create');
  document.getElementById('repository-manager-browser-btn')?.classList.toggle('hidden', action !== 'import');
  document.getElementById('repository-manager-browser-hint')?.classList.toggle('hidden', action !== 'import');
  document.getElementById('repository-manager-import-compatibility-hint')?.classList.toggle('hidden', action !== 'import');
  if (action !== 'import') repositoryManagerCloseBrowser();
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
    'repository-manager-action': 'create',
    'repository-manager-display-name': '',
    'repository-manager-repository-name': '',
    'repository-manager-relative-path': '',
    'repository-manager-encryption': 'repokey-blake2',
    'repository-manager-passphrase': '',
    'repository-manager-key-data': '',
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
  repositoryManagerState.browserPath = '';
  repositoryManagerCloseBrowser();
  repositoryManagerSyncFields();
  repositoryManagerRenderStep(1);
  modal.classList.remove('hidden');
}

function closeRepositoryManager() {
  const passphrase = document.getElementById('repository-manager-passphrase');
  const keyData = document.getElementById('repository-manager-key-data');
  if (passphrase) passphrase.value = '';
  if (keyData) keyData.value = '';
  repositoryManagerCloseBrowser();
  document.getElementById('repository-manager-modal')?.classList.add('hidden');
}

function repositoryManagerCloseBrowser() {
  if (repositoryManagerState.browserController) {
    repositoryManagerState.browserController.abort();
    repositoryManagerState.browserController = null;
  }
  repositoryManagerState.browserVisible = false;
  const browser = document.getElementById('repository-manager-browser');
  const input = document.getElementById('repository-manager-relative-path');
  browser?.classList.add('hidden');
  input?.setAttribute('aria-expanded', 'false');
}

function repositoryManagerBrowserStartPath() {
  const value = String(document.getElementById('repository-manager-relative-path')?.value || '').trim().replace(/^\/+|\/+$/g, '');
  if (!value || !value.includes('/')) return '';
  const parts = value.split('/');
  parts.pop();
  return parts.join('/');
}

function repositoryManagerRenderBrowser(data) {
  const browser = document.getElementById('repository-manager-browser');
  const list = document.getElementById('repository-manager-browser-list');
  const path = document.getElementById('repository-manager-browser-path');
  const up = document.getElementById('repository-manager-browser-up-btn');
  const input = document.getElementById('repository-manager-relative-path');
  if (!browser || !list || !path) return;
  const current = String(data?.relative_path || '').trim();
  repositoryManagerState.browserPath = current;
  const storageName = String(data?.storage_name || repositoryManagerSelectedStorageLabel() || '').trim();
  path.textContent = `${storageName}${current ? ` / ${current}` : ' /'}`;
  if (up) up.disabled = !current;
  const rows = Array.isArray(data?.directories) ? data.directories : [];
  list.innerHTML = rows.length ? rows.map((row) => {
    const relative = String(row.relative_path || '').trim();
    const managed = !!row.managed;
    const supported = row.supported !== false;
    const status = managed
      ? storageT('storage.repositoryBrowseManaged', { name: row.display_name || row.name || '' })
      : (!supported ? storageT('storage.repositoryBrowseUnsupported') : storageT('storage.repositoryBrowseAvailable'));
    const selectDisabled = managed || !supported;
    return `<div class="repository-manager-browser-row">
      <button type="button" class="repository-manager-browser-open" data-repository-browser-open="${escHtml(relative)}" ${selectDisabled ? 'disabled' : ''}>
        <span class="repository-manager-browser-folder" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 6.5h6l2 2h10v9H3z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg></span>
        <span class="repository-manager-browser-name"><strong>${escHtml(row.name || relative)}</strong><small>${escHtml(status)}</small></span>
      </button>
      <button type="button" class="btn btn-secondary" data-repository-browser-select="${escHtml(relative)}" ${selectDisabled ? 'disabled' : ''}>${escHtml(storageT('storage.repositoryBrowseSelect'))}</button>
    </div>`;
  }).join('') : `<div class="repository-manager-browser-state">${escHtml(storageT('storage.repositoryBrowseEmpty'))}</div>`;
  browser.classList.remove('hidden');
  input?.setAttribute('aria-expanded', 'true');
  repositoryManagerState.browserVisible = true;
}

async function repositoryManagerLoadBrowser(path = '') {
  if ((document.getElementById('repository-manager-action')?.value || 'create') !== 'import') return;
  const storageKey = repositoryManagerSelectedStorageKey();
  if (!storageKey) return;
  const browser = document.getElementById('repository-manager-browser');
  const list = document.getElementById('repository-manager-browser-list');
  const pathLabel = document.getElementById('repository-manager-browser-path');
  const input = document.getElementById('repository-manager-relative-path');
  if (!browser || !list) return;
  if (repositoryManagerState.browserController) repositoryManagerState.browserController.abort();
  const controller = new AbortController();
  repositoryManagerState.browserController = controller;
  repositoryManagerState.browserVisible = true;
  browser.classList.remove('hidden');
  input?.setAttribute('aria-expanded', 'true');
  if (pathLabel) pathLabel.textContent = repositoryManagerSelectedStorageLabel();
  list.innerHTML = `<div class="repository-manager-browser-state">${escHtml(storageT('storage.repositoryBrowseLoading'))}</div>`;
  try {
    const response = await fetch(`/api/repositories/browse?storage_key=${encodeURIComponent(storageKey)}&path=${encodeURIComponent(path || '')}`, {
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
    if (repositoryManagerState.browserController !== controller) return;
    repositoryManagerRenderBrowser(data);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    const details = String(error?.message || '').trim();
    const message = details
      ? `${storageT('storage.repositoryBrowseFailed')} ${details}`
      : storageT('storage.repositoryBrowseFailed');
    list.innerHTML = `<div class="repository-manager-browser-state error">${escHtml(message)}</div>`;
  } finally {
    if (repositoryManagerState.browserController === controller) repositoryManagerState.browserController = null;
  }
}

function repositoryManagerOpenBrowser() {
  if ((document.getElementById('repository-manager-action')?.value || 'create') !== 'import') return;
  if (repositoryManagerState.browserVisible) return;
  repositoryManagerLoadBrowser(repositoryManagerBrowserStartPath());
}

function repositoryManagerBrowserUp() {
  const current = String(repositoryManagerState.browserPath || '');
  const parts = current.split('/').filter(Boolean);
  parts.pop();
  repositoryManagerLoadBrowser(parts.join('/'));
}

function repositoryManagerBrowserClick(event) {
  const open = event.target.closest('[data-repository-browser-open]');
  if (open) {
    repositoryManagerLoadBrowser(open.dataset.repositoryBrowserOpen || '');
    return;
  }
  const select = event.target.closest('[data-repository-browser-select]');
  if (!select || select.disabled) return;
  const input = document.getElementById('repository-manager-relative-path');
  if (input) input.value = select.dataset.repositoryBrowserSelect || '';
  repositoryManagerPathChanged();
  repositoryManagerCloseBrowser();
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

function repositoryManagerPathInputChanged() {
  const repoName = document.getElementById('repository-manager-repository-name');
  const relative = document.getElementById('repository-manager-relative-path');
  if (!repoName || !relative) return;
  relative.value = String(relative.value || '')
    .replace(/\s+/g, '-')
    .replace(/[^A-Za-z0-9._/-]+/g, '-')
    .replace(/^-+/, '');
  repoName.value = repositoryManagerNameFromRelativePath(relative.value);
  repositoryManagerUpdateSummary();
}

function repositoryManagerPathChanged() {
  const repoName = document.getElementById('repository-manager-repository-name');
  const relative = document.getElementById('repository-manager-relative-path');
  if (!repoName || !relative) return;
  relative.value = repositoryManagerSlug(relative.value);
  repoName.value = repositoryManagerNameFromRelativePath(relative.value);
  repositoryManagerUpdateSummary();
}

async function repositoryManagerPrepareStorage() {
  const storageKey = document.getElementById('repository-manager-storage')?.value || '';
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

function repositoryManagerPayload() {
  const action = document.getElementById('repository-manager-action')?.value || 'create';
  return {
    action,
    storage_key: repositoryManagerSelectedStorageKey(),
    display_name: document.getElementById('repository-manager-display-name')?.value || '',
    repository_name: document.getElementById('repository-manager-repository-name')?.value || '',
    relative_path: document.getElementById('repository-manager-relative-path')?.value || '',
    encryption: action === 'import' ? 'auto' : (document.getElementById('repository-manager-encryption')?.value || 'repokey-blake2'),
    passphrase: document.getElementById('repository-manager-passphrase')?.value || '',
    key_data: action === 'import' ? (document.getElementById('repository-manager-key-data')?.value || '') : '',
    storage_quota: action === 'create' ? (document.getElementById('repository-manager-storage-quota')?.value || '') : '',
    append_only: action === 'create' && !!document.getElementById('repository-manager-append-only')?.checked,
    make_parent_dirs: action === 'create' && !!document.getElementById('repository-manager-make-parent-dirs')?.checked,
  };
}

function repositoryManagerErrorMessage(data, status = 0) {
  const code = String(data?.code || '').trim();
  const keyByCode = {
    repository_already_managed: 'storage.repositoryAlreadyManaged',
    repository_target_borg_exists: 'storage.repositoryTargetBorgExists',
    repository_target_not_empty: 'storage.repositoryTargetNotEmpty',
    repository_target_empty: 'storage.repositoryTargetEmpty',
    repository_target_missing: 'storage.repositoryTargetMissing',
    repository_target_not_directory: 'storage.repositoryTargetNotDirectory',
    repository_target_inaccessible: 'storage.repositoryTargetInaccessible',
    repository_relocated: 'storage.repositoryRelocated',
  };
  if (code === 'repository_target_borg_exists') {
    const action = document.getElementById('repository-manager-action');
    if (action) action.value = 'import';
    repositoryManagerSyncFields();
  }
  return keyByCode[code] ? storageT(keyByCode[code]) : apiErrorMessage(data, status);
}

async function repositoryManagerValidateTarget() {
  const response = await fetch('/api/repositories/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(repositoryManagerPayload()),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(repositoryManagerErrorMessage(data, response.status));
  return data;
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
    await repositoryManagerValidateTarget();
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
  const payload = repositoryManagerPayload();
  const btn = document.getElementById('repository-manager-save-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/repositories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(repositoryManagerErrorMessage(data, res.status));
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

function openStorageMaintenanceConfirm(repositoryKey, action, mode) {
  return new Promise((resolve) => {
    const modal = document.getElementById('storage-maintenance-confirm-modal');
    if (!modal) {
      resolve(false);
      return;
    }
    const repo = storageRepositories(storageState.data || {})
      .find((row) => storageRepositoryKey(row) === String(repositoryKey || ''));
    const job = repo ? storageJobForRepository(repo) : null;
    const resultKey = action === 'check' && mode === 'verify_data' ? 'verify_data' : action;
    const confirmKey = action === 'prune'
      ? 'storage.repositoryPruneConfirm'
      : (action === 'compact' ? 'storage.repositoryCompactConfirm' : 'storage.repositoryVerifyConfirm');
    const title = document.getElementById('storage-maintenance-confirm-title');
    const description = document.getElementById('storage-maintenance-confirm-description');
    const info = document.getElementById('storage-maintenance-confirm-info');
    if (title) title.textContent = storageT('storage.repositoryMaintenanceConfirmTitle');
    if (description) description.textContent = storageT(confirmKey);
    if (info) info.innerHTML = `<div class="modal-info-item warning"><span class="modal-info-text"><strong>${escHtml(storageRepositoryTitle(repo || {}, job))}</strong><br>${escHtml(storageT('storage.repositoryMaintenanceConfirmAction', { action: storageMaintenanceTitle(resultKey) }))}</span></div>`;
    storageState.maintenanceConfirmation = { resolve };
    modal.classList.remove('hidden');
  });
}

function closeStorageMaintenanceConfirm(confirmed = false) {
  const pending = storageState.maintenanceConfirmation;
  storageState.maintenanceConfirmation = null;
  document.getElementById('storage-maintenance-confirm-modal')?.classList.add('hidden');
  if (typeof pending?.resolve === 'function') pending.resolve(!!confirmed);
}

async function openRepositoryLifecycle(repositoryKey, mode = 'remove') {
  const key = String(repositoryKey || '').trim();
  const requestedMode = mode === 'delete' ? 'delete' : 'remove';
  if (!key) return;
  showMsg('storage-message', 'info', storageT('storage.repositoryLifecycleReviewing'));
  try {
    const response = await fetch('/api/repositories/lifecycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository_key: key, mode: requestedMode }),
    });
    const preview = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(preview, response.status));
    storageState.lifecycleCache[key] = { loading: false, ...preview };
    if (!preview.allowed) {
      if (storageState.data) renderStorage(storageState.data);
      showMsg('storage-message', 'warning', storageT('storage.repositoryLifecycleBlocked'));
      return;
    }
    const modal = document.getElementById('repository-lifecycle-modal');
    if (!modal) return;
    storageState.lifecycleConfirmation = { repositoryKey: key, mode: requestedMode, preview };
    const title = document.getElementById('repository-lifecycle-title');
    const description = document.getElementById('repository-lifecycle-description');
    const info = document.getElementById('repository-lifecycle-info');
    const nameLabel = document.getElementById('repository-lifecycle-name-label');
    const phraseGroup = document.getElementById('repository-lifecycle-phrase-group');
    const nameInput = document.getElementById('repository-lifecycle-name-input');
    const phraseInput = document.getElementById('repository-lifecycle-phrase-input');
    const confirm = document.getElementById('repository-lifecycle-confirm-btn');
    if (title) title.textContent = storageT(requestedMode === 'delete' ? 'storage.repositoryDeletePermanent' : 'storage.repositoryRemoveFromUi');
    if (description) description.textContent = storageT(requestedMode === 'delete' ? 'storage.repositoryDeleteConfirmHint' : 'storage.repositoryRemoveConfirmHint');
    if (info) info.innerHTML = `<div class="modal-info-item ${requestedMode === 'delete' ? 'error' : 'warning'}"><span class="modal-info-text"><strong>${escHtml(preview.display_name || '')}</strong><br>${escHtml(preview.repository_path || '')}<br>${escHtml(storageT('storage.repositoryArchiveCount'))}: ${Number(preview.archive_count || 0)} · ${escHtml(storageT('storage.repositoryDeduplicatedSize'))}: ${escHtml(storageFormatBytes(preview.deduplicated_size))}</span></div>`;
    if (nameLabel) nameLabel.textContent = storageT('storage.repositoryConfirmName', { name: preview.display_name || '' });
    phraseGroup?.classList.toggle('hidden', requestedMode !== 'delete');
    if (nameInput) nameInput.value = '';
    if (phraseInput) phraseInput.value = '';
    if (confirm) {
      confirm.textContent = storageT(requestedMode === 'delete' ? 'storage.repositoryDeletePermanent' : 'storage.repositoryRemoveFromUi');
      confirm.className = requestedMode === 'delete' ? 'btn-danger' : 'btn btn-primary';
      confirm.disabled = true;
    }
    hideEl('storage-message');
    modal.classList.remove('hidden');
    nameInput?.focus();
  } catch (error) {
    showMsg('storage-message', 'error', error.message || storageT('storage.error'));
  }
}

function updateRepositoryLifecycleConfirmation() {
  const pending = storageState.lifecycleConfirmation;
  const confirm = document.getElementById('repository-lifecycle-confirm-btn');
  if (!pending || !confirm) return;
  const name = String(document.getElementById('repository-lifecycle-name-input')?.value || '');
  const phrase = String(document.getElementById('repository-lifecycle-phrase-input')?.value || '');
  const nameMatches = name === String(pending.preview?.display_name || '');
  confirm.disabled = !(nameMatches && (pending.mode !== 'delete' || phrase === 'DELETE'));
}

function closeRepositoryLifecycle() {
  storageState.lifecycleConfirmation = null;
  document.getElementById('repository-lifecycle-modal')?.classList.add('hidden');
  const nameInput = document.getElementById('repository-lifecycle-name-input');
  const phraseInput = document.getElementById('repository-lifecycle-phrase-input');
  if (nameInput) nameInput.value = '';
  if (phraseInput) phraseInput.value = '';
}

async function confirmRepositoryLifecycle() {
  const pending = storageState.lifecycleConfirmation;
  const button = document.getElementById('repository-lifecycle-confirm-btn');
  if (!pending || !button || button.disabled) return;
  button.disabled = true;
  try {
    const preview = pending.preview || {};
    const response = await fetch('/api/repositories', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repository_key: pending.repositoryKey,
        mode: pending.mode,
        confirmation_name: String(document.getElementById('repository-lifecycle-name-input')?.value || ''),
        confirmation_phrase: String(document.getElementById('repository-lifecycle-phrase-input')?.value || ''),
        expected_repository_id: preview.repository_id || '',
        expected_repository_path: preview.repository_path || '',
        expected_archive_count: Number(preview.archive_count || 0),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
    const key = pending.repositoryKey;
    const mode = pending.mode;
    closeRepositoryLifecycle();
    delete storageState.lifecycleCache[key];
    delete storageState.archiveCache[key];
    storageState.selectedRepositoryKey = '';
    storageState.selectedTab = 'overview';
    await refreshStorage();
    showMsg('storage-message', 'success', storageT(mode === 'delete' ? 'storage.repositoryDeleted' : 'storage.repositoryRemovedFromUi'));
  } catch (error) {
    showMsg('storage-message', 'error', error.message || storageT('storage.error'));
    button.disabled = false;
  }
}

async function checkRun(repositoryKey, action = 'check', mode = 'quick') {
  if (!repositoryKey) return;
  if (['prune', 'compact', 'verify_data'].includes(action === 'check' ? mode : action)) {
    if (!await openStorageMaintenanceConfirm(repositoryKey, action, mode)) return;
  }
  if (checkState.es) { checkState.es.close(); checkState.es = null; }
  storageState.maintenanceState = {
    running: true,
    target_key: repositoryKey,
    action,
    mode,
    start_time: new Date().toISOString(),
  };
  if (storageState.data) renderStorage(storageState.data);

  try {
    const res = await fetch('/api/storage/check/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository_key: repositoryKey, action, mode }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      storageState.maintenanceState = { running: false };
      if (storageState.data) renderStorage(storageState.data);
      showMsg('storage-message', 'error', err.error || `HTTP ${res.status}`);
      return;
    }
  } catch (err) {
    storageState.maintenanceState = { running: false };
    if (storageState.data) renderStorage(storageState.data);
    showMsg('storage-message', 'error', storageT('storage.errorPrefix', { message: err.message }));
    return;
  }

  const es = new EventSource('/api/storage/check/stream');
  checkState.es = es;

  es.onmessage = () => {};

  es.addEventListener('done', async () => {
    es.close(); checkState.es = null;
    await refreshStorage();
  });

  es.addEventListener('error', async (e) => {
    if (e.data) showMsg('storage-message', 'error', storageT('storage.check.logError', { message: e.data }));
    es.close(); checkState.es = null;
    await refreshStorage();
  });
}

window.addEventListener('bbui:language-changed', () => {
  if (storageState.loaded && storageState.data) renderStorage(storageState.data);
});
