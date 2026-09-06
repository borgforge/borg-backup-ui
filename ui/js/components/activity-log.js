'use strict';

// File activity only: at most three file windows in the DOM, with older and
// newer windows fetched on scroll. The complete retained file stays readable.
(function initActivityLog() {
  const MAX_WINDOWS = 3;
  const BLOCK_BYTES = 65536 + 4;
  const t = (key, params = {}) => window.BBUI.components.i18n.t(`jobs.${key}`, params);

  class ActivityLog {
    constructor({ job, run, output, onStatus, onFollow }) {
      Object.assign(this, { job, run, output, onStatus, onFollow });
      this.windows = [];
      this.start = 0;
      this.end = 0;
      this.size = 0;
      this.follow = true;
      this.scrollTop = output.scrollTop;
      this.closed = false;
      this.sequence = 0;
      this.statusKey = '';
      this.toolbar = document.getElementById('activity-log-tools');
      this.note = document.getElementById('activity-log-note');
      this.download = document.getElementById('activity-log-download');
      this.bindings = [];
      this.bind('activity-log-start', 'click', () => this.load({ start: 0 }, 'replace-start', false));
      this.bind('activity-log-end', 'click', () => this.tail());
      this.bind('activity-log-older', 'click', () => this.load({ before: this.start }, 'replace-end', false));
      this.bind('activity-log-newer', 'click', () => this.load({ start: this.end }, 'replace-start', false));
      this.toolbar.classList.remove('hidden');
      this.output.classList.add('activity-log-output');
      this.tail();
    }

    bind(id, event, handler) {
      const el = document.getElementById(id);
      el.addEventListener(event, handler);
      this.bindings.push(() => el.removeEventListener(event, handler));
    }

    begin(follow = this.follow) {
      clearTimeout(this.timer);
      this.controller?.abort();
      this.controller = new AbortController();
      this.sequence += 1;
      this.busy = true;
      this.follow = follow;
      this.onFollow(follow);
      return this.sequence;
    }

    async request(params, sequence) {
      const query = new URLSearchParams({ job_id: this.job, run_id: this.run || '', ...params });
      if (this.fileId) query.set('file_id', this.fileId);
      const response = await fetch(`/api/jobs/log/window?${query}`, { signal: this.controller.signal, cache: 'no-store' });
      const data = await response.json();
      if (this.closed || sequence !== this.sequence) return null;
      if (!response.ok || data.error) throw new Error(apiErrorMessage(data, response.status));
      this.run = data.run_id;
      this.fileId = data.file_id;
      this.size = data.size;
      this.running = data.running;
      this.persistenceFailed = data.log_persistence_failed === true;
      this.failed = false;
      const downloadUrl = `/api/jobs/log/download?${new URLSearchParams({ job_id: this.job, run_id: this.run })}`;
      if (this.downloadUrl !== downloadUrl) {
        this.download.href = downloadUrl;
        this.downloadUrl = downloadUrl;
      }
      const statusKey = JSON.stringify([data.running, data.exit_code, data.phase]);
      if (statusKey !== this.statusKey) {
        this.statusKey = statusKey;
        this.onStatus(data);
      }
      return data;
    }

    async load(params, action, follow = this.follow) {
      if (this.closed) return;
      const sequence = this.begin(follow);
      try {
        const data = await this.request(params, sequence);
        if (!data) return;
        // A user scroll can precede its scroll event. Respect it before an
        // incoming live block would move the viewport back to the bottom.
        if (action === 'append' && this.follow) this.onScroll();
        if (sequence !== this.sequence) return;
        if (typeof data.text === 'string' && (data.text || action.startsWith('replace'))) this.render(data, action);
        this.updateNote(action !== 'status');
      } catch (error) {
        if (error.name !== 'AbortError' && sequence === this.sequence && !this.closed) {
          this.note.textContent = t('logError', { message: error.message });
          this.failed = true;
        }
      } finally {
        if (sequence === this.sequence && !this.closed) {
          this.busy = false;
          this.schedule();
        }
      }
    }

    schedule() {
      clearTimeout(this.timer);
      if (this.closed || this.busy) return;
      // One request at a time provides backpressure without a client queue.
      // A background tab only checks status; it catches up when shown again.
      if (this.failed || this.running || (this.follow && this.end < this.size)) {
        this.timer = setTimeout(() => {
          if (this.follow && !document.hidden) this.load({ start: this.end }, 'append');
          else this.load({ status: 1 }, 'status');
        }, this.failed || document.hidden ? 2000 : (this.follow && this.end < this.size ? 20 : 250));
      }
    }

    render(data, action) {
      const oldTop = this.output.scrollTop;
      const oldHeight = this.output.scrollHeight;
      if (action.startsWith('replace')) {
        this.windows = [];
        this.output.replaceChildren();
      }
      if (data.text) {
        const node = document.createElement('span');
        const text = document.createTextNode(data.text);
        node.append(text);
        const entry = { start: data.start, end: data.end, node, text };
        if (action === 'prepend') {
          if (this.windows.length && data.end !== this.start) throw new Error('Non-contiguous log window');
          this.windows.unshift(entry);
          this.output.prepend(node);
          // Measure once per block, before evicting the far end of the view.
          this.output.scrollTop = oldTop + this.output.scrollHeight - oldHeight;
          while (this.windows.length > MAX_WINDOWS) this.windows.pop().node.remove();
        } else {
          if (action === 'append' && this.windows.length && data.start !== this.end) throw new Error('Non-contiguous log window');
          const last = this.windows[this.windows.length - 1];
          // Polls often contain only a few lines. Fill a bounded block before
          // evicting history, so three small updates cannot empty the viewport.
          if (action === 'append' && last && data.end - last.start <= BLOCK_BYTES) {
            last.text.appendData(data.text);
            last.end = data.end;
          } else {
            this.windows.push(entry);
            this.output.append(node);
          }
          const heightBeforeTrim = this.output.scrollHeight;
          while (this.windows.length > MAX_WINDOWS) this.windows.shift().node.remove();
          if (!this.follow && action === 'append') {
            this.output.scrollTop = Math.max(0, oldTop + this.output.scrollHeight - heightBeforeTrim);
          }
        }
      }
      this.start = this.windows[0]?.start ?? data.start;
      this.end = this.windows[this.windows.length - 1]?.end ?? data.end;
      if (action === 'replace-end') this.output.scrollTop = this.output.scrollHeight;
      else if (action === 'replace-start') this.output.scrollTop = 0;
      this.syncScroll();
    }

    syncScroll() {
      if (this.follow) this.output.scrollTop = this.output.scrollHeight;
      // Remember the browser's clamped position after rendering or moving the
      // panel. Its delayed scroll event must not change the user's follow mode.
      this.scrollTop = this.output.scrollTop;
    }

    updateNote(resetText = true) {
      const text = t(this.persistenceFailed ? 'activityLogSaveFailed' : 'activityLogComplete');
      if ((resetText || this.persistenceFailed) && this.note.textContent !== text) this.note.textContent = text;
      const older = document.getElementById('activity-log-older');
      const newer = document.getElementById('activity-log-newer');
      if (older.disabled !== (this.start === 0)) older.disabled = this.start === 0;
      if (newer.disabled !== (this.end >= this.size)) newer.disabled = this.end >= this.size;
      const hint = document.getElementById('log-scroll-hint');
      hint.classList.toggle('visible', !this.follow);
    }

    onScroll() {
      if (this.closed || Math.abs(this.output.scrollTop - this.scrollTop) < 1) return;
      this.scrollTop = this.output.scrollTop;
      const wasFollowing = this.follow;
      const atBottom = this.output.scrollHeight - this.output.scrollTop <= this.output.clientHeight + 40;
      this.follow = atBottom && (wasFollowing || this.end >= this.size);
      this.onFollow(this.follow);
      if (this.busy && wasFollowing && !this.follow) {
        this.begin(false);
        this.busy = false;
        this.schedule();
      }
      if (!this.busy && !this.follow) {
        if (this.output.scrollTop < 40 && this.start > 0) this.older();
        else if (atBottom && this.end < this.size) this.newer();
      }
      document.getElementById('log-scroll-hint').classList.toggle('visible', !this.follow);
    }

    older() {
      if (this.start > 0) this.load({ before: this.start }, 'prepend', false);
    }

    newer() {
      if (this.end < this.size) this.load({ start: this.end }, 'append', false);
    }

    tail() {
      this.load({}, 'replace-end', true);
    }

    clear() {
      this.begin(true);
      this.output.replaceChildren();
      this.windows = [];
      this.start = this.end;
      this.syncScroll();
      this.busy = false;
      this.updateNote();
      this.schedule();
    }

    close() {
      this.closed = true;
      this.sequence += 1;
      this.controller?.abort();
      clearTimeout(this.timer);
      this.bindings.forEach(unbind => unbind());
      this.toolbar.classList.add('hidden');
      this.output.classList.remove('activity-log-output');
      this.windows = [];
    }
  }

  window.BBUI.components.activityLog = { create: options => new ActivityLog(options) };
})();
