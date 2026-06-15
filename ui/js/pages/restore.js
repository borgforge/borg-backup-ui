'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// BROWSE & RESTORE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.restoreState = window.BBUI.restoreState || {
  step: 1,
  job: '',
  archive: '',
  path: '',
  selectedPath: '',
  selectedName: '',
  selectedType: '',
  precheck: null,
  targetSuggestTimer: null,
  targetSuggestReq: 0,
  targetSuggestCache: new Map(),
  confirmResolver: null,
  downloadConfirmResolver: null,
  activeRestoreId: '',
  restorePollTimer: null,
  autoPrecheckKey: '',
  completed: false,
};
const restoreState = window.BBUI.restoreState;

function restoreSetStep(step) {
  const next = Math.max(1, Math.min(5, Number(step) || 1));
  restoreState.step = next;
  for (let i = 1; i <= 5; i++) {
    const panel = document.getElementById(`restore-step-panel-${i}`);
    if (panel) panel.style.display = i === next ? '' : 'none';
    const badge = document.getElementById(`restore-step-badge-${i}`);
    if (badge) {
      badge.style.opacity = i === next ? '1' : '0.55';
      badge.style.borderColor = i === next ? 'var(--accent)' : '';
      badge.style.color = i === next ? 'var(--accent)' : '';
      badge.style.background = i === next ? 'var(--state-info-dim)' : '';
    }
  }
  _restoreMsg('');
  const backBtn = document.getElementById('restore-step-back-btn');
  const nextBtn = document.getElementById('restore-step-next-btn');
  if (backBtn) {
    backBtn.disabled = next <= 1 && !restoreState.completed;
    backBtn.textContent = (next === 5 && restoreState.completed) ? 'Schließen' : 'Zurück';
  }
  if (nextBtn) {
    nextBtn.style.display = next >= 5 ? 'none' : '';
    nextBtn.textContent = next === 4 ? 'Zur Prüfung' : 'Weiter';
  }
  if (next === 5) {
    restoreEnsureAutoPrecheck();
  }
}

function restoreCanAdvance(step) {
  if (step === 1) return !!restoreState.job;
  if (step === 2) return !!restoreState.archive;
  if (step === 3) return !!restoreState.selectedPath;
  if (step === 4) return !!document.getElementById('restore-target-path')?.value?.trim();
  return true;
}

function restoreStepNext() {
  if (!restoreCanAdvance(restoreState.step)) {
    if (restoreState.step === 1) return _restoreMsg('Bitte zuerst einen Job auswählen.', true);
    if (restoreState.step === 2) return _restoreMsg('Bitte zuerst ein Archiv auswählen.', true);
    if (restoreState.step === 3) return _restoreMsg('Bitte zuerst ein Element auswählen.', true);
    if (restoreState.step === 4) return _restoreMsg('Bitte zuerst einen Zielordner angeben.', true);
  }
  restoreSetStep(restoreState.step + 1);
}

function restoreStepBack() {
  if (restoreState.step === 5 && restoreState.completed) {
    restoreReloadWizard();
    return;
  }
  restoreSetStep(restoreState.step - 1);
}

function restoreReloadWizard() {
  restoreState.completed = false;
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.archive = '';
  restoreState.job = '';
  restoreState.path = '';
  _stopRestorePolling();
  const out = document.getElementById('restore-precheck-output');
  if (out) out.textContent = '';
  hideEl('restore-assist-msg');
  restoreInit();
}

function _restoreSelectionReady() {
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  return !!(restoreState.job && restoreState.archive && restoreState.selectedPath && target);
}

