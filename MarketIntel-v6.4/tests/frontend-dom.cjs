// Integration test without layout: requires jsdom (development-only).
// Run Flask with a disposable MARKETINTEL_DATA_DIR; quotes below are fixtures.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const search=[process.cwd(),...(process.env.MARKETINTEL_TEST_NODE_PATHS||'').split(path.delimiter).filter(Boolean)];
const {JSDOM,VirtualConsole}=require(require.resolve('jsdom',{paths:search}));
const base=process.env.MARKETINTEL_TEST_URL||'http://localhost:5050';
const errors=[],timers=[],alerts=[];
let pulseCalls=0,batchCalls=0,noData=false;
const series=Object.fromEntries(['fed_upper','fed_lower','cpi','core_pce','unemployment','payrolls','gdp','pmi','consumer_sentiment','treasury_10y'].map(key=>[key,{label:key,source:key==='pmi'?'ISM':'FRED',date:'2026-08-01',display_value:key==='pmi'?null:3.4,display_unit:'percent',value:key==='pmi'?null:3.4,status:key==='pmi'?'unavailable':'ok',history:[],fetched_at:'2026-09-23T14:05:00Z'}]));
const fixture=()=>({version:'6.2',session:{label:'Mercado abierto · Nueva York'},updated_at:'2026-09-23T14:06:00Z',cached:false,
 intraday:{score:noData?null:68,label:noData?'Sin lectura intradía':'Sesgo alcista',quality:noData?0:72,coverage:noData?0:90,components:[],reason:noData?'Datos demasiado antiguos.':'',status:noData?'insufficient':'ok'},
 context:{label:'Mixto / indeciso',score:54,last_history_date:'2026-09-22',components:[]},quotes:{SPY:{price:100+pulseCalls,data_at:'2026-09-23T14:05:00Z',status:noData?'stale':'recent',reason:'Fixture'}},
 evaluation:{summary:{total:0,evaluated:0,days:0,hit_rate:null},method:'Sin resultados inventados.'},errors:[],disclaimer:'Fixture.'});

