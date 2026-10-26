// Optional real-browser regression. See run-frontend-browser.py for isolation.
// Provider requests use synthetic fixtures; Chart.js and app/backup code are real.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.MARKETINTEL_TEST_URL || 'http://127.0.0.1:5050';
const screenshots = process.env.MARKETINTEL_SCREENSHOT_DIR;
const captureOnly = process.env.MARKETINTEL_BROWSER_CAPTURE_ONLY === '1';
const screenshotPrefix = process.env.MARKETINTEL_SCREENSHOT_PREFIX || 'frontend';
const chartFile = path.join(path.dirname(require.resolve('chart.js')), 'chart.umd.js');
const sections = ['home', 'indicadores', 'screener', 'ficha', 'valuacion', 'portafolio',
  'watchlist', 'heatmap', 'vi_principios', 'vi_fundamentales', 'chatbot'];
const today = new Date().toISOString().slice(0, 10);
const dates = Array.from({length: 45}, (_, i) => new Date(Date.now() - (44-i)*86400000).toISOString().slice(0,10));
const history = {dates, prices: dates.map((_,i) => +(95 + i*.18 + Math.sin(i/3)*2).toFixed(2))};
const timestamp = new Date().toISOString();
const fixturePrices = {AAPL: 230, MSFT: 440, NVDA: 150, SPY: 620, QQQ: 550, '^VIX': 17.2};
function stock(ticker) {
  const price = fixturePrices[ticker] || 100;
  return {ticker, name: ticker + ' · Empresa de prueba', price, change: 1.5, change_pct: .75,
    market_cap: 1e12, sector: 'Technology', industry: 'Software', pe: 25, forward_pe: 22,
    eps: 8, eps_forward: 9, book_value: 20, revenue_ttm: 8e10, revenue_growth: 12,
    shares_outstanding: 1e9, profit_margin: 20, beta: 1.1, sma200: price*.9,
    above_sma200: true, analyst_target: price*1.1, data_date: today,
    spark_prices: history.prices, debt_to_equity: 30, current_ratio: 2, roe: 20,
    high_52w: price*1.2, low_52w: price*.7, currency: 'USD'};
}
const series = Object.fromEntries(['fed_upper','fed_lower','cpi','core_pce','unemployment','payrolls',
  'gdp','pmi','consumer_sentiment','treasury_10y'].map((key,i) => [key, {
    label: key, source: 'Fixture', date: today, display_value: i===7 ? 52 : 3.5,
    display_unit: 'percent', value: i===7 ? 52 : 3.5, status: 'ok', fetched_at: timestamp,
    history: dates.map((date,j) => ({date, value: 3 + j*.01})),
  }]));
// Fixed, valid exchange session: journal checks must work on weekends too.
const pulse = {version:'6.2', session:{label:'Sesión de prueba · Nueva York',date:'2026-09-23',is_open:true,calendar_verified:true,elapsed_minutes:35,remaining_minutes:355}, updated_at:'2026-09-23T14:05:00Z',
  intraday:{score:68,label:'Sesgo alcista',quality:72,coverage:90,components:[],reason:'Datos sintéticos para prueba.',status:'ok'},
  context:{label:'Mixto / indeciso',score:54,last_history_date:today,components:[]},
  quotes:{SPY:{price:620,data_at:'2026-09-23T14:05:00Z',status:'recent',usable:true,reason:'Fixture'}},
  evaluation:{summary:{total:0,evaluated:0,days:0,hit_rate:null},method:'Datos de prueba.'},
  errors:[], disclaimer:'Cotizaciones sintéticas, exclusivamente para pruebas.'};
const fundamentals = {eps:[{period:'2025',actual:7,estimate:6.5},{period:'2026',actual:8,estimate:7.8}],
  revenue:[{period:'2024',revenue:70,net_income:14,margin:20},{period:'2025',revenue:80,net_income:16,margin:20}],
  quarterly_revenue:[],margins:[],pe_history:[{period:'2024',pe:23},{period:'2025',pe:25}]};

