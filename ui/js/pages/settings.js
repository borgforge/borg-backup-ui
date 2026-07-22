// ══════════════════════════════════════════════════════════════════════════════
// SETTINGS PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.settingsState = window.BBUI.settingsState || {
  loaded: false,
  dirty: false,
  activeTab: 'general',
  advancedTab: 'reminders',
  profileSelection: { local: '', usb: '', smb: '', storagebox: '' },
  profileEditing: '',
  storageboxPubVisible: false,
  storageboxConnOk: null,
  storageboxConnMsg: '',
  storageboxLastCheckAt: '',
  storageboxChecks: null,
  restoreSubtab: 'tests',
  transferJobsPreview: null,
  transferJobsBundleText: '',
  transferJobsSecurePayloadB64: '',
  transferJobsSecurePassword: '',
  transferJobsSecureMode: false,
  transferSettingsMode: 'merge',
  transferSecretsPreview: null,
  transferSecretsPayloadB64: '',
  transferSecretsPassword: '',
  transferProfileSecretsPreview: null,
  transferProfileSecretsPayloadB64: '',
  transferProfileSecretsPassword: '',
  storageDeploySessionId: '',
  storageDeployPollTimer: null,
  storageboxProfileKey: '',
  smbCleanupKeys: [],
  smbSecretCleanupKeys: [],
  authStatus: null,
  authUsers: [],
  homepageWidgetToken: '',
  appInfo: null,
  appriseProfiles: [],
  appriseProviders: [],
  appriseProvidersLoaded: false,
  appriseProvidersLoading: false,
  appriseProviderFilter: '',
  appriseSelectedProfileId: '',
  appriseDraftProfile: null,
  appriseLastResult: null,
  data: null,
  systemHealth: null,
};
const settingsState = window.BBUI.settingsState;

const APP_CONTACT_EMAIL = 'thorsten.steinberg@gmx.de';
const APP_REPOSITORY_URL = 'https://github.com/borgforge/borg-backup-ui';
const APP_REPOSITORY_LABEL = 'borgforge/borg-backup-ui';

function escAttr(value) {
  return escHtml(String(value || ''));
}

function settingsT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`settings.${key}`, params) || `settings.${key}`;
}

function settingsLocale() {
  return window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en-US' : 'de-DE';
}

function getSettingsTabs() {
  const tabs = [
  { key: 'general', label: settingsT('tabs.general'), group: 'system', description: settingsT('menu.generalDescription'), icon: settingsMenuIcon('general') },
  { key: 'users', label: settingsT('tabs.users'), group: 'system', description: settingsT('menu.usersDescription'), icon: settingsMenuIcon('users') },
  { key: 'notifications', label: settingsT('tabs.notifications'), group: 'operations', description: settingsT('menu.notificationsDescription'), icon: settingsMenuIcon('notifications') },
  { key: 'backup', label: settingsT('tabs.backup'), group: 'operations', description: settingsT('menu.backupDescription'), icon: settingsMenuIcon('backup') },
  { key: 'restore', label: settingsT('tabs.restore'), group: 'operations', description: settingsT('menu.restoreDescription'), icon: settingsMenuIcon('restore') },
  { key: 'local', label: settingsT('tabs.localProfiles'), group: 'storage', description: settingsT('menu.localDescription'), icon: locationIcon('local') },
  { key: 'usb', label: settingsT('tabs.usbProfiles'), group: 'storage', description: settingsT('menu.usbDescription'), icon: locationIcon('usb') },
  { key: 'smb', label: settingsT('tabs.smbProfiles'), group: 'storage', description: settingsT('menu.smbDescription'), icon: locationIcon('smb') },
  { key: 'storagebox', label: settingsT('tabs.sshProfiles'), group: 'storage', description: settingsT('menu.sshDescription'), icon: locationIcon('storagebox') },
  { key: 'transfer', label: settingsT('tabs.transfer'), group: 'maintenance', description: settingsT('menu.transferDescription'), icon: settingsMenuIcon('transfer') },
  { key: 'advanced', label: settingsT('tabs.advanced'), group: 'maintenance', description: settingsT('menu.advancedDescription'), icon: settingsMenuIcon('advanced') },
  { key: 'factory-reset', label: settingsT('tabs.factoryReset'), group: 'maintenance', description: settingsT('menu.factoryResetDescription'), icon: settingsMenuIcon('factory-reset') },
  ];
  const auth = settingsState.authStatus || {};
  const isAdmin = String(auth.current_role || '').toLowerCase() === 'admin';
  if (!isAdmin || String(auth.auth_mode || '') !== 'users') {
    return tabs.filter((t) => t.key !== 'users');
  }
  return tabs;
}

function settingsMenuIcon(key) {
  const icons = {
    general: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21h-4v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1-2.8-2.8.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3v-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1 2.8-2.8.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3h4v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1 2.8 2.8-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1h.2v4h-.2a1.7 1.7 0 0 0-1.4 1z"/></svg>',
    users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="4"/><path d="M3 21v-2a6 6 0 0 1 12 0v2"/><path d="M16 4.5a4 4 0 0 1 0 7"/><path d="M18 15a5 5 0 0 1 3 4.6V21"/></svg>',
    notifications: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M20 3l-3 3"/><path d="M4 3l3 3"/></svg>',
    backup: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16v13H4z"/><path d="M7 3h10v4H7z"/><path d="M8 12h8M8 16h5"/></svg>',
    restore: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>',
    transfer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 7h13l-3-3M17 17H4l3 3"/><path d="M20 7l-3 3M4 17l3-3"/></svg>',
    advanced: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="13" cy="18" r="2"/></svg>',
    'factory-reset': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>',
  };
  return icons[key] || icons.general;
}

async function refreshSettings() {
  hideEl('settings-message');
  _renderSettingsLoading();
  try {
    const [res, verRes, healthRes, authRes, reminderRes, appriseProfilesRes] = await Promise.all([
      fetch('/api/settings'),
      fetch('/api/version'),
      window.BBUI.core.fetchSystemHealth(true).catch(() => null),
      fetch('/api/auth/status'),
      fetch('/api/notification-reminders/diagnostics').catch(() => null),
      fetch('/api/notification-profiles').catch(() => null),
    ]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    settingsState.authStatus = authRes.ok ? await authRes.json() : null;
    const auth = settingsState.authStatus || {};
    const isAdminUsersMode = String(auth.current_role || '').toLowerCase() === 'admin' && String(auth.auth_mode || '') === 'users';
    const usersRequest = isAdminUsersMode
      ? fetch('/api/auth/users')
          .then((uRes) => uRes.ok ? uRes.json() : { users: [] })
          .catch(() => ({ users: [] }))
      : Promise.resolve({ users: [] });
    if (settingsState.storageboxConnOk === null && data?.storagebox_setup?.auth_checked !== false) {
      settingsState.storageboxConnOk = !!data.storagebox_setup.auth_ok;
      settingsState.storageboxConnMsg = data.storagebox_setup.auth_ok
        ? settingsT('storagebox.sshReachable')
        : settingsT('storagebox.sshFailed');
    }
    const health = healthRes && typeof healthRes === 'object' ? { ...healthRes } : null;
    if (health && reminderRes?.ok) {
      health.notification_reminders = await reminderRes.json();
    }
    settingsState.homepageWidgetToken = '';
    settingsState.data = data;
    settingsState.systemHealth = health;
    if (appriseProfilesRes?.ok) {
      const apprisePayload = await appriseProfilesRes.json();
      settingsState.appriseProfiles = Array.isArray(apprisePayload?.profiles) ? apprisePayload.profiles : [];
      if (!settingsState.appriseProfiles.some((profile) => profile.id === settingsState.appriseSelectedProfileId)) {
        settingsState.appriseSelectedProfileId = settingsState.appriseProfiles[0]?.id || '';
      }
    }
    renderSettings(data, health);
    settingsState.smbCleanupKeys = [];
    settingsState.smbSecretCleanupKeys = [];
    settingsState.loaded = true;
    settingsState.dirty = false;
    _updateUnsavedChangesUi();
    document.getElementById('settings-save-btn')?.removeAttribute('disabled');
    if (verRes.ok) {
      const ver = await verRes.json();
      _applyVersionInfo(ver.version, ver.author, ver.borg_version, ver.contact_email, ver.repository_url);
    }
    usersRequest.then((uData) => {
      settingsState.authUsers = Array.isArray(uData?.users) ? uData.users : [];
      const usersPanel = document.querySelector('#settings-content [data-settings-panel="users"]');
      if (usersPanel) usersPanel.innerHTML = renderSettingsUsers();
    });
  } catch (err) {
    showMsg('settings-message', 'error', settingsT('error', { message: err.message }));
  } finally {
    document.getElementById('settings-content')?.classList.remove('is-refreshing');
  }
}

function _renderSettingsLoading() {
  const el = document.getElementById('settings-content');
  if (!el) return;
  if (settingsState.loaded && settingsState.data) {
    el.classList.add('is-refreshing');
    return;
  }
  el.innerHTML = `
    <div class="settings-section">
      <div class="settings-section-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        ${escHtml(settingsT('updating'))}
      </div>
      <div class="settings-body">
        <div class="status-message empty-state">${escHtml(settingsT('reloading'))}</div>
      </div>
    </div>
  `;
}

window.addEventListener?.('bbui:language-changed', () => {
  if (settingsState.loaded && settingsState.data) {
    renderSettings(settingsState.data, settingsState.systemHealth);
    if (settingsState.activeTab === 'notifications') maybeLoadAppriseProviders();
  }
});

function _normalizeAppInfo(version, author, borgVersion, contactEmail, repositoryUrl) {
  return {
    version: String(version || '').trim(),
    author: String(author || 'Thorsten Steinberg').trim(),
    borgVersion: String(borgVersion || '').trim(),
    contactEmail: String(contactEmail || APP_CONTACT_EMAIL).trim(),
    repositoryUrl: String(repositoryUrl || APP_REPOSITORY_URL).trim(),
  };
}

function _applyVersionInfo(version, author, borgVersion, contactEmail, repositoryUrl) {
  settingsState.appInfo = _normalizeAppInfo(version, author, borgVersion, contactEmail, repositoryUrl);
  const info = settingsState.appInfo;
  const el = document.getElementById('app-version-info');
  if (el) el.innerHTML = `
    <span class="app-version">${info.version ? `v${escHtml(info.version)}` : 'v—'}</span>
    <span class="app-author">${escHtml(info.author)}</span>
    <a class="app-contact" href="mailto:${escAttr(info.contactEmail)}">${escHtml(info.contactEmail)}</a>`;
  const aboutEl = document.getElementById('settings-about-version');
  if (aboutEl) aboutEl.textContent = info.version || '—';
  const borgEl = document.getElementById('settings-about-borg-version');
  if (borgEl) borgEl.textContent = info.borgVersion || '—';
  const contactEl = document.getElementById('settings-about-contact');
  if (contactEl) contactEl.innerHTML = `<a href="mailto:${escAttr(info.contactEmail)}" class="about-link">${escHtml(info.contactEmail)}</a>`;
  const repoEl = document.getElementById('settings-about-repository');
  if (repoEl) repoEl.innerHTML = `<a href="${escAttr(info.repositoryUrl)}" target="_blank" rel="noopener noreferrer" class="about-link">${APP_REPOSITORY_LABEL}</a>`;
}

function renderSettings(data, systemHealth) {
  const el = document.getElementById('settings-content');
  if (!el) return;

  const tabs = getSettingsTabs();
  const active = tabs.find((tab) => tab.key === settingsState.activeTab) || tabs[0];
  if (!tabs.some((tab) => tab.key === settingsState.activeTab)) settingsState.activeTab = active.key;
  const profileTab = ['local', 'usb', 'smb', 'storagebox'].includes(settingsState.activeTab);
  const hideGlobalSave = profileTab || settingsState.activeTab === 'factory-reset';
  const saveBtn = document.getElementById('settings-save-btn');
  if (saveBtn) saveBtn.classList.toggle('hidden', hideGlobalSave);
  el.innerHTML = `
    <div class="settings-redesign-layout">
      <aside class="settings-side-menu">
        <header><small>${settingsT('menu.configuration')}</small><strong>${settingsT('menu.areas')}</strong></header>
        <nav>${renderSettingsMenu(tabs)}</nav>
      </aside>
      <section class="settings-workspace">
        <header class="settings-workspace-header">
          <div><small>${settingsT('title')}</small><h2>${escHtml(active.label)}</h2><span>${escHtml(active.description)}</span></div>
          <span class="badge ${settingsState.dirty ? 'warning' : 'success'}" id="settings-workspace-save-state">${settingsT(settingsState.dirty ? 'menu.unsaved' : 'menu.saved')}</span>
        </header>
    <div class="settings-tab-panel ${settingsState.activeTab === 'general' ? '' : 'hidden'}" data-settings-panel="general">
      ${renderSettingsSystemHealth(systemHealth)}
      ${renderSettingsGeneral(data.general || {})}
      ${renderSettingsHomepageWidget(data.homepage_widget || {})}
      ${renderSettingsAbout()}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'notifications' ? '' : 'hidden'}" data-settings-panel="notifications">
      ${renderSettingsNotifications(data)}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'usb' ? '' : 'hidden'}" data-settings-panel="usb">
      ${renderSettingsUsbProfiles(data.usb_profiles || [])}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'local' ? '' : 'hidden'}" data-settings-panel="local">
      ${renderSettingsLocalProfiles(data.local_profiles || [])}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'smb' ? '' : 'hidden'}" data-settings-panel="smb">
      ${renderSettingsSmbProfiles(data.smb_profiles || [])}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'backup' ? '' : 'hidden'}" data-settings-panel="backup">
      ${renderSettingsDockerVMs(data.docker || {}, data.vms || {})}
      ${renderSettingsWeeklyReport(data.weekly_report || {})}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'restore' ? '' : 'hidden'}" data-settings-panel="restore">
      ${renderSettingsRestore(data.restore_tests || {}, data.restore_browse || {})}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'storagebox' ? '' : 'hidden'}" data-settings-panel="storagebox">
      ${renderSettingsStorageProfiles(data.storage_profiles || [])}
      ${renderSettingsStorageboxSetup(data.storagebox_setup || {}, data.storage_profiles || [])}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'transfer' ? '' : 'hidden'}" data-settings-panel="transfer">
      ${renderSettingsTransferTools()}
      ${renderSettingsConfigBackups()}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'advanced' ? '' : 'hidden'}" data-settings-panel="advanced">
      ${renderSettingsAdvancedTabs(data, systemHealth)}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'factory-reset' ? '' : 'hidden'}" data-settings-panel="factory-reset">
      ${renderSettingsFactoryReset()}
    </div>
    <div class="settings-tab-panel ${settingsState.activeTab === 'users' ? '' : 'hidden'}" data-settings-panel="users">
      ${renderSettingsUsers()}
    </div>
      </section>
    </div>
  `;
  const themeSel = document.getElementById('ui-theme-select');
  const getThemePref = window.BBUI?.components?.theme?.getStoredThemePreference;
  if (themeSel && typeof getThemePref === 'function') {
    themeSel.value = getThemePref();
  }
  if (settingsState.appInfo) {
    _applyVersionInfo(
      settingsState.appInfo.version,
      settingsState.appInfo.author,
      settingsState.appInfo.borgVersion,
      settingsState.appInfo.contactEmail,
      settingsState.appInfo.repositoryUrl,
    );
  }
  refreshSettingsConfigBackups();
  initializeSettingsProfileManagers();
  if (settingsState.activeTab === 'notifications') maybeLoadAppriseProviders();
  _updateUnsavedChangesUi();
}

function renderSettingsMenu(tabs) {
  const groupLabels = {
    system: settingsT('menu.system'),
    operations: settingsT('menu.operations'),
    storage: settingsT('menu.storageTargets'),
    maintenance: settingsT('menu.maintenance'),
  };
  let previous = '';
  return tabs.map((tab) => {
    const heading = tab.group !== previous
      ? `<div class="settings-menu-group">${escHtml(groupLabels[tab.group] || '')}</div>`
      : '';
    previous = tab.group;
    return `${heading}<button class="settings-menu-item ${settingsState.activeTab === tab.key ? 'active' : ''}" data-settings-tab="${tab.key}" type="button">
      <span class="settings-menu-icon">${tab.icon}</span>
      <span><strong>${escHtml(tab.label)}</strong><small>${escHtml(tab.description)}</small></span>
      <b>›</b>
    </button>`;
  }).join('');
}

function activateSettingsTab(tabKey) {
  const tabs = getSettingsTabs();
  const active = tabs.find((tab) => tab.key === tabKey) || tabs[0];
  if (!active) return;
  const previousTab = settingsState.activeTab;
  settingsState.activeTab = active.key;
  settingsState.profileEditing = '';

  document.querySelectorAll('#settings-content [data-settings-tab]').forEach((button) => {
    button.classList.toggle('active', button.dataset.settingsTab === active.key);
  });
  document.querySelectorAll('#settings-content [data-settings-panel]').forEach((panel) => {
    panel.classList.toggle('hidden', panel.dataset.settingsPanel !== active.key);
  });

  const workspaceHeader = document.querySelector('#settings-content .settings-workspace-header');
  const title = workspaceHeader?.querySelector('h2');
  const description = workspaceHeader?.querySelector('div > span');
  if (title) title.textContent = active.label;
  if (description) description.textContent = active.description;

  const profileTab = ['local', 'usb', 'smb', 'storagebox'].includes(active.key);
  document.getElementById('settings-save-btn')?.classList.toggle('hidden', profileTab || active.key === 'factory-reset');
  if (SETTINGS_PROFILE_CONFIG[previousTab]) syncSettingsProfileManager(previousTab);
  if (SETTINGS_PROFILE_CONFIG[active.key]) syncSettingsProfileManager(active.key);
  if (active.key === 'notifications') maybeLoadAppriseProviders();
  _updateUnsavedChangesUi();
}

const SETTINGS_PROFILE_CONFIG = {
  local: {
    rowsId: 'local-profiles-rows',
    rowSelector: '.local-profile-row',
    nameSelector: '[data-local-profile-name]',
    endpointSelector: '[data-local-profile-path]',
    icon: locationIcon('local'),
    fields: [
      ['[data-local-profile-name]', 'profiles.name'],
      ['[data-local-profile-path]', 'profiles.basePath'],
    ],
  },
  usb: {
    rowsId: 'usb-profiles-rows',
    rowSelector: '.usb-profile-row',
    nameSelector: '[data-usb-profile-name]',
    endpointSelector: '[data-usb-profile-path]',
    icon: locationIcon('usb'),
    fields: [
      ['[data-usb-profile-name]', 'profiles.name'],
      ['[data-usb-profile-path]', 'profiles.mountPath'],
    ],
  },
  smb: {
    rowsId: 'smb-profiles-rows',
    rowSelector: '.smb-profile-row',
    nameSelector: '[data-smb-profile-name]',
    endpointSelector: '[data-smb-profile-server]',
    icon: locationIcon('smb'),
    fields: [
      ['[data-smb-profile-name]', 'profiles.name'],
      ['[data-smb-profile-server]', 'profiles.host'],
      ['[data-smb-profile-share]', 'profiles.share'],
      ['[data-smb-profile-path]', 'profiles.mountPath'],
      ['[data-smb-profile-username]', 'profiles.username'],
      ['[data-smb-profile-password]', 'profiles.password'],
      ['[data-smb-profile-vers]', 'profiles.smbVersion'],
      ['[data-smb-profile-sec]', 'profiles.security'],
    ],
  },
  storagebox: {
    rowsId: 'storage-profiles-rows',
    rowSelector: '.storage-profile-row',
    nameSelector: '[data-storage-profile-name]',
    endpointSelector: '[data-storage-profile-host]',
    icon: locationIcon('storagebox'),
    fields: [
      ['[data-storage-profile-name]', 'profiles.name'],
      ['[data-storage-profile-host]', 'profiles.host'],
      ['[data-storage-profile-port]', 'profiles.port'],
      ['[data-storage-profile-user]', 'profiles.username'],
      ['[data-storage-profile-base-path]', 'profiles.basePath'],
      ['[data-storage-profile-ssh-key]', 'profiles.sshKey'],
      ['[data-storage-profile-target-type]', 'profiles.targetType'],
    ],
  },
};

function initializeSettingsProfileManagers() {
  Object.keys(SETTINGS_PROFILE_CONFIG).forEach((type) => syncSettingsProfileManager(type));
}

function syncSettingsProfileManager(type, selectLast = false) {
  const config = SETTINGS_PROFILE_CONFIG[type];
  const rowsBox = document.getElementById(config?.rowsId || '');
  if (!config || !rowsBox) return;
  const body = rowsBox.closest('.settings-body');
  if (!body) return;
  let manager = body.querySelector(`[data-profile-manager="${type}"]`);
  if (!manager) {
    manager = document.createElement('div');
    manager.className = 'settings-profile-manager';
    manager.dataset.profileManager = type;
    const list = document.createElement('aside');
    list.className = 'settings-profile-list';
    list.innerHTML = `<header><strong>${settingsT('menu.savedProfiles')}</strong><small data-profile-count></small></header><nav data-profile-list></nav></aside>`;
    const editor = document.createElement('section');
    editor.className = 'settings-profile-editor readonly';
    editor.innerHTML = `
      <header data-profile-editor-header></header>
      <div class="settings-profile-editor-body"></div>
      <footer>
        <button type="button" class="btn btn-secondary btn-sm" data-profile-cancel>${settingsT('dialog.cancel')}</button>
        <button type="button" class="btn btn-primary btn-sm" data-profile-save>${settingsT('menu.saveProfile')}</button>
      </footer>`;
    rowsBox.parentNode.insertBefore(manager, rowsBox);
    manager.append(list, editor);
    editor.querySelector('.settings-profile-editor-body').appendChild(rowsBox);
    list.querySelector('[data-profile-list]').addEventListener('click', (event) => {
      const button = event.target.closest('[data-profile-ui-key]');
      if (!button || settingsState.profileEditing === type) return;
      settingsState.profileSelection[type] = button.dataset.profileUiKey || '';
      if (type === 'storagebox') {
        settingsState.storageboxProfileKey = settingsState.profileSelection[type];
        const select = document.getElementById('storagebox-profile-select');
        if (select) select.value = settingsState.storageboxProfileKey;
      }
      syncSettingsProfileManager(type);
    });
    editor.querySelector('[data-profile-cancel]').addEventListener('click', () => {
      settingsState.profileEditing = '';
      settingsState.dirty = false;
      renderSettings(settingsState.data, settingsState.systemHealth);
    });
    editor.querySelector('[data-profile-save]').addEventListener('click', async () => {
      const saved = await saveSettings();
      if (!saved) return;
      settingsState.profileEditing = '';
      await reloadSettingsDataAfterSave(type);
    });
  }

  const rows = [...rowsBox.querySelectorAll(config.rowSelector)];
  rows.forEach((row, index) => {
    if (!row.dataset.profileUiKey) row.dataset.profileUiKey = row.dataset.profileKey || `new-${type}-${index + 1}`;
  });
  if (selectLast && rows.length) settingsState.profileSelection[type] = rows.at(-1).dataset.profileUiKey;
  const selectedKey = settingsState.profileSelection[type] || rows[0]?.dataset.profileUiKey || '';
  settingsState.profileSelection[type] = selectedKey;
  const selectedRow = rows.find((row) => row.dataset.profileUiKey === selectedKey) || rows[0] || null;
  if (type === 'storagebox' && selectedKey) {
    settingsState.storageboxProfileKey = selectedKey;
    const select = document.getElementById('storagebox-profile-select');
    if (select) select.value = selectedKey;
  }
  const editing = settingsState.profileEditing === type;

  rows.forEach((row) => decorateSettingsProfileFields(row, config.fields || []));

  const list = manager.querySelector('[data-profile-list]');
  const count = manager.querySelector('[data-profile-count]');
  if (count) count.textContent = settingsT('menu.profileCount', { count: rows.length });
  if (list) list.innerHTML = rows.map((row) => {
    const key = row.dataset.profileUiKey || '';
    const name = row.querySelector(config.nameSelector)?.value || key || settingsT('menu.newProfile');
    const endpoint = row.querySelector(config.endpointSelector)?.value || settingsT('common.notChecked');
    const jobsCount = Number(row.dataset.localJobsCount || row.dataset.usbJobsCount || row.dataset.smbJobsCount || row.dataset.storageJobsCount || 0);
    const inUse = jobsCount > 0 ? `<em class="settings-profile-usage">${settingsT('profiles.inUseShort', { count: jobsCount })}</em>` : '';
    return `<button type="button" class="settings-profile-list-item ${key === selectedKey ? 'active' : ''}" data-profile-ui-key="${escHtml(key)}">
      <span class="settings-profile-symbol ${type}">${config.icon}</span>
      <span><strong>${escHtml(name)}</strong><small>${escHtml(endpoint)}</small><em>${settingsT('common.jobsCount', { count: jobsCount })}</em>${inUse}</span>
      <b>›</b>
    </button>`;
  }).join('');

  rows.forEach((row) => {
    const selected = row === selectedRow;
    row.classList.toggle('hidden', !selected);
    row.querySelectorAll('input:not([type="hidden"]), select').forEach((control) => {
      control.disabled = !editing || !selected;
    });
    row.querySelectorAll('[data-settings-action$="-remove"], [data-settings-action="smb-profile-toggle-options"]').forEach((button) => {
      button.classList.toggle('hidden', !editing || !selected);
    });
  });

  const editor = manager.querySelector('.settings-profile-editor');
  editor?.classList.toggle('readonly', !editing);
  const name = selectedRow?.querySelector(config.nameSelector)?.value || settingsT('menu.noProfileSelected');
  const endpoint = selectedRow?.querySelector(config.endpointSelector)?.value || '';
  const header = manager.querySelector('[data-profile-editor-header]');
  if (header) header.innerHTML = `
    <div><small>${settingsT('menu.selectedProfile')}</small><h3>${escHtml(name)}</h3><span>${escHtml(endpoint)}</span></div>
    ${selectedRow ? `<button type="button" class="btn btn-secondary btn-sm" data-profile-edit ${editing ? 'hidden' : ''}>${settingsT('menu.edit')}</button>` : ''}`;
  header?.querySelector('[data-profile-edit]')?.addEventListener('click', () => {
    settingsState.profileEditing = type;
    syncSettingsProfileManager(type);
  });
  const footer = manager.querySelector('.settings-profile-editor > footer');
  if (footer) footer.classList.toggle('hidden', !editing);
  if (type === 'smb' && selectedRow && !editing && settingsState.activeTab === 'smb') {
    refreshSelectedSmbProfileMountStatus(selectedRow);
  }
}

async function blockProfileRemovalIfInUse(row, type) {
  const jobsCount = Number(row?.dataset?.[`${type}JobsCount`] || 0);
  const repositoriesCount = Number(row?.dataset?.[`${type}RepositoriesCount`] || 0);
  if (jobsCount <= 0 && repositoriesCount <= 0) return false;
  const refs = String(row?.dataset?.[`${type}JobRefs`] || '').trim();
  const repositoryRefs = String(row?.dataset?.[`${type}RepositoryRefs`] || '').trim();
  const titleKey = type === 'local'
    ? 'profiles.cannotRemoveLocal'
    : (type === 'usb' ? 'profiles.cannotRemoveUsb' : (type === 'smb' ? 'profiles.cannotRemoveSmb' : 'profiles.cannotRemoveStorage'));
  const msgId = type === 'local'
    ? 'local-profiles-msg'
    : (type === 'usb' ? 'usb-profiles-msg' : (type === 'smb' ? 'smb-profiles-msg' : 'storage-profiles-msg'));
  const details = [
    refs ? `\n\nJobs:\n${refs}` : '',
    repositoryRefs ? `\n\nRepositorys:\n${repositoryRefs}` : '',
  ].join('');
  await _openSettingsDialog({
    title: settingsT(titleKey),
    message: settingsT('profiles.profileInUseResourcesDialog', { jobs: jobsCount, repositories: repositoriesCount, refs: details }),
    confirmText: 'OK',
  });
  showMsg(msgId, 'warning', settingsT('profiles.profileInUseResources', { jobs: jobsCount, repositories: repositoriesCount, refs: '' }));
  return true;
}

function decorateSettingsProfileFields(row, fields) {
  fields.forEach(([selector, labelKey]) => {
    const control = row.querySelector(selector);
    if (!control || control.closest('.settings-profile-field')) return;
    const wrapper = document.createElement('label');
    wrapper.className = 'settings-profile-field';
    wrapper.innerHTML = `<span>${escHtml(settingsT(labelKey))}</span>`;
    control.parentNode.insertBefore(wrapper, control);
    wrapper.appendChild(control);
  });
}

function normalizeLocalProfileRows(rows) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((row) => {
    const name = String(row?.name || '').trim();
    const base_path = String(row?.base_path || '').trim().replace(/\/+$/, '');
    const storage_key = String(row?.storage_key || row?.key || '').trim();
    if (!name || !base_path || seen.has(base_path)) return;
    seen.add(base_path);
    out.push({
      key: storage_key,
      storage_key,
      name,
      base_path,
      jobs_count: Number(row?.jobs_count || 0),
      job_refs: Array.isArray(row?.job_refs) ? row.job_refs.map(String).filter(Boolean) : [],
    });
  });
  return out;
}

function normalizeCanonicalStoragePath(value) {
  const submitted = String(value || '').trim();
  if (!submitted || submitted.includes('//')) return '';
  const normalized = submitted.replace(/\/$/, '');
  const blocked = new Set(['/', '/mnt', '/mnt/disks', '/mnt/remotes', '/boot', '/etc', '/usr', '/var']);
  if (!normalized.startsWith('/mnt/') || blocked.has(normalized)) return '';
  const segments = normalized.slice(1).split('/');
  if (segments.some((segment) => !segment || segment === '.' || segment === '..')) return '';
  return normalized;
}

function validateLocalProfilesForSave() {
  const rows = [...document.querySelectorAll('#local-profiles-rows .local-profile-row')];
  for (const row of rows) {
    const input = row.querySelector('[data-local-profile-path]');
    const submitted = String(input?.value || '').trim();
    const normalized = normalizeCanonicalStoragePath(submitted);
    input?.classList.toggle('input-error', !normalized);
    if (!normalized) {
      showMsg('local-profiles-msg', 'error', settingsT('profiles.invalidLocalPath', {
        path: submitted || settingsT('common.none'),
      }));
      input?.focus();
      return false;
    }
    if (input) input.value = normalized;
  }
  hideEl('local-profiles-msg');
  return true;
}

function getLocalProfilesFromDom() {
  return normalizeLocalProfileRows([...document.querySelectorAll('#local-profiles-rows .local-profile-row')].map((row) => ({
    storage_key: row.dataset.storageKey || '',
    name: row.querySelector('[data-local-profile-name]')?.value || '',
    base_path: row.querySelector('[data-local-profile-path]')?.value || '',
  })));
}

function syncLocalProfilesHiddenInput() {
  const hidden = document.getElementById('local-profiles-json');
  if (hidden) hidden.value = JSON.stringify(getLocalProfilesFromDom());
}

function onLocalProfileInputChanged() {
  syncLocalProfilesHiddenInput();
  markSettingsDirty();
}

function addLocalProfileRow(row = {}) {
  const box = document.getElementById('local-profiles-rows');
  if (!box) return;
  const wrap = document.createElement('div');
  wrap.className = 'local-profile-row';
  wrap.dataset.storageKey = String(row.storage_key || '');
  wrap.innerHTML = `
    <input class="form-input" type="text" data-local-profile-name placeholder="Backup Pool" value="${escHtml(row.name || '')}" oninput="onLocalProfileInputChanged()">
    <input class="form-input mono" type="text" data-local-profile-path placeholder="/mnt/backup" value="${escHtml(row.base_path || '')}" oninput="onLocalProfileInputChanged()">
    <button type="button" class="btn btn-danger btn-sm" data-settings-action="local-profile-remove">${settingsT('common.remove')}</button>`;
  box.appendChild(wrap);
}

function renderSettingsLocalProfiles(rows) {
  const normalized = normalizeLocalProfileRows(rows);
  const content = normalized.map((row) => `
    <div class="local-profile-row" data-profile-key="${escHtml(row.storage_key)}" data-storage-key="${escHtml(row.storage_key)}" data-local-jobs-count="${row.jobs_count}" data-local-job-refs="${escHtml(row.job_refs.join(', '))}">
      <input class="form-input" type="text" data-local-profile-name value="${escHtml(row.name)}" oninput="onLocalProfileInputChanged()">
      <input class="form-input mono" type="text" data-local-profile-path value="${escHtml(row.base_path)}" oninput="onLocalProfileInputChanged()">
      <button type="button" class="btn btn-danger btn-sm" data-settings-action="local-profile-remove">${settingsT('common.remove')}</button>
    </div>`).join('');
  return settingsCard(settingsT('profiles.localTitle'), locationIcon('local'), `
    <div class="settings-body">
      <div class="text-muted" style="font-size:12px;margin-bottom:10px">${settingsT('profiles.localDescription')}</div>
      <div id="local-profiles-rows" style="display:grid;gap:8px">${content}</div>
      <input type="hidden" id="local-profiles-json" value='${escHtml(JSON.stringify(normalized))}'>
      <div style="display:flex;justify-content:flex-end;margin-top:10px">
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="local-profile-add">${settingsT('profiles.addLocal')}</button>
      </div>
      <div id="local-profiles-msg" class="status-message hidden" style="margin-top:10px"></div>
    </div>`);
}

function normalizeUsbProfileRows(rows) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((r, idx) => {
    const name = String(r?.name || '').trim();
    const mount_path = String(r?.mount_path || '').trim();
    if (!name || !mount_path) return;
    let key = String(r?.key || '').trim().toLowerCase();
    if (!key) key = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || `usb-${idx + 1}`;
    while (seen.has(key)) key = `${key}-${idx + 1}`;
    seen.add(key);
    const jobs_count = Number(r?.jobs_count || 0);
    const job_refs = Array.isArray(r?.job_refs) ? r.job_refs.map((v) => String(v || '')).filter(Boolean) : [];
    out.push({ key, name, mount_path, jobs_count, job_refs });
  });
  return out;
}

function getUsbProfilesFromDom() {
  const rows = [];
  document.querySelectorAll('#usb-profiles-rows .usb-profile-row').forEach((row, idx) => {
    rows.push({
      key: row.dataset.profileKey || `usb-${idx + 1}`,
      name: row.querySelector('[data-usb-profile-name]')?.value || '',
      mount_path: row.querySelector('[data-usb-profile-path]')?.value || '',
    });
  });
  return normalizeUsbProfileRows(rows);
}

function syncUsbProfilesHiddenInput() {
  const hidden = document.getElementById('usb-profiles-json');
  if (!hidden) return;
  hidden.value = JSON.stringify(getUsbProfilesFromDom());
  updateUsbProfilesEmptyState();
}

function updateUsbProfilesEmptyState() {
  const empty = document.getElementById('usb-profiles-empty-state');
  if (!empty) return;
  empty.classList.toggle('hidden', getUsbProfilesFromDom().length > 0);
}

function onUsbProfileInputChanged() {
  syncUsbProfilesHiddenInput();
  markSettingsDirty();
}

function addUsbProfileRow(row = {}) {
  const box = document.getElementById('usb-profiles-rows');
  if (!box) return;
  const key = String(row.key || '').trim();
  const name = String(row.name || '').trim();
  const path = String(row.mount_path || '').trim();
  const wrap = document.createElement('div');
  wrap.className = 'usb-profile-row';
  if (key) wrap.dataset.profileKey = key;
  wrap.innerHTML = `
    <input class="form-input" type="text" data-usb-profile-name placeholder="USB-Drive-A" value="${escHtml(name)}" onchange="onUsbProfileInputChanged()" oninput="onUsbProfileInputChanged()">
    <input class="form-input mono" type="text" data-usb-profile-path placeholder="/mnt/disks/DEIN_DRIVE" value="${escHtml(path)}" onchange="onUsbProfileInputChanged()" oninput="onUsbProfileInputChanged()">
    <span class="usb-profile-state text-muted" data-usb-profile-state>${settingsT('profiles.unchecked')}</span>
    <button type="button" class="btn btn-danger btn-sm" data-settings-action="usb-profile-remove">${settingsT('common.remove')}</button>
  `;
  box.appendChild(wrap);
}

