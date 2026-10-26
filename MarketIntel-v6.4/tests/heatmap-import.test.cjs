// Run with the same development-only jsdom installation as frontend-dom.cjs.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const search = [process.cwd(), ...(process.env.MARKETINTEL_TEST_NODE_PATHS || '').split(path.delimiter).filter(Boolean)];
const {JSDOM} = require(require.resolve('jsdom', {paths: search}));
const source = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const begin = source.indexOf('function hmGetColor(');
const end = source.indexOf('// ======================== TRADINGVIEW JS', begin);
assert(begin >= 0 && end > begin, 'Locate the independent custom heatmap functions');

for (const origin of ['http://localhost:5000', 'https://marketintel.example']) {
  const dom = new JSDOM('<input id="hm-new-group-input"><input id="ticker-input"><div id="hm-groups-container"></div><div id="hm-main"></div>', {
    url: origin, runScripts: 'outside-only',
  });
  const w = dom.window;
  try {
    let scheduled = 0;
    const opened = [];
    const groupName = 'Inversión ñ 📈 "doble" \'simple\' <img src=x onerror="window.injected=1">';
    const ticker = 'Q\'><img src=x onerror="window.injected=1">';
    const original = {sectors: {[groupName]: [ticker, 'BRK-B'], 'A-B': [], 'A B': []}};
    // This is the exact serialized state an imported backup restores.
    w.localStorage.setItem('hm_custom', JSON.stringify(original));
    w.hmCustom = JSON.parse(w.localStorage.getItem('hm_custom'));
    w.hmData = {'BRK-B': {price: 123.45, change_pct: 1.25, market_cap: 1e12}};
    w.MarketIntelBackup = {schedule() {scheduled++;}};
    w.go = section => assert.equal(section, 'screener');
    w.fetchStock = () => opened.push(w.document.getElementById('ticker-input').value);
    w.eval(source.slice(begin, end));
    w.renderCustomBuilder();

    const groups = () => [...w.document.querySelectorAll('.hm-custom-group')];
    const findGroup = name => groups().find(el => el.querySelector('[data-group-name]').textContent === name);
    const saved = () => JSON.parse(w.localStorage.getItem('hm_custom'));
    const assertSafe = () => {
      assert.equal(w.document.querySelectorAll('img, svg, script, iframe, [onclick], [onerror], [onkeydown]').length, 0);
      assert.equal(w.injected, undefined);
    };
    assertSafe();
    assert.equal(findGroup(groupName).querySelector('[data-group-name]').textContent, groupName);
    assert.equal(w.document.querySelector('.hm-sector-header span').textContent, groupName);
    assert.equal(w.document.querySelector('.hm-ticker').textContent, ticker);
    assert.equal(w.document.querySelector('.hm-box').title, ticker);
    assert.equal(w.document.querySelector('.hm-price').textContent, '$123');
    assert.equal(w.document.querySelectorAll('.hm-pct')[1].textContent, '+1.25%');
    const inputs = groups().map(el => el.querySelector('input').id);
    assert.equal(new Set(inputs).size, inputs.length, 'Distinct groups have distinct input IDs');
    w.document.querySelector('.hm-box').click();
    assert.deepEqual(opened, [ticker], 'Ticker click preserves the exact imported text');

    findGroup(groupName).querySelector('[data-group-tickers] button').click();
    assert.deepEqual(saved().sectors[groupName], ['BRK-B']);
    assertSafe();

    findGroup('A-B').querySelector('input').value = 'eurusd=x';
    findGroup('A-B').querySelector('[data-add-ticker]').click();
    assert.deepEqual(saved().sectors['A-B'], ['EURUSD=X']);
    assert.deepEqual(saved().sectors['A B'], [], 'Adding a ticker affects the selected group');

    const input = findGroup('A B').querySelector('input');
    input.value = '^gspc';
    input.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
    assert.deepEqual(saved().sectors['A B'], ['^GSPC']);

    const additional = 'Nuevo <svg onload="window.injected=2"> & café';
    w.document.getElementById('hm-new-group-input').value = additional;
    w.hmAddGroup();
    assert.deepEqual(saved().sectors[additional], []);
    assert(findGroup(additional));
    assertSafe();
    findGroup(additional).querySelector('[data-remove-group]').click();
    assert.equal(Object.hasOwn(saved().sectors, additional), false);
    assert.equal(scheduled, 5, 'All group/ticker mutations schedule a backup');
    assertSafe();
  } finally {
    w.close();
  }
}
console.log('Heatmap import rendering and controls passed for local and hosted origins.');
