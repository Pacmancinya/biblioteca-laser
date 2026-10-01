// Quinta parte: regresiones de la prueba en ventana real. DOM simulado, sin datos reales.
// Uso: node pruebas/probar_interfaz_parte5_v22.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new Function(script);
const tick = () => new Promise(resolve => setImmediate(resolve));

function entorno(extra = {}) {
  const elementos = new Map(), mensajes = [], confirmaciones = [];
  function elem(id) {
    if (!elementos.has(id)) {
      const e = {dataset: {}, style: {}, handlers: {}, hidden: false, textContent: '', value: '', children: [],
        classList: {add() {}, remove() {}, contains: () => false, toggle() {}},
        addEventListener(nombre, fn) { this.handlers[nombre] = fn; },
        removeAttribute() {}, querySelector: () => elem('hijo'), querySelectorAll: () => [], click() {}};
      let interno = '';
      Object.defineProperty(e, 'innerHTML', {get: () => interno, set: v => { interno = v; }});
      elementos.set(id, e);
    }
    return elementos.get(id);
  }
  const c = {console, setTimeout: () => 0, clearTimeout() {}, Promise, Set, Array, Object, Number, String, Error,
    encodeURIComponent, window: {addEventListener() {}}, localStorage: {getItem: () => null, setItem() {}},
    document: {getElementById: elem, querySelector: elem, querySelectorAll: () => [], addEventListener() {}},
    toast: (m, e) => mensajes.push({m, e}),
    confirm: texto => { confirmaciones.push(texto); return true; },
    esc: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;'),
    mensajes, confirmaciones, elem, ...extra};
  vm.createContext(c);
  const cargar = (desde, hasta) => vm.runInContext(script.slice(script.indexOf(desde), script.indexOf(hasta, script.indexOf(desde))), c);
  cargar('function tamañoAgregado(bytes)', 'function mostrarNuevos');
  return {c, elem, cargar};
}

