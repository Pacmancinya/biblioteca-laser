# Versiones de la Biblioteca Láser

Cada versión lleva **número y nombre**, para reconocerla de un vistazo.
Al publicar una nueva hay que actualizar **los dos**:

- `app.py` → `APP_VERSION` y `APP_NOMBRE`
- `version.json` → `version`, `nombre` y `novedades`

> Regla: **nunca repetir el nombre ni el texto de novedades** entre versiones.

| Versión | Nombre | Qué trajo |
|---|---|---|
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
