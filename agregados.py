# -*- coding: utf-8 -*-
"""Importación por copia. Las rutas solo llegan desde el drop nativo de Python.

La HTTP recibe un identificador aleatorio de un plan ya preparado, nunca rutas.
No se sigue ningún enlace y ningún archivo se abre para escritura en el origen.
"""
import os
import shutil
import stat
import threading
import uuid

PROHIBIDAS = {".exe", ".bat", ".cmd", ".lnk", ".ps1", ".vbs", ".js", ".msi"}
LOCK = threading.RLock()
TRABAJOS = {}


def _normal(ruta):
    return os.path.normcase(os.path.abspath(ruta))


def _dentro(ruta, carpeta):
    try:
        return os.path.commonpath([_normal(ruta), _normal(carpeta)]) == _normal(carpeta)
    except ValueError:
        return False


def _sin_enlaces(ruta):
    actual = os.path.abspath(ruta)
    while True:
        st = os.lstat(actual)
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
            raise ValueError("No se agregan enlaces ni accesos directos: " + os.path.basename(ruta))
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre


def _archivo(ruta):
    _sin_enlaces(ruta)
    if os.path.splitext(ruta)[1].lower() in PROHIBIDAS:
        raise ValueError("No se agregan ejecutables ni accesos directos: " + os.path.basename(ruta))
    st = os.stat(ruta)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("Ese elemento no es un archivo común.")
    return (ruta, st.st_size, st.st_mtime_ns)


def planificar(rutas, raiz):
    """Solo lectura: valida toda la selección antes de crear un solo destino."""
    if not raiz:
        raise ValueError("Elige primero tu carpeta principal de modelos en Ajustes.")
    if not os.path.isdir(raiz):
        raise ValueError("No encuentro la carpeta de modelos %s. ¿Está conectado el disco?" % raiz)
    _sin_enlaces(raiz)
    seleccion = list(dict.fromkeys(os.path.abspath(r) for r in rutas if r))
    if not seleccion:
        raise ValueError("No llegaron rutas. Abre la Biblioteca desde su icono.")
    seleccion = [r for r in seleccion if not any(r != p and os.path.isdir(p) and _dentro(r, p) for p in seleccion)]
    items, cantidad, total = [], 0, 0
    agregados = os.path.join(raiz, "Agregados")
    for ruta in seleccion:
        _sin_enlaces(ruta)
        # Evita copiar recursivamente la propia biblioteca o Agregados.
        if _dentro(ruta, agregados) or (os.path.isdir(ruta) and _dentro(agregados, ruta)):
            raise ValueError("Arrastra una carpeta de modelos, no la biblioteca principal ni Agregados.")
        es_carpeta = os.path.isdir(ruta)
        nombre = os.path.basename(ruta.rstrip(os.sep + "/"))
        if not es_carpeta:
            nombre = os.path.splitext(nombre)[0] or nombre
        carpetas, archivos = [""], []
        if es_carpeta:
            def fallo(error):
                raise error
            for carpeta, dirs, files in os.walk(ruta, followlinks=False, onerror=fallo):
                _sin_enlaces(carpeta)
                for d in sorted(dirs):
                    _sin_enlaces(os.path.join(carpeta, d))
                    carpetas.append(os.path.relpath(os.path.join(carpeta, d), ruta))
                for f in sorted(files):
                    full, tam, fecha = _archivo(os.path.join(carpeta, f))
                    archivos.append((full, os.path.relpath(full, ruta), tam, fecha))
        else:
            full, tam, fecha = _archivo(ruta)
            archivos.append((full, os.path.basename(ruta), tam, fecha))
        cantidad += len(archivos)
        total += sum(a[2] for a in archivos)
        items.append({"nombre": nombre, "carpetas": carpetas, "archivos": archivos, "carpeta": es_carpeta})
    if shutil.disk_usage(raiz).free < total:
        raise ValueError("No hay espacio suficiente en el disco de la biblioteca para esta copia.")
    return {"items": items, "total": cantidad, "bytes": total,
            "carpetas": sum(i["carpeta"] for i in items),
            "sueltos": sum(not i["carpeta"] for i in items)}


def _cambiar(job, **campos):
    with LOCK:
        job.update(campos)


def estado(identificador):
    with LOCK:
        job = TRABAJOS.get(identificador)
        if not job:
            return {"error": "Ese agregado ya no está disponible. Arrastra de nuevo."}
        return {k: v for k, v in job.items() if not k.startswith("_")}


