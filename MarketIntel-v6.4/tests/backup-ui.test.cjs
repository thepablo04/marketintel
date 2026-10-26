// Run with NODE_PATH pointing to installed jsdom and fake-indexeddb packages.
'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, VirtualConsole } = require('jsdom');
const { IDBFactory } = require('fake-indexeddb');

const sources = ['backup-browser-store.js', 'marketintel-reliability.js'].map(name =>
  fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8'));
const encode = JSON.stringify;
const plain = value => JSON.parse(JSON.stringify(value));
const oldSnapshot = values => ({ version: 1, localStorage: values });

function stored(window) {
  const values = {};
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i);
    values[key] = window.localStorage.getItem(key);
  }
  return values;
}

async function until(check) {
  const deadline = Date.now() + 2000;
  while (!check()) {
    if (Date.now() > deadline) assert.fail('Timed out waiting for backup UI');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  return check();
}

async function harness(t, initial = {}, options = {}) {
  const failures = [], requests = [], alerts = [], downloads = [], blobs = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => {
    // A successful import deliberately reloads the page; jsdom cannot navigate.
    if (!['Not implemented: navigation (except hash changes)', 'Not implemented: navigation to another Document'].includes(error.message)) failures.push(error);
  });
  const dom = new JSDOM('<!doctype html><section id="sec-portafolio"></section>', {
    url: options.url || 'https://marketintel.example/',
    runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole,
  });
  const { window } = dom;
  t.after(() => {
    window.close();
    assert.deepEqual(failures, [], 'Unexpected browser errors');
  });
  window.indexedDB = options.indexedDB || new IDBFactory();
  window.TextEncoder = TextEncoder;
  window.setInterval = () => 0;
  window.alert = message => alerts.push(message);
  window.fetch = async (url, init) => {
    requests.push({ url, init });
    if (options.fetch) return options.fetch(url, init);
    throw new Error('Remote backups must not call backend endpoints: ' + url);
  };
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  window.HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
    this.dispatchEvent(new window.Event('close'));
  };
  window.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:backup-' + blobs.length; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () {
    downloads.push({ filename: this.download, blob: blobs[Number(this.href.split('-').pop()) - 1] });
  };
  Object.entries(initial).forEach(([key, value]) => window.localStorage.setItem(key, value));
  sources.forEach(source => window.eval(source));
  if (window.document.readyState === 'loading') {
    await new Promise(resolve => window.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  }
  const api = window.MarketIntelBackup;
  // Drain the initialization save through the same queue, including failure cases.
  await api.save('automatic').catch(() => {});
  return {
    window, api, alerts, requests, downloads,
    store: window.MarketIntelBrowserBackupStore.createStore(),
    preview: () => window.document.getElementById('mi-backup-preview'),
  };
}

function seed() {
  return {
    pf_portfolios: encode([{ id: 'main', name: 'Principal' }]),
    pf_positions_main: encode([{ ticker: 'AAPL', shares: 2 }]),
    pf_transactions_main: encode([{ id: 'one', type: 'Compra' }, { id: 'two', type: 'Dividendo' }]),
    watchlist: encode(['AAPL', 'MSFT']),
    note_AAPL: 'La tesis original',
    'ficha_note_BRK-B': 'Una nota de ficha',
    hm_custom: encode({ name: 'Mis grupos', sectors: { Tecnología: ['AAPL', 'MSFT'], Finanzas: ['BRK-B'] } }),
    mi_theme: 'dark',
    mi_api_key: 'private-example',
    mi_backup_profile_id: 'test_browser_profile',
  };
}

test('remote snapshots include notes and heatmap, exclude secrets, and survive a new IndexedDB store', async t => {
  const values = {
    ...seed(), 'note_^GSPC': 'Índice', 'ficha_note_GC=F': 'Oro',
    mi_password: 'private-password', mi_token: 'private-token', unrelated: 'outside application',
  };
  const h = await harness(t, values);
  const payload = h.api.snapshot();
  assert.equal(payload.version, 2);
  for (const key of ['note_AAPL', 'ficha_note_BRK-B', 'note_^GSPC', 'ficha_note_GC=F', 'hm_custom']) {
    assert.equal(payload.localStorage[key], values[key]);
    assert.equal(h.api.allowed(key), true);
  }
  for (const key of ['mi_api_key', 'mi_password', 'mi_token', 'mi_backup_profile_id', 'unrelated']) {
    assert.equal(Object.hasOwn(payload.localStorage, key), false, key);
    assert.equal(h.api.allowed(key), false, key);
  }
  const saved = await h.api.save('manual');
  const reopened = h.window.MarketIntelBrowserBackupStore.createStore();
  assert.deepEqual(plain((await reopened.read(saved.id)).localStorage), plain(payload.localStorage));
  assert.equal((await reopened.list()).backups[0].reason, 'manual');
  assert.deepEqual(h.requests, []);
});

