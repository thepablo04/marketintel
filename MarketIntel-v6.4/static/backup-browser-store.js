(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MarketIntelBrowserBackupStore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  const DATABASE_NAME = 'MarketIntelBrowserBackups';
  const PAGE_SIZE = 100;
  const REASONS = new Set(['automatic', 'manual', 'before-import', 'before-restore', 'before-delete']);

  function problem(message) {
    const error = new Error(message);
    error.name = 'MarketIntelBackupError';
    return error;
  }

  function explain(error) {
    if (error && error.name === 'MarketIntelBackupError') return error;
    let message = 'No se pudo completar la operación con los respaldos del navegador.';
    if (error && error.name === 'QuotaExceededError') {
      message = 'No hay espacio disponible para guardar el respaldo en este navegador. Descarga una copia JSON y libera espacio.';
    } else if (error && (error.name === 'SecurityError' || error.name === 'NotAllowedError')) {
      message = 'El navegador bloqueó el acceso a los respaldos. Revisa los permisos de almacenamiento de este sitio.';
    } else if (error && error.name === 'AbortError') {
      message = 'Se canceló la operación con los respaldos del navegador. Los cambios no se guardaron.';
    }
    const result = problem(message);
    result.cause = error;
    return result;
  }

  function canonicalSnapshot(snapshot) {
    const values = snapshot && snapshot.localStorage;
    if (!values || typeof values !== 'object' || Array.isArray(values)) {
      throw problem('La copia debe contener localStorage como objeto.');
    }
    // The caller validates allowed application keys. Copy before awaiting IndexedDB
    // so an edit to the source object cannot change a queued backup.
    const ordered = Object.create(null);
    Object.keys(values).sort().forEach(function (key) {
      if (typeof values[key] !== 'string') throw problem('La copia contiene un valor de respaldo inválido.');
      ordered[key] = values[key];
    });
    return JSON.stringify(ordered);
  }

  function validId(value) {
    if (!Number.isSafeInteger(value) || value < 1) throw problem('Identificador de respaldo inválido.');
    return value;
  }

  function createStore(indexedDB) {
    let factory = indexedDB;
    let unavailable;
    if (arguments.length === 0) {
      try { factory = root.indexedDB; } catch (error) { unavailable = error; }
    }
    let database = null;
    let opening = null;

    async function connect() {
      if (database) return database;
      if (!factory || typeof factory.open !== 'function') {
        if (unavailable) throw explain(unavailable);
        throw problem('IndexedDB no está disponible en este navegador. Puedes usar la descarga de respaldos JSON.');
      }
      if (opening) return opening;
      opening = new Promise(function (resolve, reject) {
        let request;
        let cancelled = false;
        try {
          // Omitting a version also permits reopening after a versionchange.
          request = factory.open(DATABASE_NAME);
        } catch (error) { reject(explain(error)); return; }
        request.onupgradeneeded = function () {
          const db = request.result;
          if (!db.objectStoreNames.contains('backups')) {
            db.createObjectStore('backups', { keyPath: 'id', autoIncrement: true });
          }
          if (!db.objectStoreNames.contains('profiles')) {
            db.createObjectStore('profiles', { keyPath: 'profile' });
          }
        };
        request.onerror = function () { reject(explain(request.error)); };
        request.onblocked = function () {
          cancelled = true;
          reject(problem('Otra pestaña está bloqueando los respaldos. Cierra las otras pestañas de MarketIntel e inténtalo de nuevo.'));
        };
        request.onsuccess = function () {
          const db = request.result;
          if (cancelled) { db.close(); return; }
          database = db;
          db.onversionchange = function () {
            db.close();
            if (database === db) database = null;
          };
          db.onclose = function () { if (database === db) database = null; };
          resolve(db);
        };
      });
      try { return await opening; } finally { opening = null; }
    }

    async function transact(stores, mode, work) {
      const db = await connect();
      return new Promise(function (resolve, reject) {
        let transaction;
        let result;
        let failure;
        try { transaction = db.transaction(stores, mode); }
        catch (error) { reject(explain(error)); return; }
        // Resolve only after commit. A successful request alone does not imply
        // that a quota failure or a later request cannot abort the transaction.
        transaction.oncomplete = function () { resolve(result); };
        transaction.onerror = function (event) {
          if (!failure) failure = event.target.error || transaction.error;
        };
        transaction.onabort = function () { reject(explain(failure || transaction.error || { name: 'AbortError' })); };
        function abort(error) {
          failure = error;
          try { transaction.abort(); } catch (_) { reject(explain(error)); }
        }
        function watch(request, onSuccess) {
          request.onsuccess = function () {
            try { onSuccess(request.result); } catch (error) { abort(error); }
          };
          return request;
        }
        try { work(transaction, watch, function (value) { result = value; }); }
        catch (error) { abort(error); }
      });
    }

    async function save(snapshot, profile, reason) {
      const payload = canonicalSnapshot(snapshot);
      if (typeof profile !== 'string' || !profile.trim()) throw problem('Identificador del navegador inválido.');
      if (payload === '{}') return { status: 'empty', id: null, created_at: null };
      const savedReason = reason === undefined ? 'automatic' : (REASONS.has(reason) ? reason : 'manual');
      const size = new Blob([payload]).size;
      return transact(['backups', 'profiles'], 'readwrite', function (transaction, watch, done) {
        const backups = transaction.objectStore('backups');
        const profiles = transaction.objectStore('profiles');
        function insert() {
          const created = new Date().toISOString();
          watch(backups.add({ profile: profile, created_at: created, reason: savedReason, size_bytes: size, payload: payload }), function (id) {
            profiles.put({ profile: profile, id: id });
            done({ status: 'saved', id: id, created_at: created });
          });
        }
        if (savedReason !== 'automatic') { insert(); return; }
        // This lookup and insert share one write transaction, including across
        // tabs, so simultaneous automatic saves cannot produce duplicate rows.
        watch(profiles.get(profile), function (prior) {
          if (!prior) { insert(); return; }
          watch(backups.get(prior.id), function (row) {
            if (row && row.payload === payload) {
              done({ status: 'unchanged', id: row.id, created_at: row.created_at });
            } else insert();
          });
        });
      });
    }

    async function list(beforeId) {
      if (beforeId !== undefined && beforeId !== null) validId(beforeId);
      return transact(['backups'], 'readonly', function (transaction, watch, done) {
        const rows = [];
        watch(transaction.objectStore('backups').openCursor(null, 'prev'), function (cursor) {
          if (!cursor) { done({ backups: rows, next_before: null }); return; }
          if (beforeId != null && cursor.key >= beforeId) { cursor.continue(beforeId - 1); return; }
          if (rows.length === PAGE_SIZE) { done({ backups: rows, next_before: rows[rows.length - 1].id }); return; }
          const row = cursor.value;
          rows.push({ id: row.id, profile: row.profile, created_at: row.created_at, reason: row.reason, size_bytes: row.size_bytes });
          cursor.continue();
        });
      });
    }

    async function read(id) {
      validId(id);
      return transact(['backups'], 'readonly', function (transaction, watch, done) {
        watch(transaction.objectStore('backups').get(id), function (row) {
          if (!row) throw problem('No existe esa copia.');
          done({ version: 2, exported_at: row.created_at, localStorage: JSON.parse(row.payload) });
        });
      });
    }

    return { save: save, list: list, read: read };
  }

  return { createStore: createStore };
});
