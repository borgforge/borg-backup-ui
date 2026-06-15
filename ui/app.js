'use strict';

// Core state + navigation moved to ui/js/core/app-core.js (Phase D1).
// Dashboard moved to ui/js/pages/dashboard.js (Phase B).

// ── Clock ─────────────────────────────────────────────────────────────────────

function updateClock() {
  const el = document.getElementById('server-time');
  if (el) {
    el.textContent = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}

// Jobs moved to ui/js/pages/jobs.js (Phase B).
// Storage + Borg Check moved to ui/js/pages/storage.js (Phase B).

// Settings moved to ui/js/pages/settings.js (Phase B).

// History moved to ui/js/pages/history.js (Phase B).

// Log Viewer moved to ui/js/components/log-viewer.js (Phase D2).
// Theme helpers moved to ui/js/components/theme.js (Phase D2).
// Restore Tests moved to ui/js/pages/restore-tests.js (Phase B).

function _initApp() {
  window.BBUI?.components?.appBindings?.init?.();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _initApp);
else _initApp();

// Wizard moved to ui/js/pages/wizard.js (Phase B).

// Browse & Restore moved to ui/js/pages/restore.js (Phase B).

// Berichte moved to ui/js/pages/reports.js (Phase B).
