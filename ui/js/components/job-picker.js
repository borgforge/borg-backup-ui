/** Shared, modal job selection for Reports and Restore (#642). */
(function () {
  window.BBUI = window.BBUI || {};
  const components = window.BBUI.components = window.BBUI.components || {};
  const t = key => components.i18n?.t?.(`jobPicker.${key}`) || key;
  const locationOf = job => String(job?.location || 'local').toLowerCase();
  let dialog;

  /** Read a browser-local preference. Callers must validate the key against eligible jobs. */
  function recalled(page) {
    try { return String(JSON.parse(localStorage.getItem(`bbui.jobPicker.${page}`) || 'null')?.key || ''); }
    catch (_) { return ''; }
  }

  /** Remember a selected job and its actual location; unavailable browser storage is harmless. */
  function remember(page, job) {
    if (!job) return;
    try { localStorage.setItem(`bbui.jobPicker.${page}`, JSON.stringify({key: String(job.key), location: locationOf(job)})); }
    catch (_) { /* Private browsing or storage policy may disable persistence. */ }
  }

  /** Close the open picker, restoring focus to its trigger. No selection is made. */
  function close() { if (dialog?.open) dialog.close(); }

  /** Open a bounded job picker. Filtering is local until an eligible job is clicked.
   * @param {object} options Jobs, selected key, trusted icon renderer, location label,
   * trigger element and onSelect(key) callback. Callback runs after the dialog closes.
   * Native modal behavior keeps the underlying workspace inert; Escape cancels.
   */
  function open({jobs, selected, icon, locationLabel, trigger, onSelect}) {
    close();
    dialog?.remove();
    const order = ['local', 'usb', 'smb', 'storagebox'];
    const rank = key => order.includes(key) ? order.indexOf(key) : order.length;
    const locations = [...new Set(jobs.map(locationOf))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
    let location = locationOf(jobs.find(job => String(job.key) === String(selected)) || jobs[0]);
    let pendingKey = null;
    const modal = dialog = document.createElement('dialog');
    modal.id = 'job-picker-dialog';
    modal.className = 'job-picker-dialog';
    modal.setAttribute('aria-labelledby', 'job-picker-title');
    modal.innerHTML = `<header><h2 id="job-picker-title">${escHtml(t(selected ? 'change' : 'choose'))}</h2><button type="button" class="btn btn-secondary" data-picker-close aria-label="${escHtml(t('close'))}">×</button></header>
      <nav class="job-picker-locations" aria-label="${escHtml(t('locations'))}"></nav>
      <label class="job-picker-search" for="job-picker-search">${escHtml(t('search'))}<input id="job-picker-search" type="search" autocomplete="off"></label>
      <div class="job-picker-results"></div><footer><span id="job-picker-count" role="status"></span><button type="button" class="btn btn-secondary" data-picker-close>${escHtml(t('cancel'))}</button></footer>`;
    const search = modal.querySelector('input');
    const list = modal.querySelector('.job-picker-results');
    const nav = modal.querySelector('nav');
    function render() {
      nav.innerHTML = locations.map(key => `<button type="button" data-picker-location="${escHtml(key)}" aria-pressed="${key === location}">${escHtml(locationLabel(key))}<span class="location-nav-count">${jobs.filter(job => locationOf(job) === key).length}</span></button>`).join('');
      const query = search.value.trim().toLowerCase();
      const visible = jobs.filter(job => locationOf(job) === location && `${job.name || job.display_name || ''} ${job.archive_prefix || ''} ${job.key}`.toLowerCase().includes(query));
      list.innerHTML = visible.length ? visible.map(job => `<button type="button" class="job-picker-row" data-picker-job="${escHtml(job.key)}" title="${escHtml(job.key)}" aria-pressed="${String(job.key) === String(selected)}">${icon(job)}<span class="job-picker-name"><strong>${escHtml(job.name || job.display_name || job.key)}</strong><small>${escHtml(job.archive_prefix || '')}</small></span><span class="job-picker-location">${escHtml(locationLabel(locationOf(job)))}</span><span aria-hidden="true">${String(job.key) === String(selected) ? '✓' : ''}</span></button>`).join('') : `<p class="ui-empty">${escHtml(t('empty'))}</p>`;
      modal.querySelector('#job-picker-count').textContent = `${visible.length} ${t('jobs')}`;
      list.scrollTop = 0;
    }
    search.addEventListener('input', render);
    modal.addEventListener('click', event => {
      if (event.target.closest('[data-picker-close]')) { close(); return; }
      const filter = event.target.closest('[data-picker-location]');
      if (filter) {
        location = filter.dataset.pickerLocation; search.value = ''; render();
        [...nav.children].find(button => button.dataset.pickerLocation === location)?.focus();
        return;
      }
      const button = event.target.closest('[data-picker-job]');
      if (button) {
        const key = button.dataset.pickerJob;
        if (key !== String(selected)) pendingKey = key;
        close();
      }
    });
    modal.addEventListener('keydown', event => {
      if (event.key === 'Escape') event.stopPropagation();
      if (event.key !== 'Tab') return;
      const controls = [...modal.querySelectorAll('button, input')].filter(el => !el.disabled && el.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    modal.addEventListener('close', () => {
      trigger?.setAttribute('aria-expanded', 'false');
      if (trigger?.isConnected && !trigger.disabled && trigger.getClientRects().length) trigger.focus();
      modal.remove();
      if (pendingKey !== null) onSelect(pendingKey);
    }, {once: true});
    document.body.appendChild(modal);
    render();
    trigger?.setAttribute('aria-expanded', 'true');
    modal.showModal();
    search.focus();
  }
  components.jobPicker = {open, close, recalled, remember, locationOf};
})();
