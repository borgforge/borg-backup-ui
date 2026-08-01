'use strict';

(function initThemeComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  const UI_THEME_KEY = 'bbui_theme_preference';
  let uiThemeMediaQuery = null;

  function getStoredThemePreference() {
    try {
      const p = localStorage.getItem(UI_THEME_KEY);
      return (p === 'light' || p === 'dark' || p === 'system') ? p : 'system';
    } catch (error) {
      return 'system';
    }
  }

  function resolvedTheme(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function updateThemeControls(pref) {
    const activeTheme = resolvedTheme(pref);
    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      const choice = String(button.dataset.themeChoice || '');
      const active = choice === activeTheme;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyThemePreference(pref, persist = true) {
    const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'system';
    if (persist) {
      try {
        localStorage.setItem(UI_THEME_KEY, clean);
      } catch (error) {
        // The selected theme still applies when browser storage is unavailable.
      }
    }
    document.documentElement.setAttribute('data-theme', resolvedTheme(clean));
    const sel = document.getElementById('ui-theme-select');
    if (sel) sel.value = clean;
    updateThemeControls(clean);
  }

  function initThemePreference() {
    applyThemePreference(getStoredThemePreference(), false);
    if (!uiThemeMediaQuery) {
      uiThemeMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      uiThemeMediaQuery.addEventListener?.('change', () => {
        if (getStoredThemePreference() === 'system') applyThemePreference('system', false);
      });
    }
  }

  window.BBUI.components.theme = {
    getStoredThemePreference,
    applyThemePreference,
    initThemePreference,
    updateThemeControls,
  };
})();