function _restoreRenderSelectionSummary() {
  const jobSel = document.getElementById('restore-job-sel');
  const jobText = jobSel?.selectedOptions?.[0]?.textContent?.trim() || '—';
  const archive = restoreState.archive || '—';
  const selectedCount = restoreState.selectedPath ? 1 : 0;
  const target = document.getElementById('restore-target-path')?.value?.trim() || '—';
  const jobEl = document.getElementById('restore-summary-job');
  const archEl = document.getElementById('restore-summary-archive');
  const countEl = document.getElementById('restore-summary-count');
  const targetEl = document.getElementById('restore-summary-target');
  if (jobEl) jobEl.textContent = jobText;
  if (archEl) archEl.textContent = archive;
  if (countEl) countEl.textContent = String(selectedCount);
  if (targetEl) targetEl.textContent = target;
}

function _restoreRenderSelectedBox() {
  const typeEl = document.getElementById('restore-selected-type');
  const pathEl = document.getElementById('restore-selected-path');
  const hintEl = document.getElementById('restore-selected-hint');
  const type = restoreState.selectedType === 'd' ? 'Verzeichnis' : (restoreState.selectedType === 'f' ? 'Datei' : '—');
  const hint = restoreState.selectedType === 'd'
    ? 'Verzeichnis inkl. Inhalt wird wiederhergestellt.'
    : (restoreState.selectedType === 'f' ? 'Eine einzelne Datei wird wiederhergestellt.' : 'Noch kein Element ausgewählt.');
  if (typeEl) typeEl.textContent = type;
  if (pathEl) pathEl.textContent = restoreState.selectedPath || '—';
  if (hintEl) hintEl.textContent = hint;
}

function _stopRestorePolling() {
  if (restoreState.restorePollTimer) {
    clearTimeout(restoreState.restorePollTimer);
    restoreState.restorePollTimer = null;
  }
}