def preparar(rutas, raiz, categoria, subcategoria, al_final, respaldar):
    with LOCK:
        if any(j["estado"] in ("revisando", "confirmar", "iniciando", "copiando", "leyendo") for j in TRABAJOS.values()):
            return {"error": "Termina o cancela el agregado anterior antes de agregar otro."}
        TRABAJOS.clear()
        identificador = uuid.uuid4().hex
        job = {"id": identificador, "estado": "revisando", "copiados": 0, "bytes_copiados": 0,
               "total": 0, "bytes": 0, "categoria": categoria, "subcategoria": subcategoria,
               "_raiz": raiz, "_final": al_final, "_respaldo": respaldar}
        TRABAJOS[identificador] = job

    def revisar():
        try:
            plan = planificar(rutas, raiz)
            with LOCK:
                if job["estado"] == "cancelado":
                    return
                job["_plan"] = plan
                job.update({k: v for k, v in plan.items() if k != "items"})
                job["estado"] = "confirmar"
        except Exception as e:
            _cambiar(job, estado="error", error=str(e))
    threading.Thread(target=revisar, daemon=True).start()
    return {"ok": True, "id": identificador}


def cancelar(identificador):
    with LOCK:
        job = TRABAJOS.get(identificador)
        if not job or job["estado"] not in ("confirmar", "revisando"):
            return {"error": "La copia ya empezó."}
        job["estado"] = "cancelado"
    return {"ok": True}


def _reservar(carpeta, nombre):
    for n in range(1, 100000):
        destino = os.path.join(carpeta, nombre if n == 1 else "%s (%s)" % (nombre, n))
        try:
            os.mkdir(destino)
            return destino
        except FileExistsError:
            continue
    raise ValueError("No pude encontrar un nombre libre para esa carpeta.")


def confirmar(identificador):
    with LOCK:
        job = TRABAJOS.get(identificador)
        if not job or job["estado"] != "confirmar":
            return {"error": "Primero revisa y confirma los elementos que vas a agregar."}
        job["estado"] = "iniciando"
    # El hilo hace respaldo y copia sin bloquear las solicitudes HTTP.
    threading.Thread(target=_copiar, args=(job,), daemon=True).start()
    return {"ok": True, "id": identificador}


def _copiar(job):
    destinos, nuevos = [], []
    try:
        raiz, plan = job["_raiz"], job["_plan"]
        _sin_enlaces(raiz)
        if shutil.disk_usage(raiz).free < plan["bytes"]:
            raise ValueError("No hay espacio suficiente. No se inició la copia.")
        if job["categoria"]:
            respaldo = job["_respaldo"]()
            if not respaldo.get("ok"):
                raise ValueError(respaldo.get("error", "No pude respaldar el orden."))
        carpeta = os.path.join(raiz, "Agregados")
        os.makedirs(carpeta, exist_ok=True)
        _sin_enlaces(carpeta)
        _cambiar(job, estado="copiando")
        for item in plan["items"]:
            destino = _reservar(carpeta, item["nombre"])
            destinos.append(destino)
            for sub in item["carpetas"]:
                os.makedirs(os.path.join(destino, sub), exist_ok=True)
            for origen, relativo, tam, fecha in item["archivos"]:
                full, ahora, mtime = _archivo(origen)
                if (ahora, mtime) != (tam, fecha):
                    raise ValueError("El origen cambió desde la confirmación. Arrastra de nuevo: " + os.path.basename(origen))
                salida = os.path.join(destino, relativo)
                _sin_enlaces(os.path.dirname(salida))
                with open(full, "rb") as entrada, open(salida, "xb") as copia:
                    while True:
                        bloque = entrada.read(1024 * 1024)
                        if not bloque:
                            break
                        copia.write(bloque)
                        _cambiar(job, bytes_copiados=job["bytes_copiados"] + len(bloque))
                st = os.stat(origen)
                if (st.st_size, st.st_mtime_ns) != (tam, fecha):
                    raise ValueError("Un original cambió durante la copia. Los originales siguen donde estaban.")
                shutil.copystat(origen, salida)
                _cambiar(job, copiados=job["copiados"] + 1)
        _cambiar(job, estado="leyendo")
        nuevos = job["_final"](destinos, job["categoria"], job["subcategoria"])
        _cambiar(job, estado="listo", nuevos=nuevos)
    except Exception as e:
        # Conserva las copias parciales y ofrece sus modelos; jamás borra originales.
        if destinos:
            try:
                nuevos = job["_final"](destinos, job["categoria"], job["subcategoria"])
            except Exception:
                pass
        _cambiar(job, estado="error", nuevos=nuevos,
                 error=str(e) + (" La copia quedó incompleta en Agregados. Tus originales siguen intactos." if destinos else ""))
