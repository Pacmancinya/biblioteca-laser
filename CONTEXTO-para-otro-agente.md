# Biblioteca Láser — contexto para retomar el proyecto

Documento de traspaso. Si vas a seguir trabajando en esto, léelo entero:
te va a ahorrar los errores que ya cometí.

Última actualización: 24-ago-2026 · versión publicada **2.1 "Más cómodo"**

---

## 1. Qué es y para quién

App local de escritorio para el **papá de Ruperto**, que tiene una cortadora
láser y trabaja con **LightBurn** y **CorelDRAW** (marca "kreativowood").

Empezó como "un buscador para mis modelos" y hoy es **biblioteca + CRM +
ventas de feria + cotizador + panel de métricas**.

**Quién la usa:** una persona mayor, no técnica. Ese es el criterio de diseño
que manda sobre todo lo demás:
- Nada de jerga. Los mensajes de error se escriben como se los dirías a él.
- Si algo puede hacerse solo, se hace solo (no se le pide copiar archivos).
- Los botones que no aplican se muestran **apagados con explicación**, no se
  esconden — él lo pidió expresamente: *"le gusta más visual eso"*.

**Quién te va a hablar:** Ruperto (español de Chile, informal). Él hace de
intermediario: prueba, le pasa la app a su papá, y te trae los reportes.

---

## 2. Dónde está todo