async function _pollRestoreState(restoreId) {
  const out = document.getElementById('restore-precheck-output');
  if (!restoreId) return;
  try {
    const res = await fetch(`/api/restore/state?restore_id=${encodeURIComponent(restoreId)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data?.error || `HTTP ${res.status}`);
    if (restoreState.activeRestoreId !== restoreId) return;

    const lines = Array.isArray(data.lines) ? data.lines : [];
    const phase = data.phase || 'running';
    if (out) {
      out.textContent = [
        `Restore-ID: ${restoreId}`,
        `Status: ${data.state || 'running'}`,
        `Phase: ${phase}`,
        '',
        ...lines,
      ].join('\n');
      out.scrollTop = out.scrollHeight;
    }

    if (data.state === 'done') {
      _stopRestorePolling();
      _setRestoreAssistBusy(false);
      restoreState.completed = true;
      restoreUpdateConfirmState();
      restoreSetStep(5);
      if (data.skipped) {
        showMsg('restore-assist-msg', 'warning', `Übersprungen: ${data.reason || 'Zieldatei existiert'}`);
      } else {
        showMsg('restore-assist-msg', 'success', `Restore erfolgreich: ${data.destination_path || ''}`);
      }
      return;
    }
    if (data.state === 'error') {
      _stopRestorePolling();
      _setRestoreAssistBusy(false);
      restoreUpdateConfirmState();
      showMsg('restore-assist-msg', 'error', `Restore fehlgeschlagen: ${data.error || 'Unbekannter Fehler'}`);
      return;
    }

    restoreState.restorePollTimer = setTimeout(() => _pollRestoreState(restoreId), 1500);
  } catch (err) {
    restoreState.restorePollTimer = setTimeout(() => _pollRestoreState(restoreId), 2000);
  }
}

function _restoreBindTargetAutocomplete() {
  const input = document.getElementById('restore-target-path');
  const datalist = document.getElementById('restore-target-suggestions');
  if (!input || !datalist || input.dataset.autocompleteBound === '1') return;
  input.dataset.autocompleteBound = '1';

  const applyOptions = (dirs) => {
    datalist.innerHTML = (dirs || []).map(p => `<option value="${escHtml(p)}"></option>`).join('');
  };

  const loadSuggestions = async (rawValue) => {
    const value = String(rawValue ?? input.value ?? '').trim();
    const prefix = value || '/mnt/user/';
    if (!prefix.startsWith('/mnt/user')) {
      applyOptions([]);
      return;
    }
    if (restoreState.targetSuggestCache.has(prefix)) {
      applyOptions(restoreState.targetSuggestCache.get(prefix));
      return;
    }
    const reqId = ++restoreState.targetSuggestReq;
    try {
      const res = await fetch(`/api/restore/target-dirs?prefix=${encodeURIComponent(prefix)}&limit=30`, { credentials: 'include' });
      const data = await res.json();
      if (!res.ok || data.error) return;
      if (reqId !== restoreState.targetSuggestReq) return;
      const dirs = (data.dirs || []).map(d => d.path).filter(Boolean);
      restoreState.targetSuggestCache.set(prefix, dirs);
      applyOptions(dirs);
    } catch (_) {
      // Silent fail: autocomplete is optional UX.
    }
  };

  input.addEventListener('focus', () => {
    if (!input.value.trim()) input.value = '/mnt/user/';
    loadSuggestions(input.value);
  });
  input.addEventListener('input', () => {
    if (restoreState.targetSuggestTimer) clearTimeout(restoreState.targetSuggestTimer);
    const current = input.value;
    restoreState.targetSuggestTimer = setTimeout(() => loadSuggestions(current), 120);
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    const v = String(input.value || '').trim();
    if (!v.startsWith('/mnt/user')) return;
    const options = Array.from(datalist.options || []);
    const exact = options.find(o => o.value.replace(/\/+$/, '') === v.replace(/\/+$/, ''));
    if (exact && !v.endsWith('/')) {
      ev.preventDefault();
      input.value = `${v}/`;
      loadSuggestions(input.value);
    }
  });
}

async function restoreInit() {
  restoreState.completed = false;
  const sel = document.getElementById('restore-job-sel');
  sel.innerHTML = '<option value="">— Job wählen —</option>';
  const wizard = document.getElementById('restore-wizard');
  if (wizard) wizard.style.display = '';
  const empty = document.getElementById('restore-empty');
  if (empty) empty.style.display = 'none';
  restoreSetStep(1);
  _restoreMsg('');
  _restoreBindTargetAutocomplete();
  const targetInput = document.getElementById('restore-target-path');
  if (targetInput && !targetInput.value.trim()) targetInput.value = '/mnt/user/';
  _restoreRenderSelectionSummary();
  _restoreRenderSelectedBox();

  try {
    const jobsRes = await fetch('/api/jobs', { credentials: 'include' });
    const jobsData = await jobsRes.json();
    const jobs = (jobsData.jobs || []).filter(j => !j.is_utility);

    for (const job of jobs) {
      if (job.is_utility) continue;
      const opt = document.createElement('option');
      opt.value = job.key;
      opt.textContent = job.display_name || job.name || job.key;
      sel.appendChild(opt);
    }

    if (!jobs.length) {
      const checkRes = await fetch('/api/storage/check/jobs', { credentials: 'include' });
      if (checkRes.ok) {
        const checkData = await checkRes.json();
        for (const job of (checkData.jobs || [])) {
          const opt = document.createElement('option');
          opt.value = job.key;
          opt.textContent = job.name || job.key;
          sel.appendChild(opt);
        }
      }
    }
  } catch (e) {
    _restoreMsg('Fehler beim Laden der Jobs: ' + e.message, true);
  }
}

async function restoreLoadArchives() {
  const jobKey = document.getElementById('restore-job-sel').value;
  restoreState.job = jobKey;
  restoreState.archive = '';
  restoreState.path = '';
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.autoPrecheckKey = '';
  const sel = document.getElementById('restore-archive-sel');
  if (sel) sel.innerHTML = '<option value="">— Archiv wählen —</option>';
  _restoreMsg('');

  if (!jobKey) {
    _restoreRenderSelectionSummary();
    _restoreRenderSelectedBox();
    return;
  }
  _restoreMsg('Lade Archive...');

  try {
    const data = await (await fetch(`/api/restore/archives?job=${encodeURIComponent(jobKey)}`, { credentials: 'include' })).json();
    if (data.error) { _restoreMsg('Fehler: ' + data.error, true); return; }

    const sel = document.getElementById('restore-archive-sel');
    sel.innerHTML = '<option value="">— Archiv wählen —</option>';
    for (const a of (data.archives || [])) {
      const opt = document.createElement('option');
      opt.value = a.name;
      const date = a.start ? a.start.substring(0, 19).replace('T', ' ') : '';
      opt.textContent = a.name + (date ? '  (' + date + ')' : '');
      sel.appendChild(opt);
    }
    _restoreRenderSelectionSummary();
    _restoreMsg('');
  } catch (e) {
    _restoreMsg('Fehler: ' + e.message, true);
  }
}

async function restoreBrowse(path) {
  const jobKey = restoreState.job;
  const archive = document.getElementById('restore-archive-sel').value;
  if (!archive) return;

  restoreState.archive = archive;
  restoreState.path = path;
  _restoreRenderSelectionSummary();
  _restoreMsg('');
  const browser = document.getElementById('restore-browser');
  const filelist = document.getElementById('restore-filelist');
  if (browser) browser.style.display = '';
  if (filelist) {
    filelist.innerHTML = `
      <div class="loading-spinner" style="padding:22px 16px">
        <div class="spinner"></div>
        <span>Lade Dateien...</span>
      </div>`;
  }

  try {
    const url = `/api/restore/files?job=${encodeURIComponent(jobKey)}&archive=${encodeURIComponent(archive)}&path=${encodeURIComponent(path)}`;
    const data = await (await fetch(url, { credentials: 'include' })).json();
    if (data.error) { _restoreMsg('Fehler: ' + data.error, true); return; }

    _restoreMsg('');
    _restoreRenderBreadcrumb(path);
    _restoreRenderFiles(data.files || []);
  } catch (e) {
    _restoreMsg('Fehler: ' + e.message, true);
  }
}

function _restoreRenderBreadcrumb(path) {
  const parts = path ? path.split('/') : [];
  let html = `<span class="bc-link" data-restore-action="browse" data-path="/">/</span>`;
  let cum = '';
  for (let i = 0; i < parts.length; i++) {
    cum = parts.slice(0, i + 1).join('/');
    const p = cum;
    html += ` / <span class="${i === parts.length - 1 ? 'bc-current' : 'bc-link'}" data-restore-action="browse" data-path="${escHtml(p)}">${escHtml(parts[i])}</span>`;
  }
  document.getElementById('restore-breadcrumb').innerHTML = html;
}

function _restoreRenderFiles(files) {
  const el = document.getElementById('restore-filelist');
  if (!files.length) {
    el.innerHTML = '<div class="restore-empty">Keine Dateien</div>';
    return;
  }

  let rows = '';
  for (const f of files) {
    const isSelected = String(f.path || '') === String(restoreState.selectedPath || '');
    const icon = f.type === 'd' ? '📁' : (f.type === 'l' ? '🔗' : '📄');
    const size = f.type === 'd' ? '—' : _restoreFmtSize(f.size);
    const mtime = f.mtime ? f.mtime.substring(0, 19).replace('T', ' ') : '';
    const nameCell = f.type === 'd'
      ? `<span class="restore-dir-link" data-restore-action="browse" data-path="${escHtml(f.path)}">${icon} ${escHtml(f.name)}</span>`
      : `<span>${icon} ${escHtml(f.name)}</span>`;

    rows += `<tr class="${isSelected ? 'restore-row-selected' : ''}">
      <td class="restore-col-name">${nameCell}</td>
      <td class="restore-col-size">${size}</td>
      <td class="restore-col-date">${mtime}</td>
      <td class="restore-col-action">
        <button class="restore-icon-btn" data-restore-action="download" data-path="${escHtml(f.path)}" title="Herunterladen" aria-label="Herunterladen">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4v10m0 0l-4-4m4 4l4-4M5 20h14"/>
          </svg>
        </button>
        <button class="restore-icon-btn ${isSelected ? 'restore-icon-btn-selected' : ''}" data-restore-action="select" data-path="${escHtml(f.path)}" data-name="${escHtml(f.name)}" data-type="${escHtml(f.type || '')}" title="${isSelected ? 'Ausgewählt' : 'Auswählen'}" aria-label="${isSelected ? 'Ausgewählt' : 'Auswählen'}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 6 9 17l-5-5"/>
          </svg>
        </button>
      </td>
    </tr>`;
  }

  el.innerHTML = `<table class="restore-table">
    <thead><tr>
      <th>Name</th><th>Größe</th><th>Datum</th><th></th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function onRestoreBrowserClick(event) {
  const el = event.target.closest('[data-restore-action]');
  if (!el) return;
  const action = el.dataset.restoreAction || '';
  const path = (el.dataset.path || '').replace(/^\/$/, '');
  const name = el.dataset.name || '';
  const type = el.dataset.type || '';
  if (action === 'browse') return restoreBrowse(path);
  if (action === 'download') return restoreDownload(path);
  if (action === 'select' && path && path === restoreState.selectedPath) return restoreClearSelection();
  if (action === 'select') return restorePrepare(path, name, type);
}

async function restoreDownload(path) {
  const fileList = document.getElementById('restore-filelist');
  const originalHtml = fileList ? fileList.innerHTML : '';
  _restoreMsg('Prüfe Downloadgröße...');
  if (fileList) {
    fileList.innerHTML = `
      <div class="loading-spinner" style="padding:22px 16px">
        <div class="spinner"></div>
        <span>Prüfe Downloadgröße...</span>
      </div>`;
  }
  try {
    const baseParams = `job=${encodeURIComponent(restoreState.job)}&archive=${encodeURIComponent(restoreState.archive)}&path=${encodeURIComponent(path)}`;
    const checkRes = await fetch(`/api/restore/download-check?${baseParams}`, { credentials: 'include' });
    const checkData = await checkRes.json();
    if (!checkRes.ok || checkData?.error) {
      throw new Error(checkData?.error || `HTTP ${checkRes.status}`);
    }

    if (checkData.action === 'block') {
      if (fileList) fileList.innerHTML = originalHtml;
      _restoreMsg(checkData.message || 'Download blockiert.', 'warn');
      showMsg('restore-assist-msg', 'error', checkData.message || 'Download blockiert.');
      return;
    }

    let url = `/api/restore/download?${baseParams}`;
    if (checkData.action === 'confirm') {
      if (fileList) fileList.innerHTML = originalHtml;
      _restoreMsg('');
      const ok = await openRestoreDownloadConfirmModal(checkData.message || 'Großer Download.');
      if (!ok) return;
      url += '&confirm_large=1';
    }
    if (fileList) fileList.innerHTML = originalHtml;
    _restoreMsg('Download startet...');
    window.location.href = url;
  } catch (e) {
    if (fileList) fileList.innerHTML = originalHtml;
    _restoreMsg(`Download fehlgeschlagen: ${e.message}`, true);
    showMsg('restore-assist-msg', 'error', `Download fehlgeschlagen: ${e.message}`);
  }
}

function restorePrepare(path, name, type) {
  restoreState.selectedPath = path || '';
  restoreState.selectedName = name || '';
  restoreState.selectedType = type === 'd' ? 'd' : 'f';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const target = document.getElementById('restore-target-path');
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  if (src) src.value = path || '';
  if (out) out.textContent = '';
  if (startBtn) startBtn.disabled = true;
  if (confirmCheck) confirmCheck.checked = false;
  hideEl('restore-assist-msg');
  _restoreRenderSelectedBox();
  // Auswahl bleibt in Schritt 3 sichtbar; Wechsel nach Schritt 4 erfolgt über "Weiter".
  restoreSetStep(Math.max(3, restoreState.step));
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
  _restoreMsg('Element ausgewählt. Mit "Weiter" zu Ziel & Modus.', false);
}

function restoreClearSelection() {
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  restoreState.activeRestoreId = '';
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const targetInput = document.getElementById('restore-target-path');
  const modeSel = document.getElementById('restore-conflict-mode');
  const dryRun = document.getElementById('restore-dry-run');
  const preserveOwner = document.getElementById('restore-preserve-owner');
  const startBtn = document.getElementById('restore-start-btn');
  if (src) src.value = '';
  if (out) out.textContent = '';
  if (confirmCheck) confirmCheck.checked = false;
  if (targetInput) targetInput.value = '/mnt/user/';
  if (modeSel) modeSel.value = 'skip';
  if (dryRun) dryRun.checked = true;
  if (preserveOwner) preserveOwner.checked = false;
  if (startBtn) startBtn.disabled = true;
  _stopRestorePolling();
  hideEl('restore-assist-msg');
  _restoreMsg('');
  _restoreRenderSelectedBox();
  _restoreRenderSelectionSummary();
  restoreSetStep(3);
  restoreUpdateConfirmState();
  if (restoreState.archive) {
    restoreBrowse(restoreState.path || '');
  }
}

function restoreUpdateConfirmState() {
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const enabled = !!(_restoreSelectionReady() && restoreState.precheck && restoreState.precheck.ok && confirmCheck?.checked);
  if (startBtn) startBtn.disabled = !enabled;
}

function _isAllowedRestoreTarget(target) {
  const t = String(target || '').trim();
  return t === '/mnt/user' || t.startsWith('/mnt/user/');
}

function _setRestoreAssistBusy(busy) {
  const preBtn = document.getElementById('restore-precheck-btn');
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const modeSel = document.getElementById('restore-conflict-mode');
  const targetInput = document.getElementById('restore-target-path');
  const dryRunCheck = document.getElementById('restore-dry-run');
  if (preBtn) preBtn.disabled = !!busy;
  if (startBtn) startBtn.disabled = !!busy || startBtn.disabled;
  if (confirmCheck) confirmCheck.disabled = !!busy;
  if (modeSel) modeSel.disabled = !!busy;
  if (targetInput) targetInput.disabled = !!busy;
  if (dryRunCheck) dryRunCheck.disabled = !!busy;
}

async function restoreRunPrecheck() {
  hideEl('restore-assist-msg');
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const dryRun = !!document.getElementById('restore-dry-run')?.checked;
  const out = document.getElementById('restore-precheck-output');
  const confirmCheck = document.getElementById('restore-confirm-check');
  if (confirmCheck) confirmCheck.checked = false;
  if (out) out.textContent = 'Precheck läuft...';
  _setRestoreAssistBusy(true);
  if (!restoreState.job || !restoreState.archive || !source || !target) {
    showMsg('restore-assist-msg', 'error', 'Bitte zuerst ein Archiv auswählen, ein Element markieren und einen Zielordner angeben.');
    if (out) out.textContent = '';
    _setRestoreAssistBusy(false);
    return;
  }
  if (!_isAllowedRestoreTarget(target)) {
    showMsg('restore-assist-msg', 'error', 'Zielpfad muss unter /mnt/user liegen.');
    if (out) out.textContent = '';
    _setRestoreAssistBusy(false);
    return;
  }
  try {
    const res = await fetch('/api/restore/precheck', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_key: restoreState.job,
        archive: restoreState.archive,
        source_path: source,
        target_dir: target,
        conflict_mode: mode,
        dry_run: dryRun,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
    restoreState.precheck = data;
    const combinedDryRun = [data.dry_run_stdout || '', data.dry_run_stderr || '']
      .filter(Boolean)
      .join('\n')
      .trim();
    const lines = [
      `Archiv: ${data.archive}`,
      `Quellpfad: ${data.source_path}`,
      `Zielpfad: ${data.target_dir}`,
      `Konfliktmodus: ${data.conflict_mode}`,
      `Dry-Run: ${data.dry_run ? 'ja' : 'nein'} (Exit ${data.dry_run_exit_code})`,
      `Zieldatei: ${data.destination_path}`,
      `Existiert bereits: ${data.destination_exists ? 'ja' : 'nein'}`,
      `Mountpoint: ${data.target_mountpoint}`,
      `Freier Platz: ${_restoreFmtSize(data.target_free_bytes || 0)}`,
      '',
      '[Dry-Run Ausgabe]',
      combinedDryRun || '(leer)',
    ];
    if (out) out.textContent = lines.join('\n');
    showMsg('restore-assist-msg', data.ok ? 'success' : 'error', data.ok ? 'Precheck erfolgreich. Bitte Zusammenfassung prüfen und bestätigen.' : 'Precheck fehlgeschlagen.');
  } catch (err) {
    restoreState.precheck = null;
    if (out) out.textContent = '';
    showMsg('restore-assist-msg', 'error', `Precheck fehlgeschlagen: ${err.message}`);
  } finally {
    _setRestoreAssistBusy(false);
    restoreUpdateConfirmState();
  }
}

function _currentPrecheckKey() {
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const dryRun = !!document.getElementById('restore-dry-run')?.checked;
  return JSON.stringify([restoreState.job, restoreState.archive, source, target, mode, dryRun]);
}

function restoreEnsureAutoPrecheck() {
  const key = _currentPrecheckKey();
  if (!restoreCanAdvance(4)) {
    restoreState.precheck = null;
    restoreUpdateConfirmState();
    return;
  }
  if (restoreState.precheck?.ok && restoreState.autoPrecheckKey === key) {
    restoreUpdateConfirmState();
    return;
  }
  restoreState.autoPrecheckKey = key;
  restoreRunPrecheck();
}

async function restoreStart() {
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const preserveOwner = !!document.getElementById('restore-preserve-owner')?.checked;
  const confirmCheck = !!document.getElementById('restore-confirm-check')?.checked;
  if (!confirmCheck || !restoreState.precheck?.ok) {
    showMsg('restore-assist-msg', 'error', 'Bitte zuerst erfolgreichen Precheck ausführen und bestätigen.');
    return;
  }
  if (!_isAllowedRestoreTarget(target)) {
    showMsg('restore-assist-msg', 'error', 'Zielpfad muss unter /mnt/user liegen.');
    return;
  }
  const summary = [
    `Archiv: ${restoreState.archive}`,
    `Quellpfad: ${source}`,
    `Zielpfad: ${target}`,
    `Konfliktmodus: ${mode}`,
    `Owner/Group: ${preserveOwner ? 'aus Backup beibehalten' : 'an Zielverzeichnis anpassen'}`,
  ].join('\n');
  const confirmed = await openRestoreConfirmModal(summary);
  if (!confirmed) return;
  const out = document.getElementById('restore-precheck-output');
  if (out) {
    out.textContent = [
      'Restore läuft...',
      `Archiv: ${restoreState.archive}`,
      `Quelle: ${source}`,
      `Ziel: ${target}`,
      `Modus: ${mode}`,
      `Owner/Group: ${preserveOwner ? 'aus Backup beibehalten' : 'an Zielverzeichnis anpassen'}`,
      '',
      'Bitte warten, bis der Restore abgeschlossen ist.'
    ].join('\n');
  }
  showMsg('restore-assist-msg', 'warning', 'Restore läuft…');
  _setRestoreAssistBusy(true);
  _stopRestorePolling();
  restoreState.activeRestoreId = '';
  try {
    const res = await fetch('/api/restore/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirm: true,
        job_key: restoreState.job,
        archive: restoreState.archive,
        source_path: source,
        target_dir: target,
        conflict_mode: mode,
        preserve_owner: preserveOwner,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
    const restoreId = String(data.restore_id || '').trim();
    if (!restoreId) {
      throw new Error('Keine restore_id erhalten');
    }
    restoreState.activeRestoreId = restoreId;
    restoreState.completed = false;
    if (out) {
      out.textContent += `\n\nRestore-ID: ${restoreId}\nStatus: gestartet`;
    }
    _pollRestoreState(restoreId);
  } catch (err) {
    _stopRestorePolling();
    restoreState.activeRestoreId = '';
    _setRestoreAssistBusy(false);
    restoreUpdateConfirmState();
    showMsg('restore-assist-msg', 'error', `Restore fehlgeschlagen: ${err.message}`);
    if (out) out.textContent += `\n\nErgebnis: Fehler\n${err.message}`;
  }
}

function openRestoreConfirmModal(summaryText) {
  return new Promise((resolve) => {
    const modal = document.getElementById('restore-confirm-modal');
    const summary = document.getElementById('restore-confirm-summary');
    if (!modal || !summary) {
      resolve(window.confirm(`Restore wirklich starten?\n\n${summaryText}`));
      return;
    }
    restoreState.confirmResolver = resolve;
    summary.textContent = summaryText || '';
    modal.classList.remove('hidden');
  });
}

function closeRestoreConfirmModal(confirmed = false) {
  const modal = document.getElementById('restore-confirm-modal');
  if (modal) modal.classList.add('hidden');
  if (restoreState.confirmResolver) {
    const done = restoreState.confirmResolver;
    restoreState.confirmResolver = null;
    done(!!confirmed);
  }
}

function openRestoreDownloadConfirmModal(messageText) {
  return new Promise((resolve) => {
    const modal = document.getElementById('restore-download-confirm-modal');
    const msg = document.getElementById('restore-download-confirm-message');
    if (!modal || !msg) {
      resolve(window.confirm(messageText || 'Großer Download. Fortfahren?'));
      return;
    }
    restoreState.downloadConfirmResolver = resolve;
    msg.textContent = messageText || 'Großer Download. Fortfahren?';
    modal.classList.remove('hidden');
  });
}

function closeRestoreDownloadConfirmModal(confirmed = false) {
  const modal = document.getElementById('restore-download-confirm-modal');
  if (modal) modal.classList.add('hidden');
  if (restoreState.downloadConfirmResolver) {
    const done = restoreState.downloadConfirmResolver;
    restoreState.downloadConfirmResolver = null;
    done(!!confirmed);
  }
}

function _restoreFmtSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(i > 0 ? 1 : 0) + '\u00a0' + units[i];
}

function _restoreMsg(msg, level = 'info') {
  const el = document.getElementById('restore-msg');
  if (!msg) {
    el.classList.add('hidden');
    el.classList.remove('restore-msg-error', 'restore-msg-warn', 'restore-msg-info');
    el.textContent = '';
    return;
  }
  el.classList.remove('hidden');
  el.classList.remove('restore-msg-error', 'restore-msg-warn', 'restore-msg-info');
  const resolved = (level === true) ? 'error' : (level === false ? 'info' : String(level || 'info'));
  if (resolved === 'error') el.classList.add('restore-msg-error');
  else if (resolved === 'warn') el.classList.add('restore-msg-warn');
  else el.classList.add('restore-msg-info');
  el.textContent = msg;
}

function restoreTargetInputChanged() {
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
}

function restorePrecheckInputsChanged() {
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  restoreUpdateConfirmState();
  if (restoreState.step === 5) {
    restoreEnsureAutoPrecheck();
  }
}
