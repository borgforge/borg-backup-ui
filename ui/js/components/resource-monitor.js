'use strict';

/** Lightweight dashboard polling and bounded server-side trends (#602). */
(function resourceMonitor() {
  const root = window.BBUI = window.BBUI || {};
  let timer = null;
  let controller = null;
  let generation = 0;
  let running = false;
  let data = null;
  let failed = false;
  let expanded = false;
  let chartId = 0;
  let selectedPoint = null;
  const el = id => document.getElementById(id);
  const t = (key, params = {}) => root.components.i18n.t(`resources.${key}`, params);
  const valid = value => typeof value === 'number' && Number.isFinite(value);
  const number = value => new Intl.NumberFormat(root.components.i18n.getLanguage(), {maximumFractionDigits: 1}).format(value);
  const percent = value => valid(value) ? `${number(value)} %` : '—';
  const gib = value => valid(value) ? `${number(value / 1073741824)} GiB` : '—';
  const visible = () => !document.hidden && root.core?.state?.currentPage === 'dashboard';
  const timeLabel = timestamp => valid(timestamp) ? new Date(timestamp * 1000).toLocaleTimeString(
    root.components.i18n.getLanguage(), {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '—';

  /** Bind pointer/touch and keyboard inspection to real history samples.
   * A pointer further than ten seconds from a sample shows a missing value;
   * keyboard arrows visit recorded timestamps. Selection survives live refresh.
   */
  function bindPlots(plots, focusKey) {
    el('resource-history').querySelectorAll('[data-resource-plot-key]').forEach((node, index) => {
      const plot = plots[index];
      const samples = plot.history;
      const end = samples[samples.length - 1]?.timestamp;
      const marker = node.querySelector('.resource-crosshair');
      const readout = node.querySelector('.resource-readout');
      const canvas = node.querySelector('.resource-plot-canvas');
      const draw = () => {
        const selection = selectedPoint?.key === plot.key ? selectedPoint : null;
        const target = selection?.time ?? end;
        const nearest = samples.reduce((best, sample) => !best || Math.abs(sample.timestamp - target) < Math.abs(best.timestamp - target) ? sample : best, null);
        const found = nearest && Math.abs(nearest.timestamp - target) <= 10;
        const value = found ? plot.getter(nearest) : null;
        const timestamp = found ? nearest.timestamp : target;
        const text = `${timeLabel(timestamp)} · ${valid(value) ? plot.format(value) : t('noMeasurement')}`;
        readout.textContent = text;
        canvas.setAttribute('aria-label', `${plot.label}. ${text}. ${t('inspectHint')}`);
        marker.hidden = !selection || !valid(value) || !valid(plot.maximum) || plot.maximum <= 0;
        if (!marker.hidden) marker.style.left = `${Math.max(0, Math.min(100, (timestamp - end + 600) / 6))}%`;
      };
      const pointer = event => {
        const rect = canvas.getBoundingClientRect();
        if (!samples.length || rect.width <= 0) return;
        selectedPoint = {key: plot.key, time: end - 600 + 600 * Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), mode: 'pointer'};
        draw();
      };
      canvas.addEventListener('pointermove', pointer);
      canvas.addEventListener('pointerdown', pointer);
      canvas.addEventListener('pointerleave', event => {
        if (event.pointerType !== 'touch' && selectedPoint?.key === plot.key && selectedPoint.mode === 'pointer') {
          selectedPoint = null;
          draw();
        }
      });
      canvas.addEventListener('keydown', event => {
        if (!samples.length) return;
        if (event.key === 'Escape') { selectedPoint = null; draw(); return; }
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const time = selectedPoint?.key === plot.key ? selectedPoint.time : end;
        let current = samples.reduce((best, sample, i) => Math.abs(sample.timestamp - time) < Math.abs(samples[best].timestamp - time) ? i : best, 0);
        current = event.key === 'Home' ? 0 : event.key === 'End' ? samples.length - 1 : Math.max(0, Math.min(samples.length - 1, current + (event.key === 'ArrowLeft' ? -1 : 1)));
        selectedPoint = {key: plot.key, time: samples[current].timestamp, mode: 'keyboard'};
        draw();
      });
      draw();
      if (focusKey === plot.key) canvas.focus({preventScroll: true});
    });
  }

  /**
   * Draw a fixed-scale ten-minute trend with a fading area under each segment.
   * Missing samples/time gaps split both stroke and fill; no interpolated values
   * or smoothing are introduced. Each SVG owns a unique gradient definition.
   */
  function chart(history, getter, maximum, label, large = false) {
    if (!history?.length || !valid(maximum) || maximum <= 0) return '';
    const end = history[history.length - 1].timestamp;
    let path = '';
    let area = '';
    let segment = [];
    let previous = null;
    const finishSegment = () => {
      if (!segment.length) return;
      path += `M${segment.join(' L')} `;
      if (segment.length === 1) path += 'l0.1,0 ';
      else area += `M${segment[0].split(',')[0]},60 L${segment.join(' L')} L${segment[segment.length - 1].split(',')[0]},60 Z `;
      segment = [];
    };
    for (const sample of history) {
      const value = getter(sample);
      if (!valid(value) || !valid(sample.timestamp)) { finishSegment(); previous = null; continue; }
      const x = Math.max(0, Math.min(400, 400 * (sample.timestamp - end + 600) / 600));
      const y = 60 - Math.max(0, Math.min(60, value / maximum * 60));
      const connected = previous !== null && sample.timestamp - previous <= 20;
      if (!connected) finishSegment();
      segment.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      previous = sample.timestamp;
    }
    finishSegment();
    const gradient = `resource-area-${++chartId}`;
    return `<svg class="resource-chart${large ? ' resource-chart-large' : ''}" viewBox="0 -4 400 68" preserveAspectRatio="none" role="img" aria-label="${escHtml(label)}">
      <defs><linearGradient id="${gradient}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="currentColor" stop-opacity="0.24"/><stop offset="100%" stop-color="currentColor" stop-opacity="0.02"/></linearGradient></defs>
      ${large ? '<path class="resource-chart-grid" d="M0,15 H400 M0,30 H400 M0,45 H400" fill="none" stroke="currentColor" vector-effect="non-scaling-stroke"/>' : ''}
      <path class="resource-chart-area" d="${area}" fill="url(#${gradient})"/>
      <path d="${path}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
    </svg>`;
  }

  /** Resolve job labels from the dashboard's existing metadata, never fetch Borg. */
  function jobName(key) {
    const job = root.core?.state?.data?.backups?.find(row => row.key === key);
    return job?.display_name || job?.name || key;
  }

  /** Update host values, RAM capacity and the existing Active runs summary.
   * Protected-test budgets and history use full-width regions below the summary cards.
   * History retains its toggle and chart focus across polls. */
  function render() {
    if (!el('resource-values')) return;
    const unavailable = failed || !data?.available || data.stale;
    const host = unavailable ? {} : data.host || {};
    const runs = unavailable || !data.runs_available ? null : data.runs || [];
    const tests = unavailable ? [] : data.protected_tests || [];
    const history = unavailable ? [] : data.history || [];
    const active = runs?.length > 0;
    el('resource-live').textContent = unavailable ? t('unavailable') : t('live', {seconds: active ? 2 : 10});
    el('resource-live').classList.toggle('is-unavailable', unavailable);
    const ramRatio = valid(host.memory_available_bytes) && valid(host.memory_total_bytes) && host.memory_total_bytes > 0
      ? Math.max(0, Math.min(100, 100 * host.memory_available_bytes / host.memory_total_bytes)) : null;
    el('resource-values').innerHTML = `<div class="resource-value"><span title="${escHtml(t('cpuScale'))}">${escHtml(t('cpu'))}</span><strong>${escHtml(percent(host.cpu_percent))}</strong>${chart(history, s => s.host.cpu_percent, 100, t('cpu'))}</div>
      <div class="resource-value"><span>${escHtml(t('ram'))}</span><strong>${escHtml(gib(host.memory_available_bytes))}<small> / ${escHtml(gib(host.memory_total_bytes))}</small></strong>
      ${ramRatio === null ? '' : `<progress class="resource-ram-capacity" max="100" value="${ramRatio}" aria-label="${escHtml(t('ramTotal', {total: gib(host.memory_total_bytes)}))}"></progress>`}</div>`;
    if (typeof renderDashboardActiveRuns === 'function') renderDashboardActiveRuns(runs);
    el('resource-active').textContent = runs === null ? `${t('active')}: ${t('unavailable')}` : runActivitySummary(runs);
    el('resource-activity').hidden = !tests.length;
    el('resource-tests').hidden = !tests.length;
    el('resource-tests').innerHTML = tests.map(test => {
      const ratio = valid(test.memory_bytes) && test.memory_limit_bytes > 0 ? Math.min(100, 100 * test.memory_bytes / test.memory_limit_bytes) : null;
      return `<div class="resource-test"><strong>${escHtml(jobName(test.job_key))}<small>${escHtml(t('protectedTest'))}</small></strong>
        <span>CPU <b>${escHtml(percent(test.cpu_percent))}</b></span>
        <div class="resource-budget"><span>RAM <b>${escHtml(gib(test.memory_bytes))} / ${escHtml(gib(test.memory_limit_bytes))}</b></span>
        ${ratio === null ? '' : `<progress max="100" value="${ratio}" aria-label="${escHtml(t('budget'))}"></progress>`}</div>
        <span class="resource-reserve">${escHtml(t('reserve', {value: gib(data.configured_reserve_bytes)}))}</span></div>`;
    }).join('') + (tests.length ? `<p class="resource-note">${escHtml(t('accounting'))}</p>` : '');
    el('resource-history-toggle').textContent = t(expanded ? 'hideHistory' : 'showHistory');
    el('resource-history-toggle').setAttribute('aria-expanded', String(expanded));
    el('resource-history').hidden = !expanded;
    if (expanded) {
      const focusKey = document.activeElement?.dataset?.resourceFocusKey;
      const plots = [];
      const plot = (key, label, getter, maximum, format) => {
        plots.push({key, label, getter, maximum, format, history});
        const ticks = [1, .75, .5, .25, 0].map(fraction => `<span>${escHtml(valid(maximum) && maximum > 0 ? format(maximum * fraction) : '—')}</span>`).join('');
        return `<div data-resource-plot-key="${escHtml(key)}"><div class="resource-plot-heading"><h3>${escHtml(label)}</h3><span>${escHtml(t('current'))} <strong>${escHtml(format(getter(unavailable ? {host: {}, protected_tests: []} : data)))}</strong></span></div>
          <div class="resource-plot-grid"><div class="resource-y-axis" aria-hidden="true">${ticks}</div>
          <div class="resource-plot-canvas" tabindex="0" role="group" data-resource-focus-key="${escHtml(key)}" title="${escHtml(t('inspectHint'))}">${chart(history, getter, maximum, label, true)}<span class="resource-crosshair" hidden></span></div>
          <div class="resource-axis"><span>−10 min</span><span>−5 min</span><span>${escHtml(t('now'))}</span></div></div>
          <div class="resource-readout"></div></div>`;
      };
      el('resource-history').innerHTML = `<p class="resource-note">${escHtml(t('historyNote'))}</p><div class="resource-plots">` +
        plot('host-cpu', t('cpu'), s => s.host.cpu_percent, 100, percent) +
        plot('host-ram', t('ram'), s => s.host.memory_available_bytes, host.memory_total_bytes, gib) +
        tests.map(test => plot(`${test.id}-cpu`, `${jobName(test.job_key)} · CPU`, s => s.protected_tests.find(row => row.id === test.id)?.cpu_percent, 100, percent) +
          plot(`${test.id}-ram`, `${jobName(test.job_key)} · RAM`, s => s.protected_tests.find(row => row.id === test.id)?.memory_bytes,
            test.memory_limit_bytes, gib)).join('') + '</div>';
      bindPlots(plots, focusKey);
    }
  }

  /** Poll sequentially with timeout and generation checks so obsolete responses cannot render. */
  async function poll(epoch) {
    if (!running || epoch !== generation || !visible()) return;
    controller = new AbortController();
    const request = controller;
    const timeout = setTimeout(() => request.abort(), 8000);
    try {
      const response = await fetch('/api/system-resources', {signal: request.signal, cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = await response.json();
      if (epoch !== generation) return;
      data = next;
      failed = false;
    } catch (_) {
      if (epoch !== generation) return;
      failed = true;
    } finally {
      clearTimeout(timeout);
      if (epoch === generation) controller = null;
    }
    if (epoch !== generation || !visible()) return;
    render();
    const delay = !failed && data?.runs?.length ? 2000 : 10000;
    timer = setTimeout(() => poll(epoch), delay);
  }

  /** Start once when the dashboard is visible; no whole-dashboard reloads. */
  function start() {
    if (!visible() || running) return;
    running = true;
    failed = true; // Never label an old snapshot live when returning to this page.
    render();
    poll(++generation);
  }

  /** Cancel timers and pending requests on navigation, logout or hidden tabs. */
  function stop() {
    running = false;
    generation++;
    clearTimeout(timer);
    timer = null;
    controller?.abort();
    controller = null;
  }

  el('resource-history-toggle')?.addEventListener('click', () => { expanded = !expanded; render(); });
  document.addEventListener('visibilitychange', () => { if (visible()) start(); else stop(); });
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', () => { if (visible()) start(); });
  window.addEventListener('bbui:language-changed', render);
  root.resourceMonitor = {start, stop};
})();
