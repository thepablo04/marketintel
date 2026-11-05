// Real Chromium integration with the app HTML and controlled provider responses.
// NODE_PATH needs playwright and chart.js; no server or production API is used.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const chart = path.join(path.dirname(require.resolve('chart.js')), 'chart.umd.js');
const origin = 'http://localhost:5050';
const stamp = new Date().toISOString();
const today = stamp.slice(0, 10);
function month(offset) {
  const date = new Date();
  return new Date(Date.UTC(date.getFullYear(), date.getMonth() + offset, 1)).toISOString().slice(0, 10);
}
const before = month(-3), first = month(-2), latest = month(-1);
function seriesItem(id, value, previous, unit='percent_yoy', period=first) {
  const older = period === latest ? first : before;
  return {id, label:id, status:'ok', context_usable:true, source:'FRED fixture',
    source_url:'https://fred.stlouisfed.org/series/'+id, release_url:'https://www.bls.gov/news.release/empsit.htm',
    date:period, period, frequency:'monthly', fetched_at:stamp, published_at:null,
    publication_date_status:'not_supplied', value, display_value:value, display_unit:unit,
    previous:{date:older, display_value:previous, display_unit:unit},
    history:[{date:older,value:previous,display_value:previous,display_unit:unit},
      {date:period,value,display_value:value,display_unit:unit}]};
}
function macro(period=first, jobs=123, previousJobs=181) {
  return {status:'ok',configured:true,updated_at:stamp,series:{
    fed_upper:seriesItem('DFEDTARU',4,4.25,'percent',period),fed_lower:seriesItem('DFEDTARL',3.75,4,'percent',period),
    cpi:seriesItem('CPIAUCNS',3.2,3.4,'percent_yoy',period),core_cpi:seriesItem('CPILFENS',3.3,3.4,'percent_yoy',period),
    core_pce:seriesItem('PCEPILFE',2.8,2.9,'percent_yoy',period),pce:seriesItem('PCEPI',2.7,2.8,'percent_yoy',period),
    payrolls:seriesItem('PAYEMS',jobs,previousJobs,'change_thousands',period),unemployment:seriesItem('UNRATE',4.2,4.1,'percent',period),
    wages:seriesItem('CES0500000003',3.8,3.9,'percent_yoy',period),gdp:seriesItem('GDPC1',2.1,2.4,'percent_yoy',period),
    pmi:seriesItem('ISM-PMI',49,51,'index',period),services_pmi:seriesItem('ISM-SERVICES-PMI',52,53,'index',period),
    consumer_sentiment:seriesItem('UMCSENT',60,62,'index',period),treasury_10y:seriesItem('DGS10',4.1,4.2,'percent',period),
    retail_sales:seriesItem('RSAFS',0.4,0.3,'percent_mom',period),jolts:seriesItem('JTSJOL',7200,7400,'thousands',period),
    initial_claims:seriesItem('ICSA',240000,235000,'persons',period),
  }};
}
const pulse={version:'6.2',session:{label:'Sesión de prueba',date:today,is_open:false,calendar_verified:true},updated_at:stamp,
  intraday:{score:null,label:'Sin lectura intradía',quality:0,coverage:0,components:[],reason:'Fixture',status:'unavailable'},
  context:{label:'Mixto',score:50,last_history_date:today,components:[]},quotes:{},errors:[],
  evaluation:{storage:'browser',model:'intraday-v6.1',completed_closes:{},summary:{total:0,evaluated:0,days:0,hit_rate:null}}};
