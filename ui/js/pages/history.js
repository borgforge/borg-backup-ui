// ── History ───────────────────────────────────────────────────────────────────

window.BBUI = window.BBUI || {};
window.BBUI.historyState = window.BBUI.historyState || { loaded: false, data: null, page: 1, perPage: 20 };
const historyState = window.BBUI.historyState;

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
    if (data.error) throw new Error(data.error);
    historyState.data   = data;
    historyState.loaded = true;
    renderHistory(data);
    hideEl('history-message');
  } catch (e) {
    showMsg('history-message', 'error', 'Fehler: ' + e.message);
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
  if (countEl) countEl.textContent = `${data.total} Einträge`;

  const el = document.getElementById('history-content');
  if (!el) return;

  if (!data.entries || data.entries.length === 0) {
    el.innerHTML = `<div class="history-empty">Keine Backup-Einträge gefunden.</div>`;
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
          <th>Datum / Zeit</th>
          <th>Typ</th>
          <th>Ort</th>
          <th>Dauer</th>
          <th>Originalgröße</th>
          <th>Dedupliziert</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="history-tbody">
        ${rows}
      </tbody>
    </table>
    <div class="history-pagination" style="display:flex;justify-content:flex-end;gap:8px;align-items:center;margin-top:10px">
      <span style="color:var(--text-muted);font-size:12px">Seite ${page} / ${totalPages}</span>
      <button class="btn btn-secondary btn-sm" data-history-action="page-prev" ${prevDisabled}>Zurück</button>
      <button class="btn btn-secondary btn-sm" data-history-action="page-next" ${nextDisabled}>Weiter</button>
    </div>`;
}

function renderHistoryRow(e, idx) {
  if (e.entry_kind === 'restore_test_report') return renderRestoreReportRow(e, idx);
  const detailReason = e.skip_reason_text
    ? `Übersprungen: ${e.skip_reason_text}`
    : '';
  const detailError = e.error_message || detailReason;
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
      <td><span class="history-loc-chip ${locClass}">${escHtml(locLabel(e.location))}</span></td>
      <td>${escHtml(e.duration_fmt || '–')}</td>
      <td>${escHtml(e.original_size_fmt || '–')}</td>
      <td>${escHtml(e.deduplicated_size_fmt || '–')}</td>
      <td>${statusBadge}</td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="8">
        ${detailError ? `<div class="history-error-msg">${e.status === 'skipped' ? '' : 'Fehler: '}${escHtml(detailError)}</div>` : ''}
        <div class="history-detail-panel">
          ${detailGroup('Archiv', e.archive_name)}
          ${detailGroup('Komprimiert', e.compressed_size_fmt)}
          ${detailGroup('Repository-Größe', e.repository_size_fmt)}
          ${detailGroup('Dateien', e.files_count != null ? e.files_count.toLocaleString('de-DE') : null)}
          ${detailGroup('Exit-Code', e.exit_code != null ? String(e.exit_code) : null)}
          ${detailGroup('Letzter Check', e.repository_check_date)}
          ${detailGroup('Nächster Check', e.repository_next_check)}
          ${detailGroup('Check-Status', e.repository_check_status)}
          ${e.log_file ? `
          <div class="history-detail-group">
            <div class="history-detail-label">Log-Datei</div>
            <div class="history-detail-value" style="display:flex;align-items:center;gap:8px">
              <span style="color:var(--text-muted);font-size:11px" title="${escHtml(e.log_file)}">${escHtml(e.log_file.split('/').pop())}</span>
              <button class="btn btn-secondary btn-sm" data-history-action="open-log" data-log-file="${escHtml(e.log_file)}">Öffnen</button>
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
  const covTxt = Number.isFinite(cov) ? `${cov.toFixed(1).replace('.', ',')}%` : '0,0%';
  const detailError = e.failure_hint || e.error_message || '';

  return `
    <tr id="${rowId}" class="history-row history-restore-row" data-history-action="toggle-detail" data-row-id="${rowId}" data-detail-id="${detailId}">
      <td><svg class="history-chevron" id="chev-${idx}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg></td>
      <td style="white-space:nowrap;color:var(--text-primary)">${escHtml(e.date || '—')} <span style="color:var(--text-muted)">${escHtml(e.time || '')}</span></td>
      <td><span class="history-type-badge">RESTORE TEST</span></td>
      <td><span class="history-loc-chip ${locClass}">${escHtml(locLabel(e.location))}</span></td>
      <td>${escHtml(e.duration_fmt || '–')}</td>
      <td>—</td>
      <td>${escHtml(covTxt)}</td>
      <td>${statusBadge}</td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="8">
        ${detailError ? `<div class="history-error-msg">Fehler: ${escHtml(detailError)}</div>` : ''}
        <div class="history-detail-panel">
          ${detailGroup('Report-ID', e.report_id)}
          ${detailGroup('Job', e.job_key)}
          ${detailGroup('Archiv', e.archive_name)}
          ${detailGroup('Standort', e.location)}
          ${detailGroup('Level', e.test_level != null ? `L${e.test_level}` : null)}
          ${detailGroup('Start', e.start_ts)}
          ${detailGroup('Ende', e.end_ts || e.timestamp)}
          ${detailGroup('Gesamtstatus', e.overall_status || historyStatusLabel(e.status))}
          ${detailGroup('Gültig bis', e.valid_until)}
          ${detailGroup('Abdeckung', `${covTxt}${e.coverage_basis ? ` (${e.coverage_basis})` : ''}`)}
          ${detailGroup('Fehlercode', e.failure_code)}
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
    const statusText = st === 'passed' ? 'OK' : (st === 'failed' ? 'Fehler' : (st === 'not_tested' ? 'Nicht geprüft' : st));
    return `<tr>
      <td>${i + 1}</td>
      <td>${escHtml(label)}</td>
      <td>${escHtml(statusText)}</td>
      <td>${escHtml(dur)}</td>
      <td>${escHtml(s.message || '')}</td>
      <td style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all">${escHtml(s.command || '—')}</td>
    </tr>`;
  }).join('');
  return `
    <div style="margin-top:10px">
      <div class="history-detail-label" style="margin-bottom:6px">Prüfschritte</div>
      <table class="history-table" style="margin-bottom:0">
        <thead><tr><th>#</th><th>Schritt</th><th>Status</th><th>Dauer</th><th>Hinweis</th><th>Befehl</th></tr></thead>
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
  return { success: 'Erfolg', skipped: 'Übersprungen', warning: 'Warnung', error: 'Fehler' }[s] || s;
}

function historyTypeLabel(t) {
  return { flash: 'FLASH', appdata: 'APPDATA', photos: 'PHOTOS', VMs: 'VMs', vms: 'VMs', sonstiges: 'SONST.', restore_test: 'RESTORE TEST' }[t] || (t || '').toUpperCase();
}

function restoreStepLabel(stepId) {
  return {
    repo_reachable: 'Repository erreichbar',
    archive_readable: 'Archiv lesbar',
    metadata_check: 'Metadaten-Check',
    restore_probe: 'Stichprobe Restore',
    integrity_check: 'Integritätsvergleich',
    cleanup: 'Cleanup Testdaten',
  }[stepId] || stepId;
}
