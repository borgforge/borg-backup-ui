'use strict';
/** Managed database profiles and bounded test operations; password inputs are write-only and never populated from API responses. */
const databaseState = {profiles: [], unsupportedProfiles: [], containers: [], selected: '', operation: null, polling: false, available: {}, runs: [], runErrors: [], runFilter: 'all', runPage: 0, expandedRun: '', runsRequest: 0};
function dbT(key, params = {}) { return window.BBUI.components.i18n.t(`database.${key}`, params); }

/** Fetch a database API response and expose only localized server error codes. */
async function databaseRequest(path, body, method = 'POST') {
  const response = await fetch(`/api/settings/databases${path}`, body === undefined ? {} : {
    method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(apiErrorMessage(data, response.status));
    error.field = data.message_params?.field;
    error.code = data.code;
    throw error;
  }
  return data;
}

/** Load inventory before rendering; never replace a dirty draft during background polling. */
async function loadDatabaseSettings(selected = databaseState.selected) {
  const panel = document.getElementById('settings-databases-panel');
  if (!panel) return;
  try {
    const [data, inventory] = await Promise.all([
      databaseRequest('', undefined), fetch('/api/wizard/runtime-inventory').then(r => r.json()).catch(() => ({})),
    ]);
    databaseState.profiles = data.profiles;
    databaseState.unsupportedProfiles = data.unsupported_profiles || [];
    databaseState.containers = inventory.docker_containers || [];
    databaseState.selected = selected;
    renderDatabaseSettings();
    await loadDatabaseRuns();
    if (databaseState.operation) pollDatabaseOperation();
  } catch (e) { panel.textContent = e.message; }
}

/** Render escaped profile fields and attach event handlers without embedding user code. */
function renderDatabaseSettings() {
  const panel = document.getElementById('settings-databases-panel');
  if (!panel) return;
  const row = databaseState.profiles.find(p => p.id === databaseState.selected) || {
    engine:'mariadb', enabled:true, port:3306, timeout_seconds:1800, min_free_mib:1024, retention:'keep', databases:[], auth_mode:'managed', database_user:'root', staging_mount:'/mnt/cache', staging_dir:'/mnt/cache/borg-database-dumps',
  };
  const input = (key, type='text', extra='') => `<label class="form-label" for="db-${key}">${escHtml(dbT(key))}</label><input class="form-input" id="db-${key}" name="${key}" type="${type}" value="${escHtml(key === 'database_user' ? (row[key] || (row.engine === 'postgresql' ? 'postgres' : 'root')) : (row[key] ?? ''))}" ${extra}>`;
  const containers = [...new Set(databaseState.containers.map(p => typeof p === 'string' ? p : p.name || p.Name || '').filter(Boolean))].sort();
  if (row.container && !containers.includes(row.container)) containers.unshift(row.container);
  panel.innerHTML = `<div class="database-settings">
    <div class="database-intro"><span class="settings-menu-icon">${settingsMenuIcon('repository')}</span><div><h3>${escHtml(dbT('title'))}</h3><p>${escHtml(dbT('intro'))}</p></div></div>
    ${databaseState.unsupportedProfiles.length ? `<p class="status-message warning" id="db-unsupported">${escHtml(dbT('unsupportedProfiles'))}<br>${databaseState.unsupportedProfiles.map(p => `${escHtml(p.name)} (${escHtml(p.engine)})`).join(', ')}</p>` : ''}
    <div class="form-group"><label class="form-label" for="db-select">${escHtml(dbT('profile'))}</label>
    <select class="form-select" id="db-select"><option value="">${escHtml(dbT('new'))}</option>${databaseState.profiles.map(p => `<option value="${escHtml(p.id)}" ${p.id === row.id ? 'selected' : ''}>${escHtml(p.name)}</option>`).join('')}</select></div>
    <p class="profile-workflow-hint">${escHtml(dbT('workflowHint'))}</p>
    <form id="database-form" class="database-form">
    ${settingsCard(escHtml(dbT('connection')), settingsMenuIcon('repository'), `<div class="settings-body database-fields">
      <div class="form-group">${input('name','text','required maxlength="100"')}</div>
      <div class="form-group"><label class="form-label" for="db-engine">${escHtml(dbT('engine'))}</label><select class="form-select" id="db-engine" name="engine"><option value="mariadb">MariaDB</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option></select></div>
      <div class="form-group"><label class="form-label" for="db-container">${escHtml(dbT('container'))}</label><div><select class="form-select" id="db-container" name="container" required aria-describedby="db-container-hint"><option value="" disabled ${row.container ? '' : 'selected'}>${escHtml(dbT('chooseContainer'))}</option>${containers.map(name => `<option value="${escHtml(name)}" ${name === row.container ? 'selected' : ''}>${escHtml(name)}</option>`).join('')}</select><p class="form-help" id="db-container-hint">${escHtml(dbT(databaseState.containers.length ? 'containerHint' : 'containersEmpty'))}</p></div></div>
      <div class="form-group database-auth-field">${input('database_user','text','required autocomplete="username"')}</div>
      <div class="form-group database-auth-field"><label class="form-label" for="db-password">${escHtml(dbT('password'))}</label><input class="form-input" id="db-password" name="password" type="password" autocomplete="new-password" maxlength="4096" placeholder="${escHtml(dbT(row.credential_id || row.auth_mode === 'container' ? 'passwordKeep' : 'passwordEnter'))}"></div>
      <p class="form-help database-auth-field">${escHtml(dbT('credentials'))}</p>
      <details class="database-advanced"><summary>${escHtml(dbT('advancedConnection'))}</summary>
      ${row.auth_mode === 'container' ? `<p class="status-message info">${escHtml(dbT('legacyCredentials'))} <code>${escHtml(row.credential_file)}</code></p>` : ''}
        <div class="form-group">${input('port','number','required min="1" max="65535"')}</div>
        <div class="form-group">${input('execution_user')}</div>
      ${row.auth_mode === 'managed' && row.credential_id ? `<p class="form-help database-secret-file">${escHtml(dbT('secretFile'))}: <code>${escHtml('secrets/' + (/^[a-f0-9]{32}$/.test(row.credential_id) ? '.database-' : '') + row.credential_id + '.json')}</code></p>` : ''}
      </details>
    </div>`)}
    ${settingsCard(escHtml(dbT('databases')), settingsMenuIcon('backup'), `<div class="settings-body">
      <p class="form-help">${escHtml(dbT('selectionHint'))}</p><p class="form-help" id="db-engine-scope"></p>
      <button class="btn btn-secondary" type="submit" data-db-discover>${escHtml(dbT('discover'))}</button>
      <div id="db-databases" class="database-selection"></div>
      <div class="database-flags"><label id="db-globals-label"><input type="checkbox" id="db-globals" ${row.include_globals ? 'checked' : ''}> ${escHtml(dbT('globals'))}</label></div>
      <p id="db-globals-hint" class="form-help">${escHtml(dbT('globalsHint'))}</p><p class="form-help">${escHtml(dbT('scope'))}</p>
    </div>`)}
    ${settingsCard(escHtml(dbT('storageTitle')), settingsMenuIcon('backup'), `<div class="settings-body database-fields">
      <p class="form-help">${escHtml(dbT('storageHint'))}</p>
      <div class="form-group">${input('staging_mount','text','required placeholder="/mnt/cache"')}</div>
      <div class="form-group">${input('staging_dir','text','required placeholder="/mnt/cache/borg-database-dumps"')}</div>
      <div class="form-group"><label class="form-label" for="db-retention">${escHtml(dbT('retention'))}</label><select class="form-select" id="db-retention" name="retention"><option value="keep">${escHtml(dbT('keep'))}</option><option value="after_archive">${escHtml(dbT('after_archive'))}</option></select></div>
      <details class="database-advanced"><summary>${escHtml(dbT('limits'))}</summary>
        <div class="form-group">${input('min_free_mib','number','required min="1" max="104857600"')}</div>
        <div class="form-group">${input('timeout_seconds','number','required min="1" max="86400"')}</div>
      </details>
    </div>`)}
      <p id="db-save-feedback" data-feedback-inline class="status-message hidden" role="status" aria-live="polite"></p>
      <div class="database-footer profile-save-bar"><span data-profile-save-status></span><label><input type="checkbox" id="db-enabled" ${row.enabled ? 'checked' : ''}> ${escHtml(dbT('enabled'))}</label>
      <div class="job-script-actions"><button class="btn btn-primary" type="submit">${escHtml(dbT('save'))}</button>
        <button class="btn btn-danger" id="db-delete" type="button" ${row.id ? '' : 'disabled'}>${escHtml(dbT('delete'))}</button></div></div>
    </form>
    ${settingsCard(escHtml(dbT('actions')), settingsMenuIcon('restore'), `<div class="settings-body">
      <p class="form-help">${escHtml(dbT('savedActions'))}</p><div class="job-script-actions">${['check','dump','reconcile'].map(action => `<button class="btn btn-secondary" type="button" data-db-action="${action}" ${row.id && (row.enabled || action === 'reconcile') ? '' : 'disabled'}>${escHtml(dbT(action))}</button>`).join('')}
      <button class="btn btn-secondary" id="db-cancel" ${databaseState.operation ? '' : 'disabled'}>${escHtml(dbT('cancel'))}</button></div>
      <div id="db-progress" class="database-progress hidden" aria-live="off"></div>
      <p id="db-result" class="status-message hidden" role="status" aria-live="polite"></p>
    </div>`)}
    ${settingsCard(escHtml(dbT('runs')), settingsMenuIcon('backup'), `<div class="settings-body database-runs-body"><p class="form-help">${escHtml(dbT('runsHint'))}</p><p class="form-help">${escHtml(dbT('runsScope'))}</p><div class="database-runs-toolbar"><div id="db-run-filters" class="database-run-filters" role="group" aria-label="${escHtml(dbT('runFilters'))}"></div><button type="button" class="btn btn-secondary" id="db-refresh">${escHtml(dbT('refresh'))}</button></div><div id="db-runs"></div><p class="form-help">${escHtml(dbT('housekeeping'))}</p></div>`)}
  </div>`;
  document.getElementById('db-engine').value = row.engine;
  document.getElementById('db-retention').value = row.retention;
  settingsState.databaseDirty = false;
  const form = document.getElementById('database-form');
  const updateDraft = () => {
    settingsState.databaseDirty = settingsFormSignature(form) !== databaseState.savedDraft;
    hideEl('db-save-feedback');
    clearDatabaseFieldErrors();
    _updateUnsavedChangesUi();
  };
  form.addEventListener('input', updateDraft);
  form.addEventListener('change', updateDraft);
  form.addEventListener('invalid', event => {
    event.preventDefault();
    if (event.target === form.querySelector(':invalid')) showDatabaseSaveError({field:event.target.id.replace(/^db-/, ''), message:event.target.validationMessage});
  }, true);
  databaseEngineFields(row.engine);
  renderDatabaseChoices(databaseState.available[row.id] || [], row.databases);
  document.getElementById('db-engine').addEventListener('change', e => {
    databaseEngineFields(e.target.value);
    document.getElementById('db-port').value = {mariadb:3306,mysql:3306,postgresql:5432}[e.target.value];
    renderDatabaseChoices([], []);
    document.getElementById('db-globals').checked = false;
    document.getElementById('db-database_user').value = e.target.value === 'postgresql' ? 'postgres' : 'root';
  });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (settingsState.profileSaving) return;
    const body = Object.fromEntries(new FormData(form));
    if (row.id) body.id = row.id;
    body.databases = [...form.querySelectorAll('#db-databases input:checked')].map(el => el.value);
    body.auth_mode = row.auth_mode === 'container' && !body.password ? 'container' : 'managed';
    if (body.engine !== row.engine && body.auth_mode === 'container') body.auth_mode = 'managed';
    if (body.auth_mode === 'container') body.credential_file = row.credential_file;
    if (!body.password && row.credential_id) delete body.password;
    const discover = e.submitter?.hasAttribute('data-db-discover');
    for (const k of ['port','timeout_seconds','min_free_mib']) body[k] = Number(body[k]);
    body.enabled = document.getElementById('db-enabled').checked;
    body.include_globals = document.getElementById('db-globals').checked;
    const controls = [...panel.querySelectorAll('input, select, button')].map(el => [el, el.disabled]);
    controls.forEach(([el]) => { el.disabled = true; });
    settingsState.profileSaving = true;
    _updateUnsavedChangesUi();
    clearDatabaseFieldErrors();
    hideEl('db-save-feedback');
    let savedProfile = null, saveError = null;
    try {
      const data = await databaseRequest('', body);
      // The acknowledged profile is authoritative; a later inventory GET must
      // not turn a successful save into a failed save or overwrite the draft.
      databaseState.profiles = [...databaseState.profiles.filter(p => p.id !== data.profile.id), data.profile];
      databaseState.selected = data.profile.id;
      settingsState.databaseDirty = false;
      renderDatabaseSettings();
      void loadDatabaseRuns();
      showMsg('db-save-feedback', 'success', dbT(discover ? 'connectionSaved' : 'saved'));
      savedProfile = data.profile.id;
    } catch (err) { saveError = err; }
    finally {
      settingsState.profileSaving = false;
      controls.forEach(([el, disabled]) => { el.disabled = disabled; });
      _updateUnsavedChangesUi();
    }
    if (saveError) showDatabaseSaveError(saveError);
    if (discover && savedProfile) await startDatabaseAction(savedProfile, 'discover');
  });
  document.getElementById('db-select').addEventListener('change', async e => {
    const selected = e.target.value;
    if (settingsState.databaseDirty) {
      e.target.value = databaseState.selected;
      if (!await _openSettingsDialog({title:dbT('discardTitle'), message:dbT('discard'), confirmText:dbT('discardAction'), confirmClass:'btn-danger'})) return;
    }
    databaseState.selected = selected; renderDatabaseSettings(); loadDatabaseRuns();
  });
  document.getElementById('db-delete').addEventListener('click', async () => {
    if (!await _openSettingsDialog({dialogClass:'database-confirmation', title:dbT('delete'), message:dbT('confirmDelete') + '\n\n' + row.name, confirmText:dbT('delete'), confirmClass:'btn-danger'})) return;
    try { await databaseRequest(`?id=${encodeURIComponent(row.id)}`, {}, 'DELETE'); await loadDatabaseSettings(''); }
    catch (e) { databaseFeedback(e.message); }
  });
  panel.querySelectorAll('[data-db-action]').forEach(button => button.addEventListener('click', () => startDatabaseAction(row.id, button.dataset.dbAction)));
  document.getElementById('db-cancel').addEventListener('click', async () => {
    try { if (databaseState.operation) await databaseRequest('/cancel', {id:databaseState.operation}); databaseFeedback(dbT('cancelling')); }
    catch (e) { databaseFeedback(e.message); }
  });
  document.getElementById('db-refresh').addEventListener('click', loadDatabaseRuns);
  databaseState.savedDraft = settingsFormSignature(form);
  _updateUnsavedChangesUi();
}
/** Remove field diagnostics without touching entered values or unrelated help. */
function clearDatabaseFieldErrors() {
  const form = document.getElementById('database-form');
  form?.querySelectorAll('.database-field-error').forEach(node => node.remove());
  form?.querySelectorAll('[aria-invalid="true"]').forEach(node => {
    node.removeAttribute('aria-invalid');
    node.classList.remove('input-error');
    const described = (node.getAttribute('aria-describedby') || '').split(' ').filter(id => id && !id.endsWith('-validation-error'));
    if (described.length) node.setAttribute('aria-describedby', described.join(' '));
    else node.removeAttribute('aria-describedby');
  });
}

