/* Restore an interrupted local sync transaction before the app reads its data. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.MarketIntelSyncRecovery = api;
    try { api.recover(root.localStorage); }
    catch (_) { root.MarketIntelSyncRecoveryError = true; }
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const JOURNAL = 'marketintel_sync_journal';
  function permitted(key) {
    return key === 'marketintel_sync_state' || key === 'pf_portfolios' || key === 'pf_active_id' || key === 'watchlist' ||
      /^pf_(?:positions|transactions)_[A-Za-z0-9_-]{1,160}$/.test(key) || /^(?:note_|ficha_note_)[A-Z0-9.^=-]{1,15}$/.test(key);
  }
  function recover(storage) {
    const raw = storage.getItem(JOURNAL);
    if (!raw) return false;
    const journal = JSON.parse(raw);
    if (!journal || journal.version !== 1 || !Array.isArray(journal.entries) || journal.entries.length > 12000 ||
      journal.entries.some(pair => !Array.isArray(pair) || pair.length !== 2 || !permitted(pair[0]) || (pair[1] !== null && typeof pair[1] !== 'string'))) {
      throw new Error('No se pudo recuperar una sincronización interrumpida.');
    }
    // Removing destinations first frees enough space to restore their prior values.
    journal.entries.forEach(pair => storage.removeItem(pair[0]));
    journal.entries.forEach(pair => { if (pair[1] !== null) storage.setItem(pair[0], pair[1]); });
    storage.removeItem(JOURNAL);
    return true;
  }
  return { recover, permitted, JOURNAL };
});
