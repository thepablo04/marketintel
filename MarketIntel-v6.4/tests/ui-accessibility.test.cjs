'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'marketintel-accessibility.js'), 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

async function harness(t, markup) {
  const dom = new JSDOM('<!doctype html><body>' + markup, { runScripts: 'outside-only', url: 'https://marketintel.example/' });
  t.after(() => dom.window.close());
  dom.window.eval(source);
  await tick();
  return dom.window;
}

function key(window, target, keyValue, extra = {}) {
  const event = new window.KeyboardEvent('keydown', { key: keyValue, bubbles: true, cancelable: true, ...extra });
  target.dispatchEvent(event);
  return event;
}

test('sidebar Enter/Space activate existing callbacks once, including dynamic items', async t => {
  const w = await harness(t, '<div class="nav-item active" data-target="home"><span>Inicio</span></div>');
  const item = w.document.querySelector('.nav-item');
  let calls = 0;
  item.onclick = () => calls++;
  assert.equal(item.getAttribute('role'), 'button');
  assert.equal(item.tabIndex, 0);
  assert.equal(key(w, item, 'Enter').defaultPrevented, true);
  assert.equal(calls, 1);
  key(w, item.querySelector('span'), ' ');
  assert.equal(calls, 2);
  key(w, item, ' ', { repeat: true });
  key(w, item, 'Enter', { ctrlKey: true });
  key(w, item, 'Enter', { isComposing: true });
  assert.equal(calls, 2);

  // Redecoration must not register extra listeners.
  item.classList.add('additional-style');
  item.append(w.document.createElement('span'));
  await tick();
  key(w, item, 'Enter');
  assert.equal(calls, 3);
  w.document.body.insertAdjacentHTML('beforeend', '<div class="nav-item" data-target="valuacion">Valuación</div>');
  await tick();
  const dynamic = w.document.querySelector('[data-target="valuacion"]');
  dynamic.onclick = () => calls++;
  assert.equal(dynamic.tabIndex, 0);
  key(w, dynamic, ' ');
  assert.equal(calls, 4);
});

test('typing and native buttons keep their keyboard behavior; disabled nav does not activate', async t => {
  const w = await harness(t, '<div class="nav-item" data-target="home"><input><textarea></textarea><select><option>A</option></select><span contenteditable="true"><span id="edit">Text</span></span><button>Native</button><a href="#">Link</a></div><button class="nav-item" data-target="native">Native nav</button>');
  let calls = 0;
  w.document.querySelectorAll('.nav-item').forEach(item => item.onclick = () => calls++);
  for (const control of w.document.querySelectorAll('input, textarea, select, #edit, button, a')) {
    assert.equal(key(w, control, ' ').defaultPrevented, false);
    assert.equal(key(w, control, 'Enter').defaultPrevented, false);
  }
  assert.equal(calls, 0);
  const item = w.document.querySelector('.nav-item');
  item.setAttribute('aria-disabled', 'true');
  key(w, item, 'Enter');
  assert.equal(calls, 0);
  assert.equal(w.document.querySelector('[data-target="native"]').hasAttribute('role'), false);
});

test('active navigation reflects section changes and preserves existing role/tabindex', async t => {
  const w = await harness(t, '<div class="nav-item active" data-target="home">Inicio</div><div class="nav-item" data-target="watchlist" role="link" tabindex="-1">Watchlist</div><nav class="mi-mobile"><button class="active" data-target="home">Inicio</button><button data-target="watchlist">Watchlist</button></nav>');
  const home = w.document.querySelector('[data-target="home"]');
  const next = w.document.querySelector('[data-target="watchlist"]');
  assert.equal(home.getAttribute('aria-current'), 'page');
  assert.equal(next.hasAttribute('aria-current'), false);
  w.document.querySelectorAll('[data-target]').forEach(item => item.classList.toggle('active', item.dataset.target === 'watchlist'));
  await tick();
  w.document.querySelectorAll('[data-target]').forEach(item => {
    assert.equal(item.getAttribute('aria-current'), item.dataset.target === 'watchlist' ? 'page' : null);
  });
  assert.equal(next.getAttribute('role'), 'link');
  assert.equal(next.tabIndex, -1);
});