function fontFixtures() {
  const files = new Map();
  let css = '';
  for (const [family, pkg, weights] of [['Inter','inter',[300,400,500,600,700]],
    ['Syne','syne',[400,600,700,800]],['IBM Plex Mono','ibm-plex-mono',[400,500]]]) {
    let root;
    try { root = path.dirname(require.resolve('@fontsource/'+pkg+'/400.css')); }
    catch (_) { continue; } // Fonts are optional test-only development dependencies.
    for (const weight of weights) {
      const name = `${pkg}-latin-${weight}-normal.woff2`;
      const file = path.join(root,'files',name);
      if (!fs.existsSync(file)) continue;
      files.set('/__test_fonts__/'+name,file);
      css += `@font-face{font-family:'${family}';font-style:normal;font-weight:${weight};font-display:swap;src:url('/__test_fonts__/${name}') format('woff2')}\n`;
    }
  }
  return {css,files};
}
const fonts = fontFixtures();

async function fixtureRoutes(page, origin, hosted, requested) {
  let signalPulse = {...pulse,evaluation:hosted ? {storage:'browser',model:'intraday-v6.1',method:'Datos de prueba.',completed_closes:{}} : pulse.evaluation};
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (/cdnjs\.cloudflare\.com/.test(url.hostname) && /chart/i.test(url.pathname))
      return route.fulfill({path:chartFile,contentType:'text/javascript'});
    if (url.hostname === 'fonts.googleapis.com') return route.fulfill({body:fonts.css.replaceAll("url('/", "url('"+origin+"/"),contentType:'text/css'});
    if (url.origin !== origin) return route.abort('blockedbyclient');
    if (fonts.files.has(url.pathname)) return route.fulfill({path:fonts.files.get(url.pathname),contentType:'font/woff2'});
    let data;
    if (url.pathname === '/batch') data = Object.fromEntries((request.postDataJSON()?.tickers || []).map(t=>[t,stock(t)]));
    else if (url.pathname.startsWith('/stock/')) data = stock(decodeURIComponent(url.pathname.slice(7)));
    else if (url.pathname.startsWith('/history/')) data = history;
    else if (url.pathname.startsWith('/fundamentals/')) data = fundamentals;
    else if (url.pathname.startsWith('/financials/')) data = {annual:[],quarterly:[]};
    else if (url.pathname === '/macro') data = {status:'ok',configured:true,series,updated_at:timestamp};
    else if (url.pathname === '/news') data = {status:'ok',source:'Fixture',articles:[],updated_at:timestamp};
    else if (url.pathname === '/market-sentiment') data = signalPulse;
    if (data !== undefined) {
      requested.add(url.pathname);
      return route.fulfill({json:data});
    }
    assert(!hosted || !url.pathname.startsWith('/local-'), 'Hosted backup must not access local backup API');
    assert(!hosted || url.pathname !== '/signal-history', 'Hosted journal must not access local journal API');
    if (hosted) return route.fulfill({response:await route.fetch({url:base+url.pathname+url.search})});
    return route.continue();
  });
  return {setSignalPulse(value) { signalPulse = value; }};
}

async function seed(context) {
  await context.addInitScript(({date}) => {
    if (localStorage.getItem('browser_fixture_seeded')) return;
    const values = {
      browser_fixture_seeded:'1', mi_onboarded:'1', theme_mode:'dark', watchlist:'["AAPL","NVDA","MSFT"]',
      pf_portfolios:JSON.stringify([{id:'fixture',name:'Cuenta de prueba',type:'Paper',openingCash:10000,currency:'USD',ledgerVersion:3}]),
      pf_active_id:'fixture',
      pf_transactions_fixture:JSON.stringify([{id:'fixture-buy',date,type:'Compra',ticker:'MSFT',shares:2,price:400,fee:0}]),
      hm_custom:JSON.stringify({sectors:{'Grupo de prueba':['AAPL','MSFT']}}),
      note_AAPL:'Nota de análisis de prueba', ficha_note_AAPL:'Nota de ficha de prueba',
    };
    for (const [key,value] of Object.entries(values)) localStorage.setItem(key,value);
  },{date:dates[0]});
}

