# Versiones de la Biblioteca Láser

Cada versión lleva **número y nombre**, para reconocerla de un vistazo.
Al publicar una nueva hay que actualizar **los dos**:

- `app.py` → `APP_VERSION` y `APP_NOMBRE`
- `version.json` → `version`, `nombre` y `novedades`

> Regla: **nunca repetir el nombre ni el texto de novedades** entre versiones.

La tercera parte de **2.2, Ordenado y tranquilo** (1-oct-2026) completa la
auditoría de funciones de 2.1, manteniendo los cambios de las partes 1 y 2:

- Subidas permitidas según su tipo, comprobación del tamaño recibido y archivos
  temporales; archivos de la app y rutas externas bloqueados. Configuración
  compartida con lock, lectura con BOM y reemplazo atómico.
- Respaldo JSON de formato 3: datos de modelos, principal y visibilidad,
  clientes, encargos, ventas, sugerencias, materiales, costos, ajustes,
  categorías, subcategorías, reglas e historial/papelera. Importación completa
  en una transacción, con copia previa, remapeo de clientes, identificación de
  registros existentes y ventas sin volver a descontar stock.
- Sin diálogos en el indexador ni carpeta del autor. Un disco ausente conserva
  el índice. Limpieza muestra modelos que ya no encuentra y permite asociar
  sus datos a otra carpeta o descartarlos explícitamente. Cambiar la principal
  avisa cuántos modelos con datos se perderían de vista.
- Ventas con descuento SQL y transacción: editar ajusta la diferencia, borrar
  repone lo descontado y Guardar se bloquea durante la solicitud. Selector de
  todos los modelos con precio y costo. Clientes con pendientes no se borran;
  los demás se desvinculan de modelos, ventas y encargos sin eliminarlos.
- Categorías renombradas/borradas reasignan también reglas, datos de carpetas
  ausentes, subcategorías y clasificación futura. Panel separa ingresos por
  encargos de ventas. Migración remapea papelera e historial de la instalación.
- Ficha refrescada al abrir, archivos completos con Ver todos, foto preferida,
  URLs de miniaturas con revisión, principal persistente, filtros conservados,
  búsqueda por archivos y sinónimos, contadores sin ocultos, Escape en Abrir con
  e ideas, errores JSON con registro local y botones recuperados.
- Cotizador con medidas físicas fiables en mm o últimas medidas, último
  material y precio arriba; números y abonos validados. Costos antiguos con
  horas cero usan el reparto inicial con aviso; nuevos costos lo rechazan.
- Pantalla inicial «Ordenando tu biblioteca...» con avance; búsqueda de
  repetidos en segundo plano con porcentaje y cancelación.

Pruebas aisladas: `python pruebas/probar_v22.py`,
`python pruebas/probar_auditoria_v22.py`,
`node pruebas/probar_interfaz_v22.js` y
`node pruebas/probar_interfaz_auditoria_v22.js`.
Los tests de interfaz simulan DOM; no sustituyen una prueba de WebView2.

