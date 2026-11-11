'use strict';
// Exercise passive SMB polling and manual actions without a live NAS (#730).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.BBUI_CHROMIUM ? {executablePath: process.env.BBUI_CHROMIUM} : {})});
  try {
    for (const language of ['de', 'en']) {
      const page = await browser.newPage({viewport: {width: 1152, height: 1000}});
      const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
      const text = labels.settings.profiles;
      const errors = [], actions = [];
      let state = 'not_mounted', fail = false, reads = 0;
      let held = null, heldReady = null, holdNext = false;
      page.on('pageerror', error => errors.push(error.message));
      await page.route('http://bbui.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: '<main id="page-settings"><div id="settings-content"></div></main>'});
        if (url.pathname === '/api/storage/smb-mount-status') {
          reads++;
          const body = JSON.stringify({mount_path: url.searchParams.get('mount_path'), mount_state: state});
          if (holdNext) { holdNext = false; held = () => route.fulfill({contentType: 'application/json', body}).catch(() => {}); heldReady(); return; }
          return route.fulfill({status: fail ? 503 : 200, contentType: 'application/json', body});
        }
        if (url.pathname === '/api/storage/smb-action') {
          const data = route.request().postDataJSON(); actions.push(data.action);
          state = data.action === 'mount' ? 'mounted' : 'not_mounted';
          return route.fulfill({contentType: 'application/json', body: '{"ok":true}'});
        }
        throw new Error(`Unexpected request: ${route.request().method()} ${url.pathname}`);
      });
      await page.goto('http://bbui.test/');
      for (const file of ['ui/style.css', 'ui/design-system.css', 'ui/settings-redesign.css']) await page.addStyleTag({content: fs.readFileSync(file, 'utf8')});
      await page.evaluate(labels => {
        window.currentPage = 'settings';
        window.BBUI = {core: {getCurrentPage: () => window.currentPage}, components: {i18n: {t: (key, params = {}) => {
          const value = key.split('.').reduce((a, k) => a?.[k], labels) || key;
          return value.replace(/\{(\w+)\}/g, (_, key) => params[key] ?? '');
        }}}};
        window.escHtml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
        window.locationIcon = () => '';
        window.apiErrorMessage = (_, status) => String(status);
        window.apiMessage = (_, fallback) => fallback;
      }, labels);
      await page.addScriptTag({content: fs.readFileSync('ui/js/utils/dom.js', 'utf8')});
      await page.addScriptTag({content: fs.readFileSync('ui/js/pages/settings.js', 'utf8')});
      await page.evaluate(() => {
        settingsState.activeTab = 'smb';
        document.getElementById('settings-content').innerHTML = renderSettingsSmbProfiles([
          {key: 'nas', name: 'Backup NAS', server: 'nas.example', share: 'backup', username: 'backup', password_set: true, mount_path: '/mnt/borg-backup-ui/smb/NAS Backup'},
        ]);
        document.getElementById('settings-content').addEventListener('click', onSettingsContentClick);
        syncSettingsProfileManager('smb');
      });
      const status = page.locator('[data-smb-profile-mount-status]');
      const mount = page.locator('[data-settings-action="smb-profile-mount"]');
      const unmount = page.locator('[data-settings-action="smb-profile-unmount"]');
      await page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, text.notMounted);
      assert.equal(await unmount.isDisabled(), true);
      assert.equal(await page.locator('[data-settings-action="smb-profile-status"]').count(), 0);
      assert.equal(await mount.textContent(), text.mountNow);
      // A change caused by a backup is reflected without any manual action.
      state = 'mounted';
      await page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, text.mounted);
      assert.equal(await mount.isDisabled(), true);
      assert.deepEqual(actions, []);
      // Manual actions go to the action API; observation remains a GET.
      await unmount.click();
      await page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, text.notMounted);
      await mount.click();
      await page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, text.mounted);
      assert.deepEqual(actions, ['unmount', 'mount']);
      if (process.env.BBUI_SCREENSHOT_DIR) await page.screenshot({path: `${process.env.BBUI_SCREENSHOT_DIR}/smb-${language}.png`, fullPage: true});
      await page.setViewportSize({width: 390, height: 844});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      // A response captured before a manual unmount must not restore stale Mounted.
      const requestHeld = new Promise(resolve => { heldReady = resolve; });
      holdNext = true;
      await page.evaluate(() => { void refreshSelectedSmbProfileMountStatus(); });
      await requestHeld;
      assert.ok(held);
      await unmount.click();
      await page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, text.notMounted);
      await held(); held = null;
      assert.equal(await status.textContent(), text.notMounted);
      // Failures become unknown, not a false Not mounted; recovery is automatic.
      fail = true;
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(await status.textContent(), text.mountStatusUnknown);
      fail = false;
      state = 'read_only';
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(await status.textContent(), text.mountedReadOnly);
      // Hiding the browser tab cancels its timer and resumes immediately on return.
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange')); });
      const beforeHidden = reads;
      await page.waitForTimeout(5200);
      assert.equal(reads, beforeHidden);
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, value: false}); document.dispatchEvent(new Event('visibilitychange')); });
      await page.waitForFunction(() => settingsState.smbMountStatusRequest === null);
      assert.ok(reads > beforeHidden);
      // Editing pauses polling and preserves the draft.
      await page.locator('[data-profile-edit]').click();
      const name = page.locator('[data-smb-profile-name]');
      await name.fill('Unsaved NAS name');
      const beforeEditing = reads;
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(reads, beforeEditing);
      assert.equal(await name.inputValue(), 'Unsaved NAS name');
      assert.equal(await mount.isDisabled(), true);
      await page.evaluate(() => { window.currentPage = 'jobs'; settingsState.profileEditing = ''; stopSmbMountStatusPolling(); });
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(reads, beforeEditing);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
