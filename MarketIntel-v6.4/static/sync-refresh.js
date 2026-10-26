(function () {
  'use strict';
  window.MarketIntelSyncRefresh = function () {
    // These variables are the application's existing live state. Rebind them in
    // the same task as the storage commit, before any asynchronous callbacks run.
    window.pfReloadFromStorage();
    wlTickers = JSON.parse(localStorage.getItem('watchlist') || '[]');
    for (const ticker of Object.keys(wlData)) {
      if (!wlTickers.includes(ticker)) delete wlData[ticker];
    }
    wlRenderAll();
    const analysis = document.getElementById('stock-notes');
    if (analysis && currentTicker) analysis.value = localStorage.getItem('note_' + currentTicker) || '';
    const ficha = document.getElementById('ficha-notes');
    if (ficha && fichaCurrentTicker) ficha.value = localStorage.getItem('ficha_note_' + fichaCurrentTicker) || '';
    // Charts use their existing fetch paths; refreshed globals above are already
    // authoritative even if a provider is slow or unavailable.
    setTimeout(function () {
      if (typeof pfLoadChart === 'function') Promise.resolve(pfLoadChart()).catch(function () {});
      document.dispatchEvent(new CustomEvent('marketintel-sync-refreshed'));
    }, 0);
  };
})();
