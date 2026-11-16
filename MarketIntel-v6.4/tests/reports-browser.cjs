'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),origin='http://localhost:5079';
const pdf=Buffer.from('%PDF-1.4\nreport-browser-fixture\n%%EOF');
const report={kind:'closing',status:'partial',session_date:'2026-11-16',generated_at:'2026-11-16T22:01:00Z',cutoff_at:'2026-11-16T22:00:00Z',summary:['El S&P 500 terminó al alza. Se revisa la cobertura de las acciones.'],quotes:[{label:'S&P 500',price:6048,change:48,change_pct:.8,unit:'pts',source:'Fixture',as_of:'2026-11-16T21:00:00Z'},{label:'Nasdaq 100',price:21635,change:235,change_pct:1.1,unit:'pts'},{label:'Oro',price:2658,change:26,change_pct:.99,unit:'USD'}],breadth:[{label:'S&P 500',up:330,down:140,unchanged:30,missing:3,total:503,valid:500},{label:'Nasdaq 100',up:75,down:20,unchanged:5,missing:1,total:101,valid:100}],magnificent_seven:[{ticker:'NVDA',previous:180,price:183.6,change:3.6,change_pct:2}],watchlist_reports:[{ticker:'NVDA',title:'Resultados',status:'published',published_at:'2026-11-16T21:20:00Z',summary:'Resultado del ejemplo de prueba.',actual:'0,92 USD',consensus:'0,85 USD'},{ticker:'AAPL',title:'Publicación prevista',status:'pending',summary:'Prevista a las 17:30 NY; pendiente al corte.'}],macro:[],warnings:['La cobertura del proveedor puede ser parcial.']};
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.MARKETINTEL_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  let calls=0,fail=false,watchlist;
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==origin)return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/marketintel-reports.css"><body style="margin:0;background:#080f19;color:white"><section id="sec-home" style="padding:20px"><div class="mi-home-head"><div class="mi-actions"><button id="existing">Posición</button></div></div></section><script src="/static/marketintel-reports.js"></script></body></html>'});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.join(root,url.pathname),contentType:url.pathname.endsWith('.css')?'text/css':'text/javascript'});
   if(url.pathname.startsWith('/reports/')){calls++;watchlist=route.request().postDataJSON().watchlist;return route.fulfill({status:fail?409:200,json:fail?{error:'Disponible desde las 17:00 NY.'}:{report,pdf_base64:pdf.toString('base64'),filename:'MarketIntel-sesion.pdf'}});}
   return route.abort();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{localStorage.setItem('watchlist',JSON.stringify(['NVDA','AAPL','MSFT','AMZN','META','GOOGL','TSLA']));localStorage.setItem('portfolio-preserved','existing-data');});
  await page.goto(origin);await page.locator('[data-report-kind="closing"]').click();await page.waitForFunction(()=>document.querySelector('.mi-report-primary')?.disabled===false);
  assert.equal(watchlist.length,7);assert.match(await page.locator('#mi-report-body').innerText(),/17:30 NY/);assert.equal(await page.locator('#existing').count(),1);
  const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Descargar PDF',exact:true}).click();const download=await downloadPromise;assert(fs.readFileSync(await download.path()).equals(pdf));assert.equal(calls,1);
  for(const width of [1440,390,320]){await page.setViewportSize({width,height:900});const size=await page.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth,dialog:document.querySelector('.mi-report-dialog').clientWidth,scroll:document.querySelector('.mi-report-dialog').scrollWidth}));assert(size.page<=size.viewport+1&&size.scroll<=size.dialog+1,JSON.stringify(size));const bounds=await page.locator('.mi-report-primary').boundingBox();assert(bounds.y+bounds.height<=900);}
  await page.getByRole('button',{name:'Cerrar reporte'}).focus();await page.keyboard.press('Shift+Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Descargar PDF');await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'Cerrar reporte');await page.keyboard.press('Escape');assert(await page.locator('#mi-report-overlay').isHidden());
  fail=true;await page.locator('[data-report-kind="closing"]').click();await page.waitForFunction(()=>document.querySelector('#mi-report-status')?.textContent.includes('17:00 NY'));assert(await page.locator('.mi-report-primary').isDisabled());assert.equal(await page.evaluate(()=>localStorage.getItem('portfolio-preserved')),'existing-data');assert.deepEqual(errors,[]);
  console.log('Reports browser: full watchlist, same PDF download, pending company, server cutoff error, desktop/mobile widths, keyboard and existing actions/data passed.');
  await context.close();
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