async function navigate(page, section, mobile) {
  if (mobile) {
    const direct = page.locator(`.mi-mobile [data-target="${section}"]`);
    if (await direct.count()) await direct.click();
    else {
      await page.locator('.mi-mobile [data-more]').click();
      await page.locator(`#mi-drawer [data-target="${section}"]`).click();
    }
  } else if (section === 'chatbot') await page.locator('.sidebar [data-bot]').click();
  else await page.locator(`.sidebar [data-target="${section}"]`).click();
  await page.locator('#sec-'+section).waitFor({state:'visible'});
  const active = await page.locator('.section.active, .hero-section.active').evaluateAll(nodes=>nodes.map(node=>node.id));
  assert.deepEqual(active,['sec-'+section],'Exactly the selected section must be active');
  await page.waitForTimeout(80);
}

async function checkLayout(page, label) {
  const geometry = await page.evaluate(() => {
    const active = document.querySelector('.section.active, .hero-section.active');
    return {viewport:innerWidth,width:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),
      height:active.getBoundingClientRect().height, text:active.innerText.trim().length};
  });
  assert(geometry.height > 40 && geometry.text > 20,`${label}: active section has visible content`);
  assert(geometry.width <= geometry.viewport + 2,`${label}: page overflow ${geometry.width}px > ${geometry.viewport}px`);
}

async function screenshot(page, name) {
  if (!screenshots) return;
  fs.mkdirSync(screenshots,{recursive:true});
  await page.screenshot({path:path.join(screenshots,`${screenshotPrefix}-${name}.png`),fullPage:false});
}

async function checkPortfolioAmounts(page) {
  const amounts = await page.locator('.pf3-kpi > strong').evaluateAll(nodes => nodes.map(node => {
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter(rect => rect.width > 0);
    return {value:node.textContent,width:node.clientWidth,contentWidth:node.scrollWidth,
      lines:new Set(rects.map(rect=>Math.round(rect.top))).size};
  }));
  for (const amount of amounts) {
    assert(amount.lines===1 && amount.contentWidth<=amount.width+1,
      `Portfolio amount ${amount.value} must fit on one line: ${JSON.stringify(amount)}`);
  }
}

async function exercisePreferences(page, mobile) {
  await navigate(page,'home',mobile);
  await page.locator('[data-custom]').click();
  for (const density of ['compact','comfy','balanced']) {
    await page.locator('#mi-density').selectOption(density);
    assert.equal(await page.evaluate(()=>localStorage.mi_density),density);
    if (density!=='balanced') assert(await page.locator('body').evaluate((el,d)=>el.classList.contains('mi-'+d),density));
  }
  for (const scale of ['large','normal']) {
    await page.locator('#mi-scale').selectOption(scale);
    assert(await page.locator('body').evaluate((el,s)=>el.classList.contains('mi-scale-'+s),scale));
  }
  await page.locator('[data-widget-toggle="calendar"]').uncheck();
  await page.locator('[data-widget="calendar"]').waitFor({state:'hidden'});
  await page.locator('[data-widget-toggle="calendar"]').check();
  await page.locator('[data-widget="calendar"]').waitFor({state:'visible'});
  await page.keyboard.press('Escape');
  await page.locator('.mi-home-head h1').click();
  await page.keyboard.press('Shift+P');
  assert(await page.locator('body').evaluate(el=>el.classList.contains('mi-present')),'Presentation shortcut remains available outside inputs');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('mi-present')),false);
  if (!mobile) {
    for (const [target,key] of [['watchlist','Enter'],['home','Space']]) {
      await page.locator(`.sidebar [data-target="${target}"]`).focus();
      await page.keyboard.press(key);
      await page.locator('#sec-'+target).waitFor({state:'visible'});
      assert.equal(await page.locator(`.sidebar [data-target="${target}"]`).getAttribute('aria-current'),'page');
    }
  }
}

