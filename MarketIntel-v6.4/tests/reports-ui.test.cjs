'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(path.join(__dirname,'../static/marketintel-reports.js'),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,0));
const pdf=Buffer.from('%PDF-1.4\nfixture\n%%EOF').toString('base64');
function sample(extra={}){return {kind:'closing',status:'partial',session_date:'2026-11-16',generated_at:'2026-11-16T22:01:00Z',cutoff_at:'2026-11-16T22:00:00Z',summary:['Los índices avanzaron; la cobertura es parcial.'],quotes:[{label:'S&P 500',price:6000,change:10,change_pct:0.16,unit:'pts',as_of:'2026-11-16T21:00:00Z',source:'Proveedor'}],breadth:[{label:'S&P 500',up:70,down:20,unchanged:10,missing:403,total:503,valid:100}],magnificent_seven:[{ticker:'NVDA',previous:100,price:102,change:2,change_pct:2}],macro:[],watchlist_reports:[{ticker:'NVDA',title:'Resultado pendiente',status:'pending',summary:'Pendiente al corte.'}],warnings:['Faltan cotizaciones verificables.'],...extra};}
async function setup(t,options={}){
 const dom=new JSDOM('<!doctype html><section id="sec-home"><div class="mi-home-head"><div class="mi-actions"><button id="original">Posición</button></div></div></section>',{runScripts:'outside-only',url:'https://marketintel.example'});t.after(()=>dom.window.close());
 const w=dom.window,calls=[],downloads=[],urls=[],revoked=[];
 w.URL.createObjectURL=blob=>{urls.push(blob);return 'blob:fixture-'+urls.length};w.URL.revokeObjectURL=url=>revoked.push(url);
 w.HTMLAnchorElement.prototype.click=function(){downloads.push({href:this.href,filename:this.download});};
 w.localStorage.setItem('watchlist',options.watchlist??JSON.stringify(['NVDA','AAPL','MSFT','AMZN','META','TSLA','GOOGL']));
 w.localStorage.setItem('marketbot_apikey','existing-private-configuration');
 w.fetch=async(url,settings)=>{calls.push({url,settings});return options.fetch?options.fetch(url,settings):{ok:true,json:async()=>({report:sample(),pdf_base64:pdf,filename:'MarketIntel-cierre.pdf'})};};
 w.eval(source);await tick();return {w,d:w.document,calls,downloads,urls,revoked};
}
test('entrypoints preserve actions and remount once when app rebuilds Home',async t=>{
 const {w,d}=await setup(t);assert.equal(d.querySelectorAll('[data-report-kind]').length,2);assert(d.querySelector('#original'));
 d.querySelector('#sec-home').innerHTML='<div class="mi-home-head"><div class="mi-actions"><button id="new-original">Nueva posición</button></div></div>';
 await tick();assert.equal(d.querySelectorAll('[data-report-kind]').length,2);assert(d.querySelector('#new-original'));w.MarketIntelReports.mount();assert.equal(d.querySelectorAll('.mi-report-entrypoints').length,1);
});
test('full watchlist is sent and same returned PDF downloads without another query',async t=>{
 const {w,d,calls,downloads,urls}=await setup(t);await w.MarketIntelReports.open('closing');assert.equal(calls[0].url,'/reports/closing');assert.equal(JSON.parse(calls[0].settings.body).watchlist.length,7);assert.equal(calls[0].settings.headers['Content-Type'],'application/json');
 assert.equal(d.querySelector('.mi-report-primary').disabled,false);assert.match(d.querySelector('#mi-report-body').textContent,/100 de 503/);assert.match(d.querySelector('#mi-report-body').textContent,/Pendiente al corte/);
 d.querySelector('.mi-report-primary').click();assert.equal(calls.length,1);assert.equal(downloads.length,1);assert.equal(downloads[0].filename,'MarketIntel-cierre.pdf');assert.equal(urls.length,1);assert.equal(w.localStorage.getItem('marketbot_apikey'),'existing-private-configuration');
});
test('empty and damaged watchlists never become demo tickers or change storage',async t=>{
 for(const input of ['[]','{"invalid":true}','bad json']){
  const local=await setup(t,{watchlist:input});await local.w.MarketIntelReports.open('closing');assert.deepEqual(JSON.parse(local.calls[0].settings.body).watchlist,[]);assert.equal(local.w.localStorage.getItem('watchlist'),input);if(input!=='[]')assert.match(local.d.querySelector('#mi-report-body').textContent,/No se pudo leer la watchlist/);
 }
});
test('server cutoff error leaves PDF disabled and permits retry',async t=>{
 const {w,d,calls}=await setup(t,{fetch:async()=>({ok:false,json:async()=>({error:'El reporte de sesión está disponible desde las 17:00 NY.'})})});
 await w.MarketIntelReports.open('closing');assert.equal(d.querySelector('.mi-report-primary').disabled,true);assert.match(d.querySelector('#mi-report-status').textContent,/17:00 NY/);assert.equal(d.querySelector('.mi-report-secondary').disabled,false);d.querySelector('.mi-report-secondary').click();await tick();assert.equal(calls.length,2);
});
test('provider strings and source links cannot inject HTML or script URLs',async t=>{
 const hostile='<img src=x onerror="window.reportXSS=true">';
 const {w,d}=await setup(t,{fetch:async()=>({ok:true,json:async()=>({report:sample({summary:[hostile],quotes:[{label:hostile,price:1,source:hostile,source_url:'javascript:window.reportXSS=true'}],watchlist_reports:[{ticker:'NVDA',title:hostile,status:'pending',summary:hostile}]}),pdf_base64:pdf,filename:'../../private.pdf'})})});
 await w.MarketIntelReports.open('closing');assert.equal(d.querySelectorAll('#mi-report-body img,#mi-report-body script,#mi-report-body a[href^="javascript:"]').length,0);assert.equal(w.reportXSS,undefined);assert(d.querySelector('#mi-report-body').textContent.includes(hostile));
});
test('missing numeric data stays absent, and a non-PDF payload cannot download',async t=>{
 const {w,d}=await setup(t,{fetch:async()=>({ok:true,json:async()=>({report:sample({quotes:[{label:'Sin cotización',price:null,change:null,change_pct:null}],breadth:[{label:'Nasdaq 100',up:null,down:null,unchanged:null,missing:null,total:null,valid:null}]}),pdf_base64:Buffer.from('not pdf').toString('base64')})})});
 await w.MarketIntelReports.open('opening');assert.equal(d.querySelector('.mi-report-primary').disabled,true);assert.match(d.querySelector('#mi-report-status').textContent,/formato PDF/);assert.match(d.querySelector('.mi-report-quote strong').textContent,/Sin dato/);assert.match(d.querySelector('#mi-report-body').textContent,/Cobertura no verificada/);
});
test('watchlist preview keeps post-close price separate and includes its observation time',async t=>{
 const {w,d}=await setup(t,{fetch:async()=>({ok:true,json:async()=>({report:sample({watchlist_reports:[{ticker:'NVDA',title:'Resultados',status:'published',summary:'Titular verificado.',price:183.6,post_price:191,post_change_pct:4.03,post_as_of:'2026-11-16T21:58:00Z',published_at:'2026-11-16T21:20:00Z'}]}),pdf_base64:pdf})})});
 await w.MarketIntelReports.open('closing');const preview=d.querySelector('#mi-report-body').textContent;assert.match(preview,/Precio posterior/);assert.match(preview,/183,6/);assert.match(preview,/191/);assert.match(preview,/\+7,4/);assert.match(preview,/4,03%/);assert.match(preview,/16:58/);assert.match(preview,/no garantiza el precio/);
});
test('macro reaction shows both index levels, point changes and the verified observation window',async t=>{
 const {w,d}=await setup(t,{fetch:async()=>({ok:true,json:async()=>({report:sample({kind:'opening',macro:[{title:'CPI',actual:'0,2%',consensus:'0,3%',previous:'0,3%',explanation:'Los precios siguen aumentando.',published_at:'2026-11-16T13:30:00Z',market_reaction:[{label:'S&P 500 · futuro ES',before:5997,price:6025,change:28,unit:'pts',before_at:'2026-11-16T13:25:00Z',as_of:'2026-11-16T13:45:00Z',source:'Proveedor'},{label:'Nasdaq 100 · futuro NQ',before:21420,price:21560,change:140,unit:'pts',before_at:'2026-11-16T13:25:00Z',as_of:'2026-11-16T13:45:00Z'}],market_reaction_note:'La comparación temporal no prueba una causa única.'}]}),pdf_base64:pdf})})});
 await w.MarketIntelReports.open('opening');const preview=d.querySelector('#mi-report-body').textContent;assert.match(preview,/Qué cambió en el mercado/);assert.match(preview,/5\.?997/);assert.match(preview,/6\.?025/);assert.match(preview,/\+28 pts/);assert.match(preview,/\+140 pts/);assert.match(preview,/8:25/);assert.match(preview,/8:45/);assert.match(preview,/no prueba una causa única/);
});
test('closing pending request aborts it and prevents a stale response from reopening the PDF',async t=>{
 let resolve;
 const {w,d,calls}=await setup(t,{fetch:async()=>new Promise(r=>resolve=r)});
 const request=w.MarketIntelReports.open('opening');await tick();assert.equal(d.querySelector('.mi-report-dialog').getAttribute('aria-busy'),'true');
 w.MarketIntelReports.close();assert.equal(calls[0].settings.signal.aborted,true);resolve({ok:true,json:async()=>({report:sample(),pdf_base64:pdf})});await request;assert.equal(d.querySelector('#mi-report-overlay').hidden,true);assert.equal(d.querySelector('.mi-report-primary').disabled,true);
});
test('Escape closes and restores focus to entrypoint',async t=>{
 const {w,d}=await setup(t);const button=d.querySelector('[data-report-kind="opening"]');button.focus();await w.MarketIntelReports.open('opening');assert.equal(d.activeElement.getAttribute('aria-label'),'Cerrar reporte');d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(d.querySelector('#mi-report-overlay').hidden,true);assert.equal(d.activeElement,button);
});
