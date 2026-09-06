const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const id = '11111111-1111-4111-8111-111111111111';
const target = '22222222-2222-4222-8222-222222222222';
async function run(language) {
  const dictionary = JSON.parse(fs.readFileSync(path.join(root, `ui/i18n/${language}.json`)));
  const t = (key, params={}) => {
    const value = key.split('.').reduce((obj, part) => obj?.[part], dictionary);
    assert.equal(typeof value, 'string', `Missing ${language}: ${key}`);
    return value.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
  };
  const elements = new Map();
  const element = name => { if (!elements.has(name)) elements.set(name, {value:'',checked:false,dataset:{},classList:{add(){},remove(){}},innerHTML:'',textContent:''});return elements.get(name); };
  const calls=[];
  const context=vm.createContext({window:{addEventListener(){},BBUI:{components:{i18n:{t,getLanguage:()=>language}}}},
    document:{addEventListener(){},getElementById:element,querySelectorAll:()=>[{dataset:{deleteArtifact:'exact-content-hash'}}]},
    escHtml:text=>String(text??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
    locationIcon:()=>'<svg></svg>',svg:()=>'<svg></svg>', hideEl(){},showMsg(){},apiErrorMessage:()=> 'error',setTimeout:()=>0,clearTimeout(){},console,
    fetch:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({imported_count:1,deleted:true})};}});
  for(const file of ['settings','jobs']) vm.runInContext(fs.readFileSync(path.join(root,`ui/js/pages/${file}.js`),'utf8'),context);
  const evaluate=code=>vm.runInContext(code,context);
  const preview={jobs:[{job_id:id,name:'<unsafe label>',archive_prefix:'own',repository_key:'repo',conflict:'exists',passphrase:{status:'missing'}}],current_jobs:[{job_id:target,name:'Chosen target'}]};
  const html=context.renderSettingsTransferSelectAndActionStep(preview,preview.jobs,'file','complete');
  assert.ok(html.includes('value="new"') && html.includes('value="merge"'));
  assert.ok(html.includes('data-jobs-secure-row-target') && html.includes(target));
  assert.ok(!html.includes('value="overwrite"') && !html.includes('<unsafe label>'));
  const decision={scope:'all',selectedJobs:[id],rowModes:{[id]:'merge'},targetJobs:{[id]:target},archivePrefixes:{[id]:'another'}};
  const confirmation=context.renderSettingsTransferConfirmStep(preview,preview.jobs,'file',decision);
  assert.ok(confirmation.includes(target) && confirmation.includes('data-settings-transfer-confirm-overwrite'));
  context.preview=preview;context.decision=decision;
  evaluate(`refreshSettings=async()=>{}; refreshJobs=async()=>{}; closeModal=()=>{};
    settingsTransferRunSecureJobsWizard=async()=>decision;
    settingsState.transferJobsPreview=preview;settingsState.transferJobsSecureMode=true;
    settingsState.transferJobsSecurePayloadB64='synthetic';settingsState.transferJobsSecurePassword='synthetic';`);
  await context.importJobsApplySelected();
  assert.deepEqual(calls.at(-1).body.target_jobs,{[id]:target});
  assert.deepEqual(calls.at(-1).body.archive_prefixes,{[id]:'another'});
  assert.deepEqual(calls.at(-1).body.per_job_mode,{[id]:'merge'});
  evaluate(`jobsState.pendingDeleteJobKey='${id}'`);
  element('modal-confirm-input').value=id;element('modal-confirm-input').dataset.expected=id;
  await context.confirmJobDelete();
  assert.deepEqual(calls.at(-1).body,{job_id:id,confirmed_artifacts:['exact-content-hash']});
}
(async()=>{await run('de');await run('en');console.log('Canonical transfer UI: explicit ID target and deletion confirmations passed in DE/EN');})().catch(error=>{console.error(error);process.exitCode=1;});
