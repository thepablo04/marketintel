'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const Core = require('../static/sync-core.js');
const Portfolio = require('../static/portfolio-core.js');

function account(id = 'default', values = {}, transactions = []) {
  return {profile: {id, name: id === 'default' ? 'real' : id, type: 'Standard', openingCash: 0, currency: 'USD', ledgerVersion: 3, ...values}, transactions};
}
function tx(id, type = 'Compra', sequence = 0, values = {}) {
  return Portfolio.normalizeTransaction({id, date: '2026-10-01T00:00:00.000Z', type, ticker: 'AAPL', shares: 1, price: 100, sequence, ...values}, 0);
}
function snap(accounts = {}, notes = {}, watchlist = []) { return {version: 1, accounts, notes, watchlist}; }
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function storage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {getItem: key => data.has(key) ? data.get(key) : null,
    setItem: (key, value) => data.set(key, String(value)), removeItem: key => data.delete(key),
    key: index => Array.from(data.keys())[index] ?? null, get length() { return data.size; }};
}
function apply(store, plan) {
  plan.remove.forEach(key => store.removeItem(key));
  Object.entries(plan.set).forEach(([key, value]) => store.setItem(key, value));
}

test('capture syncs authoritative portfolio, notes and membership only', () => {
  const a = account('default', {openingCash: 500}, [tx('buy', 'Compra', 1)]);
  const local = storage({pf_portfolios: JSON.stringify([a.profile]), pf_transactions_default: JSON.stringify(a.transactions),
    pf_positions_default: '[{"ticker":"SECRET"}]', pf_active_id: 'default',
    note_AAPL: 'Mi análisis', ficha_note_AAPL: 'Mi ficha', watchlist: '["MSFT","AAPL","MSFT"]',
    mi_theme: 'light', hm_custom: '{"sector":["TSLA"]}', chat_api_key: 'credential',
    marketintel_sync_key: 'private-key', marketintel_sync_baseline: 'large-private-state',
    pf_quotes_default: '{"AAPL":999}', search_history: '["NVIDIA"]'});
  const captured = Core.capture(local);
  assert.deepEqual(captured.accounts.default, a);
  assert.deepEqual(captured.notes, {ficha_note_AAPL: 'Mi ficha', note_AAPL: 'Mi análisis'});
  assert.deepEqual(captured.watchlist, ['AAPL', 'MSFT']);
  assert.equal(JSON.stringify(captured).includes('credential'), false);
  assert.equal(JSON.stringify(captured).includes('private-key'), false);
  assert.deepEqual(Object.keys(captured).sort(), ['accounts', 'notes', 'version', 'watchlist']);
});

test('independent account and note edits merge while inputs stay untouched', () => {
  const base = snap({one: account('one'), two: account('two')}, {note_AAPL: 'a', note_MSFT: 'b'}, ['AAPL', 'TSLA']);
  const local = clone(base), remote = clone(base);
  local.accounts.one.transactions.push(tx('buy'));
  local.notes.note_AAPL = 'local';
  local.watchlist = ['TSLA', 'MSFT'];
  remote.accounts.two.profile.name = 'Remota';
  remote.notes.note_MSFT = 'remote';
  remote.watchlist = ['AAPL', 'TSLA', 'NVDA'];
  const before = JSON.stringify([base, local, remote]);
  const merged = Core.merge(base, local, remote);
  assert.equal(merged.conflicts.length, 0);
  assert.equal(merged.snapshot.accounts.one.transactions[0].id, 'buy');
  assert.equal(merged.snapshot.accounts.two.profile.name, 'Remota');
  assert.deepEqual(merged.snapshot.notes, {note_AAPL: 'local', note_MSFT: 'remote'});
  assert.deepEqual(merged.snapshot.watchlist, ['MSFT', 'NVDA', 'TSLA']);
  assert.equal(JSON.stringify([base, local, remote]), before);
});

test('same account offline trade edits conflict, preserving same-day sequence', () => {
  const base = snap({one: account('one', {openingCash: 1000}, [tx('buy', 'Compra', 1)])});
  const local = clone(base), remote = clone(base);
  local.accounts.one.transactions.unshift(tx('sell', 'Venta', 2));
  remote.accounts.one.transactions.unshift(tx('deposit', 'Depósito', 2, {ticker: '', amount: 500}));
  const result = Core.merge(base, local, remote);
  assert.equal(result.conflicts.length, 1);
  assert.equal(result.conflicts[0].id, 'account:one');
  assert.equal(result.conflicts[0].label, 'one');
  assert.deepEqual(result.snapshot.accounts.one.transactions.map(t => t.id), ['sell', 'buy']);
  const both = Core.merge(base, local, remote, {'account:one': 'both'});
  assert.equal(both.conflicts.length, 0);
  assert.equal(Object.keys(both.snapshot.accounts).length, 2);
  const otherId = Object.keys(both.snapshot.accounts).find(id => id !== 'one');
  assert.match(otherId, /^sync_[a-z0-9_]+$/);
  assert.equal(both.snapshot.accounts[otherId].profile.id, otherId);
  assert.equal(both.snapshot.accounts[otherId].profile.name, 'one (otra versión)');
  assert.deepEqual(both.snapshot.accounts[otherId].transactions.map(t => t.id), ['deposit', 'buy']);
  assert.deepEqual(Core.merge(base, local, remote, {'account:one': 'both'}), both);
  const ledger = Portfolio.processLedger(both.snapshot.accounts.one.transactions, 1000);
  assert.equal(ledger.warnings.length, 0);
  assert.equal(ledger.positions.length, 0);
  assert.equal(ledger.cash, 1000);
});