async function exerciseFlows(page, mobile, mode) {
  await navigate(page,'watchlist',mobile);
  await page.locator('#wl-input').fill('TEST');
  await page.locator('#wl-input').press('Enter');
  await page.locator('#wl-card-TEST').waitFor({state:'visible'});
  await page.waitForFunction(()=>JSON.parse(localStorage.watchlist).includes('TEST'));
  await page.locator('#wl-card-TEST button[onclick*="wlRemove"]').click();
  await page.locator('#wl-card-TEST').waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.watchlist).includes('TEST')),false);

  await navigate(page,'valuacion',mobile);
  await page.locator('#gn-eps').fill('8');
  await page.locator('#gn-bvps').fill('20');
  await page.locator('#gn-price').fill('50');
  assert.match(await page.locator('#gn-result').innerText(),/60\.00/,'Graham calculation remains functional');

  await navigate(page,'screener',mobile);
  await page.locator('#ticker-input').fill('AA');
  await page.locator('#ticker-input').press('Shift+P');
  assert.equal(await page.locator('#ticker-input').inputValue(),'AAP');
  assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('mi-present')),false,
    'Typing an uppercase P must not open presentation mode');
  await page.locator('#ticker-input').fill('AAPL');
  await page.locator('#ticker-input').press('Enter');
  await page.locator('#screener-results').waitFor({state:'visible'});
  await page.waitForFunction(()=>window.Chart.getChart(document.getElementById('chart-price'))?.data.datasets[0].data.length>0);
  await page.locator('#stock-notes').fill('Nota de análisis de prueba actualizada');
  await page.locator('#stock-notes').press('Tab');
  assert.equal(await page.evaluate(()=>localStorage.note_AAPL),'Nota de análisis de prueba actualizada');
  await page.locator('#sec-screener').evaluate(el=>el.scrollIntoView({block:'start'}));
  await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-screener-populated`);

  await navigate(page,'ficha',mobile);
  await page.locator('#ficha-ticker').fill('AAPL');
  await page.locator('#ficha-ticker').press('Enter');
  await page.locator('#ficha-content').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.querySelector('#ficha-content').classList.contains('mi-data-loading'));
  await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-ficha-populated`);

  await navigate(page,'portafolio',mobile);
  await checkPortfolioAmounts(page);
  for (const [operation, shares, price] of [['Compra','3','100'],['Venta','1','110']]) {
    await page.locator('#sec-portafolio button[onclick="pfOpenAddModal()"]:visible').first().click();
    await page.locator('#pf-in-operation').selectOption({label:operation});
    await page.locator('#pf-in-ticker').fill('TEST');
    await page.locator('#pf-in-shares').fill(shares);
    await page.locator('#pf-in-cost').fill(price);
    await page.locator('#pf-in-date').fill(today);
    await page.locator('#pf-modal-overlay button[onclick="pfAddPosition()"]').click();
    try { await page.locator('#pf-modal-overlay').waitFor({state:'hidden'}); }
    catch (error) {
      console.error('Fixture trade failed:',JSON.stringify({mode,mobile,operation,today,
        modal:await page.locator('#pf-modal-overlay').innerText(),
        inputs:await page.locator('#pf-modal-overlay input').evaluateAll(inputs=>inputs.map(input=>({id:input.id,value:input.value,validation:input.validationMessage}))),
        backup:await page.locator('#mi-backup-status').textContent()}));
      await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-failed-trade`);
      throw error;
    }
  }
  const positions = await page.evaluate(()=>JSON.parse(localStorage.pf_positions_fixture));
  assert.equal(positions.find(p=>p.ticker==='TEST').shares,2,'Buy and sell must retain remaining position');
  const trades = await page.evaluate(()=>JSON.parse(localStorage.pf_transactions_fixture).filter(tx=>tx.ticker==='TEST'));
  assert(trades.find(tx=>tx.type==='Venta').sequence>trades.find(tx=>tx.type==='Compra').sequence,
    'Same-day trades must retain entry order across persistence and normalization');
  await page.locator('.pf-tab[data-t="transactions"]').click();
  await page.locator('#pf-transactions-panel').waitFor({state:'visible'});
  assert.match(await page.locator('#pf-transactions-body').innerText(),/TEST/);
  await page.locator('.pf-tab[data-t="positions"]').click();

  await page.locator('[data-backup-now]').click();
  await page.waitForFunction(()=>!/Preparando|Guardando/.test(document.getElementById('mi-backup-status').textContent));
  await page.locator('[data-backups]').click();
  await page.locator('#mi-backups-dialog [data-restore]').first().waitFor({state:'visible'});
  const before = await page.evaluate(()=>window.MarketIntelBackup.snapshot());
  await page.locator('#mi-backups-dialog [data-restore]').first().click();
  await page.locator('#mi-backup-preview').waitFor({state:'visible'});
  await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-backup-preview`);
  assert.match(await page.locator('#mi-backup-preview').innerText(),/Notas/);
  assert.match(await page.locator('#mi-backup-preview').innerText(),/Grupos del heatmap/);
  await page.locator('#mi-backup-preview [data-cancel]').click();
  const after = await page.evaluate(()=>window.MarketIntelBackup.snapshot());
  assert.deepEqual(after.localStorage,before.localStorage,'Cancel restore must preserve saved application data');
  await page.locator('#mi-backups-dialog [data-close]').click();

  await navigate(page,'heatmap',mobile);
  await page.locator('.hm-tab[data-tab="custom"]').click();
  await page.locator('#hm-custom-builder').waitFor({state:'visible'});
  assert.match(await page.locator('#hm-custom-builder').innerText(),/Grupo de prueba/);
  await page.keyboard.press('Control+k');
  await page.locator('#mi-command-input').waitFor({state:'visible'});
  await page.keyboard.press('Escape');
  await page.locator('#mi-command').waitFor({state:'hidden'});
}

