'use strict';

let _helpLoadedLanguage = '';
let _helpRequestId = 0;
let _helpSections = [];
let _helpView = 'quick';
let _helpDocumentUrl = '';

function helpT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`help.${key}`, params) || key;
}

function helpLanguage() {
  return window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en' : 'de';
}

function helpDocumentPath(language, view = _helpView) {
  if (view === 'manual') return `/ui/docs/manual/${language}/user-manual.md`;
  return language === 'en' ? '/ui/docs/help.en.md' : '/ui/docs/help.md';
}

async function fetchHelpDocument(language) {
  const primaryPath = helpDocumentPath(language);
  const primary = await fetch(primaryPath, { cache: 'no-store' });
  if (primary.ok) return { markdown: await primary.text(), path: primaryPath };
  if (language === 'de') throw new Error(`HTTP ${primary.status}`);

  const fallbackPath = helpDocumentPath('de');
  const fallback = await fetch(fallbackPath, { cache: 'no-store' });
  if (!fallback.ok) throw new Error(`HTTP ${fallback.status}`);
  return { markdown: await fallback.text(), path: fallbackPath };
}

function _helpAssetUrl(rawSource) {
  const source = String(rawSource || '').trim();
  if (!source || /^(?:[a-z]+:|\/|#)/i.test(source)) return source;
  try {
    return new URL(source, new URL(_helpDocumentUrl, window.location.origin)).pathname;
  } catch (_err) {
    return source;
  }
}

function _helpInline(mdText) {
  const inlineCodePattern = new RegExp(String.fromCharCode(96) + '([^\\n]+)' + String.fromCharCode(96), 'g');
  return escHtml(String(mdText || ''))
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_m, alt, src) => {
      const a = escHtml(alt || '');
      const u = escHtml(_helpAssetUrl(src));
      const t = a;
      return `<figure class="help-figure"><img src="${u}" alt="${a}" title="${t}" loading="lazy"><figcaption>${a || t || ''}</figcaption></figure>`;
    })
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label, target) => {
      if (target.startsWith('#')) return '<a href="#help-' + target.slice(1) + '">' + label + '</a>';
      return '<a href="' + target + '" target="_blank" rel="noopener">' + label + '</a>';
    })
    .replace(inlineCodePattern, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
}

function _renderHelpMarkdown(md) {
  const lines = String(md || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let inList = false;
  let listType = '';
  let inCode = false;
  let callout = [];

  const closeList = () => {
    if (!inList) return;
    out.push(listType === 'ol' ? '</ol>' : '</ul>');
    inList = false;
    listType = '';
  };
  const closeCallout = () => {
    if (!callout.length) return;
    const directive = callout[0].match(/^\[!(NOTE|TIP|WARNING|IMPORTANT)\]\s*(.*)$/i);
    const emphasized = callout[0].match(/^\*\*(Hinweis|Tipp|Warnung|Wichtig|Note|Tip|Warning|Important):\*\*\s*(.*)$/i);
    const calloutKinds = {
      hinweis: 'note', note: 'note', tipp: 'tip', tip: 'tip',
      warnung: 'warning', warning: 'warning', wichtig: 'important', important: 'important',
    };
    const kind = directive
      ? String(directive[1]).toLowerCase()
      : (calloutKinds[String(emphasized?.[1] || '').toLowerCase()] || 'note');
    const title = directive?.[2] || emphasized?.[1] || helpT(`callout.${kind}`);
    const firstBody = emphasized?.[2] || '';
    const body = directive
      ? callout.slice(1)
      : (emphasized ? [firstBody, ...callout.slice(1)].filter(Boolean) : callout);
    out.push(`<aside class="help-callout help-callout--${kind}"><strong>${_helpInline(title)}</strong>${body.map(item => `<p>${_helpInline(item)}</p>`).join('')}</aside>`);
    callout = [];
  };

  for (const raw of lines) {
    const line = raw.replace(/\t/g, '  ');
    const t = line.trim();

    if (t.startsWith('```')) {
      if (!inCode) {
        inCode = true;
        closeList();
        closeCallout();
        out.push('<pre><code>');
      } else {
        inCode = false;
        out.push('</code></pre>');
      }
      continue;
    }
    if (inCode) {
      out.push(`${escHtml(line)}\n`);
      continue;
    }

    if (!t) {
      closeList();
      closeCallout();
      continue;
    }

    if (t.startsWith('> ')) {
      closeList();
      callout.push(t.slice(2).trim());
      continue;
    }
    closeCallout();

    if (t.startsWith('# ')) {
      closeList();
      out.push(`<h2 class="help-document-title">${_helpInline(t.slice(2).trim())}</h2>`);
      continue;
    }
    if (t.startsWith('## ')) {
      closeList();
      out.push(`<h2>${_helpInline(t.slice(3).trim())}</h2>`);
      continue;
    }
    if (t.startsWith('### ')) {
      closeList();
      out.push(`<h3>${_helpInline(t.slice(4).trim())}</h3>`);
      continue;
    }
    if (t.startsWith('#### ')) {
      closeList();
      out.push(`<h4>${_helpInline(t.slice(5).trim())}</h4>`);
      continue;
    }
    if (t.startsWith('- ') || t.startsWith('* ')) {
      if (inList && listType !== 'ul') closeList();
      if (!inList) { out.push('<ul>'); listType = 'ul'; }
      inList = true;
      out.push(`<li>${_helpInline(t.slice(2).trim())}</li>`);
      continue;
    }

    const ordered = t.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      if (inList && listType !== 'ol') closeList();
      if (!inList) { out.push('<ol>'); listType = 'ol'; }
      inList = true;
      out.push(`<li>${_helpInline(ordered[1])}</li>`);
      continue;
    }

    if (t === '---') {
      closeList();
      out.push('<hr>');
      continue;
    }

    closeList();
    out.push(`<p>${_helpInline(t)}</p>`);
  }

  closeList();
  closeCallout();
  if (inCode) out.push('</code></pre>');
  return out.join('');
}

