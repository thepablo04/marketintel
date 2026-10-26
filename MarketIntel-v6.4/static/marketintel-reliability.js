(function () {
  'use strict';
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stamp = value => value ? new Date(value).toLocaleString('es-DO', {dateStyle:'short', timeStyle:'short'}) : 'No informada';
  const expandedKey = key => /^(?:hm_custom|(?:note_|ficha_note_)[A-Z0-9.^=-]{1,15})$/.test(key);
  const allowed = key => (/^(pf_[\w-]+|watchlist|search_history|stock_notes[\w-]*|ticker_bar[\w-]*|mi_[\w-]+)$/.test(key) || expandedKey(key)) && !/(apikey|api_key|secret|token|password|backup_profile)/i.test(key);
  const browserMode = !['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
  const storageLabel = browserMode ? 'Respaldo en este navegador' : 'Respaldo local';
  let browserStore, browserSignals;
  let statePromise = null, saveChain = Promise.resolve(), lastSaved = '', backupTimer;

  function webStore() {
    if (!browserStore) {
      if (!window.MarketIntelBrowserBackupStore) throw new Error('No se pudo cargar el almacenamiento de respaldos. Recarga la página.');
      browserStore = window.MarketIntelBrowserBackupStore.createStore();
    }
    return browserStore;
  }
  const storage = {
    save: (payload, reason) => browserMode ? webStore().save(payload, profile(), reason) : localRequest('/local-backups', {method:'POST',body:JSON.stringify({profile:profile(),reason,snapshot:payload})}),
    list: before => browserMode ? webStore().list(before) : localRequest('/local-backups'+(before ? '?before='+before : '')),
    read: id => browserMode ? webStore().read(Number(id)) : localRequest('/local-backups/'+id),
  };

  function snapshot() {
    const values = {};
    for (let i=0; i<localStorage.length; i++) {
      const key = localStorage.key(i);
      if (allowed(key)) values[key] = localStorage.getItem(key);
    }
    return {version:2, exported_at:new Date().toISOString(), localStorage:values};
  }
  function localState() {
    if (!statePromise) statePromise = fetch('/local-state', {cache:'no-store'}).then(async response => {
      if (!response.ok) throw new Error('No se pudo conectar con los respaldos locales.');
      return response.json();
    }).catch(error => {statePromise=null; throw error;});
    return statePromise;
  }
  async function localRequest(path, options={}) {
    const state = await localState();
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(), 12000);
    try {
      const response = await fetch(path, {...options, cache:'no-store', signal:controller.signal,
        headers:{'Content-Type':'application/json','X-MarketIntel-Token':state.token, ...(options.headers||{})}});
      const data = await response.json();
      if (!response.ok) {if(response.status===403) statePromise=null; throw new Error(data.error||'Respaldo local no disponible.');}
      return data;
    } finally {clearTimeout(timer);}
  }
  function profile() {
    let value = localStorage.getItem('mi_backup_profile_id');
    if (!value || !/^[A-Za-z0-9_-]{8,80}$/.test(value)) {
      value = window.crypto && crypto.randomUUID ? crypto.randomUUID() : 'browser_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2);
      localStorage.setItem('mi_backup_profile_id', value);
    }
    return value;
  }
  function status(message, failed=false) {
    const element = document.getElementById('mi-backup-status');
    if (element) {element.textContent=message; element.classList.toggle('is-error', failed);}
  }
  function save(reason='automatic') {
    // Serialize snapshots so an older response cannot replace the newest state.
    const action = async () => {
      const payload = snapshot();
      normalizedImport(payload, true);
      const fingerprint = JSON.stringify(Object.keys(payload.localStorage).sort().map(key=>[key,payload.localStorage[key]]));
      if (reason==='automatic' && fingerprint===lastSaved) return {status:'unchanged'};
      const result = await storage.save(payload, reason);
      lastSaved=fingerprint;
      status(result.created_at ? storageLabel+': '+stamp(result.created_at) : 'Sin datos para respaldar todavía.');
      return result;
    };
    saveChain=saveChain.catch(()=>{}).then(action).catch(error=>{status('Respaldo pendiente: '+error.message,true);throw error;});
    return saveChain;
  }
  function schedule() {clearTimeout(backupTimer);backupTimer=setTimeout(()=>save().catch(()=>{}),2000);}
  async function beforeMutation(reason) {
    try {await save(reason);return true;}
    catch (error) {alert('No se hizo el cambio porque falló la copia de seguridad. '+error.message);return false;}
  }
  function normalizedImport(payload, allowEmpty=false) {
    if (!payload || !payload.localStorage || typeof payload.localStorage!=='object' || Array.isArray(payload.localStorage)) throw new Error('Formato de copia inválido.');
    if (payload.version != null && ![1,2].includes(payload.version)) throw new Error('Esta versión de copia no es compatible.');
    if (Object.keys(payload.localStorage).length>2000) throw new Error('Demasiadas entradas en la copia.');
    if (new Blob([JSON.stringify(payload.localStorage)]).size>8000000) throw new Error('La copia supera 8 MB.');
    const output = {};
    for(const [key,value] of Object.entries(payload.localStorage)) {
      // Older exports could include MarketBot API keys. Never import them.
      if(!allowed(key)) continue;
      if(typeof value!=='string' || value.length>4000000) throw new Error('Contenido de copia inválido.');
      if(/^(pf_portfolios|pf_positions_.*|pf_transactions_.*|watchlist|search_history)$/.test(key) && !Array.isArray(JSON.parse(value))) throw new Error('La copia contiene una lista de datos inválida.');
      if(key==='hm_custom') {
        const heatmap=JSON.parse(value);
        if(!heatmap || !heatmap.sectors || typeof heatmap.sectors!=='object' || Array.isArray(heatmap.sectors) || Object.values(heatmap.sectors).some(tickers=>!Array.isArray(tickers) || tickers.some(ticker=>typeof ticker!=='string'))) throw new Error('Los grupos del heatmap no son válidos.');
      }
      output[key]=value;
    }
    if(!allowEmpty && !Object.keys(output).length) throw new Error('No hay datos compatibles para importar.');
    return output;
  }
  function restoreTarget(original, values, restore) {
    const target = restore ? {} : {...original};
    // Old backups never included these keys. Do not erase unrepresented notes/groups.
    if(restore) Object.keys(original).filter(expandedKey).forEach(key=>{target[key]=original[key];});
    return Object.assign(target,values);
  }
  function parsed(values,key,fallback) {
    try {return JSON.parse(values[key] || 'null') ?? fallback;} catch (_) {return fallback;}
  }
  function summary(values) {
    const countList=key=>{const list=parsed(values,key,[]);return Array.isArray(list)?list.length:0;};
    return {
      accounts:countList('pf_portfolios'),
      transactions:Object.keys(values).filter(key=>key.startsWith('pf_transactions_')).reduce((total,key)=>total+countList(key),0),
      positions:Object.keys(values).filter(key=>key.startsWith('pf_positions_')).reduce((total,key)=>total+countList(key),0),
      notes:Object.keys(values).filter(key=>/^(note_|ficha_note_|stock_notes)/.test(key)).length,
      groups:Object.keys(parsed(values,'hm_custom',{}).sectors||{}).length,
      watchlist:countList('watchlist'),
    };
  }
  function keyLabel(key,original,target) {
    if(key==='pf_portfolios')return 'Lista de cuentas';
    if(key==='hm_custom')return 'Grupos personalizados del heatmap';
    if(key==='watchlist')return 'Watchlist';
    if(key.startsWith('ficha_note_'))return 'Nota de ficha: '+key.slice(11);
    if(key.startsWith('note_'))return 'Nota de análisis: '+key.slice(5);
    const match=key.match(/^pf_(transactions|positions)_(.+)$/);
    if(match) {
      const accounts=[...parsed(target,'pf_portfolios',[]),...parsed(original,'pf_portfolios',[])];
      const account=accounts.find(item=>item && item.id===match[2]);
      return (match[1]==='transactions'?'Operaciones: ':'Posiciones: ')+(account?account.name:match[2]);
    }
    return 'Preferencia o dato: '+key;
  }
  function previewImport(values,restore) {
    if(document.getElementById('mi-backup-preview')) return Promise.reject(new Error('Cierra la vista previa actual antes de abrir otra copia.'));
    const original=snapshot().localStorage, target=restoreTarget(original,values,restore);
    const current=summary(original), next=summary(target);
    const changes=Array.from(new Set([...Object.keys(original),...Object.keys(target)])).filter(key=>original[key]!==target[key]);
    const fields=[['accounts','Cuentas'],['transactions','Operaciones'],['positions','Posiciones'],['notes','Notas'],['groups','Grupos del heatmap'],['watchlist','Símbolos en watchlist']];
    const preserved=Object.keys(original).filter(key=>expandedKey(key) && !Object.hasOwn(values,key));
    const dialog=document.createElement('dialog');dialog.id='mi-backup-preview';dialog.className='mi-reliability-dialog';dialog.setAttribute('aria-labelledby','mi-backup-preview-title');
    dialog.innerHTML='<h2 id="mi-backup-preview-title">'+(restore?'Restaurar respaldo':'Importar respaldo')+'</h2>'+
      '<p>'+(restore?'Se reemplazarán los datos respaldables por esta versión.':'Los datos incluidos en el archivo reemplazarán sus equivalentes actuales; los demás se conservarán.')+' Se guardará una copia del estado actual antes del cambio.</p>'+
      '<div class="mi-data-scroll"><table><thead><tr><th>Contenido</th><th>Ahora</th><th>Después</th></tr></thead><tbody>'+fields.map(([key,label])=>'<tr><th>'+label+'</th><td>'+current[key]+'</td><td>'+next[key]+'</td></tr>').join('')+'</tbody></table></div>'+
      (preserved.length?'<p>Se conservarán '+preserved.length+' entradas de notas o heatmap que no figuran en esta copia. Las copias antiguas no incluían estos datos.</p>':'')+
      '<details><summary>'+changes.length+' entradas cambiarán · Ver detalle</summary><ul class="mi-backup-changes">'+changes.map(key=>'<li>'+escape(keyLabel(key,original,target))+' — '+(!Object.hasOwn(target,key)?'se eliminará':!Object.hasOwn(original,key)?'se añadirá':'se reemplazará')+'</li>').join('')+'</ul></details>'+
      '<p>Las claves API y las credenciales quedan fuera del respaldo.</p><div class="mi-backup-actions"><button type="button" class="mi-btn" data-cancel>Cancelar</button><button type="button" class="mi-btn" data-confirm>'+(restore?'Respaldar y restaurar':'Respaldar e importar')+'</button></div>';
    document.body.appendChild(dialog);
    return new Promise(resolve=>{
      let accepted=false;
      dialog.addEventListener('close',()=>{dialog.remove();resolve(accepted);},{once:true});
      dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
      dialog.querySelector('[data-confirm]').onclick=()=>{accepted=true;dialog.close();};
      dialog.showModal();dialog.querySelector('[data-cancel]').focus();
    });
  }
  async function importSnapshot(payload, restore=false) {
    const values=normalizedImport(payload);
    if(!await previewImport(values,restore)) return;
    if(!await beforeMutation(restore?'before-restore':'before-import')) return;
    const original = snapshot().localStorage;
    const target = restoreTarget(original,values,restore);
    clearTimeout(backupTimer);
    try {
      Object.keys(original).filter(key=>!Object.hasOwn(target,key)).forEach(key=>localStorage.removeItem(key));
      Object.entries(target).forEach(([key,value])=>localStorage.setItem(key,value));
    } catch(error) {
      // Roll back partial writes (for example browser quota errors).
      try {
        Object.keys(snapshot().localStorage).forEach(key=>localStorage.removeItem(key));
        Object.entries(original).forEach(([key,value])=>localStorage.setItem(key,value));
      } catch (_) {throw new Error('No se pudo completar la importación ni recuperar todos los datos del navegador. Tu copia previa está en Respaldos.');}
      throw new Error('No se pudo importar; se restauró el estado anterior.');
    }
    location.reload();
  }
  async function importFile(event) {
    const file=event.target.files&&event.target.files[0]; if(!file)return;
    try {if(file.size>8000000)throw new Error('El archivo supera 8 MB.');await importSnapshot(JSON.parse(await file.text()));}
    catch(error){alert(error.message);}finally{event.target.value='';}
  }
  function download(payload,name) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function showBackups() {
    let dialog=document.getElementById('mi-backups-dialog');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='mi-backups-dialog';dialog.className='mi-reliability-dialog';document.body.appendChild(dialog);}
    dialog.innerHTML='<button class="mi-btn" data-close>Cerrar</button><h2>'+(browserMode?'Respaldos de este navegador':'Respaldos locales')+'</h2><p>'+(browserMode?'Guardados en este navegador y dominio. No se sincronizan entre dispositivos y pueden perderse al borrar los datos del sitio. Descarga un JSON para conservar una copia independiente.':'Guardados en la carpeta de datos de esta computadora, fuera del navegador.')+' Incluyen notas y grupos personalizados del heatmap. No incluyen claves API. Las copias no se borran automáticamente.</p><div data-list>Cargando…</div>';
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.showModal();
    try {
      const [data,state]=await Promise.all([storage.list(),browserMode?Promise.resolve(null):localState()]);
      const list=dialog.querySelector('[data-list]');
      list.innerHTML=state?'<p class="mi-note">Carpeta de datos: '+escape(state.directory)+'</p>':'';
      const reasons={automatic:'Automático',manual:'Manual','before-import':'Antes de importar','before-restore':'Antes de restaurar','before-delete':'Antes de eliminar'};
      function appendPage(page) {
        const older=list.querySelector('[data-older]');if(older)older.remove();
        list.insertAdjacentHTML('beforeend',page.backups.map(row=>'<div class="mi-backup-row"><span>'+escape(stamp(row.created_at))+' · '+escape(reasons[row.reason]||row.reason)+'</span><button class="mi-btn" data-restore="'+row.id+'">Restaurar</button><button class="mi-btn" data-download="'+row.id+'">Descargar JSON</button></div>').join(''));
        list.querySelectorAll('[data-restore]').forEach(button=>button.onclick=async()=>{try{await importSnapshot(await storage.read(button.dataset.restore),true);}catch(error){alert(error.message);}});
        list.querySelectorAll('[data-download]').forEach(button=>button.onclick=async()=>{try{download(await storage.read(button.dataset.download),'MarketIntel-respaldo-'+button.dataset.download+'.json');}catch(error){alert(error.message);}});
        if(page.next_before){
          const button=document.createElement('button');button.className='mi-btn';button.dataset.older='1';button.textContent='Ver copias anteriores';list.appendChild(button);
          button.onclick=async()=>{button.disabled=true;try{appendPage(await storage.list(page.next_before));}catch(error){alert(error.message);button.disabled=false;}};
        }
      }
      appendPage(data);
      if(!data.backups.length)list.insertAdjacentHTML('beforeend','<p>Todavía no hay copias.</p>');
    }catch(error){dialog.querySelector('[data-list]').textContent=error.message;}
  }
  function initBackup() {
    const panel=document.createElement('div');panel.className='mi-backup-tools';
    panel.innerHTML='<span id="mi-backup-status" role="status">Preparando respaldo…</span><button type="button" class="mi-btn" data-backups>Respaldos</button><button type="button" class="mi-btn" data-backup-now>Guardar ahora</button><button type="button" class="mi-btn" data-backup-export>Exportar todo JSON</button><button type="button" class="mi-btn" data-backup-import>Importar JSON</button><input type="file" accept=".json,application/json" data-backup-file hidden>';
    (document.getElementById('sec-portafolio')||document.body).appendChild(panel);
    panel.querySelector('[data-backups]').onclick=showBackups;
    panel.querySelector('[data-backup-now]').onclick=()=>save('manual').catch(()=>{});
    panel.querySelector('[data-backup-export]').onclick=()=>download(snapshot(),'MarketIntel-respaldo-completo.json');
    panel.querySelector('[data-backup-import]').onclick=()=>panel.querySelector('[data-backup-file]').click();
    panel.querySelector('[data-backup-file]').onchange=importFile;
    save().catch(()=>{});
    setInterval(()=>{if(!document.hidden)save().catch(()=>{});},30000);
    window.addEventListener('online',schedule);
    window.addEventListener('storage',schedule);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
  }

  window.MarketIntelBackup={snapshot,save,schedule,beforeMutation,importFile,importSnapshot,showBackups,allowed,localRequest};

  function signalStore() {
    if (!browserSignals) {
      if (!window.MarketIntelBrowserSignalStore) throw new Error('No se pudo cargar el seguimiento del navegador. Recarga la página.');
      browserSignals = window.MarketIntelBrowserSignalStore.createStore();
    }
    return browserSignals;
  }
  async function preparePulse(pulse) {
    if (!browserMode || !pulse) return pulse;
    let evaluation;
    try {
      const history = await signalStore().processPulse(pulse);
      evaluation = {storage:'browser', model:history.model, summary:history.summary, method:history.method};
    } catch (error) {
      // A storage failure must not turn valid market data into a missing pulse,
      // nor present a server-wide/old summary as this browser's saved history.
      evaluation = {storage:'browser', summary:null, method:pulse.evaluation&&pulse.evaluation.method, error:error.message};
    }
    return {...pulse, evaluation};
  }

  function blocks(items) {
    return (items||[]).map(item=>'<div class="mi-pulse-component"><div class="mi-pulse-component-head"><span>'+escape(item.label)+'</span><small>'+escape(item.weight)+'% base</small><strong>'+ (item.score==null?'—':Number(item.score).toFixed(0))+'</strong></div><p>'+escape(item.detail)+'</p></div>').join('');
  }
  function renderPulse(host,pulse) {
    if(!pulse){host.innerHTML='<div class="mi-widget-head"><h2>Sesgo intradía</h2></div><p role="status">Consultando cotizaciones con fecha y hora…</p>';return;}
    const intra=pulse.intraday, context=pulse.context, summary=pulse.evaluation&&pulse.evaluation.summary;
    const tone=intra.score==null?'neutral':intra.score>=60?'up':intra.score<=40?'down':'neutral';
    const statuses={recent:'Reciente',delayed:'Retrasado',stale:'Antiguo · excluido',closed:'Sesión cerrada',unavailable:'Sin dato'};
    const table=Object.entries(pulse.quotes||{}).map(([ticker,q])=>'<tr title="'+escape(q.reason)+'"><td>'+escape(ticker)+'</td><td>'+ (q.price==null?'—':Number(q.price).toFixed(2))+'</td><td>'+escape(stamp(q.data_at))+'</td><td>'+escape(statuses[q.status]||q.status)+'</td></tr>').join('');
    host.innerHTML='<div class="mi-widget-head"><div><span class="mi-label">SESIÓN ACTUAL · v'+escape(pulse.version)+'</span><h2 class="mi-status-'+tone+'">'+escape(intra.label)+'</h2></div><button class="mi-btn" data-pulse-refresh>Actualizar</button></div>'+
      '<div class="mi-score"><div class="mi-intraday-number">'+(intra.score==null?'—':Number(intra.score).toFixed(0))+'<small>/100</small></div><div class="mi-score-copy"><strong>Calidad de señales '+intra.quality+'/100</strong><p>Cobertura '+intra.coverage+'% · No es probabilidad de acierto.</p></div></div>'+
      '<p>'+escape(pulse.session.label)+(intra.provisional?' · Lectura provisional: primeros 15 minutos.':'')+'</p>'+
      (intra.reason?'<p class="mi-data-warning">'+escape(intra.reason)+'</p>':'')+
      '<p class="mi-note">Consulta '+escape(stamp(pulse.updated_at))+(pulse.cached?' · respuesta en caché corta':'')+'. Las horas de cada dato aparecen abajo.</p>'+
      '<details><summary>Qué está influyendo hoy</summary>'+blocks(intra.components)+'</details>'+
      '<div class="mi-context-card"><span class="mi-label">CONTEXTO DE VARIOS DÍAS · NO ES LA DIRECCIÓN DE HOY</span><strong>'+escape(context.label)+' · '+(context.score==null?'—':context.score)+'/100</strong><p>Cierres completos hasta '+escape(context.last_history_date||'sin datos')+'</p><details><summary>Ver tendencia, sectores, VIX y crédito</summary>'+blocks(context.components)+'</details></div>'+
      '<details><summary>Frescura de las fuentes</summary><div class="mi-data-scroll"><table><thead><tr><th>Activo</th><th>Precio</th><th>Hora de la vela</th><th>Estado</th></tr></thead><tbody>'+table+'</tbody></table></div><p>Velas de 1 minuto de Yahoo Finance. No garantiza datos tick a tick. Solo se incluyen datos de esta sesión con antigüedad máxima de 5 minutos.</p></details>'+
      '<details><summary>'+(browserMode?'Seguimiento en este navegador':'Seguimiento real desde esta instalación')+'</summary><p>'+(summary?escape(summary.total+' lecturas registradas · '+summary.evaluated+' evaluadas · '+summary.days+' sesiones distintas. ')+(summary.hit_rate==null?'Aún no hay aciertos medibles.':escape(summary.hit_rate+'% de acierto observado en '+summary.directional+' lecturas direccionales. Muestra experimental, no probabilidad futura.')):escape(pulse.evaluation&&pulse.evaluation.error||'Sin historial todavía.'))+'</p><p>'+escape(pulse.evaluation&&pulse.evaluation.method||'No se generan resultados históricos ficticios.')+'</p>'+(browserMode?'<p class="mi-note">Se guarda por navegador y dominio, sin sincronización entre dispositivos. Exporta el historial antes de borrar los datos de este sitio.</p>':'')+'<button class="mi-btn" data-journal>Exportar seguimiento</button></details>'+
      ((pulse.errors||[]).length?'<p class="mi-data-warning">'+escape(pulse.errors.join(' · '))+'</p>':'')+
      '<p class="mi-pulse-disclaimer">'+escape(pulse.disclaimer)+'</p>';
    host.querySelector('[data-journal]').onclick=async()=>{try{download(await (browserMode?signalStore().history(true):localRequest('/signal-history')),'MarketIntel-seguimiento.json');}catch(error){alert(error.message);}};
  }
  window.MarketIntelPulse={render:renderPulse,prepare:preparePulse};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',initBackup);else initBackup();
})();