test('deletions propagate, but delete/edit requires an explicit choice', () => {
  const base = snap({one: account('one'), two: account('two')}, {note_AAPL: 'antes'});
  const local = clone(base), remote = clone(base);
  delete local.accounts.two;
  delete local.notes.note_AAPL;
  assert.equal(Core.merge(base, local, remote).conflicts.length, 0);
  assert.equal(Core.merge(base, local, remote).snapshot.accounts.two, undefined);
  assert.equal(Core.merge(base, local, remote).snapshot.notes.note_AAPL, undefined);
  remote.accounts.two.profile.name = 'Nueva';
  remote.notes.note_AAPL = 'editada';
  const conflict = Core.merge(base, local, remote);
  assert.deepEqual(conflict.conflicts.map(c => c.id), ['account:two', 'note:note_AAPL']);
  assert.equal(conflict.conflicts[0].local, null);
  const keepRemote = Core.merge(base, local, remote, {'account:two': 'remote', 'note:note_AAPL': 'both'});
  assert.equal(keepRemote.snapshot.accounts.two.profile.name, 'Nueva');
  assert.equal(keepRemote.snapshot.notes.note_AAPL, 'editada');
  const keepLocal = Core.merge(base, local, remote, {'account:two': 'local', 'note:note_AAPL': 'local'});
  assert.equal(keepLocal.conflicts.length, 0);
  assert.equal(keepLocal.snapshot.accounts.two, undefined);
});

test('conflicting note texts can retain both full versions', () => {
  const base = snap({}, {ficha_note_AAPL: 'base'});
  const local = snap({}, {ficha_note_AAPL: 'local <script>safe as text</script>'});
  const remote = snap({}, {ficha_note_AAPL: 'remota'});
  const result = Core.merge(base, local, remote, {'note:ficha_note_AAPL': 'both'});
  assert.equal(result.conflicts.length, 0);
  assert.match(result.snapshot.notes.ficha_note_AAPL, /Versión de este dispositivo/);
  assert.match(result.snapshot.notes.ficha_note_AAPL, /local <script>safe as text<\/script>/);
  assert.match(result.snapshot.notes.ficha_note_AAPL, /Versión del otro dispositivo ---\nremota$/);
});

test('first link ignores only the truly empty built-in account', () => {
  const empty = snap({default: account()});
  const populated = snap({default: account('default', {name: 'Mi cartera'}, [tx('buy')])}, {}, ['AAPL']);
  const linked = Core.merge(null, empty, populated);
  assert.equal(linked.conflicts.length, 0);
  assert.equal(linked.snapshot.accounts.default.profile.name, 'Mi cartera');
  assert.deepEqual(Core.merge(null, populated, empty).snapshot, linked.snapshot);
  const funded = snap({default: account('default', {openingCash: 5})});
  assert.equal(Core.merge(null, funded, populated).conflicts.length, 1);
  const renamed = snap({default: account('default', {name: 'Importante'})});
  assert.equal(Core.merge(null, renamed, populated).conflicts.length, 1);
  const newAccount = snap({new: account('new')});
  assert.deepEqual(Object.keys(Core.merge(null, empty, newAccount).snapshot.accounts), ['new']);
  assert.equal(Object.keys(Core.merge(null, empty, empty).snapshot.accounts).length, 1);
});