async function exerciseSignalJournal(page, mobile, routes) {
  await navigate(page,'home',mobile);
  async function refresh() {
    const priorButton = await page.locator('[data-pulse-refresh]').elementHandle();
    await Promise.all([page.waitForResponse(response=>new URL(response.url()).pathname==='/market-sentiment'),priorButton.click()]);
    await page.waitForFunction(button=>!button.isConnected,priorButton);
  }
  const first = await page.evaluate(()=>window.MarketIntelBrowserSignalStore.createStore().history(true));
  assert.equal(first.summary.total,1,'Hosted pulse records its first real observation in IndexedDB');
  assert.equal(first.summary.evaluated,0,'Current session never receives a completed result');
  assert.equal(first.observations[0].reference,620);
  await refresh();
  await page.waitForFunction(()=>document.querySelector('#mi-pulse').textContent.includes('1 lecturas registradas'));
  const refreshed = await page.evaluate(()=>window.MarketIntelBrowserSignalStore.createStore().history(true));
  assert.deepEqual(refreshed,first,'Refresh retains the first observation in the same half-hour window');
  routes.setSignalPulse({...pulse,
    session:{...pulse.session,date:'2026-09-24',is_open:false},
    evaluation:{storage:'browser',model:'intraday-v6.1',method:'Datos de prueba.',completed_closes:{'2026-09-23':625,'2026-09-24':999}},
  });
  await refresh();
  await page.waitForFunction(()=>document.querySelector('#mi-pulse').textContent.includes('1 evaluadas'));
  const settled = await page.evaluate(()=>window.MarketIntelBrowserSignalStore.createStore().history(true));
  assert.equal(settled.summary.hit_rate,100);
  assert.equal(settled.observations[0].close_price,625,'Only completed close from an earlier session evaluates the saved observation');
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.querySelector('#mi-pulse')?.textContent.includes('1 evaluadas'));
  assert.deepEqual(await page.evaluate(()=>window.MarketIntelBrowserSignalStore.createStore().history(true)),settled,'Reload preserves the journal and its immutable evaluation');
  const details = page.locator('#mi-pulse details').filter({has:page.locator('[data-journal]')});
  await details.locator('summary').click();
  const [download] = await Promise.all([page.waitForEvent('download'),details.locator('[data-journal]').click()]);
  assert.equal(download.suggestedFilename(),'MarketIntel-seguimiento.json');
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')),settled,'Export button downloads the browser journal without local server endpoints');
}