test('preview shows before/after counts and changes; cancel leaves data and history untouched', async t => {
  const h = await harness(t, seed());
  const before = stored(h.window), history = plain(await h.store.list());
  const operation = h.api.importSnapshot(oldSnapshot({
    pf_portfolios: encode([{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }]),
    pf_positions_a: encode([{ ticker: 'MSFT' }, { ticker: 'GOOG' }]),
    pf_transactions_a: encode([{ id: 'three' }]),
    watchlist: encode(['MSFT']),
  }), true);
  const dialog = h.preview();
  assert.ok(dialog && dialog.open);
  const counts = Object.fromEntries(Array.from(dialog.querySelectorAll('tbody tr'), row => [
    row.querySelector('th').textContent,
    Array.from(row.querySelectorAll('td'), cell => Number(cell.textContent)),
  ]));
  assert.deepEqual(counts, {
    Cuentas: [1, 2], Operaciones: [2, 1], Posiciones: [1, 2],
    Notas: [2, 2], 'Grupos del heatmap': [2, 2], 'Símbolos en watchlist': [2, 1],
  });
  assert.match(dialog.textContent, /se eliminará/);
  assert.match(dialog.textContent, /se añadirá/);
  assert.match(dialog.textContent, /se reemplazará/);
  assert.match(dialog.textContent, /se conservarán/i);
  dialog.querySelector('[data-cancel]').click();
  await operation;
  assert.equal(h.preview(), null);
  assert.deepEqual(stored(h.window), before);
  assert.deepEqual(plain(await h.store.list()), history);
});

test('restore through backup list commits a durable prior copy before replacing data on a remote host', async t => {
  const h = await harness(t, seed());
  const desired = plain(h.api.snapshot().localStorage);
  const backup = await h.api.save('manual');
  h.window.localStorage.setItem('note_AAPL', 'La nota modificada');
  h.window.localStorage.setItem('pf_positions_main', encode([{ ticker: 'TSLA', shares: 10 }]));
  h.window.localStorage.setItem('mi_theme', 'light');
  const original = plain(h.api.snapshot().localStorage);
  await h.api.showBackups();
  const dialog = h.window.document.getElementById('mi-backups-dialog');
  assert.match(dialog.textContent, /este navegador/i);
  const button = dialog.querySelector('[data-restore="' + backup.id + '"]');
  assert.ok(button);
  const operation = button.onclick();
  const preview = await until(h.preview);
  assert.equal(h.window.localStorage.getItem('note_AAPL'), original.note_AAPL);
  preview.querySelector('[data-confirm]').click();
  await operation;
  assert.deepEqual(plain(h.api.snapshot().localStorage), desired);
  const prior = (await h.store.list()).backups[0];
  assert.equal(prior.reason, 'before-restore');
  const reopened = h.window.MarketIntelBrowserBackupStore.createStore();
  assert.deepEqual(plain((await reopened.read(prior.id)).localStorage), original);
  assert.deepEqual(h.alerts, []);
  assert.deepEqual(h.requests, []);
});

