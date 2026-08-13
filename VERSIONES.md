# Versiones de la Biblioteca Láser

Cada versión lleva **número y nombre**, para reconocerla de un vistazo.
Al publicar una nueva hay que actualizar **los dos**:

- `app.py` → `APP_VERSION` y `APP_NOMBRE`
- `version.json` → `version`, `nombre` y `novedades`

> Regla: **nunca repetir el nombre ni el texto de novedades** entre versiones.

| Versión | Nombre | Qué trajo |
|---|---|---|
| **1.5** | Se reordena solo | Arregla dos fallas de la 1.4: (1) las categorías nuevas no se aplicaban porque la clasificación se calcula al **indexar**, no al mostrar — ahora `categorias.VERSION_CLASIFICADOR` queda grabado en `biblioteca.json` y la app reindexa sola al arrancar si trae una versión más nueva; (2) `convertir.py` no llegaba porque el actualizador usaba una lista fija de archivos — ahora toma todo lo que venga en el paquete. |
| 1.4 | Categorías y conversor | Arreglada la clasificación (los insectos salían en Vehículos); ahora manda la organización de carpetas del usuario. Crear, renombrar y sacar subcategorías desde Ajustes. Cada archivo se abre con su programa (LightBurn / CorelDRAW), con opción de elegir otro. Conversor de archivos. Los modelos de LightBurn sin foto muestran la miniatura que traen adentro. El respaldo ahora incluye costos y materiales. |
| 1.3 | Cotizador | Calculadora de precios en cada modelo (con las fórmulas de sus Excel), costos y materiales editables en Ajustes. Arreglado el cambio de carpeta: ahora también se puede escribir o pegar la ruta. |
| 1.2 | *(no anunciada)* | Primera versión del cotizador. |
| 1.1.2 | Botones completos | Los botones de manual y foto aparecen siempre; si faltan, salen apagados y sirven para agregarlos. |
| 1.1.1 | Ideas por WhatsApp | Número de WhatsApp para mandar las ideas anotadas. |
| 1.1.0 | Tema y ordenar | Tema claro/oscuro, cambiar carpeta desde la app, quitar modelos sin borrarlos, burbuja de ideas. |
| 1.0.2 | Instalación | Arreglada la instalación de Python en PCs que no lo tienen (alias de Microsoft Store). |
| 1.0.1 | — | Prueba del sistema de actualizaciones. |
| 1.0.0 | Primera | Biblioteca con categorías, favoritos, clientes, ventas, panel, duplicados y papelera. |
