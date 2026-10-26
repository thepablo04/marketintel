'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/sync-ui.js'),'utf8');
const key='MI1-'+'a'.repeat(43),tick=()=>new Promise(r=>setTimeout(r,0));
async function harness(t){
 const dom=new JSDOM('<!doctype html><button data-tools aria-expanded="true">More</button><div id="mi-tools-menu"><div class="mi-tools-theme"></div></div><section id="sec-portafolio"><div class="mi-backup-tools"></div></section>',{runScripts:'outside-only',url:'https://example.org'});t.after(()=>dom.window.close());
 const w=dom.window;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 let state={status:'disconnected',connected:false,conflicts:[]},listener;const calls=[];
 const publish=s=>{state={...state,...s};listener?.(state)};
 w.MarketIntelSyncEngine={getState:()=>state,ready:async()=>state,subscribe:f=>listener=f,create:async()=>{calls.push('create');publish({status:'idle',connected:true});},connect:async code=>{calls.push(['connect',code]);publish({status:'idle',connected:true});},disconnect:async()=>{calls.push('disconnect');publish({status:'disconnected',connected:false});},revealCode:()=>{calls.push('reveal');return key},sync:async choices=>{calls.push(['sync',choices]);publish({status:'idle',conflicts:[]});}};
 w.eval(source);await tick();return {w,d:w.document,calls,publish};
}
test('both entry points open modal; key only explicit create/reveal and cleared on close',async t=>{
 const {w,d,calls}=await harness(t);assert.equal(d.querySelectorAll('[data-sync-open]').length,2);d.querySelector('[data-sync-open]').click();await tick();assert.equal(d.querySelector('#mi-sync-dialog').open,true);assert.deepEqual(calls,[]);assert.equal(d.querySelector('#mi-sync-private-key').value,'');
 d.querySelector('[data-sync-create]').click();await tick();assert.deepEqual(calls,['create','reveal']);assert.equal(d.querySelector('#mi-sync-private-key').value,key);d.querySelector('[data-sync-close]').click();assert.equal(d.querySelector('#mi-sync-private-key').value,'');assert.equal(d.querySelector('#mi-sync-link-key').value,'');await w.MarketIntelSyncUI.open();assert.equal(d.querySelector('#mi-sync-private-key').value,'');
});
test('link form forwards code, clears it, retains local tools, disconnect never deletes UI data',async t=>{
 const {w,d,calls}=await harness(t);await w.MarketIntelSyncUI.open();d.querySelector('#mi-sync-link-key').value=key;d.querySelector('[data-sync-connect]').click();await tick();assert.equal(calls[0][0],'connect');assert.equal(calls[0][1],key);assert.equal(d.querySelector('#mi-sync-link-key').value,'');assert.ok(d.querySelector('.mi-backup-tools'));d.querySelector('[data-sync-disconnect]').click();await tick();assert.equal(calls.at(-1),'disconnect');assert.equal(d.querySelector('[data-sync-create]').disabled,false);
});
test('conflict choices have no unsafe default; hostile notes render as text and selections survive state refresh',async t=>{
 const {w,d,calls,publish}=await harness(t);await w.MarketIntelSyncUI.open();const conflicts=[{id:'note:note_AAPL',label:'Nota AAPL',local:'<img src=x onerror=alert(1)>',remote:'B'}];publish({status:'conflict',connected:true,conflicts});assert.equal(d.querySelector('[data-sync-resolve]').disabled,true);assert.equal(d.querySelector('.mi-sync-note-preview').textContent,conflicts[0].local);assert.equal(d.querySelector('.mi-sync-conflicts img'),null);const select=d.querySelector('[data-sync-conflict]');select.value='both';select.dispatchEvent(new w.Event('change'));assert.equal(d.querySelector('[data-sync-resolve]').disabled,false);publish({lastSynced:Date.now()});assert.equal(select.value,'both');d.querySelector('[data-sync-resolve]').click();await tick();assert.equal(calls.at(-1)[0],'sync');assert.equal(calls.at(-1)[1]['note:note_AAPL'],'both');
});
test('applied event offers close and refresh without exposing linking key',async t=>{
 const {w,d}=await harness(t);await w.MarketIntelSyncUI.open();w.dispatchEvent(new w.Event('marketintel-sync-applied'));assert.equal(d.querySelector('[data-sync-close]').textContent,'Cerrar y ver cambios');assert.equal(d.querySelector('#mi-sync-private-key').value,'');
});
