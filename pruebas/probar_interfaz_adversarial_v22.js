// Cuarta parte: funciones reales de ui.html en un DOM aislado por escenario.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8').split('<script>')[1].split('</script>')[0];
new Function(script);
const tick = () => new Promise(resolve => setImmediate(resolve));

function escenario() {
  const elementos = new Map(), llamadas = [], confirmaciones = [];
  function elem(id) {
    if (!elementos.has(id)) elementos.set(id, {
      value: '', disabled: false, textContent: '', dataset: {}, handlers: {},
      classList: {remove() {}}, addEventListener(n, fn) {this.handlers[n] = fn;}
    });
    return elementos.get(id);
  }
  const c = {console, document: {getElementById: elem}, MODELOS: [], CLIENTES: [],
    actual: null, st: {}, VENTAS: [], llamadas, confirmaciones,
    esc: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;'),
    val: id => elem(id).value, numv: id => elem(id).value === '' ? null : Number(elem(id).value),
    hoy: () => 1234567890, pintarVentas() {}, cerrarF2() {}, toast() {},
    cargar: async () => {}, verAjustes() {}, confirm: texto => {confirmaciones.push(texto);return true;},
    api: async (url, datos) => {llamadas.push({url, datos: JSON.parse(JSON.stringify(datos))});return {ok: true, ventas: []};},
    abrirF2(titulo, html, guardar, borrar) {
      c.html = html;c.guardar = guardar;c.borrar = borrar;
      for (const m of html.matchAll(/<input[^>]*id="([^"]*)"[^>]*value="([^"]*)"/g)) elem(m[1]).value = m[2];
    }
  };
  vm.createContext(c);
  vm.runInContext(script.slice(script.indexOf('function formVenta(v)'), script.indexOf('// ---------------- burbuja')), c);
  return {c, elem, llamadas, confirmaciones};
}

(async () => {
  // Modelo asociado oculto y modelo asociado fuera del índice.
  for (const ausente of [false, true]) {
    const {c, elem, llamadas} = escenario();
    c.MODELOS = ausente ? [] : [{rel: 'oculto', n: 'Mi modelo', oculto: 1}];
    c.formVenta({id: 7, rel: 'oculto', item: 'Mi modelo', cantidad: 4, stock_descontado: 1, precio_unit: 20});
    assert.match(c.html, /<option value="Mi modelo">/);
    elem('v_not').value = 'Notas nuevas';elem('v_pre').value = '500';
    c.guardar();await tick();
    assert.equal(llamadas[0].datos.rel, 'oculto');
    assert.equal(llamadas[0].datos.cantidad, 4);
    assert.equal(llamadas[0].datos.notas, 'Notas nuevas');
    assert.equal(llamadas[0].datos.precio_unit, 500);
    assert.equal(llamadas.length, 1);
  }
  // Solo cambiar el modelo mediante el input modifica la asociación.
  {
    const {c, elem, llamadas} = escenario();
    c.MODELOS = [{rel: 'otro', n: 'Otro', precio: 90, costo: 30}];
    c.formVenta({id: 7, rel: 'ausente', item: 'Anterior', cantidad: 2});
    elem('v_item').value = 'Otro';elem('v_item').handlers.input();
    c.guardar();await tick();
    assert.equal(llamadas[0].datos.rel, 'otro');
    assert.equal(llamadas[0].datos.precio_unit, 90);
    assert.equal(llamadas[0].datos.costo_unit, 30);
  }
  // Artículo libre explícito permite desvincular el modelo.
  {
    const {c, elem, llamadas} = escenario();
    c.formVenta({id: 7, rel: 'ausente', item: 'Anterior', cantidad: 2});
    elem('v_item').value = 'Artículo libre';elem('v_item').handlers.input();
    c.guardar();await tick();assert.equal(llamadas[0].datos.rel, null);
  }
  // El servidor solicita decisión sobre stock antiguo: Sí y No viajan explícitos.
  for (const decision of [true, false]) {
    for (const borrar of [true, false]) {
      const {c, elem, llamadas, confirmaciones} = escenario();
      const aviso = 'Esta venta es anterior a la versión 2.2: no sé cuánto stock descontó. ¿Quieres devolver 2 unidades al stock?';
      c.confirm = texto => {confirmaciones.push(texto);return decision;};
      c.api = async (url, datos) => {
        llamadas.push({url, datos: JSON.parse(JSON.stringify(datos))});
        return llamadas.length === 1 ? {confirmar_stock: true, aviso} : {ok: true, ventas: []};
      };
      c.formVenta({id: 7, rel: 'ausente', item: 'Anterior', cantidad: 2, stock_descontado: null});
      elem('v_cant').value = '3';(borrar ? c.borrar : c.guardar)();await tick();
      assert.deepEqual(confirmaciones, [aviso]);
      assert.equal(llamadas[1].datos.devolver_stock_antiguo, decision);
      assert.equal(llamadas[1].url, borrar ? '/api/venta/borrar' : '/api/venta');
    }
  }
  // Volver con distintas raíces requiere aceptar; cancelar no envía restauración.
  for (const aceptar of [false, true]) {
    const {c, elem, llamadas, confirmaciones} = escenario();
    vm.runInContext(script.slice(script.indexOf("document.getElementById('respaldosCont').addEventListener"),
      script.indexOf("document.getElementById('btnCarpetaRespaldo').onclick")), c);
    c.confirm = texto => {confirmaciones.push(texto);return confirmaciones.length === 1 || aceptar;};
    c.api = async (url, datos) => {
      llamadas.push({url, datos: JSON.parse(JSON.stringify(datos))});
      return llamadas.length === 1 ? {confirmar_raices: true, aviso: 'Otras carpetas. ¿Volver también?'} : {ok: true, aviso: 'Listo'};
    };
    const boton = elem('volver');boton.dataset.volver = 'copia.db';
    elem('respaldosCont').handlers.click({target: {closest: () => boton}});await tick();
    assert.equal(llamadas.length, aceptar ? 2 : 1);
    if (aceptar) assert.equal(llamadas[1].datos.restaurar_raices, true);
    else {assert.equal(boton.disabled, false);assert.equal(boton.textContent, 'Volver');}
  }
  console.log('OK: 10 escenarios adversariales de interfaz y sintaxis completa. DOM simulado.');
})().catch(error => {console.error(error);process.exitCode = 1;});
