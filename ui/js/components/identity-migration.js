'use strict';

// #479: observing a persisted migration never authorizes a write.
(function identityMigrationAssistant() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const endpoint = '/api/migration/identity';
  const stages = ['required', 'waiting', 'preparing', 'backup_ready', 'acknowledged', 'applying', 'verifying', 'interrupted', 'complete'];
  let host = null;
  let current = null;
  let timer = null;
  let request = null;
  let acting = false;
  let error = '';
  let statusError = '';
  let path = null;
  let checkedBinding = '';
  let rendered = '';

  function t(key, params = {}) {
    return window.BBUI.components.i18n.t(`settings.identityMigration.${key}`, params);
  }
  function escape(value) {
    return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  }
  function binding(data) {
    return data?.plan_id && data?.snapshot_digest ? `${data.plan_id}:${data.snapshot_digest}` : '';
  }
  function verified(data) {
    return Boolean(binding(data) && data?.snapshot?.verified === true);
  }
  function stage(data) {
    return stages.includes(data?.stage) ? data.stage : 'required';
  }
  function canPrepare(data) {
    return Boolean(data?.can_prepare === true && !data.busy && !data.restart_required
      && ['required', 'waiting', 'interrupted'].includes(data.stage)
      && ['pending', 'blocked'].includes(data.status));
  }
  function canAcknowledge(data) {
    return verified(data) && !data.busy && !data.restart_required && data.status === 'pending' && data.stage === 'backup_ready';
  }
  function canApply(data) {
    return verified(data) && !data.busy && !data.restart_required && ((data.status === 'pending' && data.stage === 'acknowledged')
      || (data.can_resume === true && data.stage === 'interrupted'));
  }
  function stepIndex(data) {
    if (data?.stage === 'interrupted') {
      return verified(data) ? (data.acknowledged === true || data.can_resume === true ? 3 : 2) : 1;
    }
    return { required: 0, waiting: 1, preparing: 1, backup_ready: 2, acknowledged: 3,
      applying: 3, verifying: 3, complete: 4 }[stage(data)];
  }
  function isVisible() {
    return Boolean(host?.isConnected && host.getClientRects().length);
  }
  function schedule() {
    clearTimeout(timer);
    if (host?.isConnected) timer = setTimeout(() => {
      if (isVisible()) refresh();
      else schedule();
    }, 2000);
  }
  function rememberInputs() {
    const field = host?.querySelector('[data-identity-path]');
    if (field) path = field.value;
  }
  function render() {
    if (!host?.isConnected) return;
    rememberInputs();
    const data = current;
    const signature = JSON.stringify([data, acting, error, statusError, checkedBinding]);
    if (rendered === signature) return;
    rendered = signature;
    if (data?.status === 'not_applicable') {
      host.innerHTML = '';
      return;
    }
    const selectedStage = stage(data);
    const busy = acting || data?.busy === true;
    const ready = verified(data);
    const currentBinding = binding(data);
    const checked = Boolean(currentBinding && checkedBinding === currentBinding);
    const snapshot = data?.snapshot || {};
    const count = Number(data?.progress?.completed);
    const total = Number(data?.progress?.total);
    const progress = Number.isSafeInteger(count) && Number.isSafeInteger(total) && count >= 0 && total > 0 && count <= total;
    const activeElement = window.document?.activeElement;
    const focusSelector = host.contains(activeElement) && activeElement?.matches?.('[data-identity-path], [data-identity-ack]')
      ? (activeElement.matches('[data-identity-path]') ? '[data-identity-path]' : '[data-identity-ack]') : '';
    const codes = reasonItems(data?.reason_codes);
    const preparationCodes = data?.last_preparation?.status === 'blocked' ? reasonItems(data.last_preparation.reason_codes) : '';
    const steps = ['stepRequired', 'stepPrepare', 'stepBackup', 'stepApply'];
    const index = stepIndex(data);
    const downloadUrl = `${endpoint}/snapshot?plan_id=${encodeURIComponent(String(data?.plan_id || ''))}&snapshot_digest=${encodeURIComponent(String(data?.snapshot_digest || ''))}`;
    host.innerHTML = `<section class="settings-section identity-migration-assistant" aria-labelledby="identity-migration-title">
      <div class="settings-section-header" id="identity-migration-title">${escape(t('title'))}</div>
      <div class="settings-body">
        <p>${escape(t('intro'))}</p>
        <ol class="identity-migration-steps">${steps.map((key, number) => `<li class="${number < index ? 'complete' : (number === index ? 'current' : '')}"${number === index ? ' aria-current="step"' : ''}><span>${number + 1}</span>${escape(t(key))}</li>`).join('')}</ol>
        <div class="identity-migration-status" role="status" aria-live="polite">
          <strong>${escape(t(data ? `stage.${selectedStage}` : 'loading'))}</strong>
          ${data ? `<p>${escape(t(`hint.${selectedStage}`))}</p>` : ''}
          ${progress && ['applying', 'verifying', 'interrupted', 'complete'].includes(selectedStage) ? `<progress value="${count}" max="${total}"></progress><span>${escape(t('progress', { completed: count, total }))}</span>` : ''}
          ${codes ? `<details open><summary>${escape(t('details'))}</summary><ul>${codes}</ul></details>` : ''}
        </div>
        ${acting ? `<p role="status" aria-live="polite">${escape(t('requestPending'))}</p>` : ''}
        ${preparationCodes ? `<div class="status-message error" role="alert"><strong>${escape(t('preparationFailed'))}</strong><ul>${preparationCodes}</ul></div>` : ''}
        ${error ? `<p class="status-message error" role="alert">${escape(error)}</p>` : ''}
        ${statusError ? `<p class="status-message error" role="alert">${escape(statusError)}</p>` : ''}
        ${canPrepare(data) ? `<div class="identity-migration-prepare">
          <label class="form-label" for="identity-migration-path">${escape(t('pathLabel'))}</label>
          <input class="form-input" id="identity-migration-path" data-identity-path type="text" value="${escape(data.state_dir || (path ?? data.suggested_state_dir ?? ''))}" autocomplete="off" spellcheck="false" aria-describedby="identity-migration-path-hint"${busy ? ' disabled' : ''}${data.state_dir ? ' readonly' : ''}>
          <p id="identity-migration-path-hint" class="text-muted">${escape(t('pathHint'))}</p>
          <button type="button" class="btn btn-primary" data-identity-action="prepare"${busy ? ' disabled' : ''}>${escape(t(data.state_dir ? 'resumePreparation' : 'prepare'))}</button>
        </div>` : ''}
        ${snapshot.path ? `<dl class="identity-migration-snapshot">
          <div><dt>${escape(t('snapshotPath'))}</dt><dd>${escape(snapshot.path)}</dd></div>
          <div><dt>${escape(t('snapshotCreated'))}</dt><dd>${escape(snapshot.created_at || t('unavailable'))}</dd></div>
          <div><dt>${escape(t('snapshotSize'))}</dt><dd>${escape(formatBytes(snapshot.size_bytes))}</dd></div>
          <div><dt>${escape(t('snapshotVerification'))}</dt><dd>${escape(t(ready ? 'verified' : 'unverified'))}</dd></div>
        </dl>` : ''}
        ${ready ? `<div class="identity-migration-backup">
          <p>${escape(t('confidential'))}</p>
          <a class="btn btn-secondary" href="${escape(downloadUrl)}" download rel="noreferrer">${escape(t('download'))}</a>
          ${canAcknowledge(data) ? `<p>${escape(t('independentCopy'))}</p>
            <label class="form-checkbox-row"><input type="checkbox" data-identity-ack${checked ? ' checked' : ''}${busy ? ' disabled' : ''}><span>${escape(t('acknowledgement'))}</span></label>
            <button type="button" class="btn btn-secondary" data-identity-action="acknowledge"${busy || !checked ? ' disabled' : ''}>${escape(t('acknowledge'))}</button>` : ''}
          ${data.stage === 'acknowledged' ? `<p>${escape(t('acknowledgedPause'))}</p>` : ''}
        </div>` : ''}
        ${canApply(data) ? `<div class="identity-migration-apply"><p>${escape(t('applyDescription'))}</p><button type="button" class="btn btn-primary" data-identity-action="apply"${busy ? ' disabled' : ''}>${escape(t(data.can_resume === true && selectedStage === 'interrupted' ? 'resume' : 'apply'))}</button></div>` : ''}
        ${data?.restart_required === true ? `<p class="status-message warning">${escape(t('restartRequired'))}</p>` : ''}
        <div class="identity-migration-actions"><button type="button" class="btn btn-secondary btn-sm" data-identity-action="refresh"${busy ? ' disabled' : ''}>${escape(t('refresh'))}</button>
        ${data?.status === 'applied' && selectedStage === 'complete' && !data.restart_required ? `<button type="button" class="btn btn-primary" data-identity-action="open">${escape(t('open'))}</button>` : ''}</div>
      </div>
    </section>`;
    if (focusSelector) host.querySelector(focusSelector)?.focus?.({ preventScroll: true });
  }
  function reason(code) {
    const key = `settings.identityMigration.reasons.${code}`;
    const translated = window.BBUI.components.i18n.t(key);
    return translated === key ? t('reasonCode', { code }) : translated;
  }
  function reasonItems(values) {
    const counts = new Map();
    if (Array.isArray(values)) values.filter(value => typeof value === 'string').forEach(code => counts.set(code, (counts.get(code) || 0) + 1));
    return [...counts].slice(0, 20).map(([code, count]) => {
      const description = reason(code);
      const diagnostic = t('reasonCode', { code });
      return `<li>${escape(description)}${count > 1 ? ` (${escape(t('reasonCount', { count }))})` : ''}${description !== diagnostic ? `<br><small>${escape(diagnostic)}</small>` : ''}</li>`;
    }).join('');
  }
  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return t('unavailable');
    const locale = window.BBUI.components.i18n.getLanguage() === 'de' ? 'de-DE' : 'en-US';
    return t('bytes', { count: bytes.toLocaleString(locale) });
  }
  function accept(data) {
    if (!data || data.migration_id !== 'immutable_job_id_v1' || !stages.includes(data.stage)
        || !['pending', 'blocked', 'failed', 'applied', 'not_applicable'].includes(data.status)) {
      throw new Error(t('invalidStatus'));
    }
    if (binding(data) !== binding(current)) checkedBinding = '';
    current = data;
    statusError = '';
    render();
  }
  async function readStatus() {
    const response = await fetch(`${endpoint}/status`, { credentials: 'include', cache: 'no-store' });
    if (!response.ok) throw new Error(t('requestFailed', { status: response.status }));
    accept(await response.json());
  }
  async function refresh() {
    if (request || acting) return request;
    request = readStatus().catch(() => {
      statusError = t('statusUnavailable');
      // Retain the last known progress, but disable mutations until revalidated.
      if (current) current = { ...current, busy: true };
      render();
    }).finally(() => { request = null; schedule(); });
    return request;
  }
  async function act(action) {
    if (acting) return;
    if (action === 'refresh') return refresh();
    if (action === 'open') {
      if (current?.status === 'applied' && current.stage === 'complete' && !current.restart_required) window.location.reload();
      return;
    }
    rememberInputs();
    const displayedBinding = binding(current);
    if (action === 'prepare' && !canPrepare(current)) return;
    if (action === 'acknowledge' && (!canAcknowledge(current) || checkedBinding !== displayedBinding)) return;
    if (action === 'apply' && !canApply(current)) return;
    if (!['prepare', 'acknowledge', 'apply'].includes(action)) return;
    error = '';
    if (action === 'prepare' && !current.state_dir && !path.trim().startsWith('/')) {
      error = t('pathRequired');
      render();
      return;
    }
    acting = true;
    clearTimeout(timer);
    render();
    try {
      // A response from an earlier poll must not replace the action's response.
      if (request) await request;
      if (action !== 'prepare' && displayedBinding !== binding(current)) throw new Error(t('changedBackup'));
      if ((action === 'prepare' && !canPrepare(current)) || (action === 'acknowledge' && !canAcknowledge(current))
          || (action === 'apply' && !canApply(current))) return;
      const payload = action === 'prepare' ? { state_dir: current.state_dir || path.trim() } : {
        plan_id: current.plan_id, snapshot_digest: current.snapshot_digest,
        ...(action === 'acknowledge' ? { independent_backup_ack: true } : {}),
      };
      const response = await fetch(`${endpoint}/${action}`, { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        // Only translate known reason codes; arbitrary response text may contain secrets.
        const failureCode = [failure.code, failure.message].find(code => typeof code === 'string'
          && window.BBUI.components.i18n.t(`settings.identityMigration.reasons.${code}`) !== `settings.identityMigration.reasons.${code}`);
        await readStatus();
        throw new Error(failureCode ? reason(failureCode) : t('requestFailed', { status: response.status }));
      }
      accept(await response.json());
    } catch (failure) {
      error = failure?.message || t('statusUnavailable');
      // An uncertain request is observed via GET; it is never retried as POST.
      if (current) current = { ...current, busy: true };
    } finally {
      acting = false;
      render();
      schedule();
    }
  }
  function mount(element) {
    if (!element) return;
    rememberInputs();
    host = element;
    rendered = '';
    host.onclick = event => {
      const button = event.target.closest('[data-identity-action]');
      if (button && host.contains(button) && !button.disabled) return act(button.dataset.identityAction);
    };
    host.onchange = event => {
      if (event.target.matches('[data-identity-ack]')) {
        checkedBinding = event.target.checked ? binding(current) : '';
        render();
      }
    };
    render();
    refresh();
  }
  window.addEventListener('bbui:language-changed', () => { rendered = ''; render(); });
  window.BBUI.components.identityMigration = { mount, refresh };
})();
