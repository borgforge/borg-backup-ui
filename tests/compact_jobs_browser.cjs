'use strict';
// Real Jobs DOM, styles and translations: density, retained facts, stable details and live updates (#619).
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true,...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1100}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    let html=fs.readFileSync('ui/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
    html=html.replace(/<link[^>]+href="\/([^\"]+)"[^>]*>/g,(_,path)=>path.endsWith('.css')?`<style>${fs.readFileSync(path,'utf8')}</style>`:'');
    html=html.replace('src="/ui/assets/app-icon.png"',`src="data:image/png;base64,${fs.readFileSync('ui/assets/app-icon.png').toString('base64')}"`);
    await page.setContent(html);
    await page.evaluate(dicts=>{
      window.lang='de';window.dicts=dicts;
      window.BBUI={components:{i18n:{getLanguage:()=>lang,t:(key,params={})=>{
        const text=key.split('.').reduce((value,part)=>value?.[part],dicts[lang]);
        return typeof text==='string'?text.replace(/\{(\w+)\}/g,(_,key)=>params[key]??''):key;
      }}},core:{state:{currentPage:'jobs'},isGlobalDataDirReady:()=>true,getSchedulesData:()=>({vms:{enabled:true,cron:'0 9 * * *'}})}};
      window.isStaleDate=()=>false;window.calcNextRun=()=>new Date('2026-10-29T09:00:00');
      document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-jobs'));
      document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page==='jobs'));
      document.documentElement.dataset.theme='light';
    },Object.fromEntries(['de','en'].map(lang=>[lang,JSON.parse(fs.readFileSync(`ui/i18n/${lang}.json`,'utf8'))])));
    for(const path of ['ui/js/utils/dom.js','ui/js/utils/format.js','ui/js/pages/dashboard.js','ui/js/pages/jobs.js'])await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
    await page.evaluate(()=>{
      const steps=[{id:'stop_vms',status:'success',duration_seconds:35,details:{target_count:1,completed_count:1}},
        {id:'create',status:'success',duration_seconds:738,details:{nfiles:158,original_size:1024**4,deduplicated_size:194*1024**3}},
        {id:'start_vms',status:'success',duration_seconds:8},{id:'prune',status:'success',duration_seconds:1},
        {id:'compact',status:'success',duration_seconds:1},{id:'check',status:'skipped',reason:'not_due'}];
      const base={location:'local',enabled:true,compression:'lz4',retention:{mode:'last',last:3},archive_prefix:'vms-backup',
        restore_verification_status:'verified',restore_verification_last_test_date:'2026-10-27 11:12:50',restore_verification_valid_until:'2026-11-26 11:12:50',
        last_log_file:'vms.log',last_status:'success',last_timestamp:'2026-10-28 00:47:00',last_successful_backup:{timestamp:'2026-10-28 00:47:00',duration_seconds:783},last_job_steps:steps,
        saved_status:{status:'success',timestamp:'2026-10-28 00:47:00',original_size:1024**4,original_size_formatted:'1 TiB',deduplicated_size:194*1024**3,deduplicated_size_formatted:'194 GiB',archive_name:'vms-archive'}};
      const now=Date.now()/1000;
      window.live={running:true,phase:'borg_create',start_time:new Date((now-480)*1000).toISOString(),run_id:'active',cancel_allowed:true,
        job_steps:[steps[0],{id:'create',status:'running',started_at:now-400},...steps.slice(2).map(s=>({...s,status:'pending'}))],
        borg_progress:{phase:'borg_create',started_at:now-400,updated_at:now-2,nfiles:158,original_size:1024**3,deduplicated_size:1024}};
      jobsState.jobs=[{...base,key:'vms',name:'All-VMs',has_vm:true,description:'Backup aller virtuellen Maschinen.'},
        {...base,key:'app',name:'Appdata',has_docker:true},
        {...base,key:'running',name:'Dokumente',...jobRuntimeState(live)},
        {...base,key:'failed',name:'Offsite',last_status:'error',saved_status:{status:'error',error_message:'SSH failed <img src=x onerror=bad> '+ 'reason '.repeat(100)}},
        {key:'new',name:'New job',location:'local',enabled:false,last_status:null,retention:{mode:'all'}}];
      BBUI.jobGroups={state:{view:'jobs',hooks:{vms:{pre:'Prepare <test>',post:'Notify',post_when:'always'},app:{post:'Cleanup',post_when:'success'}}},membership:()=>'',schedules:()=>''};
      renderJobsGrid(jobsState.jobs);
      document.getElementById('jobs-grid').addEventListener('click',onJobsGridClick);
    });
    const card=page.locator('#job-card-vms');
    assert.equal(await page.locator('.borg-stepper').count(),0);
    assert.equal(await card.locator('[data-job-feature]').count(),2,'Both configured script options are visible');
    assert.equal(await page.locator('#job-card-app [data-job-feature="pre"]').count(),0);
    assert.equal(await page.locator('#job-card-app [data-job-feature="post"]').count(),1,'Post-only configuration is independent');
    assert.equal(await page.locator('#job-card-running [data-job-feature]').count(),0,'No inferred hooks from run history');
    assert.equal(await card.locator('[data-job-feature="pre"]').getAttribute('title'),'Pre-Skript: Prepare <test>');
    assert.equal(await card.locator('[data-job-feature="pre"] test').count(),0,'Script names are escaped');
    await page.evaluate(()=>{delete BBUI.jobGroups.state.hooks.vms.post;renderJobsGrid(jobsState.jobs);});
    assert.equal(await card.locator('[data-job-feature="pre"]').count(),1,'Pre-only configuration is independent');
    assert.equal(await card.locator('[data-job-feature="post"]').count(),0,'Removed assignment disappears on refresh');
    await page.evaluate(()=>{BBUI.jobGroups.state.hooks.vms.post='Notify';renderJobsGrid(jobsState.jobs);});

    assert.equal(await page.locator('#jobs-location-list .location-nav-copy strong').evaluateAll(nodes=>nodes.every(node=>node.scrollWidth<=node.clientWidth)),true);
    assert.equal(await card.locator('.job-workflow-details').count(),0,'Closed rows omit detailed steps');
    assert.ok((await card.boundingBox()).height<165,'Completed job must be compact');
    assert.ok((await card.locator('.jobs-redesign-policy').textContent()).includes('Nächster Lauf'));
    assert.equal(await card.locator('.jobs-redesign-policy .job-policy').count(),0);
    assert.ok((await page.locator('#job-card-running .job-active-step').textContent()).includes('Aktuell: Backup erstellen'));
    assert.ok((await page.locator('#job-card-running .job-active-step').textContent()).includes('Schrittzeit:'));
    assert.equal(await page.locator('#job-card-running .borg-progress-metric').count(),3);
    assert.equal(await page.locator('#job-card-running progress').getAttribute('value'),null,'Create must never invent a percentage');
    const failed=page.locator('#job-card-failed');
    assert.equal(await failed.locator('.job-saved-message').count(),0,'Collapsed failures only show status');
    await failed.locator('[data-jobs-action="toggle-workflow"]').click();
    assert.equal(await failed.locator('.job-saved-message').count(),1,'Full outcome appears exactly once');
    assert.equal(await failed.locator('.job-saved-message img').count(),0,'Outcome is escaped');
    assert.ok((await failed.locator('.job-saved-message').innerText()).includes('reason '.repeat(99)),'Full outcome is not truncated');
    await failed.locator('[data-jobs-action="toggle-workflow"]').click();
    const cards=await page.locator('.jobs-redesign-row').evaluateAll(nodes=>nodes.map(node=>({
      top:node.getBoundingClientRect().top,bottom:node.getBoundingClientRect().bottom,
      radius:parseFloat(getComputedStyle(node).borderRadius),border:parseFloat(getComputedStyle(node).borderTopWidth)
    })));
    assert.ok(cards.every((row,i)=>row.radius>0&&row.border>0&&(!i||row.top-cards[i-1].bottom>=8)),'Separate bordered cards have visible spacing');
    const location=page.locator('#jobs-location-list [data-jobs-location="local"]');
    assert.equal(await location.evaluate(node=>getComputedStyle(node).borderRadius),'0px','Location buttons are flat');
    assert.equal(await page.locator('#jobs-location-list select').count(),0);
    assert.ok(await page.locator('#jobs-location-list .location-nav-count').evaluateAll(nodes=>nodes.length>1&&nodes.every(node=>getComputedStyle(node).borderTopWidth==='1px'&&getComputedStyle(node).fontWeight==='400')),'All location counts have the same subtle outline');
    await location.click();
    assert.equal(await page.locator('#jobs-location-list [data-jobs-location="local"]').getAttribute('aria-current'),'page');
    await page.locator('#jobs-location-list [data-jobs-location="all"]').click();
    assert.equal(await page.locator('#job-card-new [data-jobs-action="start-job"]').isDisabled(),true);
    await page.evaluate(()=>document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page==='jobs')));
    if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/jobs-compact-overview.png`,fullPage:true});
    // Stable actions preserve positions and DOM identity across protected/pending/completed states.
    const runningCard=page.locator('#job-card-running');
    const actionGeometry=()=>runningCard.evaluate(node=>{
      const origin=node.querySelector('.jobs-redesign-actions').getBoundingClientRect();
      return [...node.querySelectorAll('.job-action-stack button')].map(b=>{
        const box=b.getBoundingClientRect();return {x:box.x-origin.x,y:box.y-origin.y,width:box.width,height:box.height,text:b.textContent.replace('●','').trim()};
      });
    });
    const positions=await actionGeometry();
    await page.evaluate(()=>{window.actionNodes=[...document.querySelectorAll('#job-card-running .job-action-stack button')];});
    for(const state of [
      {running:true,cancel_allowed:false,cancel_requested:false,cancel_message_key:'jobs.cancelUnavailableRecovery'},
      {running:true,cancel_allowed:true,cancel_requested:true,cancel_message_key:'jobs.cancelPending'},
      {running:false,cancel_allowed:false,cancel_requested:false,cancel_message_key:''},
    ]){
      await page.evaluate(state=>{Object.assign(jobsState.jobs.find(j=>j.key==='running'),state);renderJobsGrid(jobsState.jobs);},state);
      const current=await actionGeometry();
      assert.ok(current.every((button,i)=>button.text===positions[i].text&&['x','y','width','height'].every(key=>Math.abs(button[key]-positions[i][key])<1)),'Action slots must not move or change their labels');
      assert.equal(await runningCard.locator('[data-jobs-action="cancel-job"]').isDisabled(),true);
      assert.equal(await runningCard.locator('.jobs-running-message').count(),0);
      assert.equal(await page.evaluate(()=>actionNodes.every((node,i)=>node===document.querySelectorAll('#job-card-running .job-action-stack button')[i])),true);
      if(state.cancel_requested)assert.match(await runningCard.locator('.jobs-redesign-operation > .badge').innerText(),/Abbruch angefordert/);
    }
    await page.evaluate(()=>{Object.assign(jobsState.jobs.find(j=>j.key==='running'),jobRuntimeState(live));renderJobsGrid(jobsState.jobs);});
    assert.equal(await runningCard.locator('[data-jobs-action="cancel-job"]').isDisabled(),false);
    await page.evaluate(()=>{window.openedSavedLog=null;BBUI.components.logViewer={open:file=>window.openedSavedLog=file};});
    await card.locator('[data-jobs-action="open-job-log"]').click();
    assert.equal(await page.evaluate(()=>openedSavedLog),'vms.log');
    await page.evaluate(()=>{window.originalOpenLogPanel=openLogPanel;window.openedLiveJob=null;openLogPanel=key=>{window.openedLiveJob=key;};});
    await runningCard.locator('[data-jobs-action="open-job-log"]').click();
    assert.equal(await page.evaluate(()=>openedLiveJob),'running');
    await page.evaluate(()=>{openLogPanel=originalOpenLogPanel;});
    await page.evaluate(()=>{const j=jobsState.jobs.find(j=>j.key==='running');j.run_log_available=false;renderJobsGrid(jobsState.jobs);});
    assert.equal(await runningCard.locator('[data-jobs-action="open-job-log"]').isDisabled(),true);
    await page.evaluate(()=>{jobsState.jobs.find(j=>j.key==='running').run_log_available=true;renderJobsGrid(jobsState.jobs);});
    assert.equal(await card.locator('.job-action-stack button .job-action-icon').count(),3,'Every stable action has an icon');
    assert.equal(await card.locator('.jobs-redesign-operation > .badge .job-status-icon svg').count(),1);
    assert.equal(await card.locator('.job-restore-proof > .restore-v-badge .job-status-icon svg').count(),1);
    assert.equal(await card.locator('.jobs-redesign-operation .badge-dot').count(),0);
    const headingBox=await page.locator('.jobs-actions-heading').first().boundingBox();
    const actionBox=await card.locator('.job-action-stack').boundingBox();
    assert.ok(Math.abs(headingBox.x+headingBox.width/2-actionBox.x-actionBox.width/2)<2,'Actions heading centers over buttons');
    const dateLefts=await card.locator('.jobs-restore-dates dd').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().left));
    assert.ok(dateLefts.length===2&&dateLefts.every(x=>x===dateLefts[0]),'Restore dates share the value column');
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      const styles=await card.locator('.jobs-redesign-operation > .badge, .job-restore-proof > .restore-v-badge').evaluateAll(nodes=>nodes.map(n=>({border:getComputedStyle(n).borderTopWidth,weight:getComputedStyle(n).fontWeight,background:getComputedStyle(n).backgroundColor})));
      assert.ok(styles.every(s=>s.border==='0px'&&s.weight==='400'&&s.background!=='rgba(0, 0, 0, 0)'),`Soft borderless normal-weight statuses in ${theme}`);
    }
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    const open=card.locator('[data-jobs-action="toggle-workflow"]');
    await page.setViewportSize({width:1600,height:800});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.evaluate(async()=>{
      const trigger=document.querySelector('#job-card-vms [data-jobs-action="toggle-workflow"]');
      trigger.click();trigger.click();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    });
    assert.equal(await page.evaluate(()=>scrollY),0,'Closing before layout cancels the queued reveal');
    await open.focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(()=>{
      const bounds=document.getElementById('job-card-vms').getBoundingClientRect();
      return bounds.top>=15 && bounds.bottom<=innerHeight-15;
    });
    assert.equal(await open.evaluate(el=>el===document.activeElement),true,'Revealing the card preserves keyboard focus');
    const revealedScroll=await page.evaluate(()=>scrollY);
    assert.ok(revealedScroll>0,'Opening an off-screen detail area reveals the card');
    await page.evaluate(async()=>{renderJobsGrid(jobsState.jobs);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
    assert.equal(await page.evaluate(()=>scrollY),revealedScroll,'Background rendering does not reposition an open card');
    if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/jobs-revealed.png`});
    await page.setViewportSize({width:1600,height:1100});
    assert.equal(await card.locator('tr[data-step="create"]').count(),1,'Each step renders exactly once');
    assert.ok((await card.locator('tr[data-step="create"]').textContent()).includes('194'));
    for(const width of [1600,1024,390])for(const lang of ['de','en']){
      await page.setViewportSize({width,height:1100});
      await page.evaluate(lang=>{window.lang=lang;renderJobsGrid(jobsState.jobs);},lang);
      // Measure after responsive layout has settled, before changing the tab.
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const before=await card.boundingBox();
      await card.locator('[data-job-view="data"]').click();
      const after=await card.boundingBox();
      assert.ok(Math.abs(before.height-after.height)<1,`Stable panel height ${lang}/${width}: ${before.height} -> ${after.height}`);
      assert.equal(await card.locator('[role="tabpanel"][aria-hidden="true"]').getAttribute('inert'),'');
      assert.ok((await card.locator('[role="tabpanel"][id$="-data"]').textContent()).includes('194 GiB'));
      assert.ok((await card.locator('.job-settings-facts').textContent()).includes('3'));
      await page.keyboard.press('ArrowLeft');
      assert.equal(await card.locator('[data-job-view="workflow"]').getAttribute('aria-selected'),'true');
      assert.equal(await page.evaluate(()=>document.activeElement.dataset.jobView),'workflow');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`No page overflow ${width}`);
      assert.match(await card.locator('[data-job-feature="pre"]').textContent(),lang==='de'?/Pre-Skript/:/Pre script/);
    }
    await page.setViewportSize({width:1600,height:1100});
    await page.evaluate(()=>{window.lang='de';renderJobsGrid(jobsState.jobs);});
    await page.locator('#job-card-running [data-jobs-action="toggle-workflow"]').click();
    await page.evaluate(()=>{window.spinner=document.querySelector('#job-card-running tr.is-running svg');window.meter=document.querySelector('#job-card-running progress');});
    await page.evaluate(()=>{live.borg_progress.nfiles=999;live.borg_progress.started_at=Date.now()/1000;updateBorgProgressDisplays({running:live});});
    assert.equal(await page.evaluate(()=>spinner===document.querySelector('#job-card-running tr.is-running svg')&&meter===document.querySelector('#job-card-running progress')),true);
    assert.ok((await page.locator('#job-card-running .job-live-metrics').textContent()).includes('999'));
    await page.evaluate(()=>{
      Object.assign(live.borg_progress,{source_size_status:'ready',estimated_total_bytes:2*1024**3,
        estimated_percent:50,processing_speed_bytes_per_sec:8*1024**2,estimated_remaining_seconds:128,rate_updated_at:Date.now()/1000});
      updateBorgProgressDisplays({running:live});
    });
    assert.equal(await page.locator('#job-card-running progress').getAttribute('value'),'50');
    assert.match(await page.locator('#job-card-running .job-live-metrics').textContent(),/8[,.]0 MiB\/s/);
    for(const width of [1600,768,390])for(const language of ['de','en']) {
      await page.setViewportSize({width,height:1100});
      await page.evaluate(language=>{window.lang=language;updateBorgProgressDisplays({running:live});},language);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Metrics fit ${width}/${language}`);
      const bar=await page.locator('#job-card-running progress').boundingBox();
      const metrics=await page.locator('#job-card-running .borg-progress-metrics').boundingBox();
      assert.ok(metrics.y>=bar.y+bar.height,`Metrics appear below bar ${width}/${language}`);
      assert.doesNotMatch(await page.locator('#job-card-running .job-live-metrics').textContent(),/Letzte Borg-Rückmeldung|Last Borg update/);

      if(process.env.BBUI_SCREENSHOT_DIR)await page.locator('#job-card-running').screenshot({animations:'disabled',path:`${process.env.BBUI_SCREENSHOT_DIR}/live-metrics-${language}-${width}.png`});
    }
    await page.setViewportSize({width:1600,height:1100});
    await page.evaluate(()=>{jobsState.jobs=jobsState.jobs.map(j=>j.key==='running'?{...j,...jobRuntimeState(live)}:j);renderJobsGrid(jobsState.jobs);});
    assert.equal(await page.locator('#job-card-running [data-jobs-action="toggle-workflow"]').getAttribute('aria-expanded'),'true');
    await page.evaluate(()=>{
      const job=jobsState.jobs.find(j=>j.key==='running');job.running=false;job.last_job_steps=live.job_steps.map(s=>({...s,status:'success',duration_seconds:30}));renderJobsGrid(jobsState.jobs);
    });
    assert.equal(await page.locator('#job-card-running progress').count(),0);
    assert.equal(await page.locator('#job-card-running tr.is-success').count(),6);
    await page.evaluate(()=>{
      jobWorkflowOpen.clear();jobWorkflowOpen.add('vms');jobDataView.delete('vms');renderJobsGrid(jobsState.jobs);
    });
    if(process.env.BBUI_SCREENSHOT_DIR){await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/jobs-compact-details.png`,fullPage:true});}
    assert.deepEqual(errors,[]);
    console.log('Compact Jobs: real render, DE/EN, three widths, stable panel height, keyboard tabs, escaped outcomes, live metrics and polling identity passed.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
