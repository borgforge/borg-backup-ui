'use strict';
/** Owned device sessions inside Settings > Users; never renders credentials. */
(function mobileDevices() {
  const t = key => window.BBUI.components.i18n.t(`mobile.${key}`);

  /** Render shared settings surfaces; data loads separately without resetting input. */
  function render() {
    return settingsCard('BorgForge Mobile', settingsMenuIcon('users'), `
      <div class="settings-body" id="mobile-devices-settings">
        <p class="text-muted">${escHtml(t('intro'))}</p>
        <p class="text-muted">${escHtml(t('warning'))}</p>
        <form id="mobile-pair-form" class="mobile-pair-form">
          <div class="form-group"><label class="form-label" for="mobile-pair-code">${escHtml(t('code'))}</label>
            <input id="mobile-pair-code" class="form-input" autocomplete="off" autocapitalize="characters" spellcheck="false"
              maxlength="16" required pattern="[A-Za-z2-9 -]{10,16}"></div>
          <label class="form-checkbox-row"><input id="mobile-job-control" type="checkbox" disabled>
            <span>${escHtml(t('jobControl'))}</span></label>
          <button class="btn btn-primary" id="mobile-approve" type="submit" disabled>${escHtml(t('approve'))}</button>
        </form>
        <div id="mobile-device-result" class="status-message hidden" role="status" aria-live="polite"></div>
        <div class="mobile-devices-heading"><h3>${escHtml(t('devices'))}</h3>
          <button type="button" class="btn btn-secondary btn-sm" data-settings-action="mobile-refresh">${escHtml(t('refresh'))}</button></div>
        <p class="text-muted">${escHtml(t('sessionHint'))}</p>
        <div id="mobile-device-list" aria-live="polite">${escHtml(t('loading'))}</div>
      </div>`);
  }

  /** Request the existing cookie/Origin API; surface translated errors only. */
  async function api(action, body) {
    let response;
    try { response = await fetch(`/api/auth/mobile/${action}`, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      ...(body ? {body: JSON.stringify(body)} : {}),
    }); } catch (_) { throw new Error(t('error')); }
    if (!response.ok) throw new Error(t(response.status === 401 ? 'login' : 'error'));
    try { return await response.json(); } catch (_) { throw new Error(t('error')); }
  }

  function message(root, text, error = false) {
    const node = root.querySelector('#mobile-device-result');
    node.textContent = text;
    node.className = `status-message ${error ? 'error' : 'success'}`;
  }

  /** Fetch current owned sessions; late reads cannot replace newer results. */
  async function refresh({clearError = true} = {}) {
    const root = document.getElementById('mobile-devices-settings');
    if (!root) return;
    bind(root);
    const generation = (root.mobileGeneration || 0) + 1;
    root.mobileGeneration = generation;
    const current = () => root.isConnected && root.mobileGeneration === generation;
    const list = root.querySelector('#mobile-device-list');
    const secure = location.protocol === 'https:';
    root.querySelector('#mobile-approve').disabled = true;
    root.querySelector('#mobile-job-control').disabled = true;
    try {
      const data = await api('sessions');
      if (!current()) return;
      if (!Array.isArray(data.sessions)) throw new Error(t('error'));
      root.mobileCanControl = data.can_approve_job_control === true;
      root.mobileLoaded = true;
      const notice = root.querySelector('#mobile-device-result');
      if (clearError && notice.classList.contains('error')) { notice.textContent = ''; notice.className = 'status-message hidden'; }
      root.querySelector('#mobile-approve').disabled = !secure || !!root.mobileBusy;
      root.querySelector('#mobile-job-control').disabled = !secure || !root.mobileCanControl || !!root.mobileBusy;
      if (!root.mobileCanControl) root.querySelector('#mobile-job-control').checked = false;
      list.innerHTML = data.sessions.length ? `<div class="mobile-devices-table"><table class="settings-table">
        <thead><tr><th>${escHtml(t('device'))}</th><th>${escHtml(t('access'))}</th><th>${escHtml(t('created'))}</th><th>${escHtml(t('expires'))}</th><th>${escHtml(t('actions'))}</th></tr></thead>
        <tbody>${data.sessions.map(session => `<tr>
          <td>${escHtml(session.label)}</td><td><span class="badge ${session.job_control ? 'warning' : 'info'}">${escHtml(t(session.job_control ? 'controlAccess' : 'readAccess'))}</span></td>
          <td>${escHtml(date(session.created_at))}</td><td>${escHtml(session.persistent === true ? t('untilRevoked') : date(session.expires_at))}</td>
          <td><button type="button" class="btn btn-danger btn-sm" data-settings-action="mobile-revoke" data-mobile-id="${escAttr(session.id)}" ${secure ? '' : 'disabled'}>${escHtml(t('revoke'))}</button></td>
        </tr>`).join('')}</tbody></table></div>` : `<div class="empty-state">${escHtml(t('empty'))}</div>`;
      if (!secure) message(root, t('https'), true);
    } catch (error) {
      if (!current()) return;
      root.mobileLoaded = false;
      list.textContent = t('loadFailed');
      message(root, error.message, true);
    }
  }

  function date(seconds) {
    return typeof seconds === 'number' && Number.isFinite(seconds)
      ? new Date(seconds * 1000).toLocaleString(settingsLocale()) : '—';
  }

  /** Bind once per rendered form. Approval is explicit and never retried. */
  function bind(root) {
    const form = root.querySelector('#mobile-pair-form');
    if (form.dataset.bound) return;
    form.dataset.bound = 'true';
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (root.mobileBusy || !root.mobileLoaded || location.protocol !== 'https:' || !form.reportValidity()) return;
      root.mobileBusy = true;
      root.querySelector('#mobile-approve').disabled = true;
      root.querySelector('#mobile-job-control').disabled = true;
      try {
        await api('approve', {user_code: root.querySelector('#mobile-pair-code').value,
          allow_job_control: root.mobileCanControl && root.querySelector('#mobile-job-control').checked});
        if (!root.isConnected) return;
        form.reset();
        message(root, t('approved'));
      } catch (error) {
        if (root.isConnected) message(root, error.message, true);
      } finally {
        root.mobileBusy = false;
        if (root.isConnected) await refresh({clearError: false});
      }
    });
  }

  /** Revoke the selected owned session and refresh the visible list in place. */
  async function handleClick(button) {
    if (button.dataset.settingsAction === 'mobile-refresh') return refresh();
    const root = document.getElementById('mobile-devices-settings');
    if (!root || button.disabled || location.protocol !== 'https:') return;
    button.disabled = true;
    root.mobileGeneration = (root.mobileGeneration || 0) + 1;
    try {
      await api('revoke', {session_id: button.dataset.mobileId});
      if (!root.isConnected) return;
      message(root, t('revoked'));
      await refresh();
    } catch (error) {
      if (root.isConnected) { message(root, error.message, true); button.disabled = false; }
    }
  }

  window.BBUI.mobileDevices = {render, refresh, handleClick};
})();
