// Regresiones de interfaz con DOM simulado. No abre ni escribe datos reales.
// Uso: node pruebas/probar_interfaz_auditoria_v22.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new Function(script);
const elementos = new Map();
class Elemento {
  constructor(dataset = {}) {
    this.dataset = dataset; this.style = {}; this.handlers = {};
    this.disabled = false; this.value = ''; this.scrollTop = 0; this.children = [];
    this.clases = new Set(); this.tagName = 'DIV'; this._html = '';
    this.classList = {add: c => this.clases.add(c), remove: c => this.clases.delete(c),
      contains: c => this.clases.has(c), toggle: (c, valor) => valor ? this.clases.add(c) : this.clases.delete(c)};
  }
  set innerHTML(texto) {
    this._html = texto;
    this.children = [...texto.matchAll(/data-(fmt|gr)="([^"]*)"/g)].map(m => new Elemento({[m[1]]: m[2]}));
    for (const m of texto.matchAll(/<input[^>]*id="([^"]*)"[^>]*value="([^"]*)"/g)) elem(m[1]).value = m[2];
  }
  get innerHTML() {return this._html;}
  addEventListener(nombre, callback) {this.handlers[nombre] = callback;}
  querySelectorAll() {return this.children;}
  querySelector() {return new Elemento();}
  checkValidity() {return true;}
  insertAdjacentHTML(_, texto) {this.innerHTML += texto;}
  click() {}
}
function elem(id) {if (!elementos.has(id)) elementos.set(id, new Elemento()); return elementos.get(id);}
const mensajes = [], llamadas = [], almacen = new Map();
const document = {activeElement: elem('activo'), handlers: {}, getElementById: elem,
  querySelector: selector => elem(selector),
  querySelectorAll: selector => selector.includes('#filFmt') ? elem('filFmt').children : selector.includes('#filGrosor') ? elem('filGrosor').children : [],
  addEventListener(nombre, callback) {this.handlers[nombre] = callback;}};
