'use strict';
// Exercise actual settings/device modules with synthetic API responses (#741).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
  try {
    for (const language of ['de','en']) for (const role of ['admin','operator','viewer']) {
      const page = await browser.newPage({viewport:{width:1200,height:1000}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      let approvals = [], revoked = [], requests = [], fail = false, failApproval = false;
      let sessions = [{id:'a'.repeat(32),label:'<img src=x onerror="window.injected=true">',created_at:1794820000,expires_at:1794863200,job_control:false}];
      await page.route('https://bbui.test/**', async route => {
        const req=route.request(), path=new URL(req.url()).pathname;
        if (path==='/') return route.fulfill({contentType:'text/html',body:fs.readFileSync('ui/index.html','utf8').replace('<script src="/ui/js/app-main.js"></script>','')});
        if (path.startsWith('/ui/')) {
          const file=path.slice(1);
          return route.fulfill({contentType:path.endsWith('.css')?'text/css':'text/plain',body:fs.existsSync(file)?fs.readFileSync(file):''});
        }
        requests.push(path);
        let data={};
        if(path==='/api/auth/status') data={auth_mode:'users',current_user:'test',current_role:role};
        else if(path==='/api/auth/mobile/sessions') {
          if(fail) return route.fulfill({status:503,contentType:'application/json',body:'{"message":"private-detail"}'});
          data={sessions,can_approve_job_control:role!=='viewer'};
        } else if(path==='/api/auth/mobile/approve') {
          if(failApproval) return route.fulfill({status:400,contentType:'application/json',body:'{"message":"private-detail"}'});
          approvals.push(req.postDataJSON()); await new Promise(resolve=>setTimeout(resolve,100)); data={approved:true};
        } else if(path==='/api/auth/mobile/revoke') {
          revoked.push(req.postDataJSON()); sessions=[]; data={revoked:true};
        } else if(role!=='admin') throw new Error('Non-admin requested '+path);
        else if(path==='/api/settings') data={storagebox_setup:{auth_checked:false}};
        else if(path==='/api/auth/users') data={users:[]};
        else if(path==='/api/notification-profiles') data={profiles:[]};
        return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      });
      await page.goto('https://bbui.test/');
      await page.evaluate(({labels,language})=>{
        window.BBUI={components:{i18n:{t:(key,params={})=>String(key.split('.').reduce((a,k)=>a?.[k],labels)||key).replace(/\{(\w+)\}/g,(_,name)=>params[name]??''),getLanguage:()=>language}}};
        window.locationIcon=()=>''; window.formLabelHtml=x=>x;
      },{labels:JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`)),language});
      for(const file of ['ui/js/utils/format.js','ui/js/utils/dom.js','ui/js/core/app-core.js','ui/js/pages/settings.js','ui/js/pages/mobile-devices.js'])
        await page.addScriptTag({content:fs.readFileSync(file,'utf8')});
      // Keep the production settings shell and user renderer; unrelated settings
      // sections have their own suites and need no storage/profile dependencies.
      const unrelated=[...fs.readFileSync('ui/js/pages/settings.js','utf8').matchAll(/function (renderSettings[A-Z]\w*)\(/g)]
        .map(m=>m[1]).filter(name=>!['renderSettingsUsers','renderSettingsUserAccounts','renderSettingsMenu'].includes(name));
      await page.evaluate(names=>{for(const name of names) window[name]=()=>'';},unrelated);
      await page.evaluate(async role=>{
        BBUI.core.setCurrentRole(role);
        BBUI.core.fetchSystemHealth=async()=>({});
        refreshSettingsConfigBackups=()=>{}; initializeSettingsProfileManagers=()=>{};
        settingsState.activeTab='users';
        document.getElementById('settings-content').addEventListener('click',onSettingsContentClick);
        document.getElementById('page-settings').classList.add('active');
        await refreshSettings();
      },role);
      await page.waitForSelector('[data-mobile-id]',{timeout:5000}).catch(async e=>{console.error(await page.locator('#settings-message').innerText(),errors);throw e;});
      assert.equal(await page.locator('#mobile-device-list img').count(),0);
      assert((await page.locator('#mobile-device-list').innerText()).includes('<img src=x'));
      assert.equal(await page.locator('#mobile-job-control').isDisabled(),role==='viewer');
      assert.equal(await page.locator('#user-new-name').count(),role==='admin'?1:0);
      if(role!=='admin') {
        assert.equal(await page.locator('[data-settings-tab]').count(),1);
        assert.equal(await page.locator('#settings-save-btn').isVisible(),false);
        assert(!requests.includes('/api/settings') && !requests.includes('/api/auth/users'));
      }
      if(process.env.BBUI_SCREENSHOT_DIR && language==='de' && role==='admin') {
        await page.evaluate(()=>document.documentElement.setAttribute('data-theme','dark'));
        await page.locator('#mobile-devices-settings').locator('..').screenshot({path:process.env.BBUI_SCREENSHOT_DIR+'/mobile-settings-devices.png'});
        await page.setViewportSize({width:390,height:900});
        const bounds=await page.locator('#mobile-devices-settings').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
        assert(bounds.scroll<=bounds.width+1, 'Device section overflows at phone width');
        await page.setViewportSize({width:1200,height:1000});
      }
      await page.locator('#mobile-pair-code').fill('ABCDE23456');
      if(role==='admin') {
        // Late user-account refresh must leave the pairing form and code intact.
        await page.evaluate(()=>{document.getElementById('settings-user-admin').innerHTML=renderSettingsUserAccounts();});
        assert.equal(await page.locator('#mobile-pair-code').inputValue(),'ABCDE23456');
      }
      await page.locator('[data-settings-action="mobile-refresh"]').click();
      await page.waitForFunction(()=>!document.getElementById('mobile-approve').disabled);
      assert.equal(await page.locator('#mobile-pair-code').inputValue(),'ABCDE23456');
      if(role!=='viewer') await page.locator('#mobile-job-control').check();
      await page.locator('#mobile-approve').click();
      await page.evaluate(()=>document.getElementById('mobile-pair-form').dispatchEvent(new Event('submit',{cancelable:true})));
      await page.waitForFunction(()=>document.getElementById('mobile-pair-code').value==='');
      assert.equal(approvals.length,1);
      assert.deepEqual(approvals[0],{user_code:'ABCDE23456',allow_job_control:role!=='viewer'});
      await page.locator('[data-settings-action="mobile-revoke"]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-mobile-id]').length===0);
      assert.deepEqual(revoked,[{session_id:'a'.repeat(32)}]);
      failApproval=true;
      await page.locator('#mobile-pair-code').fill('ABCDE23456');
      await page.locator('#mobile-approve').click();
      await page.waitForFunction(()=>!document.getElementById('mobile-approve').disabled);
      assert.equal(await page.locator('#mobile-device-result').evaluate(el=>el.classList.contains('error')),true);
      assert(!(await page.locator('#mobile-device-result').innerText()).includes('private-detail'));
      assert.equal(await page.locator('#mobile-pair-code').inputValue(),'ABCDE23456');
      failApproval=false;
      fail=true;
      await page.locator('[data-settings-action="mobile-refresh"]').click();
      await page.waitForFunction(()=>document.querySelector('#mobile-device-result').classList.contains('error'));
      assert(!(await page.locator('#mobile-device-result').innerText()).includes('private-detail'));
      assert.equal(await page.locator('#mobile-approve').isDisabled(),true);
      fail=false;
      await page.locator('[data-settings-action="mobile-refresh"]').click();
      await page.waitForFunction(()=>!document.getElementById('mobile-approve').disabled);
      // Navigation stays inside the application shell and can return to dashboard.
      await page.evaluate(()=>{BBUI.core.setAction('refreshStatus',()=>{});BBUI.core.navigate('dashboard');});
      assert.equal(await page.locator('#page-dashboard').evaluate(e=>e.classList.contains('active')),true);
      assert.deepEqual(errors,[]);
      if(process.env.BBUI_SCREENSHOT_DIR && language==='de' && role==='admin') {
        await page.evaluate(()=>BBUI.core.navigate('settings'));
        await page.waitForSelector('#mobile-approve');
        await page.locator('#mobile-devices-settings').screenshot({path:process.env.BBUI_SCREENSHOT_DIR+'/mobile-settings.png'});
      }
      await page.close();
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