(async()=>{
  const browser = await chromium.launch({executablePath:process.env.MARKETINTEL_CHROMIUM || '/usr/bin/chromium',
    args:['--no-sandbox','--disable-dev-shm-usage']});
  const reports = [];
  try {
    for (const hosted of captureOnly ? [false] : [false,true]) {
      for (const mobile of captureOnly ? [false] : [false,true]) {
        const mode = hosted ? 'web' : 'local';
        const viewport = mobile ? {width:390,height:844} : {width:1440,height:1000};
        const context = await browser.newContext({viewport,reducedMotion:'reduce'});
        await seed(context);
        const page = await context.newPage();
        const errors = [], requested = new Set();
        page.on('pageerror',error=>errors.push(error.message));
        page.on('dialog',async dialog=>{errors.push(`Unexpected ${dialog.type()}: ${dialog.message()}`);await dialog.dismiss();});
        page.setDefaultTimeout(10000);
        const origin = hosted ? 'http://marketintel.test' : base;
        const routes = await fixtureRoutes(page,origin,hosted,requested);
        await page.goto(origin,{waitUntil:'networkidle'});
        await page.locator('#mi-pulse h2').waitFor({state:'visible'});
        await page.evaluate(()=>document.fonts.ready);
        await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-home-dark`);
        if (captureOnly) { console.log('Captured dashboard:',screenshots);await context.close();continue; }
        for (const theme of ['dark','light']) {
          if (theme==='light') {
            await page.locator('[data-tools]').click();
            await page.locator('#theme-toggle-btn').click();
            await page.keyboard.press('Escape');
            assert.equal(await page.evaluate(()=>localStorage.theme_mode),'light');
          }
          for (const section of sections) {
            await navigate(page,section,mobile);
            await checkLayout(page,`${mode} ${viewport.width} ${theme} ${section}`);
            if (['home','portafolio','indicadores','valuacion','watchlist','heatmap'].includes(section))
              await screenshot(page,`${mode}-${mobile?'mobile':'desktop'}-${section}-${theme}`);
          }
        }
        await exerciseFlows(page,mobile,mode);
        await exercisePreferences(page,mobile);
        if (hosted) await exerciseSignalJournal(page,mobile,routes);
        if (!hosted) {
          const narrowWidth = mobile ? 320 : 1024;
          await page.setViewportSize({width:narrowWidth,height:900});
          for (const section of sections) {
            await navigate(page,section,mobile);
            await checkLayout(page,`${mode} ${narrowWidth} light ${section}`);
            if (section==='portafolio') await checkPortfolioAmounts(page);
          }
        }
        assert.deepEqual(errors,[],'No uncaught JavaScript errors or unexpected dialogs');
        assert(requested.has('/stock/AAPL') && requested.has('/macro') && requested.has('/fundamentals/AAPL'));
        reports.push({storage:mode,viewport:viewport.width,sections:sections.length,themes:2,
          checks:['layout','navigation','real charts','watchlist','valuation','notes','same-day buy/sell','backup preview cancellation','heatmap','keyboard shortcuts','layout preferences',...(hosted?['browser journal persistence','verified settlement','journal JSON download']:[])]});
        await context.close();
      }
    }
    console.log(JSON.stringify({browser:'Chromium',result:'passed',reports},null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
