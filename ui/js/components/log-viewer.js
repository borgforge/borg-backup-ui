'use strict';

(function initLogViewerComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const t = (key, params = {}) => window.BBUI?.components?.i18n?.t?.(`api.messages.${key}`, params) || key;

  async function open(filePath) {
    const modal = document.getElementById('log-viewer-modal');
    const body  = document.getElementById('log-viewer-body');
    const title = document.getElementById('log-viewer-title');
    if (!modal) return;

    title.textContent = String(filePath || '').split('/').pop();
    body.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><span>${escHtml(t('logLoading'))}</span></div>`;
    modal.classList.remove('hidden');

    try {
      const res  = await fetch('/api/history/log?file=' + encodeURIComponent(filePath));
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(apiErrorMessage(data, res.status));
      if (!data.exists) {
        body.innerHTML = `<div class="log-viewer-missing">${escHtml(t('logMissing'))}:<br><code id="log-viewer-missing-path"></code></div>`;
        const pathEl = document.getElementById('log-viewer-missing-path');
        if (pathEl) pathEl.textContent = String(filePath || '');
      } else {
        body.innerHTML = `<pre class="log-viewer-content">${escHtml(data.content)}</pre>`;
        body.scrollTop = 0;
      }
    } catch (e) {
      body.innerHTML = `<div class="log-viewer-missing">${escHtml(t('errorValue', { message: e.message }))}</div>`;
    }
  }

  function close() {
    document.getElementById('log-viewer-modal')?.classList.add('hidden');
  }

  window.BBUI.components.logViewer = { open, close };
})();
