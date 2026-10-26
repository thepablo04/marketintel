const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { IDBFactory, IDBObjectStore } = require('fake-indexeddb');
const { createStore, MODEL_VERSION } = require('../static/signal-browser-store.js');

function pulse(day = '2026-09-23', elapsed = 5, score = 68, reference = 100) {
  return {
    session: { date: day, is_open: true, calendar_verified: true, elapsed_minutes: elapsed, remaining_minutes: 390 - elapsed },
    intraday: { status: 'ok', score, label: 'Fixture' },
    quotes: { SPY: { usable: true, price: reference, data_at: day + 'T13:35:00Z' } },
    evaluation: { storage: 'browser', model: MODEL_VERSION, completed_closes: {} },
  };
}
function closing(closes, day = '2026-09-24') {
  const result = pulse(day);
  result.session.is_open = false;
  result.evaluation.completed_closes = closes;
  return result;
}
function rawOpen(factory, version, upgrade) {
  return new Promise((resolve, reject) => {
    const request = factory.open('MarketIntelSignalJournal', version);
    request.onupgradeneeded = () => { if (upgrade) upgrade(request.result, request.transaction); };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(Error('Connections did not close on versionchange'));
    request.onsuccess = () => resolve(request.result);
  });
}
function rawTransaction(db, mode, work) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('observations', mode);
    tx.oncomplete = resolve;
    tx.onabort = () => reject(tx.error);
    work(tx.objectStore('observations'));
  });
}

async function recordingWindows() {
  for (const [elapsed, expected] of [[4.99, 0], [5, 1], [10, 1], [10.01, 0], [29.99, 0], [30, 1], [40, 1], [40.01, 0], [330, 1], [340, 1], [345, 0], [360, 0]]) {
    const store = createStore(new IDBFactory());
    const result = await store.processPulse(pulse(undefined, elapsed));
    assert.equal(result.summary.total, expected, 'half-hour recording boundary: ' + elapsed);
    if (expected) assert.equal(result.observations[0].bucket, Math.floor(elapsed / 30));
  }
  for (const mutate of [
    p => { p.session.remaining_minutes = 44.99; },
    p => { p.session.is_open = false; },
    p => { p.session.calendar_verified = false; },
    p => { p.session.date = '2026-02-31'; },
    p => { p.session.elapsed_minutes = '5'; },
    p => { p.intraday.status = 'insufficient'; },
    p => { p.intraday.score = null; },
    p => { p.intraday.score = NaN; },
    p => { p.intraday.score = 101; },
    p => { p.quotes.SPY.usable = false; },
    p => { p.quotes.SPY.price = 0; },
    p => { p.quotes.SPY.price = Infinity; },
    p => { p.quotes.SPY.price = '100'; },
    p => { p.quotes.SPY.data_at = null; },
  ]) {
    const store = createStore(new IDBFactory()), input = pulse();
    mutate(input);
    assert.equal((await store.processPulse(input)).summary.total, 0, mutate.toString());
  }
  const edge = pulse(); edge.session.remaining_minutes = 45;
  assert.equal((await createStore(new IDBFactory()).processPulse(edge)).summary.total, 1);
}

async function immutableConcurrentObservations() {
  const factory = new IDBFactory(), stores = [createStore(factory), createStore(factory)];
  const original = pulse();
  const pending = stores[0].processPulse(original);
  original.intraday.score = 12; original.quotes.SPY.price = 999;
  const first = await pending;
  assert.equal(first.observations[0].score, 68);
  assert.equal(first.observations[0].reference, 100);
  const results = await Promise.all(Array.from({ length: 20 }, (_, n) => stores[n % 2].processPulse(pulse(undefined, 6, n, n + 1))));
  assert(results.every(result => result.summary.total === 1));
  assert.deepEqual((await stores[1].history()).observations[0], first.observations[0]);
  await stores[0].processPulse(pulse(undefined, 30, 35, 98));
  assert.equal((await createStore(factory).history()).summary.total, 2, 'survives reload/new client');
  const copy = await stores[0].history(); copy.observations[0].score = 99;
  assert.equal((await stores[0].history()).observations[0].score, 35, 'read result cannot mutate stored observation');
}

async function verifiedSettlementAndSummary() {
  const store = createStore(new IDBFactory());
  await store.processPulse(pulse(undefined, 5, 60));
  await store.processPulse(pulse(undefined, 30, 40));
  await store.processPulse(pulse(undefined, 60, 50));
  const sameDay = closing({ '2026-09-23': 101 }, '2026-09-23');
  assert.equal((await store.processPulse(sameDay)).summary.evaluated, 0, 'never settles today, including after close');
  const unverified = closing({ '2026-09-23': 101 }); unverified.session.calendar_verified = false;
  assert.equal((await store.processPulse(unverified)).summary.evaluated, 0);
  for (const invalid of [0, -1, '101', Infinity, NaN, null]) {
    assert.equal((await store.processPulse(closing({ '2026-09-23': invalid }))).summary.evaluated, 0);
  }
  const result = await store.processPulse(closing({ '2026-09-23': 101, '2026-09-25': 150, 'invalid': 101 }));
  assert.deepEqual(result.summary, { total: 3, evaluated: 3, days: 1, directional: 2, hits: 1, hit_rate: 50 });
  assert.deepEqual(result.observations.map(row => [row.actual, row.hit, row.return_pct]), [['alcista', null, 1], ['alcista', 0, 1], ['alcista', 1, 1]]);
  const later = await store.processPulse(closing({ '2026-09-23': 50 }));
  assert.deepEqual(later, result, 'settlement cannot revise a completed result');
  const forbidden = pulse('2026-09-25'); forbidden.evaluation.model = 'future';
  await assert.rejects(store.processPulse(forbidden), /compatible/);
  forbidden.evaluation.model = MODEL_VERSION; forbidden.evaluation.storage = 'unknown';
  await assert.rejects(store.processPulse(forbidden), /compatible/);
  assert.deepEqual(await store.history(), result, 'invalid contract must not change existing observations');
}

