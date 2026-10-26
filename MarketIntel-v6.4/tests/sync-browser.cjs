// Two-device integration with real Chromium, app scripts, WebCrypto and Web Locks.
// Providers and the encrypted cloud transport are controlled fixtures. No user
// accounts, production data or external credentials are used by this test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const chart = path.join(path.dirname(require.resolve('chart.js')), 'chart.umd.js');
const localOrigin = 'http://localhost:5050';
const webOrigin = 'https://marketintel.test';
const date = '2026-10-01';
const timestamp = '2026-10-02T15:00:00Z';
const history = {dates:['2026-09-28','2026-09-29','2026-09-30','2026-10-01'],prices:[100,102,101,103]};
const snapshots = new Map();
const received = [];
let sequence = 0;
const pulse = {version:'6.2',session:{label:'Sesión de prueba',date,is_open:false,calendar_verified:true},updated_at:timestamp,
  intraday:{score:null,label:'Sin lectura intradía',quality:0,coverage:0,components:[],reason:'Prueba de sincronización.',status:'unavailable'},
  context:{label:'Mixto',score:50,last_history_date:date,components:[]},quotes:{},errors:[],
  evaluation:{storage:'browser',model:'intraday-v6.1',completed_closes:{},summary:{total:0,evaluated:0,days:0,hit_rate:null}},disclaimer:'Datos sintéticos.'};
function stock(ticker) { return {ticker,name:ticker+' de prueba',price:103,change:1,change_pct:1,market_cap:1e12,
  sector:'Technology',industry:'Software',pe:25,eps:8,book_value:20,revenue_ttm:8e10,shares_outstanding:1e9,
  profit_margin:20,beta:1,analyst_target:120,data_date:date,spark_prices:history.prices,currency:'USD'}; }
function json(route, data, status=200, headers={}) {return route.fulfill({status,json:data,headers});}

