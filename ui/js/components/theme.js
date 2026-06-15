'use strict';

(function initThemeComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  const UI_THEME_KEY = 'bbui_theme_preference';
  let uiThemeMediaQuery = null;

  function getStoredThemePreference() {
    const p = localStorage.getItem(UI_THEME_KEY);
    return (p === 'light' || p === 'dark' || p === 'system') ? p : 'dark';
  }

  function resolvedTheme(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyThemePreference(pref, persist = true) {
    const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'dark';
    if (persist) localStorage.setItem(UI_THEME_KEY, clean);
    document.documentElement.setAttribute('data-theme', resolvedTheme(clean));
    const sel = document.getElementById('ui-theme-select');
    if (sel) sel.value = clean;
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
  };
})();
