// Disposable Chromium profiles reproduce the desktop icon's storage boundary.
'use strict';
const {chromium}=require('playwright');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
const origin='http://localhost:5050';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'marketintel-profile-check-'));
const account=JSON.stringify([{id:'existing',name:'Cuenta conservada',currency:'USD'}]);
const trades=JSON.stringify([{id:'trade-before-update',type:'Compra',ticker:'AAPL',shares:2,price:100}]);
async function profile(directory,app,action){
  const args=['--no-sandbox','--disable-dev-shm-usage','--profile-directory='+directory];
  if(app)args.push('--app='+origin);
  const context=await chromium.launchPersistentContext(root,{executablePath:'/usr/bin/chromium',args,headless:true});
  try{
    await context.route('**/*',route=>route.request().url().startsWith(origin)
      ?route.fulfill({contentType:'text/html',body:'<!doctype html><title>MarketIntel profile check</title><h1>MarketIntel</h1>'})
      :route.abort());
    const page=await context.newPage();await page.goto(origin);
    await action(page);
  }finally{await context.close();}
}
(async()=>{
  try{
    await profile('Profile 1',false,async page=>page.evaluate(({account,trades})=>{
      localStorage.setItem('pf_portfolios',account);localStorage.setItem('pf_transactions_existing',trades);
    },{account,trades}));
    await profile('Default',true,async page=>{
      assert.equal(await page.evaluate(()=>localStorage.getItem('pf_portfolios')),null,'Other profile must not be mistaken for the one holding the portfolio');
    });
    await profile('Profile 1',true,async page=>{
      assert.equal(await page.evaluate(()=>localStorage.getItem('pf_portfolios')),account,'App-mode with the chosen profile must retain the existing accounts');
      assert.equal(await page.evaluate(()=>localStorage.getItem('pf_transactions_existing')),trades,'Existing transactions must be unchanged');
    });
    console.log('Chromium profiles passed: wrong profile is empty, selected app profile retains original accounts and transactions.');
  }finally{fs.rmSync(root,{recursive:true,force:true});}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
