// Render the production card helper in Chromium and verify attribution/escaping.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const script = fs.readFileSync('ui/js/pages/settings.js', 'utf8');
  const helper = script.slice(script.indexOf('function renderAboutBundle('), script.indexOf('function renderSettingsAbout('));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const bundles = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).bundles;
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    for (const lang of ['de', 'en']) {
      const dict = JSON.parse(fs.readFileSync(`ui/i18n/${lang}.json`, 'utf8')).settings;
      const context = vm.createContext({escHtml: esc, escAttr: esc, settingsT: key => key.split('.').reduce((o,k) => o[k], dict)});
      vm.runInContext(helper, context);
      for (const source of ['external', 'bundled']) {
        const html = bundles.map(bundle => context.renderAboutBundle(bundle, {version: '3.12.4', source, path: '/active/python'})).join('');
        await page.setContent(html);
        assert.equal(await page.locator('[data-license-bundle]').count(), 4);
        for (const bundle of bundles) {
          const card = page.locator(`[data-license-bundle="${bundle.id}"]`);
          await card.locator('.about-license-notices > summary').click();
          for (const summary of await card.locator('.about-bundle-notice > summary').all()) await summary.click();
          assert.equal(await card.locator('pre').count(), bundle.notices.length);
          for (let i = 0; i < bundle.notices.length; i++) {
            assert.equal(await card.locator('pre').nth(i).textContent(), bundle.notices[i].content);
          }
        }
        const pythonText = await page.locator('[data-license-bundle="python"]').innerText();
        assert(pythonText.includes('3.13.18') && pythonText.includes('3.12.4') && pythonText.includes('/active/python'));
        assert(pythonText.includes(dict.health[source === 'bundled' ? 'pythonBundled' : 'pythonExternal']));
        assert.equal(await page.evaluate(() => window.licenseExecuted), undefined);
        assert.equal(await page.locator('[data-license-bundle="python"] script').count(), 0);
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
