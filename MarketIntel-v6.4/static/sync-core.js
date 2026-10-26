(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MarketIntelSyncCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const MAX_BYTES = 2 * 1024 * 1024;
  const ID = /^[A-Za-z0-9_-]{1,160}$/;
  const SYMBOL = /^[A-Z0-9.^=-]{1,15}$/;
  const NOTE = /^(note_|ficha_note_)[A-Z0-9.^=-]{1,15}$/;
  const FORBIDDEN = new Set(['__proto__', 'prototype', 'constructor']);
  const PROFILE_KEYS = ['id', 'name', 'type', 'openingCash', 'currency', 'ledgerVersion', 'migrationNotice'];
  const TX_KEYS = ['id', 'date', 'type', 'ticker', 'shares', 'price', 'fee', 'amount', 'total', 'positionType', 'note', 'sequence', 'schemaVersion'];
  const TYPES = new Set(['Compra', 'Venta', 'Abrir corto', 'Cubrir corto', 'Depósito', 'Retiro', 'Dividendo', 'Comisión']);
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const get = (object, key) => own(object, key) ? object[key] : undefined;
  function invalid(message) { throw new Error('No se pueden sincronizar los datos: ' + message + '.'); }
  function record(value, label) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) invalid(label + ' inválido');
    const proto = Object.getPrototypeOf(value);
    if (proto !== null && Object.getPrototypeOf(proto) !== null) invalid(label + ' inválido');
    for (const key of Object.keys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (FORBIDDEN.has(key) || !descriptor || !own(descriptor, 'value')) invalid(label + ' contiene una clave inválida');
    }
    return value;
  }
  function keys(value, permitted, label) {
    record(value, label);
    if (Object.keys(value).some(key => !permitted.includes(key))) invalid(label + ' contiene campos incompatibles');
  }
  function string(value, limit, label, allowEmpty) {
    if (typeof value !== 'string' || value.length > limit || (!allowEmpty && !value.length)) invalid(label + ' inválido');
    return value;
  }
  function identifier(value) {
    if (typeof value !== 'string' || !ID.test(value) || FORBIDDEN.has(value)) invalid('identificador inválido');
    return value;
  }
  function number(value, label) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) invalid(label + ' inválido');
    return value;
  }
  function list(value, maximum, label) {
    if (!Array.isArray(value) || value.length > maximum) invalid(label + ' inválida');
    return value;
  }
  function sorted(value) {
    if (Array.isArray(value)) return value.map(sorted);
    if (value && typeof value === 'object') {
      const result = {};
      Object.keys(value).sort().forEach(key => { result[key] = sorted(value[key]); });
      return result;
    }
    return value;
  }
  function encode(value) { return JSON.stringify(sorted(value)); }
  function equal(a, b) { return a === b || encode(a) === encode(b); }
  function checkSize(value) {
    const text = JSON.stringify(value);
    // TextEncoder is present wherever the sync engine's WebCrypto is supported.
    if (new TextEncoder().encode(text).length > MAX_BYTES) invalid('la copia supera el límite de 2 MB');
  }
  function profile(value, id) {
    keys(value, PROFILE_KEYS, 'cuenta');
    if (identifier(value.id) !== id) invalid('el identificador de la cuenta no coincide');
    const result = {
      id,
      name: string(value.name, 1000, 'nombre de cuenta'),
      type: string(value.type, 100, 'tipo de cuenta'),
      openingCash: number(value.openingCash, 'efectivo inicial'),
      currency: value.currency,
      ledgerVersion: value.ledgerVersion
    };
    if (result.currency !== 'USD' || result.ledgerVersion !== 3) invalid('versión de cuenta incompatible');
    if (own(value, 'migrationNotice')) result.migrationNotice = string(value.migrationNotice, 2000, 'aviso de cuenta', true);
    return result;
  }
  function transaction(value) {
    keys(value, TX_KEYS, 'operación');
    const result = {};
    result.id = identifier(value.id);
    result.date = string(value.date, 40, 'fecha');
    if (!/^\d{4}-\d{2}-\d{2}T/.test(result.date) || !Number.isFinite(new Date(result.date).getTime())) invalid('fecha inválida');
    if (!TYPES.has(value.type)) invalid('tipo de operación inválido');
    result.type = value.type;
    if (typeof value.ticker !== 'string' || value.ticker !== '' && !SYMBOL.test(value.ticker)) invalid('símbolo inválido');
    if (['Compra', 'Venta', 'Abrir corto', 'Cubrir corto'].includes(value.type) && !value.ticker) invalid('falta el símbolo de la operación');
    result.ticker = value.ticker;
    ['shares', 'price', 'fee', 'amount', 'total'].forEach(key => { result[key] = number(value[key], 'importe de operación'); });
    if (!['Largo', 'Corto'].includes(value.positionType)) invalid('posición inválida');
    result.positionType = value.positionType;
    result.note = string(value.note, 200000, 'nota de operación', true);
    if (!Number.isSafeInteger(value.sequence) || value.sequence < 0 || value.schemaVersion !== 3) invalid('versión de operación incompatible');
    result.sequence = value.sequence;
    result.schemaVersion = value.schemaVersion;
    return result;
  }
  function validate(value) {
    keys(value, ['version', 'accounts', 'notes', 'watchlist'], 'copia');
    if (value.version !== 1) invalid('versión de copia incompatible');
    record(value.accounts, 'cuentas');
    record(value.notes, 'notas');
    if (Object.keys(value.accounts).length > 500 || Object.keys(value.notes).length > 10000) invalid('demasiados registros');
    const result = {version: 1, accounts: {}, notes: {}, watchlist: []};
    let count = 0;
    Object.keys(value.accounts).sort().forEach(id => {
      identifier(id);
      const account = value.accounts[id];
      keys(account, ['profile', 'transactions'], 'cuenta');
      const transactions = list(account.transactions, 25000, 'lista de operaciones').map(transaction);
      count += transactions.length;
      if (count > 25000) invalid('demasiadas operaciones');
      const ids = new Set();
      transactions.forEach(tx => {
        if (ids.has(tx.id)) invalid('operaciones con identificador repetido');
        ids.add(tx.id);
      });
      result.accounts[id] = {profile: profile(account.profile, id), transactions};
    });
    Object.keys(value.notes).sort().forEach(key => {
      if (!NOTE.test(key)) invalid('clave de nota inválida');
      result.notes[key] = string(value.notes[key], 200000, 'nota', true);
    });
    result.watchlist = Array.from(new Set(list(value.watchlist, 10000, 'watchlist').map(ticker => {
      if (typeof ticker !== 'string' || !SYMBOL.test(ticker)) invalid('símbolo de watchlist inválido');
      return ticker;
    }))).sort();
    checkSize(result);
    return result;
  }
  function parse(storage, key, fallback) {
    const text = storage.getItem(key);
    if (text === null) return fallback;
    if (typeof text !== 'string' || text.length > MAX_BYTES) invalid('dato local demasiado grande');
    try { return JSON.parse(text); }
    catch (_) { invalid('dato local ilegible en ' + key); }
  }
  function pick(value, names, label) {
    record(value, label);
    const result = {};
    names.forEach(key => { if (own(value, key)) result[key] = value[key]; });
    return result;
  }
  function capture(storage) {
    const result = {version: 1, accounts: {}, notes: {}, watchlist: parse(storage, 'watchlist', [])};
    list(parse(storage, 'pf_portfolios', []), 500, 'lista de cuentas').forEach(account => {
      record(account, 'cuenta');
      const id = identifier(account.id);
      if (own(result.accounts, id)) invalid('cuentas con identificador repetido');
      const transactions = list(parse(storage, 'pf_transactions_' + id, []), 25000, 'lista de operaciones')
        .map(tx => pick(tx, TX_KEYS, 'operación'));
      result.accounts[id] = {profile: pick(account, PROFILE_KEYS, 'cuenta'), transactions};
    });
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (typeof key === 'string' && NOTE.test(key)) result.notes[key] = storage.getItem(key);
    }
    return validate(result);
  }
  function fingerprint(value) { return encode(validate(value)); }
  function pristine(account) {
    return account && account.profile.id === 'default' && account.profile.name === 'real'
      && account.profile.type === 'Standard' && account.profile.openingCash === 0
      && account.profile.currency === 'USD' && account.profile.ledgerVersion === 3
      && !account.profile.migrationNotice && account.transactions.length === 0;
  }
  function hash(text) {
    let value = 2166136261;
    for (let i = 0; i < text.length; i += 1) value = Math.imul(value ^ text.charCodeAt(i), 16777619);
    return (value >>> 0).toString(36);
  }
  function merge(base, local, remote, choices) {
    const l = validate(local), r = validate(remote);
    const b = base === null ? {version: 1, accounts: {}, notes: {}, watchlist: []} : validate(base);
    const decisions = choices || {};
    record(decisions, 'decisiones');
    if (base === null) {
      // A new installation's automatically generated empty account is not an
      // independent portfolio. A named/funded/used account is always preserved.
      if (pristine(l.accounts.default) && Object.keys(r.accounts).some(id => !pristine(r.accounts[id]))) delete l.accounts.default;
      if (pristine(r.accounts.default) && Object.keys(l.accounts).some(id => !pristine(l.accounts[id]))) delete r.accounts.default;
    }
    const result = {version: 1, accounts: {}, notes: {}, watchlist: []};
    const conflicts = [], clones = [];
    function combine(kind, key, left, right, prior) {
      if (equal(left, right)) return left;
      if (equal(left, prior)) return right;
      if (equal(right, prior)) return left;
      const id = kind + ':' + key;
      const choice = own(decisions, id) ? decisions[id] : null;
      if (choice === 'local') return left;
      if (choice === 'remote') return right;
      if (choice === 'both') {
        if (left === undefined) return right;
        if (right === undefined) return left;
        if (kind === 'account') { clones.push(right); return left; }
        return '--- Versión de este dispositivo ---\n' + left + '\n\n--- Versión del otro dispositivo ---\n' + right;
      }
      const label = kind === 'account'
        ? (left || right || prior).profile.name
        : (key.startsWith('ficha_note_') ? 'Nota de ficha: ' + key.slice(11) : 'Nota de análisis: ' + key.slice(5));
      conflicts.push({id, kind, key, name: label, label,
        local: left === undefined ? null : left,
        remote: right === undefined ? null : right,
        base: prior === undefined ? null : prior});
      return left;
    }
    [['accounts', 'account'], ['notes', 'note']].forEach(([collection, kind]) => {
      const all = new Set([...Object.keys(b[collection]), ...Object.keys(l[collection]), ...Object.keys(r[collection])]);
      Array.from(all).sort().forEach(key => {
        const value = combine(kind, key, get(l[collection], key), get(r[collection], key), get(b[collection], key));
        if (value !== undefined) result[collection][key] = value;
      });
    });
    clones.forEach(account => {
      const text = encode(account);
      const stem = 'sync_' + hash(text) + '_' + hash('remote:' + text);
      let id = stem, attempt = 0;
      while (true) {
        const suffix = ' (otra versión)';
        const clone = {profile: Object.assign({}, account.profile, {id, name: account.profile.name.slice(0, 1000 - suffix.length) + suffix}), transactions: account.transactions};
        if (!own(result.accounts, id)) { result.accounts[id] = clone; break; }
        if (equal(result.accounts[id], clone)) break;
        id = stem + '_' + (++attempt);
      }
    });
    const wb = new Set(b.watchlist), wl = new Set(l.watchlist), wr = new Set(r.watchlist);
    Array.from(new Set([...wb, ...wl, ...wr])).sort().forEach(ticker => {
      // Membership is binary: independent additions/removals commute.
      const keep = wl.has(ticker) === wb.has(ticker) ? wr.has(ticker) : wl.has(ticker);
      if (keep) result.watchlist.push(ticker);
    });
    // Two devices can each delete a different final account. The combined
    // deletions must still leave a selectable, empty account for the app.
    if (!Object.keys(result.accounts).length) {
      result.accounts.default = {
        profile: {id: 'default', name: 'real', type: 'Standard', openingCash: 0, currency: 'USD', ledgerVersion: 3},
        transactions: []
      };
    }
    return {snapshot: validate(result), conflicts};
  }
  function planApply(storage, value) {
    const snapshot = validate(value);
    const set = {}, remove = [];
    const ids = Object.keys(snapshot.accounts);
    set.pf_portfolios = JSON.stringify(ids.map(id => snapshot.accounts[id].profile));
    ids.forEach(id => { set['pf_transactions_' + id] = JSON.stringify(snapshot.accounts[id].transactions); });
    set.watchlist = JSON.stringify(snapshot.watchlist);
    Object.keys(snapshot.notes).forEach(key => { set[key] = snapshot.notes[key]; });
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      // Positions are derived. Leaving them behind can make legacy migration
      // resurrect a transaction which was deleted on another device.
      if (/^pf_positions_/.test(key) || /^pf_transactions_/.test(key) && !own(set, key)
          || NOTE.test(key) && !own(snapshot.notes, key)) remove.push(key);
    }
    const active = storage.getItem('pf_active_id');
    if (!ids.includes(active)) {
      if (ids.length) set.pf_active_id = ids[0];
      else if (active !== null) remove.push('pf_active_id');
    }
    // Avoid redundant writes and keep the plan small enough for a recovery journal.
    Object.keys(set).forEach(key => { if (storage.getItem(key) === set[key]) delete set[key]; });
    return {set, remove: Array.from(new Set(remove)).sort()};
  }
  return {capture, validate, fingerprint, merge, planApply, MAX_BYTES};
});
