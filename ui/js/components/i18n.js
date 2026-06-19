'use strict';

(function initI18nComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  const supportedLanguages = ['de', 'en'];
  const fallbackLanguage = 'de';
  const storageKey = 'borg-backup-ui.language';
  const resources = {};
  let activeLanguage = fallbackLanguage;
  let initPromise = null;
  let observer = null;

  function normalizeLanguage(language) {
    const normalized = String(language || '').trim().toLowerCase().split('-')[0];
    return supportedLanguages.includes(normalized) ? normalized : fallbackLanguage;
  }

  function readStoredLanguage() {
    try {
      return normalizeLanguage(window.localStorage.getItem(storageKey));
    } catch (_) {
      return fallbackLanguage;
    }
  }

  function lookup(language, key) {
    return String(key || '').split('.').reduce((value, part) => {
      if (!value || typeof value !== 'object') return undefined;
      return value[part];
    }, resources[language]);
  }

  function interpolate(value, params) {
    return String(value).replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    ));
  }

  function resolveTranslation(key) {
    const translated = lookup(activeLanguage, key);
    const fallback = lookup(fallbackLanguage, key);
    return typeof translated === 'string'
      ? translated
      : (typeof fallback === 'string' ? fallback : key);
  }

  function t(key, params = {}) {
    return interpolate(resolveTranslation(key), params);
  }

  function translateElement(element) {
    if (!(element instanceof Element)) return;
    const textKey = element.dataset.i18n;
    if (textKey && resolveTranslation(textKey) !== textKey) element.textContent = t(textKey);

    ['title', 'placeholder', 'ariaLabel'].forEach((attribute) => {
      const key = element.dataset[`i18n${attribute[0].toUpperCase()}${attribute.slice(1)}`];
      if (!key || resolveTranslation(key) === key) return;
      const htmlAttribute = attribute === 'ariaLabel' ? 'aria-label' : attribute;
      element.setAttribute(htmlAttribute, t(key));
    });
  }

  function translate(root = document) {
    if (root instanceof Element && root.matches('[data-i18n], [data-i18n-title], [data-i18n-placeholder], [data-i18n-aria-label]')) {
      translateElement(root);
    }
    root.querySelectorAll?.('[data-i18n], [data-i18n-title], [data-i18n-placeholder], [data-i18n-aria-label]')
      .forEach(translateElement);
    document.documentElement.lang = activeLanguage;
    if (resolveTranslation('app.title') !== 'app.title') document.title = t('app.title');

    const selector = document.getElementById('ui-language-select');
    if (selector && selector.value !== activeLanguage) selector.value = activeLanguage;
  }

  function setLanguage(language, options = {}) {
    activeLanguage = normalizeLanguage(language);
    if (options.persist !== false) {
      try {
        window.localStorage.setItem(storageKey, activeLanguage);
      } catch (_) {}
    }
    translate(document);
    window.dispatchEvent(new CustomEvent('bbui:language-changed', {
      detail: { language: activeLanguage },
    }));
    return activeLanguage;
  }

  function bindLanguageSelector() {
    const selector = document.getElementById('ui-language-select');
    if (!selector || selector.dataset.i18nBound === 'true') return;
    selector.dataset.i18nBound = 'true';
    selector.value = activeLanguage;
    selector.addEventListener('change', () => setLanguage(selector.value));
  }

  async function loadResource(language) {
    const response = await fetch(`/ui/i18n/${language}.json`, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`Could not load language resource: ${language}`);
    resources[language] = await response.json();
  }

  function observeDynamicContent() {
    if (observer || !document.body) return;
    observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
          if (node instanceof Element) translate(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function init() {
    if (initPromise) return initPromise;
    initPromise = Promise.allSettled(supportedLanguages.map(loadResource)).then(() => {
      activeLanguage = readStoredLanguage();
      translate(document);
      bindLanguageSelector();
      observeDynamicContent();
      return activeLanguage;
    });
    return initPromise;
  }

  window.BBUI.components.i18n = {
    getLanguage: () => activeLanguage,
    init,
    setLanguage,
    supportedLanguages: [...supportedLanguages],
    t,
    translate,
  };
})();