/** Show a persistent save error at its field and reveal collapsed inputs before focus. */
function showDatabaseSaveError(error) {
  clearDatabaseFieldErrors();
  const aliases = {include_globals:'globals', databases:'databases'};
  const field = typeof error.field === 'string' ? error.field : '';
  const target = document.getElementById('db-' + (aliases[field] || field));
  const form = document.getElementById('database-form');
  if (!target || !form?.contains(target)) { showMsg('db-save-feedback', 'error', error.message); return; }
  const control = target.matches('input, select, textarea') ? target : target.querySelector('input') || target;
  const message = document.createElement('span');
  message.id = control.id ? control.id + '-validation-error' : 'db-selection-validation-error';
  message.className = 'database-field-error';
  const hint = dbT('fieldHints.' + field);
  message.textContent = error.code === 'database_invalid_profile' && hint !== 'database.fieldHints.' + field ? hint : error.message;
  message.setAttribute('role', 'alert');
  control.setAttribute('aria-invalid', 'true');
  control.setAttribute('aria-describedby', [control.getAttribute('aria-describedby'), message.id].filter(Boolean).join(' '));
  control.classList.add('input-error');
  (target.closest('.form-group') || target.closest('label') || target).appendChild(message);
  for (let parent = control.parentElement; parent && parent !== form; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
  if (!control.matches('input, select, textarea')) control.tabIndex = -1;
  control.focus({preventScroll:true});
  control.scrollIntoView({block:'center'});
  const label = dbT(field === 'include_globals' ? 'globals' : field);
  showMsg('db-save-feedback', 'error', dbT('correctField', {field:label}));
}

/** Show only applicable engine options, retaining shared profile fields. */
function databaseEngineFields(engine) {
  const pg = engine === 'postgresql';
  document.getElementById('db-globals-label').classList.toggle('hidden', !pg);
  document.getElementById('db-globals-hint').classList.toggle('hidden', !pg);
  document.getElementById('db-engine-scope').textContent = ['mariadb','mysql'].includes(engine) ? dbT('mysqlScope') : '';

}
function databaseFeedback(message) {
  const node = document.getElementById('db-result');
  if (node) { node.textContent = message; node.classList.remove('hidden'); }
}

/** Render discovered names and retain explicit selections even when no longer discoverable. */
function renderDatabaseChoices(available, selected) {
  const node = document.getElementById('db-databases');
  if (!node) return;
  const names = [...new Set([...available, ...selected])].sort();
  node.innerHTML = names.map(name => `<label class="database-choice"><input type="checkbox" value="${escHtml(name)}" ${selected.includes(name) ? 'checked' : ''}><span>${escHtml(name)}</span></label>`).join('') || `<p class="form-help">${escHtml(dbT('notLoaded'))}</p>`;
}

/** Start only saved profile operations; local cleanup always requires an explicit confirmation. */
async function startDatabaseAction(profile_id, action, directory) {
  if (databaseState.operation) { databaseFeedback(dbT('running')); return; }
  if (settingsState.databaseDirty) { databaseFeedback(dbT('saveFirst')); return; }
  if (action === 'cleanup' && !await _openSettingsDialog({dialogClass:'database-confirmation', title:dbT('cleanup'), message:dbT('confirmCleanup') + '\n\n' + directory, confirmText:dbT('cleanup'), confirmClass:'btn-danger'})) return;
  renderDatabaseProgress({status:'running', action, started_at:new Date().toISOString(), progress:{phase:'preparing'}});
  try {
    const result = await databaseRequest('/action', {profile_id, action, directory});
    databaseState.operation = result.id;
    document.getElementById('db-cancel').disabled = false;
    pollDatabaseOperation();
  } catch (e) { renderDatabaseProgress({status:'failed'}); databaseFeedback(e.message); }
}

/** Render live test-export measurements without estimating unknown totals. */
function renderDatabaseProgress(status) {
  const node = document.getElementById('db-progress');
  if (!node) return;
  node.classList.toggle('hidden', status.status !== 'running' || status.action !== 'dump');
  if (status.status !== 'running' || status.action !== 'dump') return;
  const progress = status.progress || {};
  const phase = ['preparing','checking','exporting','globals','finalizing','completed'].includes(progress.phase) ? progress.phase : 'preparing';
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(status.started_at || '')) / 1000)) || 0;
  const elapsed = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  const database = progress.database ? `${progress.database} (${progress.database_index}/${progress.databases_total})` : status.profile_name || '';
  node.innerHTML = `<strong>${escHtml(dbT('progress.' + phase))}${database ? ' · ' + escHtml(database) : ''}</strong>
    <progress aria-label="${escHtml(dbT('progress.running'))}"></progress>
    <div class="database-progress-values"><span>${escHtml(dbT('progress.elapsed', {value:elapsed}))}</span>
    <span>${escHtml(dbT('progress.processed', {value:settingsFmtBytes(progress.processed_bytes || 0)}))}</span>
    <span>${escHtml(dbT('progress.written', {value:settingsFmtBytes(progress.written_bytes || 0)}))}</span></div>`;
}