async function install(context,control) {
  await context.addInitScript(()=>{
    window.MarketIntelSyncOptions={autoStart:false};
    localStorage.setItem('mi_onboarded','1');
    localStorage.setItem('marketbot_apikey','macro-fixture-private-key');
    localStorage.setItem('pf_portfolios',JSON.stringify([{id:'macro_fixture',name:'Cuenta conservada',type:'Paper',openingCash:10000,currency:'USD',ledgerVersion:3}]));
    localStorage.setItem('pf_active_id','macro_fixture');
    localStorage.setItem('pf_transactions_macro_fixture',JSON.stringify([{id:'buy',date:'2026-01-02',type:'Compra',ticker:'MSFT',shares:2,price:100,fee:0}]));
  });
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.hostname==='cdnjs.cloudflare.com'&&/chart/i.test(url.pathname))return route.fulfill({path:chart,contentType:'text/javascript'});
    if(url.hostname==='fonts.googleapis.com')return route.fulfill({body:'',contentType:'text/css'});
    if(url.origin!==origin)return route.abort('blockedbyclient');
    if(url.pathname==='/')return route.fulfill({path:path.join(root,'index.html'),contentType:'text/html'});
    if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.join(root,url.pathname),contentType:url.pathname.endsWith('.css')?'text/css':'text/javascript'});
    let data={};
    if(url.pathname==='/macro'){control.requests++;data=control.snapshot;}
    else if(url.pathname==='/health')data={status:'ok',service:'MarketIntel',version:'6.4.5'};
    else if(url.pathname==='/news')data={status:'ok',articles:[],updated_at:stamp};
    else if(url.pathname==='/market-sentiment')data=pulse;
    else if(url.pathname==='/batch')data=Object.fromEntries((request.postDataJSON()?.tickers||[]).map(ticker=>[ticker,{ticker,name:ticker,price:100,change:0,change_pct:0,currency:'USD',spark_prices:[99,100]}]));
    else if(url.pathname.startsWith('/history/'))data={dates:[before,first,latest],prices:[99,100,101]};
    else if(url.pathname==='/local-state')data={token:'macro-fixture',version:'6.4.5'};
    else if(url.pathname==='/local-backups')data=request.method()==='POST'?{id:1,created_at:stamp}:{backups:[]};
    else if(url.pathname==='/signal-history')data={observations:[],summary:{total:0,evaluated:0,days:0,hit_rate:null}};
    else if(url.pathname==='/sync/status')data={available:true,version:1,max_plaintext_bytes:2097152};
    return route.fulfill({json:data});
  });
}
async function refresh(page,control,snapshot) {
  const requests=control.requests;control.snapshot=snapshot;
  await page.locator('.mi-macro-toolbar button').click();
  await page.waitForFunction(previous=>document.querySelector('#macro-nfp-current')?.textContent!==previous,await page.locator('#macro-nfp-current').textContent()).catch(()=>{});
  assert(control.requests>requests,'Actualiza ahora must consult /macro again');
  await page.waitForFunction(()=>!macroSnapshotPromise);
}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.MARKETINTEL_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
  const context=await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'reduce'});
  const control={snapshot:macro(),requests:0};await install(context,control);
  const page=await context.newPage(),errors=[];page.setDefaultTimeout(15000);
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.MarketIntelMacroContext&&window.MarketIntelSyncUI);
  await page.locator('.sidebar [data-target="indicadores"]').click();
  await page.locator('#sec-indicadores').waitFor({state:'visible'});
  await page.locator('[data-tab="nfp"]').click();
  const example=page.locator('#ind-nfp .mi-macro-context');
  await example.waitFor({state:'visible'});
  assert.match(await example.innerText(),/123/,'First observed employment figure is in its course example');
  const initialText=await example.innerText();
  await refresh(page,control,macro(latest,87,123));
  assert.match(await example.innerText(),/87/,'A newer measured period replaces the current example');
  assert.notEqual(await example.innerText(),initialText);
  const revision=macro(latest,91,123);await refresh(page,control,revision);
  assert.match(await example.innerText(),/91/,'A corrected value regenerates the explanation');
  assert.equal(await page.locator('#ind-nfp .mi-macro-context').count(),1);
  assert.equal(await page.locator('.ind-panel > .mi-macro-context').count(),8);
  for(const width of [360,320]) {
    await page.setViewportSize({width,height:900});
    const overflow=await example.evaluate(el=>({width:el.scrollWidth,client:el.clientWidth}));
    assert(overflow.width<=overflow.client+2,'Macro example must fit at '+width+'px');
    const viewport=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(viewport.scroll<=viewport.width+2,'Page must not overflow at '+width+'px');
  }
  await page.setViewportSize({width:1280,height:900});
  const stale=macro(latest,91,123);stale.status='partial';
  stale.series.payrolls={...stale.series.payrolls,status:'stale',context_usable:false,warning:'La consulta falló: lectura anterior guardada.'};
  await page.evaluate(data=>renderMacroSnapshot(data),stale);
  assert.match(await example.innerText(),/antigu|confirm|vigente|disponible|verific/i,'Stale context is explicitly qualified');
  const hostile=macro(latest,91,123);hostile.series.payrolls.label='<img src=x onerror="window.macroXSS=true">';hostile.series.payrolls.source_url='javascript:window.macroXSS=true';
  await page.evaluate(data=>renderMacroSnapshot(data),hostile);
  assert.equal(await page.evaluate(()=>window.macroXSS),undefined);
  assert.equal(await page.locator('.mi-macro-context img,.mi-macro-context a[href^="javascript:"]').count(),0);
  await page.evaluate(()=>renderMacroSnapshot({status:'error',configured:true,series:{}}));
  assert.match(await example.innerText(),/disponible|verific|dato/i,'Unavailable data leaves a clear context message');
  await page.locator('.sidebar [data-target="portafolio"]').click();
  await page.locator('#sec-portafolio').waitFor({state:'visible'});
  await page.locator('#sec-portafolio button[onclick="pfOpenAddModal()"]:visible').first().click();
  await page.locator('#pf-modal-overlay').waitFor({state:'visible'});
  await page.evaluate(()=>pfCloseAddModal());
  await page.evaluate(()=>window.MarketIntelSyncUI.open());
  await page.locator('#mi-sync-dialog').waitFor({state:'visible'});
  await page.locator('[data-sync-close]').click();
  assert.equal(await page.evaluate(()=>localStorage.getItem('marketbot_apikey')),'macro-fixture-private-key');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('pf_transactions_macro_fixture')).length),1);
  assert.deepEqual(errors,[],'App must not produce uncaught errors');
  console.log('Macro browser passed: app boot, refresh/new period/correction, stale and absent states, mobile widths, safe rendering, portfolio and synchronization.');
  await context.close();
 } finally {await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
