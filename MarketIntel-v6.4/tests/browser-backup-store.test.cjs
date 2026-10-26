const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { IDBFactory, IDBObjectStore } = require('fake-indexeddb');
const { createStore } = require('../static/backup-browser-store.js');

function snapshot(values = { note_AAPL: 'Tesis de inversión 🚀', hm_custom: '["AAPL"]' }) {
  return { version: 2, exported_at: '2000-01-01T00:00:00.000Z', localStorage: values };
}

async function browserGlobals() {
  const browser = { indexedDB: new IDBFactory() };
  const context = { globalThis: browser, Blob };
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/backup-browser-store.js'), 'utf8'), context);
  const store = browser.MarketIntelBrowserBackupStore.createStore();
  const saved = await store.save(snapshot(), 'browser-one');
  assert.equal(saved.status, 'saved');
  assert.equal((await store.read(saved.id)).localStorage.note_AAPL, snapshot().localStorage.note_AAPL);
  Object.defineProperty(browser, 'indexedDB', { get() { throw new DOMException('denied', 'SecurityError'); } });
  await assert.rejects(browser.MarketIntelBrowserBackupStore.createStore().list(), /bloqueó/);
}

async function basicOperations() {
  const factory = new IDBFactory();
  const store = createStore(factory);
  assert.deepEqual(await store.list(), { backups: [], next_before: null });
  assert.deepEqual(await store.save(snapshot({}), 'browser-one'), { status: 'empty', id: null, created_at: null });
  const original = snapshot();
  const pending = store.save(original, 'browser-one', 'manual');
  original.localStorage.note_AAPL = 'changed after save was called';
  const saved = await pending;
  assert.equal(saved.status, 'saved');
  assert.ok(Number.isSafeInteger(saved.id));
  const recovered = await store.read(saved.id);
  assert.deepEqual(recovered.localStorage, snapshot().localStorage);
  assert.equal(recovered.version, 2);
  assert.equal(recovered.exported_at, saved.created_at);
  assert.notEqual(recovered.exported_at, original.exported_at);
  recovered.localStorage.note_AAPL = 'changed after reading';
  assert.deepEqual((await store.read(saved.id)).localStorage, snapshot().localStorage);
  const page = await store.list();
  assert.deepEqual(Object.keys(page.backups[0]).sort(), ['created_at', 'id', 'profile', 'reason', 'size_bytes']);
  assert.equal(page.backups[0].profile, 'browser-one');
  assert.equal(page.backups[0].reason, 'manual');
  assert.equal(page.backups[0].size_bytes, Buffer.byteLength(JSON.stringify({ hm_custom: '["AAPL"]', note_AAPL: 'Tesis de inversión 🚀' })));
  assert.equal(page.next_before, null);
  assert.deepEqual(await createStore(factory).read(saved.id), await store.read(saved.id));
  await assert.rejects(store.read(saved.id + 100), /No existe esa copia/);
  await assert.rejects(store.read(0), /Identificador/);
  await assert.rejects(store.list(-1), /Identificador/);
  await assert.rejects(store.save({ localStorage: [] }, 'browser-one'), /localStorage/);
  await assert.rejects(store.save(snapshot({ note_AAPL: null }), 'browser-one'), /valor/);
}

