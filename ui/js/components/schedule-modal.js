'use strict';

(function initScheduleModalComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  function bindScheduleEvents() {
    document.getElementById('rt-schedule-btn')?.addEventListener('click', () => {
      if (typeof showRestoreTestScheduleModal === 'function') showRestoreTestScheduleModal();
    });

    document.getElementById('schedule-close-btn')?.addEventListener('click', () => {
      if (typeof closeScheduleModal === 'function') closeScheduleModal();
    });
    document.getElementById('schedule-cancel-btn')?.addEventListener('click', () => {
      if (typeof closeScheduleModal === 'function') closeScheduleModal();
    });
    document.getElementById('schedule-save-btn')?.addEventListener('click', () => {
      if (typeof saveScheduleAction === 'function') saveScheduleAction();
    });
    document.getElementById('schedule-delete-btn')?.addEventListener('click', () => {
      if (typeof deleteScheduleAction === 'function') deleteScheduleAction();
    });

    document.getElementById('schedule-enabled')?.addEventListener('change', () => {
      if (typeof updateSchedulePreview === 'function') updateSchedulePreview();
    });
    document.getElementById('schedule-hour')?.addEventListener('input', () => {
      if (typeof updateSchedulePreview === 'function') updateSchedulePreview();
    });
    document.getElementById('schedule-minute')?.addEventListener('input', () => {
      if (typeof updateSchedulePreview === 'function') updateSchedulePreview();
    });
    document.getElementById('schedule-dom')?.addEventListener('input', () => {
      if (typeof updateSchedulePreview === 'function') updateSchedulePreview();
    });
    document.getElementById('schedule-cron-custom')?.addEventListener('input', () => {
      if (typeof updateSchedulePreview === 'function') updateSchedulePreview();
    });

    document.querySelectorAll('[data-freq]')?.forEach((el) => {
      el.addEventListener('click', () => {
        if (typeof setFrequency === 'function') setFrequency(el.dataset.freq);
      });
    });
    document.querySelectorAll('[data-dow]')?.forEach((el) => {
      el.addEventListener('click', () => {
        if (typeof selectDow === 'function') selectDow(parseInt(el.dataset.dow, 10));
      });
    });
  }

  function init() {
    bindScheduleEvents();
  }

  window.BBUI.components.scheduleModal = { init };
})();
