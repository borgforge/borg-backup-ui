'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
  try {
    for (const language of ['de','en']) {
      const page = await browser.newPage({viewport:{width:1200,height:1000}});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      let runsOverride=null, saveFailure=false, saveDelay=0;
      let profiles=[], actions=0, action='', deletes=0, lastAction;
      const browserDialogs=[];page.on('dialog',async dialog=>{browserDialogs.push(dialog.message());await dialog.dismiss();});
      const credential=language==='de'?'b'.repeat(32):'database-'+'a'.repeat(60)+'-v001';
      await page.route('http://bbui.test/**', async route => {
        const req=route.request(),url=new URL(req.url());
        let body={};
        if (url.pathname==='/') {await route.fulfill({contentType:'text/html',body:'<span id="settings-workspace-save-state"></span><main id="page-settings" style="max-width:850px;margin:20px auto"><div class="settings-tab-panel" data-settings-panel="databases"><div id="settings-databases-panel"></div></div><div id="wiz-databases"></div><div id="managed-preview"></div></main>'});return;}
        if (url.pathname==='/api/settings/databases') {
          if (req.method()==='POST') {
            if(saveDelay) await new Promise(resolve=>setTimeout(resolve,saveDelay));
            if(saveFailure){await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({code:'database_invalid_profile'})});return;}
            const {password,...payload}=req.postDataJSON(); const row={...payload,id:'db-aaaaaaaaaaaa',credential_id:credential};profiles=[row];body={profile:row};}
          else if(req.method()==='DELETE'){deletes++;profiles=[];body={deleted:true};}
          else body={profiles,unsupported_profiles:[{id:'db-cccccccccccc',name:'<img retired>',engine:'sqlite'}]};
        } else if(url.pathname.endsWith('/runs')) body=runsOverride || {runs:[{profile_id:'db-aaaaaaaaaaaa',profile_name:'MariaDB Apps',started_at:'2026-10-24T09:35:10Z',status:'dump_completed',compression:'gzip',bytes:123456789,uncompressed_bytes:5700000000,directory:'/mnt/cache/db-dumps/bbui-mariadb-apps-2026-10-24_11-35-10+0200-'+'a'.repeat(32)}],errors:[]};
        else if(url.pathname.endsWith('/action')) {actions++;lastAction=req.postDataJSON();action=lastAction.action;body={id:'a'.repeat(32),status:'running'};}
        else if(url.pathname.endsWith('/status')) body={status:'completed',profile_id:'db-aaaaaaaaaaaa',action,results:[],...(action==='discover'?{databases:['app','photos','new_unselected']}:{})};
        else if(url.pathname.endsWith('/runtime-inventory')) body={docker_containers:['mariadb-test','postgres-test']};
        await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto('http://bbui.test/');
      const index=fs.readFileSync('ui/index.html','utf8');
      await page.locator('body').evaluate((body,markup)=>body.insertAdjacentHTML('beforeend',markup),index.slice(index.indexOf('<div id="settings-dialog-modal"'),index.indexOf('<!-- Storage Key Deploy Modal -->')));
      await page.evaluate(lang=>document.documentElement.dataset.theme=lang==='en'?'light':'dark',language);
      for (const file of ['ui/style.css','ui/design-system.css','ui/settings-redesign.css']) await page.addStyleTag({content:fs.readFileSync(file,'utf8')});
      await page.evaluate(labels=>{
        window.BBUI={components:{i18n:{t:(key,params={})=>{
          const s=key.split('.').reduce((a,k)=>a?.[k],labels)||key;
          return s.replace(/\{(\w+)\}/g,(_,k)=>params[k]??'');
        }}}};
        window.escHtml=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
        window.settingsT=(key,params)=>window.BBUI.components.i18n.t('settings.'+key,params);
        window.settingsState={};
        window.settingsLocale=()=> 'de-DE';window.apiErrorMessage=d=>d.code||'error';
        window.wizardState={jobIdRequest:1};window._wizardShowError=()=>{};
      },JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`,'utf8')));
   await page.addScriptTag({content:fs.readFileSync('ui/js/utils/dom.js','utf8')});
      const settings=fs.readFileSync('ui/js/pages/settings.js','utf8');
      await page.addScriptTag({content:settings.match(/function settingsFmtBytes[\s\S]*?\n}/)[0]});
      await page.addScriptTag({content:settings.match(/function settingsCard[\s\S]*?\n}/)[0] + settings.match(/function settingsMenuIcon[\s\S]*?\n}/)[0]});
      for(const name of ['settingsFormSignature','_updateUnsavedChangesUi','canLeaveSettingsPage']) await page.addScriptTag({content:settings.match(new RegExp('(?:async )?function '+name+'[\\s\\S]*?\\n}'))[0]});
      await page.addScriptTag({content:settings.match(/function _openSettingsDialog[\s\S]*?\n}/)[0]});
      await page.addScriptTag({content:fs.readFileSync('ui/js/pages/databases.js','utf8')});
      await page.addScriptTag({content:settings.match(/async function activateSettingsTab[\s\S]*?\n}/)[0]});
      await page.evaluate(()=>{
        window.SETTINGS_PROFILE_CONFIG={};
        window.getSettingsTabs=()=>[{key:'databases',label:'Databases',description:''},{key:'general',label:'General',description:''}];
        settingsState.activeTab='databases';
      });
      await page.evaluate(()=>loadDatabaseSettings());
      assert.ok((await page.locator('#db-unsupported').textContent()).includes('<img retired>'));
      assert.equal(await page.locator('#db-unsupported img').count(),0);
      assert.equal(await page.locator('#db-container').evaluate(el=>el.tagName), 'SELECT');
      assert.equal(await page.locator('#db-container option').count(), 3);
      assert.equal(await page.locator('#settings-databases-panel').textContent().then(text=>text.includes(language==='de'?'Mitgelieferte Skripte':'Bundled scripts')), false);
      await page.locator('#db-name').fill('<img src=x onerror=alert(1)>');
      await page.locator('#db-container').selectOption('mariadb-test');
      await page.locator('#db-password').fill('fixture-secret');
      await page.locator('#db-staging_mount').fill('/mnt/cache');
      await page.locator('#db-staging_dir').fill('/mnt/cache/db-dumps');
      await page.locator('[data-db-discover]').click();
      await page.waitForSelector('#db-databases input[value=app]');
      assert.equal(await page.locator('#db-databases input:checked').count(),0);
      assert.equal(await page.locator('#db-password').inputValue(),'');
      assert.equal(JSON.stringify(profiles).includes('fixture-secret'),false);
      await page.locator('#db-databases input[value=app]').check();
      await page.locator('#db-databases input[value=photos]').check();
      await page.locator('.database-footer button[type=submit]').click();
      await page.waitForFunction(()=>document.getElementById('db-select').value==='db-aaaaaaaaaaaa' && !settingsState.databaseDirty);
      assert.equal(await page.locator('.database-secret-file code').textContent(), 'secrets/'+(language==='de'?'.database-':'')+credential+'.json');
      assert.equal(profiles[0].databases.length,2);assert.equal(profiles[0].retention,'keep');
      assert.equal(await page.locator('#settings-databases-panel img').count(),0);
      const savedName=await page.locator('#db-name').inputValue();
      await page.locator('#db-name').fill('edited profile');
      assert.equal(await page.evaluate(()=>settingsState.databaseDirty),true);
      await page.locator('#db-name').fill(savedName);
      assert.equal(await page.evaluate(()=>settingsState.databaseDirty),false);
      assert.equal(await page.evaluate(()=>canLeaveSettingsPage()),true);
      await page.locator('#db-name').fill('Saved database profile');
      await page.evaluate(()=>activateSettingsTab('databases'));
      assert.equal(await page.locator('#db-name').inputValue(),'Saved database profile');
      saveFailure=true;
      await page.locator('.database-footer button[type=submit]').click();
      await page.waitForSelector('#db-save-feedback.error-state');
      assert.equal(await page.locator('#db-name').inputValue(),'Saved database profile');
      assert.equal(await page.evaluate(()=>settingsState.databaseDirty),true);
      assert.ok((await page.locator('#settings-workspace-save-state').textContent()).length>0);
      saveFailure=false;saveDelay=150;
      await page.locator('.database-footer button[type=submit]').click();
      assert.equal(await page.locator('#db-name').isDisabled(),true);
      assert.equal(await page.evaluate(()=>canLeaveSettingsPage()),false);
      await page.waitForFunction(()=>!settingsState.profileSaving && !settingsState.databaseDirty);
      assert.equal(await page.locator('#db-name').inputValue(),'Saved database profile');
      assert.equal(await page.locator('#db-save-feedback.success-state').count(),1);
      assert.equal(await page.locator('#db-save-feedback.page-feedback').count(),0);
      assert.equal(await page.locator('#settings-workspace-save-state').textContent(),JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`,'utf8')).settings.menu.saved);
      assert.equal(await page.evaluate(()=>canLeaveSettingsPage()),true);
      saveDelay=0;
      // Preserve the malicious fixture name for the existing escaping tests.
      await page.locator('#db-name').fill(savedName);
      await page.locator('.database-footer button[type=submit]').click();
      await page.waitForFunction(()=>!settingsState.profileSaving && !settingsState.databaseDirty);
      await page.locator('[data-db-action=dump]').click();
      await page.waitForFunction(()=>document.getElementById('db-result').textContent.includes('Borg')===false && document.getElementById('db-cancel').disabled);
      assert.equal(actions,2);
      await page.waitForSelector('#db-runs .database-run-row');
      await page.locator('[data-run-details]').click();
      assert.ok((await page.locator('#db-runs').textContent()).includes('MariaDB Apps'));
      assert.ok((await page.locator('#db-runs').textContent()).includes('5.3 GB'));
      assert.equal(await page.locator('#db-runs time').getAttribute('datetime'),'2026-10-24T09:35:10Z');
      await page.locator('[data-cleanup]').click();
      assert.equal(await page.locator('#settings-dialog-modal').isVisible(),true);
      assert.equal(actions,2);
      assert.ok((await page.locator('#settings-dialog-description').textContent()).includes(language==='de'?'Borg-Archive bleiben unverändert':'Borg archives remain unchanged'));
      assert.ok((await page.locator('#settings-dialog-description').textContent()).includes('/mnt/cache/db-dumps/'));
      assert.ok((await page.locator('#settings-dialog-confirm-btn').getAttribute('class')).includes('btn-danger'));
      if(process.env.BBUI_SCREENSHOT_DIR)await page.locator('#settings-dialog-modal .modal').screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/cleanup-${language}.png`});
      await page.locator('#settings-dialog-cancel-btn').click();
      assert.equal(actions,2);
      await page.locator('[data-cleanup]').click();
      await page.locator('#settings-dialog-confirm-btn').click();
      await page.waitForFunction(()=>document.getElementById('db-cancel').disabled);
      assert.equal(actions,3);
      assert.equal(lastAction.action,'cleanup');assert.equal(lastAction.profile_id,'db-aaaaaaaaaaaa');
      assert.ok(lastAction.directory.startsWith('/mnt/cache/db-dumps/bbui-mariadb-apps-'));
      await page.locator('#db-name').fill('unsaved');
      await page.locator('[data-db-action=dump]').click();assert.equal(actions,3);
      await page.evaluate(()=>wizardLoadDatabases(1));
      await page.evaluate(()=>wizardApplyDatabases(['db-aaaaaaaaaaaa','db-bbbbbbbbbbbb']));
      assert.equal(await page.locator('#wiz-databases input:checked').count(),2);
      assert.equal(await page.locator('#wiz-databases img').count(),0);
      if (process.env.BBUI_SCREENSHOT_DIR) await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/databases-${language}.png`,fullPage:true});
      await page.setViewportSize({width:390,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true);
      await page.locator('#db-select').selectOption('');
      assert.equal(await page.locator('#settings-dialog-modal').isVisible(),true);
      await page.locator('#settings-dialog-cancel-btn').click();
      assert.equal(await page.locator('#db-select').inputValue(),'db-aaaaaaaaaaaa');
      assert.equal(await page.locator('#db-name').inputValue(),'unsaved');
      await page.locator('#db-select').selectOption('');
      await page.locator('#settings-dialog-confirm-btn').click();
      await page.waitForFunction(()=>document.getElementById('db-select').value==='');
      assert.equal(await page.locator('#db-name').inputValue(),'');
      await page.locator('#db-select').selectOption('db-aaaaaaaaaaaa');
      await page.locator('#db-delete').click();
      assert.equal(await page.locator('#settings-dialog-description img').count(),0);
      assert.ok((await page.locator('#settings-dialog-description').textContent()).includes('<img'));
      await page.locator('#settings-dialog-close-btn').click();assert.equal(deletes,0);
      await page.locator('#db-delete').click();
      await page.locator('#settings-dialog-confirm-btn').click();
      await page.waitForFunction(()=>document.querySelectorAll('#db-select option').length===1);
      assert.equal(deletes,1);
      assert.deepEqual(await page.locator('#db-engine option').evaluateAll(nodes=>nodes.map(n=>n.value).sort()),['mariadb','mysql','postgresql']);
      for (const engine of ['mysql','mariadb','postgresql']) {
        await page.locator('#db-engine').selectOption(engine);
        assert.equal(await page.locator('#db-globals-label').isVisible(),engine==='postgresql');
        assert.equal(await page.locator('#db-port').inputValue(),engine==='postgresql'?'5432':'3306');
        assert.equal(await page.locator('#db-password').isVisible(),true);
      }
      assert.equal(await page.locator('#db-sqlite-field, #db-auth-choice, #db-mongo-auth').count(),0);
      await page.locator('#db-name').fill('Keep draft on cancel');
      await page.evaluate(()=>{void activateSettingsTab('general');});
      assert.equal(await page.locator('#settings-dialog-modal').isVisible(),true);
      await page.evaluate(()=>{void activateSettingsTab('general');});
      assert.equal(await page.evaluate(()=>settingsState.activeTab),'databases');
      await page.locator('#settings-dialog-cancel-btn').click();
      assert.equal(await page.locator('#db-name').inputValue(),'Keep draft on cancel');
      assert.equal(await page.evaluate(()=>settingsState.databaseDirty),true);
      await page.evaluate(()=>{void activateSettingsTab('general');});
      await page.locator('#settings-dialog-close-btn').click();
      assert.equal(await page.evaluate(()=>settingsState.activeTab),'databases');
      await page.evaluate(()=>{void activateSettingsTab('general');});
      await page.locator('#settings-dialog-confirm-btn').click();
      await page.waitForFunction(()=>settingsState.activeTab==='general');
      assert.equal(await page.evaluate(()=>settingsState.databaseDirty),false);
      const labels=JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`,'utf8')).database;
      const storageError={profile_id:'db-aaaaaaaaaaaa',profile_name:'<img missing>',staging_dir:'/mnt/cache/<dump>',error_code:'database_storage_mount'};
      runsOverride={runs:[],errors:[storageError]};
      await page.evaluate(()=>loadDatabaseRuns());
      let runText=await page.locator('#db-runs').textContent();
      assert.ok(runText.includes(labels.runsUnavailable));
      assert.equal(runText.includes(labels.noRuns),false);
      assert.ok(runText.includes('<img missing>') && runText.includes('/mnt/cache/<dump>'));
      assert.equal(await page.locator('#db-runs img, #db-runs dump').count(),0);
      runsOverride={runs:[{profile_name:'Available profile',directory:'/mnt/cache/available',status:'dump_completed',bytes:123}],errors:[storageError]};
      await page.evaluate(()=>loadDatabaseRuns());
      runText=await page.locator('#db-runs').textContent();
      assert.ok(runText.includes('Available profile') && runText.includes('<img missing>'));
      assert.equal(runText.includes(labels.noRuns),false);
      runsOverride={runs:[],errors:[{...storageError,error_code:'database_storage_missing'}]};
      await page.evaluate(()=>loadDatabaseRuns());
      runText=await page.locator('#db-runs').textContent();
      assert.equal(runText.includes(labels.runsUnavailable),false);
      assert.ok(runText.includes('/mnt/cache/<dump>'));
      assert.equal(await page.locator('.database-pending-directory').count(),1);
      runsOverride={runs:[],errors:[]};
      await page.evaluate(()=>loadDatabaseRuns());
      assert.ok((await page.locator('#db-runs').textContent()).includes(labels.noRuns));
      // Compact retained-run table: separate origins, stable cleanup target and paging (#691).
      await page.setViewportSize({width:1200,height:1000});
      const mixed = Array.from({length:13}, (_,i) => ({
        profile_id:'db-aaaaaaaaaaaa', profile_name:i % 2 ? 'Sicherung PostgreSQL' : 'Sicherung MariaDB',
        directory:'/mnt/cache/borg-database-dumps/bbui-profile-'+i, started_at:`2026-11-${String(i+1).padStart(2,'0')}T20:14:00Z`,
        origin:i % 3 === 0 ? 'manual' : 'job', status:i === 11 ? 'failed' : i % 3 === 0 ? 'dump_completed' : 'archived',
        archived:i % 3 !== 0 && i !== 11, bytes:2800000000+i, uncompressed_bytes:5400000000,
        compression:'gzip', job_id:i % 3 === 0 ? '' : '11111111-1111-4111-8111-111111111111',
      }));
      mixed.push({profile_id:'db-aaaaaaaaaaaa',profile_name:'<img old>',directory:'/mnt/cache/<old>/'+'x'.repeat(180),origin:'unknown',started_at:'not-a-date',bytes:123,status:'dump_completed'});
      runsOverride={runs:mixed,errors:[]};
      await page.evaluate(()=>loadDatabaseRuns());
      assert.equal(await page.locator('.database-run-row').count(),10);
      assert.equal(await page.locator('.database-run-row time').first().getAttribute('datetime'),mixed[12].started_at,'Newest runs first across profiles');
      assert.equal(await page.locator('.database-run-detail').count(),0,'Long paths and cleanup start collapsed');
      assert.ok((await page.locator('[data-run-filter=all]').textContent()).includes('14'));
      assert.ok((await page.locator('[data-run-filter=manual]').textContent()).includes('5'));
      assert.ok((await page.locator('[data-run-filter=job]').textContent()).includes('8'));
      assert.ok((await page.locator('[data-run-filter=unknown]').textContent()).includes('1'));
      assert.ok(await page.locator('.database-run-row').evaluateAll(rows=>rows.every(row=>row.getBoundingClientRect().height<85)),'Compact rows replace large cards');
      if(process.env.BBUI_SCREENSHOT_DIR)await page.locator('.database-runs-body').screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/runs-table-${language}.png`});
      await page.locator('[data-run-page="1"]').click();
      assert.equal(await page.locator('.database-run-row').count(),4);
      assert.equal(await page.locator('[data-run-page="1"]').isDisabled(),true);
      await page.locator('[data-run-filter=job]').click();
      assert.equal(await page.locator('.database-run-row').count(),8);
      assert.ok((await page.locator('.database-run-row').first().textContent()).includes(labels.failed),'A failed export is still a job run');
      assert.equal(await page.locator('[data-run-page]').count(),0);
      await page.evaluate(()=>loadDatabaseRuns());
      assert.equal(await page.locator('[data-run-filter=job]').getAttribute('aria-pressed'),'true','Refresh retains selected origin');
      await page.locator('[data-run-filter=manual]').click();
      assert.equal(await page.locator('.database-run-row').count(),5);
      const toggle=page.locator('[data-run-details]').first();
      await toggle.focus();await page.keyboard.press('Enter');
      assert.equal(await toggle.getAttribute('aria-expanded'),'true');
      assert.equal(await toggle.evaluate(el=>document.activeElement===el),true,'Details preserve keyboard focus');
      assert.ok((await page.locator('.database-run-detail').textContent()).includes(mixed[12].directory));
      await page.evaluate(()=>{settingsState.databaseDirty=false;});
      const beforeCleanup=actions;
      await page.locator('[data-cleanup]').click();
      assert.ok((await page.locator('#settings-dialog-description').textContent()).includes(mixed[12].directory),'Filtered/sorted cleanup targets the displayed run');
      await page.locator('#settings-dialog-cancel-btn').click();assert.equal(actions,beforeCleanup);
      await page.locator('[data-cleanup]').click();await page.locator('#settings-dialog-confirm-btn').click();
      await page.waitForFunction(()=>document.getElementById('db-cancel').disabled);
      assert.equal(lastAction.directory,mixed[12].directory);
      assert.equal(lastAction.profile_id,mixed[12].profile_id);
      await page.locator('[data-run-filter=unknown]').click();
      assert.equal(await page.locator('.database-run-row').count(),1);
      await page.locator('[data-run-details]').click();
      assert.ok((await page.locator('.database-run-detail').textContent()).includes('/mnt/cache/<old>'));
      assert.equal(await page.locator('#db-runs img, #db-runs old').count(),0);
      await page.setViewportSize({width:390,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Narrow tables scroll internally');
      assert.equal(await page.locator('.database-runs-table-wrap').evaluate(el=>el.scrollWidth>el.clientWidth),true);
      if(process.env.BBUI_SCREENSHOT_DIR)await page.locator('.database-runs-body').screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/runs-table-narrow-${language}.png`});
      runsOverride={runs:[mixed[0]],errors:[]};
      await page.locator('[data-run-filter=job]').click();
      await page.evaluate(()=>loadDatabaseRuns());
      assert.ok((await page.locator('#db-runs').textContent()).includes(labels.runFilterEmpty));
      // A newer refresh wins even if an earlier request completes last.
      await page.evaluate(async () => {
        const original=databaseRequest;
        let finish;
        let call=0;
        databaseRequest=async (path,...rest) => {
          if(path!=='/runs')return original(path,...rest);
          if(++call===1)return new Promise(resolve=>{finish=resolve;});
          return {runs:[],errors:[]};
        };
        try {
          const old=loadDatabaseRuns();
          await loadDatabaseRuns();
          finish({runs:[{profile_name:'STALE RESULT',directory:'/stale',bytes:0}],errors:[]});
          await old;
        } finally {databaseRequest=original;}
      });
      assert.equal((await page.locator('#db-runs').textContent()).includes('STALE RESULT'),false);
      assert.deepEqual(browserDialogs,[]);
      assert.deepEqual(errors,[]);
      await page.close();
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
