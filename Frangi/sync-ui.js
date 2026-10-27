(function () {
  'use strict';
  const origin = 'https://marketintel-nu.vercel.app';
  const $ = id => document.getElementById(id);
  const dialog = $('frangi-sync-dialog');
  const keyBox = $('syncKeyBox');
  const message = $('syncStatus');
  const error = $('syncError');
  let engine, state = {status:'disconnected', connected:false, conflicts:[]}, busy = false;
  let actionError = '';
  const choices = new Map();
  const labels = {disconnected:'Sin sincronizar',idle:'Sincronizado',syncing:'Sincronizando…',
    offline:'Sin conexión · cambios pendientes',pending:'Cambios pendientes',
    conflict:'Hay trades que revisar',error:'No se pudo sincronizar',
    unsupported:'Sincronización no disponible en este navegador'};
  function cleanError(value) {
    return String(value && value.message || value || '').replace(/(?:FR1|MI1)-[A-Za-z0-9_-]+/g,'[clave privada]').slice(0,300);
  }
  function renderSync() {
    $('syncBadge').textContent = labels[state.status] || labels.error;
    message.textContent = state.lastSynced && state.status === 'idle'
      ? 'Sincronizado · ' + new Date(state.lastSynced).toLocaleString('es') : labels[state.status] || labels.error;
    error.textContent = actionError || state.error || '';
    $('syncSetup').hidden = Boolean(state.connected);
    $('syncConnected').hidden = !state.connected;
    $('syncNow').disabled = busy || !state.connected;
    for (const id of ['createSync','linkSync','createWithKey','disconnectSync']) $(id).disabled = busy;
    const conflicts = state.conflicts || [];
    const panel = $('syncConflicts'); panel.hidden = !conflicts.length;
    const list = $('syncConflictList'); list.replaceChildren();
    for (const item of conflicts) {
      const row = document.createElement('div'); row.className = 'sync-conflict-row';
      const title = document.createElement('strong'); title.textContent = item.name;
      const detail = document.createElement('small');
      detail.textContent = 'Aquí: ' + (item.local?.result || 'borrado') + ' · Otro dispositivo: ' + (item.remote?.result || 'borrado');
      const select = document.createElement('select'); select.setAttribute('aria-label','Decisión para '+item.name);
      select.dataset.conflict = item.id;
      [['','Elige qué conservar'],['local','Este dispositivo'],['remote','Otro dispositivo'],['both','Ambos resultados']].forEach(([value,label]) => {
        const option = document.createElement('option'); option.value = value; option.textContent = label; select.appendChild(option);
      });
      select.value = choices.get(item.id) || '';
      select.addEventListener('change', () => choices.set(item.id, select.value));
      row.append(title,detail,select); list.appendChild(row);
    }
  }
  function hideKey() { $('syncKey').value = ''; keyBox.hidden = true; }
  async function showKey() {
    const code = engine.revealCode();
    if (!code) return;
    $('syncKey').value = code; keyBox.hidden = false;
    $('syncKey').focus(); $('syncKey').select();
  }
  async function run(action) {
    if (busy || !engine) return;
    busy = true; actionError = ''; renderSync();
    try { await action(); state = engine.getState(); }
    catch (reason) { actionError = cleanError(reason); }
    finally { busy = false; renderSync(); }
  }
  $('openSync').addEventListener('click', () => { renderSync(); dialog.showModal(); });
  $('closeSync').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { hideKey(); $('syncInput').value = ''; });
  $('hideSyncKey').addEventListener('click', hideKey);
  $('createSync').addEventListener('click', () => run(async () => { await engine.create(); await showKey(); }));
  $('createWithKey').addEventListener('click', () => run(async () => {
    await engine.create($('syncInput').value.trim());
    if (engine.getState().connected) { $('syncInput').value = ''; await showKey(); }
  }));
  $('linkSync').addEventListener('click', () => run(async () => {
    await engine.connect($('syncInput').value.trim());
    if (engine.getState().connected) $('syncInput').value = '';
  }));
  $('syncNow').addEventListener('click', () => run(() => engine.sync()));
  $('showSyncKey').addEventListener('click', () => run(showKey));
  $('copySyncKey').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('syncKey').value); message.textContent = 'Clave copiada.'; }
    catch (_) { $('syncKey').focus(); $('syncKey').select(); message.textContent = 'Clave seleccionada: pulsa Ctrl+C.'; }
  });
  $('disconnectSync').addEventListener('click', () => run(async () => { await engine.disconnect(); hideKey(); }));
  $('resolveSync').addEventListener('click', () => run(async () => {
    const selections = {};
    for (const item of state.conflicts) {
      if (!choices.get(item.id)) throw new Error('Elige qué conservar en cada trade.');
      selections[item.id] = choices.get(item.id);
    }
    await engine.sync(selections);
    if (!engine.getState().conflicts.length) choices.clear();
  }));

  function bridgeFetch() {
    const iframe = document.createElement('iframe');
    iframe.src = origin + '/frangi/bridge.html';
    iframe.hidden = true; iframe.title = 'Conexión cifrada del calendario';
    document.body.appendChild(iframe);
    let loaded = false;
    iframe.addEventListener('load', () => { loaded = true; });
    return async (_url, options) => {
      for (let count = 0; !loaded && count < 100; count++) await new Promise(resolve => setTimeout(resolve,100));
      if (!loaded) throw new Error('No se pudo abrir la conexión con la web. Tus cambios locales siguen guardados.');
      const id = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
      const conditionName = options.method === 'PUT' ? Object.keys(options.headers).find(key => key.startsWith('X-Sync-')) : null;
      const request = {channel:'frangi-sync-v1',id,method:options.method,
        authorization:options.headers.Authorization,
        condition:conditionName ? {name:conditionName,value:options.headers[conditionName]} : null,
        envelope:options.body ? JSON.parse(options.body) : null};
      return new Promise((resolve,reject) => {
        const timer = setTimeout(() => { window.removeEventListener('message', receive); reject(new Error('La conexión tardó demasiado.')); },24000);
        function receive(event) {
          if (event.source !== iframe.contentWindow || event.origin !== origin || !event.data || event.data.channel !== request.channel || event.data.id !== id) return;
          clearTimeout(timer); window.removeEventListener('message', receive);
          resolve(new Response(event.data.body,{status:event.data.status,headers:{'Content-Type':'application/json'}}));
        }
        window.addEventListener('message', receive);
        iframe.contentWindow.postMessage(request,origin);
      });
    };
  }
  window.FrangiSyncOptions = {
    core:window.FrangiSyncCore, recovery:window.FrangiSyncRecovery,
    fetch:location.origin !== origin ? bridgeFetch() : undefined,
    backup: () => localStorage.setItem('frangi_sync_before_restore', JSON.stringify(window.FrangiSyncCore.capture(localStorage))),
    onApplied: snapshot => {
      trades = {};
      for (const [date, values] of Object.entries(snapshot.days)) trades[date] = values;
      render(); renderEditor();
    },
    isEditing: manual => editor.open || (document.activeElement?.matches('input,textarea,select') &&
      document.activeElement.getClientRects().length > 0 && !(manual && dialog.contains(document.activeElement)))
  };
  window.FrangiStartSync = async () => {
    if (hasRemoteStorage()) {
      state = {...state,status:'unsupported',error:'Abre la versión local o web del calendario para sincronizar.'}; renderSync(); return;
    }
    if (!hasLocalStorage() || !window.crypto?.subtle) {
      state = {...state,status:'unsupported',error:'Este navegador no permite guardar o cifrar tus trades.'}; renderSync(); return;
    }
    engine = window.FrangiSyncEngine;
    state = await engine.ready(); engine.subscribe(next => { state = next; renderSync(); });
    renderSync();
  };
  renderSync();
})();
