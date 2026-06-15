'use strict';

let _helpLoaded = false;

function _helpInline(mdText) {
  return escHtml(String(mdText || ''))
    .replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)/g, (_m, alt, src, title) => {
      const a = escHtml(alt || '');
      const u = escHtml(src || '');
      const t = escHtml(title || alt || '');
      return `<figure class="help-figure"><img src="${u}" alt="${a}" title="${t}" loading="lazy"><figcaption>${a || t || ''}</figcaption></figure>`;
    })
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
}

function _renderHelpMarkdown(md) {
  const lines = String(md || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let inList = false;
  let inCode = false;

  for (const raw of lines) {
    const line = raw.replace(/\t/g, '  ');
    const t = line.trim();

    if (t.startsWith('```')) {
      if (!inCode) {
        inCode = true;
        if (inList) { out.push('</ul>'); inList = false; }
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
      if (inList) { out.push('</ul>'); inList = false; }
      continue;
    }

    if (t.startsWith('# ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h2>${_helpInline(t.slice(2).trim())}</h2>`);
      continue;
    }
    if (t.startsWith('## ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h3>${_helpInline(t.slice(3).trim())}</h3>`);
      continue;
    }
    if (t.startsWith('### ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h4>${_helpInline(t.slice(4).trim())}</h4>`);
      continue;
    }
    if (t.startsWith('- ') || t.startsWith('* ')) {
      if (!inList) out.push('<ul>');
      inList = true;
      out.push(`<li>${_helpInline(t.slice(2).trim())}</li>`);
      continue;
    }

    if (inList) { out.push('</ul>'); inList = false; }
    out.push(`<p>${_helpInline(t)}</p>`);
  }

  if (inList) out.push('</ul>');
  if (inCode) out.push('</code></pre>');
  return out.join('');
}

async function helpInit(force = false) {
  if (_helpLoaded && !force) return;
  const box = document.getElementById('help-content');
  if (!box) return;
  hideEl('help-message');
  box.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><span>Lade Dokumentation...</span></div>';
  try {
    const res = await fetch('/ui/docs/help.md', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const md = await res.text();
    box.innerHTML = _renderHelpMarkdown(md);
    _helpLoaded = true;
  } catch (err) {
    _helpLoaded = false;
    box.innerHTML = '';
    showMsg('help-message', 'error', `Dokumentation konnte nicht geladen werden: ${err.message}`);
  }
}

window.helpInit = helpInit;
