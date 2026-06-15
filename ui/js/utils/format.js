'use strict';

window.BBUI = window.BBUI || {};
window.BBUI.utils = window.BBUI.utils || {};
window.BBUI.utils.format = window.BBUI.utils.format || {};

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function escHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function locLabel(l) {
  return { local: 'Lokal', usb: 'USB', smb: 'SMB', storagebox: 'Storagebox' }[l] || l || '–';
}

function renderDescriptionMarkdown(text) {
  const raw = String(text || '').replace(/\r\n?/g, '\n').trim();
  if (!raw) return '';
  const lines = raw.split('\n');
  const out = [];
  let inList = false;

  const inline = (s) => escHtml(s)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
    .replace(/_([^_\n]+)_/g, '<em>$1</em>');

  for (const lineRaw of lines) {
    const line = lineRaw.trim();
    if (!line) {
      if (inList) {
        out.push('</ul>');
        inList = false;
      }
      continue;
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) {
        out.push('<ul>');
        inList = true;
      }
      out.push(`<li>${inline(line.slice(2).trim())}</li>`);
      continue;
    }
    if (inList) {
      out.push('</ul>');
      inList = false;
    }
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

window.BBUI.utils.format.capitalize = capitalize;
window.BBUI.utils.format.truncate = truncate;
window.BBUI.utils.format.escHtml = escHtml;
window.BBUI.utils.format.locLabel = locLabel;
window.BBUI.utils.format.renderDescriptionMarkdown = renderDescriptionMarkdown;

window.capitalize = capitalize;
window.truncate = truncate;
window.escHtml = escHtml;
window.locLabel = locLabel;
window.renderDescriptionMarkdown = renderDescriptionMarkdown;