function renderSettingsUsbProfiles(rows) {
  const normalized = normalizeUsbProfileRows(rows);
  const content = normalized.map((r) => `
    <div class="usb-profile-row" data-profile-key="${escHtml(r.key || '')}" data-usb-jobs-count="${Number(r.jobs_count || 0)}" data-usb-job-refs="${escHtml((r.job_refs || []).join(', '))}">
      <input class="form-input" type="text" data-usb-profile-name placeholder="USB-Drive-A" value="${escHtml(r.name || '')}" onchange="onUsbProfileInputChanged()" oninput="onUsbProfileInputChanged()">
      <input class="form-input mono" type="text" data-usb-profile-path placeholder="/mnt/disks/DEIN_DRIVE" value="${escHtml(r.mount_path || '')}" onchange="onUsbProfileInputChanged()" oninput="onUsbProfileInputChanged()">
      <span class="usb-profile-state text-muted" data-usb-profile-state>${settingsT('profiles.unchecked')}</span>
      <button type="button" class="btn btn-danger btn-sm" data-settings-action="usb-profile-remove">${settingsT('common.remove')}</button>
    </div>
  `).join('');
  return settingsCard(settingsT('profiles.usbTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 7h12a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/><path d="M12 3v4"/><path d="M10 3h4"/><circle cx="8" cy="12" r="1"/><circle cx="16" cy="12" r="1"/></svg>`,
    `<div class="settings-body">
      <div class="text-muted" style="font-size:12px;margin-bottom:10px">
        ${settingsT('profiles.usbDescription')}
      </div>
      <div id="usb-profiles-rows" style="display:grid;gap:8px">
        ${content}
      </div>
      <input type="hidden" id="usb-profiles-json" value='${escHtml(JSON.stringify(normalized))}'>
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:10px">
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="usb-profile-check">${settingsT('common.checkStatus')}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="usb-profile-add">${settingsT('profiles.addUsb')}</button>
      </div>
      <div id="usb-profiles-msg" class="status-message hidden" style="margin-top:10px"></div>
      <div id="usb-profiles-empty-state" class="status-message warning ${normalized.length === 0 ? '' : 'hidden'}" style="margin-top:10px">${settingsT('profiles.noUsb')}</div>
    </div>`);
}

function normalizeStorageProfileRows(rows) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((r, idx) => {
    const name = String(r?.name || '').trim();
    const host = String(r?.host || '').trim();
    const user = String(r?.user || '').trim();
    const port = String(r?.port || '23').trim() || '23';
    const base_path = String(r?.base_path || '/./backup').trim() || '/./backup';
    const target_type = String(r?.target_type || 'storagebox').trim().toLowerCase() || 'storagebox';
    const ssh_key_path = String(r?.ssh_key_path || '').trim();
    const jobs_count = Number(r?.jobs_count || 0);
    const job_refs = Array.isArray(r?.job_refs) ? r.job_refs.map((v) => String(v || '')).filter(Boolean) : [];
    if (!name || !host || !user || !base_path) return;
    let key = String(r?.key || '').trim().toLowerCase();
    if (!key) key = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || `storage-${idx + 1}`;
    while (seen.has(key)) key = `${key}-${idx + 1}`;
    seen.add(key);
    out.push({ key, name, host, port, user, base_path, target_type, ssh_key_path, jobs_count, job_refs });
  });
  return out;
}

function getStorageProfilesFromDom() {
  const rows = [];
  document.querySelectorAll('#storage-profiles-rows .storage-profile-row').forEach((row, idx) => {
    const item = {
      key: row.dataset.profileKey || `storage-${idx + 1}`,
      name: row.querySelector('[data-storage-profile-name]')?.value || '',
      host: row.querySelector('[data-storage-profile-host]')?.value || '',
      port: row.querySelector('[data-storage-profile-port]')?.value || '23',
      user: row.querySelector('[data-storage-profile-user]')?.value || '',
      base_path: row.querySelector('[data-storage-profile-base-path]')?.value || '/./backup',
      target_type: row.querySelector('[data-storage-profile-target-type]')?.value || 'storagebox',
      ssh_key_path: row.querySelector('[data-storage-profile-ssh-key]')?.value || '',
    };
    const hasMeaningfulInput = ['key', 'name', 'host', 'user', 'base_path', 'ssh_key_path'].some((k) => String(item[k] || '').trim());
    if (hasMeaningfulInput) rows.push(item);
  });
  return rows;
}

function syncStorageProfilesHiddenInput() {
  const hidden = document.getElementById('storage-profiles-json');
  if (!hidden) return;
  hidden.value = JSON.stringify(getStorageProfilesFromDom());
}

function onStorageProfileInputChanged() {
  syncStorageProfilesHiddenInput();
  markSettingsDirty();
}

function addStorageProfileRow(row = {}) {
  const box = document.getElementById('storage-profiles-rows');
  if (!box) return;
  const wrap = document.createElement('div');
  wrap.className = 'storage-profile-row';
  const key = String(row.key || '').trim().toLowerCase();
  const name = String(row.name || '').trim();
  const host = String(row.host || '').trim();
  const port = String(row.port || '23').trim() || '23';
  const user = String(row.user || '').trim();
  const basePath = String(row.base_path || '/./backup').trim() || '/./backup';
  const targetType = String(row.target_type || 'storagebox').trim().toLowerCase() || 'storagebox';
  const sshKeyPath = String(row.ssh_key_path || '').trim();
  if (key) wrap.dataset.profileKey = key;
  wrap.dataset.storageJobsCount = String(Number(row.jobs_count || 0));
  wrap.dataset.storageJobRefs = Array.isArray(row.job_refs) ? row.job_refs.join(', ') : '';
  wrap.innerHTML = `
    <input class="form-input" type="text" data-storage-profile-name placeholder="Storagebox-1" value="${escHtml(name)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <input class="form-input mono" type="text" data-storage-profile-host placeholder="u12345.your-storagebox.de" value="${escHtml(host)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <input class="form-input mono" type="number" data-storage-profile-port placeholder="23" value="${escHtml(port)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <input class="form-input mono" type="text" data-storage-profile-user placeholder="u12345" value="${escHtml(user)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <input class="form-input mono" type="text" data-storage-profile-base-path placeholder="./backup" value="${escHtml(basePath)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <input class="form-input mono" type="text" data-storage-profile-ssh-key placeholder="/root/.ssh/id_ed25519_storagebox" value="${escHtml(sshKeyPath)}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
    <select class="form-select" data-storage-profile-target-type onchange="onStorageProfileInputChanged()">
      <option value="storagebox" ${targetType === 'storagebox' ? 'selected' : ''}>Storagebox</option>
      <option value="synology" ${targetType === 'synology' ? 'selected' : ''}>Synology</option>
      <option value="generic" ${targetType === 'generic' ? 'selected' : ''}>Generic SSH</option>
    </select>
    <span class="text-muted" style="font-size:12px">${settingsT('common.jobsCount', { count: Number(row.jobs_count || 0) })}</span>
    <button type="button" class="btn btn-danger btn-sm" data-settings-action="storage-profile-remove">${settingsT('common.remove')}</button>
  `;
  box.appendChild(wrap);
}

function renderSettingsStorageProfiles(rows) {
  const normalized = normalizeStorageProfileRows(rows);
  const content = normalized.map((r) => `
    <div class="storage-profile-row" data-profile-key="${escHtml(r.key || '')}" data-storage-jobs-count="${Number(r.jobs_count || 0)}" data-storage-job-refs="${escHtml((r.job_refs || []).join(', '))}">
      <input class="form-input" type="text" data-storage-profile-name placeholder="Storagebox-1" value="${escHtml(r.name || '')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <input class="form-input mono" type="text" data-storage-profile-host placeholder="u12345.your-storagebox.de" value="${escHtml(r.host || '')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <input class="form-input mono" type="number" data-storage-profile-port placeholder="23" value="${escHtml(r.port || '23')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <input class="form-input mono" type="text" data-storage-profile-user placeholder="u12345" value="${escHtml(r.user || '')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <input class="form-input mono" type="text" data-storage-profile-base-path placeholder="./backup" value="${escHtml(r.base_path || '/./backup')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <input class="form-input mono" type="text" data-storage-profile-ssh-key placeholder="/root/.ssh/id_ed25519_storagebox" value="${escHtml(r.ssh_key_path || '')}" onchange="onStorageProfileInputChanged()" oninput="onStorageProfileInputChanged()">
      <select class="form-select" data-storage-profile-target-type onchange="onStorageProfileInputChanged()">
        <option value="storagebox" ${String(r.target_type || 'storagebox') === 'storagebox' ? 'selected' : ''}>Storagebox</option>
        <option value="synology" ${String(r.target_type || '') === 'synology' ? 'selected' : ''}>Synology</option>
        <option value="generic" ${String(r.target_type || '') === 'generic' ? 'selected' : ''}>Generic SSH</option>
      </select>
      <span class="text-muted" style="font-size:12px">${settingsT('common.jobsCount', { count: Number(r.jobs_count || 0) })}</span>
      <button type="button" class="btn btn-danger btn-sm" data-settings-action="storage-profile-remove">${settingsT('common.remove')}</button>
    </div>
  `).join('');
  return settingsCard(settingsT('profiles.storageTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 5h18M3 12h18M3 19h18"/></svg>`,
    `<div class="settings-body">
      <div class="text-muted" style="font-size:12px;margin-bottom:10px">
        ${settingsT('profiles.storageDescription')}
      </div>
      <div id="storage-profiles-rows" style="display:grid;gap:8px">
        ${content}
      </div>
      <input type="hidden" id="storage-profiles-json" value='${escHtml(JSON.stringify(normalized))}'>
      <div style="display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:10px">
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="storage-profile-add">${settingsT('profiles.addStorage')}</button>
      </div>
      <div id="storage-profiles-msg" class="status-message hidden" style="margin-top:10px"></div>
    </div>`);
}

function normalizeSmbProfileRows(rows) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((r, idx) => {
    const name = String(r?.name || '').trim();
    const server = String(r?.server || '').trim();
    const share = String(r?.share || '').trim();
    let mount_path = String(r?.mount_path || '').trim();
    const username = String(r?.username || '').trim();
    const vers = String(r?.vers || '').trim() || 'auto';
    const sec = String(r?.sec || '').trim();
    const smb_password = String(r?.smb_password || '').trim();
    const password_set = !!r?.password_set;
    const mount_at_start = !!r?.mount_at_start;
    const keep_mounted = !!r?.keep_mounted;
    const is_mounted = !!r?.is_mounted;
    const jobs_count = Number(r?.jobs_count || 0);
    const job_refs = Array.isArray(r?.job_refs) ? r.job_refs.map((v) => String(v || '')).filter(Boolean) : [];
    if (!name || !server || !share || !username) return;
    if (!mount_path) mount_path = generateSmbManagedMountPath(name);
    let key = String(r?.key || '').trim().toLowerCase();
    if (!key) key = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || `smb-${idx + 1}`;
    while (seen.has(key)) key = `${key}-${idx + 1}`;
    seen.add(key);
    out.push({
      key,
      name,
      server,
      share,
      mount_path,
      username,
      vers,
      sec,
      smb_password,
      password_set,
      mount_at_start,
      keep_mounted,
      is_mounted,
      jobs_count,
      job_refs,
      repositories_count: Number(r?.repositories_count || 0),
      repository_refs: Array.isArray(r?.repository_refs) ? r.repository_refs.map((v) => String(v || '')).filter(Boolean) : [],
    });
  });
  return out;
}

function generateSmbManagedMountPath(name = '') {
  return generateSmbManagedMountPathWithSuffix(name).path;
}

function generateSmbManagedMountPathWithSuffix(name = '', suffix = '') {
  const slug = String(name || '')
    .trim()
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  let cleanSuffix = String(suffix || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 8);
  try {
    if (!cleanSuffix) {
      const values = new Uint8Array(3);
      window.crypto.getRandomValues(values);
      cleanSuffix = Array.from(values).map((v) => v.toString(16).padStart(2, '0')).join('');
    }
  } catch (_) {
    if (!cleanSuffix) cleanSuffix = Math.random().toString(16).slice(2, 8).padEnd(6, '0');
  }
  const leaf = slug ? `${slug}-smb-${cleanSuffix}` : `smb-${cleanSuffix}`;
  return { path: `/mnt/borg-backup-ui/smb/${leaf}`, suffix: cleanSuffix };
}

function extractSmbManagedPathSuffix(path = '') {
  const match = String(path || '').trim().match(/(?:^|-)smb-([a-z0-9]{6,8})$/i)
    || String(path || '').trim().match(/-([a-z0-9]{6,8})$/i);
  return match ? match[1].toLowerCase() : '';
}

function getSmbProfilesFromDom() {
  const rows = [];
  document.querySelectorAll('#smb-profiles-rows .smb-profile-row').forEach((row, idx) => {
    rows.push({
      key: row.dataset.profileKey || `smb-${idx + 1}`,
      name: row.querySelector('[data-smb-profile-name]')?.value || '',
      server: row.querySelector('[data-smb-profile-server]')?.value || '',
      share: row.querySelector('[data-smb-profile-share]')?.value || '',
      mount_path: row.querySelector('[data-smb-profile-path]')?.value || '',
      username: row.querySelector('[data-smb-profile-username]')?.value || '',
      vers: row.querySelector('[data-smb-profile-vers]')?.value || '',
      sec: row.querySelector('[data-smb-profile-sec]')?.value || '',
      smb_password: row.querySelector('[data-smb-profile-password]')?.value || '',
      password_set: row.querySelector('[data-smb-profile-password-set]')?.value === 'true',
      mount_at_start: !!row.querySelector('[data-smb-profile-mount-at-start]')?.checked,
      keep_mounted: !!row.querySelector('[data-smb-profile-keep-mounted]')?.checked,
    });
  });
  return normalizeSmbProfileRows(rows);
}

function syncSmbProfilesHiddenInput() {
  const hidden = document.getElementById('smb-profiles-json');
  if (!hidden) return;
  hidden.value = JSON.stringify(getSmbProfilesFromDom());
}

function updateSmbAutoMountPath(row) {
  if (!row || row.dataset.smbProfileAutoPath !== 'true') return;
  const nameInput = row.querySelector('[data-smb-profile-name]');
  const pathInput = row.querySelector('[data-smb-profile-path]');
  if (!pathInput) return;
  const suffix = row.dataset.smbProfilePathSuffix || extractSmbManagedPathSuffix(pathInput.value);
  const generated = generateSmbManagedMountPathWithSuffix(nameInput?.value || '', suffix);
  row.dataset.smbProfilePathSuffix = generated.suffix;
  pathInput.value = generated.path;
}

function onSmbProfileInputChanged(event) {
  const target = event?.target || null;
  const row = target?.closest?.('.smb-profile-row') || null;
  if (target?.matches?.('[data-smb-profile-path]')) {
    if (row) row.dataset.smbProfileAutoPath = 'false';
  } else if (target?.matches?.('[data-smb-profile-name]')) {
    updateSmbAutoMountPath(row);
  }
  syncSmbProfilesHiddenInput();
  markSettingsDirty();
}

function _smbVersionSelectHtml(value) {
  const selected = String(value || '').trim() || 'auto';
  const options = [
    ['auto', settingsT('profiles.smbVersionAuto')],
    ['3.1.1', 'SMB 3.1.1'],
    ['3.0', 'SMB 3.0'],
    ['2.1', 'SMB 2.1'],
    ['2.0', 'SMB 2.0'],
  ];
  return `<select class="form-select mono" data-smb-profile-vers onchange="onSmbProfileInputChanged(event)">
    ${options.map(([raw, label]) => `<option value="${escHtml(raw)}"${selected === raw ? ' selected' : ''}>${escHtml(label)}</option>`).join('')}
  </select>`;
}

function addSmbProfileRow(row = {}) {
  const box = document.getElementById('smb-profiles-rows');
  if (!box) return;
  const key = String(row.key || '').trim();
  const name = String(row.name || '').trim();
  const server = String(row.server || '').trim();
  const share = String(row.share || '').trim();
  const suppliedPath = String(row.mount_path || '').trim();
  const generated = suppliedPath ? { path: suppliedPath, suffix: extractSmbManagedPathSuffix(suppliedPath) } : generateSmbManagedMountPathWithSuffix(name || '');
  const path = generated.path;
  const username = String(row.username || '').trim();
  const vers = String(row.vers || '').trim() || 'auto';
  const sec = String(row.sec || '').trim();
  const passwordSet = !!row.password_set;
  const mountAtStart = !!row.mount_at_start;
  const keepMounted = !!row.keep_mounted;
  const jobsCount = Number(row.jobs_count || 0);
  const wrap = document.createElement('div');
  wrap.className = 'smb-profile-row';
  wrap.dataset.smbProfileAutoPath = suppliedPath ? 'false' : 'true';
  if (generated.suffix) wrap.dataset.smbProfilePathSuffix = generated.suffix;
  if (key) wrap.dataset.profileKey = key;
  wrap.innerHTML = `
    <div class="smb-profile-main">
      <input class="form-input" type="text" data-smb-profile-name placeholder="${settingsT('profiles.profileNamePlaceholder')}" value="${escHtml(name)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <input class="form-input mono" type="text" data-smb-profile-server placeholder="${settingsT('profiles.hostPlaceholder')}" value="${escHtml(server)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <input class="form-input mono" type="text" data-smb-profile-share placeholder="${settingsT('profiles.sharePlaceholder')}" value="${escHtml(share)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <input class="form-input mono" type="text" data-smb-profile-path placeholder="/mnt/user/borg-backup-ui/remotes/nas-a-backup" value="${escHtml(path)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <input class="form-input mono" type="text" data-smb-profile-username placeholder="${settingsT('profiles.usernamePlaceholder')}" value="${escHtml(username)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <input class="form-input mono" type="password" data-smb-profile-password placeholder="${passwordSet ? settingsT('profiles.passwordSetPlaceholder') : settingsT('profiles.passwordPlaceholder')}" value="" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-toggle-options">${settingsT('profiles.options')}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-status">${settingsT('profiles.mountStatusNow')}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-mount">${settingsT('profiles.mountNow')}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-unmount">${settingsT('profiles.unmountNow')}</button>
      <button type="button" class="btn btn-danger btn-sm" data-settings-action="smb-profile-remove">${settingsT('common.remove')}</button>
      <span class="text-muted" style="font-size:12px">${settingsT('common.jobsCount', { count: jobsCount })}</span>
    </div>
    <div class="smb-profile-optional hidden" data-smb-profile-optional>
      ${_smbVersionSelectHtml(vers)}
      <input class="form-input mono" type="text" data-smb-profile-sec placeholder="${settingsT('profiles.securityPlaceholder')}" value="${escHtml(sec)}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
      <label class="form-checkbox-row"><input type="checkbox" data-smb-profile-mount-at-start ${mountAtStart ? 'checked' : ''} onchange="onSmbProfileInputChanged(event)"> <span>${settingsT('profiles.mountAtStart')}</span></label>
      <label class="form-checkbox-row"><input type="checkbox" data-smb-profile-keep-mounted ${keepMounted ? 'checked' : ''} onchange="onSmbProfileInputChanged(event)"> <span>${settingsT('profiles.keepMounted')}</span></label>
    </div>
    <div class="smb-profile-checks hidden" data-smb-profile-checks></div>
    <input type="hidden" data-smb-profile-password-set value="${passwordSet ? 'true' : 'false'}">
  `;
  box.appendChild(wrap);
}

