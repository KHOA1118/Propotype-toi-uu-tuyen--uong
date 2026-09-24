const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function render(dashboard, simulation = null) {
  // Minimal DOM for the presentation renderer; no solver or simulation stubs run.
  const element = () => ({textContent: '', style: {}, children: [],
    nextElementSibling: {textContent: ''},
    append(...items) { this.children.push(...items); },
    replaceChildren() { this.children = []; }});
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  const context = vm.createContext({$: get, dashboard, simulation,
    state: {nodes: [{id: 0}, {id: 8}, {id: 19}]}, document: {createElement: element}});
  vm.runInContext(source.slice(source.indexOf("let chartSignature=")), context);
  vm.runInContext('renderBusinessMetrics({active: 2})', context);
  return get;
}

test('business metrics show missing values without invented savings or bars', () => {
  const get = render({before: null, after: null, scope: '', rerouted: 0});
  assert.equal(get('kpi-customers').textContent, 2);
  assert.equal(get('kpi-time').textContent, '—');
  assert.equal(get('kpi-saved').textContent, '—');
  for (const row of get('comparison-chart').children) {
    for (const line of row.children.slice(1)) {
      assert.equal(line.children[2].textContent, '—');
      assert.equal(line.children[1].children[0].style.width, '0%');
    }
  }
});

test('business metrics preserve actual costs, negative savings and remaining-work scope', () => {
  const get = render({before: {distance: 10000, travel: 600},
    after: {distance: 12000, travel: 720}, rerouted: 2, affected: 3,
    scope: 'Phần tuyến còn lại'}, {});
  assert.equal(get('kpi-saved').textContent, '-2 phút');
  assert.equal(get('kpi-time').textContent, '12 phút');
  assert.equal(get('kpi-time').nextElementSibling.textContent, 'Thời gian tuyến còn lại');
  assert.equal(get('kpi-active').textContent, 2);
  assert.equal(get('kpi-affected').textContent, 3);
  const distanceRow = get('comparison-chart').children[0];
  assert.equal(distanceRow.children[1].children[2].textContent, '10 km');
  assert.equal(distanceRow.children[2].children[2].textContent, '12 km');
  assert.equal(distanceRow.children[2].children[1].children[0].style.width, '100%');
});
