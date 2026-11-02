// Real-browser coverage for compact planning and cumulative inline evidence (#610).
const fs=require('node:fs');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BBUI_CHROMIUM?{executablePath:process.env.BBUI_CHROMIUM}:{})});
 try {
 const page=await browser.newPage({viewport:{width:1600,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let html=fs.readFileSync('ui/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
 html=html.replace(/<link[^>]+href="\/([^\"]+)"[^>]*>/g,(all,path)=>path.endsWith('.css')?`<style>${fs.readFileSync(path,'utf8')}</style>`:'');
 html=html.replace('src="/ui/assets/app-icon.png"',`src="data:image/png;base64,${fs.readFileSync('ui/assets/app-icon.png').toString('base64')}"`);
 await page.setContent(html);
 await page.addStyleTag({content:"*, *::before, *::after { transition: none !important; animation: none !important; }"});
 await page.evaluate(dicts=>{
  window.lang='de';window.dicts=dicts;window.BBUI={components:{i18n:{getLanguage:()=>lang,t:(key,params={})=>{
   const text=key.split('.').reduce((v,k)=>v?.[k],dicts[lang]);return typeof text==='string'?text.replace(/\{(\w+)\}/g,(_,k)=>params[k]??''):key;
  }}}};
  window.isStaleDate=()=>false;
  window.translate=()=>document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=BBUI.components.i18n.t(el.dataset.i18n));
  window.showMsg=()=>{};
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-restore-tests'));
  document.documentElement.dataset.theme='light';document.querySelectorAll('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.page==='restore-tests'));translate();
 },Object.fromEntries(['de','en'].map(l=>[l,JSON.parse(fs.readFileSync(`ui/i18n/${l}.json`))])));
 for(const path of ['ui/js/utils/dom.js','ui/js/utils/format.js','ui/js/pages/dashboard.js','ui/js/pages/jobs.js','ui/js/pages/restore-tests.js'])await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
 await page.evaluate(()=>{
  const state=BBUI.restoreTestsState;
  state.plan={jobs:['Appdata','All-VMs','Flash','Photos','Sonstiges'].map((name,i)=>({job_key:String(i),key:String(i),name,display_name:name,icon:['appdata','vms','flash','photos','folder'][i],icon_color:['orange','green','blue','purple','gray'][i],location:i<3?'local':i===3?'usb':'storagebox',enabled:true,scheduler_state:i===4?'off':'active',policy:{mode:i===4?'manual_only':'scheduled',level:3,cron:i===4?'':'0 20 1 * *',validity_days:30},last_test_date:i===4?'':'2026-10-27 10:14:22',last_test_result:i===0?'cancelled':i===3?'failed':i===4?'':'success',next_run_at:'2026-11-01 20:00:00',verification_status:i===3?'failed':'verified',verification_evidence_date:'2026-10-26 23:10:52',verification_valid_until:'2026-11-25 23:10:52'}))};
  state.jobs=state.plan.jobs;
  const success={job_key:'0',job_name:'Appdata',test_date:'2026-10-26 23:10:52',test_level:3,test_result:'success',tested_archive:'appdata-backup-2026-10-26_09-00-37',repository:'/mnt/user/backup/appdata',location:'local',report_id:'RT-DEMO',log_file:'/mnt/user/borg_backup_ui/logs/Borg-Restore-Test-2026-10-26.log',test_exit_code:0,duration_formatted:'14 Min. 32 Sek.',tested_files_count:1000,tested_folders_count:0,coverage_basis:'1000/416901',test_coverage_percentage:.2,archive_stats:{files_count:416901},archive_stats_formatted:{original:'86.8 GiB'},level3_details:{enabled:true,success_count:5,checksums:['data/file.txt:deadbeef']},steps:['repo_reachable','archive_readable','metadata_check','restore_probe','integrity_check','cleanup'].map(step_id=>({step_id,status:'passed',duration_ms:500,timestamp:step_id==='archive_readable'?'2026-10-26 23:00:00':undefined}))};
  state.data=[{...success,test_date:'2026-10-27 10:14:22',test_result:'failed',failure_code:'RT_CANCELLED',report_id:'RT-CANCEL'},success,{...success,job_key:'3',location:'usb',test_result:'failed',failure_code:'RT_SAMPLE_RESTORE_FAILED',error_analysis:{error_details:'Failure <script>alert(1)</script>\n'+ 'missing-file/'.repeat(30)},report_id:'RT-FAIL'}];
  document.getElementById('restore-tests-plan-content').addEventListener('click',onRestoreTestsPlanClick);
  document.getElementById('restore-tests-plan-content').addEventListener('click',onRestoreTestsContentClick);
  document.getElementById('restore-tests-plan-content').addEventListener('change',onRTJobReportChange);
  window.renderDemo=()=>{renderRestorePlan(state.plan);renderRestoreTestsSidebar();updateRestoreTestsWorkspace();};renderDemo();
 });
 const capture=async name=>{await page.evaluate(()=>window.scrollTo(0,0));if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({fullPage:true,path:`${process.env.BBUI_SCREENSHOT_DIR}/${name}.png`});};
 for(const language of ['de','en'])for(const theme of ['light','dark']) {
  await page.setViewportSize({width:1600,height:1100});
  await page.evaluate(({language,theme})=>{lang=language;translate();document.documentElement.dataset.theme=theme;BBUI.restoreTestsState.selectedLocation='all';BBUI.restoreTestsState.expandedJobs.clear();BBUI.restoreTestsState.selectedReports.clear();renderDemo();},{language,theme});
  assert.equal(await page.locator('#rt-subtab-reports-btn').count(),0);
  assert.equal(await page.locator('.rt-plan-card').count(),5);
  assert.equal(await page.locator('.rt-plan-group').count(),3);
  assert.deepEqual(await page.locator('[data-rt-sidebar-location]').evaluateAll(buttons=>buttons.map(b=>b.dataset.rtSidebarLocation)),['all','local','usb','storagebox']);
  assert.equal(await page.locator('[data-rt-job-key="0"] .type-icon-color-orange svg').count(),1);
  for(const count of await page.locator('#rt-sidebar-location-list .location-nav-count').all())assert.equal(await count.evaluate(el=>getComputedStyle(el).borderTopWidth),'1px');
  await capture(`restore-cards-${language}-${theme}`);
  await page.locator('[data-rt-sidebar-location=usb]').click();
  assert.equal(await page.locator('.rt-plan-card').count(),1);
  await page.locator('[data-rt-plan-action=toggle-reports]').click();
  assert.equal(await page.locator('.rt-inline-report').count(),1);
  assert.match(await page.locator('.rt-inline-report').innerText(),/<script>/);
  assert.equal(await page.locator('.rt-inline-report script').count(),0);
  await page.locator('[data-rt-sidebar-location=local]').click();
  assert.equal(await page.locator('.rt-plan-card').count(),3);
  const row=page.locator('#rt-job-card-0');
  const before=await row.boundingBox();
  const menuButton=row.locator('[data-rt-plan-action=menu]');
  await menuButton.scrollIntoViewIfNeeded();
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  await menuButton.click();
  await row.locator('.rt-plan-popover:popover-open').waitFor();
  assert.equal((await row.boundingBox()).height,before.height);
  await row.locator('[data-rt-plan-action=edit]').click();
  await page.locator('#rt-plan-dialog[open]').waitFor();
  await page.locator('#rt-plan-dialog [data-close]').first().click();
  await row.locator('[data-rt-plan-action=reports]').click();
  const panel=row.locator('.rt-job-report-panel');
  assert(await panel.isVisible());
  await page.waitForFunction(()=>{
   const bounds=document.getElementById('rt-job-card-0').getBoundingClientRect();
   return bounds.top>=15 && bounds.bottom<=innerHeight-15;
  });
  assert.equal(await row.locator('select').evaluate(el=>el===document.activeElement),true,'Opening reports reveals the card without stealing selector focus');
  if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/restore-revealed-${language}-${theme}.png`});
  const height=(await panel.boundingBox()).height;
  assert.equal(await row.locator('.rt-attempt-document').count(),1);
  assert.equal(await row.locator('select option').count(),2);
  await row.locator('[data-rt-action=evidence]').click();
  assert.equal(await row.locator('.rt-proof-document').count(),1);
  assert.equal((await panel.boundingBox()).height,height);
  assert.equal(await row.locator('.rt-level-row .rt-attempt-status.success').count(),3);
  const reportSections=row.locator('.rt-report-sections > section');
  for(let section=0;section<2;section++)assert.equal(await reportSections.nth(section).locator('dl > div').count(),5);
  await row.locator('.rt-technical-evidence > summary').click();
  const technical=row.locator('.rt-technical-evidence');
  const hashStep=technical.locator('.rt-step-row').filter({hasText:language==='de'?'Integritätsprüfung':'Integrity check'});
  await hashStep.locator('.rt-check-evidence > summary').click();
  await hashStep.locator('.rt-step-detail-section > summary').click();
  await hashStep.getByText('deadbeef',{exact:true}).waitFor();
  // Polling preserves the exact report node, nested disclosures, scroll and selector focus.
  const stable=await page.evaluate(()=>{
   const scroll=document.getElementById('rt-report-scroll-0');
   const report=scroll.firstElementChild;
   const selector=document.getElementById('rt-report-select-0');
   selector.focus({preventScroll:true});scroll.scrollTop=400;
   const top=scroll.scrollTop;
   const pageTop=window.scrollY;
   renderRestorePlan(BBUI.restoreTestsState.plan);
   return {node:document.getElementById('rt-report-scroll-0').firstElementChild===report,top:scroll.scrollTop===top,pageTop:window.scrollY===pageTop,focus:document.activeElement===selector,open:scroll.querySelector('.rt-technical-evidence').open};
  });
  assert.deepEqual(stable,{node:true,top:true,pageTop:true,focus:true,open:true});
  await capture(`restore-inline-proof-${language}-${theme}`);
  const selected=await row.locator('select').inputValue();
  const latest=await row.locator('select option').first().getAttribute('value');
  await row.locator('select').selectOption(latest);
  assert.equal((await panel.boundingBox()).height,height);
  assert.equal(await row.locator('.rt-attempt-document').count(),1);
  await row.locator('select').selectOption(selected);
  assert.equal((await panel.boundingBox()).height,height);
  // Location scoping never hides older reports belonging to the selected job.
  await page.evaluate(()=>{BBUI.restoreTestsState.data[1].location='usb';renderDemo();});
  assert.equal(await row.locator('select option').count(),2);
  await page.evaluate(()=>{BBUI.restoreTestsState.data[1].location='local';renderDemo();});
  await row.locator('[data-rt-plan-action=toggle-reports]').focus();
  await page.keyboard.press('Enter');
  assert(await panel.isHidden());
  assert.equal(await page.locator('#rt-job-toggle-0').getAttribute('aria-expanded'),'false');
  await page.keyboard.press('Enter');
  assert(await panel.isVisible());
  await page.waitForFunction(()=>{
   const bounds=document.getElementById('rt-job-card-0').getBoundingClientRect();
   return bounds.top>=15 && bounds.bottom<=innerHeight-15;
  });
  assert.equal(await row.locator('[data-rt-plan-action=toggle-reports]').evaluate(el=>el===document.activeElement),true);
  // Reports of removed jobs stay readable without run/edit actions.
  await page.evaluate(()=>{const state=BBUI.restoreTestsState;state.data.push({...state.data[1],job_key:'removed',job_name:'Former job',location:'old-target'});renderDemo();});
  await page.locator('[data-rt-sidebar-location="old-target"]').click();
  assert.equal(await page.locator('.rt-plan-card').count(),1);
  assert.equal(await page.locator('[data-rt-plan-action=run], [data-rt-plan-action=edit]').count(),0);
  await page.locator('[data-rt-plan-action=toggle-reports]').click();
  assert.equal(await page.locator('.rt-proof-document').count(),1);
  await page.evaluate(()=>{const state=BBUI.restoreTestsState;state.data=state.data.filter(r=>r.job_key!=='removed');normalizeRestoreTestsLocation();state.expandedJobs.clear();renderDemo();});
  assert.equal(await page.evaluate(()=>BBUI.restoreTestsState.selectedLocation),'all');
  for(const width of [1920,1100,768,390]) {
   await page.setViewportSize({width,height:1000});
   await page.evaluate(()=>{BBUI.restoreTestsState.expandedJobs.clear();renderDemo();});
   const layout=await page.evaluate(()=>{
    const nav=document.querySelector('.rt-location-sidebar').getBoundingClientRect(),workspace=document.querySelector('.rt-redesign-workspace').getBoundingClientRect();
    const cards=[...document.querySelectorAll('.rt-plan-card')];const a=cards[0].getBoundingClientRect(),b=cards[1].getBoundingClientRect();
    const status=getComputedStyle(cards[0].querySelector('.rt-attempt-status'));
    return {above:nav.bottom<=workspace.top,full:Math.abs(nav.width-workspace.width)<2,gap:b.top-a.bottom,weight:status.fontWeight,border:status.borderTopWidth,overflow:document.documentElement.scrollWidth>innerWidth+1};
   });
   assert(layout.above&&layout.full);assert(layout.gap>=10);assert.equal(layout.weight,'400');assert.equal(layout.border,'0px');assert(!layout.overflow,`page overflow ${width}`);
   await page.locator('#rt-job-toggle-0').click();
   const current=await page.locator('#rt-job-details-0').boundingBox();
   await page.locator('#rt-report-select-0').selectOption({index:0});
   assert.equal((await page.locator('#rt-job-details-0').boundingBox()).height,current.height);
   await page.locator('#rt-report-select-0').selectOption({index:1});
   assert.equal((await page.locator('#rt-job-details-0').boundingBox()).height,current.height);
   assert(await page.locator('#rt-report-scroll-0').evaluate(el=>el.scrollWidth<=el.clientWidth+1),`report overflow ${width}`);
   if(width===390)await capture(`restore-inline-mobile-${language}-${theme}`);
   await page.locator('#rt-job-toggle-0').click();
  }
 }
 assert.deepEqual(errors,[]);console.log('Restore cards and inline reports passed: DE/EN, both themes, desktop/mobile, stable height and polling, editing, evidence, history, removed jobs, escaping.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