const c = {document, window: {addEventListener() {}}, console, setTimeout, clearTimeout, AbortController,
  encodeURIComponent, localStorage: {getItem: k => almacen.get(k) || null, setItem: (k,v) => almacen.set(k,v)},
  toast: (m,e) => mensajes.push({m,e}),
  esc: s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/"/g,'&quot;'),
  norm: s => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,''),
  clp: n => '$' + Math.round(n || 0), val: id => elem(id).value,
  numv: id => elem(id).value === '' ? null : parseFloat(elem(id).value), hoy: () => 12345,
  MODELOS: [], CLIENTES: [], seleccionados: {}, D: {categorias: []}, actual: null, SINIMG: 'Sin imagen', revisionVista: 1,
  st: {q:'',cat:'',sub:'',flags:{},fmt:'',gr:'',vista:'biblio',verOcultos:false},
  mostrados:0, filtrados:[], grid:elem('grid'), pintarActivos() {}, lote() {},
  api: async (url,datos) => {llamadas.push({url,datos}); return {ok:true,ventas:[]};},
  pintarVentas() {}, cargar: async () => {}, cerrarF2() {}, actualizarPills() {},
  panelEditar() {}, panelCotizar() {}, panelCargar() {}, panelVersiones() {},
};
vm.createContext(c);
function cargar(desde, hasta) {vm.runInContext(script.slice(script.indexOf(desde), script.indexOf(hasta, script.indexOf(desde))), c);}
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  // Singular y plural reales de la interfaz.
  cargar('function tamañoAgregado(bytes)', 'function mostrarNuevos');
  // 1: todos los botones de quitar comparten el aviso de carpetas con submodelos.
  cargar('function confirmarQuitarModelo(rel)', 'function destinoElemento');
  c.MODELOS=[{rel:'.',ruta:'D:/modelos'},{rel:'hijo',ruta:'D:/modelos/hijo'}];
  let confirmacion='';
  c.confirm=texto=>{confirmacion=texto;return false;};
  c.quitarModelo('.');
  assert.match(confirmacion,/contiene 1 modelo\./);
  assert.match(confirmacion,/Solo se quitará este; el de adentro seguirá visible/);
  assert.match(script,/confirmarQuitarModelo\(d\.dataset\.deldup\)/);

  // 7 y 30: la ficha incluye el archivo 85, cuenta real y título actualizado.
  cargar('function abrirModelo(rel)', "document.getElementById('mtabs')");
  const archivos = Array.from({length:85}, (_,i) => `archivo${i + 1}.cdr`);
  const ficha = {rel:'uno',nombre:'Título anterior',ruta:'D:/modelos/uno',archivos:{corte:archivos,manual:[],imagen:[]},
    vista:{n:'Título actualizado'}, abrir_en:{}, programas:{}, meta:{}};
  c.api = async () => ficha;
  await c.abrirModelo('uno');
  assert.equal(elem('dTit').textContent, 'Título actualizado');
  assert.match(elem('dArch').innerHTML, /archivo85\.cdr/);
  assert.match(elem('dArch').innerHTML, /Para cortar \(85\)/);
  assert.match(elem('dArch').innerHTML, /Ver todos \(45 más\)/);

  // 17 y 29: regenerar filtros conserva resaltado; no suma modelos ocultos.
  cargar('function filtrosLaterales()', '// ---------------- categorías');
  cargar('function sincronizarBotones()', 'function limpiarFiltros()');
  c.MODELOS = [{fmt:['svg'],gr:['3mm']},{fmt:['dxf'],gr:['6mm'],oculto:1}];
  c.st.fmt='svg';c.st.gr='3mm';
  c.filtrosLaterales(); c.sincronizarBotones();
  assert.equal(elem('filFmt').children[0].classList.contains('on'), true);
  assert.equal(elem('filGrosor').children[0].classList.contains('on'), true);
  assert.doesNotMatch(elem('filFmt').innerHTML, /dxf/);

  // 28: encuentra nombres de archivos y sinónimos en ambas direcciones.
  cargar('function aplicar(conservar)', 'var SINIMG');
  Object.assign(c.st,{fmt:'',gr:'',q:'corazon'});
  c.MODELOS=[{n:'Heart',ruta_partes:[],notas:''},{n:'Sin título',ruta_partes:[],archivos_busqueda:'corazon_laser.svg'}];
  c.aplicar();assert.equal(c.filtrados.length,2);
  c.MODELOS=[{n:'Corazón',ruta_partes:[]}]; c.st.q='heart';c.aplicar();assert.equal(c.filtrados.length,1);
  for (const [es,en] of [['llavero','keychain'],['caja','box'],['lampara','lamp'],['reloj','clock'],['letrero','sign']]) {
    c.MODELOS=[{n:en,ruta_partes:[]}];c.st.q=es;c.aplicar();assert.equal(c.filtrados.length,1);
  }

  // 14: modelo 701, precio/costo editables y cambio de modelo al editar venta.
  cargar('function formVenta(v)', '// ---------------- burbuja');
  c.MODELOS=Array.from({length:701},(_,i)=>({n:'Modelo '+(i+1),rel:'modelo'+(i+1),precio:8000+i,costo:3000+i}));
  let guardar;
  c.abrirF2=(tit,html,onOk)=>{elem('f2Body').innerHTML=html;guardar=onOk;};
  c.api=async (url,datos)=>{llamadas.push({url,datos});return {ventas:[]};};
  c.formVenta({id:15,rel:'modelo1',item:'Modelo 1'});
  assert.match(elem('f2Body').innerHTML,/Modelo 701/);
  elem('v_item').value='Modelo 701'; elem('v_item').handlers.input();
  assert.equal(elem('v_pre').value,8700);assert.equal(elem('v_cos').value,3700);
  elem('v_pre').value='9999';elem('v_fec').value='2026-10-01';elem('v_cant').value='2';
  guardar();await tick();
  assert.equal(llamadas.at(-1).datos.rel,'modelo701');
  assert.equal(llamadas.at(-1).datos.precio_unit,9999);

  // 19: usa medida física o valores anteriores, recuerda material y muestra precio arriba.
  cargar('var COT=null;', '// -------- cargar archivos');
  const configuracion={materiales:[{id:3,nombre:'MDF',precio:12000}],ajustes:{},minuto:{final:10}};
  const precio={total:5000,total_piezas:10000,piezas:2,subtotal:2000,area_corte:600};
  c.api=async url=>url==='/api/cotizacion'?configuracion:precio;
  almacen.set('ultimaCotizacion',JSON.stringify({ancho:12,largo:34,material_id:3}));
  await c.panelCotizar({rel:'uno',medidas_mm:{ancho:200,alto:300}},{});await tick();
  assert.equal(elem('q_an').value,'20');assert.equal(elem('q_la').value,'30');
  assert.equal(elem('q_mat').value,3);
  assert.ok(elem('p-cotizar').innerHTML.indexOf('id="q_precio"') < elem('p-cotizar').innerHTML.indexOf('id="q_an"'));
  assert.match(elem('q_precio').innerHTML,/5000/);
  // El cálculo anterior recordó las medidas que se usaron realmente.
  await c.panelCotizar({rel:'dos'},{});await tick();
  assert.equal(elem('q_an').value,'20');assert.equal(elem('q_la').value,'30');
  assert.equal(JSON.parse(almacen.get('ultimaCotizacion')).material_id,3);

  // 13 y 15: bloquea Guardar durante la solicitud y lo recupera tras error.
  cargar('function api(u,d)', '// ---------------- carga');
  elem('velo2').classList.add('on');elem('f2Ok').disabled=false;
  let resolver;
  c.fetch=()=>new Promise(resolve=>{resolver=resolve;});
  const pendiente=c.api('/api/venta',{cantidad:1});
  assert.equal(elem('f2Ok').disabled,true);
  resolver({ok:false,json:async()=>({error:'No pude guardar esta venta.'})});
  await assert.rejects(pendiente,/No pude guardar/);
  assert.equal(elem('f2Ok').disabled,false);
  assert.match(mensajes.at(-1).m,/No pude guardar/);
  c.fetch=async()=>{throw new Error('Conexión interrumpida');};
  await assert.rejects(c.api('/api/venta',{cantidad:1}),/interrumpida/);
  assert.equal(elem('f2Ok').disabled,false);

  // 15: el botón de Releer también vuelve a estar disponible tras un error.
  c.api=async()=>{throw new Error('Disco ausente');};
  cargar("document.getElementById('btnReindexar').onclick", '// ---------------- formularios');
  elem('btnReindexar').textContent='🔄 Releer todo y reordenar';
  elem('btnReindexar').onclick();await tick();
  assert.equal(elem('btnReindexar').disabled,false);
  // El texto del botón no cambia tras una falla.
  assert.equal(elem('btnReindexar').textContent,'🔄 Releer todo y reordenar');

  // 27: Escape cierra Abrir con y la burbuja, además de las fichas.
  vm.runInContext(script.slice(script.lastIndexOf("document.addEventListener('keydown'")),c);
  for(const id of ['lupaFull','velo','veloProg','panelIdeas'])elem(id).classList.add('on');
  document.handlers.keydown({key:'Escape'});
  for(const id of ['lupaFull','velo','veloProg','panelIdeas'])assert.equal(elem(id).classList.contains('on'),false);

  console.log('OK: 11 escenarios de auditoría de interfaz y sintaxis completa. DOM simulado.');
})().catch(error=>{console.error(error);process.exitCode=1;});
