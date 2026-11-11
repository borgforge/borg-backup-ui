'use strict';
// Real EventSource lifecycle against a local HTTP fixture, without a NAS (#730).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const {chromium} = require('playwright');
const until = async predicate => {
  const deadline = Date.now() + 5000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for fixture connections');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
};
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.BBUI_CHROMIUM ? {executablePath: process.env.BBUI_CHROMIUM} : {})});
  const streams = new Set(), actions = [], unexpected = [];
  let state = 'not_mounted', reads = 0;
  const broadcast = () => streams.forEach(({res, path}) => res.write(`data: ${JSON.stringify({mount_path: path, mount_state: state})}\n\n`));
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/') {
      res.setHeader('Content-Type', 'text/html');
      res.end('<main id="page-settings"><div id="settings-content"></div></main>'); return;
    }
    if (url.pathname === '/api/storage/smb-mount-status') {
      reads++;
      res.writeHead(200, {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store'});
      const stream = {res, path: url.searchParams.get('mount_path')};
      streams.add(stream);
      req.on('close', () => streams.delete(stream));
      res.write('retry: 15000\n\n'); broadcast(); return;
    }
    if (url.pathname === '/api/storage/smb-action') {
      let body = ''; for await (const chunk of req) body += chunk;
      const data = JSON.parse(body); actions.push(data.action);
      state = data.action === 'mount' ? 'mounted' : 'not_mounted';
      res.writeHead(200, {'Content-Type': 'application/json'}); res.end('{"ok":true}'); return;
    }
    unexpected.push(req.url); res.writeHead(404); res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    for (const language of ['de', 'en']) {
      state = 'not_mounted'; actions.length = 0;
      const page = await browser.newPage({viewport: {width: 1152, height: 1000}});
      const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
      const text = labels.settings.profiles;
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
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
      const expectStatus = label => page.waitForFunction(label => document.querySelector('[data-smb-profile-mount-status]').textContent === label, label);
      await expectStatus(text.notMounted);
      assert.equal(await unmount.isDisabled(), true);
      assert.equal(await page.locator('[data-settings-action="smb-profile-status"]').count(), 0);
      const initialRequests = reads;
      state = 'mounted'; broadcast(); await expectStatus(text.mounted);
      assert.equal(reads, initialRequests); // A change requires no second HTTP request.
      assert.equal(await mount.isDisabled(), true);
      assert.deepEqual(actions, []);
      await page.evaluate(() => { window.oldMountStream = settingsState.smbMountStatusSource; });
      await unmount.click(); await expectStatus(text.notMounted);
      // An already queued event from a closed stream must not restore stale state.
      await page.evaluate(() => window.oldMountStream.onmessage({data: JSON.stringify({mount_path:'/mnt/borg-backup-ui/smb/NAS Backup',mount_state:'mounted'})}));
      assert.equal(await status.textContent(), text.notMounted);
      await mount.click(); await expectStatus(text.mounted);
      assert.deepEqual(actions, ['unmount', 'mount']);
      if (process.env.BBUI_SCREENSHOT_DIR) await page.screenshot({path: `${process.env.BBUI_SCREENSHOT_DIR}/smb-${language}.png`, fullPage: true});
      await page.setViewportSize({width: 390, height: 844});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      streams.forEach(({res}) => res.write('data: invalid\n\n')); await expectStatus(text.mountStatusUnknown);
      state = 'read_only'; broadcast(); await expectStatus(text.mountedReadOnly);
      // Losing a connection makes state unknown, without probing the NAS.
      streams.forEach(({res}) => res.destroy()); await expectStatus(text.mountStatusUnknown);
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus()); await expectStatus(text.mountedReadOnly);
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange')); });
      await until(() => streams.size === 0);
      const beforeHidden = reads;
      await page.waitForTimeout(5200);
      assert.equal(reads, beforeHidden);
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, value: false}); document.dispatchEvent(new Event('visibilitychange')); });
      await until(() => streams.size === 1);
      await expectStatus(text.mountedReadOnly);
      // Expired/revoked sessions close the connection without automatic retry.
      streams.forEach(({res}) => res.write('event: expired\ndata: {}\n\n'));
      await expectStatus(text.mountStatusUnknown); await until(() => streams.size === 0);
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus()); await expectStatus(text.mountedReadOnly);
      await page.locator('[data-profile-edit]').click(); await until(() => streams.size === 0);
      const name = page.locator('[data-smb-profile-name]');
      await name.fill('Unsaved NAS name');
      const beforeEditing = reads;
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(reads, beforeEditing);
      assert.equal(await name.inputValue(), 'Unsaved NAS name');
      assert.equal(await mount.isDisabled(), true);
      await page.evaluate(() => { window.currentPage = 'jobs'; settingsState.profileEditing = ''; stopSmbMountStatusWatch(); });
      await page.evaluate(() => refreshSelectedSmbProfileMountStatus());
      assert.equal(reads, beforeEditing);
      assert.deepEqual(errors, []);
      await page.close();
    }
    assert.deepEqual(unexpected, []);
  } finally {
    await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