test('apply plan removes stale derived positions and orphan ledgers without touching secrets/preferences', () => {
  const local = storage({pf_portfolios: JSON.stringify([account('one').profile, account('two').profile]),
    pf_transactions_one: JSON.stringify([tx('deleted')]), pf_positions_one: '[{"ticker":"AAPL"}]',
    pf_transactions_two: '[]', pf_positions_two: '[]', pf_active_id: 'one',
    note_AAPL: 'eliminar', ficha_note_MSFT: 'cambiar', watchlist: '["AAPL"]',
    marketintel_sync_key: 'private', mi_theme: 'light', chat_api_key: 'secret'});
  const target = snap({one: account('one')}, {ficha_note_MSFT: 'nueva'}, ['MSFT']);
  const plan = Core.planApply(local, target);
  assert.deepEqual(plan.remove, ['note_AAPL', 'pf_positions_one', 'pf_positions_two', 'pf_transactions_two']);
  assert.equal(plan.set.pf_active_id, undefined);
  assert.equal(local.getItem('note_AAPL'), 'eliminar');
  apply(local, plan);
  assert.deepEqual(Core.capture(local), target);
  assert.equal(local.getItem('marketintel_sync_key'), 'private');
  assert.equal(local.getItem('chat_api_key'), 'secret');
  assert.equal(local.getItem('mi_theme'), 'light');
  assert.equal(local.getItem('pf_positions_one'), null);
  assert.deepEqual(Core.planApply(local, target), {set: {}, remove: []});
  assert.equal(Core.planApply(local, snap({two: account('two')})).set.pf_active_id, 'two');
});

test('canonical fingerprint ignores object key and membership order but preserves ledger order', () => {
  const a = snap({z: account('z'), a: account('a')}, {note_MSFT: 'b', note_AAPL: 'a'}, ['MSFT', 'AAPL']);
  const b = snap({a: account('a'), z: account('z')}, {note_AAPL: 'a', note_MSFT: 'b'}, ['AAPL', 'MSFT']);
  assert.equal(Core.fingerprint(a), Core.fingerprint(b));
  a.accounts.a.transactions = [tx('first', 'Compra', 1), tx('second', 'Venta', 2)];
  b.accounts.a.transactions = a.accounts.a.transactions.slice().reverse();
  assert.notEqual(Core.fingerprint(a), Core.fingerprint(b));
});

test('rejects invalid/prototype data, duplicate IDs, unsafe symbols, secrets and excess size', () => {
  assert.throws(() => Core.validate(JSON.parse('{"version":1,"accounts":{"__proto__":{}},"notes":{},"watchlist":[]}')));
  assert.throws(() => Core.validate({...snap(), api_key: 'secret'}));
  const polluted = Object.create({name: 'prototype'});
  assert.throws(() => Core.validate({...snap(), accounts: polluted}));
  const bad = snap({one: account('one')});
  bad.accounts.one.profile.id = 'other';
  assert.throws(() => Core.validate(bad));
  bad.accounts.one = account('one', {openingCash: Infinity});
  assert.throws(() => Core.validate(bad));
  bad.accounts.one = account('one', {}, [tx('same'), tx('same')]);
  assert.throws(() => Core.validate(bad));
  assert.throws(() => Core.validate(snap({}, {}, ['AAPL\" onclick=evil'])));
  assert.throws(() => Core.validate(snap({}, {marketintel_sync_key: 'secret'})));
  const tooLarge = snap();
  for (let i = 0; i < 12; i++) tooLarge.notes['note_A' + i] = 'x'.repeat(190000);
  assert.throws(() => Core.validate(tooLarge), /2 MB/);
  assert.equal({}.polluted, undefined);
});

test('malformed local data blocks capture instead of turning it into an empty remote copy', () => {
  assert.throws(() => Core.capture(storage({pf_portfolios: '{broken'})));
  assert.throws(() => Core.capture(storage({pf_portfolios: JSON.stringify([account().profile]), pf_transactions_default: 'not json'})));
  assert.throws(() => Core.capture(storage({watchlist: '"not a list"'})));
});

test('valid identifiers matching inherited object names still merge as records', () => {
  const remote = snap({toString: account('toString')});
  const result = Core.merge(null, snap(), remote);
  assert.equal(result.conflicts.length, 0);
  assert.equal(result.snapshot.accounts.toString.profile.id, 'toString');
});

test('keeping both a maximum-length account name preserves the clone suffix within limits', () => {
  const base = snap({one: account('one')});
  const left = snap({one: account('one', {name: 'l'.repeat(1000)})});
  const right = snap({one: account('one', {name: 'r'.repeat(1000)})});
  const result = Core.merge(base, left, right, {'account:one': 'both'});
  const other = Object.values(result.snapshot.accounts).find(a => a.profile.id !== 'one');
  assert.equal(other.profile.name.length, 1000);
  assert.ok(other.profile.name.endsWith(' (otra versión)'));
});

test('independent final-account deletions leave a usable empty account without resurrecting trades', () => {
  const base = snap({one: account('one', {}, [tx('oneBuy')]), two: account('two', {}, [tx('twoBuy')])});
  const local = snap({one: base.accounts.one});
  const remote = snap({two: base.accounts.two});
  const result = Core.merge(base, local, remote);
  assert.equal(result.conflicts.length, 0);
  assert.deepEqual(result.snapshot.accounts, {default: account()});
  const repeat = Core.merge(result.snapshot, result.snapshot, result.snapshot);
  assert.deepEqual(repeat.snapshot, result.snapshot);
});