| Qué | Dónde |
|---|---|
| Código | `D:\Pacmancito Claude\biblioteca-laser` |
| Repo (público a propósito) | `github.com/Pacmancinya/biblioteca-laser` |
| Modelos del papá (copia en la PC de Ruperto) | `D:\Respaldo papá\Laser\Laser` |
| Paquete para instalar | `Biblioteca-Laser.zip` (~120 KB) |
| Carpeta ordenada de Ruperto | `Escritorio\Biblioteca Laser - Papa\` |

**La biblioteca real:** 54.000 archivos, 52 GB, **4.325 modelos**.
Un "modelo" = una carpeta que contiene al menos un archivo cortable.
Formatos por cantidad de modelos: `dxf` 2017, `cdr` 1444, `svg` 1297,
`eps` 1167, `ai` 280, `lbrn2` 133, `lbrn` 92, `dwg` 89.

Siempre prueba contra esa biblioteca real. Lo que anda con 5 archivos se cae
con 54.000.

---

## 3. Los archivos

```
lanzador.py     abre la ventana propia (pywebview sobre WebView2)
app.py          servidor HTTP local en 127.0.0.1:8777  (~2300 líneas)
ui.html         TODA la interfaz: HTML + CSS + JS a mano, sin frameworks
db.py           SQLite (biblioteca.db). Llave de todo = ruta relativa
indexar.py      recorre el disco -> biblioteca.json
categorias.py   taxonomía + clasificador automático
formatos.py     conversión automática entre formatos + caché
dxf.py svg.py eps.py lbrn.py    lectores propios, sin dependencias
migrar.py       trae los datos de una instalación anterior
crear_acceso.py crea el acceso directo del Escritorio
INSTALAR.bat    instalación de una sola vez
```

**Dependencias:** solo `pillow` y `pywebview`. Todo lo demás es stdlib,
**a propósito**: la PC del papá no tiene nada instalado y no se le puede
pedir que instale cosas.

---

## 4. ⚠️ Las trampas (lo más importante de este documento)

Cada una me costó una sesión entera. No las repitas.

### 4.1 El `.exe` NO funciona. Windows lo bloquea.

Windows 11 trae **Smart App Control**, que veta ejecutables **sin firma
digital**: *"Una directiva de Control de aplicaciones bloqueó este archivo"*.
No admite excepciones por archivo, y apagarlo es irreversible sin reinstalar
Windows.

Comprobado en la PC de Ruperto (build 26200, SAC **encendido**):
- `.exe` de PyInstaller → `NotSigned` → **bloqueado**
- `pythonw.exe` de Python.org → `Valid, CN=Python Software Foundation` → corre

**Solución vigente:** `INSTALAR.bat` + acceso directo a `pythonw.exe` con
`lanzador.py`, con icono propio. Para el usuario es idéntico (un icono,
ventana propia, sin consola) y el ZIP pesa 120 KB en vez de 29 MB.

`construir_exe.py` sigue en el repo, documentado como **no usable**. Solo
serviría comprando un certificado de firma de código.

### 4.2 NUNCA copies `biblioteca.db` con el programa abierto

La base está en **modo WAL**: los cambios recientes viven en
`biblioteca.db-wal`. Copiar solo el `.db` produce una base **corrupta**.

Me pasó de verdad: perdí materiales, costos y ajustes. Se recuperó partiendo
del `.db` íntegro y re-sembrando.

- Para respaldar: `VACUUM INTO` (ver `app.respaldar_base()`) o el botón
  "Descargar respaldo".
- Para migrar: copiar `.db` **+ `-wal` + `-shm`** y hacer
  `wal_checkpoint(TRUNCATE)` (ver `migrar.traer()`).
- El LEEME decía "copia ese archivo" para respaldar. Ya está corregido.

### 4.3 Los `\n` se rompen al insertar JS desde Python

Si insertas código JS en `ui.html` con un script de Python, los `\n` dentro
de comillas simples se convierten en **saltos de línea reales** y rompen todo
el bloque `<script>`. La app queda en "Cargando biblioteca..." **sin error
visible en consola** (es un error de sintaxis: nada se ejecuta).

Me pasó dos veces, con `prompt()` y `confirm()`.

**Cómo detectarlo:** buscar líneas con número impar de comillas dentro del
`<script>`. **Cómo evitarlo:** escribir esos textos con la herramienta de
edición directa, no con `str.replace` desde Python.

### 4.4 La categoría se calcula al INDEXAR, no al mostrar

Vive escrita en `biblioteca.json`. Mejorar `categorias.py` **no reordena
nada** hasta que se vuelva a indexar.

Publiqué una versión que arreglaba la clasificación y el papá reportó
*"no se ordenó nada"* — el código nuevo estaba ahí, sin usarse.

**Mecanismo actual:** `categorias.VERSION_CLASIFICADOR` (hoy **2**) se graba
en el índice; `app.reordenar_si_hace_falta()` compara al arrancar y reindexa
una sola vez. **Si cambias cómo se clasifica, SUBE ese número** o el cambio
no le llega a nadie.

En cambio, las **reglas de carpeta** (`reglas_carpeta`) se aplican al vuelo
en `modelo_vista()`, así que esas sí sobreviven a cualquier reindexado sin
tocar nada. Ese es el patrón preferible cuando se pueda.

### 4.5 Un archivo NUEVO no llega por el actualizador

`aplicar_actualizacion()` corre desde el `app.py` **ya instalado**. Si esa
versión tenía una lista fija de archivos, un módulo nuevo nunca llega.

Pasó con `convertir.py`: publiqué el conversor y al papá le llegó todo menos
el conversor. Arreglar la lista **no sirve para la versión en curso**, solo
para las siguientes.

**Regla:** si agregas funcionalidad que debe llegar YA, ponla dentro de un
archivo que ya existe (`app.py`). Hoy el actualizador toma todos los
archivos del paquete, así que de aquí en adelante está resuelto.

### 4.6 Al empaquetar, `sys.executable` deja de ser Python

Es el propio programa. No se puede lanzar `indexar.py` ni `elegir_carpeta.py`
como subproceso. Por eso existen:
- `app.indexar_ahora()` — importa el módulo cuando `CONGELADO`
- `app.elegir_carpeta_nativa()` — diálogo de Windows por ctypes
  (`SHBrowseForFolderW`)

### 4.7 Sin consola, un `sys.exit()` mata la app en silencio

`cargar_indice()` hacía `sys.exit(1)` si faltaba `biblioteca.json`. Con la
ventana propia, el usuario solo veía que "no abre".

**Regla:** en modo ventana, todo error sale por `MessageBoxW`, nunca por
`print`. Y las funciones de arranque devuelven vacío en vez de cortar.

### 4.8 No busques programas por extensiones genéricas

Buscando CorelDRAW por la asociación de `.svg` encontré **Internet
Explorer**, porque en esa PC los SVG abren en el navegador. Habría abierto un
navegador al pedir "Abrir en CorelDRAW".

**Regla:** buscar solo por extensiones **propias y exclusivas** (`.cdr`,
`.cmx`, `.lbrn`) y **verificar que el `.exe` encontrado esté en la lista
`exes`** del programa.

### 4.9 Los modos de apertura

`/api/abrir` recibe un `modo`. Solo las claves de `PROGRAMAS_DEF` se buscan
como programa; **cualquier otra cosa la abre Windows**. Antes, el modo
`abrir` (que manda "Ver imagen") se trataba como nombre de programa y salía
*"No encuentro **abrir** en este computador"*.

---

## 5. Decisiones tomadas con Ruperto

Estas ya se discutieron. No las revivas sin motivo.

- **Editar = solo en la app.** Nunca renombrar ni mover carpetas reales.
- **Ocultar ≠ borrar.** "Quitar de la biblioteca" solo esconde; los archivos
  quedan intactos. Borrar de verdad va a una papelera reversible.
- **Filtros: máximo 6 categorías grandes + subcategorías.** Rechazó
  explícitamente el árbol en cascada: *"es incómodo pasar de uno a otro"*.
  Y quiere el botón de limpiar filtros **arriba**, no al fondo.
- **Los duplicados se detectan por coincidencia EXACTA.** Se probó
  similitud parcial (umbral 0.65) y daba grupos absurdos de 57 modelos
  encadenados. No vuelvas a intentarlo.
- **Los archivos convertidos van a `_convertidos/`**, nunca mezclados con
  las carpetas del usuario.
- **El logo abre y cierra la columna de filtros** (lo pidió así, no un
  botón aparte).

---

## 6. Cómo publicar una actualización

1. Sube `APP_VERSION` **y** `APP_NOMBRE` en `app.py`
2. Actualiza `version.json` (`version`, `nombre`, `novedades`)
3. Agrega la fila en `VERSIONES.md`
4. `python construir_paquete.py`
5. `git add -A && git commit && git push`

**Regla del proyecto:** nunca repetir el nombre ni el texto de novedades
entre versiones. Ruperto lo pidió porque no distinguía una de otra.

El papá actualiza desde **⚙️ → Buscar actualizaciones**. Reemplaza solo el
código; **nunca toca** `biblioteca.db`, `config.json` ni los modelos.

GitHub cachea `version.json` unos minutos: no te asustes si no aparece al
instante.

---

## 7. Estado actual

**Funcionando y verificado** sobre los 4.325 modelos reales:
- Ventana propia sin navegador ni consola
- Dos botones grandes por modelo: CorelDRAW recibe SVG, LightBurn recibe
  `.lbrn`; si falta, se convierte al vuelo
- Lectores propios: `svg` 99%, `dxf` 99%, `eps` 85% (medido)
- Vista previa dibujada del modelo: **97%** de modelos con imagen
  (antes 61%)
- Categorías: crear, renombrar, ordenar, borrar, y "esta carpeta entera es
  de esta categoría"
- Varias carpetas de modelos a la vez
- Cotizador replicando sus dos Excel: **$16,0938/min**, cobra **$32,1875**
- Clientes, encargos con cobro, ventas de feria, panel de métricas
- Duplicados: ~1013 grupos en 6 s

**Pendiente / sin verificar:**
- ⚠️ **El `.lbrn` generado nunca se abrió en LightBurn de verdad.** No
  tengo LightBurn ni CorelDRAW en esta PC. La geometría se validó contra
  los archivos originales y contra las fotos de los modelos, y el XML tiene
  la misma estructura que los `.lbrn2` suyos — pero falta la prueba real.
  **Pregúntale a Ruperto si abre bien y a la escala correcta.**
- Los `.cdr` (13% de la biblioteca) **no se pueden convertir** sin
  CorelDRAW. Se avisa claramente. Vía posible sin explorar: automatizar
  CorelDRAW por COM (`CorelDRAW.Application`) en la PC del papá.
- Los `.dwg` (0,9%) tampoco.
- El papá tiene que cargar a mano los **minutos de corte** al cotizar.

---

## 8. Cómo trabajar en esto

Lo que aprendí de la forma difícil:

- **Prueba contra la biblioteca real, siempre.** Y valida el resultado
  visualmente cuando puedas: renderizar el DXF leído al lado de la foto del
  modelo destapó más problemas que cualquier assert.
- **Desconfía de tus propias pruebas.** Casi descarto un algoritmo correcto
  (Douglas-Peucker) porque mi medición calculaba distancia al vértice en vez
  de a la línea, y reportaba desvíos de 1179 mm donde había 0,02. Cuando un
  resultado te sorprenda, revisa primero la prueba.
- **Respalda antes de tocar la base** (`VACUUM INTO`) y restaura al terminar.
- **No borres nada del papá.** Todo lo destructivo va a papelera reversible.
  Para limpiar en el Escritorio de Ruperto: Papelera de reciclaje, no
  borrado permanente.
- **Sé derecho con lo que no se puede.** Los `.cdr` no se convierten y punto;
  decirlo claro vale más que una conversión a medias que arruine un corte.
- **Los mensajes son para el papá, no para ti.** "No encuentro CorelDRAW en
  este computador" sirve; un stack trace no.

---

## 9. Contacto

- Ruperto: **+56 9 5470 3465** (es el número que la app usa para la burbuja
  de ideas del papá)
- El papá anota lo que quiere cambiar en la **burbuja 💬** de la app y se
  lo manda a Ruperto por WhatsApp. Vale la pena revisar esas notas: de ahí
  salieron varias de las mejoras.