/** Poll the asynchronous operation, stopping after completion or an HTTP error. */
async function pollDatabaseOperation() {
  if (databaseState.polling || !databaseState.operation) return;
  databaseState.polling = true;
  try {
    while (databaseState.operation) {
      const status = await databaseRequest(`/status?id=${encodeURIComponent(databaseState.operation)}`, undefined);
      renderDatabaseProgress(status);
      const error = status.error_code ? apiErrorMessage({code:status.error_code}) : '';
      const locations = (status.results || []).map(r => r.directory).join(', ');
      const completed = {check:'checkCompleted', dump:'dumpCompleted', cleanup:'cleanupCompleted', reconcile:'reconcileCompleted'};
      const message = status.status === 'completed' && completed[status.action] ? dbT(completed[status.action]) : dbT(status.status);
      databaseFeedback([message, error, locations].filter(Boolean).join(' · '));
      if (status.status !== 'running') {
        if (status.status === 'completed' && Array.isArray(status.databases) && status.profile_id === databaseState.selected) {
          databaseState.available[status.profile_id] = status.databases;
          const selected = [...document.querySelectorAll('#db-databases input:checked')].map(el => el.value);
          renderDatabaseChoices(status.databases, selected);
          databaseFeedback(dbT('discovered', {count: status.databases.length}));
        }
        databaseState.operation = null; await loadDatabaseRuns(); break;
      }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  } catch (e) { renderDatabaseProgress({status:'failed'}); databaseFeedback(e.message); }
  finally { databaseState.polling = false; const b = document.getElementById('db-cancel'); if (b) b.disabled = !databaseState.operation; }
}

/** Load retained exports without allowing a stale request to overwrite a newer view. */
async function loadDatabaseRuns() {
  const node = document.getElementById('db-runs'); if (!node) return;
  const request = ++databaseState.runsRequest;
  try {
    const data = await databaseRequest('/runs', undefined);
    if (request !== databaseState.runsRequest || node !== document.getElementById('db-runs')) return;
    const timestamp = value => { const n = Date.parse(value || ''); return Number.isNaN(n) ? -Infinity : n; };
    databaseState.runs = [...data.runs].sort((a,b) => timestamp(b.started_at) - timestamp(a.started_at));
    databaseState.runErrors = data.errors || [];
    renderDatabaseRuns();
  } catch (e) {
    if (request !== databaseState.runsRequest || node !== document.getElementById('db-runs')) return;
    node.textContent = e.message;
    document.getElementById('db-run-filters')?.replaceChildren();
  }
}

/** Return only recognized origin values; older API rows stay explicitly unattributed. */
function databaseRunOrigin(run) {
  return ['job','manual'].includes(run.origin) ? run.origin : 'unknown';
}

/** Render a compact, paged table; cleanup closures retain the exact displayed run. */
function renderDatabaseRuns() {
  const node = document.getElementById('db-runs');
  const filters = document.getElementById('db-run-filters');
  if (!node || !filters) return;
  const all = databaseState.runs;
  const counts = {all:all.length, job:0, manual:0, unknown:0};
  all.forEach(run => { counts[databaseRunOrigin(run)]++; });
  const filterNames = ['all','job','manual', ...(counts.unknown || databaseState.runFilter === 'unknown' ? ['unknown'] : [])];
  filters.innerHTML = filterNames.map(key => `<button type="button" data-run-filter="${key}" aria-pressed="${databaseState.runFilter === key}">${escHtml(dbT('runFilter.' + key))} <span>${counts[key]}</span></button>`).join('');
  const selected = all.filter(run => databaseState.runFilter === 'all' || databaseRunOrigin(run) === databaseState.runFilter);
  const pageSize = 10;
  databaseState.runPage = Math.max(0, Math.min(databaseState.runPage, Math.ceil(selected.length / pageSize) - 1));
  const first = databaseState.runPage * pageSize;
  const visible = selected.slice(first, first + pageSize);
  const errors = databaseState.runErrors.filter(error => error.error_code !== 'database_storage_missing');
  const dateLabel = (run, full = false) => {
    const date = new Date(run.started_at || NaN);
    return Number.isNaN(date.getTime()) ? dbT('runUnknownDate') : date.toLocaleString(settingsLocale(), {dateStyle:'medium', timeStyle:full ? 'long' : 'short'});
  };
  const keyOf = run => JSON.stringify([run.profile_id, run.directory]);
  const rows = visible.map((run,index) => {
    const expanded = databaseState.expandedRun === keyOf(run);
    const knownStatus = ['dump_completed','running','failed','cancelled','interrupted','checked','archived'].includes(run.status) ? run.status : 'runUnknownStatus';
    const status = run.archived && !['failed','cancelled','interrupted'].includes(run.status) ? 'runArchived' : knownStatus === 'archived' ? 'runArchived' : knownStatus;
    const tone = ['failed','cancelled','interrupted'].includes(run.status) ? 'warning' : run.archived ? 'success' : 'neutral';
    return `<tr class="database-run-row">
      <th scope="row" class="database-run-profile">${escHtml(run.profile_name || run.profile_id)}</th>
      <td><time datetime="${escHtml(run.started_at || '')}" title="${escHtml(dateLabel(run,true))}">${escHtml(dateLabel(run))}</time></td>
      <td>${escHtml(dbT('runOrigin.' + databaseRunOrigin(run)))}</td>
      <td class="database-run-size">${escHtml(settingsFmtBytes(run.bytes))}</td>
      <td><span class="database-run-status ${tone}">${escHtml(dbT(status))}</span></td>
      <td><button type="button" class="btn btn-secondary database-run-toggle" data-run-details="${index}" aria-expanded="${expanded}" aria-controls="db-run-detail-${index}" aria-label="${escHtml(dbT('runDetailsFor', {profile:run.profile_name || run.profile_id, date:dateLabel(run)}))}">${escHtml(dbT(expanded ? 'runClose' : 'runDetails'))}</button></td>
    </tr>${expanded ? `<tr class="database-run-detail" id="db-run-detail-${index}"><td colspan="6"><div>
      <p><strong>${escHtml(dbT('runDirectory'))}</strong><code>${escHtml(run.directory)}</code></p>
      <p>${escHtml(dateLabel(run,true))} · ${escHtml(dbT('runOrigin.' + databaseRunOrigin(run)))}${run.job_id ? ' · '+escHtml(dbT('runJobId'))+': '+escHtml(run.job_id) : ''}</p>
      <p>${escHtml(dbT('runLocalSize'))}: ${escHtml(settingsFmtBytes(run.bytes))}${run.compression === 'gzip' ? ' · '+escHtml(dbT('originalSize',{size:settingsFmtBytes(run.uncompressed_bytes)}))+' · gzip' : ''}</p>
      <p>${escHtml(run.archived ? dbT('archived') : dbT('notArchived'))}</p>
      <button type="button" class="btn btn-secondary" data-cleanup="${index}">${escHtml(dbT('cleanup'))}</button>
    </div></td></tr>` : ''}`;
  }).join('');
  node.innerHTML = visible.length ? `<div class="database-runs-table-wrap" tabindex="0" role="region" aria-label="${escHtml(dbT('runs'))}"><table class="database-runs-table" aria-label="${escHtml(dbT('runs'))}"><thead><tr>${['profile','runDate','runSource','runLocalSize','runStatus','runDetails'].map(key => `<th scope="col">${escHtml(dbT(key))}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="database-runs-paging"><span role="status">${escHtml(dbT('runRange',{first:first+1,last:first+visible.length,total:selected.length}))}</span>${selected.length > pageSize ? `<div><button type="button" class="btn btn-secondary" data-run-page="-1" ${first ? '' : 'disabled'}>${escHtml(dbT('runPrevious'))}</button><button type="button" class="btn btn-secondary" data-run-page="1" ${first+pageSize >= selected.length ? 'disabled' : ''}>${escHtml(dbT('runNext'))}</button></div>` : ''}</div>`
    : `<p>${escHtml(dbT(all.length ? 'runFilterEmpty' : errors.length ? 'runsUnavailable' : 'noRuns'))}</p>`;
  for (const error of databaseState.runErrors) {
    const p = document.createElement('p');
    if (error.error_code === 'database_storage_missing') {
      p.className = 'database-pending-directory';
      p.textContent = `${error.profile_name || error.profile_id}: ${dbT('pendingDirectory', {path:error.staging_dir || ''})}`;
    } else {
      p.className = 'database-run-error';
      p.textContent = `${error.profile_name || error.profile_id}${error.staging_dir ? ' ('+error.staging_dir+')' : ''}: ${apiErrorMessage({code:error.error_code})}`;
    }
    node.append(p);
  }
  filters.querySelectorAll('[data-run-filter]').forEach(button => button.addEventListener('click', () => {
    databaseState.runFilter = button.dataset.runFilter;
    databaseState.runPage = 0;
    databaseState.expandedRun = '';
    renderDatabaseRuns();
    filters.querySelector(`[data-run-filter="${databaseState.runFilter}"]`)?.focus({preventScroll:true});
  }));
  node.querySelectorAll('[data-run-details]').forEach(button => button.addEventListener('click', () => {
    const index = Number(button.dataset.runDetails);
    const key = keyOf(visible[index]);
    databaseState.expandedRun = databaseState.expandedRun === key ? '' : key;
    renderDatabaseRuns();
    node.querySelector(`[data-run-details="${index}"]`)?.focus({preventScroll:true});
  }));
  node.querySelectorAll('[data-run-page]').forEach(button => button.addEventListener('click', () => {
    const delta = Number(button.dataset.runPage);
    databaseState.runPage += delta;
    databaseState.expandedRun = '';
    renderDatabaseRuns();
    const next = node.querySelector(`[data-run-page="${delta}"]:not(:disabled)`) || node.querySelector('[data-run-page]:not(:disabled)');
    next?.focus({preventScroll:true});
  }));
  node.querySelectorAll('[data-cleanup]').forEach(button => button.addEventListener('click', () => {
    const run = visible[Number(button.dataset.cleanup)];
    startDatabaseAction(run.profile_id, 'cleanup', run.directory);
  }));
}

/** Load wizard profile choices; retain unavailable selections instead of silently dropping them. */
async function wizardLoadDatabases(request) {
  try {
    const data = await databaseRequest('', undefined);
    if (request !== wizardState.jobIdRequest) return;
    wizardState.databaseProfiles = [...data.profiles, ...(data.unsupported_profiles || []).map(p => ({...p, enabled:false, databases:[]}))];
    wizardState.databasesLoaded = true;
    wizardApplyDatabases([]);
  } catch (_) { if (request === wizardState.jobIdRequest) { wizardState.databasesLoaded = false; _wizardShowError(2, dbT('loadError')); } }
}
/** Render all available and missing selected profiles without changing the requested selection. */
function wizardApplyDatabases(selected) {
  const node = document.getElementById('wiz-databases'); if (!node) return;
  const rows = [...(wizardState.databaseProfiles || [])];
  for (const id of selected) if (!rows.some(p => p.id === id)) rows.push({id,name:dbT('missing'),databases:[]});
  node.innerHTML = rows.map(p => `<label class="wizard-database-choice"><input type="checkbox" value="${escHtml(p.id)}" ${selected.includes(p.id) ? 'checked' : ''}><span><strong>${escHtml(p.name)}${p.enabled ? '' : ' ('+escHtml(dbT('missing'))+')'}</strong><small>${escHtml(p.engine || '')}${p.databases.length ? ' · '+escHtml(p.databases.join(', ')) : ''}${p.include_globals ? ' · '+escHtml(dbT('globals')) : ''}</small></span></label>`).join('') || `<p>${escHtml(dbT('noProfiles'))}</p>`;
  wizardUpdateDatabaseCount();
}

/** Update the selected-profile count, including unavailable profiles retained for explicit correction. */
function wizardUpdateDatabaseCount() {
  const count = document.getElementById('wiz-source-database-count');
  if (count) count.textContent = String(document.querySelectorAll('#wiz-databases input:checked').length);
}
