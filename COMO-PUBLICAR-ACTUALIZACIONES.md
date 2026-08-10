# Cómo entregar la app y publicar actualizaciones

Guía para **Ruperto** (no para el papá).

---

## 1. La primera entrega (una sola vez)

```
python construir_paquete.py
```

Genera **`Biblioteca-Laser.zip`** en el Escritorio (~40 KB).

Se lo pasas por pendrive / WhatsApp / Drive. Él:

1. Descomprime donde quiera (Escritorio, por ejemplo).
2. Doble clic en **`INICIAR Biblioteca.bat`**.
3. Si su PC no tiene Python, **se instala solo** (2-3 min, sin pedir administrador).
4. Le pide elegir **su carpeta de modelos** con una ventana normal de Windows.
5. Indexa y abre la biblioteca. Listo.

> El ZIP **no lleva** `config.json`, `biblioteca.json` ni `biblioteca.db`:
> allá se generan solos con SUS datos y SU carpeta.

---

## 2. Publicar una actualización

Repo: **https://github.com/Pacmancinya/biblioteca-laser** (público, para que el
actualizador pueda descargar sin claves).

1. Haces los cambios en el código.
2. Sube el número de versión en **dos** lugares (deben coincidir):
   - `app.py` → `APP_VERSION = "1.0.2"`
   - `version.json` → `"version": "1.0.2"` y escribe las novedades.
3. Sube los cambios:

```
git add -A
git commit -m "v1.0.2 - lo que cambiaste"
git push
```

Eso es todo. La próxima vez que él abra **⚙️ → Buscar actualizaciones**
(o el archivo *Buscar actualizaciones.bat*), le aparece la versión nueva y
la instala con un botón.

> Ojo: GitHub tarda unos minutos en refrescar `version.json` por su caché.
> Si acabas de publicar y no aparece, espera un poco.

---

## 3. Qué hace (y qué NO hace) la actualización

**Reemplaza** solo el código: `app.py`, `db.py`, `indexar.py`, `categorias.py`,
`ui.html`, el `.bat` y el `LEEME.txt`. Antes de reemplazar, guarda una copia
en `_version_anterior/`.

**Nunca toca:**
- `biblioteca.db` → sus favoritos, precios, clientes y ventas
- `config.json` → su carpeta de modelos
- La carpeta de modelos

Después de actualizar hay que **cerrar y volver a abrir** la biblioteca.

---

## 4. Pasar sus datos de un PC a otro

En **⚙️ Ajustes → Descargar respaldo** se baja un archivo `.json` con todo lo
que él editó (nombres, categorías corregidas, favoritos, precios, stock,
clientes, pedidos y ventas).

En el otro PC: **⚙️ Ajustes → Cargar respaldo**.

Las **categorías automáticas, las fotos y los nombres NO hacen falta
respaldarlos**: se generan solos al indexar, porque el clasificador viaja
en el código y las fotos ya están en las carpetas de los modelos.

> El respaldo se enlaza por la **ruta relativa** de cada modelo. Si en el otro
> PC la carpeta principal cambia de lugar (`D:\Laser` → `E:\Modelos`) pero
> adentro la estructura es la misma, todo calza igual.

---

## 5. Si algo falla en su PC

Que haga doble clic en **`SOLUCIONAR-PROBLEMAS.bat`** y te mande una foto:
muestra la versión de Python, qué archivos hay, la carpeta configurada y si
encontró LightBurn.
