# -*- coding: utf-8 -*-
"""Comprobaciones conservadoras antes de retirar archivos propios de la app."""
import os
import re
import stat


def sin_enlaces(ruta):
    """Rechaza enlaces, junctions y otros reparse points en cualquier componente."""
    if not ruta or not os.path.isabs(ruta):
        return False
    actual = os.path.abspath(ruta)
    while True:
        try:
            dato = os.lstat(actual)
            if stat.S_ISLNK(dato.st_mode) or getattr(dato, "st_file_attributes", 0) & 0x400:
                return False
        except FileNotFoundError:
            pass
        except OSError:
            return False
        padre = os.path.dirname(actual)
        if padre == actual:
            return True
        actual = padre


def dentro(ruta, carpeta):
    if not sin_enlaces(ruta) or not sin_enlaces(carpeta):
        return False
    ruta = os.path.normcase(os.path.realpath(ruta))
    carpeta = os.path.normcase(os.path.realpath(carpeta))
    try:
        return ruta != carpeta and os.path.commonpath([ruta, carpeta]) == carpeta
    except ValueError:
        return False


def archivo_propio(ruta, carpeta, patron):
    return (dentro(ruta, carpeta) and os.path.dirname(os.path.abspath(ruta)) == os.path.abspath(carpeta)
            and bool(re.fullmatch(patron, os.path.basename(ruta)))
            and os.path.isfile(ruta) and os.stat(ruta).st_nlink == 1)


def version_propia(version, carpeta):
    """La ubicación y el nombre no bastan: solo una creación local concede permiso."""
    if not version.get("permiso_borrado") or not carpeta or version.get("tipo") == "convertido":
        return False
    if "_convertidos" in os.path.normpath(carpeta).replace("\\", "/").lower().split("/"):
        return False
    archivo = version.get("archivo") or ""
    if not archivo or archivo != os.path.basename(archivo) or any(x in archivo for x in ("/", "\\", ":")):
        return False
    base, ext = os.path.splitext(archivo)
    patron = re.escape(base) + r"__[0-9]{8}-[0-9]{6}(?:-[2-9][0-9]*|-1[0-9]+)?" + re.escape(ext)
    ruta = version.get("respaldo") or ""
    interna = os.path.join(carpeta, "_versiones_anteriores")
    if not archivo_propio(ruta, interna, patron):
        return False
    original = os.path.join(carpeta, archivo)
    return not os.path.exists(original) or not os.path.samefile(ruta, original)


def arbol_sin_enlaces(ruta):
    if not sin_enlaces(ruta):
        return False
    if os.path.isdir(ruta):
        for padre, dirs, archivos in os.walk(ruta):
            if any(not sin_enlaces(os.path.join(padre, n)) for n in dirs + archivos):
                return False
    return True
