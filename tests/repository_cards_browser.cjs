'use strict';
// Exercise registry identity, stable panels and existing action routing on the actual UI (#621).
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
  try {
    const page=await browser.newPage({viewport:{width:1600,height:1100}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    let html=fs.readFileSync('ui/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
    html=html.replace(/<link[^>]+href="\/([^\"]+)"[^>]*>/g,(_,path)=>path.endsWith('.css')?`<style>${fs.readFileSync(path,'utf8')}</style>`:'');
    html=html.replace('src="/ui/assets/app-icon.png"',`src="data:image/png;base64,${fs.readFileSync('ui/assets/app-icon.png').toString('base64')}"`);
    await page.setContent(html);
    await page.evaluate(dicts=>{
      window.lang='de'; window.dicts=dicts;
      window.BBUI={components:{i18n:{getLanguage:()=>lang,t:(key,params={})=>{
        const text=key.split('.').reduce((value,part)=>value?.[part],dicts[lang]);
        return typeof text==='string'?text.replace(/\{(\w+)\}/g,(_,key)=>params[key]??''):key;
      }}}};
      document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-storage'));
      document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page==='storage'));
      document.documentElement.dataset.theme='light';
    },Object.fromEntries(['de','en'].map(lang=>[lang,JSON.parse(fs.readFileSync(`ui/i18n/${lang}.json`,'utf8'))])));
    for(const path of ['ui/js/utils/dom.js','ui/js/utils/format.js','ui/js/pages/dashboard.js','ui/js/pages/jobs.js','ui/js/pages/storage.js'])await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
    await page.evaluate(()=>{
      const result={status:'success',finished_at:'2026-10-28T09:46:00Z',started_at:'2026-10-28T09:45:56Z',duration_seconds:4};
      window.baseRepo={last_info_refresh_at:'2026-10-28T11:48:00Z',repository_key:'flash',repository_name:'borg-backup-flash',display_name:'Flash',backup_type:'flash',storage_key:'local',storage_name:'Backup-Lokal',used_by:['job1','job2'],path_display:'/mnt/backup/borg-backup-flash',encryption:'repokey-blake2',borg_key_exported_at:'2026-10-24T15:40:00Z',borg_repository_id:'a'.repeat(64),repository_stats:{archives_count:14,total_size:43.4*1024**3,total_csize:42.2*1024**3,unique_csize:6.7*1024**3,latest_archive_files:123456,latest_archive_name:"flash-latest"},maintenance_results:{check:{...result,details:['Repository check complete. <safe>']},verify_data:result,prune:{...result,deleted_archives_count:2,deleted_archives:['old <archive>','older-archive']},compact:{...result,freed_space:'1.2 GB'}}};
      storageState.jobs=[{key:'job1',name:'Flash – Lokal',icon:'flash',icon_color:'blue',retention:{mode:'last',last:3}},{key:'job2',name:'Flash nachts',icon:'flash',icon_color:'blue',retention:{mode:'last',last:3}}];
      storageState.data={storages:[{storage_key:'local',display_name:'Backup-Lokal',location:'local'},{storage_key:'local2',display_name:'Zweites lokales Ziel',location:'local'},{storage_key:'usb',display_name:'USB-5TB',location:'usb',mount_state:'not_mounted'}],groups:{local:[baseRepo,{...baseRepo,repository_key:'old',display_name:'Archiv ohne Job',backup_type:'photos',borg_key_exported_at:'',used_by:[],storage_key:'local2',storage_name:'Zweites lokales Ziel',maintenance_results:{},repository_stats:{archives_count:0}}],usb:[{...baseRepo,repository_key:'usb',display_name:'Flash <USB>',storage_key:'usb',storage_name:'USB-5TB',used_by:[],repository_stats:{unique_csize:123,archives_count:4},maintenance_results:{}}]},repository_info_refresh:{enabled:false}};
      window.calls=[];
      window.fetch=async(url,options={})=>{
        calls.push({url,body:options.body});let data;
        if(url==='/api/repositories/lifecycle'){const key=JSON.parse(options.body).repository_key;data={allowed:key!=='flash',job_keys:key==='flash'?['job1','job2']:[],blockers:key==='flash'?['jobs_linked']:[],repository_id:'a'.repeat(64),archive_count:14};}
        else if(url.startsWith('/api/repositories/archives?'))data={repository_id:'a'.repeat(64),can_delete:true,archive_count:14,archives:Array.from({length:14},(_,i)=>({name:`flash-${String(i).padStart(2,'0')}`,id:`archive${i}`,start:'2026-10-28T09:00:00Z'}))};
        else if(url.startsWith('/api/repositories/archive-files?'))data={files:[{name:'boot',type:'d',path:'boot',mtime:'2026-10-28T09:00:00Z'}]};
        else if(url==='/api/repositories/info') {baseRepo.last_info_refresh_at='2026-10-30T14:17:00Z';baseRepo.repository_stats.latest_archive_files=123457;data={ok:true};}
        else if(url==='/api/storage')data=storageState.data;
        else if(url==='/api/jobs')data={jobs:storageState.jobs};
        else if(url==='/api/storage/check/state')data={running:false};
        else throw Error('Unexpected API '+url);
        return {ok:true,json:async()=>data};
      };
      document.getElementById('storage-location-list').addEventListener('click',onStorageLocationClick);
      document.getElementById('storage-content').addEventListener('click',onStorageContentClick);
      renderStorage(storageState.data);
    });
    assert.equal(await page.locator('.storage-repository-card').count(),3,'Registry includes unassigned repositories');
    assert.equal(await page.locator('.storage-repository-master-detail').count(),0,'Cards start collapsed');
    assert.match(await page.locator('[data-repository-card=flash] .storage-card-jobs').innerText(),/Jobs: Flash – Lokal, Flash nachts/);
    assert.equal(await page.locator('[data-repository-card=usb] USB').count(),0,'Names are escaped');
    assert.equal(await page.locator('.storage-target-bar .storage-target-count').count(),4,'Exact targets, not just transport groups');
    assert.equal(await page.locator('.storage-target-group-heading').count(),3,'A divider separates each exact storage target');
    assert.equal(await page.locator('#storage-sidebar-search').count(),0,'Repository search removed');
    assert.match(await page.locator('[data-repository-card=old] .storage-card-key-warning').innerText(),/Borg-Key-Export fehlt/);
    assert.equal(await page.locator('[data-repository-card=flash] .type-icon-color-blue').count(),1);
    assert.equal(await page.locator('[data-repository-card=old] .type-icon-color-purple').count(),1,'Unassigned repositories retain a type icon');
    assert.equal(await page.locator('.storage-card-status.success').count(),0,'Cached data never proves reachability');
    assert.equal(await page.locator('[data-repository-card=usb] .storage-card-status.neutral').count(),0,'An unmounted scheduled target is not an error');
    assert.match(await page.locator('[data-repository-card=old] .storage-card-jobs').innerText(),/Jobs: Keine/);
    assert.match(await page.locator('[data-repository-card=old] .storage-card-size').innerText(),/0 Archive.*— belegt/s,'Missing size is not zero');
    assert.match(await page.locator('[data-repository-card=usb] .storage-card-target').innerText(),/USB-5TB\s+USB/);
    const columns=await page.locator('[data-repository-card=flash] .storage-card-summary > div').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().x));
    const headings=await page.locator('.storage-column-headings').first().locator('> span').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().x));
    assert.equal(columns.length,4);
    columns.forEach((x,i)=>assert.ok(Math.abs(x-headings[i])<1,'Column headings align with facts'));
    await page.evaluate(()=>{baseRepo.maintenance_results.check={status:'error',finished_at:'2026-10-29T09:00:00Z'};renderStorage(storageState.data);});
    assert.match(await page.locator('[data-repository-card=flash] .storage-card-identity .storage-card-status').innerText(),/Letzte Wartung fehlgeschlagen/);
    await page.evaluate(()=>{baseRepo.maintenance_results.check={status:'success',finished_at:'2026-10-28T09:46:00Z',details:['Repository check complete. <safe>']};storageState.maintenanceState={running:true,target_key:'flash'};renderStorage(storageState.data);});
    assert.equal(await page.locator('[data-repository-card=flash] .storage-card-status.info').count(),1,'Active work remains visible');
    await page.evaluate(()=>{storageState.maintenanceState={running:false};renderStorage(storageState.data);});
    const chevron=page.locator('[data-repository-card=flash] .storage-card-toggle');
    assert.ok((await chevron.boundingBox()).x < (await page.locator('[data-repository-card=flash] .storage-card-identity h2').boundingBox()).x);
    await page.locator('[data-storage-target="target:local2"]').click();
    assert.equal(await page.locator('.storage-repository-card').count(),1);
    assert.match(await page.locator('.storage-repository-card').innerText(),/Archiv ohne Job/);
    await page.locator('[data-storage-target=all]').click();
    const card=page.locator('[data-repository-card=flash]');
    await page.setViewportSize({width:1600,height:800});
    await card.locator('[data-storage-action=toggle-repository]').click();
    await page.waitForFunction(()=>!!BBUI.storageState.lifecycleCache.flash?.job_keys);
    await page.waitForFunction(()=>Math.abs(document.querySelector('[data-repository-card=flash]').getBoundingClientRect().top-16)<2);
    const overview=card.locator('[data-repository-panel=overview]');
    assert((await overview.boundingBox()).height<600,'Overview must not reserve the height of hidden archive/maintenance panes');
    assert.match(await overview.locator('.storage-statistics-heading').innerText(),/Statistik abgerufen:.*28/s);
    assert.equal(await overview.locator('[data-storage-action=repository-info]').count(),1);
    assert.match(await overview.locator('.storage-repository-stats').innerText(),/Dateien im neuesten Archiv.*123.456/s);
    assert.equal(await overview.locator('.storage-maintenance-summary-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),2);
    const maintenanceBefore=await overview.locator('.storage-maintenance-summary-grid').innerText();
    await overview.locator('[data-storage-action=repository-info]').click();
    await page.waitForFunction(()=>document.querySelector('.storage-statistics-heading').textContent.includes('30/10/2026'));
    assert.match(await overview.locator('.storage-repository-stats').innerText(),/123.457/);
    assert.equal(await overview.locator('.storage-maintenance-summary-grid').innerText(),maintenanceBefore,'Statistics refresh does not rerun or redate maintenance');
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.url==='/api/repositories/info').length),1);
    const cachedCounts=await page.evaluate(()=>{
      const original=baseRepo.repository_stats.latest_archive_files;
      delete baseRepo.repository_stats.latest_archive_files;renderStorage(storageState.data);
      const missing=document.querySelector('.storage-repository-stats > div:last-child strong').textContent;
      baseRepo.repository_stats.latest_archive_files=0;renderStorage(storageState.data);
      const zero=document.querySelector('.storage-repository-stats > div:last-child strong').textContent;
      baseRepo.repository_stats.latest_archive_files=original;renderStorage(storageState.data);
      return {missing,zero};
    });
    assert.deepEqual(cachedCounts,{missing:'—',zero:'0'});
    const beforeRefresh=await page.evaluate(()=>scrollY);
    await page.evaluate(()=>renderStorage(storageState.data));
    assert.equal(await page.evaluate(()=>scrollY),beforeRefresh,'Background refresh does not scroll');
    if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/compact-repository-overview.png`});

    assert.equal(await page.evaluate(()=>calls.some(c=>c.url.includes('/archives?'))),false,'Expanding a card does not scan archives');
    // Hold the first archive response to reproduce Overview -> loading -> Archives -> Overview (#662).
    const compactHeight=(await card.boundingBox()).height;
    await page.evaluate(()=>{
      window.originalFetch=window.fetch;
      window.fetch=async (...args)=>{
        if(args[0].startsWith('/api/repositories/archives?'))await new Promise(resolve=>window.releaseArchives=resolve);
        return originalFetch(...args);
      };
    });
    await card.locator('[data-repository-tab=archives]').click();
    await page.waitForFunction(()=>typeof releaseArchives==='function');
    assert.equal((await card.boundingBox()).height,compactHeight,'Loading does not grow the card');
    await page.evaluate(()=>{releaseArchives();window.fetch=originalFetch;});
    await page.waitForFunction(()=>!!BBUI.storageState.archiveCache.flash?.data);
    assert.equal((await card.boundingBox()).height,compactHeight,'Loaded archives fit the initial overview');
    if(process.env.BBUI_SCREENSHOT_DIR)await card.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/stable-archives.png`});
    await card.locator('[data-repository-tab=overview]').click();
    assert.equal((await card.boundingBox()).height,compactHeight,'Cached return does not retain an oversized archive panel');
    assert.equal(await card.locator('.storage-repository-panels').getAttribute('data-active-tab'),'overview');
    assert(await overview.evaluate(panel=>panel.getBoundingClientRect().bottom-panel.firstElementChild.getBoundingClientRect().bottom<35),'No oversized blank area below the overview');
    await page.evaluate(()=>renderStorage(storageState.data));
    assert.equal((await card.boundingBox()).height,compactHeight,'Background rendering preserves the compact height');
    if(process.env.BBUI_SCREENSHOT_DIR)await card.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/stable-overview-return.png`});
    await card.locator('[data-repository-tab=archives]').click();
    // Measured row heights fill the available space; both pagers disclose the range (#658).
    for (const lang of ['de', 'en']) {
      await page.setViewportSize({width:1280,height:500});
      await page.evaluate(lang=>{window.lang=lang;storageState.archivePages.flash=0;renderStorage(storageState.data);},lang);
      const top = card.locator('[data-pagination-position=top]');
      const bottom = card.locator('[data-pagination-position=bottom]');
      const visibleEntries = card.locator('.storage-archive-entry:not([hidden])');
      assert.equal(await card.locator('.storage-archive-column .storage-archive-pagination').count(),2);
      await top.scrollIntoViewIfNeeded();
      const bounds = await top.boundingBox();
      const list = await card.locator('.storage-archive-list').boundingBox();
      const browserPane = await card.locator('.storage-archive-browser').boundingBox();
      assert(bounds.y >= 0 && bounds.y + bounds.height <= 500);
      assert(bounds.y + bounds.height <= list.y && bounds.x + bounds.width <= browserPane.x);
      assert.match(await top.innerText(), /1–\d+.*14/s);
      assert(await top.locator('[data-page-step=previous]').isDisabled());
      const shortCount = await visibleEntries.count();
      const names=[];
      let step=0;
      while (true) {
        assert.equal(await top.innerText(),await bottom.innerText());
        names.push(...await visibleEntries.locator('.storage-archive-row').evaluateAll(rows=>rows.map(row=>row.dataset.archive)));
        const fits=await card.locator('.storage-archive-list').evaluate(list=>list.scrollHeight<=list.clientHeight+1);
        assert(fits,'Only complete rows should fill the page');
        if(await top.locator('[data-page-step=next]').isDisabled())break;
        await (step++ % 2 ? bottom : top).locator('[data-page-step=next]').click();
        assert(step<14,'Pagination must terminate');
      }
      assert.equal(names.length,14);
      assert.equal(new Set(names).size,14,'Every loaded archive is reachable exactly once');
      const anchor=await visibleEntries.first().locator('.storage-archive-row').getAttribute('data-archive');
      await page.setViewportSize({width:1280,height:1100});
      await page.waitForFunction(shortCount=>document.querySelectorAll('.storage-archive-entry:not([hidden])').length>shortCount,shortCount);
      assert(await visibleEntries.locator(`.storage-archive-row[data-archive="${anchor}"]`).isVisible(),'Resize retains the previous first archive');
      assert(await visibleEntries.count()>5,'Tall windows use more than five rows');
      if(process.env.BBUI_SCREENSHOT_DIR) {
        await top.scrollIntoViewIfNeeded();
        await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/archive-paging-${lang}-tall.png`});
      }
      await page.setViewportSize({width:1280,height:500});
      await page.waitForFunction(()=>document.querySelectorAll('.storage-archive-entry:not([hidden])').length<6);
      if(process.env.BBUI_SCREENSHOT_DIR) {
        await top.scrollIntoViewIfNeeded();
        await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/archive-paging-${lang}-short.png`});
      }
    }
    await page.setViewportSize({width:1600,height:800});
    await page.evaluate(()=>{window.lang='de';storageState.archivePages.flash=0;renderStorage(storageState.data);});
    // Long names stay on one line; the full text is available in the title and browser (#660).
    await page.evaluate(()=>{
      window.originalArchiveNames=storageState.archiveCache.flash.data.archives.map(a=>a.name);
      storageState.archiveCache.flash.data.archives.forEach((a,i)=>{a.name=`backup-${i}-`+'long-archive-name-'.repeat(i%3+3);});
      renderStorage(storageState.data);
    });
    assert(await card.locator('.storage-archive-list').evaluate(list=>list.scrollHeight<=list.clientHeight+1));
    assert(await card.locator('.storage-archive-entry:not([hidden])').count()>5);
    const longName=card.locator('.storage-archive-entry:not([hidden]) strong').first();
    assert.equal(await longName.getAttribute('title'),await longName.innerText());
    assert.equal(await longName.evaluate(el=>getComputedStyle(el).whiteSpace),'nowrap');
    assert.equal(await longName.evaluate(el=>getComputedStyle(el).textOverflow),'ellipsis');
    await page.evaluate(()=>{
      storageState.archiveCache.flash.data.archives.forEach((a,i)=>{a.name=originalArchiveNames[i];});
      storageState.archivePages.flash=0;renderStorage(storageState.data);
    });
    const archiveLayoutBefore=await card.locator('.storage-archive-layout').boundingBox();
    const pagerBefore=await card.locator('[data-pagination-position=bottom]').boundingBox();
    assert(await card.locator('.storage-archive-entry:not([hidden])').count()>5);
    assert.equal(await card.locator('.storage-archive-entry small').count(),0,'Technical IDs are not displayed');
    assert.equal(await page.evaluate(()=>storageState.archiveCache.flash.data.archives[0].id),'archive0','IDs remain available for guarded actions');
    await card.locator('[data-pagination-position=top] [data-storage-action=archive-page][data-page="1"]').click();
    assert.equal(await page.evaluate(()=>storageState.archivePages.flash),1);
    await card.locator('.storage-archive-entry:not([hidden]) [data-storage-action=open-repository-archive]').first().click();
    await page.waitForFunction(()=>BBUI.storageState.archiveBrowser.files.length===1);
    assert.equal(await card.locator('.storage-archive-browser-table [data-storage-action=browse-repository-archive-path]').count(),1);
    assert.equal(await card.locator('.storage-archive-entry:not([hidden]) [data-storage-action=delete-repository-archive]').count(),await card.locator('.storage-archive-entry:not([hidden])').count());
    assert.ok(Math.abs((await card.locator('.storage-archive-layout').boundingBox()).height-archiveLayoutBefore.height)<1,'Opening browser retains workspace height');
    assert.ok(Math.abs((await card.locator('[data-pagination-position=bottom]').boundingBox()).y-pagerBefore.y)<1,'Opening browser retains pager position');
    for(const width of [1600,1024,390]){
      await page.setViewportSize({width,height:1100});
      // Viewport emulation returns before resize/ResizeObserver layout settles.
      // Measure after their rendering turn, preserving the strict geometry checks (#677).
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const geometry=()=>card.locator('[data-pagination-position=bottom]').evaluate(n=>({top:n.getBoundingClientRect().top+scrollY,buttons:[...n.querySelectorAll('button')].map(b=>b.getBoundingClientRect().x)}));
      const baseline=await geometry();
      for(const variant of ['many','one','empty','loading','error','long-path']){
        await page.evaluate(variant=>{
          const browser=storageState.archiveBrowser;
          browser.loading=variant==='loading';browser.error=variant==='error'?'Read failed <safe>':'';
          browser.path=variant==='long-path'?Array.from({length:20},(_,i)=>`long-folder-${i}`).join('/'):'boot';
          browser.files=Array.from({length:variant==='many'?80:variant==='empty'?0:1},(_,i)=>({name:`file-${i}`,type:'-',path:`boot/file-${i}`,size:100,mtime:'2026-10-28T09:00:00Z'}));
          renderStorage(storageState.data);
        },variant);
        if(process.env.BBUI_SCREENSHOT_DIR && variant==='many')await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/archive-browser-${width}.png`,fullPage:true});
        const current=await geometry();
        assert.ok(Math.abs(current.top-baseline.top)<1,`Pager stays fixed for ${variant}/${width}`);
        current.buttons.forEach((x,i)=>assert.ok(Math.abs(x-baseline.buttons[i])<1,'Pager buttons retain horizontal positions'));
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      }
      await card.locator('[data-storage-action=close-repository-archive]').click();
      await page.waitForFunction(expected=>Math.abs(document.querySelector('[data-pagination-position=bottom]').getBoundingClientRect().top+scrollY-expected)<1,baseline.top);
      assert.ok(Math.abs((await geometry()).top-baseline.top)<1,`Closing browser retains pager position at ${width}: before ${baseline.top}, after ${(await geometry()).top}`);
      await card.locator('.storage-archive-entry:not([hidden]) [data-storage-action=open-repository-archive]').first().click();
      await page.waitForFunction(()=>!storageState.archiveBrowser.loading);
    }
    await page.setViewportSize({width:1600,height:1100});
    await card.locator('[data-repository-tab=management]').click();
    assert.equal(await card.locator('[data-storage-action=repository-lifecycle][data-lifecycle-mode=delete]').isDisabled(),true);
    assert.equal(await card.locator('[data-storage-action=repository-key-import-select]').isDisabled(),false,'Linked jobs do not block key recovery');
    await card.locator('[data-repository-tab=maintenance]').click();
    assert.equal(await card.locator('.storage-maintenance-page [data-storage-action=repository-maintenance]').count(),4);
    assert.match(await card.locator('.storage-maintenance-page').innerText(),/1.2 GB/);
    assert.match(await card.locator('.storage-maintenance-page').innerText(),/old <archive>/);
    assert.equal(await card.locator('.storage-maintenance-page archive').count(),0,'Result details are escaped');
    await card.locator('.storage-maintenance-page details summary').first().click();
    assert.match(await card.locator('.storage-maintenance-page details pre').innerText(),/Repository check complete. <safe>/);
    assert.equal(await card.locator('.storage-maintenance-page safe').count(),0);
    const geometry=()=>card.locator('[data-repository-panel=maintenance] [data-storage-action=repository-maintenance]').evaluateAll(nodes=>nodes.map(n=>({x:n.getBoundingClientRect().x,w:n.getBoundingClientRect().width,label:n.textContent})));
    const before=await geometry();
    await page.evaluate(()=>{window.savedCheckRun=checkRun;checkRun=(...args)=>window.routedMaintenance=args;});
    await card.locator('[data-repository-panel=maintenance] [data-repository-action=compact]').click();
    assert.deepEqual(await page.evaluate(()=>routedMaintenance),['flash','compact','quick']);
    await page.evaluate(()=>{checkRun=savedCheckRun;storageState.maintenanceState={running:true,target_key:'flash',action:'compact'};renderStorage(storageState.data);});
    const after=await geometry();assert.deepEqual(after,before,'Running action keeps Start label and width');
    assert.equal(await card.locator('.storage-maintenance-page button:disabled').count(),4);
    await page.evaluate(()=>{storageState.maintenanceState={running:false};baseRepo.maintenance_results.compact.freed_space='0 B';renderStorage(storageState.data);});
    assert.match(await card.locator('.storage-maintenance-page').innerText(),/0 B/);
    await page.evaluate(()=>{delete baseRepo.maintenance_results.compact.freed_space;renderStorage(storageState.data);});
    assert.match(await card.locator('.storage-maintenance-page').innerText(),/Speichermenge nicht erfasst/);
    await page.evaluate(()=>{baseRepo.maintenance_results.compact.freed_space='1.2 GB';renderStorage(storageState.data);});
    for(const width of [1600,1024,390])for(const lang of ['de','en']){
      await page.setViewportSize({width,height:1100});await page.evaluate(lang=>{window.lang=lang;document.documentElement.lang=lang;renderStorage(storageState.data);},lang);
      const heights=[];
      for(const tab of ['overview','archives','maintenance','management','overview']){
        await card.locator(`[data-repository-tab=${tab}]`).click();
        if(tab==='overview') {
          assert.equal(await card.locator('.storage-repository-overview .storage-repository-stats > div').count(),6);
        }
        heights.push((await card.boundingBox()).height);
        const activePanel=card.locator('[data-repository-panel].is-active');
        assert(await activePanel.evaluate(panel=>panel.scrollWidth<=panel.clientWidth+1),`No horizontal panel overflow ${width}/${lang}/${tab}`);
        if(width===390 && tab==='management') {
          assert(await activePanel.evaluate(panel=>{
            panel.scrollTop=panel.scrollHeight;
            return panel.querySelector('[data-lifecycle-mode=delete]').getBoundingClientRect().bottom<=panel.getBoundingClientRect().bottom;
          }),'Last management action remains reachable on narrow screens');
        }
        if(width===390 && tab==='overview') {
          assert(await activePanel.evaluate(panel=>panel.scrollHeight>panel.clientHeight),'Long mobile overview scrolls internally');
          assert(await activePanel.evaluate(panel=>{
            panel.scrollTop=panel.scrollHeight;
            return panel.firstElementChild.getBoundingClientRect().bottom<=panel.getBoundingClientRect().bottom;
          }),'Last overview details remain reachable');
        }
        assert.equal(await card.locator('[data-repository-panel]:not(.is-active) button').evaluateAll(nodes=>nodes.every(n=>getComputedStyle(n).visibility==='hidden')),true,'Inactive controls cannot paint through hidden panels');
        assert.equal(await card.locator('[data-repository-panel]:not(.is-active)').evaluateAll(nodes=>nodes.every(n=>n.inert&&getComputedStyle(n).visibility==='hidden')),true);
      }
      assert.ok(Math.max(...heights)-Math.min(...heights)<1,`Stable panels at ${width}/${lang}: ${heights}`);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`No page overflow ${width}/${lang}`);
    }
    // Completed checks must fit the original compact height; expanded output cannot move controls (#666).
    await page.evaluate(()=>{window.maintenanceResultsBefore=baseRepo.maintenance_results;});
    for(const width of [1600,1440,1280])for(const lang of ['de','en']) {
      await page.setViewportSize({width,height:900});
      await page.evaluate(lang=>{
        window.lang=lang;document.documentElement.lang=lang;
        baseRepo.maintenance_results={};storageState.maintenanceState={running:false};storageWorkspaceSize=null;
        storageState.selectedTab='overview';renderStorage(storageState.data);
      },lang);
      const initialHeight=(await card.boundingBox()).height;
      await card.locator('[data-repository-tab=maintenance]').click();
      const panel=card.locator('[data-repository-panel=maintenance]');
      const initialPanelHeight=(await panel.boundingBox()).height;
      const buttonPositions=()=>panel.locator('[data-storage-action=repository-maintenance]').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top-n.closest('[data-repository-panel]').getBoundingClientRect().top));
      const initialButtons=await buttonPositions();
      for(const variant of ['mixed','recorded','warning','error','running']) {
        await page.evaluate(variant=>{
          baseRepo.maintenance_results=Object.fromEntries(['check','verify_data','prune','compact'].map(key=>[key,{
            status:['warning','error'].includes(variant)?variant:'success',finished_at:'2026-10-30T15:30:00Z',duration_seconds:420,
            ...(variant!=='mixed'||key==='check'?{details:Array.from({length:20},(_,i)=>`${key} output ${i} <safe>`)}:{})
          }]));
          storageState.maintenanceState=variant==='running'?{running:true,target_key:'flash',action:'check'}:{running:false};
          renderStorage(storageState.data);
        },variant);
        assert.equal((await panel.boundingBox()).height,initialPanelHeight,`Completed checks retain shared workspace height ${width}/${lang}/${variant}`);
        if(['mixed','recorded'].includes(variant))assert.equal((await card.boundingBox()).height,initialHeight,'Successful results retain the original card height');
        assert(await panel.evaluate(p=>p.scrollHeight<=p.clientHeight+1),`Maintenance fits without outer scrolling ${width}/${lang}/${variant}`);
        assert(await panel.locator('.storage-maintenance-copy').evaluateAll(nodes=>nodes.every(n=>n.scrollHeight<=n.clientHeight+1)),`Collapsed result text fits ${width}/${lang}/${variant}`);
        assert.deepEqual(await buttonPositions(),initialButtons,'Maintenance controls stay aligned when results change');
        assert.equal(initialButtons[0],initialButtons[1]);assert.equal(initialButtons[2],initialButtons[3]);
        if(variant==='mixed' && process.env.BBUI_SCREENSHOT_DIR)await card.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/maintenance-completed-${width}-${lang}.png`});
        if(variant==='recorded') {
          for(const summary of await panel.locator('details summary').all())await summary.click();
          assert.deepEqual(await buttonPositions(),initialButtons,'Expanded logs do not move Start buttons');
          assert(await panel.evaluate(p=>p.scrollHeight<=p.clientHeight+1),`Expanded logs do not overflow the tab: ${JSON.stringify(await panel.evaluate(p=>({h:p.clientHeight,s:p.scrollHeight,children:[...p.querySelectorAll('.storage-maintenance-page,.storage-maintenance-action-grid,.storage-maintenance-card,.storage-maintenance-copy')].map(n=>({c:n.className,h:n.clientHeight,s:n.scrollHeight,rect:n.getBoundingClientRect().height}))})))}`);
          assert(await panel.locator('.storage-maintenance-copy').evaluateAll(nodes=>nodes.every(n=>{
            n.scrollTop=n.scrollHeight;
            return n.scrollHeight>n.clientHeight && n.querySelector('pre').getBoundingClientRect().bottom<=n.getBoundingClientRect().bottom+1;
          })),'Every long execution log can be scrolled to its end');
          if(process.env.BBUI_SCREENSHOT_DIR)await card.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/maintenance-expanded-${width}-${lang}.png`});
        }
      }
    }
    await page.evaluate(()=>{baseRepo.maintenance_results=maintenanceResultsBefore;storageState.maintenanceState={running:false};renderStorage(storageState.data);});
    for(const viewport of [{width:1600,height:500},{width:390,height:900}]) {
      await page.setViewportSize(viewport);
      await page.evaluate(()=>{storageState.selectedTab='maintenance';renderStorage(storageState.data);});
      const panel=card.locator('[data-repository-panel=maintenance]');
      assert(await panel.evaluate(p=>{
        p.scrollTop=p.scrollHeight;
        const button=p.querySelector('[data-repository-action=compact]');
        return button.getBoundingClientRect().bottom<=p.getBoundingClientRect().bottom+1;
      }),'Compact remains reachable in short and narrow windows');
      assert(await panel.evaluate(p=>p.scrollWidth<=p.clientWidth+1),'Maintenance has no horizontal overflow');
    }
    // Management must fit the compact overview even without expanded maintenance results (#662).
    await page.evaluate(()=>{window.savedResults=baseRepo.maintenance_results;baseRepo.maintenance_results={};});
    for(const width of [1600,1440,1280])for(const lang of ['de','en']) {
      await page.setViewportSize({width,height:900});
      await page.evaluate(lang=>{window.lang=lang;storageWorkspaceSize=null;storageState.selectedTab='overview';renderStorage(storageState.data);},lang);
      const height=(await card.boundingBox()).height;
      await card.locator('[data-repository-tab=management]').click();
      const panel=card.locator('[data-repository-panel=management]');
      assert.equal((await card.boundingBox()).height,height,'Management must keep the shared card height');
      assert(await panel.evaluate(p=>p.scrollHeight<=p.clientHeight+1),`All management content fits ${width}/${lang}: ${JSON.stringify(await panel.evaluate(p=>({height:p.clientHeight,scroll:p.scrollHeight})))}`);
      assert(await panel.locator('[data-lifecycle-mode=delete]').evaluate(button=>button.getBoundingClientRect().bottom<=button.closest('[data-repository-panel]').getBoundingClientRect().bottom),'Delete action is visible without scrolling');
      assert(await panel.locator('[data-lifecycle-mode=delete]').isDisabled(),'Linked-job deletion guard remains in place');
      const id=panel.locator('.storage-lifecycle-key-recovery dd').first();
      assert.equal(await id.evaluate(el=>getComputedStyle(el).whiteSpace),'nowrap');
      assert.equal(await id.getAttribute('title'),await id.textContent(),'Full repository ID remains available');
      const buttons=await panel.locator('[data-storage-action=repository-key-import-select], [data-lifecycle-mode=remove], [data-lifecycle-mode=delete]').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
      assert(Math.max(...buttons)-Math.min(...buttons)<1,`Management buttons align ${width}/${lang}: ${buttons}`);
      assert.deepEqual(await panel.locator('.storage-lifecycle-card').evaluateAll(nodes=>nodes.map(n=>getComputedStyle(n).borderLeftWidth)),['0px','1px','1px'],'Vertical separators distinguish the three action columns');
      if(process.env.BBUI_SCREENSHOT_DIR)await card.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/management-${width}-${lang}.png`});
    }
    await page.evaluate(()=>{baseRepo.maintenance_results=savedResults;});
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      assert.ok(await page.locator('.storage-card-key-warning').evaluate(n=>getComputedStyle(n).fontWeight==='400'&&getComputedStyle(n).borderTopWidth==='0px'));
      assert.equal(await card.locator('.storage-card-identity h2').evaluate(n=>getComputedStyle(n).fontWeight),'700');
      assert.equal(await page.locator('[data-storage-target=all]').evaluate(n=>getComputedStyle(n).fontWeight),'700');
    }
    await page.setViewportSize({width:1600,height:1100});await page.evaluate(()=>{window.lang='de';document.documentElement.lang='de';document.documentElement.dataset.theme='light';renderStorage(storageState.data);});await card.locator('[data-repository-tab=maintenance]').click();
    if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/repository-cards.png`,fullPage:true});
    await card.locator('[data-storage-action=toggle-repository]').click();
    if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/repository-columns.png`,fullPage:true});
    assert.equal(await card.locator('.storage-repository-master-detail').count(),0);
    await page.locator('[data-repository-card=old] [data-storage-action=toggle-repository]').click();await page.locator('[data-repository-card=old] [data-repository-tab=maintenance]').click();
    assert.equal(await page.locator('[data-repository-card=old] [data-repository-panel=maintenance] [data-repository-action=prune]').isDisabled(),true,'Unassigned repositories cannot infer retention');
    // Exercise actual job deletion and page navigation, including a delayed obsolete preview (#664).
    await page.addScriptTag({content:fs.readFileSync('ui/js/core/app-core.js','utf8')});
    await page.evaluate(()=>{
      window.BBUI.core.updateDataDirWarning=async()=>{};
      updateSidebarSystemHealth=()=>{};
      setCoreAction('refreshJobs',()=>{window.navigationRefresh=refreshJobs();});
      setCoreAction('refreshStorage',()=>{window.navigationRefresh=refreshStorage();});
      window.linkTestFetch=window.fetch;
      window.fetch=async(url,options={})=>{
        let data;
        if(url==='/api/jobs' && options.method==='DELETE') {
          const key=JSON.parse(options.body).job_key;
          serverJobs=serverJobs.filter(job=>job.key!==key);
          return {ok:true,json:async()=>({filename:key})};
        }
        if(url==='/api/jobs')data={jobs:serverJobs};
        else if(url==='/api/storage') {
          data=JSON.parse(JSON.stringify(storageState.data));
          data.groups.local.find(repo=>repo.repository_key==='flash').used_by=serverJobs.map(job=>job.key);
        }
        else if(['/api/schedules','/api/jobs/running','/api/status'].includes(url))data={};
        else if(url==='/api/repositories/lifecycle' && JSON.parse(options.body).repository_key==='flash') {
          if(window.failCurrentLifecycle)throw Error('Current lifecycle unavailable');
          data={job_keys:serverJobs.map(job=>job.key),allowed:serverJobs.length===0,blockers:serverJobs.length?['jobs_linked']:[],repository_id:'a'.repeat(64)};
          if(window.delayLifecycle) {
            window.delayLifecycle=false;
            await new Promise(resolve=>window.releaseOldLifecycle=resolve);
            if(window.failOldLifecycle)throw Error('Obsolete lifecycle request failed');
          }
        } else return linkTestFetch(url,options);
        return {ok:true,json:async()=>data};
      };
    });
    for(const lang of ['de','en'])for(const returnTab of ['overview','archives','management','collapsed']) {
      await page.evaluate(async({lang,returnTab})=>{
        window.lang=lang;
        window.serverJobs=[{key:'job-deleted-technical-id',name:'Flash USB',icon:'flash',location:'usb'}];
        storageState.jobs=[...serverJobs];
        storageState.data.groups.local.find(repo=>repo.repository_key==='flash').used_by=[serverJobs[0].key];
        storageState.target='all';storageState.selectedRepositoryKey='flash';storageState.expanded=true;
        storageState.selectedTab=returnTab==='collapsed'?'overview':returnTab;
        await loadRepositoryLifecycle('flash',true);
        window.delayLifecycle=true;window.failOldLifecycle=lang==='en';
        window.obsoleteLifecycle=loadRepositoryLifecycle('flash',true);
        if(returnTab==='collapsed')storageState.expanded=false;
        navigate('jobs');await navigationRefresh;
        jobsState.pendingDeleteJobKey='job-deleted-technical-id';
        await confirmJobDelete();
        navigate('storage');await navigationRefresh;
      },{lang,returnTab});
      assert.equal(await page.evaluate(()=>serverJobs.length),0,'Actual job delete handler completed');
      if(returnTab==='collapsed')await card.locator('[data-storage-action=toggle-repository]').click();
      await card.locator('[data-repository-tab=management]').click();
      await page.waitForFunction(()=>storageState.lifecycleCache.flash?.allowed===true);
      const management=card.locator('[data-repository-panel=management]');
      assert.equal(await management.locator('[data-lifecycle-mode=delete]').isDisabled(),false,`Deletion available after returning via ${returnTab}/${lang}`);
      assert.equal(await management.locator('[data-lifecycle-mode=remove]').isDisabled(),false);
      assert(!/job-deleted-technical-id|Flash USB/.test(await management.innerText()),'Deleted job is not replaced by a raw ID');
      assert.equal(await card.locator('.storage-card-identity h2').innerText(),'Flash');
      await page.evaluate(async()=>{releaseOldLifecycle();await obsoleteLifecycle;});
      assert.equal(await page.evaluate(()=>storageState.lifecycleCache.flash.allowed),true,'Obsolete response/error cannot restore blockers');
      assert.equal(await management.locator('[data-lifecycle-mode=delete]').isDisabled(),false);
    }
    await page.evaluate(async()=>{
      serverJobs=[{key:'new-link',name:'New linked job'}];
      await refreshStorage();
    });
    assert(await card.locator('[data-repository-panel=management] [data-lifecycle-mode=delete]').isDisabled(),'New links also restore the deletion guard');
    await page.evaluate(async()=>{window.failCurrentLifecycle=true;await refreshStorage();});
    assert.match(await card.locator('[data-repository-panel=management]').innerText(),/Current lifecycle unavailable/);
    assert.equal(await card.locator('[data-repository-panel=management] [data-lifecycle-mode=delete]').count(),0,'Failed current refresh does not expose stale actions');
    await page.evaluate(()=>{window.failCurrentLifecycle=false;});
    await card.locator('[data-repository-panel=management] [data-storage-action=refresh-repository-lifecycle]').click();
    await page.waitForFunction(()=>storageState.lifecycleCache.flash?.allowed===false);
    assert.deepEqual(errors,[]);
    console.log('Repository cards: registry/target filters/four columns, stable panels DE/EN, lifecycle/key blockers, archive paging/browser, maintenance routing and zero/unknown amounts passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
