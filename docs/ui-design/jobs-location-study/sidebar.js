(() => {
  const jobs = [
    {location:'Storagebox',type:'Remote',name:'Appdata Nightly',key:'appdata-storagebox',description:'Sichert Appdata, Docker-Konfigurationen und VM-Metadaten auf die Storagebox.',features:['▣ Docker','▤ VMs'],policy:'Comp: zstd,6 · Ret: 7/4/12/3',last:'vor 1 Tag · OK',restore:'Verifiziert',restoreClass:'ok',restoreDetail:'Letzter Test: 18.06.2026 · Gültig bis: 18.07.2026',schedule:'Nächster Lauf: 20.06.2026, 02:00',status:'Läuft',statusClass:'info',running:true},
    {location:'USB',type:'Lokal',name:'Fotos Weekly',key:'photos-usb',description:'Sichert die Fotosammlung wöchentlich auf das externe USB-Laufwerk.',features:['▣ Verzeichnisse'],policy:'Comp: zstd,1 · Ret: 14/8/12/5',last:'vor 6 Tagen · Warnung',restore:'Überfällig',restoreClass:'warn',restoreDetail:'Letzter Test: 12.05.2026 · Gültig bis: 11.06.2026',schedule:'Nächster Lauf: 20.06.2026, 02:30',status:'Warnung',statusClass:'warn'},
    {location:'SMB',type:'Netzwerk',name:'Dokumente NAS',key:'documents-smb',description:'Sichert Dokumente und Projektdateien auf das NAS.',features:['▣ Verzeichnisse'],policy:'Comp: lz4 · Ret: 7/4/6/3',last:'vor 2 Tagen · Fehler',restore:'Fehlgeschlagen',restoreClass:'bad',restoreDetail:'Letzter Test: 17.06.2026',schedule:'Job ist deaktiviert',status:'Deaktiviert',statusClass:'bad',disabled:true},
    {location:'Weitere Skripte',type:'Legacy',name:'Legacy Backup',key:'legacy-custom',description:'Bestehendes handgeschriebenes Backup-Skript außerhalb des Wizards.',features:['Legacy'],policy:'Keine Policy erkannt',last:'Noch kein Backup durchgeführt',restore:'Nicht geplant',restoreClass:'neutral',restoreDetail:'Für diesen Job ist kein Restore-Test geplant.',schedule:'Zeitplan deaktiviert',status:'Bereit',statusClass:'neutral',legacy:true}
  ];
  const locations = [...new Set(jobs.map(job=>job.location))];
  const badge = (text,cls='') => `<span class="badge ${cls}">${text}</span>`;
  let selected = 'all';

  const renderLocations = () => {
    const entries = [{name:'all',label:'Alle Lokationen',type:'Übersicht'},...locations.map(name=>({name,label:name,type:jobs.find(job=>job.location===name).type}))];
    document.getElementById('location-list').innerHTML = entries.map(entry=>{
      const count = entry.name==='all' ? jobs.length : jobs.filter(job=>job.location===entry.name).length;
      return `<button class="location-entry ${selected===entry.name?'active':''}" data-location="${entry.name}"><span class="location-glyph">${entry.name==='all'?'≡':entry.name==='Storagebox'?'↗':entry.name==='USB'?'▯':entry.name==='SMB'?'⌁':'⌘'}</span><span><strong>${entry.label}</strong><small>${entry.type}</small></span>${badge(count)}</button>`;
    }).join('');
    document.querySelectorAll('[data-location]').forEach(button=>button.addEventListener('click',()=>{selected=button.dataset.location;render()}));
  };

  const renderJob = job => `<article class="job-row ${job.running?'is-running':''} ${job.disabled?'is-disabled':''}">
    <div class="job-main"><div class="job-title"><span class="job-icon">▣</span><div><h3>${job.name}</h3><span class="subtitle mono">${job.key}</span></div></div><p class="description">${job.description}</p><div class="features">${job.features.map(item=>`<span class="feature">${item}</span>`).join('')}</div></div>
    <div class="job-operation"><span class="label">Betriebszustand</span>${badge(job.status,job.statusClass)}<span class="subtitle">${job.last}</span><span class="label gap">Zeitplan</span><span>${job.schedule}</span></div>
    <div class="job-policy"><span class="label">Policy</span><span class="mono">${job.policy}</span><span class="label gap">Restore-Nachweis</span>${badge(`Restore: ${job.restore}`,job.restoreClass)}<span class="subtitle">${job.restoreDetail}</span></div>
    <div class="job-actions"><button class="btn ${job.running?'':'primary'}" ${job.disabled?'disabled':''}>${job.running?'Log anzeigen':'▶ Starten'}</button><button class="btn icon" title="Job bearbeiten, Zeitplan, Aktivieren oder Löschen">⋮</button></div>
  </article>`;

  const renderJobs = () => {
    const visible = selected==='all' ? jobs : jobs.filter(job=>job.location===selected);
    document.getElementById('selection-title').textContent = selected==='all' ? 'Alle Lokationen' : selected;
    document.getElementById('selection-count').textContent = `${visible.length} ${visible.length===1?'Job':'Jobs'}`;
    const groups = selected==='all' ? locations : [selected];
    document.getElementById('job-groups').innerHTML = groups.map(location=>{
      const locationJobs = visible.filter(job=>job.location===location);
      if (!locationJobs.length) return '';
      const type = jobs.find(job=>job.location===location).type;
      return `<section class="location-group"><header><div><span class="location-glyph">${location==='Storagebox'?'↗':location==='USB'?'▯':location==='SMB'?'⌁':'⌘'}</span><div><h3>${location}</h3><span>${type}</span></div></div>${badge(`${locationJobs.length} Job`)}</header>${locationJobs.map(renderJob).join('')}</section>`;
    }).join('');
  };

  const render=()=>{renderLocations();renderJobs()};
  render();
  document.documentElement.dataset.theme=localStorage.getItem('jobs-sidebar-theme')||'dark';
  const theme=document.getElementById('theme-toggle');
  const sync=()=>theme.textContent=document.documentElement.dataset.theme==='dark'?'☀':'☾';
  sync();theme.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;localStorage.setItem('jobs-sidebar-theme',next);sync()});
})();
