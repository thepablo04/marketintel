(function () {
  'use strict';
  if (window.MarketIntelReports) return;
  const MAX_PDF_BASE64 = 18 * 1024 * 1024;
  let overlay, dialog, body, status, download, retry, title, controller, timer, activeId = 0;
  let currentKind = 'opening', currentPdf = null, currentFilename = '', returnFocus = null, oldOverflow = '';
  let mountQueued = false;

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = String(value);
    return node;
  }
  function text(value, fallback = 'No disponible') {
    if (value == null || value === '') return fallback;
    if (typeof value === 'object') return value.value != null ? String(value.value) + (value.unit ? ' ' + value.unit : '') : fallback;
    return String(value);
  }
  function number(value) {
    return (typeof value === 'number' || typeof value === 'string' && value.trim() !== '') && Number.isFinite(Number(value));
  }
  function numeric(value, signed = false) {
    if (!number(value)) return 'Sin dato';
    const n = Number(value);
    return (signed && n > 0 ? '+' : '') + n.toLocaleString('es-ES', {maximumFractionDigits: 2});
  }
  function timestamp(value) {
    if (!value) return 'Hora no suministrada';
    const d = new Date(value);
    return Number.isFinite(d.getTime()) ? d.toLocaleString('es-ES', {timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short'}) + ' NY' : 'Hora no verificable';
  }
  function rows(value) { return Array.isArray(value) ? value.filter(v => v && typeof v === 'object') : []; }
  function safeLink(value) {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch (_) { return null; }
  }
  function source(item) {
    const node = element('div', 'mi-report-source');
    const url = safeLink(item.source_url);
    const label = text(item.source, 'Fuente no suministrada');
    if (url) {
      const a = element('a', '', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; node.append(a);
    } else node.append(element('span', '', label));
    if (item.as_of || item.published_at) node.append(element('span', '', ' · ' + timestamp(item.as_of || item.published_at)));
    return node;
  }
  function section(heading) {
    const node = element('section', 'mi-report-section');
    node.append(element('h3', '', heading)); body.append(node); return node;
  }
  function notice(parent, value, className = '') {
    if (value) parent.append(element('p', 'mi-report-note ' + className, value));
  }
  function table(parent, headers, data) {
    const wrap = element('div', 'mi-report-table-scroll'), tab = element('table', 'mi-report-table');
    const head = element('thead'), row = element('tr');
    headers.forEach(label => { const th = element('th', '', label); th.scope = 'col'; row.append(th); });
    head.append(row); tab.append(head);
    const tbody = element('tbody');
    data.forEach(values => { const tr = element('tr'); values.forEach(value => tr.append(element('td', '', value))); tbody.append(tr); });
    tab.append(tbody); wrap.append(tab); parent.append(wrap);
  }
  function readWatchlist() {
    try {
      const raw = JSON.parse(localStorage.getItem('watchlist') || '[]');
      if (!Array.isArray(raw)) throw new Error('Lista inválida');
      const valid = raw.filter(v => typeof v === 'string').map(v => v.trim().toUpperCase()).filter(v => /^[A-Z0-9][A-Z0-9.^=\-]{0,14}$/.test(v));
      return {tickers: [...new Set(valid)], warning: valid.length !== raw.length ? 'Algunas entradas de la watchlist no eran símbolos válidos y no se enviaron.' : ''};
    } catch (_) {
      return {tickers: [], warning: 'No se pudo leer la watchlist de este navegador. No se sustituyó por una lista de ejemplo; revisa tu watchlist antes de generar un reporte personalizado.'};
    }
  }

  function render(report, watchlist, watchWarning) {
    body.replaceChildren();
    const meta = element('div', 'mi-report-meta');
    meta.append(element('span', '', 'Sesión: ' + text(report.session_date)));
    meta.append(element('span', '', 'Corte: ' + timestamp(report.cutoff_at)));
    if (report.report_version) meta.append(element('span', '', 'Formato del reporte: ' + text(report.report_version)));
    if (report.generated_at) meta.append(element('span', '', 'Generado: ' + timestamp(report.generated_at)));
    body.append(meta);
    if (watchWarning) notice(body, watchWarning, 'is-warning');
    if (report.status === 'partial' || report.status === 'unavailable') notice(body, 'La consulta tiene información incompleta. Revisa la cobertura y las advertencias; los datos ausentes no se presentan como cero.', 'is-warning');
    if (Array.isArray(report.summary) && report.summary.length) {
      const host = section('Lectura de la sesión');
      report.summary.filter(v => typeof v === 'string').forEach(line => host.append(element('p', 'mi-report-summary', line)));
    } else if (typeof report.summary === 'string') section('Lectura de la sesión').append(element('p', 'mi-report-summary', report.summary));

    const quoteItems = rows(report.quotes);
    if (quoteItems.length) {
      const host = section(currentKind === 'opening' ? 'Antes de la apertura' : 'Cierre y precio del oro al corte');
      const grid = element('div', 'mi-report-quotes');
      quoteItems.forEach(item => {
        const card = element('article', 'mi-report-quote');
        card.append(element('h4', '', text(item.label || item.ticker)));
        card.append(element('strong', '', numeric(item.price) + (number(item.price) && item.unit ? ' ' + text(item.unit, '') : '')));
        const changes = [];
        if (number(item.change)) changes.push(numeric(item.change, true) + (item.unit ? ' ' + text(item.unit, '') : ''));
        if (number(item.change_pct)) changes.push(numeric(item.change_pct, true) + '%');
        if (changes.length) card.append(element('p', Number(item.change) < 0 ? 'is-negative' : 'is-positive', changes.join(' · ')));
        if (item.instrument) notice(card, text(item.instrument));
        if (item.note || item.warning || item.error || item.reason) notice(card, text(item.note || item.warning || item.error || item.reason));
        if (item.baseline_label) notice(card, text(item.baseline_label));
        if (item.delay_note) notice(card, text(item.delay_note));
        card.append(source(item)); grid.append(card);
      }); host.append(grid);
    }

    const breadth = rows(report.breadth);
    if (breadth.length) {
      const host = section(currentKind === 'opening' ? 'Cuántas suben y bajan' : 'Cuántas subieron y bajaron');
      breadth.forEach(item => {
        const card = element('article', 'mi-report-breadth'); card.append(element('h4', '', text(item.label || item.index)));
        const counts = item.status === 'unavailable' || Number(item.valid) === 0 ? [null, null, null, item.missing] : [item.up, item.down, item.unchanged, item.missing];
        table(card, ['Al alza', 'A la baja', 'Sin cambio', 'Sin dato'], [counts.map(v => number(v) ? numeric(v) : 'Sin dato')]);
        const coverage = number(item.valid) && number(item.total) && Number(item.total)>0 ? numeric(item.valid) + ' de ' + numeric(item.total) + ' valores con dato (' + numeric(Number(item.valid)/Number(item.total)*100) + '% de cobertura)' : 'Cobertura no verificada';
        notice(card, coverage + '. Los valores sin dato quedan fuera de los porcentajes.');
        if (number(item.valid) && number(item.total) && Number(item.valid)<Number(item.total)) notice(card, 'Esta es una muestra: todavía no se puede cerrar el balance de todo el índice.', 'is-warning');
        if (item.status === 'unavailable' || Number(item.valid) === 0) notice(card, 'No hay cotizaciones verificables suficientes para contar subidas y bajadas en esta consulta.', 'is-warning');
        if (item.warning || item.note || item.error || item.reason) notice(card, text(item.warning || item.note || item.error || item.reason), 'is-warning');
        card.append(source(item)); host.append(card);
      });
    }

    const magnificent = rows(report.magnificent_seven);
    if (magnificent.length) {
      const host = section(currentKind === 'opening' ? 'Las siete bajo la lupa' : 'Las siete al cierre');
      table(host, ['Empresa', 'Cierre anterior', currentKind === 'opening' ? 'Premercado' : 'Cierre regular', 'Cambio USD', 'Cambio %'], magnificent.map(item => [text(item.ticker || item.name), numeric(item.previous), numeric(item.price), numeric(item.change, true), number(item.change_pct) ? numeric(item.change_pct, true) + '%' : 'Sin dato']));
      magnificent.forEach(item => {
        if (item.warning || item.error || item.reason) notice(host, text(item.ticker, '') + ': ' + text(item.warning || item.error || item.reason), 'is-warning');
        if (item.as_of || item.source) {
          const meta = element('div', 'mi-report-source'); meta.append(element('span', '', text(item.ticker, '') + ' · ')); meta.append(source(item)); host.append(meta);
        }
      });
      notice(host, currentKind === 'opening' ? 'El precio de premercado es una observación al corte; el precio definitivo de apertura puede cambiar.' : 'La tabla corresponde al cierre regular. Los movimientos posteriores de la watchlist se identifican aparte.');
    }

    const macro = rows(report.macro);
    if (macro.length) {
      const host = section('Publicaciones macro relevantes');
      macro.forEach(item => {
        const card = element('article', 'mi-report-event'); card.append(element('h4', '', text(item.title || item.label)));
        table(card, ['Actual', 'Consenso', 'Anterior'], [[text(item.actual), text(item.consensus, 'Sin consenso verificado'), text(item.previous)]]);
        if (item.explanation) notice(card, text(item.explanation));
        const reaction = rows(item.market_reaction);
        if (reaction.length || item.market_reaction_note) {
          card.append(element('h4', '', 'Qué cambió en el mercado'));
          if (reaction.length) {
            table(card, ['Referencia', 'Antes del dato', 'Al corte', 'Cambio'], reaction.map(value => [text(value.label), numeric(value.before), numeric(value.price), numeric(value.change, true) + (number(value.change) && value.unit ? ' ' + text(value.unit, '') : '')]));
            reaction.forEach(value => {
              notice(card, text(value.label) + ': ' + timestamp(value.before_at) + ' a ' + timestamp(value.as_of));
              if (value.source) card.append(source(value));
            });
          }
          if (item.market_reaction_note) notice(card, text(item.market_reaction_note));
        }
        card.append(source(item)); host.append(card);
      });
    }

    if (currentKind === 'closing') {
      const host = section('Reportes importantes de tu watchlist');
      notice(host, watchlist.length ? 'Lista enviada: ' + watchlist.join(', ') : 'La watchlist de este navegador está vacía.');
      const events = rows(report.watchlist_reports);
      if (events.length) events.forEach(item => {
        const card = element('article', 'mi-report-event');
        const labels = {published: 'Publicado', pending: 'Pendiente al corte', unverified: 'Sin verificar', unavailable: 'No disponible'};
        card.append(element('div', 'mi-report-event-state', labels[item.status] || text(item.status, 'Estado no suministrado')));
        card.append(element('h4', '', [text(item.ticker, ''), text(item.title, '')].filter(Boolean).join(' · ')));
        if (item.summary) notice(card, text(item.summary));
        if (item.actual != null || item.consensus != null) table(card, ['Publicado', 'Consenso'], [[text(item.actual), text(item.consensus, 'Sin consenso verificado')]]);
        const postPrice = item.post_price != null ? item.post_price : item.after_hours_price;
        const postTime = item.post_as_of || item.after_hours_as_of;
        const postChange = item.post_change_pct != null ? item.post_change_pct : item.after_hours_change_pct;
        if (number(postPrice) && postTime) {
          const regularClose = item.price != null ? item.price : item.regular_close != null ? item.regular_close : item.close_price;
          const dollarChange = item.post_change != null ? item.post_change : item.after_hours_change != null ? item.after_hours_change : number(regularClose) ? Number(postPrice) - Number(regularClose) : null;
          table(card, ['Cierre regular', 'Precio posterior', 'Cambio USD', 'Cambio posterior %'], [[numeric(regularClose), numeric(postPrice), numeric(dollarChange, true), number(postChange) ? numeric(postChange, true) + '%' : 'Sin dato']]);
          notice(card, 'Cotización posterior: ' + timestamp(postTime) + '. La variación se compara con el cierre regular; no garantiza el precio de la próxima apertura.');
        }
        card.append(source(item)); host.append(card);
      });
      else notice(host, 'No se recibieron reportes empresariales para mostrar. Revisa las advertencias de cobertura para distinguir ausencia de publicaciones de una fuente no disponible.');
    }
    const warnings = Array.isArray(report.warnings) ? report.warnings.filter(v => typeof v === 'string') : [];
    if (warnings.length) {
      const host = section('Cobertura y datos pendientes');
      warnings.forEach(value => notice(host, value, 'is-warning'));
    }
    if (!quoteItems.length && !breadth.length && !magnificent.length && !macro.length && !rows(report.watchlist_reports).length) notice(body, 'La fuente no entregó cifras verificables en esta consulta. El PDF detalla la información que no estuvo disponible.', 'is-warning');
  }

  function createModal() {
    if (overlay) return;
    overlay = element('div', 'mi-report-overlay'); overlay.id = 'mi-report-overlay'; overlay.hidden = true;
    dialog = element('section', 'mi-report-dialog'); dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); dialog.setAttribute('aria-labelledby', 'mi-report-title'); dialog.tabIndex = -1;
    const head = element('header', 'mi-report-head'), heading = element('div');
    heading.append(element('div', 'mi-report-eyebrow', 'MarketIntel · Reportes'));
    title = element('h2', '', 'Reporte de apertura'); title.id = 'mi-report-title'; heading.append(title);
    const close = element('button', 'mi-report-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Cerrar reporte'); close.addEventListener('click', hide);
    head.append(heading, close);
    status = element('p', 'mi-report-status'); status.id = 'mi-report-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    body = element('div', 'mi-report-body'); body.id = 'mi-report-body';
    const footer = element('footer', 'mi-report-footer'); footer.append(element('small', '', 'El PDF conserva el corte y la información de esta consulta.'));
    const actions = element('div', 'mi-report-footer-actions');
    retry = element('button', 'mi-report-secondary', 'Volver a consultar'); retry.type = 'button'; retry.addEventListener('click', () => request(currentKind));
    download = element('button', 'mi-report-primary', 'Descargar PDF'); download.type = 'button'; download.disabled = true; download.addEventListener('click', savePDF);
    actions.append(retry, download); footer.append(actions); dialog.append(head, status, body, footer); overlay.append(dialog); document.body.append(overlay);
    overlay.addEventListener('click', event => { if (event.target === overlay) hide(); });
    document.addEventListener('keydown', event => {
      if (overlay.hidden) return;
      if (event.key === 'Escape') { event.preventDefault(); hide(); return; }
      if (event.key !== 'Tab') return;
      const nodes = [...dialog.querySelectorAll('button,a[href],select,input,[tabindex="0"]')].filter(node => !node.disabled && !node.hidden);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (!first) { event.preventDefault(); dialog.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
  }

  function clearPDF() {
    if (currentPdf) URL.revokeObjectURL(currentPdf);
    currentPdf = null; currentFilename = ''; if (download) download.disabled = true;
  }
  function hide() {
    if (!overlay || overlay.hidden) return;
    activeId++; if (controller) controller.abort(); clearTimeout(timer); controller = null;
    overlay.hidden = true; document.body.style.overflow = oldOverflow; clearPDF();
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
  }
  function savePDF() {
    if (!currentPdf) return;
    const link = element('a'); link.href = currentPdf; link.download = currentFilename; document.body.append(link); link.click(); link.remove();
  }
  function pdfFromPayload(payload) {
    if (typeof payload.pdf_base64 !== 'string' || !payload.pdf_base64 || payload.pdf_base64.length > MAX_PDF_BASE64) throw new Error('El servidor no entregó un PDF válido. Puedes volver a consultar.');
    const raw = atob(payload.pdf_base64);
    if (!raw.startsWith('%PDF-')) throw new Error('El archivo recibido no tiene formato PDF. Puedes volver a consultar.');
    const bytes = Uint8Array.from(raw, char => char.charCodeAt(0));
    currentPdf = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
    const proposed = typeof payload.filename === 'string' ? payload.filename.split(/[\\/]/).pop() : '';
    currentFilename = /^[A-Za-z0-9._-]+\.pdf$/i.test(proposed) ? proposed : 'MarketIntel-' + currentKind + '.pdf';
  }
  async function request(kind) {
    createModal();
    if (!['opening', 'closing'].includes(kind)) throw new Error('Tipo de reporte no válido');
    currentKind = kind;
    if (controller) controller.abort();
    clearTimeout(timer); clearPDF();
    const id = ++activeId;
    if (overlay.hidden) { returnFocus = document.activeElement; oldOverflow = document.body.style.overflow; overlay.hidden = false; document.body.style.overflow = 'hidden'; dialog.querySelector('button').focus(); }
    title.textContent = kind === 'opening' ? 'Reporte de apertura' : 'Resumen de sesión · 17:00 NY';
    body.replaceChildren(); status.className = 'mi-report-status'; status.textContent = 'Consultando fuentes y preparando el PDF. Esta consulta puede tardar hasta un minuto…';
    dialog.setAttribute('aria-busy', 'true'); retry.disabled = true;
    const watchlist = readWatchlist();
    if (watchlist.warning) notice(body, watchlist.warning, 'is-warning');
    controller = new AbortController(); let timedOut = false;
    timer = setTimeout(() => { timedOut = true; controller && controller.abort(); }, 65000);
    try {
      const response = await fetch('/reports/' + kind, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({watchlist: watchlist.tickers}), signal: controller.signal});
      let payload;
      try { payload = await response.json(); } catch (_) { throw new Error('El servidor no devolvió un reporte válido. Comprueba que usas la versión completa actualizada.'); }
      if (id !== activeId) return;
      if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : 'No se pudo generar el reporte. Vuelve a intentarlo.');
      if (!payload.report || typeof payload.report !== 'object' || Array.isArray(payload.report)) throw new Error('El servidor no entregó los datos del reporte.');
      render(payload.report, watchlist.tickers, watchlist.warning);
      pdfFromPayload(payload); download.disabled = false;
      status.textContent = payload.report.status === 'partial' || payload.report.status === 'unavailable' ? 'Reporte preparado con información parcial. Revisa la cobertura antes de interpretarlo.' : 'Reporte preparado. Puedes revisar los datos y descargar el PDF.';
    } catch (error) {
      if (id !== activeId) return;
      status.className = 'mi-report-status is-error';
      status.textContent = timedOut ? 'La consulta superó el tiempo de espera. Puedes volver a intentarlo.' : error && error.name === 'AbortError' ? 'La consulta se canceló.' : text(error && error.message, 'No se pudo generar el reporte.');
      clearPDF();
    } finally {
      if (id === activeId) { clearTimeout(timer); controller = null; retry.disabled = false; dialog.setAttribute('aria-busy', 'false'); }
    }
  }

  function mount() {
    const home = document.getElementById('sec-home'); if (!home) return;
    const actions = home.querySelector('.mi-home-head .mi-actions');
    const target = actions || home;
    let group = home.querySelector('.mi-report-entrypoints');
    if (!group) {
      group = element('div', 'mi-report-entrypoints');
      const opening = element('button', 'mi-report-launch', 'Reporte de apertura'); opening.type = 'button'; opening.dataset.reportKind = 'opening'; opening.addEventListener('click', () => request('opening'));
      const closing = element('button', 'mi-report-launch', 'Sesión · 17:00 NY'); closing.type = 'button'; closing.dataset.reportKind = 'closing'; closing.addEventListener('click', () => request('closing'));
      group.append(opening, closing);
      if (actions) actions.prepend(group); else home.prepend(group);
    } else if (actions && group.parentElement !== actions) actions.prepend(group);
  }
  function queueMount() { if (mountQueued) return; mountQueued = true; Promise.resolve().then(() => { mountQueued = false; mount(); }); }
  function start() {
    mount();
    const home = document.getElementById('sec-home');
    if (home) new MutationObserver(queueMount).observe(home, {childList: true, subtree: true});
    document.addEventListener('sectionChanged', queueMount);
  }
  window.MarketIntelReports = {open: request, close: hide, mount};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true}); else start();
})();
