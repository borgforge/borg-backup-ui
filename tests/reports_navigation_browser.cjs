// Shared Reports navigation preserves analysis and on-demand repository details (#629).
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
 const browser = await chromium.launch({headless:true, ...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
 try {
 const page = await browser.newPage({viewport:{width:1600,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let html=fs.readFileSync('ui/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
 html=html.replace(/<link[^>]+href="\/([^\"]+)"[^>]*>/g,(_,path)=>path.endsWith('.css')?`<style>${fs.readFileSync(path,'utf8')}</style>`:'');
 html=html.replace('src="/ui/assets/app-icon.png"',`src="data:image/png;base64,${fs.readFileSync('ui/assets/app-icon.png').toString('base64')}"`);
 await page.route('http://bbui.test/',route=>route.fulfill({contentType:'text/html',body:html}));
 await page.goto('http://bbui.test/');
 await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
 await page.evaluate(dicts=>{
  window.lang='de';window.dicts=dicts;window.held=null;window.pending=[];window.calls=[];
  window.BBUI={core:{state:{currentPage:'berichte'}},components:{i18n:{getLanguage:()=>lang,t:(key,params={})=>{
   const text=key.split('.').reduce((value,part)=>value?.[part],dicts[lang]);return typeof text==='string'?text.replace(/\{(\w+)\}/g,(_,name)=>params[name]??''):key;
  }}}};
  window.translate=()=>{document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=BBUI.components.i18n.t(el.dataset.i18n));document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>el.placeholder=BBUI.components.i18n.t(el.dataset.i18nPlaceholder));};
  window.jobsFixture=[
   {key:'local-vms',name:'All-VMs',location:'local',backup_type:'vms',icon:'server',icon_color:'green',archive_prefix:'vms-backup',restore_verification_status:'verified',restore_verification_last_test_date:'2026-10-17 17:38:53',restore_verification_valid_until:'2026-11-16 16:38:53'},
   {key:'local-app',name:'Appdata',location:'local',backup_type:'appdata',icon:'box',icon_color:'orange',archive_prefix:'appdata-backup',restore_verification_status:'failed',restore_verification_failure_hint:'Recorded restore failure'},
   {key:'usb-app',name:'Appdata',location:'usb',backup_type:'appdata',archive_prefix:'appdata-usb',restore_verification_status:'not_required'},
   {key:'ssh-photo',name:'Photos with a very long archive prefix',location:'storagebox',backup_type:'photos',archive_prefix:'photos-extra-long-archive-prefix-for-responsive-layout'},
  ];
  window.reportFixture=key=>({run_count:key==='local-vms'?12:24,success_count:key==='local-vms'?11:23,avg_duration_fmt:'1h 59m',latest_repository_size_fmt:'991.2 GB',latest_original_size_fmt:'1.5 TB',latest_deduplicated_size_fmt:'194.7 GB',runs:[
   {date:'2026-09-20',repository_size:2000000000,original_size:3000000000,deduplicated_size:100000000,duration_seconds:60},
   {date:'2026-10-20',repository_size:2500000000,original_size:3000000000,deduplicated_size:200000000,duration_seconds:90},
   {date:'2026-10-28',repository_size:2900000000,original_size:3000000000,deduplicated_size:300000000,duration_seconds:120},
  ],monthly_status:[{month:'2026-09',success:3,warning:1,error:1},{month:'2026-10',success:8,warning:0,error:0}]});
  window.fetch=async url=>{
   calls.push(url);
   if(url===held)await new Promise(resolve=>pending.push(resolve));
   if(url==='/api/jobs')return {ok:true,json:async()=>({jobs:jobsFixture})};
   if(url==='/api/reports/jobs')return {ok:true,json:async()=>({jobs:jobsFixture.map(j=>({...j,display_name:j.name}))})};
   if(url.startsWith('/api/reports/data?'))return {ok:true,json:async()=>reportFixture(new URL(url,'http://localhost').searchParams.get('job'))};
   if(url.startsWith('/api/restore/repo-stats?'))return {ok:true,json:async()=>({total_size:4000000,total_csize:2000000,unique_csize:1000000,archive_count:18})};
   throw Error('Unexpected URL '+url);
  };
  document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-berichte'));
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page==='berichte'));
 },Object.fromEntries(['de','en'].map(l=>[l,JSON.parse(fs.readFileSync(`ui/i18n/${l}.json`))])));
 for(const path of ['ui/js/utils/dom.js','ui/js/utils/format.js','ui/js/pages/dashboard.js','ui/js/pages/jobs.js','ui/js/components/job-picker.js','ui/js/pages/reports.js'])await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
 await page.evaluate(()=>document.getElementById('bericht-borginfo-btn').addEventListener('click',berichtLoadBorgInfo));
 const choose=async(location,key)=>{await page.locator('#report-source-toggle').click();await page.locator(`[data-picker-location=${location}]`).click();await page.locator(`[data-picker-job=${key}]`).click();};
 const loaded=async key=>page.waitForFunction(key=>BBUI.reportState.job?.key===key&&BBUI.reportState.data&&document.getElementById('bericht-body').style.display!=='none',key);
 for(const lang of ['de','en'])for(const theme of ['light','dark']){
  await page.setViewportSize({width:1600,height:1100});
  await page.evaluate(async({lang,theme})=>{localStorage.setItem('bbui.jobPicker.reports',JSON.stringify({key:'usb-app'}));calls=[];window.lang=lang;translate();document.documentElement.dataset.theme=theme;document.getElementById('bericht-job-sel').value='';BBUI.reportState.location=null;await berichtInit();},{lang,theme});
  assert.equal(await page.locator('#bericht-job-sel').inputValue(),'');
  assert.equal(await page.evaluate(()=>BBUI.reportState.job),null);
  assert.equal(await page.locator('#report-source-toggle').innerText(),lang==='de'?'Job wählen':'Choose job');
  assert(await page.locator('#bericht-empty').isVisible());
  assert.equal(await page.evaluate(()=>calls.some(url=>url.startsWith('/api/reports/data?'))),false);
  await choose('local','local-vms');await loaded('local-vms');
  await page.locator('#report-source-toggle').click();
  assert.deepEqual(await page.locator('[data-picker-location]').evaluateAll(es=>es.map(e=>e.dataset.pickerLocation)),['local','usb','storagebox']);
  assert.equal(await page.locator('[data-picker-location=local] .location-nav-count').innerText(),'2');
  assert.equal(await page.locator('[data-picker-location=local] .location-nav-count').evaluate(e=>getComputedStyle(e).borderTopWidth),'1px');
  assert.equal(await page.locator('[data-picker-job]').count(),2);
  assert.match(await page.locator('[data-picker-job=local-vms]').innerText(),/vms-backup/);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#br-runs').innerText(),'12');
  assert.equal(await page.locator('#br-success').innerText(),'11 (92%)');
  assert.equal(await page.locator('.report-metric-ledger dd').count(),10);
  for(const el of await page.locator('.report-metric-ledger dd').all())assert.notEqual(await el.innerText(),'—');
  assert.equal(await page.locator('.report-trend-table th').count(),6);
  assert.equal(await page.locator('#bericht-trend-body tr').count(),3);
  assert.equal(await page.locator('.report-sparkline').count(),3);
  assert.equal(await page.locator('.report-status-table th').count(),7);
  assert.equal(await page.locator('#bericht-status-body tr').count(),2);
  assert.equal(await page.locator('.report-status-distribution').count(),2);
  assert.match(await page.locator('#br-restore-verification').innerText(),/2026-10-17 17:38:53.*2026-11-16 16:38:53/);
  // A long history remains complete, with a stable heading and keyboard access (#635).
  await page.evaluate(()=>_berichtStatusTable(Array.from({length:24},(_,i)=>({month:`${2025+Math.floor(i/12)}-${String(i%12+1).padStart(2,'0')}`,success:i+1,warning:0,error:0}))));
  const months=page.locator('.report-month-scroll');
  assert.equal(await months.locator('tbody tr').count(),24);
  assert(await months.evaluate(el=>el.scrollHeight>el.clientHeight));
  assert(await months.evaluate(el=>el.clientHeight<=parseFloat(getComputedStyle(document.documentElement).fontSize)*11+1));
  const headingY=await months.locator('th').first().evaluate(el=>el.getBoundingClientRect().top-el.closest('.report-month-scroll').getBoundingClientRect().top);
  await months.focus();await page.keyboard.press('End');
  await page.waitForFunction(()=>{const el=document.querySelector('.report-month-scroll');return el.scrollTop+el.clientHeight>=el.scrollHeight-0.5;});
  assert(Math.abs(await months.locator('th').first().evaluate(el=>el.getBoundingClientRect().top-el.closest('.report-month-scroll').getBoundingClientRect().top)-headingY)<2);
  // End scrolling is animated by the browser; wait until the final row is fully visible.
  await page.waitForFunction(()=>{const el=document.querySelector('.report-month-scroll tbody tr:last-child'),box=el.getBoundingClientRect(),parent=el.closest('.report-month-scroll').getBoundingClientRect();return box.bottom<=parent.bottom+1&&box.top>=parent.top;});
  await page.evaluate(()=>_berichtStatusTable(reportFixture('local-vms').monthly_status));
  assert.equal(await months.evaluate(el=>el.scrollTop),0);
  // Six months fit the large desktop page without sacrificing report sections.
  await page.setViewportSize({width:1701,height:1254});
  await page.evaluate(()=>_berichtStatusTable(Array.from({length:6},(_,i)=>({month:`2026-${String(i+5).padStart(2,'0')}`,success:5}))));
  const desktopFits=await page.evaluate(()=>{return document.scrollingElement.scrollHeight<=innerHeight+2;});
  assert(desktopFits,'Report overview should fit the reference desktop height');
  if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/reports-compact-${lang}-${theme}.png`,fullPage:true});
  await page.setViewportSize({width:390,height:720});
  assert(await page.evaluate(()=>{return document.scrollingElement.scrollHeight>innerHeight;}),'Small windows retain page scrolling');
  await months.focus();await page.keyboard.press('End');
  await page.waitForFunction(()=>{const el=document.querySelector('.report-month-scroll');return el.scrollTop+el.clientHeight>=el.scrollHeight-0.5;});
  await page.setViewportSize({width:1600,height:1100});
  await page.locator('#bericht-borginfo-btn').click();await page.waitForFunction(()=>BBUI.reportState.borgInfoLoaded);
  assert.equal(await page.locator('#bi-count').innerText(),'18');assert.equal(await page.locator('#bi-savings').innerText(),'75%');
  for(const el of await page.locator('#bericht-borginfo-cards .repo-stat-value').all())assert.notEqual(await el.innerText(),'—');
  if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/reports-${lang}-${theme}.png`,fullPage:true});
  // Search keeps all location counts, including zero matches at the current location.
  await page.locator('#report-source-toggle').click();
  await page.locator('#job-picker-search').fill('appdata-backup');assert.equal(await page.locator('[data-picker-job]').count(),1);
  await page.locator('[data-picker-job=local-app]').click();await loaded('local-app');
  assert.match(await page.locator('#br-restore-verification').innerText(),/Recorded restore failure/);
  await page.locator('#report-source-toggle').click();
  await page.locator('#job-picker-search').fill('not a job');assert.equal(await page.locator('[data-picker-job]').count(),0);
  await page.locator('[data-picker-location=usb]').focus();await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(()=>BBUI.reportState.job.key),'local-app');
  assert.equal(await page.locator('#job-picker-search').inputValue(),'');
  await page.locator('[data-picker-job=usb-app]').click();await loaded('usb-app');
  assert.match(await page.locator('#report-selection-subtitle').innerText(),/USB/);
  await page.evaluate(async()=>{document.getElementById('bericht-job-sel').value='';BBUI.reportState.location=null;await berichtInit();});
  assert.equal(await page.locator('#bericht-job-sel').inputValue(),'');assert(await page.locator('#bericht-empty').isVisible());
  await choose('local','local-app');await loaded('local-app');
  await page.locator('#report-source-toggle').click();
  assert.equal(await page.locator('[data-picker-job=local-app]').getAttribute('aria-pressed'),'true');
  await page.keyboard.press('Escape');
  await page.evaluate(()=>berichtInit());assert.equal(await page.locator('#bericht-job-sel').inputValue(),'');
  await choose('local','local-app');await loaded('local-app');
  await page.evaluate(()=>{window.lang=lang==='de'?'en':'de';translate();window.dispatchEvent(new Event('bbui:language-changed'));});
  assert.match(await page.locator('#report-selection-subtitle').innerText(),/Lokal|Local/);
  await choose('storagebox','ssh-photo');await loaded('ssh-photo');
  for(const width of [1920,1280,768,390]){
   await page.setViewportSize({width,height:1100});
   const dims=await page.evaluate(()=>{const nav=document.querySelector('.report-navigation').getBoundingClientRect(),body=document.querySelector('.report-workspace').getBoundingClientRect();return {full:document.documentElement.scrollWidth<=innerWidth+2,above:nav.bottom<=body.top,aligned:Math.abs(nav.left-body.left)<2};});assert.deepEqual(dims,{full:true,above:true,aligned:true});
  }
 }
 await page.setViewportSize({width:1600,height:1100});
 // Late report results cannot replace the selection made afterwards.
 await page.evaluate(()=>{held='/api/reports/data?job=local-app';});
 await choose('local','local-app');await page.waitForFunction(()=>pending.length===1);
 await choose('usb','usb-app');await loaded('usb-app');
 await page.evaluate(async()=>{held=null;pending.splice(0).forEach(resolve=>resolve());await new Promise(r=>setTimeout(r,0));});
 assert.equal(await page.evaluate(()=>BBUI.reportState.job.key),'usb-app');
 // The same protection applies to repository details requested for a previous job.
 await page.evaluate(()=>{held='/api/restore/repo-stats?job=usb-app';});
 await page.locator('#bericht-borginfo-btn').click();await page.waitForFunction(()=>pending.length===1);
 await choose('local','local-app');await loaded('local-app');
 await page.evaluate(async()=>{held=null;pending.splice(0).forEach(resolve=>resolve());await new Promise(r=>setTimeout(r,0));});
 assert.equal(await page.evaluate(()=>BBUI.reportState.borgInfoLoaded),false);
 assert(!await page.locator('#bericht-borginfo-cards').isVisible());
 // Removal never silently selects a different job; an empty installation remains usable.
 await page.evaluate(async()=>{jobsFixture=jobsFixture.filter(j=>j.location!=='local');await berichtInit();});assert.equal(await page.locator('#bericht-job-sel').inputValue(),'');
 assert.equal(await page.locator('[data-picker-location=local]').count(),0);
 await page.evaluate(async()=>{jobsFixture=[];await berichtInit();});
 assert.equal(await page.locator('[data-picker-location]').count(),0);assert(await page.locator('#bericht-empty').isVisible());
 assert(!await page.locator('#bericht-body').isVisible());assert.deepEqual(errors,[]);
 console.log('Reports browser passed: shared navigation, DE/EN, themes, responsive layout, retained metrics/details, selection/search, keyboard access and stale-response protection.');
 } finally {await browser.close();}
})();