async function neutralAndBearishRules() {
  const store = createStore(new IDBFactory());
  await store.processPulse(pulse('2026-09-21', 5, 40));
  await store.processPulse(pulse('2026-09-22', 5, 65));
  const result = await store.processPulse(closing({ '2026-09-21': 99, '2026-09-22': 100.05 }));
  assert.deepEqual(result.observations.map(row => [row.actual, row.hit, row.return_pct]), [['mixto', 0, 0.05], ['bajista', 1, -1]]);
  assert.equal(result.summary.days, 2);
  const empty = await createStore(new IDBFactory()).history(true);
  assert.deepEqual(empty.summary, { total: 0, evaluated: 0, days: 0, directional: 0, hits: null, hit_rate: null });
}

async function completeExportAndModelIsolation() {
  const factory = new IDBFactory(), store = createStore(factory);
  for (let i = 0; i < 105; i++) {
    await store.processPulse(pulse('2026-09-' + String(1 + Math.floor(i / 10)).padStart(2, '0'), 5 + (i % 10) * 30, i === 0 ? 70 : 30));
  }
  const ordinary = await store.history(), complete = await store.history(true);
  assert.equal(ordinary.summary.total, 105);
  assert.equal(ordinary.observations.length, 100);
  assert.equal(complete.observations.length, 105);
  assert.equal(complete.observations[0].id, 105);
  assert.equal(complete.observations.at(-1).id, 1);
  const db = await rawOpen(factory, 1);
  await rawTransaction(db, 'readwrite', records => records.add({ ...complete.observations[0], id: 1000, model: 'future' }));
  db.close();
  assert.deepEqual(await store.history(true), complete, 'other model observations never contaminate metrics');
  // Python round(1 / 16 * 100, 1) is 6.2; mirror the local summary.
  const rounding = createStore(new IDBFactory());
  for (let i = 0; i < 16; i++) await rounding.processPulse(pulse('2026-09-' + String(1 + Math.floor(i / 8)).padStart(2, '0'), 5 + (i % 8) * 30, i === 0 ? 70 : 30));
  assert.equal((await rounding.processPulse(closing({ '2026-09-01': 101, '2026-09-02': 101 }))).summary.hit_rate, 6.2);
}

async function errorsAndSchemaPreserveData() {
  await assert.rejects(createStore(null).history(), /IndexedDB/);
  const browser = {};
  Object.defineProperty(browser, 'indexedDB', { get() { throw new DOMException('denied', 'SecurityError'); } });
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/signal-browser-store.js'), 'utf8'), { globalThis: browser });
  await assert.rejects(browser.MarketIntelBrowserSignalStore.createStore().history(), /bloqueó/);
  const factory = new IDBFactory(), store = createStore(factory);
  await store.processPulse(pulse());
  const original = IDBObjectStore.prototype.add;
  try {
    IDBObjectStore.prototype.add = function () { throw new DOMException('quota', 'QuotaExceededError'); };
    await assert.rejects(store.processPulse(pulse(undefined, 30)), /espacio/);
  } finally { IDBObjectStore.prototype.add = original; }
  assert.equal((await store.history()).summary.total, 1, 'failed transaction does not add an observation');
  const future = await rawOpen(factory, 2);
  future.close();
  await assert.rejects(store.history(), /más reciente/);
  const stillThere = await rawOpen(factory, 2);
  let count;
  await rawTransaction(stillThere, 'readonly', rows => { const request = rows.count(); request.onsuccess = () => { count = request.result; }; });
  assert.equal(count, 1, 'newer schema is never deleted or downgraded');
  stillThere.close();
  const brokenFactory = new IDBFactory();
  const incompatible = await rawOpen(brokenFactory, 1, db => db.createObjectStore('observations', { keyPath: 'id' }));
  incompatible.close();
  await assert.rejects(createStore(brokenFactory).history(), /formato.*compatible/);
}

(async () => {
  const tests = [recordingWindows, immutableConcurrentObservations, verifiedSettlementAndSummary, neutralAndBearishRules, completeExportAndModelIsolation, errorsAndSchemaPreserveData];
  for (const test of tests) { await test(); console.log('PASS ' + test.name); }
  console.log(tests.length + ' signal journal test groups passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
