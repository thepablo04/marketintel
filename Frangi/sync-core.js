(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FrangiSyncCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const PREFIX = 'tpsl_calendar_trade_';
  const MAX_BYTES = 2 * 1024 * 1024;
  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  function validDate(date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
    const [year, month, day] = date.split('-').map(Number);
    return year >= 2000 && year <= 9999 && month >= 1 && month <= 12 &&
      day >= 1 && day <= new Date(year, month, 0).getDate();
  }
  function plain(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const proto = Object.getPrototypeOf(value);
    return proto === null || proto === Object.prototype;
  }
  function check(value) {
    if (!plain(value) || Object.keys(value).some(k => ['__proto__', 'constructor', 'prototype'].includes(k)))
      throw new Error('Los registros del calendario tienen un formato inválido.');
    return value;
  }
  function normalizeDay(value, date) {
    if (value === 'TP' || value === 'SL') value = [value];
    if (typeof value === 'string') {
      try { value = JSON.parse(value); } catch (_) { throw new Error('No se pudo leer un día guardado.'); }
    }
    if (!Array.isArray(value) || value.length > 10000) throw new Error('Un día guardado tiene datos inválidos.');
    const seen = new Set();
    return value.map((item, index) => {
      const trade = typeof item === 'string' ? {id: 'legacy_' + date + '_' + index, result: item} : check(item);
      if (Object.keys(trade).some(k => !['id', 'result'].includes(k)) ||
          typeof trade.id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(trade.id) ||
          !['TP', 'SL'].includes(trade.result) || seen.has(trade.id))
        throw new Error('Un trade guardado tiene datos inválidos.');
      seen.add(trade.id);
      return {id: trade.id, result: trade.result};
    });
  }
  function validate(input) {
    check(input);
    if (input.version !== 1 || !plain(input.days) || Object.keys(input).some(k => !['version', 'days'].includes(k)))
      throw new Error('La copia sincronizada no es compatible.');
    const output = {version: 1, days: {}};
    let total = 0;
    for (const date of Object.keys(check(input.days)).sort()) {
      if (!validDate(date)) throw new Error('Fecha inválida en los registros.');
      const values = normalizeDay(input.days[date], date);
      total += values.length;
      if (total > 10000) throw new Error('El calendario supera 10.000 trades.');
      if (values.length) output.days[date] = values;
    }
    if (new TextEncoder().encode(JSON.stringify(output)).length > MAX_BYTES)
      throw new Error('El calendario supera el límite de 2 MB para sincronizar.');
    return output;
  }
  function capture(storage) {
    const days = {};
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key || !key.startsWith(PREFIX)) continue;
      const date = key.slice(PREFIX.length);
      if (validDate(date)) days[date] = storage.getItem(key);
    }
    return validate({version: 1, days});
  }
  function fingerprint(snapshot) { return JSON.stringify(validate(snapshot)); }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function merge(base, local, remote, choices = {}) {
    const prior = base === null ? {version: 1, days: {}} : validate(base);
    const left = validate(local), right = validate(remote);
    check(choices);
    const output = {version: 1, days: {}}, conflicts = [];
    const dates = new Set([...Object.keys(prior.days), ...Object.keys(left.days), ...Object.keys(right.days)]);
    for (const date of [...dates].sort()) {
      const b = prior.days[date] || [], l = left.days[date] || [], r = right.days[date] || [];
      const bm = new Map(b.map(t => [t.id, t])), lm = new Map(l.map(t => [t.id, t])), rm = new Map(r.map(t => [t.id, t]));
      const ids = [...new Set([...b, ...l, ...r].map(t => t.id))], values = [];
      for (const id of ids) {
        const previous = bm.get(id), localTrade = lm.get(id), remoteTrade = rm.get(id);
        let chosen;
        if (same(localTrade, remoteTrade)) chosen = localTrade;
        else if (same(localTrade, previous)) chosen = remoteTrade;
        else if (same(remoteTrade, previous)) chosen = localTrade;
        else {
          const conflictId = 'trade:' + date + ':' + id;
          const choice = own(choices, conflictId) ? choices[conflictId] : null;
          if (choice === 'local') chosen = localTrade;
          else if (choice === 'remote') chosen = remoteTrade;
          else if (choice === 'both') {
            chosen = localTrade || remoteTrade;
            if (localTrade && remoteTrade && !same(localTrade, remoteTrade)) {
              let copyId = 'copy_' + id.slice(0, 70), counter = 0;
              while (ids.includes(copyId) || values.some(t => t.id === copyId)) copyId = 'copy_' + id.slice(0, 60) + '_' + (++counter);
              values.push({id: copyId, result: remoteTrade.result});
            }
          } else {
            conflicts.push({id: conflictId, kind: 'trade', key: date, name: 'Trade del ' + date,
              local: localTrade || null, remote: remoteTrade || null, base: previous || null});
            chosen = localTrade;
          }
        }
        if (chosen) values.push(chosen);
      }
      if (values.length) output.days[date] = values;
    }
    return {snapshot: validate(output), conflicts};
  }
  function planApply(storage, value) {
    const snapshot = validate(value), set = {}, remove = [];
    for (const [date, values] of Object.entries(snapshot.days)) set[PREFIX + date] = JSON.stringify(values);
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (key && key.startsWith(PREFIX) && validDate(key.slice(PREFIX.length)) && !own(set, key)) remove.push(key);
    }
    for (const key of Object.keys(set)) if (storage.getItem(key) === set[key]) delete set[key];
    return {set, remove};
  }
  return {capture, fingerprint, merge, planApply, validate, validDate, normalizeDay, MAX_BYTES};
});