for (const restore of [false, true]) {
  test((restore ? 'restore replaces' : 'import merges') + ' old data while preserving unrepresented notes, heatmap and credentials', async t => {
    const h = await harness(t, seed());
    const original = plain(h.api.snapshot().localStorage);
    const operation = h.api.importSnapshot(oldSnapshot({
      watchlist: encode(['NVDA']),
      mi_theme: 'light',
      mi_api_key: 'must-not-import',
    }), restore);
    h.preview().querySelector('[data-confirm]').click();
    await operation;
    assert.equal(h.window.localStorage.getItem('watchlist'), encode(['NVDA']));
    assert.equal(h.window.localStorage.getItem('mi_theme'), 'light');
    assert.equal(h.window.localStorage.getItem('pf_positions_main'), restore ? null : original.pf_positions_main);
    for (const key of ['note_AAPL', 'ficha_note_BRK-B', 'hm_custom']) {
      assert.equal(h.window.localStorage.getItem(key), original[key]);
    }
    assert.equal(h.window.localStorage.getItem('mi_api_key'), 'private-example');
    assert.equal(h.window.localStorage.getItem('mi_backup_profile_id'), 'test_browser_profile');
    const prior = (await h.store.list()).backups[0];
    assert.equal(prior.reason, restore ? 'before-restore' : 'before-import');
    assert.deepEqual(plain((await h.store.read(prior.id)).localStorage), original);
  });
}

test('malformed heatmap and unsupported snapshots fail before any storage mutation or prior backup', async t => {
  const h = await harness(t, seed());
  const before = stored(h.window), history = plain(await h.store.list());
  for (const value of ['not-json', 'null', '{}', '[]', '{"sectors":[]}', '{"sectors":{"Bad":"AAPL"}}', '{"sectors":{"Bad":[123]}}']) {
    await assert.rejects(h.api.importSnapshot(oldSnapshot({ hm_custom: value })), /JSON|heatmap|valid|Unexpected/i);
    assert.equal(h.preview(), null);
  }
  await assert.rejects(h.api.importSnapshot({ version: 999, localStorage: { watchlist: '[]' } }), /versión/);
  assert.deepEqual(stored(h.window), before);
  assert.deepEqual(plain(await h.store.list()), history);
});

test('web backups reject oversized notes and malformed heatmap instead of saving unrestorable copies', async t => {
  const h = await harness(t, seed());
  const history = plain(await h.store.list());
  for (const [key, value, message] of [
    ['note_AAPL', 'n'.repeat(4_000_001), /Contenido de copia inválido/],
    ['hm_custom', encode({ sectors: { Invalid: 'AAPL' } }), /heatmap/],
  ]) {
    const original = h.window.localStorage.getItem(key);
    h.window.localStorage.setItem(key, value);
    await assert.rejects(h.api.save('manual'), message);
    assert.deepEqual(plain(await h.store.list()), history, 'Invalid data must not create a backup');
    assert.equal(h.window.localStorage.getItem(key), value, 'Failed save must not alter current data');
    assert.match(h.window.document.getElementById('mi-backup-status').textContent, /Respaldo pendiente/);
    h.window.localStorage.setItem(key, original);
  }
  assert.deepEqual(h.requests, []);
});

test('a new empty browser saves harmlessly without creating an unusable backup', async t => {
  const h = await harness(t);
  const result = await h.api.save('manual');
  assert.equal(result.status, 'empty');
  assert.equal(result.id, null);
  assert.deepEqual(plain((await h.store.list()).backups), []);
  assert.match(h.window.document.getElementById('mi-backup-status').textContent, /Sin datos para respaldar/);
  assert.equal(h.window.document.getElementById('mi-backup-status').classList.contains('is-error'), false);
  await assert.rejects(h.api.importSnapshot(oldSnapshot({})), /No hay datos compatibles/);
  assert.equal(h.preview(), null);
  assert.deepEqual(h.alerts, []);
  assert.deepEqual(h.requests, []);
});

test('a localStorage quota failure rolls back partial writes and keeps the durable prior backup', async t => {
  const h = await harness(t, seed());
  const before = stored(h.window), original = plain(h.api.snapshot().localStorage);
  const changed = encode(['NVDA']);
  const nativeSet = h.window.Storage.prototype.setItem;
  let failureInjected = false;
  h.window.Storage.prototype.setItem = function (key, value) {
    if (!failureInjected && key === 'watchlist' && value === changed) {
      failureInjected = true;
      throw new h.window.DOMException('Storage full', 'QuotaExceededError');
    }
    return nativeSet.call(this, key, value);
  };
  const operation = h.api.importSnapshot(oldSnapshot({ mi_theme: 'light', watchlist: changed }), true);
  const rejected = assert.rejects(operation, /se restauró el estado anterior/);
  h.preview().querySelector('[data-confirm]').click();
  await rejected;
  assert.equal(failureInjected, true);
  assert.deepEqual(stored(h.window), before);
  const prior = (await h.store.list()).backups[0];
  assert.equal(prior.reason, 'before-restore');
  assert.deepEqual(plain((await h.store.read(prior.id)).localStorage), original);
});

