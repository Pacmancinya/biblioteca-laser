// Pruebas del orden alfabético de la lista de modelos (2.3) y de la sintaxis de la interfaz.
// Uso: node pruebas/probar_orden_v23.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new Function(script); // valida la sintaxis de todo el <script>

const desde = script.indexOf('// ---------------- orden alfabético');
const hasta = script.indexOf('function sincronizarOrden');
assert.ok(desde > 0 && hasta > desde, 'no encuentro el bloque de orden');
const c = vm.createContext({ localStorage: { getItem: () => null, setItem() {} } });
vm.runInContext(script.slice(desde, hasta), c);

const nombres = lista => lista.map(m => m.n);
const modelos = ns => ns.map((n, i) => ({ n, rel: 'r' + i }));
const orden = (ns, sentido = 'az') => nombres(vm.runInContext('ordenarModelos', c)(modelos(ns), sentido));

// mayúsculas y minúsculas no importan
assert.deepEqual(orden(['zorro', 'Abeja', 'casa', 'Barco']), ['Abeja', 'Barco', 'casa', 'zorro']);
// tildes: á = a; la ñ va después de la n y antes de la o
assert.deepEqual(orden(['Oso', 'Ñandú', 'Árbol', 'nube', 'Avión', 'Zorro']), ['Árbol', 'Avión', 'nube', 'Ñandú', 'Oso', 'Zorro']);
assert.deepEqual(orden(['Peña', 'Pena', 'Peso', 'Pera']), ['Pena', 'Peña', 'Pera', 'Peso']);
// números en orden natural
assert.deepEqual(orden(['Caja 10', 'Caja 2', 'Caja 1', 'Caja 20']), ['Caja 1', 'Caja 2', 'Caja 10', 'Caja 20']);
assert.deepEqual(orden(['3D gato', 'Gato 2', 'Gato 10', '10 perros', '2 perros']), ['2 perros', '3D gato', '10 perros', 'Gato 2', 'Gato 10']);
// espacios y signos al comienzo no mandan el modelo al principio
assert.deepEqual(orden(['Barco', '  Abeja', '(Casa)', '- Animal', '_Dado', '¡Hola!']), ['  Abeja', '- Animal', 'Barco', '(Casa)', '_Dado', '¡Hola!']);
// Z → A es exactamente lo contrario
assert.deepEqual(orden(['Caja 10', 'Caja 2', 'Ñandú', 'oso', 'Ábaco'], 'za'), ['oso', 'Ñandú', 'Caja 10', 'Caja 2', 'Ábaco']);
// empates: estable y sin romperse con nombres iguales o vacíos
assert.equal(orden(['Gato', 'gato', 'GATO']).length, 3);
assert.deepEqual(orden(['b', '', 'a']).length, 3);
assert.doesNotThrow(() => orden(['x', undefined, null]));
// los recién agregados van primero hasta que se cambie el orden
vm.runInContext("nuevosPrimero = new Set(['r1'])", c);
assert.deepEqual(orden(['Abeja', 'Zorro', 'Barco']), ['Zorro', 'Abeja', 'Barco']);
vm.runInContext('nuevosPrimero = null', c);
// rapidez con la biblioteca completa
const muchos = Array.from({ length: 4325 }, (_, i) => ({ n: (i % 7 ? 'Modelo ' : 'Árbol ') + ((i * 7919) % 5000), rel: 'm' + i }));
const t = Date.now();
vm.runInContext('ordenarModelos', c)(muchos, 'az');
assert.ok(Date.now() - t < 500, 'ordenar 4.325 modelos tardó ' + (Date.now() - t) + ' ms');
// la lista queda de verdad ordenada en orden natural
for (let i = 1; i < muchos.length; i++) assert.ok(vm.runInContext('compararNombres', c)(muchos[i - 1], muchos[i]) <= 0);

// el orden elegido se recuerda entre sesiones
assert.match(script, /localStorage\.setItem\('orden_modelos'/);
assert.match(script, /localStorage\.getItem\('orden_modelos'\)==='za'/);
// los botones existen y son grandes
assert.match(html, /id="ordenAZ"[^>]*>A → Z</);
assert.match(html, /id="ordenZA"[^>]*>Z → A</);
assert.match(html, /\.orden-b\{min-height:44px/);
// las fotos se reintentan y las consultas se repiten sin repetir acciones que guardan
assert.match(script, /onerror="reintentarImagen\(this\)"/);
assert.match(script, /function fetchConReintento/);

console.log('OK: orden alfabético (tildes, mayúsculas, números, signos), recuerdo del orden y sintaxis completa.');
