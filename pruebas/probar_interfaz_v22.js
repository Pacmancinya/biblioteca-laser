// Pruebas del código de interfaz con DOM mínimo; no equivalen a un drop real de Windows.
// Uso: node pruebas/probar_interfaz_v22.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new Function(script); // También valida la sintaxis de la interfaz completa.

class Elemento {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.style = {};
    this.handlers = {};
    this.innerHTML = '';
    this.scrollTop = 0;
    this.children = [];
    this.clases = new Set();
    this.classList = {
      add: c => this.clases.add(c), remove: c => this.clases.delete(c),
      contains: c => this.clases.has(c),
      toggle: (c, activo) => {
        activo = activo === undefined ? !this.clases.has(c) : activo;
        if (activo) this.clases.add(c); else this.clases.delete(c);
      },
    };
  }
  addEventListener(nombre, callback) { this.handlers[nombre] = callback; }
  querySelectorAll() { return this.children; }
  querySelector() { return null; }
  closest(selector) { return this.destinos?.[selector] || null; }
  matches(selector) { return this.tipo === selector; }
  insertAdjacentHTML(_, texto) { this.innerHTML += texto; }
  removeAttribute() {}
  click() {}
}

const elementos = new Map();
const elem = id => {
  if (!elementos.has(id)) elementos.set(id, new Elemento());
  return elementos.get(id);
};
const document = {
  handlers: {}, getElementById: elem, querySelectorAll: () => [],
  querySelector: selector => elem(selector),
  addEventListener(nombre, callback) { this.handlers[nombre] = callback; },
};
const llamadas = [], mensajes = [];
const c = {
  document, window: {}, console, Set, Date, Array, Object, String, Number, Math,
  encodeURIComponent, setTimeout: () => 0,
  MODELOS: [], D: {categorias: []}, seleccionados: {},
  st: {q: '', cat: '', sub: '', flags: {}, fmt: '', gr: '', vista: 'biblio', verOcultos: false},
  mostrados: 0, filtrados: [], LOTE: 60, revisionVista: 1,
  grid: elem('grid'), qEl: elem('q'), actual: null, SINIMG: '<svg/>',
  esc: s => String(s ?? ''), norm: s => s.toLowerCase(), clp: String,
  pintarActivos: () => {}, actualizarPills: () => {}, sincronizarBotones: () => {},
  pintarSubs: cat => { c.hover = cat; },
  pintarCategorias: () => {}, verCategorias: () => {},
  toast: (m, error) => mensajes.push({m, error}), confirm: () => false,
  cargar: async () => {}, abrirModelo: async rel => { c.fichaRefrescada = rel; },
  api: async (url, datos) => { llamadas.push({url, datos}); return {ok: true}; },
};
vm.createContext(c);
vm.runInContext(script.slice(script.indexOf('// ---------------- arrastrar:'), script.indexOf('// ---------------- tema claro')), c);
vm.runInContext(script.slice(script.indexOf('function aplicar(conservar)'), script.indexOf('var SINIMG')), c);
vm.runInContext(script.slice(script.indexOf('function lote(){'), script.indexOf("document.getElementById('main').addEventListener('scroll'")), c);
vm.runInContext(script.slice(script.indexOf("grid.addEventListener('click'"), script.indexOf('// ---------------- modal modelo')), c);