test('blocked IndexedDB prevents destructive changes and reports failure without backend fallback', async t => {
  const h = await harness(t, seed(), {
    indexedDB: { open() { const error = new Error('Storage blocked'); error.name = 'SecurityError'; throw error; } },
  });
  const before = stored(h.window);
  assert.equal(await h.api.beforeMutation('before-delete'), false);
  const operation = h.api.importSnapshot(oldSnapshot({ watchlist: '[]' }), true);
  h.preview().querySelector('[data-confirm]').click();
  await operation;
  assert.deepEqual(stored(h.window), before);
  assert.equal(h.alerts.length, 2);
  h.alerts.forEach(message => assert.match(message, /No se hizo el cambio porque falló la copia/));
  assert.match(h.window.document.getElementById('mi-backup-status').textContent, /Respaldo pendiente/);
  assert.deepEqual(h.requests, []);
});

test('JSON export and import controls retain notes and heatmap for moving between local and hosted app', async t => {
  const h = await harness(t, seed());
  h.window.document.querySelector('[data-backup-export]').click();
  assert.equal(h.downloads.length, 1);
  assert.match(h.downloads[0].filename, /\.json$/);
  const json = await new Promise((resolve, reject) => {
    const reader = new h.window.FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsText(h.downloads[0].blob);
  });
  const exported = JSON.parse(json);
  assert.equal(exported.localStorage.note_AAPL, seed().note_AAPL);
  assert.equal(exported.localStorage.hm_custom, seed().hm_custom);
  assert.equal(Object.hasOwn(exported.localStorage, 'mi_api_key'), false);
  const input = h.window.document.querySelector('[data-backup-file]');
  let pickerOpened = false;
  input.click = () => { pickerOpened = true; };
  h.window.document.querySelector('[data-backup-import]').click();
  assert.equal(pickerOpened, true);
  h.window.localStorage.setItem('note_AAPL', 'Changed since export');
  const file = new h.window.File([json], 'portable.json', { type: 'application/json' });
  file.text = async () => json;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  const operation = input.onchange({ target: input });
  const preview = await until(h.preview);
  preview.querySelector('[data-confirm]').click();
  await operation;
  assert.equal(h.window.localStorage.getItem('note_AAPL'), seed().note_AAPL);
  assert.equal(input.value, '');
  assert.equal((await h.store.list()).backups[0].reason, 'before-import');
  assert.deepEqual(h.requests, []);
});

test('localhost keeps authenticated server backups and never opens IndexedDB', async t => {
  const rows = [];
  let nextId = 1;
  const h = await harness(t, seed(), {
    url: 'http://localhost:5000/',
    indexedDB: { open() { assert.fail('Local backups should use the server'); } },
    fetch: async (url, init = {}) => {
      const response = data => ({ ok: true, json: async () => data });
      if (url === '/local-state') return response({ token: 'local-test-token', directory: '/tmp/marketintel-test' });
      assert.equal(init.headers['X-MarketIntel-Token'], 'local-test-token');
      if (url === '/local-backups' && init.method === 'POST') {
        const data = JSON.parse(init.body);
        const row = { id: nextId++, created_at: new Date().toISOString(), reason: data.reason, snapshot: data.snapshot };
        rows.unshift(row);
        return response({ status: 'saved', id: row.id, created_at: row.created_at });
      }
      if (url === '/local-backups') return response({ backups: rows, next_before: null });
      assert.fail('Unexpected local backup request: ' + url);
    },
  });
  await h.api.save('manual');
  assert.equal(rows[0].snapshot.localStorage.note_AAPL, seed().note_AAPL);
  assert.equal(rows[0].snapshot.localStorage.hm_custom, seed().hm_custom);
  await h.api.showBackups();
  assert.match(h.window.document.getElementById('mi-backups-dialog').textContent, /Respaldos locales/);
  assert.equal(h.requests.filter(request => request.url === '/local-state').length, 1);
  assert.equal(h.window.document.querySelectorAll('[data-restore]').length, rows.length);
  assert.deepEqual(h.alerts, []);
});