(async () => {
  // 9: tamaños en KB para archivos chicos, nunca "(0 MB)"; singular y plural.
  {
    const {c} = entorno();
    assert.equal(c.tamañoAgregado(0), '0 KB');
    assert.equal(c.tamañoAgregado(500), '500 bytes');
    assert.equal(c.tamañoAgregado(2048), '2 KB');
    assert.equal(c.tamañoAgregado(300 * 1024), '300 KB');
    assert.equal(c.tamañoAgregado(5 * 1024 * 1024), '5 MB');
    assert.equal(c.tamañoAgregado(3 * 1024 * 1024 * 1024), '3 GB');
    assert.equal(c.tamañoMB(0), 'menos de 50 KB');
    assert.equal(c.tamañoMB(0.3), '307 KB');
    assert.equal(c.tamañoMB(12.5), '12,5 MB');
    assert.equal(c.plural(1, 'modelo', 'modelos'), '1 modelo');
    assert.equal(c.plural(0, 'modelo', 'modelos'), '0 modelos');
    assert.equal(c.plural(2, 'modelo agregado', 'modelos agregados'), '2 modelos agregados');
    assert.equal(c.plural(1234, 'modelo', 'modelos'), '1.234 modelos');
  }

  // 1: un error del servidor muestra SU mensaje (no el de falla de red) y ofrece lo copiado.
  function escenarioAgregado(rechazo) {
    const {c, elem, cargar} = entorno();
    cargar('function mostrarNuevos', '// ---------------- tema claro');
    const nuevos = [];
    c.mostrarNuevos = (rels, cat, sub) => { nuevos.push({rels, cat, sub}); return Promise.resolve(); };
    c.jobAgregado = null;
    c.api = async url => { throw rechazo; };
    return {c, elem, nuevos};
  }
  function errorServidor(datos) {
    const e = new Error(datos.error); e.servidor = true; e.datos = datos; return e;
  }
  for (const aceptar of [true, false]) {
    const {c, elem, nuevos} = escenarioAgregado(errorServidor({
      estado: 'error', error: 'El origen cambió desde la confirmación. La copia quedó incompleta en Agregados. Tus originales siguen intactos.',
      nuevos: ['Agregados\\Casa'], categoria: 'Casas', subcategoria: ''}));
    c.confirm = texto => { c.confirmaciones.push(texto); return aceptar; };
    c.recibirAgregado('abc'); await tick(); await tick();
    assert.equal(c.mensajes.length, 1);
    assert.match(c.mensajes[0].m, /El origen cambió/);
    assert.doesNotMatch(c.mensajes[0].m, /No pude consultar el avance/);
    assert.match(c.confirmaciones[0], /¿Quieres ver lo que sí alcanzó a copiarse\?/);
    assert.equal(nuevos.length, aceptar ? 1 : 0);
    if (aceptar) assert.deepEqual(JSON.parse(JSON.stringify(nuevos[0])), {rels: ['Agregados\\Casa'], cat: 'Casas', sub: ''});
    assert.equal(elem('agregadoAvance').hidden, true);
  }
  {
    // Rechazo de .exe: sin copia parcial no se ofrece nada.
    const {c, nuevos} = escenarioAgregado(errorServidor({estado: 'error', error: 'No se agregan ejecutables ni accesos directos: b.bat', nuevos: []}));
    c.recibirAgregado('abc'); await tick(); await tick();
    assert.deepEqual(c.mensajes.map(x => x.m), ['No se agregan ejecutables ni accesos directos: b.bat']);
    assert.equal(c.confirmaciones.length, 0);
    assert.equal(nuevos.length, 0);
  }
  {
    // Sin carpeta principal / disco ausente: sale el mensaje del servidor, sin confirmación.
    const {c} = escenarioAgregado(errorServidor({error: 'No encuentro la carpeta de modelos E:\\Laser. ¿Está conectado el disco?', estado: 'error'}));
    c.recibirAgregado('abc'); await tick(); await tick();
    assert.match(c.mensajes[0].m, /No encuentro la carpeta de modelos E:\\Laser/);
  }
  {
    // Una falla de red de verdad sí usa el mensaje genérico.
    const {c} = escenarioAgregado(new Error('Failed to fetch'));
    c.recibirAgregado('abc'); await tick(); await tick();
    assert.match(c.mensajes.at(-1).m, /No pude consultar el avance de la copia/);
  }
  {
    // Terminó bien con un solo modelo: singular.
    const {c, cargar} = entorno();
    cargar('function mostrarNuevos', '// ---------------- tema claro');
    c.mostrarNuevos = () => Promise.resolve();
    c.api = async () => ({estado: 'listo', nuevos: ['Agregados\\Uno'], categoria: '', subcategoria: ''});
    c.recibirAgregado('abc'); await tick(); await tick(); await tick();
    assert.match(c.mensajes.at(-1).m, /^Listo\. 1 modelo agregado\./);
  }
  // api() entrega el cuerpo del error del servidor.
  {
    const {c, cargar} = entorno({AbortController, fetch: async () => ({ok: false, json: async () => ({error: 'Mensaje del servidor', estado: 'error'})})});
    cargar('function api(u,d)', '// ---------------- carga');
    await assert.rejects(c.api('/api/agregados/estado?id=x'), e => e.servidor === true && e.datos.estado === 'error' && /Mensaje del servidor/.test(e.message));
  }

  // 8: los botones apagados explican por qué en vez de callar.
  {
    const {c, elem, cargar} = entorno({panelEditar() {}, panelCotizar() {}, panelCargar() {}, panelVersiones() {},
      MODELOS: [], revisionVista: 1, actual: null, SINIMG: '', PROGS: {}});
    cargar('function abrirModelo(rel)', "document.getElementById('mtabs')");
    const motivo = 'No encuentro la carpeta de modelos E:\\Laser. ¿Está conectado el disco?';
    c.api = async () => ({rel: 'uno', nombre: 'Uno', ruta: 'E:\\Laser\\uno', archivos: {corte: [], manual: [], imagen: []},
      vista: {n: 'Uno'}, programas: {}, meta: {},
      abrir_en: {lightburn: {puede: false, motivo}, corel: {puede: true, archivo: 'a.dxf', instalado: false}}});
    await c.abrirModelo('uno');
    const botones = elem('dAcc').innerHTML;
    assert.ok(botones.includes('data-aviso="' + motivo + '"'));
    assert.match(botones, /aria-disabled="true"/);
    assert.ok(!/ disabled/.test(botones), 'un botón disabled no responde al clic');
    assert.match(botones, /No encuentro CorelDRAW\. Indica dónde está/);
    // El clic en un botón apagado muestra la explicación.
    cargar("document.getElementById('velo').addEventListener('click'", '// -------- abrir con otro programa');
    c.actual = {rel: 'uno'};
    const aviso = {dataset: {aviso: motivo}};
    elem('velo').handlers.click({target: {closest: sel => sel === '[data-aviso]' ? aviso : null}});
    assert.deepEqual(JSON.parse(JSON.stringify(c.mensajes.at(-1))), {m: motivo, e: true});
  }

  // 9: borrar un cliente pregunta una sola vez; las demás eliminaciones, la pregunta genérica.
  {
    const {c, elem, cargar} = entorno();
    cargar('var f2={};', 'function formCliente(c)');
    let borrados = 0;
    c.abrirF2('Cliente', '<div/>', () => {}, () => { borrados++; }, true);
    elem('f2Del').onclick();
    assert.equal(c.confirmaciones.length, 0);
    assert.equal(borrados, 1);
    c.abrirF2('Encargo', '<div/>', () => {}, () => { borrados++; });
    elem('f2Del').onclick();
    assert.deepEqual(c.confirmaciones, ['¿Eliminar?']);
    assert.equal(borrados, 2);
    // El formulario de clientes avisa que ya hace su propia pregunta.
    let llamada;
    c.abrirF2 = (...args) => { llamada = args; };
    cargar('function formCliente(c)', 'function formPedido(p)');
    c.formCliente({id: 3, nombre: 'Ana'});
    assert.equal(llamada[4], true);
    c.formCliente({});
    assert.equal(llamada[3], null);
  }

  // 4: borrar una venta vuelve a leer los modelos (el stock de la tarjeta no queda viejo).
  {
    let recargas = 0;
    const {c, cargar} = entorno({MODELOS: [{rel: 'a', n: 'A'}], CLIENTES: [], VENTAS: [], pintarVentas() {}, cerrarF2() {},
      val: () => '', numv: () => null, hoy: () => 1, cargar: async () => { recargas++; }});
    c.api = async url => ({ok: true, ventas: []});
    let borrar;
    c.abrirF2 = (t, h, ok, del) => { borrar = del; };
    cargar('function formVenta(v)', '// ---------------- burbuja');
    c.formVenta({id: 7, rel: 'a', item: 'A', cantidad: 1, stock_descontado: 1});
    borrar(); await tick(); await tick();
    assert.equal(recargas, 1);
  }

  // 9: Ajustes -> Categorías: «Otros» no cuenta para el máximo de 6.
  for (const [nombres, bloqueado] of [[['A', 'B', 'C', 'D', 'E', 'F', 'Otros'], true], [['A', 'B', 'C', 'D', 'E', 'Otros'], false]]) {
    const {c, elem, cargar} = entorno({D: {categorias: nombres.map(n => ({nombre: n, n: 1, subs: []}))}, prepararPlegables() {}, verReglas() {}});
    cargar('function verCategorias()', '// las carpetas que el papa marco');
    c.verCategorias();
    const pagina = elem('catsCont').innerHTML;
    assert.match(pagina, /hasta 6 categorías grandes\. «Otros» no cuenta/);
    assert.equal(/id="catNueva" disabled/.test(pagina), bloqueado);
    assert.match(pagina, /class="mover"/);
  }

  // 5 y 7: la barra de categorías no es fija y los textos tienen tamaño legible.
  assert.doesNotMatch(html, /#v-biblio>details\{[^}]*sticky/);
  const tamaño = (regla, minimo) => {
    const m = html.match(new RegExp(regla.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{[^}]*?font-size:([0-9.]+)px'));
    assert.ok(m, 'no encuentro ' + regla);
    assert.ok(parseFloat(m[1]) >= minimo, regla + ' = ' + m[1] + 'px, mínimo ' + minimo);
  };
  tamaño('.card .rt', 12);
  tamaño('.card .nm', 15);
  tamaño('.fb', 14);
  tamaño('.sb', 14);
  tamaño('.btn', 14);
  tamaño('.btn.mini', 14);
  tamaño('.act', 14);
  tamaño('.arch button', 14);
  tamaño('.cuenta', 14);
  // Las rutas conservan los espacios dobles.
  assert.match(html, /\.card \.rt\{[^}]*white-space:pre[;}]/);
  assert.match(html, /\.mh \.rt\{[^}]*white-space:pre-wrap/);
  // En 1024 px el buscador no se achica a un icono.
  assert.match(html, /@media\(max-width:1180px\)\{[^@]*\.buscador\{[^}]*min-width:200px/);

  console.log('OK: escenarios de la quinta parte (puntos 1, 3, 4, 7, 8 y 9) y sintaxis completa. DOM simulado.');
})().catch(error => { console.error(error); process.exitCode = 1; });