const dragevent = (target, archivos = false) => ({
  target, preventDefault() {}, stopPropagation() {},
  dataTransfer: {types: archivos ? ['Files'] : ['application/x-biblioteca'], setData(tipo, texto) { this.payload = JSON.parse(texto); }},
});
const top = cat => {
  const e = new Elemento({destCat: cat});
  e.tipo = '.cat-b';
  e.destinos = {'[data-dest-cat]': e, '[data-dest-cat], #catsCont [data-org-cat]': e};
  return e;
};
const fila = (cat, sub) => {
  const e = new Elemento({orgCat: cat, arrSub: sub});
  e.destinos = {'#catsCont [data-org-cat]': e, '#catsCont [data-arr-sub]': sub ? e : null};
  return e;
};
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  // Ctrl+clic y arrastre conjunto hacia una categoría, con destino resaltado.
  const card = new Elemento({rel: 'uno'}), otra = new Elemento({rel: 'dos'});
  card.destinos = {'.card': card}; otra.destinos = {'.card': otra};
  c.grid.children = [card, otra];
  c.grid.handlers.click({target: card, ctrlKey: true});
  c.grid.handlers.click({target: otra, ctrlKey: true});
  assert.equal(card.classList.contains('seleccionada'), true);
  assert.equal(otra.classList.contains('seleccionada'), true);
  const e = dragevent(card);
  document.handlers.dragstart(e);
  assert.deepEqual(e.dataTransfer.payload.rels, ['uno', 'dos']);
  const destino = top('Casas');
  document.handlers.dragover(dragevent(destino));
  assert.equal(destino.classList.contains('destino-drag'), true);
  assert.equal(elem('[data-plegable="categorias-biblioteca"]').open, true);
  document.handlers.drop(dragevent(destino));
  await tick();
  assert.equal(llamadas[0].url, '/api/modelos/asignar');
  assert.deepEqual(JSON.parse(JSON.stringify(llamadas[0].datos)), {rels: ['uno', 'dos'], categoria: 'Casas', subcategoria: ''});

  // Subcategoría como destino del modelo.
  c.arrastre = {tipo: 'modelos', rels: ['uno']};
  const subdestino = top('Casas'); subdestino.dataset.sub = 'Maquetas';
  document.handlers.drop(dragevent(subdestino));
  await tick();
  assert.equal(llamadas.at(-1).datos.subcategoria, 'Maquetas');

  // Reordenar categorías y subcategorías, y trasladar una subcategoría.
  c.D.categorias = [{nombre: 'A', subs: [{nombre: 'Primera'}, {nombre: 'Segunda'}]}, {nombre: 'B', subs: []}];
  c.arrastre = {tipo: 'categoria', categoria: 'B'};
  document.handlers.drop(dragevent(fila('A')));
  await tick();
  assert.deepEqual(Array.from(llamadas.at(-1).datos.orden), ['B', 'A']);
  c.arrastre = {tipo: 'subcategoria', categoria: 'A', subcategoria: 'Segunda'};
  document.handlers.drop(dragevent(fila('A', 'Primera')));
  await tick();
  assert.equal(llamadas.at(-1).url, '/api/subcategoria/ordenar');
  assert.deepEqual(Array.from(llamadas.at(-1).datos.orden), ['Segunda', 'Primera']);
  c.arrastre = {tipo: 'subcategoria', categoria: 'A', subcategoria: 'Primera'};
  document.handlers.drop(dragevent(fila('B')));
  await tick();
  assert.equal(llamadas.at(-1).url, '/api/subcategoria/trasladar');
  assert.equal(llamadas.at(-1).datos.destino, 'B');

  // Un navegador sin rutas no inicia importaciones inventando nombres.
  const antes = llamadas.length;
  c.arrastre = null;
  document.handlers.drop(dragevent(new Elemento(), true));
  assert.equal(llamadas.length, antes);
  assert.equal(mensajes.at(-1).m, 'Para agregar arrastrando, abre la Biblioteca desde su icono.');

  // Cancelar en la confirmación no inicia la copia.
  c.api = async (url, datos) => {
    llamadas.push({url, datos});
    return url.includes('/estado') ? {estado: 'confirmar', carpetas: 3, bytes: 1288490189} : {ok: true};
  };
  c.confirm = texto => { c.confirmacion = texto; return false; };
  c.recibirAgregado('plan');
  await tick();
  assert.match(c.confirmacion, /3 carpetas/);
  assert.match(c.confirmacion, /Se copian; los originales quedan/);
  assert.equal(llamadas.at(-1).url, '/api/agregados/cancelar');

  // Conservar la lista ya cargada y su scroll tras refrescar, incluyendo tarjeta con foto.
  c.MODELOS = Array.from({length: 150}, (_, i) => ({rel: String(i), n: String(i), ruta_partes: [], fmt: [], gr: []}));
  c.MODELOS[90].img = 1; c.MODELOS[90].prev = 1;
  c.mostrados = 120;
  c.grid.innerHTML = '';
  c.grid.children = [];
  elem('main').scrollTop = 1730;
  c.aplicar(true);
  assert.equal(c.mostrados, 120);
  assert.equal(elem('main').scrollTop, 1730);
  assert.match(c.grid.innerHTML, /thumb\?rel=90/);
  c.actual = {rel: '90'};
  elem('velo').classList.add('on');
  await c.refrescarModelo('90');
  assert.equal(c.fichaRefrescada, '90');
  console.log('OK: 8 escenarios de interfaz y sintaxis JavaScript completa. DOM simulado; Windows no probado.');
})().catch(error => { console.error(error); process.exitCode = 1; });
