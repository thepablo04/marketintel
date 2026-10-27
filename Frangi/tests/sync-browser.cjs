'use strict';
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const crypto = require('node:crypto');
const html = path.join(__dirname,'../frangi.html');
const bridge = path.join(__dirname,'../bridge.html');
const cloud = new Map();
let counter=0, offline=false;
const local='http://localhost:5060/frangi.html';
const web='https://marketintel-nu.vercel.app/frangi/index.html';
const reply=(route,status,body,origin)=>route.fulfill({status,json:body,headers:{'Access-Control-Allow-Origin':origin||'*','Access-Control-Allow-Headers':'Authorization,Content-Type,X-Sync-If-Match,X-Sync-If-None-Match','Access-Control-Allow-Methods':'GET,PUT,OPTIONS','Cache-Control':'no-store'}});
async function route(context) {
  await context.route('**/*', async req=>{
    const request=req.request(),url=new URL(request.url());
    if(url.pathname==='/frangi/bridge.html') return req.fulfill({path:bridge,contentType:'text/html'});
    if(url.pathname==='/frangi/index.html'||url.pathname==='/frangi.html') return req.fulfill({path:html,contentType:'text/html'});
    if(url.pathname==='/sync/data') {
      const origin=request.headers().origin;
      if(request.method()==='OPTIONS')return req.fulfill({status:204,headers:{'Access-Control-Allow-Origin':origin||'*','Access-Control-Allow-Headers':'Authorization,Content-Type,X-Sync-If-Match,X-Sync-If-None-Match','Access-Control-Allow-Methods':'GET,PUT,OPTIONS'}});
      if(offline)return reply(req,503,{code:'unavailable'},origin);
      const token=request.headers().authorization;
      assert.match(token||'',/^Bearer [A-Za-z0-9_-]{43}$/);
      const old=cloud.get(token);
      if(request.method()==='GET')return reply(req,old?200:404,old||{code:'not_found'},origin);
      const body=request.postDataJSON();
      assert.deepEqual(Object.keys(body).sort(),['ciphertext','iv','version']);
      const headers=request.headers();
      if(old?headers['x-sync-if-match']!==old.revision:headers['x-sync-if-none-match']!=='*')return reply(req,409,{code:'conflict'},origin);
      const revision='"test-'+(++counter)+'"';cloud.set(token,{revision,envelope:body});
      return reply(req,200,{revision},origin);
    }
    return req.abort('blockedbyclient');
  });
}
async function ready(page) {
  await page.waitForFunction(()=>window.FrangiSyncEngine && window.FrangiSyncEngine.getState().status!=='disconnected' || window.FrangiSyncEngine && window.FrangiSyncEngine.getState().status==='disconnected' && document.querySelector('#calGrid [data-date]'));
  await page.evaluate(()=>window.FrangiSyncEngine.ready());
}
async function sync(page,choices) {
  await page.evaluate(choices=>window.FrangiSyncEngine.sync(choices),choices);
  await page.waitForFunction(()=>window.FrangiSyncEngine.getState().status!=='syncing');
  return page.evaluate(()=>window.FrangiSyncEngine.getState());
}
async function edit(page,date,result) {
  await page.locator(`[data-date="${date}"]`).click();
  await page.locator(result==='TP'?'#addTp':'#addSl').click();
  await page.locator('#closeEditor').click();
}
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
 const errors=[];
 try {
   const localContext=await browser.newContext({viewport:{width:320,height:740}});
   const webContext=await browser.newContext({viewport:{width:1200,height:900}});
   await localContext.addInitScript(()=>{
     if(location.hostname!=='localhost') return;
     const date=new Date();const key=`tpsl_calendar_trade_${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-05`;
     if(!localStorage.getItem('frangi_test_seed')) {localStorage.setItem('frangi_test_seed','1');localStorage.setItem(key,'TP');}
   });
   await route(localContext);await route(webContext);
   const first=await localContext.newPage(),second=await webContext.newPage();
   first.on('pageerror',e=>errors.push(e.stack));second.on('pageerror',e=>errors.push(e.stack));
   await first.goto(local);await second.goto(web);await ready(first);await ready(second);
   const date=await first.evaluate(()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-05`});
   assert.equal(await first.locator('#tradeCount').innerText(),'1');
   assert.equal(cloud.size,0,'Unlinked page must not upload');
   await first.locator('#openSync').click();await first.locator('#createSync').click();
   try { await first.waitForFunction(()=>window.FrangiSyncEngine.getState().status==='idle',null,{timeout:10000}); }
   catch(e) { console.error('Create state',await first.evaluate(()=>({state:window.FrangiSyncEngine.getState(),error:document.querySelector('#syncError').textContent,badge:document.querySelector('#syncBadge').textContent})), 'cloud',cloud.size,'page errors',errors); throw e; }
   const key=await first.locator('#syncKey').inputValue();assert.match(key,/^FR1-[A-Za-z0-9_-]{43}$/);
   assert.equal(cloud.size,1);
   await first.locator('#closeSync').click();
   await second.locator('#openSync').click();await second.locator('#syncInput').fill(key);await second.locator('#linkSync').click();
   try { await second.waitForFunction(()=>window.FrangiSyncEngine.getState().status==='idle',null,{timeout:10000}); }
   catch(e) { console.error('Connect state',await second.evaluate(()=>({state:window.FrangiSyncEngine.getState(),error:document.querySelector('#syncError').textContent,badge:document.querySelector('#syncBadge').textContent})), 'cloud',cloud.size,'page errors',errors); throw e; }
   await second.locator('#closeSync').click();
   assert.equal(await second.locator('#tradeCount').innerText(),'1');
   assert.equal(await second.locator('#winRatio').innerText(),'100%');
   await edit(first,date,'TP');await edit(first,date,'SL');
   await sync(first);await sync(second);
   assert.equal(await second.locator('#tradeCount').innerText(),'3');
   assert.equal(await second.locator('#winRatio').innerText(),'67%');
   offline=true;await edit(first,date,'TP');await edit(second,date,'SL');
   assert.equal((await sync(first)).pending,true);
   offline=false;await sync(first);await sync(second);
   assert.equal(await second.locator('#tradeCount').innerText(),'5');
   assert.equal(await second.locator('#winRatio').innerText(),'60%');
   await first.reload();await ready(first);await sync(first);
   assert.equal(await first.locator('#tradeCount').innerText(),'5');
   assert.equal(await first.locator('#winRatio').innerText(),'60%');
   const wire=JSON.stringify([...cloud.values()]);
   assert(!wire.includes(key) && !wire.includes('legacy_') && !wire.includes('result'),'Cloud receives only encrypted payloads');
   const width=await first.locator('.wrap').evaluate(e=>e.scrollWidth-e.clientWidth);
   assert(width<=1,'320px layout must not overflow');
   assert.deepEqual(errors,[]);
   console.log('Frangi browser passed: old mark, encrypted link local/web, 3 then 5 trades in a day, offline independent additions, win rate, reload, 320px.');
   await localContext.close();await webContext.close();
   const bridgeContext=await browser.newContext();
   await route(bridgeContext);
   const bridged=await bridgeContext.newPage();
   bridged.on('pageerror',e=>errors.push(e.message));
   await bridged.goto(local);await ready(bridged);
   const previousRevision=[...cloud.values()][0].revision;
   await bridged.locator('#openSync').click();
   await bridged.locator('#syncInput').fill('MI1-'+key.slice(4));
   await bridged.locator('#createWithKey').click();
   await bridged.waitForFunction(()=>window.FrangiSyncEngine.getState().status==='idle',null,{timeout:20000});
   assert.equal(cloud.size,1,'The same private key must reach the same Frangi vault through the bridge');
   const marketAuth=crypto.createHash('sha256').update('MarketIntel sync auth v1\0').update(Buffer.from(key.slice(4),'base64url')).digest('base64url');
   assert(!cloud.has('Bearer '+marketAuth),'MarketIntel and Frangi must have separate vaults for the same key');
   await bridged.locator('#closeSync').click();
   await edit(bridged,date,'SL');await sync(bridged);
   assert.notEqual([...cloud.values()][0].revision,previousRevision,'The bridge must send updates, not just downloads');
   assert.deepEqual(errors,[]);
   await bridgeContext.close();
   console.log('Frangi bridge passed: local page to hosted iframe to encrypted API, separate vault for the same MI1 key.');
 } finally {await browser.close()}
})().catch(e=>{console.error(String(e.stack).replace(/(?:FR1|MI1)-[A-Za-z0-9_-]+/g,'[private key]'));process.exitCode=1});