test('calculator labels reference existing IDs without changing values or explicit associations', async t => {
  const w = await harness(t, '<div class="calc-field"><label>Precio</label><input id="price" value="123"></div><div class="calc-field"><label for="explicit">Nombre</label><input id="name" aria-label="Nombre personalizado"></div><div class="calc-field"><label>Sin ID</label><input></div><div class="calc-field"><label>Ambiguo</label><input id="first"><input id="second"></div><div class="calc-field"><label>Implícito<input id="wrapped"></label></div>');
  const doc = w.document;
  assert.equal(doc.querySelector('label').htmlFor, 'price');
  assert.equal(doc.getElementById('price').value, '123');
  assert.equal(doc.querySelector('[for="explicit"]').htmlFor, 'explicit');
  assert.equal(doc.getElementById('name').getAttribute('aria-label'), 'Nombre personalizado');
  assert.equal(doc.getElementById('first').parentElement.querySelector('label').hasAttribute('for'), false);
  assert.equal(doc.getElementById('wrapped').parentElement.hasAttribute('for'), false);
  assert.deepEqual(Array.from(doc.querySelectorAll('[id]'), element => element.id), ['price', 'name', 'first', 'second', 'wrapped']);

  const field = doc.createElement('div');
  field.className = 'calc-field';
  field.innerHTML = '<label>Fecha</label>';
  doc.body.append(field);
  await tick();
  field.insertAdjacentHTML('beforeend', '<input id="date" type="date" value="2026-10-09">');
  await tick();
  assert.equal(field.querySelector('label').htmlFor, 'date');
  assert.equal(doc.getElementById('date').value, '2026-10-09');
});

test('icon controls reuse titles, update generated labels, and preserve application names', async t => {
  const w = await harness(t, '<button class="mi-icon" id="auto" title="Ocupar dos columnas"><svg></svg></button><button class="mi-icon" id="named" title="Otro título" aria-label="Nombre elegido"></button><button class="mi-icon" id="labelled" title="Otro" aria-labelledby="heading"></button><span id="heading">Cerrar ventana</span><button class="mi-open-mobile"></button><div class="mi-drawer"><button data-close></button></div><button data-close-command></button><button class="mi-icon" id="unknown"></button><button title="Texto de ayuda" id="text">Guardar</button>');
  const doc = w.document;
  assert.equal(doc.getElementById('auto').getAttribute('aria-label'), 'Ocupar dos columnas');
  assert.equal(doc.getElementById('named').getAttribute('aria-label'), 'Nombre elegido');
  assert.equal(doc.getElementById('labelled').hasAttribute('aria-label'), false);
  assert.equal(doc.querySelector('.mi-open-mobile').getAttribute('aria-label'), 'Abrir menú de navegación');
  assert.equal(doc.querySelector('[data-close]').getAttribute('aria-label'), 'Cerrar menú de navegación');
  assert.equal(doc.querySelector('[data-close-command]').getAttribute('aria-label'), 'Cerrar buscador');
  assert.equal(doc.getElementById('unknown').hasAttribute('aria-label'), false);
  assert.equal(doc.getElementById('text').hasAttribute('aria-label'), false);
  doc.getElementById('auto').title = 'Volver a una columna';
  await tick();
  assert.equal(doc.getElementById('auto').getAttribute('aria-label'), 'Volver a una columna');
  doc.getElementById('auto').setAttribute('aria-label', 'Nombre actualizado por la aplicación');
  doc.getElementById('auto').title = 'Otro título';
  await tick();
  assert.equal(doc.getElementById('auto').getAttribute('aria-label'), 'Nombre actualizado por la aplicación');
});

test('dynamic enhancement settles without repeated DOM mutations', async t => {
  const w = await harness(t, '<main></main>');
  const mutations = [];
  const observer = new w.MutationObserver(records => mutations.push(...records));
  observer.observe(w.document.body, { subtree: true, attributes: true, childList: true });
  t.after(() => observer.disconnect());
  w.document.querySelector('main').innerHTML = '<div class="nav-item active" data-target="home">Inicio</div><div class="calc-field"><label>Dato</label><input id="data"></div><button class="mi-icon" title="Exportar"></button>';
  await tick();
  const count = mutations.length;
  assert.ok(count > 1 && count < 15, 'Only initial insertion and semantic attributes should change');
  await tick();
  await tick();
  assert.equal(mutations.length, count);
});
