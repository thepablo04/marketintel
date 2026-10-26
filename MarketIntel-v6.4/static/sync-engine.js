(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else {
    root.MarketIntelSync = factory();
    root.MarketIntelSyncEngine = root.MarketIntelSync.createEngine(Object.assign({ window: root }, root.MarketIntelSyncOptions || {}));
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const STATE = 'marketintel_sync_state', JOURNAL = 'marketintel_sync_journal';
  const MAX_BYTES = 2097152;
  const EMPTY = { version: 1, accounts: {}, notes: {}, watchlist: [] };
  function createEngine(options = {}) {
    const win = options.window || (typeof window !== 'undefined' ? window : null);
    const doc = options.document || (win && win.document);
    const storage = options.storage || (win && win.localStorage);
    const core = options.core || (win && win.MarketIntelSyncCore);
    const crypt = options.crypto || (win && win.crypto);
    const locks = options.locks || (win && win.navigator && win.navigator.locks);
    const fetcher = options.fetch || (win && win.fetch.bind(win));
    const recovery = options.recovery || (win && win.MarketIntelSyncRecovery);
    const encoder = new TextEncoder(), decoder = new TextDecoder('utf-8', { fatal: true });
    const clock = options.now || Date.now;
    const timers = new Set();
    const subscribers = new Set();
    const localHost = win && ['localhost', '127.0.0.1', '[::1]', '::1'].includes(win.location.hostname);
    const baseURL = options.baseURL != null ? options.baseURL : localHost ? 'https://marketintel-nu.vercel.app' : '';
    const online = options.online || (() => !win || win.navigator.onLine !== false);
    const backup = options.backup || (() => {
      if (!win || !win.MarketIntelBackup) throw new Error('No se pudo preparar el respaldo antes de sincronizar.');
      return win.MarketIntelBackup.save('before-restore');
    });
    const visible = () => !doc || doc.visibilityState !== 'hidden';
    const isEditing = options.isEditing || (manual => {
      if (!doc) return false;
      const own = doc.getElementById('mi-sync-dialog');
      const active = doc.activeElement;
      if (active && active.matches('input,textarea,select,[contenteditable="true"]')
          && active.getClientRects().length > 0 && win.getComputedStyle(active).visibility !== 'hidden'
          && !(manual && own && own.contains(active))) return true;
      return Array.from(doc.querySelectorAll('dialog[open],.modal.active,.modal.open,.modal-overlay.active,.modal-overlay.open,[role="dialog"]')).some(el => {
        if (manual && el === own) return false;
        const style = win.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && (el.getClientRects().length > 0);
      });
    });
    let state = { status: 'disconnected', connected: false, lastSynced: null, pending: false, error: null, conflicts: [] };
    let initial, activeRun = null, disposed = false, started = false, observed = null, debounce = null;
    let conflictContext = null, refreshNeeded = false, releasePage = null, pageLease = null;
    const guardTabs = options.guardTabs !== false && Boolean(win && doc);
    function b64(bytes) {
      let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      return (typeof btoa === 'function' ? btoa(binary) : Buffer.from(bytes).toString('base64')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    function unb64(value) {
      if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('La clave o copia de sincronización no es válida.');
      const binary = typeof atob === 'function' ? atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)) : Buffer.from(value, 'base64url').toString('binary');
      const bytes = Uint8Array.from(binary, ch => ch.charCodeAt(0));
      if (b64(bytes) !== value) throw new Error('La clave o copia de sincronización no es válida.');
      return bytes;
    }
    function codeBytes(code) {
      if (typeof code !== 'string' || !/^MI1-[A-Za-z0-9_-]{43}$/.test(code.trim())) throw new Error('Introduce la clave privada completa que comienza por MI1-.');
      const bytes = unb64(code.trim().slice(4));
      if (bytes.length !== 32) throw new Error('La clave privada no es válida.');
      return bytes;
    }
    function publish(next = {}) {
      state = Object.assign({}, state, next);
      for (const cb of subscribers) { try { cb(getState()); } catch (_) {} }
      return getState();
    }
    function getState() { return Object.assign({}, state, { conflicts: state.conflicts.map(item => Object.assign({}, item)) }); }
    function readRecord() {
      const raw = storage.getItem(STATE);
      if (!raw) return null;
      const record = JSON.parse(raw);
      if (!record || record.version !== 1 || typeof record.creator !== 'boolean') throw new Error('La configuración de sincronización está dañada. Tus datos locales siguen disponibles.');
      codeBytes(record.code);
      if (record.base !== null) core.validate(record.base);
      if (record.revision !== null && (typeof record.revision !== 'string' || !record.revision.length)) throw new Error('La versión de sincronización no es válida.');
      return record;
    }
    function persist(record) { storage.setItem(STATE, JSON.stringify(record)); }
    function current() { return core.capture(storage); }
    function fingerprint(snapshot) { return core.fingerprint(snapshot); }
    function same(a, b) { return fingerprint(a) === fingerprint(b); }
    function assertSupported() {
      if (!storage || !core || !crypt || !crypt.subtle || !locks || typeof locks.request !== 'function' || !fetcher) {
        throw new Error('Para sincronizar abre la app con INICIAR.bat o HTTPS en un navegador actualizado. Tus datos locales siguen disponibles.');
      }
      if ((win && win.MarketIntelSyncRecoveryError) || storage.getItem(JOURNAL)) throw new Error('Hay una recuperación local pendiente. Recarga la página antes de sincronizar.');
    }
    async function keys(code) {
      const master = codeBytes(code);
      async function derive(label) {
        const prefix = encoder.encode(label + '\0');
        const input = new Uint8Array(prefix.length + master.length);
        input.set(prefix); input.set(master, prefix.length);
        return new Uint8Array(await crypt.subtle.digest('SHA-256', input));
      }
      const auth = b64(await derive('MarketIntel sync auth v1'));
      const key = await crypt.subtle.importKey('raw', await derive('MarketIntel sync encryption v1'), 'AES-GCM', false, ['encrypt', 'decrypt']);
      return { auth, key };
    }
    async function encrypt(snapshot, derived) {
      const data = encoder.encode(JSON.stringify(core.validate(snapshot)));
      if (data.length > MAX_BYTES) throw new Error('Tus datos superan el límite de 2 MB para sincronizar. Las copias locales siguen disponibles.');
      const iv = crypt.getRandomValues(new Uint8Array(12));
      const ciphertext = new Uint8Array(await crypt.subtle.encrypt({ name: 'AES-GCM', iv }, derived.key, data));
      return { version: 1, iv: b64(iv), ciphertext: b64(ciphertext) };
    }
    async function decrypt(envelope, derived) {
      try {
        if (!envelope || envelope.version !== 1 || Object.keys(envelope).sort().join(',') !== 'ciphertext,iv,version' || typeof envelope.ciphertext !== 'string' || envelope.ciphertext.length > 2796224) throw new Error();
        const iv = unb64(envelope.iv), cipher = unb64(envelope.ciphertext);
        if (iv.length !== 12 || cipher.length < 16 || cipher.length > MAX_BYTES + 16) throw new Error();
        const plaintext = await crypt.subtle.decrypt({ name: 'AES-GCM', iv }, derived.key, cipher);
        return core.validate(JSON.parse(decoder.decode(plaintext)));
      } catch (_) { throw new Error('No se pudo abrir la copia cifrada. Revisa la clave privada; tus datos locales no se han cambiado.'); }
    }
    async function request(derived, method, envelope, revision) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 25000);
      const headers = { Authorization: 'Bearer ' + derived.auth };
      if (method === 'PUT') {
        headers['Content-Type'] = 'application/json';
        headers[revision === null ? 'X-Sync-If-None-Match' : 'X-Sync-If-Match'] = revision === null ? '*' : revision;
      }
      try {
        const response = await fetcher(baseURL + '/sync/data', { method, headers, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer', signal: controller.signal, ...(method === 'PUT' ? { body: JSON.stringify(envelope) } : {}) });
        const text = await response.text();
        if (text.length > 3000000) throw new Error('La respuesta de sincronización es demasiado grande.');
        let data;
        try { data = JSON.parse(text); } catch (_) { throw new Error('El servicio de sincronización no respondió correctamente.'); }
        if (!response.ok) {
          const error = new Error(response.status === 404 ? 'No existe una copia con esta clave privada.' : response.status === 409 ? 'Otro dispositivo acaba de guardar cambios.' : response.status === 429 ? 'Espera un minuto antes de volver a sincronizar.' : 'No se pudo conectar con la sincronización. Tus cambios locales se conservan.');
          error.status = response.status;
          throw error;
        }
        if (!data || typeof data.revision !== 'string' || !data.revision.length || data.revision.length > 256) throw new Error('El servidor no confirmó la versión de los datos.');
        return data;
      } catch (error) {
        if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('No se pudo conectar con la sincronización. Tus cambios locales se conservan.');
        throw error;
      } finally { clearTimeout(timeout); }
    }
    function fail(error) {
      let record = null;
      try { record = readRecord(); } catch (_) {}
      return publish({ status: online() ? 'error' : 'offline', connected: Boolean(record), pending: Boolean(record), error: error.message || 'No se pudo sincronizar. Tus datos locales se conservan.' });
    }
    async function acquirePage() {
      if (!guardTabs || releasePage || disposed) return;
      await new Promise((resolve, reject) => {
        pageLease = locks.request('marketintel-sync-page-v1', { mode: 'shared' }, () => new Promise(done => {
          releasePage = () => { releasePage = null; done(); };
          resolve();
        })).catch(reject);
      });
    }
    async function exclusiveApply(action) {
      if (!guardTabs) return action();
      if (releasePage) { releasePage(); await pageLease; }
      try {
        return await locks.request('marketintel-sync-page-v1', { mode: 'exclusive', ifAvailable: true }, async lock => {
          if (!lock) {
            publish({ status: 'pending', pending: true, error: 'Cierra las otras pestañas de MarketIntel en este navegador para recibir los cambios.' });
            return false;
          }
          return action();
        });
      } finally { await acquirePage(); }
    }
    function finishRefresh() {
      if (!refreshNeeded || isEditing(false)) return;
      refreshNeeded = false;
      if (options.refresh) options.refresh();
      else if (win) win.location.reload();
    }
    function notifyApplied(snapshot) {
      const hook = options.onApplied || (win && win.MarketIntelSyncRefresh);
      if (hook) {
        hook(snapshot);
      } else {
        refreshNeeded = true;
        if (win) win.dispatchEvent(new win.CustomEvent('marketintel-sync-applied'));
      }
    }
    async function apply(snapshot, before, record, remote, revision, manual) {
      if (isEditing(manual)) { publish({ status: 'pending', pending: true, error: 'Termina de editar o cierra el formulario para recibir los cambios.' }); return false; }
      return exclusiveApply(async () => {
        await backup();
        if (!same(current(), before) || isEditing(manual)) {
          publish({ status: 'pending', pending: true, error: 'Hay cambios nuevos en este dispositivo. Se volverán a comparar antes de sincronizar.' });
          return false;
        }
        const plan = core.planApply(storage, snapshot);
        const nextRecord = Object.assign({}, record, { base: remote, revision });
        // The refresh hook recalculates derived positions; include destinations
        // for newly received accounts in the rollback journal as well.
        const derivedKeys = Object.keys(snapshot.accounts).map(id => 'pf_positions_' + id);
        const mutations = Array.from(new Set([...Object.keys(plan.set), ...plan.remove, ...derivedKeys, STATE]));
        if (mutations.length > 12000) throw new Error('Demasiados datos para preparar la recuperación local.');
        if (recovery && mutations.some(key => !recovery.permitted(key))) throw new Error('La copia contiene datos incompatibles.');
        const entries = mutations.map(key => [key, storage.getItem(key)]);
        // The journal must be durably stored before the first local mutation.
        storage.setItem(JOURNAL, JSON.stringify({ version: 1, entries }));
        try {
          plan.remove.forEach(key => storage.removeItem(key));
          Object.entries(plan.set).forEach(([key, value]) => storage.setItem(key, value));
          persist(nextRecord);
          // Refresh synchronous app globals before callbacks or quote timers resume.
          notifyApplied(snapshot);
          storage.removeItem(JOURNAL);
        } catch (error) {
          if (recovery) recovery.recover(storage);
          else {
            entries.forEach(([key]) => storage.removeItem(key));
            entries.forEach(([key, value]) => { if (value !== null) storage.setItem(key, value); });
            storage.removeItem(JOURNAL);
          }
          try { notifyApplied(before); } catch (_) {}
          throw error;
        }
        return true;
      });
    }
    async function perform(choices, manual) {
      assertSupported();
      let record = readRecord();
      if (!record) return publish({ status: 'disconnected', connected: false, pending: false, error: null, conflicts: [] });
      if (!online()) return publish({ status: 'offline', connected: true, pending: true, error: null });
      publish({ status: 'syncing', connected: true, error: null });
      const derived = await keys(record.code);
      for (let attempt = 0; attempt < 3; attempt++) {
        let remote, revision;
        try {
          const response = await request(derived, 'GET');
          remote = await decrypt(response.envelope, derived);
          revision = response.revision;
        } catch (error) {
          if (error.status !== 404 || !record.creator || record.base !== null) throw error;
          remote = null; revision = null;
        }
        const local = current();
        const context = { local: fingerprint(local), remote: remote === null ? null : fingerprint(remote) };
        const safeChoices = choices && conflictContext && conflictContext.local === context.local && conflictContext.remote === context.remote ? choices : {};
        const merged = remote === null ? { snapshot: local, conflicts: [] } : core.merge(record.base, local, remote, safeChoices);
        if (merged.conflicts.length) {
          conflictContext = context;
          return publish({ status: 'conflict', connected: true, pending: true, error: null, conflicts: merged.conflicts });
        }
        conflictContext = null;
        publish({ conflicts: [] });
        if (!same(merged.snapshot, local)) {
          if (!await apply(merged.snapshot, local, record, remote, revision, manual)) return getState();
          record = readRecord();
        }
        // Remember exactly the snapshot acknowledged remotely, not edits made while awaiting the request.
        if (remote === null || !same(merged.snapshot, remote)) {
          const envelope = await encrypt(merged.snapshot, derived);
          try { revision = (await request(derived, 'PUT', envelope, revision)).revision; }
          catch (error) {
            if (error.status === 409) { record = readRecord(); choices = null; continue; }
            throw error;
          }
        }
        record = Object.assign({}, record, { base: merged.snapshot, revision, lastSynced: new Date(clock()).toISOString() });
        persist(record);
        const latest = current();
        const pending = !same(latest, record.base);
        observed = fingerprint(latest);
        publish({ status: pending ? 'pending' : 'idle', connected: true, lastSynced: record.lastSynced, pending, error: null, conflicts: [] });
        if (pending) schedule();
        finishRefresh();
        return getState();
      }
      return publish({ status: 'pending', connected: true, pending: true, error: 'Otro dispositivo sigue guardando cambios. Vuelve a sincronizar en un momento.' });
    }
    async function locked(action) {
      await ready();
      assertSupported();
      return locks.request('marketintel-sync-run-v1', { mode: 'exclusive' }, action);
    }
    function sync(choices, manual = true) {
      if (activeRun) return activeRun;
      activeRun = locked(() => perform(choices, manual)).catch(fail).finally(() => { activeRun = null; finishRefresh(); });
      return activeRun;
    }
    async function create() {
      try {
        return await locked(async () => {
          if (readRecord()) throw new Error('Este dispositivo ya está vinculado. Desconéctalo antes de crear otra sincronización.');
          const snapshot = current();
          // Validate size before creating a new capability.
          if (encoder.encode(JSON.stringify(snapshot)).length > MAX_BYTES) throw new Error('Tus datos superan el límite de 2 MB para sincronizar.');
          const code = 'MI1-' + b64(crypt.getRandomValues(new Uint8Array(32)));
          persist({ version: 1, code, creator: true, base: null, revision: null, lastSynced: null });
          return perform(null, true);
        });
      } catch (error) { return fail(error); }
    }
    async function connect(code) {
      try {
        return await locked(async () => {
          if (readRecord()) throw new Error('Este dispositivo ya está vinculado. Desconéctalo antes de usar otra clave.');
          const clean = String(code || '').trim();
          const derived = await keys(clean);
          const remote = await request(derived, 'GET');
          await decrypt(remote.envelope, derived);
          persist({ version: 1, code: clean, creator: false, base: null, revision: remote.revision, lastSynced: null });
          return perform(null, true);
        });
      } catch (error) { return fail(error); }
    }
    async function disconnect() {
      try {
        return await locked(() => {
          storage.removeItem(STATE); conflictContext = null;
          return publish({ status: 'disconnected', connected: false, pending: false, error: null, conflicts: [], lastSynced: null });
        });
      } catch (error) { return fail(error); }
    }
    function revealCode() { const record = readRecord(); return record ? record.code : null; }
    function schedule() {
      if (!started || disposed || debounce !== null) return;
      debounce = setTimeout(() => { timers.delete(debounce); debounce = null; if (visible()) sync(null, false); }, 5000);
      timers.add(debounce);
    }
    function observe() {
      if (disposed) return;
      finishRefresh();
      try {
        const record = readRecord();
        if (!record) return;
        const snapshot = current(), value = fingerprint(snapshot);
        if (value !== observed) {
          observed = value;
          const pending = record.base === null || !same(snapshot, record.base);
          if (!activeRun && state.status !== 'conflict') publish({ pending, connected: true, status: pending ? online() ? 'pending' : 'offline' : 'idle' });
          if (pending && state.status !== 'conflict') schedule();
        }
      } catch (error) { fail(error); }
    }
    function wake() { if (visible() && state.connected && !activeRun) sync(null, false); }
    function storageEvent(event) {
      if (event.key === STATE) {
        try {
          const record = readRecord();
          publish({ connected: Boolean(record), lastSynced: record && record.lastSynced, status: record ? 'pending' : 'disconnected', conflicts: [] });
          observed = null;
        } catch (error) { fail(error); }
      }
    }
    function start() {
      if (started || disposed || options.autoStart === false) return;
      started = true;
      timers.add(setInterval(observe, 2000));
      timers.add(setInterval(wake, 300000));
      if (win) { win.addEventListener('online', wake); win.addEventListener('focus', wake); win.addEventListener('storage', storageEvent); win.addEventListener('pagehide', dispose); }
      if (doc) doc.addEventListener('visibilitychange', wake);
      if (state.connected) schedule();
    }
    function ready() {
      if (!initial) initial = (async () => {
        try {
          assertSupported();
          await acquirePage();
          const record = readRecord();
          const snapshot = current();
          observed = fingerprint(snapshot);
          const pending = record && (record.base === null || !same(snapshot, record.base));
          publish({ status: record ? online() ? pending ? 'pending' : 'idle' : 'offline' : 'disconnected', connected: Boolean(record), lastSynced: record && record.lastSynced, pending: Boolean(pending), error: null });
          start();
        } catch (error) { publish({ status: 'unsupported', error: error.message }); }
        return getState();
      })();
      return initial;
    }
    function subscribe(callback) { subscribers.add(callback); callback(getState()); return () => subscribers.delete(callback); }
    function dispose() {
      disposed = true;
      for (const timer of timers) { clearTimeout(timer); clearInterval(timer); }
      timers.clear();
      if (releasePage) releasePage();
      if (win) { win.removeEventListener('online', wake); win.removeEventListener('focus', wake); win.removeEventListener('storage', storageEvent); win.removeEventListener('pagehide', dispose); }
      if (doc) doc.removeEventListener('visibilitychange', wake);
    }
    return { ready, create, connect, disconnect, sync, getState, subscribe, revealCode, dispose };
  }
  return { createEngine };
});
