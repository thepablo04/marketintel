(function () {
  'use strict';
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stamp = value => value ? new Date(value).toLocaleString('es-DO', {dateStyle:'short', timeStyle:'short'}) : 'No informada';
  const allowed = key => /^(pf_[\w-]+|watchlist|search_history|stock_notes[\w-]*|ticker_bar[\w-]*|mi_[\w-]+)$/.test(key) && !/(apikey|api_key|secret|token|password|backup_profile)/i.test(key);
  let statePromise = null, saveChain = Promise.resolve(), lastSaved = '', backupTimer;

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
      const fingerprint = JSON.stringify(Object.keys(payload.localStorage).sort().map(key=>[key,payload.localStorage[key]]));
      if (reason==='automatic' && fingerprint===lastSaved) return {status:'unchanged'};
      const result = await localRequest('/local-backups', {method:'POST',body:JSON.stringify({profile:profile(),reason,snapshot:payload})});
      lastSaved=fingerprint;
      status(result.created_at ? 'Respaldo local: '+stamp(result.created_at) : 'Sin datos para respaldar todavía.');
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
  function normalizedImport(payload) {
    if (!payload || !payload.localStorage || typeof payload.localStorage!=='object' || Array.isArray(payload.localStorage)) throw new Error('Formato de copia inválido.');
    const output = {};
    for(const [key,value] of Object.entries(payload.localStorage)) {
      // Older exports could include MarketBot API keys. Never import them.
      if(!allowed(key)) continue;
      if(typeof value!=='string' || value.length>4000000) throw new Error('Contenido de copia inválido.');
      if(/^(pf_portfolios|pf_positions_.*|pf_transactions_.*|watchlist|search_history)$/.test(key) && !Array.isArray(JSON.parse(value))) throw new Error('La copia contiene una lista de datos inválida.');
      output[key]=value;
    }
    if(!Object.keys(output).length) throw new Error('No hay datos compatibles para importar.');
    return output;
  }
  async function importSnapshot(payload, restore=false) {
    const values=normalizedImport(payload);
    if(!confirm(restore?'¿Restaurar esta copia? Se respaldará el estado actual antes de reemplazar tus datos.':'¿Importar esta copia? Se respaldará el estado actual antes del cambio.')) return;
    if(!await beforeMutation(restore?'before-restore':'before-import')) return;
    const original = snapshot().localStorage;
    try {
      if(restore) Object.keys(original).forEach(key=>localStorage.removeItem(key));
      Object.entries(values).forEach(([key,value])=>localStorage.setItem(key,value));
    } catch(error) {
      // Roll back partial writes (for example browser quota errors).
      Object.keys(snapshot().localStorage).forEach(key=>localStorage.removeItem(key));
      Object.entries(original).forEach(([key,value])=>localStorage.setItem(key,value));
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
    dialog.innerHTML='<button class="mi-btn" data-close>Cerrar</button><h2>Respaldos locales</h2><p>Guardados fuera del navegador. No incluyen claves API. Las copias no se borran automáticamente.</p><div data-list>Cargando…</div>';
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.showModal();
    try {
      const [data,state]=await Promise.all([localRequest('/local-backups'),localState()]);
      const list=dialog.querySelector('[data-list]');
      list.innerHTML='<p class="mi-note">Carpeta de datos: '+escape(state.directory)+'</p>';
      const reasons={automatic:'Automático',manual:'Manual','before-import':'Antes de importar','before-restore':'Antes de restaurar','before-delete':'Antes de eliminar'};
      function appendPage(page) {
        const older=list.querySelector('[data-older]');if(older)older.remove();
        list.insertAdjacentHTML('beforeend',page.backups.map(row=>'<div class="mi-backup-row"><span>'+escape(stamp(row.created_at))+' · '+escape(reasons[row.reason]||row.reason)+'</span><button class="mi-btn" data-restore="'+row.id+'">Restaurar</button><button class="mi-btn" data-download="'+row.id+'">Descargar JSON</button></div>').join(''));
        list.querySelectorAll('[data-restore]').forEach(button=>button.onclick=async()=>{try{await importSnapshot(await localRequest('/local-backups/'+button.dataset.restore),true);}catch(error){alert(error.message);}});
        list.querySelectorAll('[data-download]').forEach(button=>button.onclick=async()=>{try{download(await localRequest('/local-backups/'+button.dataset.download),'MarketIntel-respaldo-'+button.dataset.download+'.json');}catch(error){alert(error.message);}});
        if(page.next_before){
          const button=document.createElement('button');button.className='mi-btn';button.dataset.older='1';button.textContent='Ver copias anteriores';list.appendChild(button);
          button.onclick=async()=>{button.disabled=true;try{appendPage(await localRequest('/local-backups?before='+page.next_before));}catch(error){alert(error.message);button.disabled=false;}};
        }
      }
      appendPage(data);
      if(!data.backups.length)list.insertAdjacentHTML('beforeend','<p>Todavía no hay copias.</p>');
    }catch(error){dialog.querySelector('[data-list]').textContent=error.message;}
  }
  function initBackup() {
    const panel=document.createElement('div');panel.className='mi-backup-tools';
    panel.innerHTML='<span id="mi-backup-status" role="status">Preparando respaldo local…</span><button type="button" class="mi-btn" data-backups>Respaldos</button><button type="button" class="mi-btn" data-backup-now>Guardar ahora</button>';
    (document.getElementById('sec-portafolio')||document.body).appendChild(panel);
    panel.querySelector('[data-backups]').onclick=showBackups;
    panel.querySelector('[data-backup-now]').onclick=()=>save('manual').catch(()=>{});
    save().catch(()=>{});
    setInterval(()=>{if(!document.hidden)save().catch(()=>{});},30000);
    window.addEventListener('online',schedule);
    window.addEventListener('storage',schedule);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
  }

  window.MarketIntelBackup={snapshot,save,schedule,beforeMutation,importFile,importSnapshot,showBackups,allowed,localRequest};

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
      '<details><summary>Seguimiento real desde esta instalación</summary><p>'+(summary?escape(summary.total+' lecturas registradas · '+summary.evaluated+' evaluadas · '+summary.days+' sesiones distintas. ')+(summary.hit_rate==null?'Aún no hay aciertos medibles.':escape(summary.hit_rate+'% de acierto observado en '+summary.directional+' lecturas direccionales. Muestra experimental, no probabilidad futura.')):escape(pulse.evaluation&&pulse.evaluation.error||'Sin historial todavía.'))+'</p><p>'+escape(pulse.evaluation&&pulse.evaluation.method||'No se generan resultados históricos ficticios.')+'</p><button class="mi-btn" data-journal>Exportar seguimiento</button></details>'+
      ((pulse.errors||[]).length?'<p class="mi-data-warning">'+escape(pulse.errors.join(' · '))+'</p>':'')+
      '<p class="mi-pulse-disclaimer">'+escape(pulse.disclaimer)+'</p>';
    host.querySelector('[data-journal]').onclick=async()=>{try{download(await localRequest('/signal-history'),'MarketIntel-seguimiento.json');}catch(error){alert(error.message);}};
  }
  window.MarketIntelPulse={render:renderPulse};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',initBackup);else initBackup();
})();