async function mockedFetch(url,options={}){
 const pathname=new URL(url,base).pathname;let data;
 if(pathname==='/market-sentiment'){pulseCalls++;assert(!('quotes' in JSON.parse(options.body||'{}')));data=fixture();}
 else if(pathname==='/batch'){batchCalls++;data=Object.fromEntries((JSON.parse(options.body).tickers||[]).map(t=>[t,{ticker:t,price:100,change:1,change_pct:1,name:t,market_cap:1e9,data_date:'2026-09-23',spark_prices:[98,99,100]}]));}
 else if(pathname==='/macro')data={status:'partial',configured:true,series,updated_at:'2026-09-23T14:06:00Z'};
 else if(pathname==='/news')data={status:'ok',source:'Fixture',articles:[],updated_at:'2026-09-23T14:06:00Z'};
 else if(pathname.startsWith('/history/'))data={dates:['2026-09-01','2026-09-22','2026-09-23'],prices:[98,99,100]};
 else if(pathname.startsWith('/stock/'))data={ticker:'AAPL',name:'Fixture',price:100,change_pct:1,market_cap:1e9,pe:20,eps:5,eps_forward:6,revenue_ttm:1000000,revenue_growth:10,book_value:8,shares_outstanding:10000000,profit_margin:20};
 else return fetch(new URL(url,base),options);
 return {ok:true,status:200,json:async()=>data};
}
const virtual=new VirtualConsole();virtual.on('jsdomError',e=>{if(!/Not implemented.*navigation/i.test(e.message))errors.push(e.message)});
const source=fs.readFileSync('index.html','utf8').replace(/<script\b[^>]*\bsrc=[^>]*>[\s\S]*?<\/script>/gi,'');
const dom=new JSDOM(source,{url:base,runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:virtual,beforeParse(w){
 w.fetch=mockedFetch;w.AbortController=AbortController;w.alert=m=>alerts.push(m);w.confirm=()=>true;
 w.scrollTo=()=>{};
 w.localStorage.setItem('mi_onboarded','1');w.localStorage.setItem('watchlist','["AAPL"]');w.localStorage.setItem('marketbot_apikey','fixture-secret');
 w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){},addListener(){},removeListener(){}});
 w.setInterval=(fn,ms)=>{timers.push({fn,ms});return timers.length};w.clearInterval=()=>{};
 w.HTMLCanvasElement.prototype.getContext=function(){return {canvas:this}};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const charts=new Map();class Chart{constructor(ctx,config){this.data=config.data;this.options=config.options||{};this.config=config;this.ctx=ctx;if(ctx?.canvas)charts.set(ctx.canvas,this)}destroy(){}update(){}resize(){}};
 Chart.defaults={font:{},animation:{},interaction:{},plugins:{legend:{labels:{}},tooltip:{}},elements:{line:{},point:{}}};Chart.register=()=>{};Chart.getChart=canvas=>charts.get(canvas);w.Chart=Chart;
}});
const w=dom.window;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await pause(30)}throw Error('Timed out: '+fn.toString())}
(async()=>{
 await until(()=>w.document.readyState==='complete');
 for(const file of ['marketintel-reliability.js','marketintel-v2.js','portfolio-core.js','portfolio-v3.js'])w.eval(fs.readFileSync('static/'+file,'utf8'));
 await until(()=>w.document.querySelector('#mi-pulse h2')?.textContent==='Sesgo alcista');
 assert(w.document.querySelector('#sec-portafolio [data-backups]'),'El control de respaldo debe estar en Portafolio');
 assert(!w.document.querySelector('#mi-pulse').textContent.includes('Confianza'));
 const prior=pulseCalls;await Promise.all(timers.filter(t=>t.ms===60000).map(timer=>timer.fn()));
 await until(()=>pulseCalls>prior);assert(batchCalls>=2);
 noData=true;await until(()=>w.document.querySelector('[data-pulse-refresh]'));
 w.document.querySelector('[data-pulse-refresh]').click();
 await until(()=>w.document.querySelector('#mi-pulse h2')?.textContent==='Sin lectura intradía');
 assert.equal(w.document.querySelector('.mi-intraday-number').textContent,'—/100');
 w.go('indicadores');await until(()=>w.document.querySelectorAll('.mi-macro-card').length===10);
 assert(w.document.querySelector('#macro-live').textContent.includes('Sin dato'));
 assert(w.document.querySelector('#semaforo-grid').textContent.includes('Sin dato'));
 const complete={...series,
  fed_upper:{...series.fed_upper,display_value:4,value:4,status:'ok'},
  payrolls:{...series.payrolls,display_value:162,value:162,status:'ok'},
  unemployment:{...series.unemployment,display_value:4.1,value:4.1,status:'ok'},
  gdp:{...series.gdp,display_value:2.1,value:2.1,status:'ok'},
  core_pce:{...series.core_pce,display_value:3.3,value:3.3,status:'ok',date:'2026-07-01'},
  pmi:{...series.pmi,display_value:54.6,value:54.6,status:'ok',date:'2026-08-01'},
  consumer_sentiment:{...series.consumer_sentiment,display_value:47.8,value:47.8,status:'ok',date:'2026-09-01',source:'U. Michigan',warning:'Lectura preliminar'}};
 w.buildSemaforo({series:complete});
 assert(w.document.querySelector('#sem-overall').textContent.includes('LIGERAMENTE ALCISTA'));
 assert(w.document.querySelector('#sem-overall').textContent.includes('8 de 8 disponibles'));
 assert(w.document.querySelector('#semaforo-grid').textContent.includes('U. Michigan'));
 const saved=await w.MarketIntelBackup.save('manual');
 const original=await w.MarketIntelBackup.localRequest('/local-backups/'+saved.id);
 assert.equal(original.localStorage.watchlist,'["AAPL"]');assert(!original.localStorage.marketbot_apikey);
 w.localStorage.setItem('watchlist','["QQQ"]');await w.MarketIntelBackup.importSnapshot(original,true);
 assert.equal(w.localStorage.getItem('watchlist'),'["AAPL"]');
 const versions=await w.MarketIntelBackup.localRequest('/local-backups');assert(versions.backups.some(row=>row.reason==='before-restore'));
 await w.MarketIntelBackup.showBackups();assert(w.document.querySelector('#mi-backups-dialog [data-restore]'));
 assert.deepEqual(errors,[]);assert.deepEqual(alerts,[]);
 console.log(JSON.stringify({dom:'passed',checks:['automatic refresh','current quote request','missing data','10 macro cards','backup button placement','backup read and restore','API key exclusion','no script exceptions'],pulseCalls,batchCalls}));
 w.close();
})().catch(e=>{console.error(e.stack);console.error({errors,alerts,pulseCalls,batchCalls,pulse:w.document.querySelector('#mi-pulse')?.textContent});w.close();process.exit(1)});
