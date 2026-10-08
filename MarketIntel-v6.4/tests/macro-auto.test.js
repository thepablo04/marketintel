const assert = require('assert');
const fs = require('fs');

const source = fs.readFileSync('index.html', 'utf8');
const dashboardSource = fs.readFileSync('static/marketintel-v2.js', 'utf8');

assert(source.includes('requestMacroSnapshot(force=false)'));
assert(source.includes("fetchJSONRetry('/macro', {timeout:60000,cache:'no-store'}, 2)"));
assert(source.includes("if(id==='indicadores'){"));
assert(source.includes("loadMacroSnapshot({force:true})"));
assert(source.includes('if(tickerRefreshInterval) clearInterval(tickerRefreshInterval)'));
assert(source.includes("const quotes = await fetchJSONRetry('/batch'"));
assert(source.includes("fetchJSONRetry('/news', {timeout:30000}, 2)"));
assert(source.includes('newsRefreshInterval = setInterval'));
assert(source.includes('refreshMacroCharts(macro)'));
assert(source.includes("setMacroText('macro-unemployment-current'"));
assert(source.includes('buildSemaforo(macro)'));
assert(!source.includes("{name:'Tasa FED',val:'4.25–4.50%'"));
assert(!source.includes("fetch('/macro', {signal: AbortSignal.timeout(7000)"));
assert(!source.includes("fetch('/macro', {signal: AbortSignal.timeout(6000)"));
assert(dashboardSource.includes("api('/market-sentiment'"));
assert(dashboardSource.includes('sentimentTimer=setInterval'));
assert(dashboardSource.includes('window.MarketIntelPulse.render'));
assert(!dashboardSource.includes('loadSentiment(lastMarketBatch'));
assert(!dashboardSource.includes('score=38+p*17'));
assert(!dashboardSource.includes('spark(up?['));
assert(source.includes('Array.isArray(d.dates) && Array.isArray(d.prices)'));
assert(source.includes('Array.isArray(s.dates) ? s.dates.indexOf(date) : -1'));

console.log('macro auto-load: all tests passed');