async function installRoutes(context, origin, control) {
  const localBackups = [];
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.pathname.startsWith('/sync/')){
      const headers={'Access-Control-Allow-Origin':origin,'Access-Control-Allow-Methods':'GET, PUT, OPTIONS',
        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Sync-If-Match, X-Sync-If-None-Match','Cache-Control':'no-store'};
      if(request.method()==='OPTIONS')return route.fulfill({status:204,headers});
      if(control.offline)return json(route,{code:'unavailable',error:'Sin conexión de prueba.'},503,headers);
      if(url.pathname==='/sync/status')return json(route,{available:true,version:1,max_plaintext_bytes:2097152},200,headers);
      assert.equal(url.pathname,'/sync/data');
      const token=request.headers().authorization;
      assert.match(token||'',/^Bearer [A-Za-z0-9_-]{43}$/,'Transport uses a derived authentication capability');
      const prior=snapshots.get(token);
      if(request.method()==='GET')return prior?json(route,prior,200,headers):json(route,{code:'not_found',error:'No existe copia.'},404,headers);
      assert.equal(request.method(),'PUT');
      const envelope=request.postDataJSON();
      assert.deepEqual(Object.keys(envelope).sort(),['ciphertext','iv','version']);
      assert.equal(envelope.version,1);assert.match(envelope.iv,/^[A-Za-z0-9_-]{16}$/);
      assert.equal(Buffer.from(envelope.iv,'base64url').length,12);
      if(prior?request.headers()['x-sync-if-match']!==prior.revision:request.headers()['x-sync-if-none-match']!=='*')
        return json(route,{code:'conflict',error:'Otro dispositivo guardó cambios.'},409,headers);
      const revision='"fixture-'+(++sequence)+'"';
      snapshots.set(token,{envelope,revision});received.push(JSON.stringify(envelope));
      return json(route,{revision},200,headers);
    }
    if(url.hostname==='cdnjs.cloudflare.com'&&/chart/i.test(url.pathname))return route.fulfill({path:chart,contentType:'text/javascript'});
    if(url.hostname==='fonts.googleapis.com')return route.fulfill({body:'',contentType:'text/css'});
    if(url.origin!==origin)return route.abort('blockedbyclient');
    if(url.pathname==='/')return route.fulfill({path:path.join(root,'index.html'),contentType:'text/html'});
    if(url.pathname.startsWith('/static/')){
      const file=path.resolve(root,'.'+url.pathname);
      assert(file.startsWith(path.join(root,'static')+path.sep));
      return route.fulfill({path:file,contentType:file.endsWith('.css')?'text/css':'text/javascript'});
    }
    if(url.pathname==='/health')return json(route,{status:'ok',service:'MarketIntel',version:'6.4.4'});
    if(url.pathname==='/batch')return json(route,Object.fromEntries((request.postDataJSON()?.tickers||[]).map(t=>[t,stock(t)])));
    if(url.pathname.startsWith('/stock/'))return json(route,stock(decodeURIComponent(url.pathname.slice(7))));
    if(url.pathname.startsWith('/history/'))return json(route,history);
    if(url.pathname.startsWith('/fundamentals/'))return json(route,{eps:[],revenue:[],quarterly_revenue:[],margins:[],pe_history:[]});
    if(url.pathname.startsWith('/financials/'))return json(route,{annual:[],quarterly:[]});
    if(url.pathname==='/macro')return json(route,{status:'ok',configured:true,series:{},updated_at:timestamp});
    if(url.pathname==='/news')return json(route,{status:'ok',articles:[],updated_at:timestamp});
    if(url.pathname==='/market-sentiment')return json(route,pulse);
    if(url.pathname==='/local-state')return json(route,{token:'fixture-local-backup-token',version:'6.4.4'});
    if(url.pathname==='/local-backups'&&request.method()==='POST'){
      const value=request.postDataJSON(),row={id:localBackups.length+1,created_at:timestamp,...value};localBackups.push(row);
      return json(route,{id:row.id,created_at:timestamp});
    }
    if(url.pathname==='/local-backups')return json(route,{backups:localBackups});
    if(url.pathname==='/signal-history')return json(route,{observations:[],summary:{total:0,evaluated:0,days:0,hit_rate:null}});
    return json(route,{error:'Unhandled test route '+url.pathname},404);
  });
  return localBackups;
}
async function seed(context, populated) {
  await context.addInitScript(({populated,date})=>{
    // Deterministic manual runs; the production scheduler has separate unit tests.
    window.MarketIntelSyncOptions={autoStart:false};
    if(localStorage.getItem('sync_fixture_seeded'))return;
    const values={sync_fixture_seeded:'1',mi_onboarded:'1',theme_mode:'dark',
      mi_api_key:'secret-fixture-never-synced',hm_custom:'{"sectors":{"Solo local":["MSFT"]}}'};
    if(populated)Object.assign(values,{
      watchlist:'["AAPL"]',note_AAPL:'Tesis inicial privada',ficha_note_AAPL:'Ficha inicial privada',
      pf_portfolios:JSON.stringify([{id:'fixture',name:'Cuenta privada de prueba',type:'Paper',openingCash:10000,currency:'USD',ledgerVersion:3}]),
      pf_active_id:'fixture',pf_transactions_fixture:JSON.stringify([{id:'buy-initial',date,type:'Compra',ticker:'MSFT',shares:2,price:100,fee:0}])});
    for(const [key,value] of Object.entries(values))localStorage.setItem(key,value);
  },{populated,date});
}
async function ready(page) {
  await page.waitForFunction(()=>window.MarketIntelSyncEngine&&window.MarketIntelSyncUI&&window.MarketIntelSyncCore);
  await page.evaluate(()=>window.MarketIntelSyncEngine.ready());
}
async function openSync(page) {
  await page.evaluate(()=>window.MarketIntelSyncUI.open());
  await page.locator('#mi-sync-dialog').waitFor({state:'visible'});
}
async function closeSync(page) {
  const close=page.locator('#mi-sync-dialog[open] [data-sync-close]');
  if(await close.count())await close.click();
}
async function state(page) {return page.evaluate(()=>window.MarketIntelSyncEngine.getState());}
async function snapshot(page) {return page.evaluate(()=>window.MarketIntelSyncCore.capture(localStorage));}
async function sync(page,choices) {
  await closeSync(page);
  try {await page.evaluate(choices=>window.MarketIntelSyncEngine.sync(choices),choices);}
  catch(error){if(!/Execution context was destroyed|navigation/.test(error.message))throw error;}
  await ready(page);
  await page.waitForFunction(()=>window.MarketIntelSyncEngine.getState().status!=='syncing');
}
async function editNote(page,value) {
  await closeSync(page);
  await page.evaluate(()=>go('screener'));
  await page.locator('#ticker-input').fill('AAPL');await page.locator('#ticker-input').press('Enter');
  await page.locator('#screener-results').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.getElementById('screener-results').classList.contains('mi-data-loading'));
  await page.locator('#stock-notes').fill(value);await page.locator('#stock-notes').press('Tab');
  await page.locator('#sec-screener').click({position:{x:8,y:8}});
  assert.equal(await page.evaluate(()=>localStorage.note_AAPL),value);
}
async function addWatchlist(page,ticker) {
  await closeSync(page);await page.evaluate(()=>go('watchlist'));
  await page.locator('#wl-input').fill(ticker);await page.locator('#wl-input').press('Enter');
  await page.locator('#wl-card-'+ticker).waitFor({state:'visible'});
  await page.locator('#sec-watchlist').click({position:{x:8,y:8}});
}
async function addTrade(page) {
  await page.evaluate(()=>go('portafolio'));
  await page.locator('#sec-portafolio button[onclick="pfOpenAddModal()"]:visible').first().click();
  await page.locator('#pf-in-operation').selectOption({label:'Compra'});
  await page.locator('#pf-in-ticker').fill('AAPL');await page.locator('#pf-in-shares').fill('3');
  await page.locator('#pf-in-cost').fill('100');await page.locator('#pf-in-date').fill('2026-10-02');
  await page.locator('#pf-modal-overlay button[onclick="pfAddPosition()"]').click();
  await page.locator('#pf-modal-overlay').waitFor({state:'hidden'});
  await page.locator('#sec-portafolio').click({position:{x:8,y:8}});
}

