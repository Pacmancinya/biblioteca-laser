# -*- coding: utf-8 -*-
"""Busca una instalacion anterior de la Biblioteca y se trae sus datos.

Asi el usuario no tiene que copiar archivos a mano al pasar a la version
nueva: el programa encuentra solo su biblioteca.db y su config.json.

Nunca borra ni modifica la carpeta vieja: solo copia.
"""
import os
import shutil

# lo que vale la pena traerse de la instalacion anterior
DATOS = ["biblioteca.db", "config.json", "biblioteca.json"]

# las carpetas donde la gente suele dejar el programa
def _lugares(desde=None):
    inicio = os.path.expanduser("~")
    base = []
    # lo primero: al lado de donde esta instalado ahora. Es lo mas comun,
    # porque la gente descomprime la version nueva junto a la vieja.
    if desde:
        padre = os.path.dirname(os.path.abspath(desde))
        base.append(padre)
        base.append(os.path.dirname(padre))
    base += [
        os.path.join(inicio, "Desktop"),
        os.path.join(inicio, "OneDrive", "Desktop"),
        os.path.join(inicio, "Escritorio"),
        os.path.join(inicio, "Downloads"),
        os.path.join(inicio, "Descargas"),
        os.path.join(inicio, "Documents"),
        os.path.join(inicio, "Documentos"),
        inicio,
        "C:\\",
        "D:\\",
    ]
    return [x for x in base if os.path.isdir(x)]


def _es_instalacion(carpeta):
    """Una carpeta cuenta si tiene datos Y parece de la Biblioteca."""
    try:
        hay = set(os.listdir(carpeta))
    except OSError:
        return False
    if "biblioteca.db" not in hay:
        return False
    # que sea de verdad nuestra app, no una carpeta cualquiera
    return bool(hay & {"app.py", "ui.html", "indexar.py", "Biblioteca Laser.exe"})


def buscar(saltar=None):
    """Devuelve las instalaciones anteriores encontradas, de mas nueva a mas vieja."""
    saltar = os.path.abspath(saltar or "").lower()
    vistas = set()
    encontradas = []
    for lugar in _lugares(saltar):
        try:
            hijos = os.listdir(lugar)
        except OSError:
            continue
        # miramos la carpeta y un nivel adentro (no mas: seria lentisimo)
        candidatas = [lugar] + [os.path.join(lugar, h) for h in hijos]
        for c in candidatas:
            try:
                if not os.path.isdir(c):
                    continue
            except OSError:
                continue
            clave = os.path.abspath(c).lower()
            if clave in vistas or clave == saltar:
                continue
            vistas.add(clave)
            if _es_instalacion(c):
                try:
                    cuando = os.path.getmtime(os.path.join(c, "biblioteca.db"))
                except OSError:
                    cuando = 0
                encontradas.append((cuando, c))
    encontradas.sort(reverse=True)
    return [c for _t, c in encontradas]


def resumen(carpeta):
    """Que datos tiene guardados esa instalacion, en cristiano."""
    import sqlite3
    info = {"carpeta": carpeta, "modelos": 0, "clientes": 0, "ventas": 0,
            "favoritos": 0, "sugerencias": 0}
    db = os.path.join(carpeta, "biblioteca.db")
    try:
        cx = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        for tabla, clave in (("modelos", "modelos"), ("clientes", "clientes"),
                             ("ventas", "ventas"), ("sugerencias", "sugerencias")):
            try:
                info[clave] = cx.execute("SELECT COUNT(*) FROM %s" % tabla).fetchone()[0]
            except sqlite3.Error:
                pass
        try:
            info["favoritos"] = cx.execute(
                "SELECT COUNT(*) FROM modelos WHERE favorito=1").fetchone()[0]
        except sqlite3.Error:
            pass
        cx.close()
    except Exception:
        pass
    return info


def traer(desde, hacia):
    """Copia los datos de la instalacion vieja a la nueva.

    Ojo con SQLite: si la base quedo en modo WAL, hay cambios en el archivo
    -wal que NO estan en el .db. Por eso se copian los tres archivos.
    """
    copiados = []
    for n in DATOS + ["biblioteca.db-wal", "biblioteca.db-shm"]:
        o = os.path.join(desde, n)
        d = os.path.join(hacia, n)
        if not os.path.exists(o):
            continue
        try:
            shutil.copy2(o, d)
            if n in DATOS:
                copiados.append(n)
        except OSError:
            pass

    # dejar la base consolidada y comprobar que quedo sana
    destino_db = os.path.join(hacia, "biblioteca.db")
    if os.path.exists(destino_db):
        try:
            import sqlite3
            cx = sqlite3.connect(destino_db)
            estado = cx.execute("PRAGMA integrity_check").fetchone()[0]
            cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            cx.commit()
            cx.close()
            if estado != "ok":
                return {"error": "Los datos de la carpeta vieja venian dañados. "
                                 "Se empieza con datos nuevos."}
        except Exception as e:
            return {"error": "No pude leer los datos viejos: %s" % str(e)[:80]}

    # las carpetas con archivos que el usuario cargo o borro
    for carpeta in ("_papelera", "_convertidos"):
        o = os.path.join(desde, carpeta)
        d = os.path.join(hacia, carpeta)
        if os.path.isdir(o) and not os.path.isdir(d):
            try:
                shutil.copytree(o, d)
            except OSError:
                pass

    return {"ok": True, "copiados": copiados}


def hace_falta(carpeta):
    """¿Esta instalacion esta recien puesta, sin datos propios?"""
    return not os.path.exists(os.path.join(carpeta, "biblioteca.db"))