function renderSettingsSmbProfiles(rows) {
  const normalized = normalizeSmbProfileRows(rows);
  const content = normalized.map((r) => `
    <div class="smb-profile-row" data-profile-key="${escHtml(r.key || '')}" data-smb-jobs-count="${Number(r.jobs_count || 0)}" data-smb-job-refs="${escHtml((r.job_refs || []).join(', '))}" data-smb-repositories-count="${Number(r.repositories_count || 0)}" data-smb-repository-refs="${escHtml((r.repository_refs || []).join(', '))}">
      <div class="smb-profile-main">
        <input class="form-input" type="text" data-smb-profile-name placeholder="${settingsT('profiles.profileNamePlaceholder')}" value="${escHtml(r.name || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <input class="form-input mono" type="text" data-smb-profile-server placeholder="${settingsT('profiles.hostPlaceholder')}" value="${escHtml(r.server || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <input class="form-input mono" type="text" data-smb-profile-share placeholder="${settingsT('profiles.sharePlaceholder')}" value="${escHtml(r.share || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <input class="form-input mono" type="text" data-smb-profile-path placeholder="/mnt/user/borg-backup-ui/remotes/nas-a-backup" value="${escHtml(r.mount_path || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <input class="form-input mono" type="text" data-smb-profile-username placeholder="${settingsT('profiles.usernamePlaceholder')}" value="${escHtml(r.username || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <input class="form-input mono" type="password" data-smb-profile-password placeholder="${r.password_set ? settingsT('profiles.passwordSetPlaceholder') : settingsT('profiles.passwordPlaceholder')}" value="" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-toggle-options">${settingsT('profiles.options')}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-status">${settingsT('profiles.mountStatusNow')}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-mount">${settingsT('profiles.mountNow')}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-unmount">${settingsT('profiles.unmountNow')}</button>
        <button type="button" class="btn btn-danger btn-sm" data-settings-action="smb-profile-remove">${settingsT('common.remove')}</button>
        <span class="text-muted" data-smb-profile-mount-status style="font-size:12px">${r.is_mounted ? settingsT('profiles.mounted') : settingsT('profiles.notMounted')}</span>
        <span class="text-muted" style="font-size:12px">${settingsT('common.jobsCount', { count: Number(r.jobs_count || 0) })}</span>
      </div>
      <div class="smb-profile-optional hidden" data-smb-profile-optional>
        ${_smbVersionSelectHtml(r.vers || 'auto')}
        <input class="form-input mono" type="text" data-smb-profile-sec placeholder="${settingsT('profiles.securityPlaceholder')}" value="${escHtml(r.sec || '')}" onchange="onSmbProfileInputChanged(event)" oninput="onSmbProfileInputChanged(event)">
        <label class="form-checkbox-row"><input type="checkbox" data-smb-profile-mount-at-start ${r.mount_at_start ? 'checked' : ''} onchange="onSmbProfileInputChanged(event)"> <span>${settingsT('profiles.mountAtStart')}</span></label>
        <label class="form-checkbox-row"><input type="checkbox" data-smb-profile-keep-mounted ${r.keep_mounted ? 'checked' : ''} onchange="onSmbProfileInputChanged(event)"> <span>${settingsT('profiles.keepMounted')}</span></label>
      </div>
      <div class="smb-profile-checks hidden" data-smb-profile-checks></div>
      <input type="hidden" data-smb-profile-password-set value="${r.password_set ? 'true' : 'false'}">
    </div>
  `).join('');
  return settingsCard(settingsT('profiles.smbTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18v10H3z"/><path d="M7 7V5h10v2"/><path d="M7 12h.01"/><path d="M11 12h.01"/><path d="M15 12h.01"/></svg>`,
    `<div class="settings-body">
      <div class="text-muted" style="font-size:12px;margin-bottom:10px">
        ${settingsT('profiles.smbDescription')}
      </div>
      <div id="smb-profiles-rows" style="display:grid;gap:8px">
        ${content}
      </div>
      <input type="hidden" id="smb-profiles-json" value='${escHtml(JSON.stringify(normalized))}'>
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:10px">
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-check">${settingsT('common.checkStatus')}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-settings-action="smb-profile-add">${settingsT('profiles.addSmb')}</button>
      </div>
      <div id="smb-profiles-msg" class="status-message hidden" style="margin-top:10px"></div>
      ${normalized.length === 0 ? `<div class="status-message warning" style="margin-top:10px">${settingsT('profiles.noSmb')}</div>` : ''}
    </div>`);
}

function _renderSmbChecksHtml(r) {
  const c = r?.checks || {};
  const steps = [
    { label: settingsT('profiles.smbPort'), ok: !!c.port_ok, msg: String(c.port_msg || '') },
    { label: settingsT('profiles.authentication'), ok: !!c.auth_ok, msg: String(c.auth_msg || '') },
    { label: settingsT('profiles.temporaryMount'), ok: !!c.mount_ok, msg: !!c.mount_ok ? String(c.mount_msg || '') : settingsT('profiles.mountFailed') },
    { label: settingsT('profiles.shareFound'), ok: !!c.share_ok, msg: String(c.share_msg || '') },
    { label: settingsT('profiles.writeTest'), ok: !!c.write_ok, msg: String(c.write_msg || '') },
    { label: settingsT('profiles.unmount'), ok: !!c.unmount_ok, msg: String(c.unmount_msg || '') },
  ];
  let blocked = false;
  const line = (label, ok, msg) => {
    if (blocked) {
      return `<div class="smb-check-row skip"><span>${escHtml(label)}</span><span>${settingsT('profiles.notTested')}</span></div>`;
    }
    const message = String(msg || '').trim();
    if (ok) {
      return `<div class="smb-check-row ok"><span>${escHtml(label)}</span><span>OK</span></div>`;
    }
    if (message) {
      blocked = true;
      return `<div class="smb-check-row bad"><span>${escHtml(label)}</span><span>${settingsT('common.error')}</span></div>`;
    }
    return `<div class="smb-check-row skip"><span>${escHtml(label)}</span><span>${settingsT('profiles.notTested')}</span></div>`;
  };
  const rows = steps.map((s) => line(s.label, s.ok, s.msg)).join('');
  const failureHints = {
    SMB_AUTH_OR_PERMISSION_FAILED: settingsT('profiles.smbAuthOrPermissionFailed'),
    SMB_SHARE_NOT_FOUND: settingsT('profiles.smbShareNotFound'),
    SMB_PROTOCOL_OR_OPTIONS_FAILED: settingsT('profiles.smbProtocolOrOptionsFailed'),
    SMB_NETWORK_UNREACHABLE: settingsT('profiles.smbNetworkUnreachable'),
    SMB_MOUNT_FAILED: settingsT('profiles.smbMountFailedGeneric'),
  };
  const failureHint = failureHints[String(r?.failure_code || '')] || String(r?.failure_hint || r?.message || '');
  const technicalDetails = String(r?.technical_details || '').trim();
  return `
    <div class="smb-check-grid">
      ${rows}
    </div>
    ${failureHint ? `<div class="status-message ${r?.ok ? 'success' : 'error'}" style="margin-top:8px">${escHtml(failureHint)}</div>` : ''}
    ${technicalDetails ? `<details class="smb-check-details"><summary>${settingsT('profiles.technicalDetails')}</summary><pre>${escHtml(technicalDetails)}</pre></details>` : ''}
  `;
}

function _renderStorageboxChecksHtml(payload) {
  if (!payload || !Array.isArray(payload.rows) || payload.rows.length === 0) return '';
  const rows = payload.rows.map((row) => {
    const ok = !!row?.ok;
    const label = String(row?.label || '');
    const msg = String(row?.message || '');
    return `<div class="smb-check-row ${ok ? 'ok' : 'fail'}"><span>${escHtml(label)}</span><span>${ok ? settingsT('common.ok') : settingsT('common.error')}${msg ? ` - ${escHtml(msg)}` : ''}</span></div>`;
  }).join('');
  const details = String(payload.details || '').trim();
  return `
    <div class="smb-check-grid">
      ${rows}
    </div>
    ${details ? `<details class="smb-check-details"><summary>${settingsT('common.details')}</summary><pre>${escHtml(details)}</pre></details>` : ''}
  `;
}

function renderSettingsSystemHealth(data) {
  const startupState = data?.startup_state && typeof data.startup_state === 'object'
    ? data.startup_state
    : (window.BBUI?.core?.getStartupState?.() || {});
  const maintenanceActive = String(startupState?.mode || '') === 'maintenance';
  const startupFailures = Array.isArray(startupState?.failures) ? startupState.failures : [];
  const primaryStartupFailure = startupFailures.find((row) => String(row?.error || '').trim()) || startupFailures[0] || {};
  const failedStartupMigrations = Array.isArray(startupState?.failed_migrations)
    ? startupState.failed_migrations.map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  const startupMigration = String(primaryStartupFailure?.migration_id || failedStartupMigrations[0] || '—');
  const startupPhase = String(primaryStartupFailure?.phase || settingsT('health.startupFailureUnknownPhase'));
  const startupCause = String(primaryStartupFailure?.error || settingsT('health.startupFailureUnknownCause'));
  const cifsState = String(data?.checks?.cifs_state || '').toLowerCase();
  const cifsDetail = cifsState === 'loaded'
    ? settingsT('health.cifsLoaded')
    : (cifsState === 'available' ? settingsT('health.cifsAvailable') : settingsT('health.cifsMissing'));
  const perms = data?.secrets_permissions || {};
  const permDetail = perms.ok
    ? settingsT('health.permissionsOk')
    : ((Array.isArray(perms.bad_files) && perms.bad_files.length)
      ? perms.bad_files.map((f) => `${f.path} (${f.mode})`).join(' | ')
      : settingsT('health.checkPermissions'));
  const inventories = data?.canonical_inventories || {};
  const inventoryDetail = inventories.ok
    ? settingsT('health.inventoriesOk')
    : (Array.isArray(inventories.errors)
      ? inventories.errors.map((row) => `${row.path}: ${row.error}`).join(' | ')
      : settingsT('health.inventoriesFailed'));
  const assignments = data?.repository_assignments || {};
  const assignmentProblems = [
    ...(Array.isArray(assignments.errors) ? assignments.errors : []),
    ...(Array.isArray(assignments.usage_mismatches) ? assignments.usage_mismatches : []),
  ];
  const assignmentDetail = assignments.ok
    ? settingsT('health.repositoryAssignmentsOk')
    : (assignmentProblems.map((row) => String(row?.message || row?.job_key || row?.repository_key || '')).filter(Boolean).join(' | ')
      || settingsT('health.repositoryAssignmentsFailed'));
  const checks = [
    [settingsT('health.dataRoot'), data?.checks?.data_root_ok, data?.paths?.data_root || '—'],
    [settingsT('health.jobsPath'), data?.checks?.jobs_path_ok, data?.paths?.jobs || '—'],
    [settingsT('health.secretsPath'), data?.checks?.secrets_path_ok, data?.paths?.secrets || '—'],
    [settingsT('health.mountAvailable'), data?.checks?.mount_bin_ok, `${data?.paths?.mount_bin || '—'} | ${data?.paths?.umount_bin || '—'}`],
    [settingsT('health.cifsSupport'), data?.checks?.cifs_supported, cifsDetail],
    [settingsT('health.secretPermissions'), data?.checks?.secrets_permissions_ok, permDetail],
    [settingsT('health.canonicalInventories'), data?.checks?.canonical_inventories_ok, inventoryDetail],
    [settingsT('health.repositoryAssignments'), data?.checks?.repository_assignments_ok, assignmentDetail],
  ];
  const migrationSummary = _buildMigrationSummary(data || {});
  const lastEffectiveTs = _formatHealthTimestamp(migrationSummary.lastEffectiveRun) || settingsT('health.noEffectiveChanges');
  const registrySummary = data?.migration_registry?.summary && typeof data.migration_registry.summary === 'object'
    ? data.migration_registry.summary
    : {};
  const registryItems = Array.isArray(data?.migration_registry?.items) ? data.migration_registry.items : [];
  const registryActionItems = _migrationRegistryActionItems(registryItems);
  const jobHealth = data?.job_health && typeof data.job_health === 'object' ? data.job_health : {};
  const jobSummary = jobHealth.summary && typeof jobHealth.summary === 'object' ? jobHealth.summary : {};
  const jobItems = Array.isArray(jobHealth.items) ? jobHealth.items : [];
  const jobFailed = Number(jobSummary.failed || 0);
  const runtimeRecovery = data?.runtime_recovery && typeof data.runtime_recovery === 'object' ? data.runtime_recovery : {};
  const runtimeAttention = Number(runtimeRecovery.attention_count || 0);
  const failedChecks = checks.filter(([, ok]) => !ok).length;
  const registryAttention = Number(registrySummary?.pending || 0) + Number(registrySummary?.failed || 0) + Number(registrySummary?.blocked || 0);
  const overallOk = !maintenanceActive && failedChecks === 0 && migrationSummary.status !== 'failed' && registryAttention === 0 && jobFailed === 0 && runtimeAttention === 0;
  const jobTotal = Number(jobSummary.total || jobItems.length || 0);
  const jobsDetail = jobFailed
    ? settingsT('health.jobChecksFailed', { count: jobFailed })
    : `${jobTotal} ${settingsT('health.jobs')}`;
  const migrationOk = !maintenanceActive && migrationSummary.status !== 'failed';
  const migrationStateLabel = maintenanceActive ? settingsT('health.startupBlocked') : migrationSummary.state;
  const migrationReasonLabel = maintenanceActive ? startupCause : migrationSummary.reason;
  const startupFailureHtml = maintenanceActive ? `
      <section class="startup-migration-critical" role="alert">
        <div class="startup-migration-critical-header">
          <span class="startup-migration-critical-mark">!</span>
          <div>
            <strong>${settingsT('health.startupFailureTitle')}</strong>
            <span>${settingsT('health.startupFailureSubtitle')}</span>
          </div>
          <span class="system-health-badge bad">${settingsT('health.severityCritical')}</span>
        </div>
        <div class="startup-migration-facts">
          <div><span>${settingsT('health.startupFailureMigration')}</span><strong>${escHtml(startupMigration)}</strong></div>
          <div><span>${settingsT('health.startupFailurePhase')}</span><strong>${escHtml(startupPhase)}</strong></div>
          <div><span>${settingsT('health.startupFailureCause')}</span><strong>${escHtml(startupCause)}</strong></div>
        </div>
        <div class="startup-migration-recommendations">
          <strong>${settingsT('health.startupFailureRecommendations')}</strong>
          <ol>
            <li>${settingsT('health.recommendationSupportBundle')}</li>
            <li>${escHtml(settingsT('health.recommendationMigrationLog', { path: data?.paths?.migration_log_file || '—' }))}</li>
            <li>${settingsT('health.recommendationCorrectCause')}</li>
            <li>${settingsT('health.recommendationRestart')}</li>
            <li>${settingsT('health.recommendationPreserveState')}</li>
          </ol>
          <button type="button" class="btn btn-secondary btn-sm" data-settings-tab="transfer">${settingsT('health.openImportExport')}</button>
        </div>
      </section>` : '';
  const technicalRows = [
    [settingsT('health.migrationState'), data?.paths?.migration_state_file || '—'],
    [settingsT('health.migrationLog'), data?.paths?.migration_log_file || '—'],
    [settingsT('health.checkedSecretFiles'), String(perms.checked_files_count ?? 0)],
  ];

  return settingsCard(settingsT('health.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    `<div class="settings-body">
      ${startupFailureHtml}
      <div class="system-health-overview ${overallOk ? 'ok' : 'bad'}">
        <span class="system-health-overview-mark">${overallOk ? '✓' : '!'}</span>
        <div>
          <div class="system-health-overview-title">${overallOk ? settingsT('health.okTitle') : (maintenanceActive ? settingsT('health.startupBlocked') : settingsT('health.attentionTitle'))}</div>
          <div class="system-health-overview-subtitle">${overallOk ? settingsT('health.okSubtitle') : (maintenanceActive ? settingsT('health.startupFailureSubtitle') : _systemHealthAttentionText(failedChecks, registryAttention, jobFailed, runtimeAttention))}</div>
        </div>
        <span class="system-health-badge ${overallOk ? 'ok' : 'bad'}">${overallOk ? settingsT('common.ok') : settingsT('health.check')}</span>
      </div>

      <div class="settings-health-summary-grid">
        <div><span>${settingsT('health.dataRoot')}</span><strong class="${data?.checks?.data_root_ok ? 'ok' : 'bad'}">${data?.checks?.data_root_ok ? settingsT('common.ok') : settingsT('health.check')}</strong><small>${escHtml(data?.paths?.data_root || '—')}</small></div>
        <div><span>${settingsT('health.jobsPath')}</span><strong class="${jobFailed ? 'bad' : 'ok'}">${jobFailed ? settingsT('health.check') : settingsT('common.ok')}</strong><small>${escHtml(jobsDetail)}</small></div>
        <div><span>${settingsT('health.secretsPath')}</span><strong class="${data?.checks?.secrets_path_ok ? 'ok' : 'bad'}">${data?.checks?.secrets_path_ok ? settingsT('common.ok') : settingsT('health.check')}</strong><small>${escHtml(String(perms.checked_files_count ?? 0))} ${settingsT('health.checkedSecretFiles')}</small></div>
        <div><span>${settingsT('health.lastMigration')}</span><strong class="${migrationOk ? 'ok' : 'bad'}">${escHtml(migrationStateLabel)}</strong><small>${escHtml(migrationReasonLabel)}</small></div>
      </div>

      <details class="system-health-technical">
        <summary>${settingsT('health.technicalDetails')}</summary>
        <div class="system-health-block">
          <div class="system-health-block-title">${settingsT('health.system')}</div>
          <div class="system-health-grid">${_renderSystemHealthRows(checks)}</div>
        </div>

        <div class="system-health-block">
          <div class="system-health-block-title">${settingsT('health.jobs')}</div>
          ${_renderJobHealthOverview(jobSummary, jobItems)}
        </div>

        <div class="system-health-block">
          <div class="system-health-block-title">${settingsT('health.runtimeRecovery')}</div>
          ${_renderRuntimeRecoveryOverview(runtimeRecovery)}
        </div>

        <div class="system-health-block">
          <div class="system-health-block-title">${settingsT('health.lastMigration')}</div>
          <div class="migration-status-grid">
            <div><span class="system-health-name">${settingsT('health.lastRun')}</span><strong>${escHtml(migrationSummary.lastRun)}</strong></div>
            <div><span class="system-health-name">${settingsT('health.lastEffectiveRun')}</span><strong>${escHtml(lastEffectiveTs)}</strong></div>
            <div><span class="system-health-name">${settingsT('health.status')}</span><span class="system-health-badge ${migrationOk ? 'ok' : 'bad'}">${escHtml(migrationStateLabel)}</span></div>
          </div>
          <div class="migration-summary">
            <div><strong>${settingsT('health.reason')}</strong> ${escHtml(migrationReasonLabel)}</div>
            <div><strong>${settingsT('health.actions')}</strong> ${migrationSummary.actions.length ? migrationSummary.actions.map((a) => escHtml(a)).join(' · ') : settingsT('common.none')}</div>
            ${migrationSummary.errors ? `<div class="system-health-error"><strong>${settingsT('health.errors')}</strong> ${escHtml(migrationSummary.errors)}</div>` : ''}
          </div>
        </div>

        <div class="system-health-block">
          <div class="system-health-block-title">${settingsT('health.setupConfigMaintenance')}</div>
          ${_renderMigrationRegistryOverview(registrySummary, registryActionItems)}
        </div>
        <div class="system-health-grid">
          ${technicalRows.map(([name, detail]) => `
            <div class="system-health-row neutral">
              <span class="system-health-name">${escHtml(name)}</span>
              <span class="system-health-state">•</span>
              <span class="system-health-detail">${escHtml(String(detail || '—'))}</span>
            </div>
          `).join('')}
        </div>
        ${registryItems.length ? `
          <div class="migration-registry-list">
            ${_renderMigrationRegistryGroups(registryItems)}
          </div>
        ` : ''}
        ${migrationSummary.techMsg ? `
          <details class="system-health-technical migration-startup-technical">
            <summary>${escHtml(settingsT('health.technicalStartupSummary'))}</summary>
            <pre class="system-health-tech-msg">${escHtml(migrationSummary.techMsg)}</pre>
          </details>
        ` : ''}
      </details>
    </div>`);
}

function renderSettingsAdvancedTabs(data, systemHealth) {
  const active = settingsState.advancedTab === 'passphrases' ? 'passphrases' : 'reminders';
  settingsState.advancedTab = active;
  return `
    <div class="settings-subtab-card">
      <div class="segmented-control settings-subtab-control" role="tablist" aria-label="${escHtml(settingsT('tabs.advanced'))}">
        <button type="button" class="segmented-btn ${active === 'reminders' ? 'active' : ''}" data-settings-advanced-tab="reminders" role="tab" aria-selected="${active === 'reminders' ? 'true' : 'false'}">${settingsT('health.notificationReminders')}</button>
        <button type="button" class="segmented-btn ${active === 'passphrases' ? 'active' : ''}" data-settings-advanced-tab="passphrases" role="tab" aria-selected="${active === 'passphrases' ? 'true' : 'false'}">${settingsT('forms.perRepoTitle')}</button>
      </div>
    </div>
    <div class="settings-subtab-panel ${active === 'reminders' ? '' : 'hidden'}" data-settings-advanced-panel="reminders">
      ${renderSettingsNotificationReminderDiagnostics(systemHealth?.notification_reminders || {})}
    </div>
    <div class="settings-subtab-panel ${active === 'passphrases' ? '' : 'hidden'}" data-settings-advanced-panel="passphrases">
      ${renderSettingsPerRepoPassphrases(data.per_repo_passphrases || [])}
    </div>
  `;
}

function renderSettingsNotificationReminderDiagnostics(data) {
  const icon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`;
  if (!data || !data.enabled) {
    const error = String(data?.error || '').trim();
    return `<div class="settings-section settings-reminder-diagnostics-card">
      <div class="settings-section-header">${icon}<div><strong>${settingsT('health.notificationReminders')}</strong></div></div>
      <div class="settings-body"><p class="text-muted" style="font-size:13px;margin:0">${escHtml(error || settingsT('health.notificationRemindersInactive'))}</p></div>
    </div>`;
  }
  const settings = data.settings && typeof data.settings === 'object' ? data.settings : {};
  const generated = _formatReminderTimestamp(data.generated_at) || String(data.generated_at || '—');
  return `<div class="settings-section settings-reminder-diagnostics-card">
    <div class="settings-section-header">${icon}<div><strong>${settingsT('health.notificationReminders')}</strong></div></div>
    <div class="settings-body">
      <div class="migration-overview-grid">
        ${_renderMigrationMetric(settingsT('health.reminderIntervalHours'), Number(settings.reminder_interval_hours || 0), 'neutral')}
        ${_renderMigrationMetric(settingsT('health.backupToleranceHours'), Number(settings.backup_overdue_tolerance_hours || 0), 'neutral')}
      </div>
      <div class="migration-registry-id" style="margin:8px 0 12px">${escHtml(settingsT('health.generatedAt'))}: ${escHtml(generated)}</div>
      <p class="reminder-diagnostics-hint">${escHtml(settingsT('health.notificationReminderDiagnosticsHint'))}</p>
      ${_renderReminderGroup(data.backup_overdue || {}, settingsT('health.backupOverdueDiagnostics'))}
      ${_renderReminderGroup(data.restore_test_overdue || {}, settingsT('health.restoreTestOverdueDiagnostics'))}
    </div>
  </div>`;
}

function _renderReminderGroup(group, title) {
  if (!group || !group.enabled) return '';
  const items = Array.isArray(group.items) ? group.items : [];
  const channels = Array.isArray(group.channels) ? group.channels.join(', ') : '';
  return `
    <div class="migration-registry-group">
      <div class="migration-registry-group-title">${escHtml(title)}${channels ? ` · ${escHtml(channels)}` : ''}</div>
      ${items.length ? _renderReminderTable(items) : `<div class="migration-action-empty">${settingsT('health.noReminderItems')}</div>`}
    </div>
  `;
}

function _renderReminderTable(items) {
  return `
    <div class="reminder-diagnostics-table-wrap">
      <table class="settings-table reminder-diagnostics-table">
        <thead>
          <tr>
            <th>${settingsT('health.job')}</th>
            <th>${settingsT('health.status')}</th>
            <th>${settingsT('health.expectedRun')}</th>
            <th>${settingsT('health.latestStatus')}</th>
            <th>${settingsT('health.reminderInfo')}</th>
          </tr>
        </thead>
        <tbody>${items.map(_renderReminderTableRow).join('')}</tbody>
      </table>
    </div>
  `;
}

function _renderReminderTableRow(item) {
  const state = String(item?.state || 'unknown').trim();
  const tone = state === 'overdue_ready' ? 'warn' : (state === 'overdue_waiting' ? 'warning' : (state === 'unsupported' || state === 'missing_due' || state === 'missing_status' ? 'error' : 'success'));
  const type = String(item?.type || '');
  const expected = type === 'backup_overdue' ? item.expected_run : item.next_due_at;
  const nextScheduled = type === 'backup_overdue' ? item.next_scheduled_run : '';
  const overdueAfter = type === 'backup_overdue' ? item.overdue_after : item.next_due_at;
  const latest = type === 'backup_overdue'
    ? (item.latest_status_at || item.latest_status)
    : (item.last_test_date || (item.level ? `L${item.level}` : ''));
  const reminderKey = String(item?.reminder_key || '').trim();
  const expectedFormatted = _formatReminderTimestamp(expected) || String(expected || '—');
  const nextScheduledFormatted = _formatReminderTimestamp(nextScheduled) || String(nextScheduled || '');
  const overdueAfterFormatted = _formatReminderTimestamp(overdueAfter) || String(overdueAfter || '—');
  const latestFormatted = _formatReminderTimestamp(latest) || String(latest || '—');
  const sentFormatted = item?.sent ? (_formatReminderTimestamp(item.sent_at) || item.sent_at || '—') : settingsT('health.notSentYet');
  const nextAllowedFormatted = item?.next_allowed_at ? (_formatReminderTimestamp(item.next_allowed_at) || item.next_allowed_at) : '—';
  const showNextScheduled = nextScheduledFormatted && nextScheduledFormatted !== expectedFormatted;
  const scheduleRows = type === 'backup_overdue'
    ? [
        [settingsT('health.monitoredRun'), expectedFormatted],
        [settingsT('health.overdueAfter'), overdueAfterFormatted],
        ...(showNextScheduled ? [[settingsT('health.nextScheduledRun'), nextScheduledFormatted]] : []),
      ]
    : [[settingsT('health.nextDueAt'), expectedFormatted]];
  const reminderRows = [
    [settingsT('health.sentAt'), sentFormatted],
    ...(item?.next_allowed_at ? [[settingsT('health.nextAllowedAt'), nextAllowedFormatted]] : []),
  ];
  return `
    <tr>
      <td>
        <strong class="reminder-job-name" ${reminderKey ? `title="${escHtml(reminderKey)}"` : ''}>${escHtml(String(item?.display_name || item?.job_key || 'Job'))}</strong>
      </td>
      <td><span class="badge reminder-state-badge ${escHtml(tone)}">${escHtml(_reminderStateLabel(state))}</span></td>
      <td class="reminder-date-cell">
        ${scheduleRows.map(([label, value]) => _renderReminderDetailLine(label, value)).join('')}
      </td>
      <td class="reminder-date-cell"><span class="reminder-date-main">${escHtml(latestFormatted)}</span></td>
      <td class="reminder-date-cell reminder-detail-stack">
        ${reminderRows.map(([label, value]) => _renderReminderStackLine(label, value)).join('')}
      </td>
    </tr>
  `;
}

function _renderReminderDetailLine(label, value) {
  return `<span class="reminder-detail-line"><span class="reminder-detail-label">${escHtml(label)}:</span><span class="reminder-detail-value">${escHtml(value || '—')}</span></span>`;
}

function _renderReminderStackLine(label, value) {
  return `<span class="reminder-stack-line"><span class="reminder-detail-label">${escHtml(label)}</span><span class="reminder-detail-value">${escHtml(value || '—')}</span></span>`;
}

function _reminderStateLabel(state) {
  const labels = {
    current: settingsT('health.reminderCurrent'),
    overdue_ready: settingsT('health.reminderReady'),
    overdue_waiting: settingsT('health.reminderWaiting'),
    unsupported: settingsT('health.reminderUnsupported'),
    missing_due: settingsT('health.reminderMissingDue'),
    missing_status: settingsT('health.reminderMissingStatus'),
  };
  return labels[state] || state || settingsT('health.statusUnknown');
}

function _formatHealthTimestamp(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const d = new Date(raw);
    if (!Number.isNaN(d.getTime())) return d.toLocaleString(settingsLocale());
  } catch (_) {}
  return raw;
}

function _formatReminderTimestamp(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const d = new Date(raw);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(settingsLocale(), {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    }
  } catch (_) {}
  return raw;
}

function _renderSystemHealthRows(rows) {
  const icon = (ok) => ok ? '✓' : '✗';
  const cls = (ok) => ok ? 'ok' : 'bad';
  return rows.map(([name, ok, detail]) => `
    <div class="system-health-row ${cls(!!ok)}">
      <span class="system-health-name">${escHtml(name)}</span>
      <span class="system-health-state">${icon(!!ok)}</span>
      <span class="system-health-detail">${escHtml(String(detail || '—'))}</span>
    </div>
  `).join('');
}

function _formatMigrationRegistrySummary(summary) {
  const total = Number(summary?.total || 0);
  if (!total) return settingsT('health.noRegistryData');
  const parts = [
    `${total} ${settingsT('common.entries')}`,
    `${Number(summary?.pending || 0)} ${settingsT('health.statusPending')}`,
    `${Number(summary?.failed || 0)} ${settingsT('health.statusFailed')}`,
    `${Number(summary?.blocked || 0)} ${settingsT('health.statusBlocked')}`,
  ];
  return parts.join(', ');
}

function _systemHealthAttentionText(failedChecks, registryAttention, jobFailed = 0, runtimePending = 0) {
  const parts = [];
  if (failedChecks > 0) parts.push(settingsT('health.systemChecksFailed', { count: failedChecks }));
  if (jobFailed > 0) parts.push(settingsT('health.jobChecksFailed', { count: jobFailed }));
  if (runtimePending > 0) parts.push(settingsT('health.runtimeRecoveryOpen', { count: runtimePending }));
  if (registryAttention > 0) parts.push(settingsT('health.maintenanceOpen', { count: registryAttention }));
  return parts.join(' · ') || settingsT('health.attentionTitle');
}

function _renderJobHealthOverview(summary, items) {
  const total = Number(summary?.total || 0);
  const failed = Number(summary?.failed || 0);
  const warnings = Number(summary?.warnings || 0);
  const ok = Number(summary?.ok || 0);
  const problemItems = (Array.isArray(items) ? items : []).filter((item) => String(item?.state || '') !== 'ok');
  const hasProblems = failed > 0 || warnings > 0;
  return `
    <div class="migration-overview-grid">
      ${_renderMigrationMetric(settingsT('health.jobs'), total, 'neutral')}
      ${_renderMigrationMetric(settingsT('common.ok'), ok, 'ok')}
      ${_renderMigrationMetric(settingsT('common.warnings'), warnings, warnings > 0 ? 'warn' : 'ok')}
      ${_renderMigrationMetric(settingsT('common.failed'), failed, failed > 0 ? 'bad' : 'ok')}
    </div>
    <div class="migration-action-panel ${hasProblems ? 'attention' : 'ok'}">
      <div class="migration-action-title">${hasProblems ? settingsT('health.jobChecksAttention') : settingsT('health.jobChecksOk')}</div>
      ${hasProblems ? _renderJobHealthProblems(problemItems) : `<div class="migration-action-empty">${settingsT('health.jobChecksPlausible')}</div>`}
    </div>
  `;
}

function _renderJobHealthProblems(items) {
  if (!items.length) return `<div class="migration-action-empty">${settingsT('health.noDetails')}</div>`;
  return `<div class="migration-action-list">${items.map((item) => {
    const errors = Array.isArray(item?.errors) ? item.errors : [];
    const errorDetails = Array.isArray(item?.error_details) ? item.error_details : [];
    const warnings = Array.isArray(item?.warnings) ? item.warnings : [];
    const localizedErrors = errorDetails.length
      ? errorDetails.map((row) => {
        const code = String(row?.code || '').trim();
        return code ? settingsT(`health.jobErrors.${code}`, row?.params || {}) : '';
      }).filter(Boolean)
      : errors;
    const details = localizedErrors.concat(warnings).map((v) => String(v || '').trim()).filter(Boolean).join(' · ');
    return `
      <div class="migration-action-row ${escHtml(String(item?.state || 'bad'))}">
        <div>
          <strong>${escHtml(String(item?.name || item?.job_key || 'Job'))}</strong>
          <span>${escHtml(details || settingsT('health.checkFailed'))}</span>
        </div>
      </div>
    `;
  }).join('')}</div>`;
}

function _renderRuntimeRecoveryOverview(recovery) {
  const attentionEntries = Array.isArray(recovery?.entries) ? recovery.entries : [];
  const activeEntries = Array.isArray(recovery?.active_entries) ? recovery.active_entries : [];
  const attention = Number(recovery?.attention_count || attentionEntries.length || 0);
  const active = Number(recovery?.active_count || activeEntries.length || 0);
  const pending = Number(recovery?.pending_count || attention + active || 0);
  if (!pending) {
    return `
      <div class="migration-overview-grid">
        ${_renderMigrationMetric(settingsT('health.runtimeRecoveryPending'), 0, 'ok')}
      </div>
      <div class="migration-action-panel ok">
        <div class="migration-action-title">${settingsT('health.runtimeRecoveryOk')}</div>
        <div class="migration-action-empty">${escHtml(recovery?.state_file || '')}</div>
      </div>
    `;
  }
  if (!attention) {
    return `
      <div class="migration-overview-grid">
        ${_renderMigrationMetric(settingsT('health.runtimeRecoveryPending'), pending, 'neutral')}
        ${_renderMigrationMetric(settingsT('health.runtimeRecoveryDocker'), Number(recovery?.docker_pending_count || 0), 'neutral')}
        ${_renderMigrationMetric(settingsT('health.runtimeRecoveryVms'), Number(recovery?.vm_pending_count || 0), 'neutral')}
      </div>
      <div class="migration-action-panel ok">
        <div class="migration-action-title">${settingsT('health.runtimeRecoveryOk')}</div>
        <div class="migration-action-empty">${escHtml(recovery?.state_file || '')}</div>
      </div>
    `;
  }
  return `
    <div class="migration-overview-grid">
      ${_renderMigrationMetric(settingsT('health.runtimeRecoveryPending'), attention, 'warn')}
      ${_renderMigrationMetric(settingsT('health.runtimeRecoveryDocker'), Number(recovery?.docker_attention_count || 0), 'warn')}
      ${_renderMigrationMetric(settingsT('health.runtimeRecoveryVms'), Number(recovery?.vm_attention_count || 0), 'warn')}
    </div>
    <div class="migration-action-panel attention">
      <div class="migration-action-title">${settingsT('health.runtimeRecoveryAttention')}</div>
      <div class="migration-action-list">
        ${attentionEntries.map((entry) => _renderRuntimeRecoveryEntry(entry, 'warn')).join('')}
      </div>
      <div class="migration-action-empty">${escHtml(recovery?.state_file || '')}</div>
    </div>
  `;
}

function _renderRuntimeRecoveryEntry(entry, tone = 'warn') {
  const targets = Array.isArray(entry?.targets) ? entry.targets : [];
  const targetText = targets.map((target) => String(target?.name || target?.id || '').trim()).filter(Boolean).join(', ');
  const kind = String(entry?.kind || '').trim();
  const state = String(entry?.state || '').trim();
  const entryId = String(entry?.id || '').trim();
  return `
    <div class="migration-action-row ${escHtml(tone)}">
      <div>
        <strong>${escHtml(String(entry?.job_name || entry?.backup_type || 'Backup'))}</strong>
        <span>${escHtml(settingsT('health.runtimeRecoveryDetail', {
          kind: kind || 'runtime',
          state: state || 'pending',
          count: targets.length,
          stoppedAt: String(entry?.stopped_at || '—'),
        }))}</span>
        <span>${escHtml(targetText || settingsT('health.noDetails'))}</span>
      </div>
      ${entryId ? `<button class="btn btn-secondary btn-sm migration-action-button" data-settings-action="runtime-recovery-ack" data-runtime-recovery-id="${escHtml(entryId)}">${settingsT('health.runtimeRecoveryAck')}</button>` : ''}
    </div>
  `;
}

function _migrationRegistryActionItems(items) {
  return items.filter((item) => {
    const status = String(item?.status || '').trim();
    return status === 'pending' || status === 'failed' || status === 'blocked';
  });
}

function _renderMigrationRegistryOverview(summary, actionItems) {
  const total = Number(summary?.total || 0);
  if (!total) return `<div class="migration-action-empty">${settingsT('health.noRegistryData')}</div>`;
  const pending = Number(summary?.pending || 0);
  const failed = Number(summary?.failed || 0);
  const blocked = Number(summary?.blocked || 0);
  const hasAction = actionItems.length > 0;
  return `
    <div class="migration-overview-grid">
      ${_renderMigrationMetric(settingsT('common.entries'), total, 'neutral')}
      ${_renderMigrationMetric(settingsT('common.pending'), pending, pending > 0 ? 'warn' : 'ok')}
      ${_renderMigrationMetric(settingsT('common.failed'), failed, failed > 0 ? 'bad' : 'ok')}
      ${_renderMigrationMetric(settingsT('health.statusBlocked'), blocked, blocked > 0 ? 'warn' : 'ok')}
    </div>
    <div class="migration-action-panel ${hasAction ? 'attention' : 'ok'}">
      <div class="migration-action-title">${hasAction ? settingsT('health.openItems') : settingsT('health.noActionRequired')}</div>
      ${hasAction ? _renderMigrationActionList(actionItems) : `<div class="migration-action-empty">${settingsT('health.registryOk')}</div>`}
    </div>
  `;
}

function _renderMigrationMetric(label, value, tone) {
  return `
    <div class="migration-metric ${escHtml(tone)}">
      <span>${escHtml(label)}</span>
      <strong>${Number(value || 0)}</strong>
    </div>
  `;
}

function _renderMigrationActionList(actionItems) {
  const rows = actionItems.map((item) => _renderMigrationActionItem(item)).join('');
  return `<div class="migration-action-list">${rows}</div>`;
}

function _renderMigrationActionItem(item) {
  const status = String(item?.status || 'unknown').trim();
  const title = _migrationRegistryText(item, 'title');
  const reason = _migrationRegistryText(item, 'reason');
  const details = item?.details && typeof item.details === 'object' ? item.details : {};
  const count = _migrationRegistryAffectedCount(details);
  const suffix = count > 0 ? ` · ${settingsT('health.affected', { count })}` : '';
  return `
    <div class="migration-action-row ${escHtml(status)}">
      <div>
        <strong>${escHtml(title)}</strong>
        <span>${escHtml(_migrationRegistryStatusLabel(status))}${escHtml(suffix)}${reason ? `: ${escHtml(reason)}` : ''}</span>
      </div>
    </div>
  `;
}

function _migrationRegistryAffectedCount(details = {}) {
  const missing = Number(details.missing_count || 0);
  const unknown = Number(details.unknown_count || 0);
  const candidates = Number(details.candidate_count || 0);
  const changed = details.canonical_content_changed === true ? 1 : 0;
  return Math.max(candidates, missing + unknown + changed);
}

function _migrationRegistryStatusLabel(status) {
  const raw = String(status || 'unknown').trim();
  const labels = {
    applied: settingsT('health.statusApplied'),
    pending: settingsT('health.statusPending'),
    failed: settingsT('health.statusFailed'),
    blocked: settingsT('health.statusBlocked'),
    not_needed: settingsT('health.statusNotNeeded'),
    not_required: settingsT('health.statusNotNeeded'),
    unknown: settingsT('health.statusUnknown'),
  };
  return labels[raw] || raw;
}

function _migrationRegistryText(item, field) {
  const id = String(item?.id || '').trim();
  const status = String(item?.status || '').trim();
  const keys = {
    setup_jobs_dir: {
      title: 'registryJobsDirTitle',
      reason: status === 'applied' ? 'registryJobsDirPresent' : 'registryJobsDirMissing',
    },
    setup_storage_inventory: {
      title: 'registryStorageInventoryTitle',
      reason: status === 'applied' ? 'registryStorageInventoryPresent' : 'registryStorageInventoryMissing',
    },
    config_backup_conf_schema: {
      title: 'registrySchemaTitle',
      reason: status === 'applied' ? 'registrySchemaComplete' : '',
    },
    notification_events_v1: {
      title: 'registryNotificationEventsTitle',
      reason: status === 'applied' ? 'registryNotificationEventsApplied' : (status === 'not_needed' ? 'registryNotificationEventsCurrent' : 'registryNotificationEventsPending'),
    },
    canonical_data_model_v1: {
      title: 'registryCanonicalModelTitle',
      reason: status === 'applied' ? 'registryCanonicalModelApplied' : (status === 'not_needed' ? 'registryCanonicalModelCurrent' : (status === 'failed' ? 'registryCanonicalModelFailed' : 'registryCanonicalModelPending')),
    },
    job_source_paths_v1: {
      title: 'registryJobSourcePathsTitle',
      reason: status === 'applied' ? 'registryJobSourcePathsApplied' : (status === 'not_needed' ? 'registryJobSourcePathsCurrent' : (status === 'failed' ? 'registryJobSourcePathsFailed' : 'registryJobSourcePathsPending')),
    },
    smb_protocol_auto_v1: {
      title: 'registrySmbProtocolTitle',
      reason: status === 'applied' ? 'registrySmbProtocolApplied' : (['not_needed', 'not_required'].includes(status) ? 'registrySmbProtocolCurrent' : (status === 'failed' ? 'registrySmbProtocolFailed' : 'registrySmbProtocolPending')),
    },
    borg_keyfiles_v1: {
      title: 'registryBorgKeyfilesTitle',
      reason: status === 'applied' ? 'registryBorgKeyfilesApplied' : (status === 'not_needed' ? 'registryBorgKeyfilesCurrent' : 'registryBorgKeyfilesPending'),
    },
    canonical_storage_profiles_v1: {
      title: 'registryCanonicalStoragesTitle',
      reason: status === 'applied' ? 'registryCanonicalStoragesApplied' : (status === 'not_needed' ? 'registryCanonicalStoragesCurrent' : 'registryCanonicalStoragesPending'),
    },
  };
  const key = keys[id]?.[field];
  if (key) return settingsT(`health.${key}`);
  return String(item?.[field] || (field === 'title' ? id || settingsT('health.entry') : '')).trim();
}

function _renderMigrationRegistryItem(item) {
  const status = String(item?.status || 'unknown').trim();
  const stage = String(item?.stage || 'active').trim();
  const statusLabel = _migrationRegistryStatusLabel(status);
  const plannedSuffix = stage === 'planned' && status !== 'not_needed' ? ` · ${settingsT('health.planned')}` : '';
  const title = _migrationRegistryText(item, 'title') || settingsT('health.migration');
  const id = String(item?.id || '').trim();
  const reason = _migrationRegistryText(item, 'reason');
  const details = item?.details && typeof item.details === 'object' ? item.details : {};
  const candidates = Array.isArray(details.candidate_keys) ? details.candidate_keys : [];
  const updatedKeys = Array.isArray(details.updated_keys) ? details.updated_keys.map((key) => String(key || '').trim()).filter(Boolean) : [];
  const appliedAt = String(details.applied_at || '').trim();
  const lastCheckedAt = String(details.last_checked_at || '').trim();
  const introducedIn = String(details.introduced_in || '').trim();
  const failedPhase = String(details.failed_phase || '').trim();
  const failureReason = String(details.error || '').trim();
  const rollbackStatus = String(details.rollback_status || '').trim();
  const missingKeys = Array.isArray(details.missing_keys) ? details.missing_keys.map((key) => String(key || '').trim()).filter(Boolean) : [];
  const unknownKeys = Array.isArray(details.unknown_keys) ? details.unknown_keys.map((key) => String(key || '').trim()).filter(Boolean) : [];
  const canonicalChanged = details.canonical_content_changed === true;
  const plan = details?.dry_run_plan && typeof details.dry_run_plan === 'object' ? details.dry_run_plan : null;
  const planCandidateCount = Number(plan?.candidate_count || 0);
  const planText = plan && planCandidateCount > 0
    ? settingsT('health.dryRunPlan', {
      count: Number(plan.candidate_count || 0),
      mode: plan.mode === 'remove' ? settingsT('health.removeKeys') : settingsT('health.commentKeys'),
    })
    : '';
  const auditRows = [
    [settingsT('health.migrationActions'), details.actions],
    [settingsT('health.updatedKeys'), details.updated_keys],
    [settingsT('health.addedKeys'), details.added_keys],
    [settingsT('health.removedKeys'), details.removed_keys],
    [settingsT('health.missingKeys'), details.missing_keys],
    [settingsT('health.unknownKeys'), details.unknown_keys],
    [settingsT('health.affectedFiles'), details.affected_files],
    [settingsT('health.backupDirectory'), details.backup_directory],
    [settingsT('health.runId'), details.run_id],
  ].map(([label, value]) => {
    const values = Array.isArray(value)
      ? value.map((entry) => String(entry || '').trim()).filter(Boolean)
      : (String(value || '').trim() ? [String(value).trim()] : []);
    return values.length ? [label, values] : null;
  }).filter(Boolean);
  const appliedTimestamp = appliedAt
    ? `<div class="migration-registry-id">${escHtml(settingsT('health.appliedAt'))}: ${escHtml(_formatHealthTimestamp(appliedAt) || appliedAt)}</div>`
    : (status === 'applied' ? `<div class="migration-registry-id">${escHtml(settingsT('health.appliedAtUnknown'))}</div>` : '');
  return `
    <div class="migration-registry-item ${escHtml(status)}">
      <div class="migration-registry-head">
        <strong>${escHtml(title)}</strong>
        <span>${escHtml(statusLabel)}${plannedSuffix}</span>
      </div>
      ${id ? `<div class="migration-registry-id">${escHtml(id)}</div>` : ''}
      ${reason ? `<div>${escHtml(reason)}</div>` : ''}
      ${planText ? `<div class="migration-registry-plan">${escHtml(planText)}</div>` : ''}
      ${candidates.length ? `<div class="migration-registry-id">Deprecated: ${candidates.map((row) => escHtml(String(row?.key || ''))).filter(Boolean).join(', ')}</div>` : ''}
      ${updatedKeys.length ? `<div class="migration-registry-id">${escHtml(settingsT('health.updatedKeys'))}: ${updatedKeys.map((value) => escHtml(value)).join(', ')}</div>` : ''}
      ${missingKeys.length ? `<div class="migration-registry-id">${escHtml(settingsT('health.missingKeys'))}: ${missingKeys.map((value) => escHtml(value)).join(', ')}</div>` : ''}
      ${unknownKeys.length ? `<div class="migration-registry-id">${escHtml(settingsT('health.unknownKeys'))}: ${unknownKeys.map((value) => escHtml(value)).join(', ')}</div>` : ''}
      ${canonicalChanged ? `<div class="migration-registry-id">${escHtml(settingsT('health.canonicalContentChanged'))}</div>` : ''}
      ${failedPhase ? `<div class="migration-registry-id">${escHtml(settingsT('health.failedPhase'))}: ${escHtml(failedPhase)}</div>` : ''}
      ${failureReason ? `<div class="migration-registry-id">${escHtml(settingsT('health.failureReason'))}: ${escHtml(failureReason)}</div>` : ''}
      ${rollbackStatus ? `<div class="migration-registry-id">${escHtml(settingsT('health.rollbackStatus'))}: ${escHtml(settingsT(`health.rollback_${rollbackStatus}`))}</div>` : ''}
      ${appliedTimestamp}
      ${lastCheckedAt ? `<div class="migration-registry-id">${escHtml(settingsT('health.lastCheckedAt'))}: ${escHtml(_formatHealthTimestamp(lastCheckedAt) || lastCheckedAt)}</div>` : ''}
      ${introducedIn ? `<div class="migration-registry-id">${escHtml(settingsT('health.introducedIn'))}: ${escHtml(introducedIn)}</div>` : ''}
      ${auditRows.length ? `
        <details class="migration-registry-audit">
          <summary>${escHtml(settingsT('health.auditDetails'))}</summary>
          <dl>
            ${auditRows.map(([label, values]) => `
              <dt>${escHtml(label)}</dt>
              <dd>${values.map((value) => escHtml(value)).join('<br>')}</dd>
            `).join('')}
          </dl>
        </details>
      ` : ''}
    </div>
  `;
}

function _renderMigrationRegistryGroups(items) {
  const groups = [
    ['setup', settingsT('health.initialSetup')],
    ['config', settingsT('health.configuration')],
    ['migration', settingsT('health.executedMigrations')],
    ['planned_migration', settingsT('health.plannedMigrations')],
  ];
  return groups.map(([category, title]) => {
    const rows = items.filter((item) => String(item?.category || 'setup') === category);
    if (!rows.length) return '';
    return `
      <div class="migration-registry-group">
        <div class="migration-registry-group-title">${escHtml(title)}</div>
        ${rows.map(_renderMigrationRegistryItem).join('')}
      </div>
    `;
  }).join('');
}

function _localizeMigrationAction(value) {
  const raw = String(value || '').trim();
  const moved = raw.match(/^(\d+) (?:Elemente verschoben|items moved)$/);
  const moveErrors = raw.match(/^(\d+) (?:Verschiebe-Fehler|move errors)$/);
  const migrationApplied = raw.match(/^(.+) applied$/);
  const updatedKeys = raw.match(/^Updated keys: (.+)$/);
  if (moved) return settingsT('health.itemsMoved', { count: moved[1] });
  if (moveErrors) return settingsT('health.moveErrors', { count: moveErrors[1] });
  if (migrationApplied) return settingsT('health.migrationApplied', { id: migrationApplied[1] });
  if (updatedKeys) return settingsT('health.updatedKeysSummary', { keys: updatedKeys[1] });
  const known = {
    'Storage-Pfade aktualisiert': 'storagePathsUpdated',
    'Storage paths updated': 'storagePathsUpdated',
    'Profileinstellungen angepasst': 'profileSettingsUpdated',
    'Profile settings updated': 'profileSettingsUpdated',
    'backup.conf korrigiert': 'configCorrected',
    'backup.conf corrected': 'configCorrected',
    'Job-Layout geprüft': 'jobLayoutChecked',
    'Job layout checked': 'jobLayoutChecked',
  };
  return known[raw] ? settingsT(`health.${known[raw]}`) : raw;
}

function _localizeMigrationReason(code, fallback, status) {
  const keys = {
    none: 'reasonNone',
    storage_paths_changed: 'reasonStorageChanged',
    no_changes: 'reasonNoChanges',
    restore_history_migrated: 'reasonRestoreHistoryMigrated',
    startup_migrations_applied: 'reasonStartupMigrationsApplied',
    error: 'reasonFailed',
  };
  if (keys[code]) return settingsT(`health.${keys[code]}`);
  return fallback || settingsT(status === 'success' ? 'health.reasonSuccess' : 'health.reasonFailed');
}

function _buildMigrationSummary(data) {
  const summary = data?.migration_summary && typeof data.migration_summary === 'object' ? data.migration_summary : null;
  if (summary) {
    const legacyState = String(summary.state || '').trim();
    const status = String(summary.status || '').trim() || (['Fehlgeschlagen', 'Failed'].includes(legacyState) ? 'failed' : 'success');
    const reasonCode = String(summary.reason_code || '').trim();
    const errors = Array.isArray(summary.errors)
      ? summary.errors.map((v) => _localizeMigrationAction(v)).filter(Boolean).join(' · ')
      : String(summary.errors || '').trim();
    const actions = Array.isArray(summary.actions)
      ? summary.actions.map((v) => _localizeMigrationAction(v)).filter(Boolean)
      : [];
    return {
      status,
      state: status === 'failed' ? settingsT('health.stateFailed') : (status === 'none' ? settingsT('health.stateNone') : settingsT('health.stateSuccess')),
      lastRun: _formatHealthTimestamp(summary.last_run) || '—',
      lastEffectiveRun: String(summary.last_effective_run || '').trim(),
      reason: _localizeMigrationReason(reasonCode, String(summary.reason || '').trim(), status),
      errors,
      actions,
      techMsg: String(summary.technical_message || '').trim(),
    };
  }
  const lastEvent = data?.migration_log?.last_event && typeof data.migration_log.last_event === 'object'
    ? data.migration_log.last_event
    : (data?.last_migration || {});
  const tsRaw = String(lastEvent?.timestamp || '').trim();
  if (!tsRaw) {
    return {
      status: 'none',
      state: settingsT('health.stateNone'),
      lastRun: '—',
      lastEffectiveRun: '',
      reason: settingsT('health.reasonNone'),
      errors: '',
      actions: [],
      techMsg: '',
    };
  }
  const lastRun = _formatHealthTimestamp(tsRaw);

  const ok = !!lastEvent?.success;
  const reasonText = String(lastEvent?.reason_text || '').trim();
  const reasonCode = String(lastEvent?.reason_code || '').trim();
  const msg = String(lastEvent?.message || '').trim();
  const details = (lastEvent?.details && typeof lastEvent.details === 'object') ? lastEvent.details : {};
  const storage = (details?.storage_paths && typeof details.storage_paths === 'object') ? details.storage_paths : {};
  const actions = [];
  const moved = Number(storage?.moved || 0);
  const moveErrors = Number(storage?.move_errors || 0);
  if (moved > 0) actions.push(settingsT('health.itemsMoved', { count: moved }));
  if (storage?.changed === true) actions.push(settingsT('health.storagePathsUpdated'));
  if (storage?.settings_changed === true) actions.push(settingsT('health.profileSettingsUpdated'));
  if (storage?.forced_conf_write === true) actions.push(settingsT('health.configCorrected'));
  const restoreHistory = (details?.restore_history && typeof details.restore_history === 'object') ? details.restore_history : {};
  const restoreImported = Number(restoreHistory?.imported || 0);
  const restoreErrors = Number(restoreHistory?.errors || 0);
  if (restoreImported > 0) actions.push(settingsT('health.restoreHistoryImported', { count: restoreImported }));
  const jobs = (details?.jobs_layout && typeof details.jobs_layout === 'object') ? details.jobs_layout : {};
  if (String(jobs?.status || '').toLowerCase() === 'ok') actions.push(settingsT('health.jobLayoutChecked'));
  const errors = moveErrors > 0
    ? settingsT('health.moveErrors', { count: moveErrors })
    : (restoreErrors > 0 ? settingsT('health.restoreHistoryErrors', { count: restoreErrors }) : (!ok ? settingsT('health.migrationFailed') : ''));
  const status = ok ? 'success' : 'failed';
  const reason = _localizeMigrationReason(reasonCode, reasonText, status);
  return {
    status,
    state: ok ? settingsT('health.stateSuccess') : settingsT('health.stateFailed'),
    lastRun,
    lastEffectiveRun: String(data?.migration_log?.last_effective_event?.timestamp || '').trim(),
    reason,
    errors,
    actions,
    techMsg: msg,
  };
}

function renderSettingsGeneral(g) {
  const hint = !((g.GLOBAL_DATA_DIR || '').trim())
    ? `<div class="status-message warning" style="grid-column:1/-1">
         ${settingsT('general.dataDirWarning')}
       </div>`
    : '';
  return settingsCard(settingsT('general.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    `<div class="settings-body two-col">
      ${hint}
      ${fmono('GLOBAL_DATA_DIR', settingsT('general.dataDir'), g.GLOBAL_DATA_DIR, g.GLOBAL_DATA_DIR_SUGGESTION || '/mnt/user/borg-backup-ui')}
      ${fmonoRO(settingsT('general.derived', { name: 'GLOBAL_LOG_DIR' }), g.GLOBAL_LOG_DIR || '')}
      ${fmonoRO(settingsT('general.derived', { name: 'STATUS_DIR' }), g.STATUS_DIR || '')}
      ${fmonoRO(settingsT('general.derived', { name: 'RESTORE_TEST_STATUS_DIR' }), g.RESTORE_TEST_STATUS_DIR || '')}
      <div class="form-group">
        <label class="form-label">${settingsT('general.theme')}</label>
        <select class="form-select" id="ui-theme-select">
          <option value="dark">${settingsT('general.themeDark')}</option>
          <option value="light">${settingsT('general.themeLight')}</option>
          <option value="system">${settingsT('general.themeSystem')}</option>
        </select>
      </div>
      ${fnum('GLOBAL_LOG_RETENTION_DAYS', settingsT('general.logRetention'), g.GLOBAL_LOG_RETENTION_DAYS)}
      ${fmono('GLOBAL_BORG_CACHE_BASE', settingsT('general.borgCache'), g.GLOBAL_BORG_CACHE_BASE)}
      ${fnum('GLOBAL_BORG_CHECK_INTERVAL_DAYS', settingsT('general.checkInterval'), g.GLOBAL_BORG_CHECK_INTERVAL_DAYS)}
      <label class="form-checkbox-row" style="grid-column:1/-1">
        <input type="checkbox" data-key="ABORT_ON_PARITY_CHECK"
          ${g.ABORT_ON_PARITY_CHECK === 'true' ? 'checked' : ''}
          onchange="markSettingsDirty()">
        ${settingsT('general.abortParity')}
      </label>
    </div>`);
}

function homepageWidgetYaml(token) {
  const endpoint = `${window.location.origin}/api/widget/summary`;
  return `- Borg Backup UI:\n    href: ${window.location.origin}/\n    widget:\n      type: customapi\n      url: ${endpoint}\n      refreshInterval: 60000\n      headers:\n        X-Borg-Widget-Token: "${token}"\n      mappings:\n        - field: status.label\n          label: Status\n        - field: display.backups\n          label: Backups\n        - field: display.restore_tests\n          label: Restore tests\n        - field: display.active\n          label: Active`;
}

function renderSettingsHomepageWidget(widget) {
  const configured = !!widget?.configured;
  const token = String(settingsState.homepageWidgetToken || '');
  const yaml = token ? homepageWidgetYaml(token) : '';
  const statusClass = configured ? 'success' : 'warning';
  const statusText = settingsT(configured ? 'homepageWidget.configured' : 'homepageWidget.notConfigured');
  return settingsCard(settingsT('homepageWidget.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h3v3H7zM14 9h3M14 13h3M7 16h10"/></svg>`,
    `<div class="settings-body">
      <p style="margin:0 0 12px">${settingsT('homepageWidget.description')}</p>
      <div class="status-message ${statusClass}" style="margin-bottom:12px">${statusText}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" type="button" data-settings-action="homepage-widget-rotate">${settingsT(configured ? 'homepageWidget.rotate' : 'homepageWidget.create')}</button>
        ${configured ? `<button class="btn btn-secondary btn-sm" type="button" data-settings-action="homepage-widget-revoke">${settingsT('homepageWidget.revoke')}</button>` : ''}
      </div>
      ${token ? `<div class="form-group" style="margin-top:16px">
        <label class="form-label">${settingsT('homepageWidget.token')}</label>
        <div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px">
          <input class="form-input mono" id="homepage-widget-token" value="${escAttr(token)}" readonly>
          <button class="btn btn-secondary btn-sm" type="button" data-settings-action="homepage-widget-copy-token">${settingsT('homepageWidget.copy')}</button>
        </div>
        <small>${settingsT('homepageWidget.tokenOnce')}</small>
      </div>
      <div class="form-group" style="margin-top:12px">
        <label class="form-label">${settingsT('homepageWidget.yaml')}</label>
        <textarea class="form-input mono" id="homepage-widget-yaml" rows="18" readonly>${escHtml(yaml)}</textarea>
        <button class="btn btn-secondary btn-sm" style="margin-top:8px" type="button" data-settings-action="homepage-widget-copy-yaml">${settingsT('homepageWidget.copyYaml')}</button>
      </div>` : ''}
      <div id="homepage-widget-message" class="status-message hidden" style="margin-top:12px"></div>
    </div>`);
}

async function rotateHomepageWidgetToken() {
  try {
    const res = await fetch('/api/settings/homepage-widget-token', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || !data?.token) throw new Error(data?.message || `HTTP ${res.status}`);
    settingsState.homepageWidgetToken = String(data.token);
    settingsState.data.homepage_widget = { configured: true };
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    showMsg('homepage-widget-message', 'success', settingsT('homepageWidget.rotatedSuccess'));
  } catch (err) {
    showMsg('homepage-widget-message', 'error', settingsT('homepageWidget.actionFailed', { message: err.message }));
  }
}

async function revokeHomepageWidgetToken() {
  const confirmed = await _openSettingsDialog({
    title: settingsT('homepageWidget.revokeTitle'),
    message: settingsT('homepageWidget.revokeMessage'),
    confirmText: settingsT('homepageWidget.revoke'),
    confirmClass: 'btn-danger',
  });
  if (!confirmed) return;
  try {
    const res = await fetch('/api/settings/homepage-widget-token', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.message || `HTTP ${res.status}`);
    settingsState.homepageWidgetToken = '';
    settingsState.data.homepage_widget = { configured: false };
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    showMsg('homepage-widget-message', 'success', settingsT('homepageWidget.revokedSuccess'));
  } catch (err) {
    showMsg('homepage-widget-message', 'error', settingsT('homepageWidget.actionFailed', { message: err.message }));
  }
}

function copyHomepageWidgetFieldFallback(field, value) {
  const previousFocus = document.activeElement;
  const previousStart = typeof field.selectionStart === 'number' ? field.selectionStart : null;
  const previousEnd = typeof field.selectionEnd === 'number' ? field.selectionEnd : null;
  try {
    field.focus();
    field.select();
    if (typeof field.setSelectionRange === 'function') field.setSelectionRange(0, value.length);
    return document.execCommand('copy');
  } catch (_) {
    return false;
  } finally {
    if (previousStart !== null && previousEnd !== null && typeof field.setSelectionRange === 'function') {
      field.setSelectionRange(previousStart, previousEnd);
    }
    if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
  }
}

async function copyHomepageWidgetField(id) {
  const field = document.getElementById(id);
  const value = String(field?.value || '');
  if (!value) return;
  let copied = false;
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      copied = true;
    }
  } catch (_) {
    copied = false;
  }
  if (!copied) copied = copyHomepageWidgetFieldFallback(field, value);
  if (copied) {
    showMsg('homepage-widget-message', 'success', settingsT('homepageWidget.copied'));
  } else {
    showMsg('homepage-widget-message', 'error', settingsT('homepageWidget.copyFailed'));
  }
}

function renderSettingsUsers() {
  const rows = Array.isArray(settingsState.authUsers) ? settingsState.authUsers : [];
  const timeout = String(settingsState.authStatus?.session_timeout_minutes || '30');
  const currentUser = String(settingsState.authStatus?.current_user || '').trim();
  const currentRole = String(settingsState.authStatus?.current_role || '').trim().toLowerCase();
  const ownSessions = Number(settingsState.authStatus?.active_sessions_own || 0);
  const totalSessionsRaw = settingsState.authStatus?.active_sessions_total;
  const totalSessions = totalSessionsRaw === null || totalSessionsRaw === undefined ? null : Number(totalSessionsRaw || 0);
  return settingsCard(settingsT('users.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6"/><path d="M23 11h-6"/></svg>`,
    `<div class="settings-body">
      <div style="display:grid;grid-template-columns:1fr;gap:8px;align-items:end;margin-bottom:10px">
        <div class="form-group">
          <label class="form-label">${settingsT('users.sessionTimeout')}</label>
          <input class="form-input" type="number" min="5" data-key="UI_SESSION_TIMEOUT_MINUTES" value="${escHtml(timeout)}" onchange="markSettingsDirty()" oninput="markSettingsDirty()">
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <span class="text-muted" style="font-size:12px">
            ${settingsT('users.signedIn')} <strong>${escHtml(currentUser || '—')}</strong>${currentRole ? ` (${escHtml(currentRole)})` : ''}
            · ${settingsT('users.activeSessions')} <strong>${ownSessions}</strong>${totalSessions !== null ? ` · ${settingsT('users.total')} <strong>${totalSessions}</strong>` : ''}
          </span>
          <button class="btn btn-secondary btn-sm" data-settings-action="user-change-own-password">${settingsT('users.changeOwnPassword')}</button>
          <button class="btn btn-secondary btn-sm" data-settings-action="user-logout-own-sessions">${settingsT('users.logoutOwn')}</button>
          ${currentRole === 'admin' ? `<button class="btn btn-secondary btn-sm" data-settings-action="user-logout-all-sessions">${settingsT('users.logoutAll')}</button>` : ''}
        </div>
      </div>
      <div style="display:grid;grid-template-columns:2fr 1.2fr 1fr auto;gap:8px;align-items:end">
        <div class="form-group"><label class="form-label">${settingsT('users.username')}</label><input id="user-new-name" class="form-input" type="text" placeholder="newuser"></div>
        <div class="form-group"><label class="form-label">${settingsT('users.role')}</label><select id="user-new-role" class="form-select"><option value="viewer">viewer</option><option value="operator">operator</option><option value="admin">admin</option></select></div>
        <div class="form-group"><label class="form-label">${settingsT('users.password')}</label><input id="user-new-password" class="form-input" type="password" placeholder="${settingsT('users.passwordMin')}"></div>
        <button class="btn btn-secondary btn-sm" data-settings-action="user-create">${settingsT('users.create')}</button>
      </div>
      <div id="users-msg" class="status-message hidden" style="margin-top:8px"></div>
      <table class="settings-table" style="margin-top:10px">
        <thead><tr><th>${settingsT('users.user')}</th><th>${settingsT('users.role')}</th><th>${settingsT('users.active')}</th><th>${settingsT('users.lastLogin')}</th><th>${settingsT('users.actions')}</th></tr></thead>
        <tbody>
          ${rows.map((u) => `<tr data-user-name="${escHtml(u.username)}">
            <td>${escHtml(u.username)}</td>
            <td><select class="form-select" data-user-role style="width:130px">
              ${['viewer','operator','admin'].map((r) => `<option value="${r}" ${String(u.role||'')===r?'selected':''}>${r}</option>`).join('')}
            </select></td>
            <td><input type="checkbox" data-user-enabled ${u.enabled ? 'checked' : ''}></td>
            <td>${escHtml(u.last_login_at || '—')}</td>
            <td style="display:flex;gap:6px">
              <button class="btn btn-secondary btn-sm" data-settings-action="user-save">${settingsT('users.save')}</button>
              <button class="btn btn-secondary btn-sm" data-settings-action="user-reset-password">${settingsT('users.password')}</button>
              <button class="btn btn-secondary btn-sm" data-settings-action="user-deactivate">${settingsT('users.deactivate')}</button>
              <button class="btn btn-danger btn-sm" data-settings-action="user-delete">${settingsT('users.delete')}</button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>`);
}

function renderSettingsConfigBackups() {
  return settingsCard(settingsT('backups.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l3 3"/></svg>`,
    `<div class="settings-body">
      <div class="text-muted" style="font-size:12px;margin-bottom:10px">
        ${settingsT('backups.description')}
      </div>
      <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
        <button class="btn btn-secondary btn-sm" data-settings-action="delete-backups-keep-latest">${settingsT('backups.deleteExceptLatest')}</button>
      </div>
      <div id="settings-config-backups-msg" class="status-message hidden"></div>
      <div id="settings-config-backups-list">
        <div class="loading-spinner"><div class="spinner"></div><span>${settingsT('backups.loading')}</span></div>
      </div>
      <div id="settings-config-backups-diff" class="hidden" style="margin-top:10px"></div>
    </div>`);
}

function renderSettingsTransferTools() {
  const jobsPreview = settingsState.transferJobsPreview;
  const profileSecretsPreview = settingsState.transferProfileSecretsPreview;
  return settingsCard(settingsT('transfer.title'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
    `<div class="settings-body">
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px">
        ${settingsT('transfer.description')}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-bottom:8px">
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="export-support-bundle">${settingsT('transfer.supportBundle')}</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-bottom:8px">
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="export-jobs-secure">${settingsT('transfer.jobsExport')}</button>
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="import-jobs-secure-select-file">${settingsT('transfer.jobsPreview')}</button>
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="import-jobs-apply" ${jobsPreview ? '' : 'disabled'}>${settingsT('transfer.jobsImport')}</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-bottom:8px">
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="export-profile-secrets">${settingsT('transfer.profilesExport')}</button>
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="import-profile-secrets-select-file">${settingsT('transfer.profilesPreview')}</button>
        <button class="btn btn-secondary btn-sm" style="width:100%;justify-content:center" data-settings-action="import-profile-secrets-apply" ${profileSecretsPreview ? '' : 'disabled'}>${settingsT('transfer.profilesImport')}</button>
      </div>
      <div id="settings-transfer-msg" class="status-message hidden"></div>
      <div id="settings-transfer-preview-jobs" style="margin-top:10px">
        ${jobsPreview ? renderJobsImportPreview(jobsPreview) : ''}
      </div>
      <div id="settings-transfer-preview-profile-secrets" style="margin-top:10px">
        ${profileSecretsPreview ? renderProfileSecretsImportPreview(profileSecretsPreview) : ''}
      </div>
    </div>`);
}

function renderSettingsFactoryReset() {
  return settingsCard(settingsT('transfer.factoryResetTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>`,
    `<div class="settings-body">
      <div class="status-message error" style="margin:0 0 12px 0">
        <strong>${settingsT('transfer.factoryResetWarningTitle')}</strong><br>
        ${settingsT('transfer.factoryResetWarning')}
      </div>
      <p class="text-muted" style="font-size:12px;margin:0 0 12px 0">${settingsT('transfer.factoryResetRepositories')}</p>
      <button class="btn btn-danger" data-settings-action="factory-reset-start">${settingsT('transfer.factoryResetButton')}</button>
      <div id="settings-factory-reset-msg" class="status-message hidden" style="margin-top:10px"></div>
    </div>`);
}

function renderLegacyEncryptionWarning(data) {
  if (!data?.legacy_encryption) return '';
  return `<div class="status-message warning" style="margin:0 0 8px 0">${settingsT('transfer.legacyEncryptionWarning')}</div>`;
}

function clearJobsImportPreview() {
  settingsState.transferJobsPreview = null;
  settingsState.transferJobsBundleText = '';
  settingsState.transferJobsSecurePayloadB64 = '';
  settingsState.transferJobsSecurePassword = '';
  settingsState.transferJobsSecureMode = false;
  const previewEl = document.getElementById('settings-transfer-preview-jobs');
  if (previewEl) previewEl.replaceChildren();
  document.querySelector('[data-settings-action="import-jobs-apply"]')?.setAttribute('disabled', 'disabled');
}

function clearSecretsImportPreview() {
  settingsState.transferSecretsPreview = null;
  settingsState.transferSecretsPayloadB64 = '';
  settingsState.transferSecretsPassword = '';
}

function clearProfileSecretsImportPreview() {
  settingsState.transferProfileSecretsPreview = null;
  settingsState.transferProfileSecretsPayloadB64 = '';
  settingsState.transferProfileSecretsPassword = '';
  const previewEl = document.getElementById('settings-transfer-preview-profile-secrets');
  if (previewEl) previewEl.replaceChildren();
  document.querySelector('[data-settings-action="import-profile-secrets-apply"]')?.setAttribute('disabled', 'disabled');
}

function renderJobsImportPreview(d) {
  const rows = Array.isArray(d?.jobs) ? d.jobs : [];
  const sp = d?.settings_preview || null;
  if (!rows.length && !(sp && sp.present)) return '';
  const stats = rows.reduce((acc, r) => {
    const c = String(r?.conflict || 'new');
    acc.total += 1;
    if (c === 'new') acc.new += 1;
    else if (c === 'exists') acc.exists += 1;
    else if (c === 'invalid') acc.invalid += 1;
    else acc.other += 1;
    return acc;
  }, { total: 0, new: 0, exists: 0, invalid: 0, other: 0 });
  const settingsBlock = sp && sp.present ? `
    <div class="text-muted" style="font-size:12px;margin:10px 0 6px 0">${settingsT('transfer.settingsImport')}</div>
    <div class="status-message info" style="margin:0 0 8px 0">
      ${settingsT('transfer.profilesInBundle', { count: Number(sp.profiles_total || 0) })}
      <select class="form-select" id="settings-import-mode" style="width:220px;display:inline-block;margin-left:6px">
        <option value="merge" ${settingsState.transferSettingsMode === 'merge' ? 'selected' : ''}>${settingsT('transfer.mergeMode')}</option>
        <option value="replace" ${settingsState.transferSettingsMode === 'replace' ? 'selected' : ''}>${settingsT('transfer.replaceMode')}</option>
        <option value="ignore" ${settingsState.transferSettingsMode === 'ignore' ? 'selected' : ''}>${settingsT('transfer.ignoreMode')}</option>
      </select>
    </div>
    <table class="settings-table" style="margin-bottom:8px">
      <thead><tr><th>${settingsT('transfer.scope')}</th><th>${settingsT('transfer.profile')}</th><th>${settingsT('transfer.status')}</th><th>${settingsT('transfer.jobs')}</th><th>${settingsT('transfer.conflictMode')}</th></tr></thead>
      <tbody>
        ${[...(sp.usb || []).map(r => ({...r, scope:'usb'})), ...(sp.smb || []).map(r => ({...r, scope:'smb'}))].map((r) => {
          const modeKey = `${r.scope}:${r.key}`;
          const jobs = r.scope === 'smb' ? Number(r.jobs_count || 0) : 0;
          const refs = r.scope === 'smb' && Array.isArray(r.job_refs) && r.job_refs.length ? ` title="${escHtml(r.job_refs.join('\n'))}"` : '';
          return `<tr>
            <td>${r.scope.toUpperCase()}</td>
            <td>${escHtml(r.name || r.key)}</td>
            <td>${escHtml(r.status || 'new')}</td>
            <td${refs}>${jobs || '—'}</td>
            <td>${r.status === 'conflict' ? `<select class="form-select" data-settings-profile-mode="${escHtml(modeKey)}" style="width:140px"><option value="skip" selected>skip</option><option value="overwrite">overwrite</option><option value="rename">rename</option></select>` : '—'}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  ` : '';
  return `
    ${renderLegacyEncryptionWarning(d)}
    ${settingsBlock}
    <div class="text-muted" style="font-size:12px;margin-bottom:8px">${settingsT('transfer.jobsPreviewTitle', { count: rows.length })}${Number(d?.passphrase_count || 0) ? ` · ${settingsT('transfer.passphrasesInPackage', { count: Number(d.passphrase_count) })}` : ''}${Number(d?.keyfile_count || 0) ? ` · ${settingsT('transfer.keyfilesInPackage', { count: Number(d.keyfile_count) })}` : ''}</div>
    <div class="status-message info" style="margin:0 0 8px 0">
      ${settingsT('transfer.total', { count: stats.total })} · ${settingsT('transfer.new', { count: stats.new })} · ${settingsT('transfer.existing', { count: stats.exists })} · ${settingsT('transfer.invalid', { count: stats.invalid })}${stats.other ? ` · ${settingsT('transfer.other', { count: stats.other })}` : ''}
    </div>
    <table class="settings-table">
      <thead><tr><th>${settingsT('transfer.import')}</th><th>${settingsT('transfer.name')}</th><th>${settingsT('transfer.type')}</th><th>${settingsT('transfer.location')}</th><th>${settingsT('transfer.schedule')}</th><th>${settingsT('transfer.features')}</th><th>${settingsT('transfer.job')}</th><th>${settingsT('transfer.passphrase')}</th><th>${settingsT('transfer.mode')}</th></tr></thead>
      <tbody>
      ${rows.map((r, idx) => {
        const feats = `${r?.features?.docker ? 'docker ' : ''}${r?.features?.vm ? 'vm' : ''}`.trim() || '—';
        const sch = r?.schedule?.cron ? `${r.schedule.cron}${r?.schedule?.enabled ? '' : ' (off)'}` : '—';
        const pp = ({
          present_match: settingsT('transfer.present'),
          present_mismatch: settingsT('transfer.different'),
          present: settingsT('transfer.present'),
          missing: settingsT('transfer.missing'),
          unknown: settingsT('transfer.unknown'),
        })[r?.passphrase?.status || 'unknown'] || settingsT('transfer.unknown');
        return `<tr>
          <td><input type="checkbox" data-job-preview-select="${idx}" ${r.conflict === 'invalid' ? 'disabled' : 'checked'}></td>
          <td>${escHtml(r.name || r.job_key || '')}</td>
          <td>${escHtml(r.backup_type || '—')}</td>
          <td>${escHtml(r.location || '—')}</td>
          <td>${escHtml(sch)}</td>
          <td>${escHtml(feats)}</td>
          <td>${escHtml(r.conflict || 'new')}</td>
          <td>${escHtml(pp)}</td>
          <td>
            <select class="form-select" data-job-preview-mode="${idx}" style="width:140px">
              ${['skip','overwrite','rename'].map(m => `<option value="${m}" ${(r.suggested_mode || 'skip') === m ? 'selected' : ''}>${m}</option>`).join('')}
            </select>
          </td>
        </tr>`;
      }).join('')}
      </tbody>
    </table>`;
}

function renderSecretsImportPreview(d) {
  const rows = Array.isArray(d?.files) ? d.files : [];
  if (!rows.length) return '';
  const stats = rows.reduce((acc, r) => {
    const s = String(r?.status || 'unknown');
    acc.total += 1;
    if (s === 'present_mismatch') acc.mismatch += 1;
    else if (s === 'present_match' || s === 'present') acc.present += 1;
    else if (s === 'missing') acc.missing += 1;
    else acc.unknown += 1;
    return acc;
  }, { total: 0, present: 0, mismatch: 0, missing: 0, unknown: 0 });
  return `
    ${renderLegacyEncryptionWarning(d)}
    <div class="text-muted" style="font-size:12px;margin:12px 0 8px 0">${settingsT('transfer.passphrasePreview', { count: rows.length })}</div>
    <div class="status-message info" style="margin:0 0 8px 0">
      ${settingsT('transfer.total', { count: stats.total })} · ${settingsT('transfer.presentCount', { count: stats.present })} · ${settingsT('transfer.differentCount', { count: stats.mismatch })} · ${settingsT('transfer.missingCount', { count: stats.missing })}${stats.unknown ? ` · ${settingsT('transfer.unknownCount', { count: stats.unknown })}` : ''}
    </div>
    <table class="settings-table">
      <thead><tr><th>${settingsT('transfer.import')}</th><th>${settingsT('transfer.file')}</th><th>${settingsT('transfer.status')}</th></tr></thead>
      <tbody>
      ${rows.map((r, idx) => `<tr>
        <td><input type="checkbox" data-secret-preview-select="${idx}" checked></td>
        <td><code style="font-size:12px">${escHtml(r.name || '')}</code></td>
        <td>${escHtml(({
          present_match: settingsT('transfer.present'),
          present_mismatch: settingsT('transfer.different'),
          present: settingsT('transfer.present'),
          missing: settingsT('transfer.missing'),
          unknown: settingsT('transfer.unknown'),
        })[r.status || 'unknown'] || settingsT('transfer.unknown'))}</td>
      </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderProfileSecretsImportPreview(d) {
  const rows = Array.isArray(d?.entries) ? d.entries : [];
  const options = d?.profile_options || {};
  const sp = d?.settings_preview || null;
  if (!rows.length) return '';
  const stats = rows.reduce((acc, r) => {
    const s = String(r?.status || 'unknown');
    acc.total += 1;
    if (s === 'present_match') acc.match += 1;
    else if (s === 'present_mismatch') acc.mismatch += 1;
    else if (s === 'profile_missing') acc.profile_missing += 1;
    else if (s === 'missing') acc.missing += 1;
    else acc.other += 1;
    return acc;
  }, { total: 0, match: 0, mismatch: 0, profile_missing: 0, missing: 0, other: 0 });
  const label = (s) => ({
    present_match: settingsT('transfer.present'),
    present_mismatch: settingsT('transfer.different'),
    profile_missing: settingsT('transfer.profileMissing'),
    missing: settingsT('transfer.missing'),
    unknown: settingsT('transfer.unknown'),
  }[s] || settingsT('transfer.unknown'));
  const settingsRows = sp ? [
    ...((sp.smb || []).map((r) => ({ scope: 'smb', ...r }))),
    ...((sp.storage || []).map((r) => ({ scope: 'storage', ...r }))),
  ] : [];
  const settingsBlock = sp && sp.present ? `
    <div class="text-muted" style="font-size:12px;margin:10px 0 6px 0">${settingsT('transfer.profilesInPackage', { count: Number(sp.profiles_total || 0) })}</div>
    <div class="status-message info" style="margin:0 0 8px 0">
      ${settingsT('transfer.profileMode')}
      <select class="form-select" id="profile-secrets-settings-mode" style="width:220px;display:inline-block;margin-left:6px">
        <option value="merge" selected>${settingsT('transfer.mergeMode')}</option>
        <option value="replace">${settingsT('transfer.replaceMode')}</option>
        <option value="ignore">${settingsT('transfer.ignoreMode')}</option>
      </select>
    </div>
    <table class="settings-table" style="margin-bottom:8px">
      <thead><tr><th>${settingsT('transfer.scope')}</th><th>${settingsT('transfer.profile')}</th><th>${settingsT('transfer.status')}</th></tr></thead>
      <tbody>
        ${settingsRows.map((r) => `<tr>
          <td>${escHtml(String(r.scope || '').toUpperCase())}</td>
          <td>${escHtml(r.name || r.key || '')}</td>
          <td>${escHtml(r.status || 'new')}</td>
        </tr>`).join('')}
      </tbody>
    </table>
  ` : '';
  return `
    ${renderLegacyEncryptionWarning(d)}
    ${settingsBlock}
    <div class="text-muted" style="font-size:12px;margin:12px 0 8px 0">${settingsT('transfer.profilesSecretsPreview', { count: rows.length })}</div>
    <div class="status-message info" style="margin:0 0 8px 0">
      ${settingsT('transfer.total', { count: stats.total })} · ${settingsT('transfer.presentCount', { count: stats.match })} · ${settingsT('transfer.differentCount', { count: stats.mismatch })} · ${settingsT('transfer.missingCount', { count: stats.missing })} · ${settingsT('transfer.profileMissingCount', { count: stats.profile_missing })}${stats.other ? ` · ${settingsT('transfer.other', { count: stats.other })}` : ''}
    </div>
    <table class="settings-table">
      <thead><tr><th>${settingsT('transfer.import')}</th><th>${settingsT('transfer.type')}</th><th>${settingsT('transfer.profile')}</th><th>${settingsT('transfer.targetProfile')}</th><th>${settingsT('transfer.secret')}</th><th>${settingsT('transfer.status')}</th><th>${settingsT('transfer.targetPath')}</th></tr></thead>
      <tbody>
      ${rows.map((r, idx) => {
        const pType = String(r.profile_type || '').toLowerCase();
        const candidates = Array.isArray(options[pType]) ? options[pType] : [];
        const selectedTarget = candidates.includes(r.profile_key) ? r.profile_key : (candidates[0] || '');
        const selectHtml = `<select class="form-select" data-profile-secret-target="${idx}" style="width:150px">${candidates.map((k) => `<option value="${escHtml(k)}" ${k === selectedTarget ? 'selected' : ''}>${escHtml(k)}</option>`).join('')}</select>`;
        const canImportMissingProfile = String(r.status) !== 'profile_missing' || !!(sp && sp.present);
        return `<tr>
        <td><input type="checkbox" data-profile-secret-preview-select="${idx}" ${canImportMissingProfile ? 'checked' : 'disabled'}></td>
        <td>${escHtml(String(r.profile_type || '').toUpperCase())}</td>
        <td><code style="font-size:12px">${escHtml(r.profile_key || '')}</code></td>
        <td>${candidates.length ? selectHtml : '—'}</td>
        <td>${escHtml(r.secret_type || '')}</td>
        <td>${escHtml(label(String(r.status || 'unknown')))}</td>
        <td><code style="font-size:12px">${escHtml(r.target_path || '')}</code></td>
      </tr>`;
      }).join('')}
      </tbody>
    </table>`;
}

function _downloadTextFile(filename, content, mime = 'application/json;charset=utf-8') {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'download.txt';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function _pickFileText(accept = '') {
  return new Promise((resolve, reject) => {
    const inp = document.createElement('input');
    inp.type = 'file';
    if (accept) inp.accept = accept;
    inp.onchange = () => {
      const f = inp.files && inp.files[0];
      if (!f) return reject(new Error(settingsT('transfer.noFileSelected')));
      const r = new FileReader();
      r.onerror = () => reject(new Error(settingsT('transfer.fileReadError')));
      r.onload = () => resolve({ name: f.name || '', content: String(r.result || '') });
      r.readAsText(f);
    };
    inp.click();
  });
}

function _pickFileBufferAsBase64(accept = '') {
  return new Promise((resolve, reject) => {
    const inp = document.createElement('input');
    inp.type = 'file';
    if (accept) inp.accept = accept;
    inp.onchange = () => {
      const f = inp.files && inp.files[0];
      if (!f) return reject(new Error(settingsT('transfer.noFileSelected')));
      const r = new FileReader();
      r.onerror = () => reject(new Error(settingsT('transfer.fileReadError')));
      r.onload = () => {
        const buf = new Uint8Array(r.result);
        let s = '';
        for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
        resolve({ name: f.name || '', payload_b64: btoa(s) });
      };
      r.readAsArrayBuffer(f);
    };
    inp.click();
  });
}

async function _pickFileViaUiDialog(cfg) {
  const ok = await _openSettingsDialog({
    title: cfg?.title || settingsT('transfer.selectFile'),
    message: cfg?.message || settingsT('transfer.selectFileMessage'),
    confirmText: cfg?.confirmText || settingsT('transfer.chooseFile'),
  });
  if (!ok) return null;
  const picked = cfg?.binary ? await _pickFileBufferAsBase64(cfg?.accept || '') : await _pickFileText(cfg?.accept || '');
  const name = String(picked?.name || '');
  const prefix = String(cfg?.namePrefix || '').trim();
  if (prefix && !name.startsWith(prefix)) {
    throw new Error(settingsT('transfer.wrongFileType', { prefix }));
  }
  return picked;
}

function _openSettingsDialog(cfg) {
  return new Promise((resolve) => {
    const modal = document.getElementById('settings-dialog-modal');
    const title = document.getElementById('settings-dialog-title');
    const desc = document.getElementById('settings-dialog-description');
    const inputWrap = document.getElementById('settings-dialog-input-wrap');
    const inputLabel = document.getElementById('settings-dialog-input-label');
    const input = document.getElementById('settings-dialog-input');
    const okBtn = document.getElementById('settings-dialog-confirm-btn');
    const cancelBtn = document.getElementById('settings-dialog-cancel-btn');
    const closeBtn = document.getElementById('settings-dialog-close-btn');
    if (!modal || !title || !desc || !inputWrap || !inputLabel || !input || !okBtn || !cancelBtn || !closeBtn) return resolve(null);

    title.textContent = cfg?.title || settingsT('transfer.confirmation');
    if (cfg?.html) {
      desc.innerHTML = String(cfg.html);
    } else {
      desc.textContent = cfg?.message || '';
    }
    const needInput = !!cfg?.input;
    inputWrap.classList.toggle('hidden', !needInput);
    inputLabel.textContent = cfg?.input?.label || '';
    input.type = cfg?.input?.type || 'text';
    input.value = cfg?.input?.value || '';
    input.placeholder = cfg?.input?.placeholder || '';
    okBtn.textContent = cfg?.confirmText || settingsT('transfer.confirm');
    okBtn.className = `btn ${cfg?.confirmClass || 'btn-primary'}`;
    const validate = cfg?.input?.validate || (() => true);
    const update = () => { okBtn.disabled = needInput ? !validate(input.value) : false; };
    update();

    let done = false;
    const finish = (val) => {
      if (done) return;
      done = true;
      modal.classList.add('hidden');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      closeBtn.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      input.removeEventListener('input', update);
      input.removeEventListener('keydown', onEnter);
      resolve(val);
    };
    const resolveValue = typeof cfg?.resolveValue === 'function'
      ? cfg.resolveValue
      : (() => (needInput ? input.value : true));
    const onOk = () => finish(resolveValue({ modal, input }));
    const onCancel = () => finish(null);
    const onBackdrop = (e) => { if (e.target === modal) onCancel(); };
    const onEnter = (e) => {
      if (e.key === 'Enter' && !okBtn.disabled) {
        e.preventDefault();
        onOk();
      }
    };

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    closeBtn.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    input.addEventListener('input', update);
    input.addEventListener('keydown', onEnter);
    modal.classList.remove('hidden');
    if (needInput) setTimeout(() => input.focus(), 0);
  });
}

async function exportJobsBundle() {
  hideEl('settings-transfer-msg');
  try {
    const res = await fetch('/api/settings/jobs-export');
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    _downloadTextFile(data.filename || 'bbui-jobs-export.json', data.bundle_text || JSON.stringify(data.bundle || {}, null, 2));
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.exportCreated', { jobs: data.job_count || 0 }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.exportFailed', { message: err.message }));
  }
}

async function exportJobsBundleSecure() {
  hideEl('settings-transfer-msg');
  try {
    const password = await _openSettingsDialog({
      title: settingsT('transfer.exportJobsTitle'),
      message: settingsT('transfer.jobsPasswordPrompt'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 8 },
      confirmText: settingsT('transfer.startExport'),
    });
    if (!password) return;
    const res = await fetch('/api/settings/jobs-export-secure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const bytes = atob(data.payload_b64 || '');
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const blob = new Blob([arr], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || 'bbui-jobs-secure.jobs.enc';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.secureJobsCreated', { jobs: data.job_count || 0, passphrases: data.passphrase_count || 0, keyfiles: data.keyfile_count || 0 }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.secureJobsFailed', { message: err.message }));
  }
}

async function exportSupportBundle() {
  hideEl('settings-transfer-msg');
  try {
    const res = await fetch('/api/settings/support-bundle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const bytes = atob(data.payload_b64 || '');
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const blob = new Blob([arr], { type: 'application/zip' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || 'borg-backup-ui-support.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.supportCreated', { count: data.file_count || 0 }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.supportFailed', { message: err.message }));
  }
}

function factoryResetOperationBlockerMessage(row) {
  const name = String(row?.name || '').trim();
  const key = {
    backup: 'factoryResetBlockerBackup',
    job: 'factoryResetBlockerBackup',
    restore_test: 'factoryResetBlockerRestoreTest',
    repository_maintenance: 'factoryResetBlockerMaintenance',
    restore: 'factoryResetBlockerRestore',
  }[String(row?.type || '').trim()] || 'factoryResetBlockerOperation';
  return settingsT(`transfer.${key}`, { name });
}

async function startFactoryReset() {
  const messageId = 'settings-factory-reset-msg';
  hideEl(messageId);
  try {
    const statusRes = await fetch('/api/settings/factory-reset/status', { credentials: 'include' });
    const status = await statusRes.json();
    if (!statusRes.ok) throw new Error(apiErrorMessage(status, statusRes.status));
    const operationBlockers = Array.isArray(status.operation_blockers) ? status.operation_blockers : [];
    const repositoryBlockers = Array.isArray(status.repository_blockers) ? status.repository_blockers : [];
    if (!status.allowed) {
      const rows = [
        ...operationBlockers.map(factoryResetOperationBlockerMessage),
        ...repositoryBlockers.map((row) => settingsT('transfer.factoryResetBlockerRepository', {
          name: String(row?.display_name || '').trim(),
          path: String(row?.path || '').trim(),
        })),
      ];
      showMsg(messageId, 'error', `${settingsT('transfer.factoryResetBlocked')} ${rows.join(' ')}`.trim());
      return;
    }
    const server = String(status.server_name || '');
    const configRoot = String(status.configuration_root || '');
    const dataRoot = String(status.operational_data_root || '');
    const confirmation = await _openSettingsDialog({
      title: settingsT('transfer.factoryResetTitle'),
      html: `
        <div class="modal-info-item danger">${settingsT('transfer.factoryResetDialogWarning')}</div>
        <div class="modal-info-item" style="margin-top:8px"><strong>${settingsT('transfer.factoryResetDeletePaths')}</strong><br><code>${escHtml(configRoot)}</code>${dataRoot ? `<br><code>${escHtml(dataRoot)}</code>` : ''}</div>
        <label class="form-checkbox-row" style="margin-top:12px"><input type="checkbox" id="factory-reset-ack-configuration"> ${settingsT('transfer.factoryResetAckConfiguration')}</label>
        <label class="form-checkbox-row" style="margin-top:8px"><input type="checkbox" id="factory-reset-ack-data"> ${settingsT('transfer.factoryResetAckData')}</label>
        <label class="form-checkbox-row" style="margin-top:8px"><input type="checkbox" id="factory-reset-ack-secrets"> ${settingsT('transfer.factoryResetAckSecrets')}</label>
        <label class="form-checkbox-row" style="margin-top:8px"><input type="checkbox" id="factory-reset-ack-repositories"> ${settingsT('transfer.factoryResetAckRepositories')}</label>
        <div class="form-group" style="margin-top:12px"><label class="form-label">${settingsT('transfer.factoryResetServerName', { name: server })}</label><input class="form-input" id="factory-reset-server-name" autocomplete="off"></div>
        <div class="form-group"><label class="form-label">${settingsT('transfer.factoryResetPassword')}</label><input class="form-input" type="password" id="factory-reset-password" autocomplete="current-password"></div>`,
      input: {
        label: settingsT('transfer.factoryResetPhrase', { phrase: status.confirmation_phrase || 'FACTORY RESET' }),
        placeholder: status.confirmation_phrase || 'FACTORY RESET',
        validate: (value) => String(value || '').trim() === String(status.confirmation_phrase || 'FACTORY RESET'),
      },
      confirmText: settingsT('transfer.factoryResetConfirm'),
      confirmClass: 'btn-danger',
      resolveValue: ({ modal, input }) => ({
        confirmation_phrase: String(input.value || '').trim(),
        server_name: String(modal.querySelector('#factory-reset-server-name')?.value || '').trim(),
        current_password: String(modal.querySelector('#factory-reset-password')?.value || ''),
        ack_configuration: !!modal.querySelector('#factory-reset-ack-configuration')?.checked,
        ack_operational_data: !!modal.querySelector('#factory-reset-ack-data')?.checked,
        ack_secrets: !!modal.querySelector('#factory-reset-ack-secrets')?.checked,
        ack_repositories_preserved: !!modal.querySelector('#factory-reset-ack-repositories')?.checked,
      }),
    });
    if (!confirmation) return;
    const resetRes = await fetch('/api/settings/factory-reset', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(confirmation),
    });
    const result = await resetRes.json();
    if (!resetRes.ok) throw new Error(apiErrorMessage(result, resetRes.status));
    showMsg(messageId, 'success', settingsT('transfer.factoryResetScheduled'));
    const waitForRestart = async (remaining = 30) => {
      try {
        const response = await fetch('/api/auth/status', { credentials: 'include', cache: 'no-store' });
        const state = await response.json();
        if (response.ok && state.bootstrap_required) {
          window.location.href = '/setup-admin';
          return;
        }
      } catch (_) { /* service is expected to be temporarily unavailable */ }
      if (remaining > 0) setTimeout(() => waitForRestart(remaining - 1), 2000);
    };
    setTimeout(() => waitForRestart(), 3000);
  } catch (err) {
    showMsg(messageId, 'error', settingsT('transfer.factoryResetFailed', { message: err.message }));
  }
}

async function acknowledgeRuntimeRecoveryEntry(el) {
  const entryId = String(el?.dataset?.runtimeRecoveryId || '').trim();
  if (!entryId) return;
  const confirmed = await _openSettingsDialog({
    title: settingsT('health.runtimeRecoveryAckTitle'),
    message: settingsT('health.runtimeRecoveryAckMessage'),
    confirmText: settingsT('health.runtimeRecoveryAck'),
    confirmClass: 'btn-danger',
  });
  if (!confirmed) return;
  try {
    const res = await fetch('/api/system-health/runtime-recovery/ack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: entryId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-message', 'success', settingsT('health.runtimeRecoveryAckSuccess'));
    await refreshSettings();
    window.BBUI?.core?.updateSidebarSystemHealth?.(true);
  } catch (err) {
    showMsg('settings-message', 'error', settingsT('health.runtimeRecoveryAckFailed', { message: err.message }));
  }
}

async function importJobsBundle(dryRun) {
  hideEl('settings-transfer-msg');
  try {
    const picked = await _pickFileText();
    const text = picked.content;
    const modeRaw = await _openSettingsDialog({
      title: settingsT('transfer.importJobsTitle'),
      message: settingsT('transfer.importModePrompt'),
      input: { label: settingsT('transfer.importMode'), value: 'skip', placeholder: 'skip | overwrite | rename', validate: (v) => ['skip', 'overwrite', 'rename'].includes((v || '').trim()) },
      confirmText: dryRun ? settingsT('transfer.checkAction') : settingsT('transfer.importAction'),
    });
    if (!modeRaw) return;
    const mode = modeRaw.trim();
    const res = await fetch('/api/settings/jobs-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bundle_text: text, mode, dry_run: !!dryRun }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const lines = (data.report || []).slice(0, 10).map(r => `${r.job_key || '-'} -> ${r.new_job_key || r.job_key || '-'} [${r.status}]`);
    const summary = `Jobs: ${data.imported_count || 0}, Schedules: ${data.scheduled_count || 0}`;
    const suffix = lines.length ? `\n${lines.join('\n')}` : '';
    showMsg('settings-transfer-msg', dryRun ? 'warning' : 'success', `${dryRun ? settingsT('transfer.checkOk') : settingsT('transfer.importOk')}: ${summary}${suffix}`);
    if (!dryRun) await refreshSettings();
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.importFailed', { message: err.message }));
  }
}

async function importJobsPreviewSelectFile() {
  hideEl('settings-transfer-msg');
  try {
    const picked = await _pickFileViaUiDialog({
      title: settingsT('transfer.selectJobsFile'),
      message: settingsT('transfer.selectJobsFileMessage'),
      confirmText: settingsT('transfer.openFile'),
      binary: false,
    });
    if (!picked) return;
    const text = picked.content;
    clearJobsImportPreview();
    const res = await fetch('/api/settings/jobs-import-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bundle_text: text }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.transferJobsBundleText = text;
    settingsState.transferJobsSecureMode = false;
    settingsState.transferJobsSecurePayloadB64 = '';
    settingsState.transferJobsSecurePassword = '';
    settingsState.transferJobsPreview = data;
    settingsState.transferSettingsMode = 'merge';
    await refreshSettings();
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.previewLoadedJobs', { count: data.job_count || 0, file: picked.name || settingsT('transfer.file') }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.previewFailed', { message: err.message }));
  }
}

async function importJobsSecurePreviewSelectFile() {
  hideEl('settings-transfer-msg');
  try {
    const picked = await _pickFileViaUiDialog({
      title: settingsT('transfer.selectSecureJobsFile'),
      message: settingsT('transfer.selectSecureJobsFileMessage'),
      confirmText: settingsT('transfer.openFile'),
      binary: true,
      accept: '.jobs.enc,application/octet-stream',
      namePrefix: 'bbui-jobs-secure-',
    });
    if (!picked) return;
    const password = await _openSettingsDialog({
      title: settingsT('transfer.secureJobsPreviewTitle'),
      message: settingsT('transfer.jobsFilePassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 1 },
      confirmText: settingsT('transfer.loadPreview'),
    });
    if (!password) return;
    const payload_b64 = picked.payload_b64;
    clearJobsImportPreview();
    const res = await fetch('/api/settings/jobs-import-secure-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, payload_b64 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.transferJobsBundleText = '';
    settingsState.transferJobsSecureMode = true;
    settingsState.transferJobsSecurePayloadB64 = payload_b64;
    settingsState.transferJobsSecurePassword = password;
    settingsState.transferJobsPreview = data;
    settingsState.transferProfileSecretsPreview = null;
    settingsState.transferProfileSecretsPayloadB64 = '';
    settingsState.transferProfileSecretsPassword = '';
    settingsState.transferSettingsMode = 'merge';
    await refreshSettings();
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.previewLoadedJobs', { count: data.job_count || 0, file: picked.name || settingsT('transfer.file') }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.previewFailed', { message: err.message }));
  }
}

async function importJobsApplySelected() {
  hideEl('settings-transfer-msg');
  try {
    const preview = settingsState.transferJobsPreview;
    const hasPayload = settingsState.transferJobsSecureMode
      ? !!settingsState.transferJobsSecurePayloadB64
      : !!settingsState.transferJobsBundleText;
    if (!preview || !hasPayload) throw new Error(settingsT('transfer.noJobsPreview'));
    const selected = [];
    const perMode = {};
    const perProfileMode = {};
    (preview.jobs || []).forEach((r, idx) => {
      const cb = document.querySelector(`[data-job-preview-select="${idx}"]`);
      const modeSel = document.querySelector(`[data-job-preview-mode="${idx}"]`);
      if (cb?.checked) {
        selected.push(r.job_key);
        if (modeSel?.value) perMode[r.job_key] = modeSel.value;
      }
    });
    if (!selected.length) throw new Error(settingsT('transfer.noJobsSelected'));
    const settingsModeEl = document.getElementById('settings-import-mode');
    const settingsMode = String(settingsModeEl?.value || settingsState.transferSettingsMode || 'merge').trim().toLowerCase();
    document.querySelectorAll('[data-settings-profile-mode]').forEach((el) => {
      const k = String(el.getAttribute('data-settings-profile-mode') || '').trim();
      const v = String(el.value || 'skip').trim().toLowerCase();
      if (k) perProfileMode[k] = v;
    });
    const existsCnt = selected.filter((key) => {
      const row = (preview.jobs || []).find((r) => r.job_key === key);
      return String(row?.conflict || '') === 'exists';
    }).length;
    const ok = await _openSettingsDialog({
      title: settingsT('transfer.importJobsTitle'),
      message: settingsT('transfer.confirmJobsImport', { count: selected.length, existing: existsCnt ? settingsT('transfer.existingSelection', { count: existsCnt }) : '' }),
      confirmText: settingsT('transfer.startImport'),
    });
    if (!ok) return;
    let importJobs = true;
    let importPassphrases = true;
    if (settingsState.transferJobsSecureMode) {
      const scope = await _openSettingsDialog({
        title: settingsT('transfer.importContent'),
        html: `
          <div style="display:flex;flex-direction:column;gap:8px">
            <label class="form-checkbox-row"><input type="radio" name="jobs-secure-scope" value="both" checked> ${settingsT('transfer.jobsAndPassphrases')}</label>
            <label class="form-checkbox-row"><input type="radio" name="jobs-secure-scope" value="jobs_only"> ${settingsT('transfer.jobsOnly')}</label>
            <label class="form-checkbox-row"><input type="radio" name="jobs-secure-scope" value="passphrases_only"> ${settingsT('transfer.passphrasesOnly')}</label>
          </div>
        `,
        confirmText: settingsT('transfer.continue'),
        resolveValue: ({ modal }) => {
          const checked = modal?.querySelector('input[name="jobs-secure-scope"]:checked');
          return String(checked?.value || 'both');
        },
      });
      if (!scope) return;
      importJobs = scope !== 'passphrases_only';
      importPassphrases = scope !== 'jobs_only';
    }
    const endpoint = settingsState.transferJobsSecureMode ? '/api/settings/jobs-import-secure' : '/api/settings/jobs-import';
    const body = settingsState.transferJobsSecureMode ? {
      password: settingsState.transferJobsSecurePassword,
      payload_b64: settingsState.transferJobsSecurePayloadB64,
      mode: 'skip',
      dry_run: false,
      selected_jobs: selected,
      per_job_mode: perMode,
      settings_mode: settingsMode,
      per_profile_mode: perProfileMode,
      import_jobs: importJobs,
      import_passphrases: importPassphrases,
    } : {
      bundle_text: settingsState.transferJobsBundleText,
      mode: 'skip',
      dry_run: false,
      selected_jobs: selected,
      per_job_mode: perMode,
      settings_mode: settingsMode,
      per_profile_mode: perProfileMode,
    };
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const report = Array.isArray(data?.report) ? data.report : [];
    const byStatus = report.reduce((acc, r) => {
      const s = String(r?.status || 'unknown');
      acc[s] = (acc[s] || 0) + 1;
      return acc;
    }, {});
    const detail = Object.keys(byStatus).length
      ? ` · ${Object.entries(byStatus).map(([k, v]) => `${k}:${v}`).join(', ')}`
      : '';
    const srep = data?.settings_report || null;
    const stext = srep ? ` · Settings(${srep.mode}): ${srep.applied || 0} ${settingsT('transfer.settingsApplied')}, ${settingsT('transfer.conflicts')} ${srep.conflicts || 0}${data?.settings_backup ? `, Backup: ${data.settings_backup}` : ''}` : '';
    const ppText = Number(data?.restored_passphrases || 0) ? ` · ${settingsT('transfer.passphrasesRestored', { count: Number(data.restored_passphrases) })}` : '';
    const keyText = Number(data?.restored_keyfiles || 0) ? ` · ${settingsT('transfer.keyfilesRestored', { count: Number(data.restored_keyfiles) })}` : '';
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.importSummary', { jobs: data.imported_count || 0, schedules: data.scheduled_count || 0, details: `${detail}${stext}${ppText}${keyText}` }));
    settingsState.transferJobsPreview = null;
    settingsState.transferJobsBundleText = '';
    settingsState.transferJobsSecurePayloadB64 = '';
    settingsState.transferJobsSecurePassword = '';
    settingsState.transferJobsSecureMode = false;
    await refreshSettings();
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.importFailed', { message: err.message }));
  }
}

async function exportSecretsBackup() {
  hideEl('settings-transfer-msg');
  try {
    const password = await _openSettingsDialog({
      title: settingsT('transfer.passphraseExportTitle'),
      message: settingsT('transfer.encryptedBackupPassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 8 },
      confirmText: settingsT('transfer.startExport'),
    });
    if (!password) return;
    const res = await fetch('/api/settings/secrets-backup-export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const bytes = atob(data.payload_b64 || '');
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const blob = new Blob([arr], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || 'bbui-secrets-backup.enc';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.passphraseBackupCreated', { count: data.count || 0 }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.passphraseBackupFailed', { message: err.message }));
  }
}

async function importSecretsBackup() {
  hideEl('settings-transfer-msg');
  try {
    const password = await _openSettingsDialog({
      title: settingsT('transfer.passphraseImportTitle'),
      message: settingsT('transfer.backupFilePassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 1 },
      confirmText: settingsT('transfer.continue'),
    });
    if (!password) return;
    const picked = await _pickFileViaUiDialog({
      title: settingsT('transfer.selectPassphraseBackup'),
      message: settingsT('transfer.selectPassphraseBackupMessage'),
      confirmText: settingsT('transfer.openFile'),
      binary: true,
    });
    if (!picked) return;
    const fileText = picked.payload_b64;
    const modeRaw = await _openSettingsDialog({
      title: settingsT('transfer.importMode'),
      message: settingsT('transfer.existingFilesPrompt'),
      input: { label: settingsT('transfer.importMode'), value: 'skip', placeholder: 'skip | overwrite | rename', validate: (v) => ['skip', 'overwrite', 'rename'].includes((v || '').trim()) },
      confirmText: settingsT('transfer.startImport'),
    });
    if (!modeRaw) return;
    const mode = modeRaw.trim();
    const res = await fetch('/api/settings/secrets-backup-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, payload_b64: fileText, mode }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.passphraseImportOk', { count: data.restored_count || 0, suffix: settingsT('transfer.restoredSuffix') }));
    await refreshSettings();
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.passphraseImportFailed', { message: err.message }));
  }
}

async function importSecretsPreviewSelectFile() {
  hideEl('settings-transfer-msg');
  try {
    const password = await _openSettingsDialog({
      title: settingsT('transfer.passphrasePreviewTitle'),
      message: settingsT('transfer.backupFilePassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 1 },
      confirmText: settingsT('transfer.continue'),
    });
    if (!password) return;
    const picked = await _pickFileViaUiDialog({
      title: settingsT('transfer.selectPassphraseBackup'),
      message: settingsT('transfer.selectPreviewBackupMessage'),
      confirmText: settingsT('transfer.openFile'),
      binary: true,
    });
    if (!picked) return;
    const payload_b64 = picked.payload_b64;
    clearSecretsImportPreview();
    const res = await fetch('/api/settings/secrets-backup-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, payload_b64 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.transferSecretsPreview = data;
    settingsState.transferSecretsPayloadB64 = payload_b64;
    settingsState.transferSecretsPassword = password;
    await refreshSettings();
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.previewLoadedPassphrases', { count: data.count || 0, file: picked.name || settingsT('transfer.file') }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.secretsPreviewFailed', { message: err.message }));
  }
}

async function importSecretsApplySelected() {
  hideEl('settings-transfer-msg');
  try {
    const preview = settingsState.transferSecretsPreview;
    if (!preview || !settingsState.transferSecretsPayloadB64 || !settingsState.transferSecretsPassword) {
      throw new Error(settingsT('transfer.noSecretsPreview'));
    }
    const selected = [];
    (preview.files || []).forEach((r, idx) => {
      const cb = document.querySelector(`[data-secret-preview-select="${idx}"]`);
      if (cb?.checked) selected.push(r.name);
    });
    if (!selected.length) throw new Error(settingsT('transfer.noPassphraseFilesSelected'));
    const modeRaw = await _openSettingsDialog({
      title: settingsT('transfer.importMode'),
      message: settingsT('transfer.existingFilesPrompt'),
      input: { label: settingsT('transfer.importMode'), value: 'skip', placeholder: 'skip | overwrite | rename', validate: (v) => ['skip', 'overwrite', 'rename'].includes((v || '').trim()) },
      confirmText: settingsT('transfer.startImport'),
    });
    if (!modeRaw) return;
    const mismatchCnt = (preview.files || []).filter((r) => selected.includes(r.name) && String(r.status || '') === 'present_mismatch').length;
    const ok = await _openSettingsDialog({
      title: settingsT('transfer.passphraseImportTitle'),
      message: settingsT('transfer.confirmPassphraseImport', { count: selected.length, mode: modeRaw.trim(), different: mismatchCnt ? settingsT('transfer.differentSelection', { count: mismatchCnt }) : '' }),
      confirmText: settingsT('transfer.startImport'),
    });
    if (!ok) return;
    const res = await fetch('/api/settings/secrets-backup-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        password: settingsState.transferSecretsPassword,
        payload_b64: settingsState.transferSecretsPayloadB64,
        mode: modeRaw.trim(),
        selected_names: selected,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.passphraseImportOk', { count: data.restored_count || 0, suffix: '' }));
    settingsState.transferSecretsPreview = null;
    settingsState.transferSecretsPayloadB64 = '';
    settingsState.transferSecretsPassword = '';
    await refreshSettings();
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.passphraseImportFailed', { message: err.message }));
  }
}

async function exportProfileSecretsBackup() {
  hideEl('settings-transfer-msg');
  try {
    const password = await _openSettingsDialog({
      title: settingsT('transfer.exportProfilesTitle'),
      message: settingsT('transfer.secretsPackagePassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 8 },
      confirmText: settingsT('transfer.startExport'),
    });
    if (!password) return;
    const res = await fetch('/api/settings/profile-secrets-export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const bytes = atob(data.payload_b64 || '');
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const blob = new Blob([arr], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || 'bbui-profile-secrets.profiles.enc';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.profilesExported', { count: data.count || 0 }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.profilesExportFailed', { message: err.message }));
  }
}

async function importProfileSecretsPreviewSelectFile() {
  hideEl('settings-transfer-msg');
  try {
    const picked = await _pickFileViaUiDialog({
      title: settingsT('transfer.selectProfilesFile'),
      message: settingsT('transfer.selectProfilesFileMessage'),
      confirmText: settingsT('transfer.openFile'),
      binary: true,
      accept: '.profiles.enc,application/octet-stream',
      namePrefix: 'bbui-profile-secrets-',
    });
    if (!picked) return;
    const password = await _openSettingsDialog({
      title: settingsT('transfer.profilesPreviewTitle'),
      message: settingsT('transfer.secretsFilePassword'),
      input: { label: settingsT('transfer.password'), type: 'password', value: '', validate: (v) => String(v || '').length >= 1 },
      confirmText: settingsT('transfer.loadPreview'),
    });
    if (!password) return;
    const payload_b64 = picked.payload_b64;
    clearProfileSecretsImportPreview();
    const res = await fetch('/api/settings/profile-secrets-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, payload_b64 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.transferProfileSecretsPreview = data;
    settingsState.transferProfileSecretsPayloadB64 = payload_b64;
    settingsState.transferProfileSecretsPassword = password;
    settingsState.transferJobsPreview = null;
    settingsState.transferJobsBundleText = '';
    settingsState.transferJobsSecurePayloadB64 = '';
    settingsState.transferJobsSecurePassword = '';
    settingsState.transferJobsSecureMode = false;
    await refreshSettings();
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.previewLoadedProfiles', { count: data.count || 0, file: picked.name || settingsT('transfer.file') }));
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.profilesPreviewFailed', { message: err.message }));
  }
}

async function importProfileSecretsApplySelected() {
  hideEl('settings-transfer-msg');
  try {
    const preview = settingsState.transferProfileSecretsPreview;
    if (!preview || !settingsState.transferProfileSecretsPayloadB64 || !settingsState.transferProfileSecretsPassword) {
      throw new Error(settingsT('transfer.noProfilesPreview'));
    }
    const selected = [];
    const profileMap = {};
    (preview.entries || []).forEach((r, idx) => {
      const cb = document.querySelector(`[data-profile-secret-preview-select="${idx}"]`);
      if (cb?.checked) {
        const entryId = `${String(r.profile_type || '').toLowerCase()}:${String(r.profile_key || '').toLowerCase()}:${String(r.secret_type || '')}`;
        selected.push(entryId);
        const targetSel = document.querySelector(`[data-profile-secret-target="${idx}"]`);
        const mapped = String(targetSel?.value || '').trim().toLowerCase();
        if (mapped) profileMap[entryId] = mapped;
      }
    });
    if (!selected.length) throw new Error(settingsT('transfer.noProfilesSelected'));
    const modeRaw = await _openSettingsDialog({
      title: settingsT('transfer.importMode'),
      message: settingsT('transfer.existingFilesShortPrompt'),
      input: { label: settingsT('transfer.importMode'), value: 'skip', placeholder: 'skip | overwrite', validate: (v) => ['skip', 'overwrite'].includes((v || '').trim()) },
      confirmText: settingsT('transfer.startImport'),
    });
    if (!modeRaw) return;
    const settingsModeEl = document.getElementById('profile-secrets-settings-mode');
    const settingsMode = String(settingsModeEl?.value || 'merge').trim().toLowerCase();
    const res = await fetch('/api/settings/profile-secrets-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        password: settingsState.transferProfileSecretsPassword,
        payload_b64: settingsState.transferProfileSecretsPayloadB64,
        mode: modeRaw.trim(),
        settings_mode: settingsMode,
        selected_entries: selected,
        profile_map: profileMap,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-transfer-msg', 'success', settingsT('transfer.profilesImportOk', { count: data.restored_count || 0 }));
    settingsState.transferProfileSecretsPreview = null;
    settingsState.transferProfileSecretsPayloadB64 = '';
    settingsState.transferProfileSecretsPassword = '';
    await refreshSettings();
  } catch (err) {
    showMsg('settings-transfer-msg', 'error', settingsT('transfer.profilesImportFailed', { message: err.message }));
  }
}

async function refreshSettingsConfigBackups() {
  const el = document.getElementById('settings-config-backups-list');
  if (!el) return;
  if (window.BBUI?.core?.isStartupMaintenanceMode?.()) {
    el.innerHTML = `<div class="status-message warning-state">${settingsT('backups.maintenanceUnavailable')}</div>`;
    return;
  }
  try {
    const res = await fetch('/api/settings/backup-history');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const rows = data.backups || [];
    if (!rows.length) {
      el.innerHTML = `<div class="text-muted" style="font-size:13px">${settingsT('backups.none')}</div>`;
      return;
    }
    el.innerHTML = `
      <table class="settings-table">
        <thead><tr><th>${settingsT('backups.file')}</th><th>${settingsT('backups.reason')}</th><th>${settingsT('backups.changed')}</th><th>${settingsT('backups.size')}</th><th></th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>${escHtml(r.name)}</td>
              <td>${escHtml(r.reason || '—')}</td>
              <td>${new Date((r.mtime || 0) * 1000).toLocaleString('de-DE')}</td>
              <td>${_fmtBytes(Number(r.size || 0))}</td>
              <td style="text-align:right">
                <button class="btn btn-secondary btn-sm" data-settings-action="diff-config-backup" data-backup-name="${escHtml(r.name)}">Diff</button>
                <button class="btn btn-secondary btn-sm" data-settings-action="restore-config-backup" data-backup-name="${escHtml(r.name)}">${settingsT('backups.restore')}</button>
                <button class="btn btn-secondary btn-sm" data-settings-action="delete-config-backup" data-backup-name="${escHtml(r.name)}">${settingsT('backups.delete')}</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = `<div class="status-message error-state">${settingsT('backups.loadError', { message: escHtml(err.message || String(err)) })}</div>`;
  }
}

async function restoreSettingsConfigBackup(name) {
  if (!name) return;
  const ok = await _openSettingsDialog({
    title: settingsT('backups.restoreTitle'),
    message: settingsT('backups.restoreMessage', { name }),
    confirmText: settingsT('backups.restore'),
  });
  if (!ok) return;
  hideEl('settings-config-backups-msg');
  try {
    const res = await fetch('/api/settings/backup-restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-config-backups-msg', 'success', settingsT('backups.restored', { name }));
    await refreshSettings();
  } catch (err) {
    showMsg('settings-config-backups-msg', 'error', settingsT('backups.restoreError', { message: err.message }));
  }
}

async function diffSettingsConfigBackup(name) {
  if (!name) return;
  hideEl('settings-config-backups-msg');
  const box = document.getElementById('settings-config-backups-diff');
  if (box) {
    box.className = '';
    box.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><span>${settingsT('backups.loadingDiff')}</span></div>`;
  }
  try {
    const res = await fetch('/api/settings/backup-diff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, context_lines: 3 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    if (!box) return;
    if (!data.changed) {
      box.innerHTML = `<div class="status-message success">${settingsT('backups.noDifferences', { name: escHtml(name) })}</div>`;
      return;
    }
    const rows = Array.isArray(data.side_by_side) ? data.side_by_side : [];
    const leftTitle = settingsT('backups.activeConfig');
    const rightTitle = `Backup: ${name}`;
    const lineNo = (n) => (Number.isInteger(n) ? String(n) : '');
    const sideRows = rows.map((r) => `
      <tr class="sbs-${escHtml(String(r.tag || 'equal'))}">
        <td class="sbs-ln">${escHtml(lineNo(r.left_no))}</td>
        <td class="sbs-code"><code>${escHtml(r.left || '')}</code></td>
        <td class="sbs-ln">${escHtml(lineNo(r.right_no))}</td>
        <td class="sbs-code"><code>${escHtml(r.right || '')}</code></td>
      </tr>
    `).join('');
    const unifiedFallback = String(data.diff || '').trim();
    box.innerHTML = `
      <div class="text-muted" style="font-size:12px;margin-bottom:6px">Diff: aktiv → Backup (${escHtml(name)})</div>
      <div class="settings-sbs-wrap">
        <table class="settings-sbs-table">
          <thead>
            <tr>
              <th class="sbs-ln">#</th><th>${escHtml(leftTitle)}</th>
              <th class="sbs-ln">#</th><th>${escHtml(rightTitle)}</th>
            </tr>
          </thead>
          <tbody>${sideRows}</tbody>
        </table>
      </div>
      <details style="margin-top:8px">
        <summary style="cursor:pointer;color:var(--text-muted)">${settingsT('backups.showDiff')}</summary>
        <pre class="log-output" style="max-height:240px;overflow:auto">${escHtml(unifiedFallback)}</pre>
      </details>
    `;
  } catch (err) {
    if (box) {
      box.innerHTML = `<div class="status-message error-state">${settingsT('backups.diffError', { message: escHtml(err.message || String(err)) })}</div>`;
    }
  }
}

async function deleteSettingsConfigBackup(name) {
  if (!name) return;
  const ok = await _openSettingsDialog({
    title: settingsT('backups.deleteTitle'),
    message: name,
    confirmText: settingsT('backups.delete'),
  });
  if (!ok) return;
  hideEl('settings-config-backups-msg');
  try {
    const res = await fetch('/api/settings/backup-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('settings-config-backups-msg', 'success', settingsT('backups.deleted', { value: name }));
    await refreshSettingsConfigBackups();
  } catch (err) {
    showMsg('settings-config-backups-msg', 'error', settingsT('backups.deleteError', { message: err.message }));
  }
}

async function deleteConfigBackupsKeepLatest() {
  const ok = await _openSettingsDialog({
    title: settingsT('backups.cleanupTitle'),
    message: settingsT('backups.cleanupMessage'),
    confirmText: settingsT('backups.cleanup'),
  });
  if (!ok) return;
  hideEl('settings-config-backups-msg');
  try {
    const res = await fetch('/api/settings/backup-delete-keep-latest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const count = Number(data.deleted_count || 0);
    const kept = data.kept ? `, behalten: ${data.kept}` : '';
    showMsg('settings-config-backups-msg', 'success', settingsT('backups.deleted', { value: `${count}${kept}` }));
    await refreshSettingsConfigBackups();
  } catch (err) {
    showMsg('settings-config-backups-msg', 'error', settingsT('backups.cleanupError', { message: err.message }));
  }
}

function renderSettingsSMTP(s) {
  const passwordSet = String(s.GLOBAL_SMTP_PASSWORD_SET || 'false') === 'true';
  const emailEvents = s.NOTIFY_EMAIL_EVENTS || 'backup_failed';
  const eventRows = notificationEventRows(emailEvents, notificationEventOptions(), 'data-email-event', '_syncEmailEvents');
  return settingsCard(settingsT('forms.smtpTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
    `<div class="settings-body two-col">
      ${ftext('GLOBAL_MAIL_RECIPIENT', settingsT('forms.recipient'), s.GLOBAL_MAIL_RECIPIENT)}
      ${ftext('GLOBAL_MAIL_SENDER', settingsT('forms.sender'), s.GLOBAL_MAIL_SENDER)}
      ${ftext('GLOBAL_SMTP_HOST', 'SMTP-Host', s.GLOBAL_SMTP_HOST)}
      ${fnum('GLOBAL_SMTP_PORT', 'SMTP-Port', s.GLOBAL_SMTP_PORT)}
      ${ftext('GLOBAL_SMTP_USER', settingsT('forms.smtpUser'), s.GLOBAL_SMTP_USER)}
      ${fpwd('GLOBAL_SMTP_PASSWORD', passwordSet ? settingsT('forms.smtpPasswordSet') : settingsT('forms.smtpPassword'), '')}
      <label class="form-checkbox-row" style="grid-column:1/-1">
        <input type="checkbox" data-key="GLOBAL_SMTP_USE_TLS"
          ${s.GLOBAL_SMTP_USE_TLS === 'true' ? 'checked' : ''}
          onchange="markSettingsDirty()">
        ${settingsT('forms.useTls')}
      </label>
      <input type="hidden" data-key="NOTIFY_EMAIL_EVENTS" value="${escHtml(emailEvents)}">
      <fieldset class="settings-fieldset" style="grid-column:1/-1">
        <legend>${settingsT('forms.notifyEvents')}</legend>
        <div class="settings-body two-col">${eventRows}</div>
      </fieldset>
      <div style="grid-column:1/-1;display:flex;align-items:center;gap:12px;margin-top:4px">
        <button class="btn btn-secondary btn-sm" id="smtp-test-btn" data-settings-action="send-test-email">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
          ${settingsT('forms.sendTestEmail')}
        </button>
        <span id="smtp-test-result" style="font-size:13px"></span>
      </div>
    </div>`);
}

async function sendTestEmail() {
  const btn    = document.getElementById('smtp-test-btn');
  const result = document.getElementById('smtp-test-result');
  if (!btn || !result) return;
  const smtpFields = [
    'GLOBAL_MAIL_RECIPIENT',
    'GLOBAL_MAIL_SENDER',
    'GLOBAL_SMTP_HOST',
    'GLOBAL_SMTP_PORT',
    'GLOBAL_SMTP_USER',
    'GLOBAL_SMTP_PASSWORD',
    'GLOBAL_SMTP_USE_TLS',
    'NOTIFY_EMAIL_EVENTS',
  ];
  const hasUnsavedSmtpChanges = smtpFields.some((key) => {
    const el = document.querySelector(`[data-key="${key}"]`);
    if (!el) return false;
    const current = el.type === 'checkbox' ? (el.checked ? 'true' : 'false') : String(el.value || '');
    const saved = String(settingsState.data?.smtp?.[key] ?? '');
    if (key === 'GLOBAL_SMTP_PASSWORD') return String(current || '').trim() !== '';
    return current !== saved;
  });
  if (hasUnsavedSmtpChanges) {
    result.textContent = settingsT('forms.saveBeforeTestEmail');
    result.style.color = 'var(--ui-state-warning-fg)';
    return;
  }
  btn.classList.add('loading');
  result.textContent = '';
  result.style.color = '';

  try {
    const res  = await fetch('/api/settings/test-smtp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    result.textContent = apiMessage(data, data.success ? settingsT('forms.sent') : settingsT('forms.error'));
    result.style.color = data.success ? 'var(--success)' : 'var(--error)';
  } catch (err) {
    result.textContent = settingsT('error', { message: err.message });
    result.style.color = 'var(--error)';
  } finally {
    btn.classList.remove('loading');
  }
}

function _notificationEventEnabled(events, key) {
  return String(events || '').split(',').map((item) => item.trim()).includes(key);
}

function _syncNotificationEvents(targetKey, attrName) {
  const hidden = document.querySelector(`[data-key="${targetKey}"]`);
  if (!hidden) return;
  const values = Array.from(document.querySelectorAll(`[${attrName}]`))
    .filter((el) => el.checked)
    .map((el) => el.getAttribute(attrName))
    .filter(Boolean);
  hidden.value = values.join(',');
  markSettingsDirty();
}

function _syncEmailEvents() {
  _syncNotificationEvents('NOTIFY_EMAIL_EVENTS', 'data-email-event');
}

function _syncUnraidEvents() {
  _syncNotificationEvents('NOTIFY_UNRAID_EVENTS', 'data-unraid-event');
}

function notificationEventRows(events, rows, attrName, syncFn) {
  return rows.map(([key, label]) => `
    <label class="form-checkbox-row">
      <input type="checkbox" ${attrName}="${key}" ${_notificationEventEnabled(events, key) ? 'checked' : ''} onchange="${syncFn}()">
      ${label}
    </label>`).join('');
}

function notificationEventOptions() {
  return [
    ['backup_success', settingsT('forms.notifyEventBackupSuccess')],
    ['backup_warning', settingsT('forms.notifyEventBackupWarning')],
    ['backup_failed', settingsT('forms.notifyEventBackupFailed')],
    ['backup_skipped', settingsT('forms.notifyEventBackupSkipped')],
    ['backup_overdue', settingsT('forms.notifyEventBackupOverdue')],
    ['restore_test_success', settingsT('forms.notifyEventRestoreTestSuccess')],
    ['restore_test_failed', settingsT('forms.notifyEventRestoreTestFailed')],
    ['restore_test_overdue', settingsT('forms.notifyEventRestoreTestOverdue')],
  ];
}

function renderSettingsNotificationReminders(s) {
  const interval = s.NOTIFY_REMINDER_INTERVAL_HOURS || '24';
  const backupTolerance = s.NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS || '6';
  return settingsCard(settingsT('forms.notificationReminderTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    `<div class="settings-body two-col">
      <div class="status-message info" style="grid-column:1/-1">${settingsT('forms.notificationReminderHint')}</div>
      ${fnum('NOTIFY_REMINDER_INTERVAL_HOURS', settingsT('forms.notifyReminderInterval'), interval)}
      ${fnum('NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS', settingsT('forms.backupOverdueTolerance'), backupTolerance)}
      <div class="form-help" style="grid-column:1/-1">${settingsT('forms.backupOverdueToleranceHint')}</div>
    </div>`);
}

function renderSettingsUnraidNotifications(s) {
  const events = s.NOTIFY_UNRAID_EVENTS || 'backup_success,backup_warning,backup_failed,backup_skipped';
  const eventRows = notificationEventRows(events, notificationEventOptions(), 'data-unraid-event', '_syncUnraidEvents');
  return settingsCard(settingsT('forms.unraidNotifyTitle'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
    `<div class="settings-body two-col">
      <div class="status-message info" style="grid-column:1/-1">${settingsT('forms.unraidNotifyHint')}</div>
      <input type="hidden" data-key="NOTIFY_UNRAID_EVENTS" value="${escHtml(events)}">
      <fieldset class="settings-fieldset" style="grid-column:1/-1">
        <legend>${settingsT('forms.notifyEvents')}</legend>
        <div class="settings-body two-col">${eventRows}</div>
      </fieldset>
    </div>`);
}

function renderSettingsNotifications(data) {
  return `
    ${renderSettingsNotificationReminders(data.unraid_notifications || {})}
    ${renderSettingsSMTP(data.smtp || {})}
    ${renderSettingsUnraidNotifications(data.unraid_notifications || {})}
    ${renderSettingsAppriseProfiles()}`;
}

function _appriseDefaultEvents() {
  return ['backup_success', 'backup_warning', 'backup_failed', 'backup_skipped', 'restore_test_failed'];
}

function _appriseProfileName(profile) {
  return String(profile?.name || profile?.id || settingsT('apprise.newProfile')).trim();
}

function _appriseProviderLabel(profile) {
  const provider = String(profile?.provider || '').trim().toLowerCase();
  if (!provider) return settingsT('apprise.genericProvider');
  const row = settingsState.appriseProviders.find((item) => (item.schemas || []).includes(provider));
  const service = String(row?.service_name || '').trim();
  if (!service) return provider;
  return service.toLowerCase() === provider ? service : `${service} (${provider})`;
}

function _appriseProviderSchema(profile) {
  return String(profile?.provider || '').trim().toLowerCase();
}

function _appriseSelectedProfile() {
  const profiles = Array.isArray(settingsState.appriseProfiles) ? settingsState.appriseProfiles : [];
  return profiles.find((profile) => profile.id === settingsState.appriseSelectedProfileId) || profiles[0] || null;
}

function _appriseDraftFromProfile(profile, duplicate = false) {
  const source = profile || {};
  const id = duplicate
    ? `${String(source.id || 'apprise').replace(/-copy(?:-\\d+)?$/, '')}-copy`
    : String(source.id || '');
  return {
    id,
    original_id: duplicate ? '' : String(source.id || ''),
    name: duplicate ? settingsT('apprise.copyName', { name: _appriseProfileName(source) }) : _appriseProfileName(source),
    enabled: source.enabled !== false,
    provider: String(source.provider || 'ntfy'),
    selected_events: Array.isArray(source.selected_events) && source.selected_events.length
      ? [...source.selected_events]
      : _appriseDefaultEvents(),
    timeout_seconds: Number(source.timeout_seconds || 15),
    retry_policy: {
      attempts: Number(source.retry_policy?.attempts || 1),
      backoff_seconds: Number(source.retry_policy?.backoff_seconds || 0),
    },
    priority: String(source.priority || 'default') || 'default',
    default: !!source.default,
    url_template: String(source.url_template || ''),
    url_set: !!source.url_set,
    url_fields: source.url_fields && typeof source.url_fields === 'object' ? { ...source.url_fields } : {},
    apprise_url: '',
  };
}

function _appriseEmptyDraft() {
  return _appriseDraftFromProfile({
    id: '',
    name: settingsT('apprise.newProfile'),
    provider: 'ntfy',
    enabled: true,
    default: !settingsState.appriseProfiles.length,
    selected_events: _appriseDefaultEvents(),
    timeout_seconds: 15,
    retry_policy: { attempts: 1, backoff_seconds: 0 },
    priority: 'default',
    url_set: false,
  });
}

function _appriseProviderCategory(row) {
  const haystack = `${row.service_name || ''} ${(row.schemas || []).join(' ')}`.toLowerCase();
  if (haystack.includes('mail') || haystack.includes('smtp')) return 'email';
  if (haystack.includes('discord') || haystack.includes('slack') || haystack.includes('telegram') || haystack.includes('matrix')) return 'chat';
  if (haystack.includes('ntfy') || haystack.includes('gotify') || haystack.includes('pushover') || haystack.includes('pushbullet')) return 'push';
  if (haystack.includes('json') || haystack.includes('webhook') || haystack.includes('http')) return 'webhook';
  return 'other';
}

function _appriseRecommendedProviders(selectedProvider) {
  const recommended = [
    ['ntfy', 'ntfy'],
    ['ntfys', 'ntfy (HTTPS)'],
    ['mailtos', 'SMTP / E-Mail'],
    ['discord', 'Discord'],
    ['telegram', 'Telegram'],
    ['gotify', 'Gotify'],
    ['pushover', 'Pushover'],
    ['slack', 'Slack'],
    ['json', 'JSON webhook'],
    ['apprise', settingsT('apprise.genericProvider')],
  ];
  if (selectedProvider && !recommended.some(([value]) => value === selectedProvider)) {
    recommended.unshift([selectedProvider, _appriseProviderLabel({ provider: selectedProvider })]);
  }
  return recommended;
}

function _renderAppriseProviderOptions(selectedProvider) {
  return _appriseRecommendedProviders(selectedProvider)
    .map(([value, label]) => `<option value="${escAttr(value)}" ${selectedProvider === value ? 'selected' : ''}>${escHtml(label)}</option>`)
    .join('');
}

function _renderAppriseProviderResults(selectedProvider) {
  const filter = String(settingsState.appriseProviderFilter || '').trim().toLowerCase();
  const rows = Array.isArray(settingsState.appriseProviders) ? settingsState.appriseProviders : [];
  const candidates = [];
  rows.forEach((row) => {
    (row.schemas || []).forEach((schema) => {
      const item = {
        schema,
        service_name: row.service_name || schema,
        setup_url: row.setup_url || '',
        category: _appriseProviderCategory(row),
      };
      const text = `${item.schema} ${item.service_name}`.toLowerCase();
      if (!filter || text.includes(filter)) candidates.push(item);
    });
  });
  candidates.sort((a, b) => a.category.localeCompare(b.category) || a.service_name.localeCompare(b.service_name) || a.schema.localeCompare(b.schema));
  const visible = candidates.slice(0, 24);
  const grouped = visible.reduce((acc, item) => {
    acc[item.category] = acc[item.category] || [];
    acc[item.category].push(item);
    return acc;
  }, {});
  const groups = ['push', 'chat', 'email', 'webhook', 'other']
    .filter((key) => grouped[key])
    .map((key) => `
      <section class="apprise-provider-group">
        <h4>${settingsT(`apprise.categories.${key}`)}</h4>
        <div>
          ${grouped[key].map((item) => `
            <button type="button" class="apprise-provider-choice ${item.schema === selectedProvider ? 'active' : ''}" data-settings-action="apprise-provider-select" data-apprise-provider="${escAttr(item.schema)}">
              <strong>${escHtml(item.service_name)}</strong>
              <small>${escHtml(item.schema)}</small>
            </button>`).join('')}
        </div>
      </section>`)
    .join('');
  const empty = settingsState.appriseProvidersLoading
    ? settingsT('apprise.providersLoading')
    : (settingsState.appriseProvidersLoaded ? settingsT('apprise.noProviders') : settingsT('apprise.providersNotLoaded'));
  const limited = candidates.length > visible.length
    ? `<div class="form-help">${settingsT('apprise.providerResultsLimited', { shown: visible.length, count: candidates.length })}</div>`
    : '';
  return `${groups || `<div class="status-message empty-state">${escHtml(empty)}</div>`}${limited}`;
}

function _renderAppriseProviderAdvanced(selectedProvider) {
  return `
    <details class="apprise-provider-advanced" style="grid-column:1/-1">
      <summary>${settingsT('apprise.advancedProviders')}</summary>
      <div class="form-group">
        <label class="form-label" for="apprise-provider-filter">${settingsT('apprise.providerSearch')}</label>
        <input class="form-input" id="apprise-provider-filter" type="search" value="${escAttr(settingsState.appriseProviderFilter)}" placeholder="${escAttr(settingsT('apprise.providerSearchPlaceholder'))}" oninput="onAppriseProviderFilterChange(this.value)">
        <div class="form-help">${settingsT('apprise.providerCount', { count: settingsState.appriseProviders.length || 0 })}</div>
      </div>
      <div class="apprise-provider-picker" id="apprise-provider-picker">
        ${_renderAppriseProviderResults(selectedProvider)}
      </div>
    </details>`;
}

function _renderAppriseEvents(events) {
  const selected = Array.isArray(events) ? events : _appriseDefaultEvents();
  return notificationEventOptions().map(([key, label]) => `
    <label class="form-checkbox-row">
      <input type="checkbox" data-apprise-event="${escAttr(key)}" ${selected.includes(key) ? 'checked' : ''}>
      ${label}
    </label>`).join('');
}

function _appriseProviderMetadata(provider) {
  const schema = String(provider || '').trim().toLowerCase();
  if (!schema) return null;
  return (settingsState.appriseProviders || []).find((item) =>
    Array.isArray(item?.schemas) && item.schemas.map((value) => String(value).toLowerCase()).includes(schema)
  ) || null;
}

function _appriseProviderSetupUrl(provider) {
  const row = _appriseProviderMetadata(provider);
  return row?.setup_url ? String(row.setup_url) : '';
}

function _appriseTemplateForSchema(template, schema) {
  const value = String(template || '').trim();
  if (!value) return '';
  return value.replaceAll('{schema}', String(schema || '').trim().toLowerCase() || 'apprise');
}

function _appriseTemplateSignature(template) {
  const value = String(template || '').trim().toLowerCase();
  return value
    .replace(/^[a-z0-9+.-]+:\/\//, '{schema}://')
    .replaceAll('{schema}', '{schema}');
}

function _appriseProviderTemplates(provider) {
  const schema = String(provider || '').trim().toLowerCase();
  const row = _appriseProviderMetadata(schema);
  const templates = Array.isArray(row?.templates) ? row.templates : [];
  return templates
    .map((template) => _appriseTemplateForSchema(template, schema))
    .filter(Boolean);
}

function _appriseTemplateTokenKeys(template) {
  const keys = [];
  const seen = new Set();
  String(template || '').replace(/\{([a-zA-Z0-9_.-]+)\}/g, (_match, key) => {
    const value = String(key || '').trim().toLowerCase();
    if (value && value !== 'schema' && !seen.has(value)) {
      seen.add(value);
      keys.push(value);
    }
    return _match;
  });
  return keys;
}

function _appriseTokenMeta(provider, key) {
  const metadata = _appriseProviderMetadata(provider);
  const tokens = Array.isArray(metadata?.tokens) ? metadata.tokens : [];
  const wanted = String(key || '').toLowerCase();
  return tokens.find((item) => String(item.key || '').toLowerCase() === wanted) || { key: wanted, name: wanted };
}

function _appriseTokenIsSecret(token) {
  const text = `${token?.key || ''} ${token?.name || ''}`.toLowerCase();
  return !!token?.private || /\b(pass|password|token|secret|apikey|api_key|key)\b/.test(text);
}

function _appriseTokenLabel(token, key) {
  return String(token?.name || key || '').replaceAll('_', ' ') || String(key || '');
}

function _appriseTokenFieldExamples(provider, key) {
  const metadata = _appriseProviderMetadata(provider);
  const tokens = Array.isArray(metadata?.tokens) ? metadata.tokens : [];
  const wanted = String(key || '').toLowerCase();
  const rows = tokens
    .filter((item) => String(item?.map_to || '').toLowerCase() === wanted && String(item?.key || '').toLowerCase() !== wanted)
    .map((item) => {
      const label = _appriseTokenLabel(item, item?.key || '');
      const prefix = String(item?.prefix || '').trim();
      return prefix ? `${label}: ${prefix}` : label;
    })
    .filter(Boolean)
    .slice(0, 5);
  if (!rows.length) return '';
  return settingsT('apprise.fieldExamples', { examples: rows.join(', ') });
}

function _appriseUrlPlaceholder(provider, urlSet = false) {
  if (urlSet) return settingsT('apprise.urlPreservePlaceholder');
  const schema = String(provider || '').trim().toLowerCase();
  const template = _appriseProviderTemplates(schema)[0] || '';
  if (template) return template;
  if (schema && schema !== 'apprise') return `${schema}://...`;
  return settingsT('apprise.urlPlaceholder');
}

function _appriseSelectedTemplate(provider, current = {}) {
  const templates = _appriseProviderTemplates(provider);
  const selected = String(current?.url_template || '').trim();
  if (selected && templates.includes(selected)) return selected;
  if (selected) {
    const signature = _appriseTemplateSignature(selected);
    const compatible = templates.find((item) => _appriseTemplateSignature(item) === signature);
    if (compatible) return compatible;
  }
  return templates[0] || '';
}

function _renderAppriseUrlBuilder(provider, current = {}) {
  const schema = String(provider || '').trim().toLowerCase();
  const templates = _appriseProviderTemplates(schema);
  const template = _appriseSelectedTemplate(schema, current);
  const keys = _appriseTemplateTokenKeys(template);
  if (!template || !keys.length) return '';
  const values = current?.url_fields && typeof current.url_fields === 'object' ? current.url_fields : {};
  const templateSelect = templates.length > 1
    ? `<div class="form-group" style="grid-column:1/-1">
      <label class="form-label" for="apprise-url-template">${settingsT('apprise.urlTemplate')}</label>
      <select class="form-select mono" id="apprise-url-template" data-apprise-field="url_template" onchange="onAppriseTemplateSelect(this.value)">
        ${templates.map((item) => `<option value="${escAttr(item)}" ${item === template ? 'selected' : ''}>${escHtml(item)}</option>`).join('')}
      </select>
    </div>`
    : `<input type="hidden" data-apprise-field="url_template" value="${escAttr(template)}">`;
  const rows = keys.map((key) => {
    const token = _appriseTokenMeta(schema, key);
    const secret = _appriseTokenIsSecret(token);
    const required = !!token.required;
    const label = _appriseTokenLabel(token, key);
    const stored = secret ? '' : String(values[key] || '');
    const placeholder = secret && current.url_set
      ? settingsT('apprise.secretPreservePlaceholder')
      : (required ? settingsT('apprise.requiredFieldPlaceholder') : '');
    const examples = _appriseTokenFieldExamples(schema, key);
    return `<div class="form-group">
      <label class="form-label" for="apprise-url-token-${escAttr(key)}">
        ${escHtml(label)}${required ? ' *' : ''}${secret ? ` <span class="settings-muted">(${settingsT('apprise.secretField')})</span>` : ''}
      </label>
      <input class="form-input ${secret ? '' : 'mono'}" id="apprise-url-token-${escAttr(key)}" type="${secret ? 'password' : 'text'}" data-apprise-url-token="${escAttr(key)}" data-apprise-url-secret="${secret ? 'true' : 'false'}" data-apprise-url-required="${required ? 'true' : 'false'}" value="${escAttr(stored)}" placeholder="${escAttr(placeholder)}" autocomplete="off" oninput="onAppriseUrlFieldInput()">
      ${examples ? `<div class="form-help">${escHtml(examples)}</div>` : ''}
    </div>`;
  }).join('');
  return `<fieldset class="settings-fieldset apprise-url-builder" style="grid-column:1/-1">
    <legend>${settingsT('apprise.urlFields')}</legend>
    <div class="settings-body two-col">${templateSelect}${rows}</div>
    <div class="form-help">${settingsT('apprise.urlFieldsHint')}</div>
    <div class="apprise-url-preview"><span>${settingsT('apprise.urlPreview')}</span><code id="apprise-url-preview">${escHtml(_apprisePreviewUrlFromValues(schema, template, values))}</code></div>
  </fieldset>`;
}

function _apprisePreviewUrlFromValues(provider, template, values = {}) {
  const schema = String(provider || '').trim().toLowerCase();
  return String(template || '').replace(/\{([a-zA-Z0-9_.-]+)\}/g, (match, key) => {
    const tokenKey = String(key || '').toLowerCase();
    if (tokenKey === 'schema') return schema || 'apprise';
    const token = _appriseTokenMeta(schema, tokenKey);
    if (_appriseTokenIsSecret(token)) return values[tokenKey] ? '***' : `{${tokenKey}}`;
    return String(values[tokenKey] || match);
  });
}

function _appriseBuildUrlFromFields() {
  const provider = String(document.querySelector('[data-apprise-field="provider"]')?.value || 'apprise').trim().toLowerCase();
  const template = String(document.querySelector('[data-apprise-field="url_template"]')?.value || '').trim() || _appriseSelectedTemplate(provider);
  const inputs = Array.from(document.querySelectorAll('[data-apprise-url-token]'));
  if (!template || !inputs.length) return { url: '', fields: {}, complete: false, hasBuilder: false };
  const fields = {};
  let complete = true;
  inputs.forEach((input) => {
    const key = String(input.dataset.appriseUrlToken || '').toLowerCase();
    const value = String(input.value || '').trim();
    if (value) fields[key] = value;
    if (!value) complete = false;
  });
  if (!complete) return { url: '', fields, complete: false, hasBuilder: true };
  const url = template.replace(/\{([a-zA-Z0-9_.-]+)\}/g, (match, key) => {
    const tokenKey = String(key || '').toLowerCase();
    if (tokenKey === 'schema') return provider || 'apprise';
    return fields[tokenKey] || match;
  });
  return { url, fields, complete: true, hasBuilder: true };
}

function _updateAppriseUrlPreview() {
  const provider = String(document.querySelector('[data-apprise-field="provider"]')?.value || 'apprise').trim().toLowerCase();
  const template = String(document.querySelector('[data-apprise-field="url_template"]')?.value || '').trim() || _appriseSelectedTemplate(provider);
  const preview = document.getElementById('apprise-url-preview');
  if (!preview || !template) return;
  const values = {};
  Array.from(document.querySelectorAll('[data-apprise-url-token]')).forEach((input) => {
    const key = String(input.dataset.appriseUrlToken || '').toLowerCase();
    const value = String(input.value || '').trim();
    if (value) values[key] = value;
  });
  preview.textContent = _apprisePreviewUrlFromValues(provider, template, values);
}

function onAppriseUrlFieldInput() {
  _updateAppriseUrlPreview();
}

function _appriseCurrentUrlFieldValues() {
  const values = {};
  Array.from(document.querySelectorAll('[data-apprise-url-token]')).forEach((input) => {
    const key = String(input.dataset.appriseUrlToken || '').toLowerCase();
    const value = String(input.value || '').trim();
    if (key && value && input.dataset.appriseUrlSecret !== 'true') values[key] = value;
  });
  return values;
}

function onAppriseTemplateSelect(template) {
  const provider = String(document.querySelector('[data-apprise-field="provider"]')?.value || 'apprise').trim().toLowerCase();
  const urlConfig = document.getElementById('apprise-url-config');
  if (!urlConfig) return;
  const current = {
    ...(settingsState.appriseDraftProfile || {}),
    url_template: String(template || ''),
    url_fields: {
      ...(settingsState.appriseDraftProfile?.url_fields || {}),
      ..._appriseCurrentUrlFieldValues(),
    },
  };
  settingsState.appriseDraftProfile = current;
  urlConfig.innerHTML = _renderAppriseUrlConfig(provider, current, true);
  _updateAppriseUrlPreview();
}

function _renderAppriseTokenSummary(tokens, filterFn, labelKey) {
  const rows = (Array.isArray(tokens) ? tokens : []).filter(filterFn).slice(0, 8);
  if (!rows.length) return '';
  return `<span>${settingsT(labelKey)}: ${escHtml(rows.map((item) => item.name || item.key).join(', '))}</span>`;
}

function _renderAppriseUrlConfig(provider, current = {}, editing = false) {
  const builder = editing ? _renderAppriseUrlBuilder(provider, current) : '';
  const hasBuilder = !!builder;
  const urlLabel = hasBuilder ? settingsT('apprise.urlOverride') : (current.url_set ? settingsT('apprise.urlSet') : settingsT('apprise.url'));
  return `${builder}
    <div class="form-group" style="grid-column:1/-1">
      <label class="form-label" for="apprise-profile-url">${urlLabel}</label>
      <input class="form-input mono" id="apprise-profile-url" type="password" data-apprise-field="apprise_url" value="" placeholder="${escAttr(_appriseUrlPlaceholder(provider, current.url_set))}" autocomplete="off" ${editing ? '' : 'disabled'}>
      <div id="apprise-url-help">${_renderAppriseUrlHelp(provider, current.url_set)}</div>
    </div>`;
}

function _renderAppriseUrlHelp(provider, urlSet = false) {
  const schema = String(provider || '').trim().toLowerCase();
  const metadata = _appriseProviderMetadata(schema);
  const templates = _appriseProviderTemplates(schema);
  const tokens = Array.isArray(metadata?.tokens) ? metadata.tokens : [];
  const setupUrl = _appriseProviderSetupUrl(schema);
  const docLink = setupUrl
    ? `<a href="${escAttr(setupUrl)}" target="_blank" rel="noopener noreferrer">${settingsT('apprise.urlDocs')}</a>`
    : '';
  const templateRows = templates.length
    ? templates.slice(0, 5).map((template) => `<code>${escHtml(template)}</code>`).join('')
    : (schema && schema !== 'apprise' ? `<code>${escHtml(`${schema}://...`)}</code>` : '');
  return `<div class="apprise-url-help">
    <span>${settingsT(templates.length ? 'apprise.dynamicUrlHint' : 'apprise.genericUrlHint', { provider: schema || 'apprise' })}</span>
    ${templateRows}
    ${_renderAppriseTokenSummary(tokens, (item) => item.required, 'apprise.requiredTokens')}
    ${_renderAppriseTokenSummary(tokens, (item) => item.private, 'apprise.secretTokens')}
    ${docLink ? `<span>${docLink}</span>` : ''}
    ${urlSet ? `<span>${settingsT('apprise.urlSecretReplaceHint')}</span>` : `<span>${settingsT('apprise.urlHint')}</span>`}
  </div>`;
}

function _renderAppriseProfileSummary(profile, events) {
  const badges = [
    profile.enabled === false ? settingsT('apprise.disabled') : settingsT('apprise.enabled'),
    profile.default ? settingsT('apprise.defaultProfile') : '',
    profile.url_set ? settingsT('apprise.secretSet') : settingsT('apprise.secretMissing'),
  ].filter(Boolean);
  const eventLabels = notificationEventOptions()
    .filter(([key]) => (events || []).includes(key))
    .map(([, label]) => label);
  const priority = settingsT(`forms.ntfyPriority${String(profile.priority || 'default').charAt(0).toUpperCase()}${String(profile.priority || 'default').slice(1)}`);
  const providerLabel = _appriseProviderLabel(profile);
  const schema = _appriseProviderSchema(profile);
  const urlTemplate = String(profile.url_template || '').trim();
  return `<div class="apprise-profile-summary">
    <div class="apprise-profile-summary-main">
      <span class="apprise-provider-name">${escHtml(providerLabel)}</span>
      ${schema && schema !== providerLabel.toLowerCase() ? `<code>${escHtml(schema)}</code>` : ''}
      ${badges.map((badge) => `<em>${escHtml(badge)}</em>`).join('')}
    </div>
    <dl>
      <div><dt>${settingsT('forms.ntfyPriority')}</dt><dd>${escHtml(priority)}</dd></div>
      <div><dt>${settingsT('apprise.summaryDelivery')}</dt><dd>${escHtml(`${Number(profile.timeout_seconds || 15)}s / ${Number(profile.retry_policy?.attempts || 1)}x`)}</dd></div>
      ${urlTemplate ? `<div><dt>${settingsT('apprise.urlTemplate')}</dt><dd><code>${escHtml(urlTemplate)}</code></dd></div>` : ''}
      <div class="wide"><dt>${settingsT('forms.notifyEvents')}</dt><dd>${escHtml(eventLabels.join(', ') || settingsT('common.none'))}</dd></div>
    </dl>
  </div>`;
}

function renderSettingsAppriseProfiles() {
  const profiles = Array.isArray(settingsState.appriseProfiles) ? settingsState.appriseProfiles : [];
  const selected = _appriseSelectedProfile();
  const draft = settingsState.appriseDraftProfile;
  const editing = !!draft;
  const current = draft || selected;
  const hasCurrent = !!current;
  const provider = String(current?.provider || 'ntfy');
  const events = Array.isArray(current?.selected_events) ? current.selected_events : _appriseDefaultEvents();
  const priorities = ['default', 'min', 'low', 'high', 'urgent']
    .map((value) => `<option value="${value}" ${(current?.priority || 'default') === value ? 'selected' : ''}>${settingsT(`forms.ntfyPriority${value.charAt(0).toUpperCase()}${value.slice(1)}`)}</option>`)
    .join('');
  const profileRows = profiles.map((profile) => {
    const active = profile.id === settingsState.appriseSelectedProfileId && !editing;
    const badges = [
      profile.enabled === false ? settingsT('apprise.disabled') : settingsT('apprise.enabled'),
      profile.default ? settingsT('apprise.defaultProfile') : '',
      profile.url_set ? settingsT('apprise.secretSet') : settingsT('apprise.secretMissing'),
    ].filter(Boolean);
    return `<button type="button" class="settings-profile-list-item ${active ? 'active' : ''}" data-settings-action="apprise-profile-select" data-apprise-profile-id="${escAttr(profile.id)}">
      <span class="settings-profile-symbol notifications">${settingsMenuIcon('notifications')}</span>
      <span><strong>${escHtml(_appriseProfileName(profile))}</strong><small>${escHtml(_appriseProviderLabel(profile))}</small><em>${escHtml(badges.join(' / '))}</em></span>
      <b>›</b>
    </button>`;
  }).join('');
  const body = hasCurrent ? `
    <div class="settings-profile-manager apprise-profile-manager">
      <aside class="settings-profile-list">
        <header>
          <strong>${settingsT('apprise.savedProfiles')}</strong>
          <small>${settingsT('menu.profileCount', { count: profiles.length })}</small>
          <button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-add">${settingsT('apprise.addProfile')}</button>
        </header>
        <nav>${profileRows || `<div class="apprise-profile-empty">${settingsT('apprise.noProfiles')}</div>`}</nav>
      </aside>
      <section class="settings-profile-editor ${editing ? '' : 'readonly'}">
        <header>
          <div><small>${settingsT(editing ? 'apprise.editor' : 'menu.selectedProfile')}</small><h3>${escHtml(_appriseProfileName(current))}</h3><span>${escHtml(_appriseProviderLabel(current))}</span></div>
          <div class="apprise-editor-actions">
            ${editing ? '' : `<button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-duplicate">${settingsT('apprise.duplicate')}</button>`}
            ${editing ? '' : `<button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-edit">${settingsT('menu.edit')}</button>`}
          </div>
        </header>
        <div class="settings-profile-editor-body">
          <div id="apprise-profiles-msg" class="status-message hidden"></div>
          ${editing ? `<div class="settings-body two-col">
            <div class="form-group">
              <label class="form-label" for="apprise-profile-name">${settingsT('apprise.profileName')}</label>
              <input class="form-input" id="apprise-profile-name" type="text" data-apprise-field="name" value="${escAttr(current.name || '')}" ${editing ? '' : 'disabled'}>
            </div>
            <label class="form-checkbox-row">
              <input type="checkbox" data-apprise-field="enabled" ${current.enabled === false ? '' : 'checked'} ${editing ? '' : 'disabled'}>
              ${settingsT('apprise.enabled')}
            </label>
            <label class="form-checkbox-row">
              <input type="checkbox" data-apprise-field="default" ${current.default ? 'checked' : ''} ${editing ? '' : 'disabled'}>
              ${settingsT('apprise.defaultProfile')}
            </label>
            <div class="form-group">
              <label class="form-label" for="apprise-profile-provider">${settingsT('apprise.provider')}</label>
              <select class="form-select" id="apprise-profile-provider" data-apprise-field="provider" ${editing ? 'onchange="onAppriseProviderSelect(this.value)"' : 'disabled'}>
                ${_renderAppriseProviderOptions(provider)}
              </select>
              <div class="form-help">${settingsT('apprise.providerHint')}</div>
            </div>
            <div class="form-group">
              <label class="form-label" for="apprise-profile-priority">${settingsT('forms.ntfyPriority')}</label>
              <select class="form-select" id="apprise-profile-priority" data-apprise-field="priority" ${editing ? '' : 'disabled'}>${priorities}</select>
            </div>
            <div class="form-group">
              <label class="form-label" for="apprise-profile-timeout">${settingsT('forms.ntfyTimeout')}</label>
              <input class="form-input" id="apprise-profile-timeout" type="number" min="1" max="300" data-apprise-field="timeout_seconds" value="${escAttr(current.timeout_seconds || 15)}" ${editing ? '' : 'disabled'}>
            </div>
            <div class="form-group">
              <label class="form-label" for="apprise-profile-attempts">${settingsT('apprise.retryAttempts')}</label>
              <input class="form-input" id="apprise-profile-attempts" type="number" min="1" max="5" data-apprise-field="retry_attempts" value="${escAttr(current.retry_policy?.attempts || 1)}" ${editing ? '' : 'disabled'}>
            </div>
            <div class="form-group">
              <label class="form-label" for="apprise-profile-backoff">${settingsT('apprise.retryBackoff')}</label>
              <input class="form-input" id="apprise-profile-backoff" type="number" min="0" max="3600" data-apprise-field="retry_backoff_seconds" value="${escAttr(current.retry_policy?.backoff_seconds || 0)}" ${editing ? '' : 'disabled'}>
            </div>
            ${editing ? _renderAppriseProviderAdvanced(provider) : ''}
            <div id="apprise-url-config" style="grid-column:1/-1">${_renderAppriseUrlConfig(provider, current, editing)}</div>
            <fieldset class="settings-fieldset" style="grid-column:1/-1">
              <legend>${settingsT('forms.notifyEvents')}</legend>
              <div class="settings-body two-col">${_renderAppriseEvents(events)}</div>
            </fieldset>
          </div>` : _renderAppriseProfileSummary(current, events)}
        </div>
        <footer>
          ${editing ? `<button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-cancel">${settingsT('dialog.cancel')}</button>` : ''}
          ${editing ? `<button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-validate">${settingsT('apprise.validate')}</button>` : ''}
          <button type="button" class="btn btn-secondary btn-sm" data-settings-action="apprise-profile-test">${settingsT('apprise.sendTest')}</button>
          ${editing ? `<button type="button" class="btn btn-primary btn-sm" data-settings-action="apprise-profile-save">${settingsT('menu.saveProfile')}</button>` : ''}
          ${!editing && selected ? `<button type="button" class="btn btn-danger btn-sm" data-settings-action="apprise-profile-delete">${settingsT('common.remove')}</button>` : ''}
        </footer>
      </section>
    </div>` : `
      <div class="settings-body">
        <div id="apprise-profiles-msg" class="status-message hidden"></div>
        <div class="status-message empty-state">${settingsT('apprise.noProfiles')}</div>
        <button type="button" class="btn btn-primary btn-sm" data-settings-action="apprise-profile-add">${settingsT('apprise.addProfile')}</button>
      </div>`;
  return settingsCard(settingsT('apprise.title'),
    settingsMenuIcon('notifications'),
    `<div class="settings-body">
      ${body}
    </div>`);
}

function onAppriseProviderFilterChange(value) {
  settingsState.appriseProviderFilter = String(value || '');
  const providerInput = document.querySelector('[data-apprise-field="provider"]');
  const picker = document.getElementById('apprise-provider-picker');
  if (picker) picker.innerHTML = _renderAppriseProviderResults(String(providerInput?.value || 'ntfy'));
  const filter = document.getElementById('apprise-provider-filter');
  if (filter) {
    filter.focus();
    const len = filter.value.length;
    filter.setSelectionRange(len, len);
  }
}

async function maybeLoadAppriseProviders() {
  if (settingsState.appriseProvidersLoaded || settingsState.appriseProvidersLoading) return;
  settingsState.appriseProvidersLoading = true;
  _rerenderAppriseProviderPickerOnly();
  try {
    const res = await fetch('/api/notification-profiles/providers');
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) throw new Error(apiErrorMessage(data, res.status));
    settingsState.appriseProviders = Array.isArray(data.providers) ? data.providers : [];
    settingsState.appriseProvidersLoaded = true;
  } catch (err) {
    settingsState.appriseProviders = [];
    settingsState.appriseProvidersLoaded = true;
    showMsg('apprise-profiles-msg', 'error', settingsT('apprise.providersLoadFailed', { message: err.message }));
  } finally {
    settingsState.appriseProvidersLoading = false;
    _rerenderAppriseProviderPickerOnly();
  }
}

function _rerenderAppriseProviderPickerOnly() {
  const picker = document.getElementById('apprise-provider-picker');
  const provider = String(document.querySelector('[data-apprise-field="provider"]')?.value || 'ntfy');
  if (picker) picker.innerHTML = _renderAppriseProviderResults(provider);
  const urlConfig = document.getElementById('apprise-url-config');
  if (urlConfig && settingsState.appriseDraftProfile) {
    urlConfig.innerHTML = _renderAppriseUrlConfig(provider, settingsState.appriseDraftProfile, true);
    _updateAppriseUrlPreview();
  }
}

function _setAppriseDraftProvider(provider) {
  const value = String(provider || 'apprise').trim().toLowerCase();
  const input = document.querySelector('[data-apprise-field="provider"]');
  if (input) {
    if (input.tagName === 'SELECT' && !Array.from(input.options || []).some((option) => option.value === value)) {
      input.insertAdjacentHTML('afterbegin', `<option value="${escAttr(value)}">${escHtml(_appriseProviderLabel({ provider: value }))}</option>`);
    }
    input.value = value;
  }
  const urlInput = document.querySelector('[data-apprise-field="apprise_url"]');
  const urlSet = !!settingsState.appriseDraftProfile?.url_set;
  if (urlInput) urlInput.placeholder = _appriseUrlPlaceholder(value, urlSet);
  const urlHelp = document.getElementById('apprise-url-help');
  if (urlHelp) urlHelp.innerHTML = _renderAppriseUrlHelp(value, urlSet);
  const urlConfig = document.getElementById('apprise-url-config');
  if (urlConfig) urlConfig.innerHTML = _renderAppriseUrlConfig(value, settingsState.appriseDraftProfile || {}, true);
  _updateAppriseUrlPreview();
  _rerenderAppriseProviderPickerOnly();
}

function onAppriseProviderSelect(provider) {
  _setAppriseDraftProvider(provider);
}

function _appriseSelectedEventsFromDom() {
  const selected = Array.from(document.querySelectorAll('[data-apprise-event]'))
    .filter((el) => el.checked)
    .map((el) => el.getAttribute('data-apprise-event'))
    .filter(Boolean);
  return selected.length ? selected : _appriseDefaultEvents();
}

function _collectAppriseProfilePayload({ forDelivery = false } = {}) {
  const provider = String(document.querySelector('[data-apprise-field="provider"]')?.value || 'apprise').trim().toLowerCase();
  const explicitUrl = String(document.querySelector('[data-apprise-field="apprise_url"]')?.value || '').trim();
  const built = _appriseBuildUrlFromFields();
  const url = explicitUrl || built.url;
  const id = '';
  const payload = {
    id,
    profile_id: id || settingsState.appriseDraftProfile?.original_id || settingsState.appriseSelectedProfileId || '',
    name: String(document.querySelector('[data-apprise-field="name"]')?.value || '').trim(),
    enabled: !!document.querySelector('[data-apprise-field="enabled"]')?.checked,
    provider,
    selected_events: _appriseSelectedEventsFromDom(),
    timeout_seconds: Number(document.querySelector('[data-apprise-field="timeout_seconds"]')?.value || 15),
    retry_policy: {
      attempts: Number(document.querySelector('[data-apprise-field="retry_attempts"]')?.value || 1),
      backoff_seconds: Number(document.querySelector('[data-apprise-field="retry_backoff_seconds"]')?.value || 0),
    },
    priority: String(document.querySelector('[data-apprise-field="priority"]')?.value || 'default'),
    default: !!document.querySelector('[data-apprise-field="default"]')?.checked,
  };
  if (url) payload.apprise_url = url;
  if (built.hasBuilder) {
    payload.url_template = String(document.querySelector('[data-apprise-field="url_template"]')?.value || '').trim();
    payload.url_fields = Object.fromEntries(
      Object.entries(built.fields).filter(([key]) => {
        const input = Array.from(document.querySelectorAll('[data-apprise-url-token]'))
          .find((item) => String(item.dataset.appriseUrlToken || '').toLowerCase() === String(key).toLowerCase());
        return input?.dataset.appriseUrlSecret !== 'true';
      })
    );
  }
  if (forDelivery && !url && payload.profile_id) {
    delete payload.apprise_url;
  }
  return payload;
}

async function refreshAppriseProfiles({ keepSelection = true } = {}) {
  const res = await fetch('/api/notification-profiles');
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
  const profiles = Array.isArray(data.profiles) ? data.profiles : [];
  settingsState.appriseProfiles = profiles;
  if (!keepSelection || !profiles.some((profile) => profile.id === settingsState.appriseSelectedProfileId)) {
    settingsState.appriseSelectedProfileId = profiles[0]?.id || '';
  }
  settingsState.appriseDraftProfile = null;
  renderSettings(settingsState.data || {}, settingsState.systemHealth);
}

async function saveAppriseProfile() {
  const btn = document.querySelector('[data-settings-action="apprise-profile-save"]');
  btn?.classList.add('loading');
  hideEl('apprise-profiles-msg');
  try {
    const draft = settingsState.appriseDraftProfile || {};
    const payload = _collectAppriseProfilePayload();
    const isUpdate = !!draft.original_id;
    const res = await fetch('/api/notification-profiles', {
      method: isUpdate ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(isUpdate ? { ...payload, profile_id: draft.original_id, id: draft.original_id } : payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.appriseSelectedProfileId = data.profile?.id || payload.profile_id || payload.id || '';
    await refreshAppriseProfiles({ keepSelection: true });
    showMsg('apprise-profiles-msg', 'success', settingsT(isUpdate ? 'apprise.saved' : 'apprise.created'));
  } catch (err) {
    showMsg('apprise-profiles-msg', 'error', settingsT('apprise.saveFailed', { message: err.message }));
  } finally {
    btn?.classList.remove('loading');
  }
}

async function validateAppriseProfile() {
  const btn = document.querySelector('[data-settings-action="apprise-profile-validate"]');
  btn?.classList.add('loading');
  hideEl('apprise-profiles-msg');
  try {
    const payload = _collectAppriseProfilePayload({ forDelivery: true });
    const res = await fetch('/api/notification-profiles/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) throw new Error(apiMessage(data, settingsT('apprise.urlInvalid')));
    showMsg('apprise-profiles-msg', 'success', apiMessage(data, settingsT('apprise.urlValid')));
  } catch (err) {
    showMsg('apprise-profiles-msg', 'error', settingsT('apprise.validateFailed', { message: err.message }));
  } finally {
    btn?.classList.remove('loading');
  }
}

async function testAppriseProfile() {
  const btn = document.querySelector('[data-settings-action="apprise-profile-test"]');
  btn?.classList.add('loading');
  hideEl('apprise-profiles-msg');
  try {
    const payload = settingsState.appriseDraftProfile
      ? _collectAppriseProfilePayload({ forDelivery: true })
      : { profile_id: settingsState.appriseSelectedProfileId };
    const res = await fetch('/api/notification-profiles/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) throw new Error(apiMessage(data, settingsT('apprise.testFailedGeneric')));
    showMsg('apprise-profiles-msg', 'success', apiMessage(data, settingsT('apprise.testSent')));
  } catch (err) {
    showMsg('apprise-profiles-msg', 'error', settingsT('apprise.testFailed', { message: err.message }));
  } finally {
    btn?.classList.remove('loading');
  }
}

async function deleteAppriseProfile() {
  const profile = _appriseSelectedProfile();
  if (!profile?.id) return;
  const ok = await _openSettingsDialog({
    title: settingsT('apprise.deleteTitle'),
    message: settingsT('apprise.deleteMessage', { name: _appriseProfileName(profile) }),
    confirmText: settingsT('common.remove'),
    confirmClass: 'btn-danger',
  });
  if (!ok) return;
  hideEl('apprise-profiles-msg');
  try {
    const res = await fetch(`/api/notification-profiles?profile_id=${encodeURIComponent(profile.id)}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    await refreshAppriseProfiles({ keepSelection: false });
    showMsg('apprise-profiles-msg', 'success', settingsT('apprise.deleted'));
  } catch (err) {
    showMsg('apprise-profiles-msg', 'error', settingsT('apprise.deleteFailed', { message: err.message }));
  }
}

function renderSettingsPerRepoPassphrases(list) {
  const icon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="8" cy="15" r="4"/><path d="M12 15h8M16 12v6"/></svg>`;
  if (!list.length) {
    return `<div class="settings-section settings-passphrase-card">
      <div class="settings-section-header">${icon}<div><strong>${settingsT('forms.perRepoTitle')}</strong></div></div>
      <div class="settings-body"><p class="text-muted" style="font-size:13px;margin:0">${settingsT('forms.noPassphrases')}</p></div>
    </div>`;
  }
  const rows = list.map(p => {
    const d = new Date(p.mtime * 1000);
    const ts = d.toLocaleDateString(settingsLocale()) + ' ' + d.toLocaleTimeString(settingsLocale(), {hour:'2-digit', minute:'2-digit'});
    return `<tr>
      <td><code class="settings-passphrase-key">${p.type_id}</code></td>
      <td class="settings-passphrase-path">${p.path}</td>
      <td class="settings-passphrase-date">${ts}</td>
    </tr>`;
  }).join('');
  return `<div class="settings-section settings-passphrase-card">
    <div class="settings-section-header">${icon}<div><strong>${settingsT('forms.perRepoTitle')}</strong></div></div>
    <div class="settings-body">
      <div class="settings-passphrase-table-wrap">
        <table class="settings-table settings-passphrase-table">
          <thead><tr><th>${settingsT('forms.type')}</th><th>${settingsT('forms.flashPath')}</th><th>${settingsT('forms.changed')}</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

function renderSettingsStorageboxSetup(s, storageProfiles = []) {
  const profiles = normalizeStorageProfileRows(storageProfiles || []);
  if (!settingsState.storageboxProfileKey) {
    settingsState.storageboxProfileKey = String(s?.profile_key || profiles[0]?.key || '').trim().toLowerCase();
  }
  const selectedKey = settingsState.storageboxProfileKey;
  const profileOptions = profiles.map((p) => {
    const label = `${p.name} (${p.host})`;
    return `<option value="${escHtml(p.key)}" ${selectedKey === p.key ? 'selected' : ''}>${escHtml(label)}</option>`;
  }).join('');
  const pubBtnLabel = settingsState.storageboxPubVisible ? settingsT('forms.hidePublicKey') : settingsT('forms.showPublicKey');
  return settingsCard(settingsT('forms.sshSetup'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>`,
    `<div class="settings-body">
      <div class="form-group" style="margin-top:-2px;margin-bottom:8px">
        <label class="form-label">${settingsT('forms.profile')}</label>
        <select class="form-select" id="storagebox-profile-select" onchange="onStorageboxProfileSelectChanged()">
          ${profileOptions}
        </select>
      </div>
      <div class="smb-profile-checks ${settingsState.storageboxChecks ? '' : 'hidden'}" data-storagebox-checks style="margin-top:8px">
        ${settingsState.storageboxChecks ? _renderStorageboxChecksHtml(settingsState.storageboxChecks) : ''}
      </div>
      <div class="storagebox-actions">
        <button class="btn btn-secondary btn-sm" data-settings-action="storagebox-key-status">${settingsT('common.checkStatus')}</button>
        <button class="btn btn-secondary btn-sm" data-settings-action="storagebox-key-generate">${settingsT('forms.generateKey')}</button>
        <button class="btn btn-secondary btn-sm" data-settings-action="storagebox-key-public">${pubBtnLabel}</button>
        <button class="btn btn-secondary btn-sm" data-settings-action="storagebox-key-deploy">${settingsT('forms.deployKey')}</button>
        <button class="btn btn-secondary btn-sm" data-settings-action="storagebox-test">${settingsT('forms.testConnection')}</button>
      </div>
      <div id="storagebox-setup-msg" class="status-message hidden" style="margin-top:10px"></div>
      <textarea id="storagebox-public-key" class="form-input mono ${settingsState.storageboxPubVisible ? '' : 'hidden'}" style="margin-top:8px;min-height:84px" readonly></textarea>
    </div>`);
}

function renderSettingsRetention(rows) {
  const header = [settingsT('forms.type'), settingsT('forms.daily'), settingsT('forms.weekly'), settingsT('forms.monthly'), settingsT('forms.yearly')];
  const thead = `<tr>${header.map(h => `<th>${h}</th>`).join('')}</tr>`;
  const tbody = rows.map(r => `
    <tr>
      <td class="type-cell">${capitalize(r.type)}</td>
      ${['daily','weekly','monthly','yearly'].map(p => `
        <td><input class="retention-input form-input"
          type="number" min="0" max="999"
          data-key="RETENTION_${r.conf_prefix}_${p.toUpperCase()}"
          value="${escHtml(r[p])}"
          onchange="markSettingsDirty()">
        </td>`).join('')}
    </tr>`).join('');

  return settingsCard(settingsT('forms.retention'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    `<div class="settings-body" style="padding:0">
      <table class="retention-table" style="margin:0">
        <thead>${thead}</thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>`);
}

function renderSettingsCompression(rows) {
  const options = ['lz4','zstd,1','zstd,3','zstd,6','zstd,9','zstd,22','zlib','lzma','none'];
  const content = rows.map(r => `
    <div class="compression-row">
      <span class="compression-type">${capitalize(r.type)}</span>
      <select class="form-select" style="width:160px"
        data-key="${r.conf_key}" onchange="markSettingsDirty()">
        ${options.map(o => `<option value="${o}" ${r.value===o?'selected':''}>${o}</option>`).join('')}
      </select>
    </div>`).join('');

  return settingsCard(settingsT('forms.compression'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>`,
    `<div class="settings-body">${content}</div>`);
}

function renderSettingsRestoreTests(rt) {
  const levelOpts = ['1','2','3'].map(v =>
    `<option value="${v}" ${(rt.RESTORE_TEST_LEVEL||'2')===v?'selected':''}>${v}</option>`
  ).join('');
  const locOpts = ['local','usb','smb','storagebox','all'].map(v =>
    `<option value="${v}" ${(rt.RESTORE_TEST_LOCATION||'local')===v?'selected':''}>${locLabel(v)}</option>`
  ).join('');
  return settingsCard(settingsT('forms.restoreTests'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0 1 12 2.944a11.955 11.955 0 0 1-8.618 3.04A12.02 12.02 0 0 0 3 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>`,
    `<div class="settings-body">
      <h4 class="settings-subtitle">${settingsT('forms.basic')}</h4>
      <div class="two-col">
        <div class="form-group">
          <label class="form-label">${settingsT('forms.defaultTestLevel')}</label>
          <select class="form-select" data-key="RESTORE_TEST_LEVEL" onchange="markSettingsDirty()">${levelOpts}</select>
        </div>
        ${fnum('RESTORE_TEST_INTERVAL_DAYS', settingsT('forms.intervalDays'), rt.RESTORE_TEST_INTERVAL_DAYS || '30')}
        <div class="form-group">
          <label class="form-label">${settingsT('forms.defaultLocation')}</label>
          <select class="form-select" data-key="RESTORE_TEST_LOCATION" onchange="markSettingsDirty()">${locOpts}</select>
        </div>
      </div>

      <h4 class="settings-subtitle">${settingsT('forms.dryRunStrategy')}</h4>
      <div class="two-col">
        ${ftext('RESTORE_TEST_FORCE_CHUNK_TYPES', settingsT('forms.forceChunkTypes'), rt.RESTORE_TEST_FORCE_CHUNK_TYPES || 'vms,photos')}
        ${fnum('RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB', settingsT('forms.chunkFromSize'), rt.RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB || '500')}
      </div>
      <div class="muted" style="font-size:12px;margin-top:-6px">
        ${settingsT('forms.chunkHint')}
      </div>

      <h4 class="settings-subtitle">${settingsT('forms.limitsPerformance')}</h4>
      <div class="two-col">
        ${fnum('RESTORE_TEST_MIN_COVERAGE', settingsT('forms.minimumCoverage'), rt.RESTORE_TEST_MIN_COVERAGE || '5')}
        ${fnum('RESTORE_TEST_MAX_ENTRIES', settingsT('forms.maxEntries'), rt.RESTORE_TEST_MAX_ENTRIES || '1000')}
        ${fnum('RESTORE_TEST_SAMPLE_SIZE', settingsT('forms.sampleFiles'), rt.RESTORE_TEST_SAMPLE_SIZE || '5')}
        ${fnum('RESTORE_TEST_BORG_TIMEOUT', settingsT('forms.borgTimeout'), rt.RESTORE_TEST_BORG_TIMEOUT || '240')}
        ${fnum('RESTORE_TEST_DRY_RUN_TIMEOUT', settingsT('forms.dryRunTimeout'), rt.RESTORE_TEST_DRY_RUN_TIMEOUT || '0')}
        ${fnum('RESTORE_TEST_DRY_RUN_CHUNK_SIZE', settingsT('forms.chunkSize'), rt.RESTORE_TEST_DRY_RUN_CHUNK_SIZE || '100')}
        ${fnum('RESTORE_TEST_DRY_RUN_MAX_FILES', settingsT('forms.maxDryRunFiles'), rt.RESTORE_TEST_DRY_RUN_MAX_FILES || '1000')}
      </div>
      <label class="form-checkbox-row" style="margin-top:10px">
        <input type="checkbox" data-key="RESTORE_TEST_LEVEL3_LEGACY_SAMPLING"
          ${(rt.RESTORE_TEST_LEVEL3_LEGACY_SAMPLING || 'false') === 'true' ? 'checked' : ''}
          onchange="markSettingsDirty()">
        ${settingsT('forms.legacySampling')}
      </label>
    </div>`);
}

function renderSettingsRestore(rt, browse) {
  const active = settingsState.restoreSubtab === 'browse' ? 'browse' : 'tests';
  return `
    <div class="segmented-control" style="margin-bottom:12px">
      <button type="button" class="segmented-btn ${active === 'tests' ? 'active' : ''}" data-settings-action="restore-subtab" data-restore-subtab="tests">${settingsT('forms.restoreTestsTab')}</button>
      <button type="button" class="segmented-btn ${active === 'browse' ? 'active' : ''}" data-settings-action="restore-subtab" data-restore-subtab="browse">${settingsT('forms.browseRestoreTab')}</button>
    </div>
    <div class="${active === 'tests' ? '' : 'hidden'}">${renderSettingsRestoreTests(rt)}</div>
    <div class="${active === 'browse' ? '' : 'hidden'}">${renderSettingsBrowseRestore(browse)}</div>
  `;
}

function parseRestoreAllowedRoots(raw) {
  const seen = new Set();
  const roots = [];
  String(raw || '/mnt/user').split(',').forEach((part) => {
    const clean = normalizeRestoreRootInput(part);
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    roots.push(clean);
  });
  return roots.length ? roots : ['/mnt/user'];
}

function normalizeRestoreRootInput(raw) {
  let value = String(raw || '').trim();
  if (!value) return '';
  value = value.replace(/\/+$/, '') || '/';
  return value;
}

function readRestoreRootInput(raw) {
  return String(raw || '').trim();
}

function isSafeRestoreRoot(value) {
  const path = normalizeRestoreRootInput(value);
  if (!path || !path.startsWith('/')) return false;
  if (['/', '/mnt', '/mnt/disks', '/mnt/remotes', '/boot', '/etc', '/usr', '/var'].includes(path)) return false;
  if (path === '/mnt/user' || path.startsWith('/mnt/user/')) return true;
  if (path === '/mnt/data' || path.startsWith('/mnt/data/')) return true;
  if (/^\/mnt\/disk[0-9]+(?:\/.*)?$/.test(path)) return true;
  if (/^\/mnt\/disks\/[^/]+(?:\/.*)?$/.test(path)) return true;
  if (/^\/mnt\/remotes\/[^/]+(?:\/.*)?$/.test(path)) return true;
  return false;
}

function syncRestoreAllowedRootsHiddenInput({ normalizeInputs = false } = {}) {
  const box = document.getElementById('restore-allowed-roots-list');
  const hidden = document.getElementById('restore-allowed-roots-hidden');
  if (!box || !hidden) return;
  const roots = [];
  const seen = new Set();
  box.querySelectorAll('[data-restore-root-input]').forEach((input) => {
    const raw = readRestoreRootInput(input.value);
    const clean = normalizeRestoreRootInput(raw);
    if (normalizeInputs) input.value = clean;
    input.classList.toggle('input-error', !!clean && !isSafeRestoreRoot(clean));
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    roots.push(clean);
  });
  hidden.value = (roots.length ? roots : ['/mnt/user']).join(',');
}

function renderSettingsBrowseRestore(browse) {
  const roots = parseRestoreAllowedRoots(browse.RESTORE_ALLOWED_ROOTS || '/mnt/user');
  const rows = roots.map((root) => renderRestoreRootRow(root)).join('');
  return settingsCard(settingsT('forms.browseRestore'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 5h7l2 3h7v11H4z"/><path d="M9 14l2 2 4-4"/></svg>`,
    `<div class="settings-body">
      <div class="settings-info-box">
        <strong>${settingsT('forms.restoreAllowedRootsTitle')}</strong>
        <p>${settingsT('forms.restoreAllowedRootsIntro')}</p>
        <details>
          <summary>${settingsT('forms.restoreAllowedRootsHelpTitle')}</summary>
          <div class="settings-help-grid">
            <div><strong>${settingsT('forms.restoreAllowedRootsAllowed')}</strong><ul>
              <li>/mnt/user</li>
              <li>/mnt/data</li>
              <li>/mnt/disk1, /mnt/disk2, ...</li>
              <li>/mnt/disks/&lt;name&gt;</li>
              <li>/mnt/remotes/&lt;name&gt;</li>
            </ul></div>
            <div><strong>${settingsT('forms.restoreAllowedRootsBlocked')}</strong><ul>
              <li>/</li>
              <li>/mnt</li>
              <li>/mnt/disks</li>
              <li>/mnt/remotes</li>
              <li>/boot, /etc, /usr, /var</li>
            </ul></div>
          </div>
        </details>
      </div>
      <input type="hidden" id="restore-allowed-roots-hidden" data-key="RESTORE_ALLOWED_ROOTS" value="${escHtml(roots.join(','))}">
      <div id="restore-allowed-roots-list" class="settings-list-stack">
        ${rows}
      </div>
      <div id="restore-allowed-roots-msg" class="form-hint"></div>
      <button type="button" class="btn btn-secondary btn-sm" data-settings-action="restore-root-add">${settingsT('forms.restoreAllowedRootsAdd')}</button>
    </div>`);
}

function renderRestoreRootRow(root = '') {
  const safe = isSafeRestoreRoot(root);
  return `<div class="settings-inline-row restore-root-row">
    <input class="form-input mono ${safe ? '' : 'input-error'}" type="text" data-restore-root-input value="${escHtml(root)}" placeholder="/mnt/user" oninput="onRestoreAllowedRootsChanged(false)" onchange="onRestoreAllowedRootsChanged(true)">
    <button type="button" class="btn btn-secondary btn-sm" data-settings-action="restore-root-remove">${settingsT('common.remove')}</button>
  </div>`;
}

function onRestoreAllowedRootsChanged(normalizeInputs = false) {
  syncRestoreAllowedRootsHiddenInput({ normalizeInputs });
  const msg = document.getElementById('restore-allowed-roots-msg');
  const invalid = Array.from(document.querySelectorAll('[data-restore-root-input]'))
    .map((input) => normalizeRestoreRootInput(input.value))
    .filter((value) => value && !isSafeRestoreRoot(value));
  if (msg) {
    msg.textContent = invalid.length
      ? settingsT('forms.restoreAllowedRootsInvalid', { paths: invalid.join(', ') })
      : settingsT('forms.restoreAllowedRootsSavedAs', { roots: document.getElementById('restore-allowed-roots-hidden')?.value || '/mnt/user' });
  }
  markSettingsDirty();
}

function renderSettingsDockerVMs(docker, vms) {
  return settingsCard(settingsT('forms.dockerVms'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/></svg>`,
    `<div class="settings-body two-col">
      ${fnum('DOCKER_STOP_TIMEOUT', 'Docker Stop Timeout (s)', docker.DOCKER_STOP_TIMEOUT)}
      ${fnum('DOCKER_STOP_WAIT', settingsT('forms.dockerStopWait'), docker.DOCKER_STOP_WAIT)}
      ${fnum('DOCKER_START_WAIT', settingsT('forms.dockerStartWait'), docker.DOCKER_START_WAIT)}
      <div></div>
      ${fnum('VM_SHUTDOWN_TIMEOUT', 'VM Shutdown Timeout (s)', vms.VM_SHUTDOWN_TIMEOUT)}
      ${fnum('VM_SHUTDOWN_WARNING_MINUTES', settingsT('forms.vmWarning'), vms.VM_SHUTDOWN_WARNING_MINUTES)}
      ${fnum('VM_STARTUP_WAIT', settingsT('forms.vmStartWait'), vms.VM_STARTUP_WAIT)}
    </div>`);
}

function renderSettingsWeeklyReport(wr) {
  const enabled = (wr.WEEKLY_REPORT_ENABLED || 'false') === 'true';
  const dayOpts = [
    ['0',settingsT('forms.monday')], ['1',settingsT('forms.tuesday')], ['2',settingsT('forms.wednesday')], ['3',settingsT('forms.thursday')],
    ['4',settingsT('forms.friday')], ['5',settingsT('forms.saturday')], ['6',settingsT('forms.sunday')],
  ].map(([v, l]) => `<option value="${v}" ${(wr.WEEKLY_REPORT_DAY||'1')===v?'selected':''}>${l}</option>`).join('');

  return settingsCard(settingsT('forms.weeklyReport'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
    `<div class="settings-body">
      <div class="form-group" style="margin-bottom:16px">
        <label class="form-checkbox-row">
          <input type="checkbox" data-key="WEEKLY_REPORT_ENABLED" onchange="markSettingsDirty()" ${enabled?'checked':''}>
          ${settingsT('forms.enableReport')}
        </label>
      </div>
      <div class="two-col">
        <div class="form-group">
          <label class="form-label">${settingsT('forms.weekday')}</label>
          <select class="form-select" data-key="WEEKLY_REPORT_DAY" onchange="markSettingsDirty()">${dayOpts}</select>
        </div>
        <div class="form-group">
          <label class="form-label">${settingsT('forms.time')}</label>
          <input type="time" class="form-input" data-key="WEEKLY_REPORT_TIME" value="${escHtml(wr.WEEKLY_REPORT_TIME||'09:00')}" oninput="markSettingsDirty()">
        </div>
        <div class="form-group">
          <label class="form-label">${settingsT('forms.recipient')}</label>
          <input type="email" class="form-input" data-key="WEEKLY_REPORT_RECIPIENT" value="${escHtml(wr.WEEKLY_REPORT_RECIPIENT||'')}" placeholder="${settingsT('forms.defaultRecipient')}" oninput="markSettingsDirty()">
        </div>
      </div>
      <div id="weekly-report-message" class="status-message hidden" style="margin-top:12px"></div>
      <div style="margin-top:12px">
        <button class="btn btn-secondary" id="weekly-report-send-btn" data-settings-action="send-weekly-report">${settingsT('forms.sendNow')}</button>
      </div>
    </div>`);
}

async function onSettingsContentClick(event) {
  const tabBtn = event.target.closest('[data-settings-tab]');
  if (tabBtn) {
    if (settingsState.dirty) {
      const discard = await _openSettingsDialog({
        title: settingsT('forms.unsavedTitle'),
        message: settingsT('forms.tabUnsavedMessage'),
        confirmText: settingsT('forms.discardSwitch'),
        confirmClass: 'btn-danger',
      });
      if (!discard) return;
      await refreshSettings();
    }
    const tab = tabBtn.dataset.settingsTab || 'general';
    activateSettingsTab(tab);
    return;
  }
  const advancedTabBtn = event.target.closest('[data-settings-advanced-tab]');
  if (advancedTabBtn) {
    settingsState.advancedTab = advancedTabBtn.dataset.settingsAdvancedTab === 'passphrases' ? 'passphrases' : 'reminders';
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  const el = event.target.closest('[data-settings-action]');
  if (!el) return;
  const action = el.dataset.settingsAction || '';
  if (action === 'delete-backups-keep-latest') return deleteConfigBackupsKeepLatest();
  if (action === 'export-jobs') return exportJobsBundle();
  if (action === 'export-jobs-secure') return exportJobsBundleSecure();
  if (action === 'import-jobs-select-file') return importJobsPreviewSelectFile();
  if (action === 'import-jobs-secure-select-file') return importJobsSecurePreviewSelectFile();
  if (action === 'import-jobs-apply') return importJobsApplySelected();
  if (action === 'import-jobs-dry-run') return importJobsBundle(true);
  if (action === 'import-jobs') return importJobsBundle(false);
  if (action === 'export-secrets') return exportSecretsBackup();
  if (action === 'import-secrets-select-file') return importSecretsPreviewSelectFile();
  if (action === 'import-secrets-apply') return importSecretsApplySelected();
  if (action === 'import-secrets') return importSecretsBackup();
  if (action === 'export-profile-secrets') return exportProfileSecretsBackup();
  if (action === 'import-profile-secrets-select-file') return importProfileSecretsPreviewSelectFile();
  if (action === 'import-profile-secrets-apply') return importProfileSecretsApplySelected();
  if (action === 'export-support-bundle') return exportSupportBundle();
  if (action === 'factory-reset-start') return startFactoryReset();
  if (action === 'runtime-recovery-ack') return acknowledgeRuntimeRecoveryEntry(el);
  if (action === 'diff-config-backup') return diffSettingsConfigBackup(el.dataset.backupName || '');
  if (action === 'restore-config-backup') return restoreSettingsConfigBackup(el.dataset.backupName || '');
  if (action === 'delete-config-backup') return deleteSettingsConfigBackup(el.dataset.backupName || '');
  if (action === 'send-test-email') return sendTestEmail();
  if (action === 'apprise-profile-select') {
    if (settingsState.appriseDraftProfile) return;
    settingsState.appriseSelectedProfileId = el.dataset.appriseProfileId || '';
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'apprise-provider-select') {
    _setAppriseDraftProvider(el.dataset.appriseProvider || '');
    return;
  }
  if (action === 'apprise-profile-add') {
    settingsState.appriseDraftProfile = _appriseEmptyDraft();
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'apprise-profile-edit') {
    const profile = _appriseSelectedProfile();
    if (!profile) return;
    settingsState.appriseDraftProfile = _appriseDraftFromProfile(profile);
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'apprise-profile-duplicate') {
    const profile = _appriseSelectedProfile();
    if (!profile) return;
    settingsState.appriseDraftProfile = _appriseDraftFromProfile(profile, true);
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'apprise-profile-cancel') {
    settingsState.appriseDraftProfile = null;
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'apprise-profile-save') return saveAppriseProfile();
  if (action === 'apprise-profile-validate') return validateAppriseProfile();
  if (action === 'apprise-profile-test') return testAppriseProfile();
  if (action === 'apprise-profile-delete') return deleteAppriseProfile();
  if (action === 'send-weekly-report') return sendWeeklyReport();
  if (action === 'homepage-widget-rotate') return rotateHomepageWidgetToken();
  if (action === 'homepage-widget-revoke') return revokeHomepageWidgetToken();
  if (action === 'homepage-widget-copy-token') return copyHomepageWidgetField('homepage-widget-token');
  if (action === 'homepage-widget-copy-yaml') return copyHomepageWidgetField('homepage-widget-yaml');
  if (action === 'restore-subtab') {
    settingsState.restoreSubtab = el.dataset.restoreSubtab === 'browse' ? 'browse' : 'tests';
    renderSettings(settingsState.data || {}, settingsState.systemHealth);
    return;
  }
  if (action === 'restore-root-add') {
    const box = document.getElementById('restore-allowed-roots-list');
    if (box) {
      box.insertAdjacentHTML('beforeend', renderRestoreRootRow(''));
      const input = box.querySelector('.restore-root-row:last-child [data-restore-root-input]');
      if (input) input.focus();
    }
    onRestoreAllowedRootsChanged();
    return;
  }
  if (action === 'restore-root-remove') {
    const row = el.closest('.restore-root-row');
    if (row) row.remove();
    const box = document.getElementById('restore-allowed-roots-list');
    if (box && !box.querySelector('[data-restore-root-input]')) {
      box.insertAdjacentHTML('beforeend', renderRestoreRootRow('/mnt/user'));
    }
    onRestoreAllowedRootsChanged();
    return;
  }
  if (action === 'storagebox-key-status') return storageboxKeyStatus();
  if (action === 'storagebox-key-generate') return storageboxKeyGenerate();
  if (action === 'storagebox-key-public') return storageboxKeyPublic();
  if (action === 'storagebox-key-deploy') return storageboxKeyDeploy();
  if (action === 'storagebox-test') return storageboxTest();
  if (action === 'local-profile-add') {
    addLocalProfileRow();
    onLocalProfileInputChanged();
    settingsState.profileEditing = 'local';
    syncSettingsProfileManager('local', true);
    return;
  }
  if (action === 'local-profile-remove') {
    const row = event.target.closest('.local-profile-row');
    if (await blockProfileRemovalIfInUse(row, 'local')) return;
    row?.remove();
    onLocalProfileInputChanged();
    syncSettingsProfileManager('local');
    return;
  }
  if (action === 'usb-profile-add') {
    addUsbProfileRow();
    onUsbProfileInputChanged();
    settingsState.profileEditing = 'usb';
    syncSettingsProfileManager('usb', true);
    return;
  }
  if (action === 'usb-profile-check') return checkUsbProfilesStatus();
  if (action === 'usb-profile-remove') {
    const row = event.target.closest('.usb-profile-row');
    if (await blockProfileRemovalIfInUse(row, 'usb')) return;
    if (row) row.remove();
    onUsbProfileInputChanged();
    syncSettingsProfileManager('usb');
    return;
  }
  if (action === 'smb-profile-add') {
    addSmbProfileRow({ username: '', password_set: false });
    onSmbProfileInputChanged();
    settingsState.profileEditing = 'smb';
    syncSettingsProfileManager('smb', true);
    return;
  }
  if (action === 'smb-profile-check') return checkSmbProfilesStatus();
  if (action === 'smb-profile-status' || action === 'smb-profile-mount' || action === 'smb-profile-unmount') {
    const row = event.target.closest('.smb-profile-row');
    const smbAction = action === 'smb-profile-mount'
      ? 'mount'
      : (action === 'smb-profile-unmount' ? 'unmount' : 'status');
    return runSmbProfileAction(row, smbAction);
  }
  if (action === 'smb-profile-toggle-options') {
    const row = event.target.closest('.smb-profile-row');
    const opts = row?.querySelector('[data-smb-profile-optional]');
    if (opts) opts.classList.toggle('hidden');
    return;
  }
  if (action === 'smb-profile-remove') {
    const row = event.target.closest('.smb-profile-row');
    if (await blockProfileRemovalIfInUse(row, 'smb')) return;
    const profileKey = String(row?.dataset?.profileKey || '').trim().toLowerCase();
    if (!profileKey) return;
    const confirmedRemove = await _openSettingsDialog({
      title: settingsT('profiles.removeSmbTitle'),
      html: settingsT('profiles.removeSmbHtml'),
      input: {
        label: settingsT('profiles.confirmProfile', { name: profileKey }),
        value: '',
        placeholder: profileKey,
        validate: (v) => String(v || '').trim() === profileKey,
      },
      confirmText: settingsT('common.remove'),
      confirmClass: 'btn-danger',
      resolveValue: ({ modal }) => ({
        confirmed: true,
        unmountFirst: !!modal.querySelector('#smb-remove-unmount-first')?.checked,
        cleanupMountpoint: !!modal.querySelector('#smb-remove-mountpoint-cleanup')?.checked,
        cleanupSecret: !!modal.querySelector('#smb-remove-secret-cleanup')?.checked,
      }),
    });
    if (!confirmedRemove || !confirmedRemove.confirmed) return;
    settingsState.smbCleanupKeys = settingsState.smbCleanupKeys.filter((k) => k !== profileKey);
    settingsState.smbSecretCleanupKeys = settingsState.smbSecretCleanupKeys.filter((k) => k !== profileKey);
    if (confirmedRemove.cleanupMountpoint) settingsState.smbCleanupKeys.push(profileKey);
    if (confirmedRemove.cleanupSecret) settingsState.smbSecretCleanupKeys.push(profileKey);

    if (confirmedRemove.unmountFirst) {
      try {
        const res = await fetch('/api/storage/smb-action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile_key: profileKey, action: 'unmount' }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          throw new Error(apiErrorMessage(data, res.status));
        }
      } catch (err) {
        showMsg('smb-profiles-msg', 'error', settingsT('profiles.unmountRemoveFailed', { message: err.message }));
        return;
      }
    }

    if (row) row.remove();
    onSmbProfileInputChanged();
    syncSettingsProfileManager('smb');
    await saveSettings();
    return;
  }
  if (action === 'storage-profile-add') {
    addStorageProfileRow({ target_type: 'storagebox', port: '23', base_path: './backup' });
    onStorageProfileInputChanged();
    settingsState.profileEditing = 'storagebox';
    syncSettingsProfileManager('storagebox', true);
    return;
  }
  if (action === 'storage-profile-remove') {
    const row = event.target.closest('.storage-profile-row');
    if (await blockProfileRemovalIfInUse(row, 'storage')) return;
    if (row) row.remove();
    onStorageProfileInputChanged();
    syncSettingsProfileManager('storagebox');
    return;
  }
  if (action === 'user-create') return createUserFromSettings();
  if (action === 'user-save') {
    const row = event.target.closest('tr[data-user-name]');
    if (row) return updateUserFromRow(row);
    return;
  }
  if (action === 'user-reset-password') {
    const row = event.target.closest('tr[data-user-name]');
    if (row) return resetUserPasswordFromRow(row);
    return;
  }
  if (action === 'user-delete') {
    const row = event.target.closest('tr[data-user-name]');
    if (row) return deleteUserFromRow(row);
    return;
  }
  if (action === 'user-deactivate') {
    const row = event.target.closest('tr[data-user-name]');
    if (row) return deactivateUserFromRow(row);
    return;
  }
  if (action === 'user-change-own-password') return changeOwnPasswordFromSettings();
  if (action === 'user-logout-own-sessions') return logoutOwnSessionsFromSettings();
  if (action === 'user-logout-all-sessions') return logoutAllSessionsFromSettings();
}

async function createUserFromSettings() {
  const name = (document.getElementById('user-new-name')?.value || '').trim();
  const role = (document.getElementById('user-new-role')?.value || 'viewer').trim();
  const password = (document.getElementById('user-new-password')?.value || '');
  try {
    const res = await fetch('/api/auth/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, role, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.createSuccess', { name }));
    await refreshSettings();
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.createError', { message: err.message }));
  }
}

async function updateUserFromRow(row) {
  const username = String(row.dataset.userName || '').trim();
  const role = String(row.querySelector('[data-user-role]')?.value || '').trim();
  const enabled = !!row.querySelector('[data-user-enabled]')?.checked;
  try {
    const res = await fetch('/api/auth/users', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, role, enabled }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.updateSuccess', { name: username }));
    await refreshSettings();
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.updateError', { message: err.message }));
  }
}

async function resetUserPasswordFromRow(row) {
  const username = String(row.dataset.userName || '').trim();
  const value = await _openSettingsDialog({
    title: settingsT('users.resetPasswordTitle'),
    input: {
      label: settingsT('users.newPasswordFor', { name: username }),
      value: '',
      type: 'password',
      validate: (v) => String(v || '').length >= 12,
    },
    confirmText: settingsT('users.set'),
  });
  if (!value) return;
  try {
    const res = await fetch('/api/auth/users/password-reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: String(value) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.passwordUpdated', { name: username }));
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.passwordResetError', { message: err.message }));
  }
}

async function deleteUserFromRow(row) {
  const username = String(row.dataset.userName || '').trim();
  if (!username) return;
  const isEnabled = !!row.querySelector('[data-user-enabled]')?.checked;
  const ok = await _openSettingsDialog({
    title: settingsT('users.hardDeleteTitle'),
    html: settingsT('users.hardDeleteHtml', {
      active: isEnabled ? `<div class="modal-info-item warning" style="margin-top:8px">${settingsT('users.currentlyActive')}</div>` : '',
    }),
    input: {
      label: settingsT('users.confirmName', { name: username }),
      value: '',
      placeholder: username,
      validate: (v) => String(v || '').trim() === username,
    },
    confirmText: settingsT('users.delete'),
    confirmClass: 'btn-danger',
  });
  if (!ok) return;
  try {
    const res = await fetch('/api/auth/users', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.deleted', { name: username }));
    await refreshSettings();
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.deleteError', { message: err.message }));
  }
}

async function deactivateUserFromRow(row) {
  const username = String(row.dataset.userName || '').trim();
  const role = String(row.querySelector('[data-user-role]')?.value || '').trim();
  if (!username) return;
  try {
    const res = await fetch('/api/auth/users', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, role, enabled: false }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.deactivated', { name: username }));
    await refreshSettings();
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.deactivateError', { message: err.message }));
  }
}

async function changeOwnPasswordFromSettings() {
  const currentUser = String(settingsState.authStatus?.current_user || '').trim();
  const values = await _openSettingsDialog({
    title: settingsT('users.changePasswordTitle'),
    html: `
      <div class="form-group"><label class="form-label">${settingsT('users.currentPassword')}</label><input id="pwd-current" class="form-input" type="password"></div>
      <div class="form-group"><label class="form-label">${settingsT('users.newPassword')}</label><input id="pwd-new" class="form-input" type="password"></div>
      <div class="form-group"><label class="form-label">${settingsT('users.confirmNewPassword')}</label><input id="pwd-new-confirm" class="form-input" type="password"></div>
    `,
    confirmText: settingsT('users.changePassword'),
    resolveValue: ({ modal }) => ({
      current_password: String(modal.querySelector('#pwd-current')?.value || ''),
      new_password: String(modal.querySelector('#pwd-new')?.value || ''),
      new_password_confirm: String(modal.querySelector('#pwd-new-confirm')?.value || ''),
    }),
  });
  if (!values) return;
  try {
    const res = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('users-msg', 'success', settingsT('users.passwordChanged', { name: currentUser || settingsT('users.currentUser') }));
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.changePasswordError', { message: err.message }));
  }
}

async function logoutOwnSessionsFromSettings() {
  const ok = await _openSettingsDialog({
    title: settingsT('users.logoutOwnTitle'),
    message: settingsT('users.logoutOwnMessage'),
    confirmText: settingsT('users.logout'),
  });
  if (!ok) return;
  try {
    const res = await fetch('/api/auth/logout-all-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'current' }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    window.location.href = '/login';
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.logoutError', { message: err.message }));
  }
}

async function logoutAllSessionsFromSettings() {
  const ok = await _openSettingsDialog({
    title: settingsT('users.logoutAllTitle'),
    message: settingsT('users.logoutAllMessage'),
    confirmText: settingsT('users.logoutAllConfirm'),
    confirmClass: 'btn-danger',
  });
  if (!ok) return;
  try {
    const res = await fetch('/api/auth/logout-all-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'all' }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(apiErrorMessage(data, res.status));
    window.location.href = '/login';
  } catch (err) {
    showMsg('users-msg', 'error', settingsT('users.logoutAllError', { message: err.message }));
  }
}

async function checkUsbProfilesStatus() {
  const profiles = getUsbProfilesFromDom();
  const msgEl = document.getElementById('usb-profiles-msg');
  if (!profiles.length) {
    showMsg('usb-profiles-msg', 'warning', settingsT('profiles.noneToCheckUsb'));
    return;
  }
  try {
    const res = await fetch('/api/settings/usb-profiles-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profiles }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const rows = Array.isArray(data?.results) ? data.results : [];
    const rowEls = document.querySelectorAll('#usb-profiles-rows .usb-profile-row');
    rowEls.forEach((rowEl, idx) => {
      const stateEl = rowEl.querySelector('[data-usb-profile-state]');
      if (!stateEl) return;
      const r = rows[idx];
      if (!r) {
        stateEl.textContent = settingsT('profiles.unchecked');
        stateEl.className = 'usb-profile-state text-muted';
        return;
      }
      if (r.ok) {
        stateEl.textContent = 'OK';
        stateEl.className = 'usb-profile-state text-success';
      } else {
        stateEl.textContent = settingsT('profiles.checkErrorMessage', { message: settingsT('common.error') });
        stateEl.className = 'usb-profile-state text-danger';
      }
    });
    const okCount = rows.filter((r) => r.ok).length;
    const failCount = rows.length - okCount;
    showMsg('usb-profiles-msg', failCount ? 'warning' : 'success', settingsT('profiles.checkComplete', { ok: okCount, failed: failCount }));
  } catch (err) {
    if (msgEl) showMsg('usb-profiles-msg', 'error', settingsT('profiles.checkErrorMessage', { message: err.message }));
  }
}

async function checkSmbProfilesStatus() {
  const profiles = getSmbProfilesFromDom();
  const msgEl = document.getElementById('smb-profiles-msg');
  if (!profiles.length) {
    showMsg('smb-profiles-msg', 'warning', settingsT('profiles.noneToCheckSmb'));
    return;
  }
  try {
    const res = await fetch('/api/settings/smb-profiles-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profiles }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const rows = Array.isArray(data?.results) ? data.results : [];
    const rowEls = document.querySelectorAll('#smb-profiles-rows .smb-profile-row');
    rowEls.forEach((rowEl, idx) => {
      const r = rows[idx];
      if (!r) {
        const checksEl = rowEl.querySelector('[data-smb-profile-checks]');
        if (checksEl) {
          checksEl.classList.add('hidden');
          checksEl.innerHTML = '';
        }
        return;
      }
      const checksEl = rowEl.querySelector('[data-smb-profile-checks]');
      if (checksEl) {
        checksEl.classList.remove('hidden');
        checksEl.innerHTML = _renderSmbChecksHtml(r);
      }
    });
    const okCount = rows.filter((r) => r.ok).length;
    const failCount = rows.length - okCount;
    showMsg('smb-profiles-msg', failCount ? 'warning' : 'success', settingsT('profiles.checkComplete', { ok: okCount, failed: failCount }));
  } catch (err) {
    if (msgEl) showMsg('smb-profiles-msg', 'error', settingsT('profiles.checkErrorMessage', { message: err.message }));
  }
}

function refreshSelectedSmbProfileMountStatus(row = null) {
  const selectedRow = row || document.querySelector('#smb-profiles-rows .smb-profile-row:not(.hidden)');
  if (!selectedRow || settingsState.profileEditing === 'smb') return;
  const profileKey = String(selectedRow.dataset?.profileKey || '').trim().toLowerCase();
  if (!profileKey) return;
  runSmbProfileAction(selectedRow, 'status', { silent: true });
}

async function runSmbProfileAction(row, action, options = {}) {
  const profileKey = String(row?.dataset?.profileKey || '').trim().toLowerCase();
  if (!profileKey) {
    if (!options.silent) showMsg('smb-profiles-msg', 'warning', settingsT('profiles.saveBeforeMountAction'));
    return;
  }
  const statusEl = row.querySelector('[data-smb-profile-mount-status]');
  const requestId = `${profileKey}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  row.dataset.smbMountStatusRequest = requestId;
  if (action === 'status' && statusEl) {
    statusEl.textContent = settingsT('profiles.mountStatusChecking');
  }
  try {
    const res = await fetch('/api/storage/smb-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_key: profileKey, action }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(apiErrorMessage(data, res.status));
    const label = action === 'mount'
      ? settingsT('profiles.mountActionOk')
      : (action === 'unmount' ? settingsT('profiles.unmountActionOk') : settingsT('profiles.statusActionOk'));
    if (!options.silent) showMsg('smb-profiles-msg', 'success', apiMessage(data, label));
    const mounted = action === 'mount'
      ? true
      : (action === 'unmount' ? false : (typeof data.is_mounted === 'boolean' ? data.is_mounted : null));
    if (mounted !== null && row.isConnected && row.dataset.smbMountStatusRequest === requestId) {
      if (statusEl) statusEl.textContent = mounted ? settingsT('profiles.mounted') : settingsT('profiles.notMounted');
    }
  } catch (err) {
    if (statusEl && action === 'status' && row.isConnected && row.dataset.smbMountStatusRequest === requestId) {
      statusEl.textContent = settingsT('profiles.mountStatusUnknown');
    }
    if (!options.silent) showMsg('smb-profiles-msg', 'error', settingsT('profiles.mountActionFailed', { message: err.message }));
  }
}

async function _storageboxCall(action, body = {}) {
  const profileKey = String(settingsState.storageboxProfileKey || '').trim().toLowerCase();
  const payload = { ...body };
  if (profileKey) payload.profile_key = profileKey;
  const res = await fetch(`/api/storagebox/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
  return data;
}

function onStorageboxProfileSelectChanged() {
  const sel = document.getElementById('storagebox-profile-select');
  settingsState.storageboxProfileKey = String(sel?.value || '').trim().toLowerCase();
  settingsState.storageboxChecks = null;
  storageboxKeyStatus();
}

function _storageboxShow(msg, ok = true) {
  showMsg('storagebox-setup-msg', ok ? 'success' : 'error', msg);
}

function _storageboxRenderChecks() {
  const checks = document.querySelector('[data-storagebox-checks]');
  if (!checks) return;
  checks.innerHTML = settingsState.storageboxChecks ? _renderStorageboxChecksHtml(settingsState.storageboxChecks) : '';
  checks.classList.toggle('hidden', !settingsState.storageboxChecks);
}

async function storageboxKeyStatus() {
  hideEl('storagebox-setup-msg');
  try {
    const key = await _storageboxCall('key-status');
    settingsState.storageboxChecks = {
      rows: [
        { label: settingsT('storagebox.sshKeyPresent'), ok: !!key.key_exists, message: key.key_exists ? settingsT('storagebox.keyFileFound') : settingsT('storagebox.keyFileMissing') },
        { label: settingsT('storagebox.publicKeyPresent'), ok: !!key.pub_exists, message: key.pub_exists ? settingsT('storagebox.publicKeyFileFound') : settingsT('storagebox.publicKeyFileMissing') },
      ],
      details: key.key_path ? settingsT('storagebox.keyPath', { path: key.key_path }) : '',
    };
    settingsState.storageboxLastCheckAt = new Date().toISOString();
    _storageboxRenderChecks();
    _storageboxShow(settingsT('storagebox.statusUpdated'), true);
  } catch (e) {
    _storageboxShow(settingsT('error', { message: e.message }), false);
  }
}

async function storageboxKeyGenerate() {
  hideEl('storagebox-setup-msg');
  try {
    const d = await _storageboxCall('key-generate');
    const generated = d?.generated !== false;
    const type = generated ? 'success' : 'warning';
    showMsg('storagebox-setup-msg', type, apiMessage(d, settingsT('storagebox.keyGenerated')));
  } catch (e) { _storageboxShow(settingsT('error', { message: e.message }), false); }
}

async function storageboxKeyPublic() {
  hideEl('storagebox-setup-msg');
  try {
    if (settingsState.storageboxPubVisible) {
      settingsState.storageboxPubVisible = false;
      const taHide = document.getElementById('storagebox-public-key');
      if (taHide) taHide.classList.add('hidden');
      const btnHide = document.querySelector('[data-settings-action="storagebox-key-public"]');
      if (btnHide) btnHide.textContent = settingsT('forms.showPublicKey');
      _storageboxShow(settingsT('storagebox.publicKeyHidden'));
      return;
    }
    const d = await _storageboxCall('key-public');
    const ta = document.getElementById('storagebox-public-key');
    if (ta) {
      ta.value = d.public_key || '';
      ta.classList.remove('hidden');
    }
    settingsState.storageboxPubVisible = true;
    const btn = document.querySelector('[data-settings-action="storagebox-key-public"]');
    if (btn) btn.textContent = settingsT('forms.hidePublicKey');
    _storageboxShow(settingsT('storagebox.publicKeyLoaded', { path: d.pub_path || '' }));
  } catch (e) { _storageboxShow(settingsT('error', { message: e.message }), false); }
}

async function storageboxKeyDeploy() {
  try {
    hideEl('storagebox-setup-msg');
    const d = await _storageboxCall('deploy/start', {});
    openStorageDeployModal(d.session_id, d.target_type || 'generic');
  } catch (e) {
    _storageboxShow(settingsT('error', { message: e.message }), false);
  }
}

function closeStorageDeployModal() {
  const m = document.getElementById('storage-deploy-modal');
  if (m) m.classList.add('hidden');
  if (settingsState.storageDeployPollTimer) {
    clearInterval(settingsState.storageDeployPollTimer);
    settingsState.storageDeployPollTimer = null;
  }
}

async function openStorageDeployModal(sessionId, targetType) {
  settingsState.storageDeploySessionId = String(sessionId || '');
  const modal = document.getElementById('storage-deploy-modal');
  const out = document.getElementById('storage-deploy-output');
  const hint = document.getElementById('storage-deploy-target-hint');
  const input = document.getElementById('storage-deploy-input');
  const sendBtn = document.getElementById('storage-deploy-send-btn');
  const cancelBtn = document.getElementById('storage-deploy-cancel-btn');
  const okBtn = document.getElementById('storage-deploy-ok-btn');
  if (!modal || !out || !hint || !input || !sendBtn || !cancelBtn || !okBtn) return;

  out.textContent = '';
  hint.textContent = settingsT('deploy.session');
  input.value = '';
  sendBtn.disabled = false;
  cancelBtn.disabled = false;
  okBtn.disabled = false;
  modal.classList.remove('hidden');

  const poll = async () => {
    if (!settingsState.storageDeploySessionId) return;
    try {
      const st = await fetch(`/api/storagebox/deploy/state?session_id=${encodeURIComponent(settingsState.storageDeploySessionId)}`).then((r) => r.json());
      out.textContent = String(st.output || '');
      out.scrollTop = out.scrollHeight;
      const done = ['success', 'error', 'canceled', 'timeout'].includes(String(st.status || ''));
      if (done) {
        clearInterval(settingsState.storageDeployPollTimer);
        settingsState.storageDeployPollTimer = null;
        sendBtn.disabled = true;
        cancelBtn.disabled = true;
        const ok = st.status === 'success';
        _storageboxShow(ok ? settingsT('storagebox.deploySuccess') : settingsT('storagebox.deployEnded', { status: st.status }), ok);
      }
    } catch (_) {}
  };

  if (settingsState.storageDeployPollTimer) clearInterval(settingsState.storageDeployPollTimer);
  settingsState.storageDeployPollTimer = setInterval(poll, 700);
  poll();
}

async function storageDeploySendInput() {
  const sid = settingsState.storageDeploySessionId;
  const input = document.getElementById('storage-deploy-input');
  if (!sid || !input) return;
  const text = String(input.value || '');
  if (!text) return;
  try {
    const res = await _storageboxCall('deploy/input', { session_id: sid, text });
    if (res && res.sent === false) {
      _storageboxShow(settingsT('storagebox.inputNotSent', { status: res.status || settingsT('common.unknown') }), false);
      return;
    }
    input.value = '';
  } catch (e) {
    _storageboxShow(settingsT('error', { message: e.message }), false);
  }
}

async function storageDeployCancel() {
  const sid = settingsState.storageDeploySessionId;
  // UI sofort schließen, unabhängig vom Backend-Response
  closeStorageDeployModal();
  settingsState.storageDeploySessionId = '';
  if (!sid) return;
  try {
    await _storageboxCall('deploy/cancel', { session_id: sid });
  } catch (_) {}
}

async function storageboxTest() {
  hideEl('storagebox-setup-msg');
  try {
    const d = await _storageboxCall('test');
    settingsState.storageboxConnOk = !!d.success;
    settingsState.storageboxConnMsg = apiMessage(d, d.success ? settingsT('storagebox.sshReachable') : settingsT('storagebox.sshFailed'));
    const details = String(d.details || '').trim();
    settingsState.storageboxChecks = {
      rows: [
        { label: settingsT('storagebox.sshConnection'), ok: d?.steps?.ssh_ok === true, message: d?.steps?.ssh_ok === true ? settingsT('storagebox.sshReachable') : (d?.steps?.ssh_ok === false ? settingsT('storagebox.sshFailed') : settingsT('common.notChecked')) },
        { label: settingsT('storagebox.borgAvailable'), ok: d?.steps?.borg_ok === true, message: d?.steps?.borg_ok === true ? settingsT('storagebox.borgPresent') : (d?.steps?.borg_ok === false ? settingsT('storagebox.borgMissing') : settingsT('common.notChecked')) },
        { label: settingsT('storagebox.repoPathFound'), ok: d?.steps?.path_exists === true, message: d?.steps?.path_exists === true ? settingsT('storagebox.pathPresent') : (d?.steps?.path_exists === false ? settingsT('storagebox.pathMissing') : settingsT('common.notChecked')) },
        { label: settingsT('storagebox.writeTest'), ok: d?.steps?.path_writable === true, message: d?.steps?.path_writable === true ? settingsT('storagebox.writeSuccess') : (d?.steps?.path_writable === false ? settingsT('storagebox.writeFailed') : settingsT('common.notChecked')) },
      ],
      details: details || apiMessage(d, ''),
    };
    settingsState.storageboxLastCheckAt = new Date().toISOString();
    _storageboxRenderChecks();
    _storageboxShow(settingsState.storageboxConnMsg, !!d.success);
  } catch (e) { _storageboxShow(settingsT('error', { message: e.message }), false); }
}

async function sendWeeklyReport() {
  const btn = document.getElementById('weekly-report-send-btn');
  if (btn) btn.disabled = true;
  hideEl('weekly-report-message');
  const recipInput = document.querySelector('[data-key="WEEKLY_REPORT_RECIPIENT"]');
  const recipient = recipInput ? recipInput.value.trim() : '';
  try {
    const res = await fetch('/api/settings/weekly-report/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recipient }),
    });
    const data = await res.json();
    showMsg(
      'weekly-report-message',
      data.success ? 'success' : 'error',
      apiMessage(data, data.success ? settingsT('forms.sent') : settingsT('forms.error')),
    );
  } catch (err) {
    showMsg('weekly-report-message', 'error', settingsT('error', { message: err.message }));
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Settings-Formular-Hilfsfunktionen ─────────────────────────────────────────

function renderSettingsAbout() {
  const info = settingsState.appInfo || _normalizeAppInfo('', '', '', '', '');
  return settingsCard(settingsT('forms.about'),
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    `<div class="settings-body">
      <div class="about-grid">
        <div class="about-row"><span class="about-label">Version</span><span class="about-value" id="settings-about-version">${escHtml(info.version || '—')}</span></div>
        <div class="about-row"><span class="about-label">Borg Version</span><span class="about-value" id="settings-about-borg-version">${escHtml(info.borgVersion || '—')}</span></div>
        <div class="about-row"><span class="about-label">${settingsT('forms.author')}</span><span class="about-value">${escHtml(info.author)}</span></div>
        <div class="about-row"><span class="about-label">${settingsT('forms.contact')}</span><span class="about-value" id="settings-about-contact"><a href="mailto:${escAttr(info.contactEmail)}" class="about-link">${escHtml(info.contactEmail)}</a></span></div>
        <div class="about-row"><span class="about-label">${settingsT('forms.license')}</span><span class="about-value">MIT</span></div>
        <div class="about-row">
          <span class="about-label">${settingsT('forms.thirdPartyLicenses')}</span>
          <span class="about-value">
            BorgBackup (BSD-3-Clause),
            <a href="https://github.com/borgbackup/borg/blob/master/LICENSE" target="_blank" class="about-link">${settingsT('forms.originalLicense')}</a>
          </span>
        </div>
        <div class="about-row"><span class="about-label">${settingsT('forms.repository')}</span><span class="about-value" id="settings-about-repository"><a href="${escAttr(info.repositoryUrl)}" target="_blank" rel="noopener noreferrer" class="about-link">${APP_REPOSITORY_LABEL}</a></span></div>
      </div>
    </div>`);
}

function settingsCard(title, icon, body) {
  return `<div class="settings-section">
    <div class="settings-section-header">${icon}<div><strong>${title}</strong></div></div>
    ${body}
  </div>`;
}

function ftext(key, label, value) {
  return `<div class="form-group">
    <label class="form-label">${label}</label>
    <input class="form-input" type="text" data-key="${key}"
      value="${escHtml(value || '')}" onchange="markSettingsDirty()" oninput="markSettingsDirty()">
  </div>`;
}

function fpwd(key, label, value) {
  return `<div class="form-group">
    <label class="form-label">${label}</label>
    <input class="form-input" type="password" data-key="${key}"
      value="${escHtml(value || '')}" onchange="markSettingsDirty()" oninput="markSettingsDirty()">
  </div>`;
}

function fnum(key, label, value) {
  return `<div class="form-group">
    <label class="form-label">${label}</label>
    <input class="form-input" type="number" min="0" data-key="${key}"
      value="${escHtml(value || '')}" onchange="markSettingsDirty()" oninput="markSettingsDirty()">
  </div>`;
}

function fmono(key, label, value, placeholder = '') {
  return `<div class="form-group" style="grid-column:1/-1">
    <label class="form-label">${label}</label>
    <input class="form-input mono" type="text" data-key="${key}"
      value="${escHtml(value || '')}" placeholder="${escHtml(placeholder || '')}" onchange="markSettingsDirty()" oninput="markSettingsDirty()">
  </div>`;
}

function fmonoRO(label, value) {
  return `<div class="form-group" style="grid-column:1/-1">
    <label class="form-label">${label}</label>
    <input class="form-input mono" type="text" value="${escHtml(value || '')}" readonly>
  </div>`;
}

function markSettingsDirty() {
  settingsState.dirty = true;
  _updateUnsavedChangesUi();
}

function _updateUnsavedChangesUi() {
  const btn = document.getElementById('settings-save-btn');
  btn?.classList.toggle('btn-save-dirty', !!settingsState.dirty);
  const state = document.getElementById('settings-workspace-save-state');
  if (state) {
    state.className = `badge ${settingsState.dirty ? 'warning' : 'success'}`;
    state.textContent = settingsT(settingsState.dirty ? 'menu.unsaved' : 'menu.saved');
  }
}

async function canLeaveSettingsPage() {
  if (!settingsState.dirty) return true;
  const discard = await _openSettingsDialog({
    title: settingsT('forms.unsavedTitle'),
    message: settingsT('forms.leaveUnsavedMessage'),
    confirmText: settingsT('forms.leave'),
    confirmClass: 'btn-danger',
  });
  if (!discard) return false;
  await refreshSettings();
  return true;
}

window.canLeaveSettingsPage = canLeaveSettingsPage;

if (!window.__bbuiSettingsBeforeUnloadBound) {
  window.addEventListener('beforeunload', (event) => {
    if (!settingsState.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.__bbuiSettingsBeforeUnloadBound = true;
}

async function saveSettings() {
  syncUsbProfilesHiddenInput();
  syncSmbProfilesHiddenInput();
  syncStorageProfilesHiddenInput();
  syncRestoreAllowedRootsHiddenInput({ normalizeInputs: true });
  const updates = {};
  const profileUpdates = {};
  const activePanel = document.querySelector('#settings-content .settings-tab-panel:not(.hidden)');
  const activeTab = activePanel?.dataset?.settingsPanel || settingsState.activeTab || 'general';
  if (activeTab === 'local' && !validateLocalProfilesForSave()) return false;
  activePanel?.querySelectorAll('[data-key]').forEach(el => {
    const key = el.dataset.key;
    if (el.type === 'checkbox') {
      updates[key] = el.checked ? 'true' : 'false';
    } else {
      updates[key] = el.value;
    }
  });
  if (activeTab === 'local') profileUpdates.local = getLocalProfilesFromDom();
  if (activeTab === 'usb') profileUpdates.usb = getUsbProfilesFromDom();
  if (activeTab === 'smb') profileUpdates.smb = getSmbProfilesFromDom();
  if (activeTab === 'storagebox') profileUpdates.storagebox = getStorageProfilesFromDom();
  if (Object.prototype.hasOwnProperty.call(updates, 'GLOBAL_DATA_DIR') && !String(updates.GLOBAL_DATA_DIR || '').trim()) {
    showMsg('settings-message', 'error', settingsT('forms.dataDirRequired'));
    return false;
  }
  if (Object.prototype.hasOwnProperty.call(updates, 'GLOBAL_DATA_DIR')) {
    updates.GLOBAL_DATA_DIR = String(updates.GLOBAL_DATA_DIR).trim();
  }
  if (updates.UI_SESSION_TIMEOUT_MINUTES !== undefined) {
    const t = Number(updates.UI_SESSION_TIMEOUT_MINUTES);
    updates.UI_SESSION_TIMEOUT_MINUTES = String(Number.isFinite(t) ? Math.max(5, Math.floor(t)) : 30);
  }
  if (updates.RESTORE_ALLOWED_ROOTS !== undefined) {
    const invalid = String(updates.RESTORE_ALLOWED_ROOTS || '').split(',')
      .map((value) => normalizeRestoreRootInput(value))
      .filter((value) => value && !isSafeRestoreRoot(value));
    if (invalid.length) {
      showMsg('settings-message', 'error', settingsT('forms.restoreAllowedRootsInvalid', { paths: invalid.join(', ') }));
      return false;
    }
    updates.RESTORE_ALLOWED_ROOTS = parseRestoreAllowedRoots(updates.RESTORE_ALLOWED_ROOTS).join(',');
  }

  const btn = document.getElementById('settings-save-btn');
  if (btn) btn.classList.add('loading');
  hideEl('settings-message');

  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        updates,
        profile_updates: profileUpdates,
        smb_cleanup_keys: settingsState.smbCleanupKeys || [],
        smb_secret_cleanup_keys: settingsState.smbSecretCleanupKeys || [],
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    settingsState.dirty = false;
    _updateUnsavedChangesUi();
    const dd = data?.data_dirs;
    if (data?.data_dir_initialized && dd && dd.logs && dd.status && dd.restore_status) {
      showMsg(
        'settings-message',
        'success',
        settingsT('forms.savedDirectories', { directories: `${dd.logs}, ${dd.status}, ${dd.restore_status}` })
      );
    } else {
      showMsg('settings-message', 'success', settingsT('forms.saved'));
    }
    if (data?.smb_cleanup && Array.isArray(data.smb_cleanup.removed) && data.smb_cleanup.removed.length) {
      const removed = data.smb_cleanup.removed.map((r) => r.path).filter(Boolean).join(', ');
      showMsg('settings-message', 'success', settingsT('forms.savedMountsRemoved', { paths: removed }));
    }
    if (data?.smb_secret_cleanup && Array.isArray(data.smb_secret_cleanup.removed) && data.smb_secret_cleanup.removed.length) {
      const removedSecrets = data.smb_secret_cleanup.removed.map((r) => r.path).filter(Boolean).join(', ');
      showMsg('settings-message', 'success', settingsT('forms.credentialsRemoved', { paths: removedSecrets }));
    }
    settingsState.smbCleanupKeys = [];
    settingsState.smbSecretCleanupKeys = [];
    if (window.BBUI?.core?.invalidateSetupStatusCache) {
      window.BBUI.core.invalidateSetupStatusCache();
    }
    await refreshSettingsConfigBackups();
    await window.BBUI.core.updateDataDirWarning();
    if (!['usb', 'smb', 'storagebox'].includes(activeTab)) {
      await reloadSettingsDataAfterSave();
    }
    return true;
  } catch (err) {
    showMsg('settings-message', 'error', settingsT('error', { message: err.message }));
    return false;
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

async function reloadSettingsDataAfterSave(profileType = '') {
  try {
    const res = await fetch('/api/settings/basic');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    settingsState.data = data;
    settingsState.dirty = false;
    if (profileType) {
      const rows = Array.isArray(data?.[`${profileType === 'storagebox' ? 'storage' : profileType}_profiles`])
        ? data[`${profileType === 'storagebox' ? 'storage' : profileType}_profiles`]
        : [];
      const selected = settingsState.profileSelection[profileType] || '';
      if (!rows.some((row) => String(row?.key || '').trim() === selected)) {
        settingsState.profileSelection[profileType] = rows[0]?.key || '';
      }
    }
    renderSettings(settingsState.data, settingsState.systemHealth);
  } catch (_) {
    if (profileType) syncSettingsProfileManager(profileType);
  }
}

window.onAppriseProviderFilterChange = onAppriseProviderFilterChange;
window.onAppriseProviderSelect = onAppriseProviderSelect;
