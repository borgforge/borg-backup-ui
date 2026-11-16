'use strict';
/** Manage owned device sessions; credentials never enter the DOM. */
(async function mobileDevices() {
  const i18n = window.BBUI.components.i18n;
  await i18n.init();
  const t = key => i18n.t(`mobile.${key}`);
  const result = document.getElementById('result');
  const form = document.getElementById('pair-form');
  /** Call the same-origin cookie API and show only translated failures. */
  async function api(action, body) {
    const response = await fetch(`/api/auth/mobile/${action}`, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (response.status === 401) document.getElementById('login').hidden = false;
    if (!response.ok) throw new Error(t('error'));
    return response.json();
  }
  /** Render names as text, with per-device revocation owned by this browser user. */
  async function refresh() {
    try {
      const data = await api('sessions');
      document.getElementById('job-control').disabled = data.can_approve_job_control !== true;
      const list = document.getElementById('devices');
      list.replaceChildren();
      for (const session of data.sessions) {
        const row = document.createElement('li');
        const text = document.createElement('span');
        text.textContent = `${session.label} · ${t(session.job_control ? 'controlAccess' : 'readAccess')} · ${t('expires')} ${new Date(session.expires_at * 1000).toLocaleString()} `;
        const button = document.createElement('button');
        button.textContent = t('revoke');
        button.onclick = async () => {
          button.disabled = true;
          try { await api('revoke', {session_id: session.id}); await refresh(); }
          catch (_) { result.textContent = t('error'); button.disabled = false; }
        };
        row.append(text, button); list.append(row);
      }
      if (!data.sessions.length) list.textContent = t('empty');
    } catch (_) { result.textContent = t('error'); }
  }
  form.onsubmit = async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await api('approve', {user_code: document.getElementById('code').value, allow_job_control: document.getElementById('job-control').checked});
      document.getElementById('code').value = '';
      document.getElementById('job-control').checked = false;
      result.textContent = t('approved');
    } catch (_) { result.textContent = t('error'); }
    finally { button.disabled = false; }
  };
  document.getElementById('refresh').onclick = refresh;
  if (location.protocol !== 'https:') {
    result.textContent = t('https');
    form.querySelector('button').disabled = true;
  }
  await refresh();
})();
