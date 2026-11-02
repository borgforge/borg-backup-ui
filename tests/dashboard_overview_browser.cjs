// Browser regression for compact summaries, inline disclosures and responsive telemetry (#607).
const fs = require('fs');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.BBUI_CHROMIUM ? {executablePath:process.env.BBUI_CHROMIUM} : {})});
  try {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  let html = fs.readFileSync('ui/index.html', 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  html = html.replace(/<link[^>]+href="\/([^\"]+)"[^>]*>/g, (all, path) => path.endsWith('.css') ? `<style>${fs.readFileSync(path, 'utf8')}</style>` : '');
  html = html.replace('src="/ui/assets/app-icon.png"', `src="data:image/png;base64,${fs.readFileSync('ui/assets/app-icon.png').toString('base64')}"`);
  await page.setContent(html);
  const dictionaries = Object.fromEntries(['de','en'].map(l => [l, JSON.parse(fs.readFileSync(`ui/i18n/${l}.json`))]));
  await page.evaluate(dicts => {
    window.lang = 'de'; window.dicts = dicts;
    const backups = ['All-VMs', 'Appdata', 'Flash', 'Photos', 'Portableapps-Dockcase', 'Test-PR-595'].map((name, i) => ({
      key: String(i), name, display_name: name, location: 'local', status: 'success', duration: '14 Min. 17 Sek.',
      restore_verification_status: 'verified', total_size: '162.3 GB', last_backup: '2026-10-26T09:00:00Z',
      archive_name: `${name.toLowerCase()}-backup-2026-10-26_09-00-37`}));
    backups[4].status='error'; backups[4].error_message='Required source is missing <script>not executable</script>';
    for(let i=6;i<14;i++) backups.push({key:String(i),name:`Demo ${i}`,location:i<10?'usb':i<12?'smb':'storagebox',status:'success',restore_verification_status:'not_required'});
    window.BBUI = {components: {i18n: {getLanguage: () => lang, t: (key, params = {}) => {
      const text = key.split('.').reduce((v,k) => v?.[k], dicts[lang]);
      return typeof text === 'string' ? text.replace(/\{(\w+)\}/g, (_,k) => params[k] ?? '') : key;
    }}}, core: {state: {currentPage: 'dashboard', data: {backups}}, getSchedulesData: () => ({})}};
    window.openWizard = () => {throw Error('Navigation must not open the job wizard');};
    window.resolveJobIcon = () => 'archive'; window.resolveJobIconColor = () => '';
    window.isStaleDate = () => false; window.calcNextRun = () => new Date();
    window.demoIdle = true;
    const group = {id:'demo', job_key:'1', cpu_percent:12, memory_bytes:1.3*1024**3, memory_limit_bytes:2*1024**3};
    window.fetch = async () => ({ok:true, json:async () => ({available:true, stale:false,
      host:{cpu_percent:1.3, memory_available_bytes:36.5*1024**3, memory_total_bytes:62.7*1024**3},
      runs_available:true, runs:demoIdle ? [] : [{job_key:'1', operation:'restore_test'}],
      protected_tests:demoIdle ? [] : [group], configured_reserve_bytes:1024**3,
      history:Array.from({length:121}, (_,i) => ({timestamp:Date.now()/1000-600+i*5,
        host:{cpu_percent:1.3+.4*Math.sin(i*.5), memory_available_bytes:(36.5+Math.sin(i*.2)*.2)*1024**3},
        protected_tests:[{...group,cpu_percent:12+3*Math.sin(i*.3),memory_bytes:(1.1+i/600)*1024**3}]}))})});
    document.documentElement.dataset.theme = 'light';
    window.translate = () => document.querySelectorAll('[data-i18n]').forEach(el => {el.textContent=BBUI.components.i18n.t(el.dataset.i18n);});
    translate();
  }, dictionaries);
  for (const path of ['ui/js/utils/dom.js','ui/js/utils/format.js','ui/js/pages/dashboard.js','ui/js/components/resource-monitor.js','ui/js/pages/jobs.js','ui/js/pages/job-groups.js']) await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
  await page.evaluate(() => {
    const data = BBUI.core.state.data;
    const steps = ['stop_vms','create','start_vms','prune','compact','check'].map(id => ({id,status:'success',duration_seconds:60}));
    data.backups[0] = {...data.backups[0], job_steps:steps, timestamp:'2026-10-24 00:47:00', original_size:1500, original_size_formatted:'1.5 TB', repository_size:991, repository_size_formatted:'991 GB', deduplicated_size_formatted:'194 GB', compressed_size_formatted:'562 GB', error_message:''};
    data.backups[4].error_message += '\nMissing path: /mnt/disks/' + 'long-path-'.repeat(20);
    window.demoJobs = data.backups.map(b => ({...b, enabled:true, archive_prefix:b.name, compression:'lz4', retention_daily:7,retention_weekly:4,retention_monthly:6,retention_yearly:3}));
    window.telemetryFetch = window.fetch;
    window.overviewQueries=[];
    window.fetch = async url => {
      if (url.startsWith('/api/reports/overview')) {
        overviewQueries.push(url);
        const params=new URL('http://local'+url).searchParams;
        const days=Number(params.get('days'));
        return {ok:true,json:async()=>({days,location:params.get('location'),from:'2026-10-01',to:'2026-10-27',run_count:days*3,success_rate:200/3,counts:{success:days*2,warning:0,error:days,skipped:0,cancelled:0,unknown:0},repository_count:2,unassigned_jobs:0,repository_last_sample:'2026-10-27T09:00:00Z',daily:Array.from({length:days},(_,i)=>({date:'2026-10-'+String(i+1).padStart(2,'0'),success:2,warning:0,error:1,skipped:0,cancelled:0,unknown:0,repository_bytes:(300+i)*1024**3,measured_repositories:2}))})};
      }
      if(url==='/api/job-groups')return {ok:true,json:async()=>({groups:[],hooks:{}})};
      if(url==='/api/jobs')return {ok:true,json:async()=>({jobs:demoJobs})};
      if(url==='/api/status')return {ok:true,json:async()=>data};
      if(url==='/api/schedules'||url==='/api/jobs/running')return {ok:true,json:async()=>({})};
      return telemetryFetch(url);
    };
    Object.assign(BBUI.core,{isGlobalDataDirReady:()=>true,updateDataDirWarning:async()=>{},setSchedulesData:()=>{},navigate:page=>{
      document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+page));
      BBUI.core.state.currentPage=page;
      if(page==='jobs') {BBUI.resourceMonitor.stop(); refreshJobs();}
    }});
    document.getElementById('jobs-grid').addEventListener('click',onJobsGridClick);
    BBUI.core.state.lastRefresh = new Date('2026-10-27T19:00:00Z');
    updateRefreshLabel();
    renderDashboard(data,null); refreshDashboardOverview(); BBUI.resourceMonitor.start();
  });
  const capture=async name=>{if(process.env.BBUI_SCREENSHOT_DIR)await page.screenshot({animations:'disabled',fullPage:true,path:`${process.env.BBUI_SCREENSHOT_DIR}/${name}.png`});};
  await page.waitForSelector('.management-bars');
  // Real workspace switching used to reset the requested location on a cold list (#658).
  for (const lang of ['de','en']) {
    for (const location of ['usb','local','smb','storagebox']) {
      await page.evaluate(({lang,location})=>{
        window.lang=lang;translate();
        jobsState.jobs=[];jobsState.loaded=false; // first visit / stale cache
        BBUI.core.state.currentPage='dashboard';
        document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-dashboard'));
        dashboardSelectedLocation='all';renderDashboard(BBUI.core.state.data,null);
      },{lang,location});
      assert.equal(await page.locator('[aria-labelledby=dashboard-locations-title] .management-heading [data-dashboard-jobs]').count(),0);
      assert.equal(await page.locator('#dashboard-locations [data-dashboard-jobs]').count(),4);
      await page.locator(`#dashboard-locations [data-location="${location}"]`).click();
      await page.waitForFunction(location=>jobsState.loaded && jobsState.selectedLocation===location, location, {timeout:5000}).catch(async error=>{console.error(errors,await page.locator('#jobs-message').innerText(),await page.evaluate(()=>({location:jobsState.selectedLocation,loaded:jobsState.loaded,view:BBUI.jobGroups.state.view})));throw error;});
      assert(await page.locator(`[data-jobs-location="${location}"]`).evaluate(el=>el.getAttribute('aria-current')==='page'));
      assert.equal(await page.locator('#jobs-grid .jobs-redesign-row').count(),await page.evaluate(location=>demoJobs.filter(j=>j.location===location).length,location));
      assert.deepEqual(await page.evaluate(()=>[...new Set([...document.querySelectorAll('#jobs-grid .jobs-redesign-row')].map(el=>jobsState.jobs.find(j=>`job-card-${j.key}`===el.id)?.location))]),[location]);
      await page.evaluate(()=>refreshJobs());
      assert.equal(await page.evaluate(()=>jobsState.selectedLocation),location);
    }
    await page.evaluate(async()=>{
      await BBUI.jobGroups.view('groups');
      BBUI.core.state.currentPage='dashboard';
      document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-dashboard'));
      renderDashboard(BBUI.core.state.data,null);
    });
    await page.locator('#dashboard-locations [data-location=usb]').click();
    await page.waitForFunction(()=>BBUI.jobGroups.state.view==='jobs' && jobsState.selectedLocation==='usb');
    assert(await page.locator('#page-jobs .jobs-location-layout').isVisible());
  }
  // Overdue status comes from /api/status, not the job configuration (#679).
  for (const lang of ['de','en']) {
    for (const status of ['success','skipped','error']) {
      await page.evaluate(async ({lang,status}) => {
        window.lang=lang;translate();jobsState.selectedLocation='local';
        Object.assign(BBUI.core.state.data.backups[3], {
          status,backup_overdue:true,backup_overdue_after:'2026-11-01T16:00:00',
          timestamp:'2026-10-30 09:20:00',last_successful_backup:{timestamp:'2026-10-30 09:20:00'},
        });
        await refreshJobs();
      }, {lang,status});
      const job = page.locator('#job-card-3');
      assert.equal(await job.locator('.job-workflow-details').count(),0);
      assert(await job.locator('.jobs-redesign-operation .job-backup-overdue').isVisible());
      assert.equal(await job.locator('.job-backup-overdue').innerText(),lang==='de'?'Überfällig':'Overdue');
      assert.equal(await job.locator(`.jobs-redesign-operation > .badge.${status}`).count(),1,'Last outcome remains independent of overdue status');
      if (status==='success' && process.env.BBUI_SCREENSHOT_DIR) await job.screenshot({path:`${process.env.BBUI_SCREENSHOT_DIR}/overdue-job-${lang}.png`});
    }
    await page.evaluate(async () => {
      Object.assign(BBUI.core.state.data.backups[3],{status:'success',backup_overdue:false});
      await refreshJobs();
    });
    assert.equal(await page.locator('#job-card-3 .job-backup-overdue').count(),0,'A refreshed status clears the overdue badge');
  }
  await page.evaluate(()=>{
    window.lang='de';translate();
    BBUI.core.state.currentPage='dashboard';
    document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-dashboard'));
    renderDashboard(BBUI.core.state.data,null);
  });
  assert.equal(await page.locator('.dashboard-summary-section').count(),3);
  assert.equal(await page.locator('.dashboard-coverage-track .success').count(),6);
  assert.equal(await page.locator('#backup-grid').count(),0);
  assert.match(await page.locator('#dashboard-attention').textContent(),/<script>not executable<\/script>/);
  assert.equal(await page.locator('#dashboard-attention script').count(),0);
  const cards=await page.locator('.dashboard-summary-pair > section').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
  assert(cards.every(top=>top===cards[0]));
  assert.equal(cards.length,4);
  assert.match(await page.locator('#last-refresh').innerText(), /Aktualisiert:/);
  await page.locator('.dashboard-tests-link').focus();
  await page.evaluate(()=>renderDashboard(BBUI.core.state.data,null));
  assert(await page.locator('.dashboard-tests-link').evaluate(el=>el===document.activeElement));
  // A populated desktop overview fits without clipping; disclosures remain keyboard accessible.
  for (const lang of ['de','en']) for (const theme of ['light','dark']) {
    await page.evaluate(({lang,theme})=>{window.lang=lang;document.documentElement.dataset.theme=theme;translate();updateRefreshLabel();renderDashboard(BBUI.core.state.data,null);},{lang,theme});
    // Status fills stay consistent across themes without recoloring host telemetry (#623).
    const palette = await page.evaluate(() => {
      const style = selector => getComputedStyle(document.querySelector(selector));
      const triangle = document.createElement('span');
      triangle.innerHTML = iconWarn();
      return {
        legend: ['success','warning','error','skipped','cancelled','unknown'].map(status => style(`.management-legend .${status} i`).backgroundColor),
        coverage: style('.dashboard-coverage-track .success').backgroundColor,
        attention: style('.dashboard-attention-disclosure').backgroundColor,
        surface: style('.dashboard-summary-section').backgroundColor,
        stripe: style('.dashboard-attention-disclosure').borderLeftWidth,
        icon: document.querySelector('#dashboard-attention-toggle .dashboard-attention-icon').innerHTML,
        triangle: triangle.innerHTML,
        resourceAccent: style('.resource-ram-capacity').accentColor,
        unchangedAccent: style('.management-chart-line').stroke,
      };
    });
    assert.deepEqual(palette.legend, ['rgb(34, 160, 107)','rgb(233, 162, 59)','rgb(228, 93, 101)','rgb(148, 163, 184)','rgb(124, 140, 232)','rgb(226, 232, 240)']);
    assert.equal(palette.coverage, palette.legend[0]);
    assert.equal(palette.attention, palette.surface);
    if (theme === 'light') assert.equal(palette.attention, 'rgb(255, 255, 255)');
    assert.equal(palette.stripe, '0px');
    assert.equal(palette.icon, palette.triangle);
    assert.equal(palette.resourceAccent, palette.unchangedAccent);
    for (const viewport of [{width:1920,height:1080},{width:1600,height:1000}]) {
      await page.setViewportSize(viewport);
      const bounds=await page.locator('#dashboard-locations').boundingBox();
      assert(bounds.y+bounds.height<=viewport.height, `Location table exceeds ${viewport.width}x${viewport.height}: ${bounds.y+bounds.height}`);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+1));
    }
    await capture(`compact-dashboard-${lang}-${theme}`);
  }
  // Cancelled outcomes use their own solid segment, distinct from warnings.
  const outcomeRing = await page.evaluate(() => {
    renderSummaryBar(['success','warning','error','skipped','cancelled','unknown'].map(status => ({status})));
    const ring = getComputedStyle(document.querySelector('.dashboard-summary-ring')).backgroundImage;
    renderDashboard(BBUI.core.state.data,null);
    return ring;
  });
  for (const color of ['34, 160, 107','233, 162, 59','228, 93, 101','148, 163, 184','124, 140, 232','226, 232, 240']) assert(outcomeRing.includes(`rgb(${color})`));
  await page.setViewportSize({width:1920,height:1080});
  await page.evaluate(()=>{window.lang='de';document.documentElement.dataset.theme='light';translate();renderDashboard(BBUI.core.state.data,null);});
  await page.locator('#dashboard-attention-toggle').focus();
  await page.keyboard.press('Enter');
  assert(await page.locator('#dashboard-attention li').first().isVisible());
  await page.locator('#dashboard-rate-info summary').click();
  assert(await page.locator('#dashboard-rate-info p').isVisible());
  await page.evaluate(()=>{renderDashboard(BBUI.core.state.data,null);});
  assert(await page.locator('#dashboard-rate-info p').isVisible());
  assert(await page.locator('#dashboard-attention li').first().isVisible());
  await page.locator('#dashboard-rate-info summary').click();
  await page.locator('#dashboard-attention-toggle').click();
  await capture('management-dashboard-de');
  await page.evaluate(()=>{BBUI.core.state.data.backups[4].status='success';renderDashboard(BBUI.core.state.data,null);});
  assert(await page.locator('.dashboard-attention-clear').isVisible());
  assert.equal(await page.locator('#dashboard-attention details').count(),0);
  await capture('compact-dashboard-healthy-de');
  for (const width of [1280,768]) {
    await page.setViewportSize({width,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    const positions=await page.locator('.dashboard-summary-pair > section').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
    assert.equal(positions[0],positions[1]);
    assert.equal(positions[2],positions[3]);
    assert(positions[2]>positions[0]);
  }
  await page.setViewportSize({width:1920,height:1080});
  await page.evaluate(()=>{BBUI.core.state.data.backups[4].status='error';renderDashboard(BBUI.core.state.data,null);});
  // Background refresh must preserve chart geometry, SVG/table identity and focus.
  assert.deepEqual(await page.locator('#dashboard-location-filter option').evaluateAll(nodes=>nodes.map(n=>n.value)), ['all','local','usb','smb','storagebox']);
  assert.equal(await page.locator('#dashboard-locations tbody tr').count(), 4);
  assert.equal(await page.locator('#dashboard-location-filter option[value="all"]').innerText(), 'Alle Standorte');
  const stability = await page.evaluate(async () => {
    const trends = document.getElementById('dashboard-trends');
    const locations = document.getElementById('dashboard-locations');
    const bars = trends.querySelector('.management-bars');
    const svg = trends.querySelector('svg');
    const line = svg.querySelector('.management-chart-line');
    const row = document.getElementById('dashboard-location-local');
    const action = row.querySelector('button');
    action.focus({preventScroll:true});
    const height = trends.getBoundingClientRect().height;
    const savedFetch = window.fetch;
    let mutations=0;
    const observer = new MutationObserver(records=>{mutations+=records.length;});
    for (const node of [trends,locations]) observer.observe(node,{childList:true,subtree:true,attributes:true,characterData:true});
    const unchanged = [];
    for (let i=0; i<3; i++) {
      window.fetch = () => new Promise(resolve=>{window.releaseOverview=resolve;});
      renderDashboard(BBUI.core.state.data,null);
      const refresh = refreshDashboardOverview();
      unchanged.push(bars === trends.querySelector('.management-bars') && height === trends.getBoundingClientRect().height);
      releaseOverview({ok:true,json:async()=>structuredClone(dashboardOverview)});
      await refresh;
      unchanged.push(svg === trends.querySelector('svg') && row === document.getElementById('dashboard-location-local') && action === document.activeElement);
    }
    const writes = mutations + observer.takeRecords().length;
    observer.disconnect();
    // New values update existing text/paths instead of rebuilding the view.
    const overview = structuredClone(dashboardOverview);
    const originalStatus = BBUI.core.state.data.backups[0].status;
    BBUI.core.state.data.backups[0].status='error';
    renderDashboard(BBUI.core.state.data,null);
    dashboardOverview.success_rate=75;
    dashboardOverview.daily[0].repository_bytes=100*1024**3;
    const previousPath=line.getAttribute('d');
    renderDashboardTrends();
    const changed = svg === trends.querySelector('svg') && line === svg.querySelector('.management-chart-line') && previousPath !== line.getAttribute('d') && row.cells[2].textContent === '4/6' && trends.querySelector('strong').textContent === '75 %';
    BBUI.core.state.data.backups[0].status=originalStatus;
    dashboardOverview=overview;
    window.fetch=savedFetch;
    renderDashboard(BBUI.core.state.data,null);
    return {unchanged,writes,changed};
  });
  assert(stability.unchanged.every(Boolean));
  assert.equal(stability.writes,0);
  assert(stability.changed);
  // Removing the selected location resets the filter; unaffected rows survive removals.
  const emptyLocations = await page.evaluate(() => {
    const data=BBUI.core.state.data;
    const backups=data.backups;
    const storagebox=document.getElementById('dashboard-location-storagebox');
    data.backups=backups.filter(b=>b.location!=='usb');
    renderDashboard(data,null);
    const preserved=storagebox===document.getElementById('dashboard-location-storagebox');
    dashboardSelectedLocation='usb';
    renderDashboard(data,null);
    const reset=dashboardSelectedLocation==='all' && document.getElementById('dashboard-location-filter').value==='all' && !document.querySelector('#dashboard-location-filter option[value="usb"]');
    data.backups=[];
    renderDashboard(data,null);
    const empty=document.querySelectorAll('#dashboard-locations tbody tr').length===0 && document.querySelectorAll('#dashboard-location-filter option').length===1;
    data.backups=backups;
    renderDashboard(data,null);
    return {preserved,reset,empty};
  });
  assert.deepEqual(emptyLocations,{preserved:true,reset:true,empty:true});
  await page.locator('#dashboard-location-filter').selectOption('usb');
  await page.waitForFunction(()=>dashboardOverview?.location==='usb');
  assert.equal(await page.locator('.dashboard-summary-ring strong').innerText(),'4');
  assert.equal(await page.locator('.dashboard-summary-ring small').innerText(),'/4');
  assert.equal(await page.locator('.dashboard-coverage-track .success').count(),0);
  assert.equal(await page.locator('#dashboard-attention li').count(),0);
  await page.locator('#dashboard-period').selectOption('7');
  await page.waitForFunction(()=>dashboardOverview?.days===7);
  assert.equal(await page.locator('.management-bar').count(),7);
  await page.locator('#dashboard-location-filter').selectOption('all');
  await page.evaluate(()=>{demoIdle=false;BBUI.resourceMonitor.stop();BBUI.resourceMonitor.start();});
  await page.waitForSelector('#resource-tests .resource-test');
  const full=await page.locator('#resource-activity').boundingBox();
  const summary=await page.locator('.dashboard-summary-pair').boundingBox();
  assert(Math.abs(full.width-summary.width)<2);
  assert(await page.locator('#resource-history').isHidden());
  await page.locator('#resource-history-toggle').click();
  const plots=await page.locator('#resource-history [data-resource-plot-key="host-cpu"], #resource-history [data-resource-plot-key="host-ram"]').evaluateAll(nodes=>nodes.map(n=>({top:n.getBoundingClientRect().top,left:n.getBoundingClientRect().left})));
  assert.equal(plots.length,2);assert.equal(plots[0].top,plots[1].top);
  await page.locator('#dashboard-attention-toggle').click();
  await page.locator('#dashboard-attention [data-dashboard-jobs="4"]').click();
  await page.waitForSelector('#job-card-4 .job-details .job-saved-message', {timeout:5000}).catch(async error => { console.error(errors, await page.locator('#jobs-message').innerText()); throw error; });
  assert(await page.locator('#job-card-4 .job-details .job-saved-message').isVisible());
  assert.equal(await page.locator('#job-card-4 > .job-saved-message').count(),0);
    assert.match(await page.locator('#job-card-4 .job-details .job-saved-message').innerText(),/Missing path:/);
  assert.equal(await page.locator('#jobs-grid script').count(),0);
  assert.equal(await page.locator('#job-card-0 tr[data-step]').count(),0);
  await page.locator('#job-card-0 [data-jobs-action="toggle-workflow"]').click();
  assert(await page.locator('#job-card-0 .job-workflow-details').isVisible());
  assert.equal(await page.locator('#job-card-0 tr[data-step]').count(),6);
  assert(await page.locator('#job-card-0 .dashboard-job-details').isHidden());
  await page.locator('#job-card-0 [data-job-view="data"]').click();
  assert(await page.locator('#job-card-0 .dashboard-job-details').isVisible());
  await page.evaluate(()=>refreshJobs());
  assert(await page.locator('#job-card-0 .job-workflow-details').isHidden());
  assert(await page.locator('#job-card-0 .dashboard-job-details').isVisible());
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.jobsAction),'select-details');
  // Previous errors stay in the saved-status disclosure while a new run is active (#613).
  for (const language of ['de', 'en']) {
    await page.evaluate(language=>{window.lang=language; jobsState.jobs[4].running=true; jobWorkflowOpen.delete('4');jobDataView.delete('4'); renderJobsGrid(jobsState.jobs);}, language);
    assert.equal(await page.locator('#job-card-4 > .job-saved-message').count(),0);
    const savedError=page.locator('#job-card-4 .job-details .job-saved-message');
    assert(await savedError.isHidden());
    await page.locator('#job-card-4 [data-jobs-action="toggle-workflow"]').click();
    assert(await savedError.isVisible());
    assert.match(await savedError.innerText(),/Missing path:/);
    assert.match(await savedError.innerText(),/<script>not executable<\/script>/);
    await page.evaluate(()=>renderJobsGrid(jobsState.jobs));
    assert(await savedError.isVisible());
    assert.equal(await page.locator('#jobs-grid script').count(),0);
    await page.evaluate(()=>{jobsState.jobs[4].running=false;renderJobsGrid(jobsState.jobs);});
    assert.equal(await page.locator('#job-card-4 > .job-saved-message').count(),0);
    assert.match(await page.locator('#job-card-4 .job-details .job-saved-message').innerText(),/Missing path:/);
  }
  await page.evaluate(()=>{window.lang='de';});
  // Real log-panel placement must not resize any location's cards (#613).
  await page.evaluate(()=>{window.EventSource=class { addEventListener() {} close() {} }; jobsState.selectedLocation='all'; renderJobsGrid(jobsState.jobs);});
  for (const width of [1920, 1280, 768, 390]) {
    await page.setViewportSize({width,height:1080});
    const dimensions=await page.evaluate(async ()=>{
      const settle=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      closeLogPanel();
      await settle();
      const widths=()=>Array.from(document.querySelectorAll('.jobs-redesign-row'),el=>el.getBoundingClientRect().width);
      const before=widths();
      openLogPanel('6');
      if (document.getElementById('log-panel').parentElement.id!=='log-slot-usb') throw new Error('Log must be inside its location group');
      const output=document.getElementById('log-output');
      output.textContent='[INFO] /mnt/disks/'+'long-path-'.repeat(400)+'\nshort line';
      await settle();
      const after=widths();
      output.scrollLeft=200;
      const scrolls=output.scrollWidth>output.clientWidth && output.scrollLeft>0;
      const withinWorkspace=document.getElementById('log-panel').getBoundingClientRect().right<=document.querySelector('.jobs-workspace').getBoundingClientRect().right+1;
      renderJobsGrid(jobsState.jobs);
      await settle();
      const refreshed=widths();
      closeLogPanel();
      await settle();
      return {before,after,refreshed,closed:widths(),scrolls,withinWorkspace};
    });
    assert.deepEqual(dimensions.after,dimensions.before,`Log changed card widths at ${width}px`);
    assert.deepEqual(dimensions.refreshed,dimensions.before,`Refresh changed card widths at ${width}px`);
    assert.deepEqual(dimensions.closed,dimensions.before);
    assert(dimensions.scrolls,`Long log line must scroll at ${width}px`);
    assert(dimensions.withinWorkspace,`Log exceeds workspace at ${width}px`);
  }
  await page.setViewportSize({width:1920,height:1080});
  // The latest cancelled attempt must not replace a still-valid restore proof.
  for (const language of ['de','en']) {
    const proof = await page.evaluate(language => {
      window.lang=language;
      const row={...jobsState.jobs[0], restore_verification_status:'verified', restore_verification_last_test_result:'cancelled',
        restore_verification_last_test_date:'2026-10-27 10:14:22', restore_verification_evidence_date:'2026-10-26 23:10:52',
        restore_verification_valid_until:'2026-11-25 23:10:52'};
      Object.assign(demoJobs[0], row);
      Object.assign(BBUI.core.state.data.backups[0], {
        restore_verification_status:row.restore_verification_status,
        restore_verification_last_test_result:row.restore_verification_last_test_result,
        restore_verification_last_test_date:row.restore_verification_last_test_date,
        restore_verification_evidence_date:row.restore_verification_evidence_date,
        restore_verification_valid_until:row.restore_verification_valid_until,
      });
      return {card:renderJobRestoreVerification(row),details:renderDashboardRestoreVerificationBadge(row)};
    },language);
    await page.evaluate(()=>refreshJobs());
    assert.match(await page.locator('#job-card-0 .job-restore-proof').innerText(), language==='de'?/[Aa]bgebrochen/:/[Cc]ancelled/);
    assert.equal(await page.locator('#job-card-0 .job-restore-proof .restore-v-badge.success').count(),1);
    for (const html of Object.values(proof)) {
      assert.match(html,/restore-v-badge success/);
      assert.match(html,language==='de'?/[Aa]bgebrochen/:/[Cc]ancelled/);
      assert.match(html,/2026-10-26 23:10:52/);
      assert.match(html,/2026-10-27 10:14:22/);
      assert.match(html,/2026-11-25 23:10:52/);
    }
  }
  await page.evaluate(()=>{window.lang='de';});
  await capture('management-jobs-de');
  for(const lang of ['de','en'])for(const theme of ['light','dark']) {
    await page.evaluate(({lang,theme})=>{window.lang=lang;document.documentElement.dataset.theme=theme;translate();renderJobsGrid(jobsState.jobs);},{lang,theme});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await capture(`management-jobs-${lang}-${theme}-mobile`);
    await page.evaluate(()=>{BBUI.core.navigate('dashboard');renderDashboard(BBUI.core.state.data,null);});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.equal(await page.locator('#dashboard-location-filter option[value="all"]').innerText(), lang==='de'?'Alle Standorte':'All locations');
    await capture(`management-dashboard-${lang}-${theme}-mobile`);
    await page.evaluate(()=>BBUI.core.navigate('jobs'));
  }
  assert.deepEqual(errors,[]);
  console.log('Management dashboard / Jobs browser checks passed (DE/EN, desktop/mobile, light/dark, independent disclosures, full errors, live tests, stable refresh, empty locations).');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
