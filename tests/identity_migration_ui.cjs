const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'ui/js/components/identity-migration.js'), 'utf8');
const base = { migration_id: 'immutable_job_id_v1', status: 'pending', stage: 'required', busy: false,
  reason_codes: [], suggested_state_dir: '/mnt/user/private/migration', can_prepare: true };
const backup = { ...base, stage: 'backup_ready', plan_id: 'plan-one', snapshot_digest: 'sha-one',
  can_prepare: false,
  snapshot: { path: '/mnt/user/private/<unsafe>', created_at: '2026-09-06T12:00:00Z', size_bytes: 456, verified: true } };
async function run(language) {
  const dictionary = JSON.parse(fs.readFileSync(path.join(root, `ui/i18n/${language}.json`)));
  const t = (key, params={}) => {
    const value = key.split('.').reduce((obj, part) => obj?.[part], dictionary);
    if (value === undefined && key.includes('.reasons.')) return key;
    assert.equal(typeof value, 'string', `Missing ${language}: ${key}`);
    return value.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
  };
  let server = { ...base }, fail = false, postFailure = false, resolvePost = null, reloads = 0;
  let prepareBlocked = false, httpFailure = null;
  let updates = 0, html = '', fieldValue = null;
  const timers = new Map(), calls = [], listeners = {};
  const host = {
    isConnected: true, getClientRects: () => [1], contains: () => true,
    get innerHTML() { return html; }, set innerHTML(value) {
      html=value; updates++; fieldValue = html.match(/data-identity-path[^>]*value="([^"]*)"/)?.[1] ?? null;
    }, querySelector(selector) { return selector === '[data-identity-path]' && fieldValue !== null ? { value: fieldValue } : null; },
  };
  const window = { BBUI: { components: { i18n: { t, getLanguage: () => language } } }, location: { reload: () => reloads++ },
    addEventListener: (name, handler) => listeners[name] = handler };
  const context = vm.createContext({ window, console, clearTimeout: id => timers.delete(id),
    setTimeout: fn => { const id=Symbol(); timers.set(id,fn); return id; },
    fetch: async (url, options={}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({ url, method: options.method || 'GET', body, options });
      if (fail) throw new Error('connection interrupted');
      if (options.method === 'POST') {
        if (postFailure) throw new Error('connection interrupted');
        if (resolvePost) await new Promise(resolve => resolvePost.resolve=resolve);
        if (httpFailure) return { ok: false, status: 400, json: async () => httpFailure };
        if (prepareBlocked) {
          server = {...base, status:'blocked', reason_codes:['invalid_identity_descriptor'],
            last_preparation:{status:'blocked',reason_codes:['invalid_identity_descriptor']}};
          return {ok:true,json:async()=>server};
        }
        if (url.endsWith('/prepare')) server={...backup};
        if (url.endsWith('/acknowledge')) server={...server,stage:'acknowledged'};
        if (url.endsWith('/apply')) server={...server,stage:'applying',busy:true};
      }
      return { ok: true, json: async () => JSON.parse(JSON.stringify(server)) };
    } });
  vm.runInContext(source,context);
  const assistant=window.BBUI.components.identityMigration;
  const click=action=>host.onclick({target:{closest:()=>({dataset:{identityAction:action},disabled:false})}});
  const check=checked=>host.onchange({target:{matches:()=>true,checked}});
  const posts=()=>calls.filter(call=>call.method==='POST');
  assistant.mount(host);
  await assistant.refresh();
  assert.equal(posts().length,0,'opening only observes');
  assert.ok(html.includes('data-identity-action="prepare"'));
  assert.ok(!html.includes('data-identity-action="apply"'));
  const unchanged=updates;
  await assistant.refresh();
  assert.equal(updates,unchanged,'unchanged polling does not replace the form');
  for (const invalid of ['', 'relative/path']) {
    fieldValue=invalid; await click('prepare');
    assert.equal(posts().length,0,'missing/relative paths never silently choose a server default');
    assert.ok(html.includes(t('settings.identityMigration.pathRequired')));
    assert.equal(fieldValue,invalid,'validation preserves an intentionally empty path');
    await click('prepare');
    assert.equal(posts().length,0,'repeated validation never restores a default path');
  }
  fieldValue='/mnt/cache/private/selected';
  prepareBlocked=true; resolvePost={};
  const blockedRequest=click('prepare');
  assert.ok(html.includes(t('settings.identityMigration.requestPending')),'click gives immediate feedback');
  resolvePost.resolve(); await blockedRequest; resolvePost=null; prepareBlocked=false;
  assert.ok(html.includes(t('settings.identityMigration.preparationFailed')));
  assert.ok(html.includes(t('settings.identityMigration.reasons.invalid_identity_descriptor')));
  server={...server,status:'pending',reason_codes:Array(6).fill('invalid_identity_descriptor')};
  await assistant.refresh();
  assert.ok(html.includes(t('settings.identityMigration.preparationFailed')),'readiness polling retains last failed preparation');
  assert.ok(html.includes(t('settings.identityMigration.reasonCount',{count:6})));
  assert.equal(html.split('Diagnosecode: invalid_identity_descriptor').length-1,language==='de'?2:0,
    'duplicate current reasons become one row, alongside the last preparation result');
  httpFailure={code:'invalid_request',message:'original_migration_location_required'};
  await click('prepare'); httpFailure=null;
  assert.ok(html.includes(t('settings.identityMigration.reasons.original_migration_location_required')));
  await assistant.refresh();
  assert.ok(html.includes(t('settings.identityMigration.reasons.original_migration_location_required')),'polling retains action errors');
  httpFailure={code:'invalid_request',message:'password=do-not-display'};
  await click('prepare'); httpFailure=null;
  assert.ok(!html.includes('do-not-display'),'arbitrary server error text is not shown');
  assert.ok(html.includes(t('settings.identityMigration.requestFailed',{status:400})));
  server={...base}; await assistant.refresh(); calls.length=0;
  fieldValue='/mnt/cache/private/selected';
  await click('prepare');
  assert.deepEqual(posts().at(-1).body,{state_dir:'/mnt/cache/private/selected'});
  assert.equal(posts().length,1);
  assert.ok(html.includes('/snapshot?plan_id=plan-one&amp;snapshot_digest=sha-one'));
  assert.ok(html.includes('&lt;unsafe&gt;') && !html.includes('/private/<unsafe>'));
  assert.ok(!html.includes('data-identity-action="apply"'),'verified snapshot is mandatory pause');
  await click('acknowledge');
  assert.equal(posts().length,1,'unchecked acknowledgement cannot POST');
  check(true);
  assert.equal(posts().length,1,'checkbox alone cannot POST');
  await click('acknowledge');
  assert.deepEqual(posts().at(-1).body,{plan_id:'plan-one',snapshot_digest:'sha-one',independent_backup_ack:true});
  assert.equal(posts().length,2,'acknowledgement does not apply');
  assert.ok(html.includes('data-identity-action="apply"'));
  resolvePost={};
  const first=click('apply');
  await click('apply');
  assert.equal(posts().length,3,'rapid double-click only starts one request');
  resolvePost.resolve(); await first; resolvePost=null;
  assert.equal(reloads,0);
  assert.ok(!html.includes('data-identity-action="apply"'));
  assistant.mount(host); await assistant.refresh();
  assert.equal(posts().length,3,'reconnect to an active operation only observes');
  server={...backup,stage:'interrupted',status:'failed',can_resume:false};
  await assistant.refresh(); await click('apply');
  assert.equal(posts().length,3,'unknown partial state cannot resume');
  server={...server,can_resume:true}; await assistant.refresh();
  assert.ok(html.includes(t('settings.identityMigration.resume')));
  await click('apply'); assert.equal(posts().length,4);
  server={...backup,stage:'backup_ready'}; await assistant.refresh(); check(true);
  server={...server,plan_id:'plan-two',snapshot_digest:'sha-two'}; await assistant.refresh();
  await click('acknowledge'); assert.equal(posts().length,4,'new binding clears local acknowledgement');
  server={...server,snapshot:{...server.snapshot,verified:false}}; await assistant.refresh();
  assert.ok(!html.includes('download rel='));
  await click('apply'); assert.equal(posts().length,4,'unverified snapshot cannot apply');
  server={...backup,stage:'acknowledged'}; await assistant.refresh();
  postFailure=true; await click('apply'); postFailure=false;
  const uncertainPosts=posts().length;
  await click('apply'); assert.equal(posts().length,uncertainPosts,'uncertain POST cannot immediately retry');
  server={...server,stage:'applying',busy:true}; await assistant.refresh();
  assert.equal(posts().length,uncertainPosts,'status reconciliation never retries writes');
  fail=true; await assistant.refresh();
  assert.ok(html.includes(t('settings.identityMigration.statusUnavailable')));
  await click('apply'); assert.equal(posts().length,uncertainPosts);
  fail=false;
  server={...base,stage:'interrupted',plan_id:'original-plan',state_dir:'/mnt/cache/private/original',can_prepare:true};
  await assistant.refresh();
  assert.ok(html.includes('readonly') && html.includes(t('settings.identityMigration.resumePreparation')));
  assert.ok(html.includes('aria-current="step"><span>2</span>'), 'interrupted preparation never marks the backup complete');
  fieldValue='/mnt/cache/new-map-is-forbidden';
  await click('prepare');
  assert.deepEqual(posts().at(-1).body,{state_dir:'/mnt/cache/private/original'},'resume preparation retains original location');
  server={...backup,reason_codes:['<script>unsafe</script>'],stage:'waiting',status:'blocked'};
  await assistant.refresh();
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;') && !html.includes('<script>'));
  server={...backup,stage:'complete',status:'applied',restart_required:true}; await assistant.refresh();
  await click('open'); assert.equal(reloads,0);
  server={...server,restart_required:false}; await assistant.refresh();
  assert.equal(reloads,0,'completion does not reload automatically');
  await click('open'); assert.equal(reloads,1);
  listeners['bbui:language-changed']();
  server={...base,status:'not_applicable',stage:'complete'}; await assistant.refresh();
  assert.equal(html,'');
  assert.ok(calls.every(call=>call.options.credentials==='include'));
  const settingsCalls=[], elements=new Map();
  const element=id=>{
    if (!elements.has(id)) elements.set(id,{innerHTML:'',classList:{add(){},remove(){}}});
    return elements.get(id);
  };
  const health={startup_state:{mode:'maintenance',failures:[]},paths:{migration_log_file:'/private/migration.jsonl'}};
  const settingsContext=vm.createContext({window:{addEventListener(){},BBUI:{core:{fetchSystemHealth:async()=>health},
    components:{i18n:{t,getLanguage:()=>language},identityMigration:{mount(){}}}}},
    document:{getElementById:element},hideEl(){},showMsg(){},locationIcon:()=>'<svg></svg>',
    escHtml:value=>String(value??'').replaceAll('<','&lt;'),
    fetch:async url=>{settingsCalls.push(url);return{ok:true,json:async()=>({current_role:'admin'})}}});
  vm.runInContext(fs.readFileSync(path.join(root,'ui/js/pages/settings.js'),'utf8'),settingsContext);
  await settingsContext.refreshSettings();
  assert.deepEqual(settingsCalls,['/api/auth/status'],'maintenance never loads operational settings or inventory routes');
  assert.ok(element('settings-content').innerHTML.includes('identity-migration-assistant'));
  assert.ok(!element('settings-content').innerHTML.includes('data-key='));
}
(async()=>{await run('de');await run('en');console.log('Migration assistant: explicit consent, pause, reconnect, safe continuation and escaping passed in DE/EN');})().catch(error=>{console.error(error);process.exitCode=1;});
