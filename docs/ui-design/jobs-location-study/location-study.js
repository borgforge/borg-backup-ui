(() => {
  const jobs = [
    {location:'Storagebox',type:'Remote',name:'Appdata Nightly',key:'appdata-storagebox',description:'Sichert Appdata, Docker-Konfigurationen und VM-Metadaten auf die Storagebox.',features:['▣ Docker','▤ VMs'],compression:'zstd,6',retention:'7/4/12/3',last:'vor 1 Tag · OK',restore:'Verifiziert',restoreClass:'ok',restoreDetail:'Letzter Test: 18.06.2026 · Gültig bis: 18.07.2026',schedule:'Nächster Lauf: 20.06.2026, 02:00',status:'Läuft',statusClass:'info',running:true},
    {location:'USB',type:'Lokal',name:'Fotos Weekly',key:'photos-usb',description:'Sichert die Fotosammlung wöchentlich auf das externe USB-Laufwerk.',features:['▣ Verzeichnisse'],compression:'zstd,1',retention:'14/8/12/5',last:'vor 6 Tagen · Warnung',restore:'Überfällig',restoreClass:'warn',restoreDetail:'Letzter Test: 12.05.2026 · Gültig bis: 11.06.2026',schedule:'Nächster Lauf: 20.06.2026, 02:30',status:'Warnung',statusClass:'warn'},
    {location:'SMB',type:'Netzwerk',name:'Dokumente NAS',key:'documents-smb',description:'Sichert Dokumente und Projektdateien auf das NAS.',features:['▣ Verzeichnisse'],compression:'lz4',retention:'7/4/6/3',last:'vor 2 Tagen · Fehler',restore:'Fehlgeschlagen',restoreClass:'bad',restoreDetail:'Letzter Test: 17.06.2026',schedule:'Job ist deaktiviert',status:'Deaktiviert',statusClass:'bad',disabled:true},
    {location:'Weitere Skripte',type:'Legacy',name:'Legacy Backup',key:'legacy-custom',description:'Bestehendes handgeschriebenes Backup-Skript außerhalb des Wizards.',features:['Legacy'],compression:'Keine Policy erkannt',retention:'—',last:'Noch kein Backup durchgeführt',restore:'Nicht geplant',restoreClass:'neutral',restoreDetail:'Für diesen Job ist kein Restore-Test geplant.',schedule:'Zeitplan deaktiviert',status:'Bereit',statusClass:'neutral',legacy:true}
  ];

  const badge = (text, cls='') => `<span class="badge ${cls}">${text}</span>`;
  const actions = job => `<div class="job-actions"><button class="btn ${job.running?'':'primary'}" ${job.disabled?'disabled':''}>${job.running?'Log anzeigen':'▶ Starten'}</button><button class="btn icon" title="Weitere Aktionen">⋮</button></div>`;
  const menu = job => `<div class="action-strip"><button>${job.legacy?'In Wizard übernehmen':'Job bearbeiten'}</button><button>Zeitplan ${job.schedule.includes('Nächster')?badge('aktiv','ok'):badge('aus','neutral')}</button><button>Job ${job.disabled?'aktivieren':'deaktivieren'}</button><button class="danger">Job löschen</button></div>`;
  const facts = job => `<div class="fact"><label>Letzter Lauf</label>${job.last}</div><div class="fact"><label>Kompression</label><span class="mono">${job.compression}</span></div><div class="fact"><label>Retention</label><span class="mono">${job.retention}</span></div><div class="fact"><label>Zeitplan</label>${job.schedule}</div>`;

  document.getElementById('variant-a').innerHTML = jobs.map(job => `
    <article class="location-workspace ${job.running?'is-running':''} ${job.disabled?'is-disabled':''}">
      <header class="workspace-head"><div class="location-identity"><span class="location-symbol">${job.location==='Storagebox'?'↗':job.location==='USB'?'▯':job.location==='SMB'?'⌁':'⌘'}</span><div><span class="label">${job.type}</span><h2>${job.location}</h2></div></div><div>${badge('1 Job')} ${badge(job.status,job.statusClass)}</div></header>
      <div class="workspace-job"><div class="job-primary"><div class="job-title"><span class="job-icon">▣</span><div><h3>${job.name}</h3><span class="subtitle mono">${job.key}</span></div></div><p class="description">${job.description}</p><div class="features">${job.features.map(x=>`<span class="feature">${x}</span>`).join('')}</div></div><div class="workspace-facts">${facts(job)}</div><div class="proof"><span class="label">Restore-Nachweis</span>${badge(`Restore: ${job.restore}`,job.restoreClass)}<span class="subtitle">${job.restoreDetail}</span></div>${actions(job)}</div>
      ${job.name==='Fotos Weekly'?menu(job):''}
    </article>`).join('');

  const browser = document.getElementById('variant-b');
  const renderBrowser = selectedIndex => {
    const selected = jobs[selectedIndex];
    const hasDocker = selected.features.includes('▣ Docker');
    const hasVms = selected.features.includes('▤ VMs');
    const impacts = hasDocker || hasVms
      ? `<div class="impact"><strong>Startauswirkungen</strong>${hasDocker?'<span>Docker-Container werden gestoppt und danach wieder gestartet.</span>':''}${hasVms?'<span>Laufende VMs werden heruntergefahren und danach neu gestartet.</span>':''}<small>Die Log-Ausgabe wird live im Browser angezeigt.</small></div>`
      : `<div class="impact quiet"><strong>Startauswirkungen</strong><span>Die Log-Ausgabe wird live im Browser angezeigt.</span></div>`;
    const tabs = jobs.map((job,i)=>`<button class="location-tab ${i===selectedIndex?'active':''}" data-location-index="${i}"><span>${job.location}</span><small>${job.type} · 1 Job</small><b class="status-pip ${job.statusClass}"></b></button>`).join('');
    browser.innerHTML = `<div class="location-tabs">${tabs}</div><div class="location-browser"><aside><div class="browser-head"><span class="label">${selected.location}</span><strong>Jobs an diesem Ort</strong></div><div class="compact-job active"><div><strong>${selected.name}</strong><span class="subtitle mono">${selected.key}</span></div>${badge(selected.status,selected.statusClass)}</div><button class="btn add-location">＋ Job für ${selected.location}</button></aside><article class="job-sheet"><header><div class="job-title"><span class="job-icon">▣</span><div><h2>${selected.name}</h2><span class="subtitle mono">${selected.key}</span></div></div>${actions(selected)}</header><p>${selected.description}</p><div class="features">${selected.features.map(x=>`<span class="feature">${x}</span>`).join('')}</div><div class="sheet-grid">${facts(selected)}<div class="fact restore-fact"><label>Restore-Nachweis</label>${badge(`Restore: ${selected.restore}`,selected.restoreClass)}<span class="subtitle">${selected.restoreDetail}</span></div></div>${impacts}${menu(selected)}</article></div>`;
    browser.querySelectorAll('[data-location-index]').forEach(tab=>tab.addEventListener('click',()=>renderBrowser(Number(tab.dataset.locationIndex))));
  };
  renderBrowser(0);

  document.getElementById('variant-c').innerHTML = `<div class="location-summary">${jobs.map(job=>`<div class="summary-tile"><span class="location-symbol">${job.location==='Storagebox'?'↗':job.location==='USB'?'▯':job.location==='SMB'?'⌁':'⌘'}</span><div><span class="label">${job.type}</span><strong>${job.location}</strong><small>1 Job · ${job.status}</small></div></div>`).join('')}</div><div class="matrix-head"><span>Job / Beschreibung</span><span>Betrieb</span><span>Datenschutz</span><span>Ausführung</span><span></span></div>${jobs.map(job=>`<article class="matrix-job ${job.running?'is-running':''} ${job.disabled?'is-disabled':''}"><div class="matrix-location"><span>${job.location}</span>${badge(job.type)}</div><div class="matrix-row"><div><div class="job-title"><span class="job-icon">▣</span><div><h3>${job.name}</h3><span class="subtitle mono">${job.key}</span></div></div><p class="description">${job.description}</p><div class="features">${job.features.map(x=>`<span class="feature">${x}</span>`).join('')}</div></div><div>${badge(job.status,job.statusClass)}<span class="subtitle">${job.last}</span></div><div>${badge(`Restore: ${job.restore}`,job.restoreClass)}<span class="subtitle">${job.restoreDetail}</span></div><div><span class="mono">${job.compression} · ${job.retention}</span><span class="subtitle">${job.schedule}</span></div>${actions(job)}</div></article>`).join('')}`;

  const q = new URLSearchParams(location.search);
  const variant = ['a','b','c'].includes(q.get('v')) ? q.get('v') : 'a';
  document.querySelectorAll('.variant').forEach(x=>x.classList.toggle('active',x.dataset.variant===variant));
  document.querySelectorAll('[data-variant-choice]').forEach(x=>{x.classList.toggle('active',x.dataset.variantChoice===variant);x.addEventListener('click',()=>{q.set('v',x.dataset.variantChoice);location.search=q.toString()})});
  document.documentElement.dataset.theme = localStorage.getItem('jobs-location-theme') || 'dark';
  const theme=document.getElementById('theme-toggle');
  const sync=()=>theme.textContent=document.documentElement.dataset.theme==='dark'?'☀':'☾';
  sync(); theme.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;localStorage.setItem('jobs-location-theme',next);sync()});
})();