(async()=>{
  const browser=await chromium.launch({executablePath:process.env.MARKETINTEL_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
  const errors=[];
  try {
    const contexts=[],pages=[],controls=[];
    for(const [origin,populated] of [[localOrigin,true],[webOrigin,false]]){
      const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
      const control={offline:false};await seed(context,populated);await installRoutes(context,origin,control);
      const page=await context.newPage();page.setDefaultTimeout(15000);
      page.on('pageerror',error=>errors.push(error.message));
      page.on('dialog',async dialog=>{errors.push(dialog.message());await dialog.dismiss();});
      await page.goto(origin,{waitUntil:'networkidle'});await ready(page);
      contexts.push(context);pages.push(page);controls.push(control);
    }
    const [local,web]=pages;
    assert.equal(snapshots.size,0,'An unlinked browser never uploads personal data');
    const original=await snapshot(local);
    await openSync(local);await local.locator('[data-sync-create]').click();
    await local.waitForFunction(()=>window.MarketIntelSyncEngine.getState().connected&&window.MarketIntelSyncEngine.getState().status!=='syncing');
    await local.locator('#mi-sync-private-key').waitFor({state:'visible'});
    const code=await local.locator('#mi-sync-private-key').inputValue();assert.match(code,/^MI1-[A-Za-z0-9_-]{43}$/);
    assert.equal(snapshots.size,1);await closeSync(local);
    await openSync(web);await web.locator('#mi-sync-link-key').fill(code);await web.locator('[data-sync-connect]').click();
    await web.waitForFunction(()=>window.MarketIntelSyncEngine?.getState().connected);
    await closeSync(web);await ready(web);
    await web.waitForFunction(()=>localStorage.note_AAPL==='Tesis inicial privada');
    assert.deepEqual(await snapshot(web),original,'First link imports portfolio, transaction ledger, notes and watchlist');
    assert.equal(await web.evaluate(()=>localStorage.getItem('pf_positions_default')),null,'Import cannot leave positions that resurrect a discarded default account');

    await addWatchlist(web,'NVDA');await addTrade(web);await sync(web);await sync(local);
    await local.waitForFunction(()=>JSON.parse(localStorage.watchlist||'[]').includes('NVDA'));
    assert.equal((await snapshot(local)).accounts.fixture.transactions.filter(tx=>tx.ticker==='AAPL').length,1,'A trade created in web reaches the local portfolio');
    assert.deepEqual(await snapshot(local),await snapshot(web));

    controls[0].offline=true;
    await editNote(local,'Edición local guardada sin conexión');await sync(local);
    assert((await state(local)).pending,'Offline edits remain pending');
    assert.equal(await local.evaluate(()=>localStorage.note_AAPL),'Edición local guardada sin conexión');
    await local.reload({waitUntil:'networkidle'});await ready(local);
    assert.equal(await local.evaluate(()=>localStorage.note_AAPL),'Edición local guardada sin conexión','Offline edits survive reload');
    controls[0].offline=false;await sync(local);await sync(web);
    await web.waitForFunction(()=>localStorage.note_AAPL==='Edición local guardada sin conexión');

    controls[0].offline=true;controls[1].offline=true;
    await editNote(local,'Versión del PC que hay que conservar');await editNote(web,'Versión del móvil que hay que conservar');
    controls[0].offline=false;await sync(local);controls[1].offline=false;await sync(web);
    assert.equal((await state(web)).status,'conflict','Incompatible edits require review');
    assert.equal(await web.evaluate(()=>localStorage.note_AAPL),'Versión del móvil que hay que conservar','Conflict does not silently replace local data');
    await openSync(web);await web.locator('select[data-sync-conflict="note:note_AAPL"]').selectOption('both');
    await web.locator('[data-sync-resolve]').click();
    await web.waitForFunction(()=>window.MarketIntelSyncEngine?.getState().status!=='conflict'&&window.MarketIntelSyncEngine?.getState().status!=='syncing');
    await closeSync(web);await ready(web);await sync(local);
    const combined=await local.evaluate(()=>localStorage.note_AAPL);
    assert.match(combined,/Versión del PC/);assert.match(combined,/Versión del móvil/);
    assert.deepEqual(await snapshot(local),await snapshot(web));
    for(const page of pages){
      const backup=await page.evaluate(()=>window.MarketIntelBackup.snapshot());
      assert(!Object.keys(backup.localStorage).some(key=>key.startsWith('marketintel_sync_')),'Backup exports must exclude linking credentials and sync metadata');
      assert(!JSON.stringify(backup).includes(code),'Private linking key never appears in backup export');
    }
    assert(received.every(body=>!body.includes('Tesis inicial')&&!body.includes('Cuenta privada')&&!body.includes('secret-fixture')&&!body.includes(code)),
      'Cloud request bodies contain ciphertext, never financial text or credentials');
    const extra=await contexts[1].newPage();
    await extra.goto(webOrigin,{waitUntil:'networkidle'});await ready(extra);
    await editNote(local,'Cambio que espera a cerrar otra pestaña');await sync(local);await sync(web);
    assert.equal((await state(web)).status,'pending');
    assert.match((await state(web)).error,/otras pestañas/);
    assert.equal(await web.evaluate(()=>localStorage.note_AAPL),combined,'A stale open tab cannot overwrite newly received data');
    await extra.close();await sync(web);
    assert.equal(await web.evaluate(()=>localStorage.note_AAPL),'Cambio que espera a cerrar otra pestaña');
    await web.evaluate(()=>{go('portafolio');pfOpenAddModal();});
    await web.locator('#pf-in-ticker').fill('MSFT');
    await editNote(local,combined);await sync(local);
    await web.evaluate(()=>MarketIntelSyncEngine.sync());
    assert.equal((await state(web)).status,'pending');
    assert.equal(await web.locator('#pf-in-ticker').inputValue(),'MSFT','A remote apply cannot interrupt an open trade form');
    await web.evaluate(()=>pfCloseAddModal());await sync(web);
    assert.equal(await web.evaluate(()=>localStorage.note_AAPL),combined);
    await web.setViewportSize({width:320,height:780});await openSync(web);
    for(const theme of ['dark','light']){
      await web.evaluate(theme=>document.documentElement.classList.toggle('light-theme',theme==='light'),theme);
      const dimensions=await web.locator('#mi-sync-dialog').evaluate(el=>({width:el.getBoundingClientRect().width,scroll:el.scrollWidth,client:el.clientWidth,viewport:innerWidth}));
      assert(dimensions.width<=dimensions.viewport&&dimensions.scroll<=dimensions.client+2,'Mobile '+theme+' sync dialog must fit the viewport');
    }
    await web.locator('[data-sync-disconnect]').click();
    await web.waitForFunction(()=>!window.MarketIntelSyncEngine.getState().connected);
    assert.equal(await web.evaluate(()=>localStorage.note_AAPL),combined,'Disconnect preserves local data');
    assert.deepEqual(errors,[],'No uncaught browser exceptions or unexpected alerts');
    console.log(JSON.stringify({browser:'Chromium',result:'passed',devices:2,
      checks:['opt-in encryption','local-to-web initial link','web-to-local watchlist and trade','offline persistence and recovery','note conflict review and keep both','secret exclusion','multiple-tab guard','unfinished form guard','mobile 320px dark/light','disconnect retains data']},null,2));
    await Promise.all(contexts.map(context=>context.close()));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
