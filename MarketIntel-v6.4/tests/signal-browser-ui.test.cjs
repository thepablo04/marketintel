const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const { IDBFactory } = require('fake-indexeddb');

function pulse() {
  return {
    version: '6.2', updated_at: '2026-09-23T14:05:00Z',
    session: { label: 'Sesión de prueba', date: '2026-09-23', is_open: true, calendar_verified: true, elapsed_minutes: 35, remaining_minutes: 355 },
    intraday: { status: 'ok', score: 68, label: 'Sesgo alcista', quality: 80, coverage: 90, components: [] },
    quotes: { SPY: { usable: true, price: 100, data_at: '2026-09-23T14:05:00Z', status: 'recent' } },
    context: { score: 55, label: 'Mixto', components: [], last_history_date: '2026-09-22' },
    evaluation: { storage: 'browser', model: 'intraday-v6.1', completed_closes: {} }, errors: [],
  };
}
async function browser(hosted, available = true) {
  const dom = new JSDOM('<!doctype html><body><article id="pulse"></article></body>', {
    url: hosted ? 'https://marketintel.example' : 'http://localhost:5050', runScripts: 'outside-only',
  });
  const w = dom.window, calls = [], alerts = [], downloads = [];
  const localHistory = { model: 'intraday-v6.1', summary: { total: 7, evaluated: 2, days: 1, hit_rate: null }, observations: [{ id: 7 }], method: 'Fixture local' };
  if (available) w.indexedDB = new IDBFactory();
  w.Blob = Blob; w.setInterval = () => 0; w.alert = message => alerts.push(message);
  w.fetch = async (url, options) => {
    calls.push({ url, options });
    if (hosted) throw Error('Hosted UI must not request local APIs: ' + url);
    const payload = url === '/local-state' ? { token: 'fixture-token', directory: '/tmp' } : url === '/signal-history' ? localHistory : { status: 'empty' };
    return { ok: true, json: async () => payload };
  };
  w.URL.createObjectURL = blob => { downloads.push({ blob }); return 'blob:fixture'; };
  w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () { downloads.at(-1).name = this.download; };
  for (const filename of ['backup-browser-store.js', 'signal-browser-store.js', 'marketintel-reliability.js']) {
    w.eval(fs.readFileSync('static/' + filename, 'utf8'));
  }
  await new Promise(resolve => setTimeout(resolve, 0));
  return { w, dom, calls, alerts, downloads, localHistory };
}

async function hostedExportAndReload() {
  const env = await browser(true);
  const { w, calls, downloads, alerts } = env;
  try {
    const original = pulse(), result = await w.MarketIntelPulse.prepare(original);
    assert.equal(original.evaluation.summary, undefined, 'preparing a cached pulse must not mutate server data');
    assert.equal(result.evaluation.summary.total, 1);
    const host = w.document.getElementById('pulse');
    w.MarketIntelPulse.render(host, result);
    assert.match(host.textContent, /Seguimiento en este navegador/);
    await host.querySelector('[data-journal]').onclick();
    assert.equal(downloads[0].name, 'MarketIntel-seguimiento.json');
    const exported = JSON.parse(await downloads[0].blob.text());
    assert.equal(exported.observations.length, 1);
    assert.equal(exported.observations[0].reference, 100);
    assert.equal((await w.MarketIntelBrowserSignalStore.createStore().history(true)).summary.total, 1);
    const selfHosted = pulse();
    selfHosted.evaluation = {...selfHosted.evaluation,storage:'local',summary:{total:9999},observations:[{id:9999}]};
    const browserOnly = await w.MarketIntelPulse.prepare(selfHosted);
    assert.equal(browserOnly.evaluation.summary.total,1,'Non-loopback Flask also uses this browser, without borrowing the server journal');
    assert.equal(browserOnly.evaluation.observations,undefined,'Shared server observations are not retained in the browser evaluation');
    assert.deepEqual(calls, []);
    assert.deepEqual(alerts, []);
  } finally { w.close(); }
}

async function storageFailureKeepsPulse() {
  const { w, calls, alerts } = await browser(true, false);
  try {
    const input = pulse(); input.evaluation.summary = { total: 9999 };
    const result = await w.MarketIntelPulse.prepare(input);
    assert.equal(result.intraday.score, 68);
    assert.equal(result.evaluation.summary, null);
    assert.match(result.evaluation.error, /IndexedDB/);
    w.MarketIntelPulse.render(w.document.getElementById('pulse'), result);
    assert.equal(w.document.querySelector('#pulse h2').textContent, 'Sesgo alcista');
    assert.match(w.document.getElementById('pulse').textContent, /IndexedDB/);
    assert.doesNotMatch(w.document.getElementById('pulse').textContent, /9999/);
    assert.deepEqual(calls, []);
    assert.deepEqual(alerts, [], 'background storage failures use inline status rather than blocking dialogs');
  } finally { w.close(); }
}

async function localExportUnchanged() {
  const { w, calls, downloads, alerts, localHistory } = await browser(false, false);
  try {
    const input = pulse(); input.evaluation = { ...localHistory, storage: 'local' };
    assert.equal(await w.MarketIntelPulse.prepare(input), input, 'loopback preserves server SQLite result');
    w.MarketIntelPulse.render(w.document.getElementById('pulse'), input);
    await w.document.querySelector('[data-journal]').onclick();
    assert.deepEqual(JSON.parse(await downloads[0].blob.text()), localHistory);
    const request = calls.find(call => call.url === '/signal-history');
    assert.equal(request.options.headers['X-MarketIntel-Token'], 'fixture-token');
    assert.deepEqual(alerts, []);
  } finally { w.close(); }
}

(async () => {
  for (const test of [hostedExportAndReload, storageFailureKeepsPulse, localExportUnchanged]) {
    await test(); console.log('PASS ' + test.name);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