| Versión | Nombre | Qué trajo |
|---|---|---|
| **2.2** | Ordenado y tranquilo | Se elimina conversor manual y automático; selección de archivos existentes por programa con prioridad y respeto del principal, incluido CDR para CorelDRAW. Lectores solo para vistas previas; `_convertidos` queda protegido de escrituras y limpieza. Categorías, filtros y reglas plegables con estado por sección en localStorage y controles de 44 px. Respaldos con `sqlite3.Connection.backup`: uno diario, copia previa a cambios de organización/importación, retención independiente de 30 diarios y 30 cambios solo de esta versión. Restauración con bloqueo de solicitudes, cierre/reapertura de conexión y copia previa para deshacer; copia diaria externa opcional, descargas habilitadas en pywebview. Recuperar papelera usa POST y el indexador excluye carpetas internas a cualquier nivel. Segunda parte: basurero y repetidos solo ocultan, sin mover archivos; papelera solo de recuperación. Arrastre interno de uno o varios modelos (Ctrl+clic) a categorías/subcategorías y orden/traslado de categorías en Ajustes, con respaldo previo. Drop nativo Python DOM de pywebview 5+ para copiar carpetas/archivos a Agregados con confirmación, espacio, progreso en hilo, nombres únicos y rechazo de ejecutables/enlaces. Lectura única de carpeta compartida con indexar.py, índice atómico y miniatura invalidada tras subir/restaurar/copiar/recuperar; tarjeta y ficha se actualizan sin perder la posición. Pruebas aisladas sin dependencias en `pruebas/probar_v22.py`. |
| **2.1** | Más cómodo | **Bug:** «Ver imagen» y «Ver manual» respondían *"No encuentro **abrir** en este computador… Ajustes > Programas"* — la UI mandaba `modo=abrir` y el servidor lo trataba como si fuera el nombre de un programa. Ahora solo las claves de `PROGRAMAS_DEF` se buscan como programa; el resto lo abre Windows. **Detección de programas** por el registro (`App Paths` + asociación de `.cdr`/`.lbrn`), que encuentra CorelDRAW aunque cambie de carpeta entre versiones; se validó que el `.exe` hallado sea el correcto tras detectar que `.svg` devolvía el navegador. **Varias carpetas de modelos**: `bibliotecas_extra` en config; la principal conserva sus `rel` para no perder favoritos ni precios, las agregadas llevan marca `[nombre]`. **El logo abre y cierra la columna de filtros** (lo pidió así el papá: tocar el logo, no un botón aparte); el subtítulo del logo cambia a «▸ mostrar filtros» cuando está escondida. **Ajustes por secciones** (Carpetas/Categorías/Programas/Costos/Respaldo/Versión) para no scrollear. |
| 2.0.1 | Icono en el Escritorio | El `.exe` de PyInstaller **no sirve**: Windows 11 lo bloquea con "Una directiva de Control de aplicaciones bloqueó este archivo" (Smart App Control veta los ejecutables sin firma, y no admite excepciones por archivo). Se reemplaza por `INSTALAR.bat` + acceso directo a `pythonw.exe`, que **sí** viene firmado por la Python Software Foundation. Mismo resultado para el usuario: un icono en el Escritorio, ventana propia, sin consola — y el ZIP baja de 29 MB a 110 KB. Además `migrar.py`: al abrir por primera vez busca la instalación anterior y ofrece traerse favoritos, precios, clientes y ventas. Arreglado que el programa moría en silencio sin biblioteca indexada, y que `sys.executable` no sirve para lanzar scripts al estar empaquetado. |
| 2.0 | Programa de verdad | Deja de ser una página web: ahora es un `.exe` con ventana propia (pywebview + WebView2), sin navegador ni consola. Los `.py` quedan **fuera** del bundle para que las actualizaciones sigan funcionando. Dos botones grandes por modelo: CorelDRAW recibe siempre un SVG y LightBurn siempre un `.lbrn`, convirtiendo al vuelo si hace falta (lectores propios de DXF/EPS/SVG/LBRN, sin instalar nada). Lo editado en CorelDRAW se puede dejar como archivo principal. Categorías grandes: crear, renombrar, ordenar (▲▼), borrar, y "esta carpeta entera es de esta categoría". Vista previa dibujada del modelo: pasó de 61% a 97% de modelos con imagen. |
| 1.5 | Se reordena solo | Arregla dos fallas de la 1.4: (1) las categorías nuevas no se aplicaban porque la clasificación se calcula al **indexar**, no al mostrar — ahora `categorias.VERSION_CLASIFICADOR` queda grabado en `biblioteca.json` y la app reindexa sola al arrancar si trae una versión más nueva; (2) `convertir.py` no llegaba porque el actualizador usaba una lista fija de archivos — ahora toma todo lo que venga en el paquete. |
| 1.4 | Categorías y conversor | Arreglada la clasificación (los insectos salían en Vehículos); ahora manda la organización de carpetas del usuario. Crear, renombrar y sacar subcategorías desde Ajustes. Cada archivo se abre con su programa (LightBurn / CorelDRAW), con opción de elegir otro. Conversor de archivos. Los modelos de LightBurn sin foto muestran la miniatura que traen adentro. El respaldo ahora incluye costos y materiales. |
| 1.3 | Cotizador | Calculadora de precios en cada modelo (con las fórmulas de sus Excel), costos y materiales editables en Ajustes. Arreglado el cambio de carpeta: ahora también se puede escribir o pegar la ruta. |
| 1.2 | *(no anunciada)* | Primera versión del cotizador. |
| 1.1.2 | Botones completos | Los botones de manual y foto aparecen siempre; si faltan, salen apagados y sirven para agregarlos. |
| 1.1.1 | Ideas por WhatsApp | Número de WhatsApp para mandar las ideas anotadas. |
| 1.1.0 | Tema y ordenar | Tema claro/oscuro, cambiar carpeta desde la app, quitar modelos sin borrarlos, burbuja de ideas. |
| 1.0.2 | Instalación | Arreglada la instalación de Python en PCs que no lo tienen (alias de Microsoft Store). |
| 1.0.1 | — | Prueba del sistema de actualizaciones. |
| 1.0.0 | Primera | Biblioteca con categorías, favoritos, clientes, ventas, panel, duplicados y papelera. |