async function deduplication() {
  const store = createStore(new IDBFactory());
  const first = await store.save(snapshot({ b: 'two', a: 'one' }), 'browser-one');
  const reordered = await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-one', 'automatic');
  assert.deepEqual(reordered, { status: 'unchanged', id: first.id, created_at: first.created_at });
  const otherProfile = await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-two');
  assert.equal(otherProfile.status, 'saved');
  assert.notEqual(otherProfile.id, first.id);
  const manual = await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-one', 'manual');
  assert.equal(manual.status, 'saved');
  assert.notEqual(manual.id, first.id);
  assert.equal((await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-one')).id, manual.id);
  const protectedMutation = await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-one', 'before-restore');
  assert.equal(protectedMutation.status, 'saved');
  const changed = await store.save(snapshot({ a: 'changed' }), 'browser-one');
  const reverted = await store.save(snapshot({ a: 'one', b: 'two' }), 'browser-one');
  assert.equal(changed.status, 'saved');
  assert.equal(reverted.status, 'saved', 'only the latest state for a profile is deduplicated');
}

async function pagination() {
  const store = createStore(new IDBFactory());
  for (let index = 0; index < 205; index += 1) {
    await store.save(snapshot({ note_AAPL: String(index) }), 'browser-one', 'manual');
  }
  const first = await store.list();
  assert.equal(first.backups.length, 100);
  assert.equal(first.backups[0].id, 205);
  assert.equal(first.next_before, 106);
  const second = await store.list(first.next_before);
  assert.equal(second.backups.length, 100);
  assert.equal(second.backups[0].id, 105);
  assert.equal(second.next_before, 6);
  const last = await store.list(second.next_before);
  assert.equal(last.backups.length, 5);
  assert.equal(last.next_before, null);
  const ids = [...first.backups, ...second.backups, ...last.backups].map(row => row.id);
  assert.equal(new Set(ids).size, 205);
  assert.equal(ids[ids.length - 1], 1);
  assert.equal((await store.list(1)).backups.length, 0);
  const exactlyFull = await store.list(101);
  assert.equal(exactlyFull.backups.length, 100);
  assert.equal(exactlyFull.next_before, null, 'a full final page must not offer an empty next page');
}

async function simultaneousSaves() {
  const factory = new IDBFactory();
  const stores = [createStore(factory), createStore(factory)];
  const results = await Promise.all(Array.from({ length: 20 }, (_, index) => stores[index % 2].save(snapshot(), 'browser-one')));
  assert.equal(results.filter(row => row.status === 'saved').length, 1);
  assert.equal(results.filter(row => row.status === 'unchanged').length, 19);
  assert.equal(new Set(results.map(row => row.id)).size, 1);
  const manual = await Promise.all(Array.from({ length: 12 }, (_, index) => stores[index % 2].save(snapshot(), 'browser-one', 'manual')));
  assert.equal(new Set(manual.map(row => row.id)).size, 12);
  assert.ok(manual.every(row => row.status === 'saved'));
  assert.equal((await stores[0].list()).backups.length, 13);
}

async function reopenAfterVersionChange() {
  const factory = new IDBFactory();
  const store = createStore(factory);
  const saved = await store.save(snapshot(), 'browser-one');
  await new Promise((resolve, reject) => {
    const request = factory.open('MarketIntelBrowserBackups', 2);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('The store did not close its old connection'));
    request.onsuccess = () => { request.result.close(); resolve(); };
  });
  assert.deepEqual((await store.read(saved.id)).localStorage, snapshot().localStorage);
  assert.equal((await store.save(snapshot(), 'browser-one')).status, 'unchanged');
}

async function abortedTransaction() {
  const store = createStore(new IDBFactory());
  const existing = await store.save(snapshot(), 'browser-one');
  const nativePut = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (...args) {
    const request = nativePut.apply(this, args);
    if (this.name === 'profiles') request.addEventListener('success', () => this.transaction.abort());
    return request;
  };
  try {
    await assert.rejects(store.save(snapshot({ note_AAPL: 'New state' }), 'browser-one'), /canceló/);
  } finally { IDBObjectStore.prototype.put = nativePut; }
  const rows = (await store.list()).backups;
  assert.equal(rows.length, 1, 'an aborted commit must not leave a backup row');
  assert.equal(rows[0].id, existing.id);
  assert.equal((await store.save(snapshot(), 'browser-one')).status, 'unchanged', 'the profile pointer must roll back too');
  assert.equal((await store.save(snapshot({ note_AAPL: 'New state' }), 'browser-one')).status, 'saved');
}

async function storageErrors() {
  await assert.rejects(createStore(null).list(), /IndexedDB no está disponible/);
  await assert.rejects(createStore({ open() { throw new DOMException('denied', 'SecurityError'); } }).list(), /bloqueó/);
  const store = createStore(new IDBFactory());
  await store.list();
  const nativeAdd = IDBObjectStore.prototype.add;
  IDBObjectStore.prototype.add = function () { throw new DOMException('full', 'QuotaExceededError'); };
  try { await assert.rejects(store.save(snapshot(), 'browser-one'), /No hay espacio disponible/); }
  finally { IDBObjectStore.prototype.add = nativeAdd; }
  assert.equal((await store.list()).backups.length, 0);
  assert.equal((await store.save(snapshot(), 'browser-one')).status, 'saved');
  const factory = new IDBFactory();
  let attempts = 0;
  const retryStore = createStore({ open(...args) {
    attempts += 1;
    if (attempts === 1) throw new DOMException('temporarily denied', 'SecurityError');
    return factory.open(...args);
  } });
  await assert.rejects(retryStore.list(), /bloqueó/);
  assert.deepEqual(await retryStore.list(), { backups: [], next_before: null });
}

(async () => {
  for (const test of [browserGlobals, basicOperations, deduplication, pagination, simultaneousSaves, reopenAfterVersionChange, abortedTransaction, storageErrors]) {
    await test();
    console.log('browser-backup-store: ' + test.name + ' passed');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
