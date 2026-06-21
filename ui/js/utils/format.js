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

function locationIcon(location) {
  const icons = {
    all: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3" cy="6" r="1" fill="currentColor"/><circle cx="3" cy="12" r="1" fill="currentColor"/><circle cx="3" cy="18" r="1" fill="currentColor"/></svg>',
    local: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6" stroke-width="3"/><line x1="6" y1="18" x2="6.01" y2="18" stroke-width="3"/></svg>',
    usb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 8h1a4 4 0 0 1 0 8h-1"/><path d="M3 8h11v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8z"/><line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/><line x1="8" y1="4" x2="8" y2="10"/></svg>',
    smb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/></svg>',
    storagebox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
    utility: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="4"/></svg>',
  };
  return icons[String(location || '').toLowerCase()] || icons.local;
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
window.BBUI.utils.format.locationIcon = locationIcon;
window.BBUI.utils.format.renderDescriptionMarkdown = renderDescriptionMarkdown;

window.capitalize = capitalize;
window.truncate = truncate;
window.escHtml = escHtml;
window.locLabel = locLabel;
window.locationIcon = locationIcon;
window.renderDescriptionMarkdown = renderDescriptionMarkdown;
