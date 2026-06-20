// ── History ───────────────────────────────────────────────────────────────────

window.BBUI = window.BBUI || {};
window.BBUI.historyState = window.BBUI.historyState || { loaded: false, data: null, page: 1, perPage: 20 };
const historyState = window.BBUI.historyState;

function historyT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`history.${key}`, params) || `history.${key}`;
}

function historyLocale() {
  return window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en-US' : 'de-DE';
}

async function refreshHistory() {
  const btn = document.getElementById('history-refresh-btn');
  if (btn) btn.disabled = true;

  const type     = document.getElementById('history-filter-type')?.value     || '';
  const location = document.getElementById('history-filter-location')?.value || '';
  const status   = document.getElementById('history-filter-status')?.value   || '';

  const params = new URLSearchParams();
  if (type)     params.set('type', type);
  if (location) params.set('location', location);
  if (status)   params.set('status', status);
  params.set('page', String(historyState.page || 1));
  params.set('per_page', String(historyState.perPage || 20));

  try {
    const res  = await fetch('/api/history?' + params.toString(), { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(apiErrorMessage(data, res.status));
    historyState.data   = data;
    historyState.loaded = true;
    renderHistory(data);
    hideEl('history-message');
  } catch (e) {
    showMsg('history-message', 'error', historyT('error', { message: e.message }));
  } finally {
    if (btn) btn.disabled = false;
  }
}

function applyHistoryFilters() {
  historyState.loaded = false;
  historyState.page = 1;
  refreshHistory();
}

function renderHistory(data) {
  const countEl = document.getElementById('history-count');
  if (countEl) countEl.textContent = historyT('entryCount', { count: data.total });

  const el = document.getElementById('history-content');
  if (!el) return;

  if (!data.entries || data.entries.length === 0) {
    el.innerHTML = `<div class="history-empty">${escHtml(historyT('empty'))}</div>`;
    return;
  }

  const rows = data.entries.map((e, i) => renderHistoryRow(e, i)).join('');
  const page = data.page || 1;
  const totalPages = data.total_pages || 1;
  const prevDisabled = page <= 1 ? 'disabled' : '';
  const nextDisabled = page >= totalPages ? 'disabled' : '';

  el.innerHTML = `
    <table class="history-table">
      <thead>
        <tr>
          <th></th>
          <th>${escHtml(historyT('dateTime'))}</th>
          <th>${escHtml(historyT('type'))}</th>
          <th>${escHtml(historyT('location'))}</th>
          <th>${escHtml(historyT('duration'))}</th>
          <th>${escHtml(historyT('originalSize'))}</th>
          <th>${escHtml(historyT('deduplicated'))}</th>
          <th>${escHtml(historyT('status'))}</th>
        </tr>
      </thead>
      <tbody id="history-tbody">
        ${rows}
      </tbody>
    </table>
    <div class="history-pagination" style="display:flex;justify-content:flex-end;gap:8px;align-items:center;margin-top:10px">
      <span style="color:var(--text-muted);font-size:12px">${escHtml(historyT('page', { page, totalPages }))}</span>
      <button class="btn btn-secondary btn-sm" data-history-action="page-prev" ${prevDisabled}>${escHtml(historyT('previous'))}</button>
      <button class="btn btn-secondary btn-sm" data-history-action="page-next" ${nextDisabled}>${escHtml(historyT('next'))}</button>
    </div>`;
}

function renderHistoryRow(e, idx) {
  if (e.entry_kind === 'restore_test_report') return renderRestoreReportRow(e, idx);
  const skipKey = `dashboard.skipReasons.${e.skip_reason_code || 'skipped'}`;
  const skipTranslation = window.BBUI?.components?.i18n?.t?.(skipKey) || skipKey;
  const detailReason = skipTranslation === skipKey ? historyT('skippedReason', { reason: '' }) : skipTranslation;
  const detailError = e.status === 'error' ? historyT('backupFailedDetails') : detailReason;
  const statusBadge = `<span class="history-status-badge ${e.status}">${historyStatusLabel(e.status)}</span>`;
  const locClass = e.location || '';
  const typeLabel = historyTypeLabel(e.backup_type);
  const rowId = `hrow-${idx}`;
  const detailId = `hdetail-${idx}`;

  return `
    <tr id="${rowId}" class="history-row" data-history-action="toggle-detail" data-row-id="${rowId}" data-detail-id="${detailId}">
      <td><svg class="history-chevron" id="chev-${idx}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg></td>
      <td style="white-space:nowrap;color:var(--text-primary)">${escHtml(e.date)} <span style="color:var(--text-muted)">${escHtml(e.time)}</span></td>
      <td><span class="history-type-badge">${escHtml(typeLabel)}</span></td>
      <td><span class="history-loc-chip ${locClass}">${escHtml(historyLocationLabel(e.location))}</span></td>
      <td>${escHtml(e.duration_fmt || '–')}</td>
      <td>${escHtml(e.original_size_fmt || '–')}</td>
      <td>${escHtml(e.deduplicated_size_fmt || '–')}</td>
      <td>${statusBadge}</td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="8">
        ${detailError ? `<div class="history-error-msg">${e.status === 'skipped' ? '' : escHtml(historyT('errorPrefix'))}${escHtml(detailError)}</div>` : ''}
        <div class="history-detail-panel">
          ${detailGroup(historyT('archive'), e.archive_name)}
          ${detailGroup(historyT('compressed'), e.compressed_size_fmt)}
          ${detailGroup(historyT('repositorySize'), e.repository_size_fmt)}
          ${detailGroup(historyT('files'), e.files_count != null ? e.files_count.toLocaleString(historyLocale()) : null)}
          ${detailGroup(historyT('exitCode'), e.exit_code != null ? String(e.exit_code) : null)}
          ${detailGroup(historyT('lastCheck'), e.repository_check_date)}
          ${detailGroup(historyT('nextCheck'), e.repository_next_check)}
          ${detailGroup(historyT('checkStatus'), e.repository_check_status)}
          ${e.log_file ? `
          <div class="history-detail-group">
            <div class="history-detail-label">${escHtml(historyT('logFile'))}</div>
            <div class="history-detail-value" style="display:flex;align-items:center;gap:8px">
              <span style="color:var(--text-muted);font-size:11px" title="${escHtml(e.log_file)}">${escHtml(e.log_file.split('/').pop())}</span>
              <button class="btn btn-secondary btn-sm" data-history-action="open-log" data-log-file="${escHtml(e.log_file)}">${escHtml(historyT('open'))}</button>
            </div>
          </div>` : ''}
        </div>
      </td>
    </tr>`;
}

function renderRestoreReportRow(e, idx) {
  const rowId = `hrow-${idx}`;
  const detailId = `hdetail-${idx}`;
  const statusBadge = `<span class="history-status-badge ${e.status}">${historyStatusLabel(e.status)}</span>`;
  const locClass = e.location || '';
  const cov = Number(e.coverage_percent || 0);
  const covTxt = Number.isFinite(cov) ? `${cov.toLocaleString(historyLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : `0${historyLocale() === 'de-DE' ? ',' : '.'}0%`;
  const failureKey = `restoreTests.failures.${e.failure_code || 'RT_UNKNOWN'}`;
  const failureTranslation = window.BBUI?.components?.i18n?.t?.(failureKey) || failureKey;
  const detailError = (e.status === 'failed' || e.status === 'unavailable' || e.status === 'error')
    ? (failureTranslation === failureKey
      ? window.BBUI?.components?.i18n?.t?.('restoreTests.failures.RT_UNKNOWN') || ''
      : failureTranslation)
    : '';

  return `
    <tr id="${rowId}" class="history-row history-restore-row" data-history-action="toggle-detail" data-row-id="${rowId}" data-detail-id="${detailId}">
      <td><svg class="history-chevron" id="chev-${idx}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg></td>
      <td style="white-space:nowrap;color:var(--text-primary)">${escHtml(e.date || '—')} <span style="color:var(--text-muted)">${escHtml(e.time || '')}</span></td>
      <td><span class="history-type-badge">RESTORE TEST</span></td>
      <td><span class="history-loc-chip ${locClass}">${escHtml(historyLocationLabel(e.location))}</span></td>
      <td>${escHtml(e.duration_fmt || '–')}</td>
      <td>—</td>
      <td>${escHtml(covTxt)}</td>
      <td>${statusBadge}</td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="8">
        ${detailError ? `<div class="history-error-msg">${escHtml(historyT('errorPrefix'))}${escHtml(detailError)}</div>` : ''}
        <div class="history-detail-panel">
          ${detailGroup(historyT('reportId'), e.report_id)}
          ${detailGroup(historyT('job'), e.job_key)}
          ${detailGroup(historyT('archive'), e.archive_name)}
          ${detailGroup(historyT('locationDetail'), historyLocationLabel(e.location))}
          ${detailGroup(historyT('level'), e.test_level != null ? `L${e.test_level}` : null)}
          ${detailGroup(historyT('start'), e.start_ts)}
          ${detailGroup(historyT('end'), e.end_ts || e.timestamp)}
          ${detailGroup(historyT('overallStatus'), e.overall_status || historyStatusLabel(e.status))}
          ${detailGroup(historyT('validUntil'), e.valid_until)}
          ${detailGroup(historyT('coverage'), `${covTxt}${e.coverage_basis ? ` (${e.coverage_basis})` : ''}`)}
          ${detailGroup(historyT('failureCode'), e.failure_code)}
        </div>
        ${renderRestoreReportSteps(e.steps)}
      </td>
    </tr>`;
}

function renderRestoreReportSteps(steps) {
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) return '';
  const list = rows.map((s, i) => {
    const ms = Number(s.duration_ms || 0);
    const dur = ms > 0 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : '—';
    const label = restoreStepLabel(String(s.step_id || ''));
    const st = String(s.status || '').toLowerCase();
    const statusText = st === 'passed' ? historyT('stepPassed') : (st === 'failed' ? historyT('stepFailed') : (st === 'not_tested' ? historyT('stepNotTested') : st));
    return `<tr>
      <td>${i + 1}</td>
      <td>${escHtml(label)}</td>
      <td>${escHtml(statusText)}</td>
      <td>${escHtml(dur)}</td>
      <td>${escHtml(`${label}: ${statusText}`)}</td>
      <td style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all">${escHtml(s.command || '—')}</td>
    </tr>`;
  }).join('');
  return `
    <div style="margin-top:10px">
      <div class="history-detail-label" style="margin-bottom:6px">${escHtml(historyT('testSteps'))}</div>
      <table class="history-table" style="margin-bottom:0">
        <thead><tr><th>#</th><th>${escHtml(historyT('step'))}</th><th>${escHtml(historyT('status'))}</th><th>${escHtml(historyT('duration'))}</th><th>${escHtml(historyT('note'))}</th><th>${escHtml(historyT('command'))}</th></tr></thead>
        <tbody>${list}</tbody>
      </table>
    </div>`;
}

function onHistoryContentClick(event) {
  const actionEl = event.target.closest('[data-history-action]');
  if (!actionEl) return;
  const action = actionEl.dataset.historyAction || '';
  if (action === 'toggle-detail') {
    const rowId = actionEl.dataset.rowId || '';
    const detailId = actionEl.dataset.detailId || '';
    return toggleHistoryDetail(rowId, detailId);
  }
  if (action === 'open-log') {
    event.stopPropagation();
    const logFile = actionEl.dataset.logFile || '';
    if (logFile) window.BBUI?.components?.logViewer?.open?.(logFile);
  }
  if (action === 'page-prev') {
    historyState.page = Math.max(1, (historyState.page || 1) - 1);
    return refreshHistory();
  }
  if (action === 'page-next') {
    historyState.page = (historyState.page || 1) + 1;
    return refreshHistory();
  }
}

function toggleHistoryDetail(rowId, detailId) {
  const detail = document.getElementById(detailId);
  const row    = document.getElementById(rowId);
  const idx    = detailId.replace('hdetail-', '');
  const chev   = document.getElementById('chev-' + idx);
  if (!detail) return;
  const open = detail.style.display !== 'none';
  detail.style.display = open ? 'none' : 'table-row';
  row?.classList.toggle('history-expanded', !open);
  chev?.classList.toggle('open', !open);
}

function detailGroup(label, value) {
  if (value == null || value === '') return '';
  return `
    <div class="history-detail-group">
      <div class="history-detail-label">${escHtml(label)}</div>
      <div class="history-detail-value">${escHtml(String(value))}</div>
    </div>`;
}

function historyStatusLabel(s) {
  return { success: historyT('statusSuccess'), skipped: historyT('statusSkipped'), warning: historyT('statusWarning'), error: historyT('statusError') }[s] || s;
}

function historyTypeLabel(t) {
  return { flash: 'FLASH', appdata: 'APPDATA', photos: 'PHOTOS', VMs: 'VMs', vms: 'VMs', sonstiges: historyT('otherShort'), restore_test: 'RESTORE TEST' }[t] || (t || '').toUpperCase();
}

function historyLocationLabel(location) {
  const key = { local: 'jobs.locationLocal', usb: 'jobs.locationUsb', smb: 'jobs.locationSmb', storagebox: 'jobs.locationStoragebox' }[location];
  return key ? window.BBUI?.components?.i18n?.t?.(key) || location : location || '–';
}

function restoreStepLabel(stepId) {
  return {
    repo_reachable: historyT('stepRepoReachable'),
    archive_readable: historyT('stepArchiveReadable'),
    metadata_check: historyT('stepMetadataCheck'),
    restore_probe: historyT('stepRestoreProbe'),
    integrity_check: historyT('stepIntegrityCheck'),
    cleanup: historyT('stepCleanup'),
  }[stepId] || stepId;
}

window.addEventListener?.('bbui:language-changed', () => {
  if (historyState.loaded && historyState.data) renderHistory(historyState.data);
});
