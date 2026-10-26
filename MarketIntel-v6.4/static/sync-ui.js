(function () {
  'use strict';

  let engine, state = {status:'disconnected', connected:false}, dialog, elements;
  let busy = false, localError = '', conflictSignature = '', opener, applied = false;
  const selections = new Map();
  const statuses = {
    disconnected:'Sincronización desactivada', idle:'Sincronizado', syncing:'Sincronizando…',
    offline:'Sin conexión · cambios guardados en este dispositivo',
    pending:'Hay cambios pendientes de sincronizar', conflict:'Hay diferencias que revisar',
    error:'No se pudo sincronizar · tus datos locales se conservan',
    unsupported:'La sincronización necesita un navegador actualizado y una conexión segura'
  };
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  function text(item, value) { if (item && item.textContent !== value) item.textContent = value; }
  function button(label, handler, className='mi-btn') {
    const item=node('button',label,className);item.type='button';item.addEventListener('click',handler);return item;
  }
  function controlLabel(label, id) { const item=node('label',label);item.htmlFor=id;return item; }
  function formatDate(value) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString('es-DO', {dateStyle:'short',timeStyle:'short'}) : 'Todavía no se ha completado una sincronización';
  }
  function cleanError(error) {
    // Neither a provider exception nor a badly formed input should echo a key.
    return String(error && error.message || error || 'No se pudo completar la operación.').replace(/MI1-[A-Za-z0-9_-]+/g,'[clave privada]').slice(0,600);
  }
  async function run(action) {
    if (busy) return;
    busy=true;localError='';render();
    try { await action(); }
    catch (error) { localError=cleanError(error); }
    finally { busy=false;if(engine)state=engine.getState();render(); }
  }
  function hideKey() {
    if(!elements)return;
    elements.key.value='';elements.keyBox.hidden=true;text(elements.copyStatus,'');
  }
  async function showKey() {
    const value=await engine.revealCode();
    if(typeof value!=='string'||!/^MI1-[A-Za-z0-9_-]{43}$/.test(value))throw new Error('No se pudo mostrar la clave de este dispositivo.');
    elements.key.value=value;elements.keyBox.hidden=false;elements.key.focus();elements.key.select();
  }
  async function copyKey() {
    const value=elements.key.value;
    if(!value)return;
    try {
      if(!navigator.clipboard||!navigator.clipboard.writeText)throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(value);text(elements.copyStatus,'Clave copiada. Compártela solo con tus propios dispositivos.');
    } catch (_) {
      elements.key.focus();elements.key.select();text(elements.copyStatus,'Seleccionamos la clave. Usa Copiar en tu navegador o Ctrl+C.');
    }
  }
  function makeDialog() {
    dialog=node('dialog',null,'mi-sync-dialog');dialog.id='mi-sync-dialog';
    dialog.setAttribute('aria-labelledby','mi-sync-title');
    const header=node('div',null,'mi-sync-head'),title=node('h2','Tus datos, en tus dispositivos');title.id='mi-sync-title';
    const close=button('Cerrar',()=>dialog.close());close.dataset.syncClose='';header.append(title,close);
    const intro=node('p','Sincroniza tus cuentas y operaciones del portafolio, notas y watchlist entre la versión local y la web. Puedes seguir trabajando sin conexión.');
    const status=node('p',null,'mi-sync-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const last=node('p',null,'mi-sync-muted');
    const error=node('p',null,'mi-sync-error');error.setAttribute('role','alert');error.hidden=true;
    const appliedNotice=node('p','Los datos se actualizaron. Cierra esta ventana para ver los cambios.','mi-sync-muted');appliedNotice.hidden=true;appliedNotice.setAttribute('role','status');
    const disconnected=node('div',null,'mi-sync-setup');
    const createBox=node('section',null,'mi-sync-card');createBox.append(node('h3','Empieza en el dispositivo que ya tiene tus datos'),node('p','Crea una clave privada y úsala una sola vez en cada dispositivo que quieras vincular.'));
    const create=button('Crear mi sincronización',()=>run(async()=>{await engine.create();await showKey();}),'mi-btn-main');create.dataset.syncCreate='';createBox.append(create);
    const connectBox=node('form',null,'mi-sync-card');connectBox.autocomplete='off';connectBox.append(node('h3','¿Ya tienes una clave?'));
    const input=node('input');input.id='mi-sync-link-key';input.type='password';input.autocomplete='off';input.spellcheck=false;input.setAttribute('autocapitalize','none');input.placeholder='MI1-…';input.required=true;input.maxLength=64;
    input.setAttribute('aria-describedby','mi-sync-key-help');
    const inputHelp=node('p','Pega la clave creada en tu otro dispositivo. Tus datos actuales se revisarán antes de combinar versiones incompatibles.','mi-sync-muted');inputHelp.id='mi-sync-key-help';
    const connect=button('Vincular dispositivo',()=>{});connect.type='submit';connect.dataset.syncConnect='';
    connectBox.append(controlLabel('Clave privada de sincronización',input.id),input,inputHelp,connect);
    connectBox.addEventListener('submit',event=>{event.preventDefault();const code=input.value.trim();if(!code){input.focus();return;}run(async()=>{await engine.connect(code);input.value='';});});
    disconnected.append(createBox,connectBox);
    const connected=node('div',null,'mi-sync-connected');
    const connectedActions=node('div',null,'mi-sync-actions');
    const sync=button('Sincronizar ahora',()=>run(()=>engine.sync()),'mi-btn-main');sync.dataset.syncNow='';
    const reveal=button('Mostrar clave para otro dispositivo',()=>run(showKey));reveal.dataset.syncReveal='';
    connectedActions.append(sync,reveal);
    const disconnect=button('Desvincular este dispositivo',()=>run(async()=>{await engine.disconnect();hideKey();}));disconnect.dataset.syncDisconnect='';
    connected.append(connectedActions,node('p','Al desvincular, los datos de este dispositivo se conservan. La copia en la nube sigue disponible con tu clave privada.','mi-sync-muted'),disconnect);
    const keyBox=node('section',null,'mi-sync-card mi-sync-key-box');keyBox.hidden=true;
    const key=node('textarea');key.id='mi-sync-private-key';key.readOnly=true;key.rows=2;key.spellcheck=false;key.setAttribute('autocapitalize','none');key.setAttribute('autocomplete','off');
    const keyActions=node('div',null,'mi-sync-actions');keyActions.append(button('Copiar clave',copyKey),button('Ocultar',hideKey));
    const copyStatus=node('p',null,'mi-sync-muted');copyStatus.setAttribute('role','status');
    keyBox.append(node('h3','Guarda tu clave privada'),node('p','Quien tenga esta clave puede acceder a tus datos sincronizados. Guárdala en un lugar seguro. Si la pierdes y no queda ningún dispositivo vinculado, no podremos recuperarla.'),controlLabel('Tu clave privada',key.id),key,keyActions,copyStatus);
    const conflicts=node('section',null,'mi-sync-conflicts');conflicts.hidden=true;conflicts.setAttribute('aria-labelledby','mi-sync-conflict-title');
    const conflictTitle=node('h3','Revisa los cambios de ambos dispositivos');conflictTitle.id='mi-sync-conflict-title';
    const conflictHelp=node('p','Los dos dispositivos modificaron estos datos. Elige qué conservar en cada caso. Conservar ambas versiones crea otra cuenta o reúne las dos notas.');
    const conflictList=node('div');
    const resolve=button('Guardar las versiones elegidas',()=>run(async()=>{
      const choices={};
      for(const conflict of state.conflicts||[]){const value=selections.get(conflict.id);if(!value)throw new Error('Elige qué conservar en cada diferencia.');choices[conflict.id]=value;}
      await engine.sync(choices);
    }),'mi-btn-main');resolve.dataset.syncResolve='';
    conflicts.append(conflictTitle,conflictHelp,conflictList,resolve);
    const footer=node('p','La copia en la nube está cifrada. Tus claves API, preferencias visuales y respaldos permanecen en cada dispositivo.','mi-sync-muted');
    dialog.append(header,intro,status,last,error,appliedNotice,disconnected,connected,keyBox,conflicts,footer);
    document.body.append(dialog);
    elements={status,last,error,appliedNotice,close,disconnected,connected,keyBox,key,copyStatus,conflicts,conflictList,create,connect,input,sync,reveal,disconnect,resolve};
    dialog.addEventListener('close',()=>{hideKey();input.value='';if(opener&&opener.isConnected)opener.focus();});
  }
  function sidePreview(value,label,isAccount,other) {
    const card=node('div',null,'mi-sync-version');card.append(node('h4',label));
    if(value==null){card.append(node('p','Eliminado o no existe en esta versión.'));return card;}
    if(!isAccount){const note=node('pre',String(value),'mi-sync-note-preview');card.append(note);return card;}
    const profile=value.profile||{},transactions=Array.isArray(value.transactions)?value.transactions:[];
    card.append(node('p',String(profile.name||'Cuenta')+' · '+transactions.length+' operaciones'),node('p','Efectivo inicial: '+Number(profile.openingCash||0).toLocaleString('es-DO')+' '+String(profile.currency||'USD')));
    const others=new Map((other&&Array.isArray(other.transactions)?other.transactions:[]).map(tx=>[tx.id,JSON.stringify(tx)]));
    const changed=transactions.filter(tx=>others.get(tx.id)!==JSON.stringify(tx));
    if(changed.length){
      const details=node('details');details.append(node('summary','Ver '+changed.length+' operaciones diferentes'));
      const list=node('ol',null,'mi-sync-transactions');
      changed.forEach(tx=>{
        const date=new Date(tx.date),when=Number.isFinite(date.getTime())?date.toLocaleDateString('es-DO'):String(tx.date||'');
        const row=node('li');row.append(node('strong',[when,tx.type,tx.ticker].filter(Boolean).join(' · ')));
        row.append(node('span','Cantidad: '+Number(tx.shares||0)+' · Precio: '+Number(tx.price||0)+' · Importe: '+Number(tx.amount||0)+' · Comisión: '+Number(tx.fee||0)));
        if(tx.note)row.append(node('span',String(tx.note)));
        list.append(row);
      });details.append(list);card.append(details);
    } else card.append(node('p','Las operaciones coinciden; revisa los datos de la cuenta.','mi-sync-muted'));
    return card;
  }
  function renderConflicts() {
    const conflicts=Array.isArray(state.conflicts)?state.conflicts:[];
    elements.conflicts.hidden=!conflicts.length;
    const signature=JSON.stringify(conflicts);
    if(signature===conflictSignature)return;
    conflictSignature=signature;selections.clear();elements.conflictList.replaceChildren();
    conflicts.forEach((conflict,index)=>{
      const isAccount=String(conflict.id).startsWith('account:'),item=node('fieldset',null,'mi-sync-conflict');
      const label=conflict.label||(isAccount?'Cuenta: ':'Nota: ')+String(conflict.id).replace(/^[^:]+:/,'');
      item.append(node('legend',label));
      const versions=node('div',null,'mi-sync-versions');versions.append(sidePreview(conflict.local,'Este dispositivo',isAccount,conflict.remote),sidePreview(conflict.remote,'La nube',isAccount,conflict.local));item.append(versions);
      const select=node('select');select.id='mi-sync-choice-'+index;select.dataset.syncConflict=conflict.id;
      [['','Elige qué conservar'],['local','Versión de este dispositivo'],['remote','Versión de la nube'],['both','Conservar ambas versiones']].forEach(([value,label])=>{const option=node('option',label);option.value=value;select.append(option);});
      select.addEventListener('change',()=>{selections.set(conflict.id,select.value);updateButtons();});
      item.append(controlLabel('Conservar',select.id),select);elements.conflictList.append(item);
    });
  }
  function updateButtons() {
    if(!elements)return;
    const working=busy||state.status==='syncing',unsupported=state.status==='unsupported';
    [elements.create,elements.connect,elements.sync,elements.reveal].forEach(item=>item.disabled=working||unsupported);
    elements.disconnect.disabled=working;
    elements.input.disabled=working||unsupported;
    const conflicts=state.conflicts||[];
    elements.resolve.disabled=working||!conflicts.length||conflicts.some(item=>!selections.get(item.id));
    elements.conflictList.querySelectorAll('select').forEach(item=>item.disabled=working);
  }
  function render() {
    const label=statuses[state.status]||(state.connected?'Sincronización vinculada':'Sincronización desactivada');
    document.querySelectorAll('[data-sync-status]').forEach(item=>text(item,label));
    if(!elements)return;
    text(elements.status,label);elements.status.dataset.status=state.status;
    elements.appliedNotice.hidden=!applied;text(elements.close,applied?'Cerrar y ver cambios':'Cerrar');
    text(elements.last,state.lastSynced?'Última sincronización: '+formatDate(state.lastSynced):'');elements.last.hidden=!state.lastSynced;
    const message=localError||(state.error?cleanError(state.error):'');text(elements.error,message);elements.error.hidden=!message;
    elements.disconnected.hidden=!!state.connected;elements.connected.hidden=!state.connected;
    if(!state.connected)hideKey();
    renderConflicts();updateButtons();
  }
  async function open() {
    opener=document.activeElement;
    if(!dialog)makeDialog();
    if(!dialog.open)dialog.showModal();
    render();dialog.querySelector('[data-sync-close]').focus();
    if(!engine){localError='No se pudo cargar la sincronización. Recarga la página.';render();return;}
    try {await engine.ready();state=engine.getState();render();}
    catch(error){localError=cleanError(error);render();}
  }
  function init() {
    engine=window.MarketIntelSyncEngine;
    window.addEventListener('marketintel-sync-applied',()=>{applied=true;render();});
    const tools=document.getElementById('mi-tools-menu');
    if(tools){
      const item=button('Sincronizar dispositivos',()=>{tools.hidden=true;const toggle=document.querySelector('[data-tools]');if(toggle){toggle.setAttribute('aria-expanded','false');toggle.classList.remove('active');}open();});
      item.dataset.syncOpen='';tools.insertBefore(item,tools.querySelector('.mi-tools-theme'));
    }
    const host=document.querySelector('.mi-backup-tools')||document.getElementById('sec-portafolio');
    if(host){
      const toolbar=node('div',null,'mi-sync-toolbar');toolbar.id='mi-sync-toolbar';
      const copy=node('div');copy.append(node('strong','Sincronización entre dispositivos'));const status=node('span',null,'mi-sync-muted');status.dataset.syncStatus='';copy.append(status);
      const configure=button('Configurar sincronización',open);configure.dataset.syncOpen='';toolbar.append(copy,configure);
      if(host.classList.contains('mi-backup-tools'))host.insertAdjacentElement('beforebegin',toolbar);else host.append(toolbar);
    }
    window.MarketIntelSyncUI={open};
    if(engine){state=engine.getState();engine.subscribe(next=>{state=next;render();});Promise.resolve(engine.ready()).then(()=>{state=engine.getState();render();}).catch(error=>{localError=cleanError(error);render();});}
    render();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
