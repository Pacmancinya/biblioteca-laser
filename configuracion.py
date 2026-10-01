# -*- coding: utf-8 -*-
"""Configuración compartida: cambios pequeños, escritura atómica y sin BOM."""
import json
import os
import tempfile
import threading
import seguridad_archivos

LOCK = threading.RLock()


def leer(ruta):
    with LOCK:
        try:
            with open(ruta, encoding="utf-8-sig") as archivo:
                dato = json.load(archivo)
            if not isinstance(dato, dict):
                raise ValueError("La configuración debe ser un objeto.")
            return dato
        except FileNotFoundError:
            return {}


def modificar(ruta, cambios):
    with LOCK:
        dato = leer(ruta)
        if callable(cambios):
            cambios(dato)
        else:
            dato.update(cambios)
        fd, temporal = tempfile.mkstemp(prefix=".config-", dir=os.path.dirname(os.path.abspath(ruta)))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as archivo:
                json.dump(dato, archivo, ensure_ascii=False, indent=2)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, ruta)
        finally:
            if seguridad_archivos.archivo_propio(temporal, os.path.dirname(os.path.abspath(ruta)), r"\.config-[a-z0-9_]+"):
                os.remove(temporal)
        return dato
