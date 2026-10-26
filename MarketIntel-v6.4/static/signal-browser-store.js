(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MarketIntelBrowserSignalStore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  const DATABASE_NAME = 'MarketIntelSignalJournal';
  const MODEL_VERSION = 'intraday-v6.1';
  const METHOD = 'SPY desde el precio registrado hasta el cierre de esa sesión. Zona neutral ±0.10%. Lecturas mixtas no cuentan como pronósticos direccionales. Observaciones del mismo día están correlacionadas. No incluye costos ni representa rentabilidad o probabilidad futura.';
  const PAGE_SIZE = 100;

  function problem(message) {
    const error = new Error(message);
    error.name = 'MarketIntelSignalStoreError';
    return error;
  }
  function explain(error) {
    if (error && error.name === 'MarketIntelSignalStoreError') return error;
    const messages = {
      QuotaExceededError: 'No hay espacio para guardar el seguimiento en este navegador. Exporta el historial antes de liberar espacio.',
      SecurityError: 'El navegador bloqueó el almacenamiento del seguimiento.',
      NotAllowedError: 'El navegador bloqueó el almacenamiento del seguimiento.',
      VersionError: 'El seguimiento usa una versión más reciente. Actualiza MarketIntel; los datos existentes se conservan.',
      AbortError: 'No se pudo guardar el seguimiento. La operación se canceló sin cambios.',
    };
    const result = problem(messages[error && error.name] || 'No se pudo acceder al seguimiento guardado en este navegador.');
    result.cause = error;
    return result;
  }
  function validDay(value) {
    return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  }
  const positive = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
  // Keep half-way rounding consistent with the SQLite/Python summary.
  function rounded(value, places) {
    const scale = 10 ** places, scaled = value * scale, floor = Math.floor(scaled);
    return (scaled - floor === 0.5 ? (floor % 2 === 0 ? floor : floor + 1) : Math.round(scaled)) / scale;
  }

  function inputFromPulse(pulse) {
    const evaluation = pulse && pulse.evaluation;
    if (!evaluation || !['browser', 'local'].includes(evaluation.storage) || evaluation.model !== MODEL_VERSION) {
      throw problem('La respuesta del servidor no incluye seguimiento compatible. Esta lectura no se registró.');
    }
    const session = pulse.session || {}, intra = pulse.intraday || {}, quote = (pulse.quotes || {}).SPY || {};
    const closes = Object.create(null);
    let observation = null;
    // Only the server supplies verified completed closes. Never derive them
    // from a current quote, context score, local date, or previous browser state.
    if (session.calendar_verified === true && validDay(session.date)) {
      const supplied = evaluation.completed_closes;
      if (supplied && typeof supplied === 'object' && !Array.isArray(supplied)) {
        Object.entries(supplied).forEach(([day, close]) => {
          if (validDay(day) && day < session.date && positive(close)) closes[day] = close;
        });
      }
      const elapsed = session.elapsed_minutes;
      if (session.is_open === true && intra.status === 'ok' &&
          typeof intra.score === 'number' && Number.isFinite(intra.score) && intra.score >= 0 && intra.score <= 100 &&
          typeof elapsed === 'number' && Number.isFinite(elapsed) && elapsed >= 5 && elapsed % 30 <= 10 &&
          typeof session.remaining_minutes === 'number' && Number.isFinite(session.remaining_minutes) && session.remaining_minutes >= 45 &&
          quote.usable === true && positive(quote.price) && typeof quote.data_at === 'string' && Number.isFinite(Date.parse(quote.data_at)) &&
          typeof intra.label === 'string') {
        observation = {
          model: MODEL_VERSION, day: session.date, bucket: Math.floor(elapsed / 30),
          recorded_at: new Date().toISOString(), data_at: quote.data_at,
          score: intra.score, label: intra.label, reference: quote.price,
          close_price: null, return_pct: null, actual: null, hit: null,
        };
      }
    }
    return { closes, observation };
  }

  function report(rows, complete) {
    const all = rows.filter(row => row.model === MODEL_VERSION).sort((a, b) => b.id - a.id);
    const evaluated = all.filter(row => row.close_price != null);
    const directional = evaluated.filter(row => row.hit != null);
    const hits = directional.length ? directional.reduce((count, row) => count + row.hit, 0) : null;
    return {
      model: MODEL_VERSION,
      summary: {
        total: all.length, evaluated: evaluated.length,
        days: new Set(evaluated.map(row => row.day)).size,
        directional: directional.length, hits,
        hit_rate: directional.length ? rounded(hits / directional.length * 100, 1) : null,
      },
      observations: complete ? all : all.slice(0, PAGE_SIZE), method: METHOD,
    };
  }

  function createStore(indexedDB) {
    let factory = indexedDB, unavailable, database = null, opening = null;
    if (arguments.length === 0) {
      try { factory = root.indexedDB; } catch (error) { unavailable = error; }
    }
    async function connect() {
      if (database) return database;
      if (!factory || typeof factory.open !== 'function') {
        throw unavailable ? explain(unavailable) : problem('IndexedDB no está disponible. El seguimiento no puede guardarse en este navegador.');
      }
      if (opening) return opening;
      opening = new Promise((resolve, reject) => {
        let request, cancelled = false;
        const timer = setTimeout(() => fail(problem('El almacenamiento del seguimiento no respondió. Cierra otras pestañas e inténtalo de nuevo.')), 8000);
        function fail(error) { cancelled = true; clearTimeout(timer); reject(explain(error)); }
        try { request = factory.open(DATABASE_NAME, 1); }
        catch (error) { fail(error); return; }
        request.onupgradeneeded = function (event) {
          if (event.oldVersion !== 0) { request.transaction.abort(); return; }
          const store = request.result.createObjectStore('observations', { keyPath: 'id', autoIncrement: true });
          store.createIndex('window', ['model', 'day', 'bucket'], { unique: true });
        };
        request.onerror = () => fail(request.error);
        request.onblocked = () => fail(problem('Otra pestaña bloquea el seguimiento. Cierra las otras pestañas de MarketIntel e inténtalo de nuevo.'));
        request.onsuccess = function () {
          const db = request.result;
          if (cancelled) { db.close(); return; }
          try {
            const store = db.transaction('observations', 'readonly').objectStore('observations');
            const index = store.index('window');
            if (db.version !== 1 || store.keyPath !== 'id' || !store.autoIncrement || !index.unique ||
                JSON.stringify(index.keyPath) !== JSON.stringify(['model', 'day', 'bucket'])) throw Error('schema');
          } catch (_) {
            db.close(); fail(problem('El formato del seguimiento no es compatible. Los datos existentes se conservan.')); return;
          }
          clearTimeout(timer);
          database = db;
          db.onversionchange = function () { db.close(); if (database === db) database = null; };
          db.onclose = function () { if (database === db) database = null; };
          resolve(db);
        };
      });
      try { return await opening; } finally { opening = null; }
    }

    async function transact(mode, work) {
      const db = await connect();
      return new Promise((resolve, reject) => {
        let transaction, result, failure;
        try { transaction = db.transaction('observations', mode); }
        catch (error) { reject(explain(error)); return; }
        const timer = setTimeout(() => abort(problem('El seguimiento no pudo guardarse a tiempo. Vuelve a intentarlo.')), 8000);
        transaction.oncomplete = function () { clearTimeout(timer); resolve(result); };
        transaction.onerror = event => { if (!failure) failure = event.target.error || transaction.error; };
        transaction.onabort = function () { clearTimeout(timer); reject(explain(failure || transaction.error || { name: 'AbortError' })); };
        function abort(error) {
          failure = error;
          try { transaction.abort(); } catch (_) { clearTimeout(timer); reject(explain(error)); }
        }
        function watch(request, then) {
          request.onsuccess = function () { try { then(request.result); } catch (error) { abort(error); } };
        }
        try { work(transaction.objectStore('observations'), watch, value => { result = value; }); }
        catch (error) { abort(error); }
      });
    }

    async function processPulse(pulse) {
      // Copy the accepted fields before awaiting: later changes to a cached
      // response must not rewrite the observation queued by this request.
      const { observation, closes } = inputFromPulse(pulse);
      return transact('readwrite', function (store, watch, done) {
        function settleAndRead() {
          watch(store.openCursor(), function visit(cursor) {
            if (!cursor) { watch(store.getAll(), rows => done(report(rows, false))); return; }
            const row = cursor.value, close = closes[row.day];
            if (row.model === MODEL_VERSION && row.close_price == null && positive(close) && positive(row.reference)) {
              const change = (close / row.reference - 1) * 100;
              const actual = change > 0.1 ? 'alcista' : change < -0.1 ? 'bajista' : 'mixto';
              const predicted = row.score >= 60 ? 'alcista' : row.score <= 40 ? 'bajista' : 'mixto';
              // An evaluated result is never revised by subsequent responses.
              cursor.update({ ...row, close_price: close, return_pct: rounded(change, 5), actual,
                hit: predicted === 'mixto' ? null : Number(predicted === actual) });
            }
            cursor.continue();
          });
        }
        if (!observation) { settleAndRead(); return; }
        // The unique index and this single write transaction protect the first
        // observation even when several tabs refresh the same half-hour window.
        watch(store.index('window').get([MODEL_VERSION, observation.day, observation.bucket]), prior => {
          if (prior) { settleAndRead(); return; }
          watch(store.add(observation), settleAndRead);
        });
      });
    }
    async function history(complete = false) {
      return transact('readonly', (store, watch, done) => watch(store.getAll(), rows => done(report(rows, complete))));
    }
    return { processPulse, history };
  }
  return { createStore, MODEL_VERSION };
});