function _renderHelpToc(content) {
  const toc = document.getElementById('help-toc');
  if (!toc || !content) return;
  const usedIds = new Set();
  const headings = [...content.querySelectorAll('h2, h3')];
  headings.forEach((heading, index) => {
    const base = String(heading.textContent || `section-${index + 1}`)
      .toLocaleLowerCase()
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || `section-${index + 1}`;
    let id = `help-${base}`;
    let suffix = 2;
    while (usedIds.has(id)) id = `help-${base}-${suffix++}`;
    usedIds.add(id);
    heading.id = id;
  });
  toc.innerHTML = headings.map((heading, index) => `
    <a class="ui-context-nav__item help-toc-entry ${heading.tagName === 'H3' ? 'is-subsection' : ''}"
      href="#${heading.id}" data-help-target="${heading.id}" ${index === 0 ? 'aria-current="page"' : ''}>
      <span>${escHtml(heading.textContent || '')}</span>
    </a>`).join('');

  _helpSections = [];
  let current = null;
  [...content.children].forEach((node) => {
    if (node.tagName === 'H2') {
      current = { heading: node, nodes: [node], text: '' };
      _helpSections.push(current);
    } else if (current) {
      current.nodes.push(node);
    }
  });
  _helpSections.forEach((section) => {
    section.text = section.nodes.map(node => node.textContent || '').join(' ').toLocaleLowerCase();
    section.tocTargets = section.nodes
      .filter(node => node.matches?.('h2, h3'))
      .map(node => node.id)
      .filter(Boolean);
  });
}

function helpFilter(rawQuery = '') {
  const query = String(rawQuery || '').trim().toLocaleLowerCase();
  const clear = document.getElementById('help-search-clear-btn');
  const status = document.getElementById('help-search-status');
  clear?.classList.toggle('hidden', !query);
  let visible = 0;
  _helpSections.forEach((section) => {
    const match = !query || section.text.includes(query);
    section.nodes.forEach(node => node.classList.toggle('help-search-hidden', !match));
    section.tocTargets.forEach((target) => {
      document.querySelectorAll(`[data-help-target="${target}"]`).forEach(link => link.classList.toggle('help-search-hidden', !match));
    });
    if (match) visible += 1;
  });
  if (status) status.textContent = query ? helpT('searchResults', { count: visible }) : helpT('searchHint');
}

function helpClearSearch() {
  const input = document.getElementById('help-search-input');
  if (input) input.value = '';
  helpFilter('');
  input?.focus();
}

function helpSetView(rawView) {
  const view = rawView === 'manual' ? 'manual' : 'quick';
  if (_helpView === view && _helpLoadedLanguage) return;
  _helpView = view;
  _helpLoadedLanguage = '';
  document.querySelectorAll('[data-help-view]').forEach((button) => {
    const active = button.dataset.helpView === view;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  helpClearSearch();
  helpInit(true);
}

function openHelpTopic(topic) {
  const input = document.getElementById('help-search-input');
  if (input) input.value = '';
  helpFilter('');
  const normalized = String(topic || '').replace(/^#/, '');
  const target = document.getElementById(normalized) || document.getElementById(`help-${normalized}`);
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function helpInit(force = false) {
  const language = helpLanguage();
  if (_helpLoadedLanguage === language && !force) return;
  const box = document.getElementById('help-content');
  if (!box) return;
  const requestId = ++_helpRequestId;
  hideEl('help-message');
  const toc = document.getElementById('help-toc');
  if (toc) toc.innerHTML = '';
  box.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><span>${escHtml(helpT('loading'))}</span></div>`;
  try {
    const helpDocument = await fetchHelpDocument(language);
    if (requestId !== _helpRequestId) return;
    _helpDocumentUrl = helpDocument.path;
    box.innerHTML = _renderHelpMarkdown(helpDocument.markdown);
    _renderHelpToc(box);
    helpFilter(document.getElementById('help-search-input')?.value || '');
    _helpLoadedLanguage = language;
  } catch (err) {
    if (requestId !== _helpRequestId) return;
    _helpLoadedLanguage = '';
    box.innerHTML = '';
    showMsg('help-message', 'error', helpT('loadFailed', { message: err.message }));
  }
}

window.addEventListener?.('bbui:language-changed', () => helpInit(true));
window.helpInit = helpInit;
window.helpFilter = helpFilter;
window.helpClearSearch = helpClearSearch;
window.helpSetView = helpSetView;
window.openHelpTopic = openHelpTopic;
