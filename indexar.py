# -*- coding: utf-8 -*-
"""
Indexador de la biblioteca laser.
Recorre la carpeta de modelos y genera biblioteca.json con un registro por modelo.

Un "modelo" = cualquier carpeta que contenga al menos un archivo cortable
(dxf, svg, eps, cdr, ai, lbrn, lbrn2, plt, dwg).
"""
import os, json, re, sys, time
import categorias
import configuracion

BASE = os.environ.get("BIBLIOTECA_LASER_BASE") or os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "biblioteca.json")
CONFIG = os.path.join(BASE, "config.json")
RAIZ_POR_DEFECTO = ""


def obtener_raiz():
    """Nunca abre diálogos ni adivina la carpeta de otro computador."""
    return configuracion.leer(CONFIG).get("biblioteca") or ""


def elegir_carpeta():
    """Abre una ventana para elegir la carpeta de modelos (si se puede)."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(
            "Biblioteca Láser",
            "Elige la carpeta donde tienes tus modelos.\n\n"
            "(Es la carpeta principal; adentro puede tener todas las subcarpetas que quieras.)")
        r = filedialog.askdirectory(title="Elige la carpeta con tus modelos")
        root.destroy()
        return r.replace("/", os.sep) if r else ""
    except Exception:
        print("\nNo encuentro la carpeta de modelos.")
        print("Escribe (o arrastra) la ruta de la carpeta y presiona Enter:")
        r = input("> ").strip().strip('"')
        return r if os.path.isdir(r) else ""


def guardar_raiz(r):
    configuracion.modificar(CONFIG, {"biblioteca": r})
    return r


RAIZ = None  # se define en indexar()

CORTE   = {".dxf", ".svg", ".eps", ".cdr", ".ai", ".lbrn", ".lbrn2", ".plt", ".dwg", ".cmx"}
IMAGEN  = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
MANUAL  = {".pdf", ".txt", ".doc", ".docx"}
TRES_D  = {".stl", ".step", ".stp", ".sldprt", ".skp", ".3dm", ".obj"}
VIDEO   = {".mp4", ".avi", ".mov", ".mkv"}
COMPRIM = {".zip", ".rar", ".7z"}
IGNORAR = {"thumbs.db", "desktop.ini", ".ds_store"}
CARPETAS_INTERNAS = {"respaldos", "_papelera", "_convertidos", "_versiones_anteriores",
                    "_version_anterior", ".miniaturas", "_ventana", "_exe"}

# grosores tipo "3mm", "1.5 mm", "6mm"
RE_GROSOR = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm", re.IGNORECASE)


def limpiar_nombre(nombre):
    n = nombre.replace("_", " ").replace("-", " ")
    n = re.sub(r"\s+", " ", n).strip()
    return n


def todas_las_carpetas():
    """Las carpetas de modelos: la principal y las que el usuario agrego.

    La principal conserva su lugar de siempre en config.json ("biblioteca"),
    asi lo que el usuario ya tenia guardado (favoritos, precios) sigue
    calzando. Las extra van en "bibliotecas_extra".
    """
    cfg = configuracion.leer(CONFIG)
    carpetas = []
    principal = cfg.get("biblioteca")
    if principal:
        carpetas.append(principal)
    for extra in (cfg.get("bibliotecas_extra") or []):
        if extra and extra not in carpetas:
            carpetas.append(extra)
    return carpetas


def heredar_categoria(modelo, por_rel):
    if modelo["categoria"] != "Otros":
        return
    partes = modelo["rel"].split(os.sep)
    for corte in range(len(partes) - 1, 0, -1):
        padre = por_rel.get(os.sep.join(partes[:corte]))
        if padre and padre["categoria"] != "Otros":
            modelo["categoria"] = padre["categoria"]
            modelo["subcategoria"] = padre["subcategoria"]
            break


def leer_modelo(dirpath, carpeta_base, marca="", identificador=0, padres=None):
    """Única lectura de una carpeta, usada por la app y el índice completo."""
    filenames = sorted(e.name for e in os.scandir(dirpath) if e.is_file())
    archivos = {"corte": [], "imagen": [], "manual": [], "3d": [], "video": [], "otro": []}
    grosores = set()
    tam_total = 0
    mtime = 0

    for fn in filenames:
        if fn.lower() in IGNORAR:
            continue
        ext = os.path.splitext(fn)[1].lower()
        full = os.path.join(dirpath, fn)
        try:
            st = os.stat(full)
            tam_total += st.st_size
            if st.st_mtime > mtime:
                mtime = st.st_mtime
        except OSError:
            pass

        if ext in CORTE:
            archivos["corte"].append(fn)
            for g in RE_GROSOR.findall(fn):
                grosores.add(g.replace(",", ".") + "mm")
        elif ext in IMAGEN:
            archivos["imagen"].append(fn)
        elif ext in MANUAL:
            archivos["manual"].append(fn)
        elif ext in TRES_D:
            archivos["3d"].append(fn)
        elif ext in VIDEO:
            archivos["video"].append(fn)
        elif ext in COMPRIM:
            archivos["otro"].append(fn)

    if not archivos["corte"]:
        return None  # no es un modelo

    rel = os.path.relpath(dirpath, carpeta_base)
    partes = rel.split(os.sep)
    nombre = partes[-1] if rel != "." else os.path.basename(carpeta_base.rstrip(os.sep + "/"))
    if marca:
        # la carpeta principal no lleva marca: asi los favoritos y precios
        # que el usuario ya tenia guardados siguen calzando igual
        rel = os.path.join(marca, rel) if rel != "." else marca

    # preview: prefiere imagen con nombre parecido al de la carpeta, si no la primera
    preview = ""
    if archivos["imagen"]:
        base = nombre.lower()
        mejor = None
        for im in archivos["imagen"]:
            if os.path.splitext(im)[0].lower() in base or base in os.path.splitext(im)[0].lower():
                mejor = im
                break
        preview = mejor or archivos["imagen"][0]

    # extensiones de corte presentes (para filtrar por formato)
    formatos = sorted({os.path.splitext(f)[1].lower().lstrip(".") for f in archivos["corte"]})

    nom_limpio = limpiar_nombre(nombre)
    cat, sub = categorias.clasificar(nom_limpio, partes)

    modelo = {
        "id": identificador,
        "nombre": nom_limpio,
        "nombre_real": nombre,
        "ruta": dirpath,
        "rel": rel,
        "categoria": cat,
        "subcategoria": sub,
        "carpeta_origen": partes[0] if rel != "." else "",
        "raiz": carpeta_base,
        "ruta_partes": partes,
        "archivos": archivos,
        "n_corte": len(archivos["corte"]),
        "n_imagen": len(archivos["imagen"]),
        "formatos": formatos,
        "grosores": sorted(grosores),
        "preview": preview,
        "tiene_manual": bool(archivos["manual"]),
        "tiene_imagen": bool(archivos["imagen"]),
        "tiene_3d": bool(archivos["3d"]),
        "tiene_video": bool(archivos["video"]),
        "tiene_lightburn": any(f.lower().endswith((".lbrn", ".lbrn2")) for f in archivos["corte"]),
        "mb": round(tam_total / (1024 * 1024), 1),
        "mtime": int(mtime),
    }
    heredar_categoria(modelo, padres or {})
    return modelo


def guardar_json_atomico(ruta, datos):
    """Un fallo deja el índice anterior entero; el temporal vive en el mismo disco."""
    import tempfile
    fd, temporal = tempfile.mkstemp(prefix=".indice-", dir=os.path.dirname(os.path.abspath(ruta)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)


def indexar(carpeta=None, avance=None):
    global RAIZ
    RAIZ = carpeta or obtener_raiz()
    if not RAIZ:
        raise ValueError("Elige tu carpeta de modelos en Ajustes > Carpetas.")
    carpetas = todas_las_carpetas() or [RAIZ]
    if carpeta:
        carpetas[0] = carpeta
    for raiz in carpetas:
        if not os.path.isdir(raiz):
            raise FileNotFoundError("No encuentro la carpeta de modelos %s. ¿Está conectado el disco?" % raiz)
    RAIZ = carpetas[0]
    print("Biblioteca:", RAIZ)
    for extra in carpetas[1:]:
        print("  y tambien:", extra)
    print("Indexando, espera un momento...")

    t0 = time.time()
    modelos = []
    total_carpetas = 0
    ultima_notificacion = 0

    for i_carpeta, carpeta_base in enumerate(carpetas):
      # las carpetas agregadas llevan una marca en su ruta relativa, para que
      # dos modelos que se llamen igual en carpetas distintas no se pisen
      marca = "" if i_carpeta == 0 else ("[%s]" % os.path.basename(carpeta_base.rstrip(os.sep + "/")) )
      def fallo(error):
          raise error
      for dirpath, dirnames, filenames in os.walk(carpeta_base, onerror=fallo):
        total_carpetas += 1
        if avance and time.monotonic() - ultima_notificacion >= 0.1:
            avance("Ordenando tu biblioteca... %s carpetas, %s modelos" % (total_carpetas, len(modelos)))
            ultima_notificacion = time.monotonic()
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in CARPETAS_INTERNAS]

        m = leer_modelo(dirpath, carpeta_base, marca, len(modelos))
        if m:
            modelos.append(m)

    # --- Herencia: las subcarpetas técnicas ("Inch", "metric", "Old", "files"...)
    # toman la categoría del modelo que las contiene.
    por_rel = {m["rel"]: m for m in modelos}
    heredados = 0
    for m in modelos:
        antes = m["categoria"]
        heredar_categoria(m, por_rel)
        heredados += int(antes != m["categoria"])

    data = {
        "raiz": RAIZ,
        "raices": carpetas,
        "heredados": heredados,
        "generado": int(time.time()),
        # con qué versión del clasificador se ordenó esto: si la app trae una
        # más nueva, vuelve a ordenar sola
        "clasificador": getattr(categorias, "VERSION_CLASIFICADOR", 1),
        "total_modelos": len(modelos),
        "total_carpetas": total_carpetas,
        "categorias": categorias.estructura(),
        "modelos": modelos,
    }
    for raiz in carpetas:
        if not os.path.isdir(raiz):
            raise FileNotFoundError("No encuentro la carpeta de modelos %s. ¿Está conectado el disco?" % raiz)
    guardar_json_atomico(SALIDA, data)
    if avance:
        avance("Ordenando tu biblioteca... %s carpetas, %s modelos. Listo." % (total_carpetas, len(modelos)))

    seg = round(time.time() - t0, 1)
    if len(carpetas) > 1:
        print("Carpetas de modelos :", len(carpetas))
    print("Carpetas recorridas :", total_carpetas)
    print("MODELOS indexados   :", len(modelos))
    print("Con imagen          :", sum(1 for m in modelos if m["tiene_imagen"]))
    print("Con manual (pdf)    :", sum(1 for m in modelos if m["tiene_manual"]))
    print("Con archivo LightBurn:", sum(1 for m in modelos if m["tiene_lightburn"]))
    print()
    print("--- Clasificacion ---")
    cuenta = {}
    for m in modelos:
        cuenta[m["categoria"]] = cuenta.get(m["categoria"], 0) + 1
    for c in categorias.ORDEN:
        if c in cuenta:
            pct = round(cuenta[c] / len(modelos) * 100)
            print(f"  {c:<22} {cuenta[c]:>5}  ({pct}%)")
    print()
    print("Segundos            :", seg)
    print("Archivo             :", SALIDA)


if __name__ == "__main__":
    try:
        indexar(sys.argv[1] if len(sys.argv) > 1 else None)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
