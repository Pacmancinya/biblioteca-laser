# -*- coding: utf-8 -*-
"""
Biblioteca Láser — app local.
Servidor en 127.0.0.1 que sirve la biblioteca en el navegador y permite:
  - navegar / buscar / filtrar los modelos del disco
  - editar nombre, categoría, notas, precios y stock (SIN tocar los archivos)
  - marcar favoritos
  - cargar imagen / manual / modelo (con historial de 3 versiones)
  - clientes, pedidos con cobro y vencimiento
  - ventas de feria y panel de métricas
"""
import os, sys, json, re, threading, webbrowser, subprocess, urllib.parse, mimetypes, hashlib, shutil, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import db

APP_VERSION = "1.2.0"
# De dónde se bajan las actualizaciones (ZIP con los archivos de la app).
URL_ACTUALIZACIONES = "https://raw.githubusercontent.com/Pacmancinya/biblioteca-laser/main/version.json"
# A quién le llegan las ideas/cambios que anota el usuario (WhatsApp de Ruperto).
WHATSAPP_SOPORTE = "56954703465"

BASE = os.path.dirname(os.path.abspath(__file__))
INDICE = os.path.join(BASE, "biblioteca.json")
CONFIG = os.path.join(BASE, "config.json")
CACHE_THUMBS = os.path.join(BASE, ".miniaturas")
PUERTO = 8777
CARPETA_VERSIONES = "_versiones_anteriores"

os.makedirs(CACHE_THUMBS, exist_ok=True)

try:
    from PIL import Image
    HAY_PIL = True
except ImportError:
    HAY_PIL = False

EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
EXT_MANUAL = {".pdf"}
EXT_CORTE = {".dxf", ".svg", ".eps", ".cdr", ".ai", ".lbrn", ".lbrn2", ".plt", ".dwg", ".cmx"}


# ---------------------------------------------------------------- índice
def cargar_indice():
    if not os.path.exists(INDICE):
        print("Falta biblioteca.json — ejecuta primero:  python indexar.py")
        sys.exit(1)
    with open(INDICE, encoding="utf-8") as f:
        return json.load(f)

DATOS = cargar_indice()
RAIZ = DATOS["raiz"]
MODELOS = DATOS["modelos"]
POR_REL = {m["rel"]: m for m in MODELOS}


def recargar_indice():
    global DATOS, RAIZ, MODELOS, POR_REL
    DATOS = cargar_indice()
    RAIZ = DATOS["raiz"]
    MODELOS = DATOS["modelos"]
    POR_REL = {m["rel"]: m for m in MODELOS}


def cargar_config():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def guardar_config(c):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)

CFG = cargar_config()


def buscar_lightburn():
    if CFG.get("lightburn") and os.path.exists(CFG["lightburn"]):
        return CFG["lightburn"]
    cand = [r"C:\Program Files\LightBurn\LightBurn.exe",
            r"C:\Program Files (x86)\LightBurn\LightBurn.exe"]
    for b in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
              os.environ.get("LOCALAPPDATA", "")):
        if b:
            cand.append(os.path.join(b, "LightBurn", "LightBurn.exe"))
    for c in cand:
        if c and os.path.exists(c):
            CFG["lightburn"] = c
            guardar_config(CFG)
            return c
    return None


def ruta_segura(p):
    try:
        p = os.path.abspath(p)
        return os.path.commonpath([os.path.abspath(RAIZ), p]) == os.path.abspath(RAIZ)
    except Exception:
        return False


# ---------------------------------------------------------------- vista de modelos
def modelo_vista(m, metas=None):
    """Mezcla el modelo del disco con lo que el usuario editó."""
    metas = metas if metas is not None else db.meta_todos()
    mt = metas.get(m["rel"]) or {}
    partes = m["ruta_partes"]
    return {
        "rel": m["rel"], "id": m["id"],
        "n": mt.get("nombre") or m["nombre"],
        "n_orig": m["nombre"],
        "c": mt.get("categoria") or m["categoria"],
        "s": mt.get("subcategoria") if mt.get("subcategoria") is not None else m["subcategoria"],
        "ruta_partes": partes,
        "fmt": m["formatos"], "gr": m["grosores"],
        "img": 1 if m["tiene_imagen"] else 0, "man": 1 if m["tiene_manual"] else 0,
        "lb": 1 if m["tiene_lightburn"] else 0, "d3": 1 if m["tiene_3d"] else 0,
        "fav": 1 if mt.get("favorito") else 0,
        "oculto": 1 if mt.get("oculto") else 0,
        "costo": mt.get("costo"), "precio": mt.get("precio"), "stock": mt.get("stock") or 0,
        "cliente_id": mt.get("cliente_id"),
        "notas": mt.get("notas") or "",
        "nc": m["n_corte"], "mb": m["mb"],
    }


def categorias_con_conteo(vistas):
    """Las 6 categorías grandes con sus subcategorías y cuántos modelos tiene cada una."""
    import categorias as cats
    conteo, conteo_sub = {}, {}
    for v in vistas:
        conteo[v["c"]] = conteo.get(v["c"], 0) + 1
        conteo_sub[(v["c"], v["s"])] = conteo_sub.get((v["c"], v["s"]), 0) + 1
    salida = []
    for grupo in cats.estructura():
        cat = grupo["nombre"]
        subs = [{"nombre": s, "n": conteo_sub.get((cat, s), 0)} for s in grupo["subs"]]
        # subcategorías que el usuario creó a mano al editar un modelo
        for (c, s), n in conteo_sub.items():
            if c == cat and s and s not in grupo["subs"]:
                subs.append({"nombre": s, "n": n})
        salida.append({"nombre": cat, "n": conteo.get(cat, 0),
                       "subs": [s for s in subs if s["n"] > 0]})
    # categorías inventadas por el usuario
    for c, n in conteo.items():
        if c not in [g["nombre"] for g in salida]:
            subs = [{"nombre": s, "n": k} for (cc, s), k in conteo_sub.items() if cc == c and s]
            salida.append({"nombre": c, "n": n, "subs": subs})
    return [g for g in salida if g["n"] > 0]


def miniatura(rel):
    m = POR_REL.get(rel)
    if not m or not m.get("preview"):
        return None
    origen = os.path.join(m["ruta"], m["preview"])
    if not os.path.exists(origen):
        return None
    if not HAY_PIL:
        with open(origen, "rb") as f:
            return f.read(), mimetypes.guess_type(origen)[0] or "image/jpeg"
    h = hashlib.md5(rel.encode("utf-8")).hexdigest()
    destino = os.path.join(CACHE_THUMBS, h + ".jpg")
    try:
        if not os.path.exists(destino) or os.path.getmtime(destino) < os.path.getmtime(origen):
            im = Image.open(origen).convert("RGB")
            im.thumbnail((520, 520), Image.LANCZOS)
            im.save(destino, "JPEG", quality=82)
    except Exception:
        return None
    with open(destino, "rb") as f:
        return f.read(), "image/jpeg"


# ---------------------------------------------------------------- subir archivos
def ruta_respaldo(carpeta, nombre):
    """Nombre único dentro de _versiones_anteriores (nunca pisa un respaldo previo)."""
    vers = os.path.join(carpeta, CARPETA_VERSIONES)
    os.makedirs(vers, exist_ok=True)
    base, ext = os.path.splitext(nombre)
    marca = time.strftime("%Y%m%d-%H%M%S")
    p = os.path.join(vers, f"{base}__{marca}{ext}")
    n = 2
    while os.path.exists(p):
        p = os.path.join(vers, f"{base}__{marca}-{n}{ext}")
        n += 1
    return p


def guardar_archivo(rel, tipo, nombre, datos):
    """Guarda un archivo en la carpeta del modelo. Si reemplaza a otro,
    respalda el anterior en _versiones_anteriores (máximo 3)."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    carpeta = m["ruta"]
    if not ruta_segura(carpeta):
        return {"error": "ruta no permitida"}
    nombre = os.path.basename(nombre).replace("\\", "").replace("/", "")
    if not nombre:
        return {"error": "nombre inválido"}
    destino = os.path.join(carpeta, nombre)

    if os.path.exists(destino):
        respaldo = ruta_respaldo(carpeta, nombre)
        try:
            shutil.move(destino, respaldo)
            db.registrar_version(rel, tipo, nombre, respaldo)
        except OSError as e:
            return {"error": f"no se pudo respaldar: {e}"}

    with open(destino, "wb") as f:
        f.write(datos)
    return {"ok": True, "archivo": nombre}


# ---------------------------------------------------------------- papelera
PAPELERA = os.path.join(BASE, "_papelera")

def _destino_papelera(nombre):
    os.makedirs(PAPELERA, exist_ok=True)
    base, ext = os.path.splitext(nombre)
    marca = time.strftime("%Y%m%d-%H%M%S")
    p = os.path.join(PAPELERA, f"{base}__{marca}{ext}")
    n = 2
    while os.path.exists(p):
        p = os.path.join(PAPELERA, f"{base}__{marca}-{n}{ext}")
        n += 1
    return p


def borrar_archivo(rel, nombre):
    """Manda UN archivo a la papelera (no lo borra de verdad)."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    origen = os.path.join(m["ruta"], os.path.basename(nombre))
    if not ruta_segura(origen) or not os.path.isfile(origen):
        return {"error": "archivo no encontrado"}
    destino = _destino_papelera(os.path.basename(nombre))
    try:
        shutil.move(origen, destino)
    except OSError as e:
        return {"error": f"no se pudo mover: {e}"}
    db.a_papelera("archivo", rel, os.path.basename(nombre), origen, destino)
    recargar_parcial(rel)
    return {"ok": True}


def borrar_modelo(rel):
    """Manda la CARPETA completa del modelo a la papelera."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    origen = m["ruta"]
    if not ruta_segura(origen) or not os.path.isdir(origen):
        return {"error": "carpeta no encontrada"}
    if os.path.abspath(origen) == os.path.abspath(RAIZ):
        return {"error": "no se puede borrar la carpeta principal"}
    destino = _destino_papelera(os.path.basename(origen))
    try:
        shutil.move(origen, destino)
    except OSError as e:
        return {"error": f"no se pudo mover: {e}"}
    db.a_papelera("modelo", rel, m["nombre"], origen, destino)
    # sacar del índice en memoria
    MODELOS[:] = [x for x in MODELOS if x["rel"] != rel and not x["rel"].startswith(rel + os.sep)]
    POR_REL.pop(rel, None)
    for k in [k for k in POR_REL if k.startswith(rel + os.sep)]:
        POR_REL.pop(k, None)
    return {"ok": True}


def restaurar_papelera(pid):
    it = db.item_papelera(pid)
    if not it:
        return {"error": "no está en la papelera"}
    if not os.path.exists(it["destino"]):
        return {"error": "el archivo ya no está en la papelera"}
    if os.path.exists(it["origen"]):
        return {"error": "ya existe algo con ese nombre en la carpeta original"}
    try:
        os.makedirs(os.path.dirname(it["origen"]), exist_ok=True)
        shutil.move(it["destino"], it["origen"])
    except OSError as e:
        return {"error": f"no se pudo restaurar: {e}"}
    db.quitar_de_papelera(pid)
    if it["tipo"] == "archivo":
        recargar_parcial(it["rel"])
    return {"ok": True, "tipo": it["tipo"]}


def vaciar_papelera():
    n = 0
    for it in db.papelera():
        try:
            if os.path.isdir(it["destino"]):
                shutil.rmtree(it["destino"]); n += 1
            elif os.path.isfile(it["destino"]):
                os.remove(it["destino"]); n += 1
        except OSError:
            pass
        db.quitar_de_papelera(it["id"])
    return {"ok": True, "borrados": n}


# ---------------------------------------------------------------- duplicados
SIMILITUD_MINIMA = 0.65   # cuánto se tienen que parecer dos modelos para ser "el mismo"

def buscar_duplicados():
    """Modelos que son el MISMO modelo: comparten casi todos sus archivos.

    Huella por archivo = tamaño + md5 de los primeros 128 KB (se guarda en caché,
    así la segunda búsqueda es casi instantánea). Dos modelos son duplicados si
    la similitud entre sus conjuntos de archivos supera SIMILITUD_MINIMA."""
    cache = db.huellas_todas()
    nuevas = []
    firmas = {}

    for m in MODELOS:
        a = m.get("archivos") or {}
        candidatos = (a.get("corte") or [])[:25]
        if not candidatos:
            continue
        conj = set()
        for fn in candidatos:
            p = os.path.join(m["ruta"], fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size < 200:
                continue
            c = cache.get(p)
            if c and c["tam"] == st.st_size and c["mtime"] == int(st.st_mtime):
                conj.add(c["hash"])
                continue
            try:
                with open(p, "rb") as f:
                    h = hashlib.md5(f.read(131072)).hexdigest()
            except OSError:
                continue
            clave = f"{st.st_size}-{h}"
            conj.add(clave)
            nuevas.append((p, st.st_size, int(st.st_mtime), clave))
        if conj:
            firmas[m["rel"]] = conj

    db.guardar_huellas(nuevas)

    # Agrupamos SOLO por coincidencia exacta (sin encadenar A-B-C):
    #   a) mismo conjunto completo de archivos de corte  -> es el mismo modelo
    #   b) misma foto (imagen idéntica)                  -> muy probablemente el mismo
    por_firma = {}
    for rel, conj in firmas.items():
        por_firma.setdefault("A:" + hashlib.md5("|".join(sorted(conj)).encode()).hexdigest(),
                             set()).add(rel)

    for m in MODELOS:
        if not m.get("preview"):
            continue
        p = os.path.join(m["ruta"], m["preview"])
        try:
            st = os.stat(p)
            if st.st_size < 2000:
                continue
        except OSError:
            continue
        c = cache.get(p)
        if c and c["tam"] == st.st_size and c["mtime"] == int(st.st_mtime):
            clave = c["hash"]
        else:
            try:
                with open(p, "rb") as f:
                    clave = f"{st.st_size}-{hashlib.md5(f.read(131072)).hexdigest()}"
            except OSError:
                continue
            nuevas.append((p, st.st_size, int(st.st_mtime), clave))
        por_firma.setdefault("F:" + clave, set()).add(m["rel"])

    db.guardar_huellas(nuevas)

    # unimos los grupos que comparten modelos (mismo modelo detectado por las dos vías)
    grupos_crudos = [g for g in por_firma.values() if len(g) > 1]
    fusionados, usados = [], set()
    for g in grupos_crudos:
        if any(r in usados for r in g):
            for f in fusionados:
                if f & g:
                    f |= g
                    break
        else:
            fusionados.append(set(g))
        usados |= g

    vistos, grupos = set(), []
    metas = db.meta_todos()
    for grupo in fusionados:
        if not grupo or next(iter(grupo)) in vistos:
            continue
        vistos |= grupo
        items = []
        for rr in grupo:
            mm = POR_REL.get(rr)
            if not mm:
                continue
            mt = metas.get(rr) or {}
            items.append({
                "rel": rr, "nombre": mt.get("nombre") or mm["nombre"],
                "ruta": mm["rel"], "mb": mm["mb"], "n_corte": mm["n_corte"],
                "img": 1 if mm["tiene_imagen"] else 0,
                "man": 1 if mm["tiene_manual"] else 0,
                "fav": 1 if mt.get("favorito") else 0,
            })
        if len(items) > 1:
            items.sort(key=lambda x: (-x["n_corte"], -x["mb"]))
            grupos.append(items)
    grupos.sort(key=lambda g: -len(g))
    return grupos


# ---------------------------------------------------------------- respaldo de datos
ARCHIVOS_CODIGO = ["app.py", "db.py", "indexar.py", "categorias.py", "ui.html"]

# ---------------------------------------------------------------- cotización
def costo_por_minuto():
    """Igual que el Excel 'Costo Minuto Laser': cada costo fijo se reparte en sus
    horas, se pasa a minutos, se suman todos y se le agrega el % de ganancia."""
    detalle, parcial = [], 0.0
    for c in db.costos_fijos():
        horas = float(c["horas"] or 0)
        monto = float(c["monto"] or 0)
        if horas <= 0:
            continue
        valor_hora = monto / horas
        valor_min = valor_hora / 60.0
        parcial += valor_min
        detalle.append({"id": c["id"], "nombre": c["nombre"], "grupo": c["grupo"],
                        "monto": monto, "horas": horas,
                        "valor_hora": round(valor_hora, 4), "valor_minuto": round(valor_min, 5)})
    aj = db.ajustes_todos()
    pct = float(aj.get("ganancia_minuto") or 0)
    ganancia = parcial * pct / 100.0
    return {"detalle": detalle, "parcial": round(parcial, 4),
            "ganancia_pct": pct, "ganancia": round(ganancia, 4),
            "final": round(parcial + ganancia, 4)}


def cotizar(d):
    """Igual que el Excel 'CALCULO_DE_COSTOS': material por cm2 + tiempo de corte
    + luz + mano de obra + depreciación, y al final la utilidad."""
    aj = db.ajustes_todos()
    num = lambda v, x=0.0: (float(v) if v not in (None, "") else x)

    minutos = num(d.get("minutos"), num(aj.get("minutos_defecto"), 30))
    ancho_c, largo_c = num(d.get("ancho")), num(d.get("largo"))
    piezas = max(1, int(num(d.get("piezas"), 1)))

    # material
    mat, costo_cm2, area_plancha = None, 0.0, 0.0
    if d.get("material_id"):
        mat = db.fila("SELECT * FROM materiales WHERE id=?", (d["material_id"],))
    if mat:
        area_plancha = num(mat["ancho"]) * num(mat["largo"])
        if area_plancha > 0:
            costo_cm2 = num(mat["precio"]) / area_plancha
    area_corte = ancho_c * largo_c
    costo_material = area_corte * costo_cm2

    # costo del minuto de máquina
    cmin = num(d.get("costo_minuto")) or costo_por_minuto()["final"]
    costo_corte = minutos * cmin

    costo_luz = num(d.get("luz"), num(aj.get("luz_pieza"), 0))
    costo_mo = num(d.get("manoobra"), num(aj.get("manoobra_pieza"), 0))
    dep_min = num(d.get("depreciacion_minuto"), num(aj.get("depreciacion_minuto"), 0))
    costo_dep = minutos * dep_min
    extra = num(d.get("extra"))

    subtotal = costo_material + costo_corte + costo_luz + costo_mo + costo_dep + extra
    pct_util = num(d.get("utilidad"), num(aj.get("utilidad"), 0))
    utilidad = subtotal * pct_util / 100.0
    total = subtotal + utilidad

    return {
        "material": (mat["nombre"] + (" · " + mat["proveedor"] if mat["proveedor"] else "")) if mat else "",
        "area_plancha": round(area_plancha, 1), "costo_cm2": round(costo_cm2, 5),
        "area_corte": round(area_corte, 1),
        "costo_material": round(costo_material), "minutos": minutos,
        "costo_minuto": round(cmin, 3), "costo_corte": round(costo_corte),
        "costo_luz": round(costo_luz), "costo_manoobra": round(costo_mo),
        "costo_depreciacion": round(costo_dep), "extra": round(extra),
        "subtotal": round(subtotal), "utilidad_pct": pct_util, "utilidad": round(utilidad),
        # el total por N piezas se calcula con el total ya redondeado,
        # así lo que ve el usuario siempre cuadra (precio x cantidad)
        "total": round(total), "piezas": piezas, "total_piezas": round(total) * piezas,
    }


def cambiar_carpeta(nueva=None):
    """Cambia la carpeta de modelos y vuelve a indexar.
    Si no se pasa ruta, abre el selector de carpetas de Windows."""
    if not nueva:
        try:
            r = subprocess.run([sys.executable, os.path.join(BASE, "elegir_carpeta.py")],
                               cwd=BASE, capture_output=True, text=True, timeout=300)
            nueva = (r.stdout or "").strip().splitlines()[-1].strip() if r.stdout.strip() else ""
        except Exception as e:
            return {"error": f"no se pudo abrir el selector: {e}"}
    if not nueva:
        return {"error": "no se eligió ninguna carpeta"}
    if not os.path.isdir(nueva):
        return {"error": "esa carpeta no existe"}

    cfg = cargar_config()
    cfg["biblioteca"] = nueva
    guardar_config(cfg)
    try:
        r = subprocess.run([sys.executable, os.path.join(BASE, "indexar.py"), nueva],
                           cwd=BASE, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return {"error": "no pude leer esa carpeta"}
    except Exception as e:
        return {"error": str(e)}
    recargar_indice()
    return {"ok": True, "carpeta": RAIZ, "total": len(MODELOS)}


def exportar_datos():
    """Todo lo que el usuario editó, en un solo archivo para llevarlo a otro PC."""
    return {
        "version": APP_VERSION,
        "fecha": int(time.time()),
        "modelos": db.filas("SELECT * FROM modelos"),
        "clientes": db.filas("SELECT * FROM clientes"),
        "pedidos": db.filas("SELECT * FROM pedidos"),
        "ventas": db.filas("SELECT * FROM ventas"),
        "sugerencias": db.sugerencias(),
    }


def importar_datos(datos, modo="fusionar"):
    """Carga un respaldo. modo=fusionar (respeta lo que ya hay) o reemplazar."""
    if not isinstance(datos, dict) or "modelos" not in datos:
        return {"error": "el archivo no es un respaldo válido"}
    c = db.cx()
    n = {"modelos": 0, "clientes": 0, "pedidos": 0, "ventas": 0}
    try:
        if modo == "reemplazar":
            for t in ("modelos", "clientes", "pedidos", "ventas"):
                c.execute(f"DELETE FROM {t}")

        for m in datos.get("modelos", []):
            existe = db.meta(m.get("rel", ""))
            if existe and modo == "fusionar":
                continue
            campos = {k: m.get(k) for k in ("nombre", "categoria", "subcategoria", "notas",
                                            "favorito", "costo", "precio", "stock", "cliente_id")}
            db.guardar_meta(m.get("rel", ""), campos)
            n["modelos"] += 1

        mapa_cli = {}
        for cl in datos.get("clientes", []):
            viejo = cl.get("id")
            nuevo = db.guardar_cliente(cl)
            mapa_cli[viejo] = nuevo
            n["clientes"] += 1

        for p in datos.get("pedidos", []):
            p = dict(p); p.pop("id", None)
            p["cliente_id"] = mapa_cli.get(p.get("cliente_id"), p.get("cliente_id"))
            db.guardar_pedido(p)
            n["pedidos"] += 1

        for v in datos.get("ventas", []):
            v = dict(v); v.pop("id", None)
            v["cliente_id"] = mapa_cli.get(v.get("cliente_id"), v.get("cliente_id"))
            db.guardar_venta(v)
            n["ventas"] += 1
        c.commit()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "importado": n}


# ---------------------------------------------------------------- actualizaciones
def _version_tupla(s):
    try:
        return tuple(int(x) for x in str(s).strip().split("."))
    except ValueError:
        return (0,)


def revisar_actualizacion():
    """Consulta si hay una versión nueva publicada."""
    import urllib.request
    try:
        req = urllib.request.Request(URL_ACTUALIZACIONES, headers={"User-Agent": "BibliotecaLaser"})
        with urllib.request.urlopen(req, timeout=8) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": "no pude conectarme para revisar (¿hay internet?)", "detalle": str(e)}
    nueva = info.get("version", "0")
    return {
        "ok": True,
        "actual": APP_VERSION,
        "disponible": nueva,
        "hay_nueva": _version_tupla(nueva) > _version_tupla(APP_VERSION),
        "novedades": info.get("novedades", ""),
        "zip": info.get("zip", ""),
    }


def aplicar_actualizacion(url_zip):
    """Descarga el ZIP y reemplaza SOLO los archivos de código.
    Nunca toca biblioteca.db, config.json ni la carpeta de modelos."""
    import urllib.request, zipfile, io
    if not url_zip.startswith("https://"):
        return {"error": "dirección de descarga no válida"}
    try:
        req = urllib.request.Request(url_zip, headers={"User-Agent": "BibliotecaLaser"})
        with urllib.request.urlopen(req, timeout=60) as r:
            crudo = r.read()
    except Exception as e:
        return {"error": f"no se pudo descargar: {e}"}

    respaldo = os.path.join(BASE, "_version_anterior")
    os.makedirs(respaldo, exist_ok=True)
    cambiados = []
    try:
        with zipfile.ZipFile(io.BytesIO(crudo)) as z:
            nombres = z.namelist()
            for archivo in ARCHIVOS_CODIGO + ["INICIAR Biblioteca.bat", "LEEME.txt"]:
                cand = [n for n in nombres if n.endswith("/" + archivo) or n == archivo]
                if not cand:
                    continue
                datos = z.read(cand[0])
                destino = os.path.join(BASE, archivo)
                if os.path.exists(destino):
                    shutil.copy2(destino, os.path.join(respaldo, archivo))
                with open(destino, "wb") as f:
                    f.write(datos)
                cambiados.append(archivo)
    except Exception as e:
        return {"error": f"el archivo descargado no sirve: {e}"}
    if not cambiados:
        return {"error": "el paquete no traía archivos de la app"}
    return {"ok": True, "archivos": cambiados,
            "aviso": "Cierra y vuelve a abrir la biblioteca para usar la versión nueva."}


def restaurar_version(rel, vid):
    v = db.fila("SELECT * FROM versiones WHERE id=?", (vid,))
    if not v or not os.path.exists(v["respaldo"]):
        return {"error": "esa versión ya no está"}
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    actual = os.path.join(m["ruta"], v["archivo"])
    # leemos la versión a restaurar ANTES de mover nada (evita pisarla)
    with open(v["respaldo"], "rb") as f:
        contenido = f.read()
    # el archivo actual pasa a ser una versión más
    if os.path.exists(actual):
        try:
            resp = ruta_respaldo(m["ruta"], v["archivo"])
            shutil.move(actual, resp)
            db.registrar_version(rel, v["tipo"], v["archivo"], resp)
        except OSError:
            pass
    with open(actual, "wb") as f:
        f.write(contenido)
    return {"ok": True, "archivo": v["archivo"]}


# ---------------------------------------------------------------- servidor
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self):
        try:
            return json.loads(self._cuerpo().decode("utf-8") or "{}")
        except Exception:
            return {}

    # ------------------------------------------------------------ GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        r = u.path
        q = urllib.parse.parse_qs(u.query)
        arg = lambda k, d="": (q.get(k) or [d])[0]

        if r in ("/", "/index.html"):
            with open(os.path.join(BASE, "ui.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if r == "/api/datos":
            metas = db.meta_todos()
            vistas = [modelo_vista(m, metas) for m in MODELOS]
            return self._send(200, {
                "modelos": vistas,
                "categorias": categorias_con_conteo(vistas),
                "total": len(vistas),
                "raiz": RAIZ,
                "lightburn": buscar_lightburn() or "",
                "clientes": db.clientes(),
            })

        if r == "/api/modelo":
            rel = arg("rel")
            m = POR_REL.get(rel)
            if not m:
                return self._send(404, {"error": "no existe"})
            d = dict(m)
            d["meta"] = db.meta(rel) or {}
            d["versiones"] = db.versiones(rel)
            return self._send(200, d)

        if r == "/thumb":
            res = miniatura(arg("rel"))
            if not res:
                return self._send(404, b"", "text/plain")
            body, ctype = res
            return self._send(200, body, ctype, {"Cache-Control": "max-age=3600"})

        if r == "/api/archivo":
            p = arg("p")
            if not ruta_segura(p) or not os.path.exists(p):
                return self._send(404, b"", "text/plain")
            ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
            with open(p, "rb") as f:
                return self._send(200, f.read(), ctype, {"Cache-Control": "max-age=3600"})

        if r == "/api/abrir":
            p, modo = arg("p"), arg("modo", "auto")
            if not ruta_segura(p) or not os.path.exists(p):
                return self._send(403, {"error": "ruta no permitida"})
            try:
                if modo == "lightburn":
                    exe = buscar_lightburn()
                    if exe:
                        subprocess.Popen([exe, p]); return self._send(200, {"ok": True, "con": "lightburn"})
                    os.startfile(p); return self._send(200, {"ok": True, "con": "sistema"})
                os.startfile(p)
                return self._send(200, {"ok": True})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        if r == "/api/carpeta":
            p = arg("p")
            if not ruta_segura(p) or not os.path.exists(p):
                return self._send(403, {"error": "ruta no permitida"})
            subprocess.Popen(["explorer", os.path.normpath(p)])
            return self._send(200, {"ok": True})

        if r == "/api/clientes":
            return self._send(200, {"clientes": db.clientes()})

        if r == "/api/pedidos":
            return self._send(200, {"pedidos": db.pedidos(
                int(arg("cliente")) if arg("cliente") else None,
                arg("pendientes") == "1")})

        if r == "/api/ventas":
            return self._send(200, {"ventas": db.ventas()})

        if r == "/api/metricas":
            return self._send(200, db.metricas())

        if r == "/api/papelera":
            return self._send(200, {"items": db.papelera()})

        if r == "/api/cotizacion":
            return self._send(200, {
                "materiales": db.materiales(),
                "costos_fijos": db.costos_fijos(),
                "ajustes": db.ajustes_todos(),
                "minuto": costo_por_minuto(),
            })

        if r == "/api/sugerencias":
            return self._send(200, {"items": db.sugerencias(),
                                    "whatsapp": CFG.get("whatsapp", WHATSAPP_SOPORTE)})

        if r == "/api/ocultos":
            lista = []
            for o in db.ocultos():
                m = POR_REL.get(o["rel"])
                lista.append({"rel": o["rel"],
                              "nombre": o.get("nombre") or (m["nombre"] if m else o["rel"]),
                              "ruta": o["rel"]})
            return self._send(200, {"items": lista})

        if r == "/api/duplicados":
            return self._send(200, {"grupos": buscar_duplicados()})

        if r == "/api/version":
            return self._send(200, {"version": APP_VERSION})

        if r == "/api/actualizacion/revisar":
            return self._send(200, revisar_actualizacion())

        if r == "/api/datos/exportar":
            cuerpo = json.dumps(exportar_datos(), ensure_ascii=False, indent=1)
            nombre = "biblioteca-respaldo-" + time.strftime("%Y%m%d") + ".json"
            return self._send(200, cuerpo, "application/json; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{nombre}"'})

        return self._send(404, {"error": "no encontrado"})

    # ------------------------------------------------------------ POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        r = u.path
        q = urllib.parse.parse_qs(u.query)
        arg = lambda k, d="": (q.get(k) or [d])[0]

        if r == "/api/meta":
            d = self._json()
            rel = d.pop("rel", "")
            if not rel or rel not in POR_REL:
                return self._send(400, {"error": "modelo no válido"})
            db.guardar_meta(rel, d)
            return self._send(200, {"ok": True, "meta": db.meta(rel)})

        if r == "/api/favorito":
            rel = self._json().get("rel", "")
            if not rel or rel not in POR_REL:
                return self._send(400, {"error": "modelo no válido"})
            return self._send(200, {"ok": True, "favorito": db.alternar_favorito(rel)})

        if r == "/api/cliente":
            d = self._json()
            if not str(d.get("nombre") or "").strip():
                return self._send(400, {"error": "el cliente necesita un nombre"})
            cid = db.guardar_cliente(d, d.get("id"))
            return self._send(200, {"ok": True, "id": cid, "clientes": db.clientes()})

        if r == "/api/cliente/borrar":
            db.borrar_cliente(self._json().get("id"))
            return self._send(200, {"ok": True, "clientes": db.clientes()})

        if r == "/api/pedido":
            d = self._json()
            pid = db.guardar_pedido(d, d.get("id"))
            return self._send(200, {"ok": True, "id": pid, "pedidos": db.pedidos()})

        if r == "/api/pedido/borrar":
            db.borrar_pedido(self._json().get("id"))
            return self._send(200, {"ok": True, "pedidos": db.pedidos()})

        if r == "/api/venta":
            d = self._json()
            vid = db.guardar_venta(d, d.get("id"))
            return self._send(200, {"ok": True, "id": vid, "ventas": db.ventas()})

        if r == "/api/venta/borrar":
            db.borrar_venta(self._json().get("id"))
            return self._send(200, {"ok": True, "ventas": db.ventas()})

        if r == "/api/subir":
            rel, tipo, nombre = arg("rel"), arg("tipo", "modelo"), arg("nombre")
            datos = self._cuerpo()
            if not datos:
                return self._send(400, {"error": "archivo vacío"})
            res = guardar_archivo(rel, tipo, nombre, datos)
            if "error" in res:
                return self._send(400, res)
            recargar_parcial(rel)
            return self._send(200, res)

        if r == "/api/restaurar":
            d = self._json()
            res = restaurar_version(d.get("rel", ""), d.get("id"))
            if "error" in res:
                return self._send(400, res)
            recargar_parcial(d.get("rel", ""))
            return self._send(200, res)

        if r == "/api/cotizar":
            return self._send(200, cotizar(self._json()))

        if r == "/api/material":
            d = self._json()
            if not str(d.get("nombre") or "").strip():
                return self._send(400, {"error": "ponle un nombre al material"})
            db.guardar_material(d, d.get("id"))
            return self._send(200, {"ok": True, "materiales": db.materiales()})

        if r == "/api/material/borrar":
            db.borrar_material(self._json().get("id"))
            return self._send(200, {"ok": True, "materiales": db.materiales()})

        if r == "/api/costo-fijo":
            d = self._json()
            if not str(d.get("nombre") or "").strip():
                return self._send(400, {"error": "ponle un nombre al costo"})
            db.guardar_costo_fijo(d, d.get("id"))
            return self._send(200, {"ok": True, "costos_fijos": db.costos_fijos(),
                                    "minuto": costo_por_minuto()})

        if r == "/api/costo-fijo/borrar":
            db.borrar_costo_fijo(self._json().get("id"))
            return self._send(200, {"ok": True, "costos_fijos": db.costos_fijos(),
                                    "minuto": costo_por_minuto()})

        if r == "/api/ajuste":
            d = self._json()
            for k, v in (d.get("ajustes") or {}).items():
                db.guardar_ajuste(k, v)
            return self._send(200, {"ok": True, "ajustes": db.ajustes_todos(),
                                    "minuto": costo_por_minuto()})

        if r == "/api/sugerencia":
            t = str(self._json().get("texto") or "").strip()
            if not t:
                return self._send(400, {"error": "escribe algo primero"})
            db.agregar_sugerencia(t[:4000])
            return self._send(200, {"ok": True, "items": db.sugerencias()})

        if r == "/api/sugerencia/borrar":
            db.borrar_sugerencia(self._json().get("id"))
            return self._send(200, {"ok": True, "items": db.sugerencias()})

        if r == "/api/sugerencia/enviadas":
            db.marcar_enviadas()
            return self._send(200, {"ok": True, "items": db.sugerencias()})

        if r == "/api/config/whatsapp":
            CFG["whatsapp"] = str(self._json().get("numero") or "").strip()
            guardar_config(CFG)
            return self._send(200, {"ok": True, "whatsapp": CFG["whatsapp"]})

        if r == "/api/ocultar":
            rel = self._json().get("rel", "")
            if not rel or rel not in POR_REL:
                return self._send(400, {"error": "modelo no válido"})
            return self._send(200, {"ok": True, "oculto": db.alternar_oculto(rel)})

        if r == "/api/carpeta/cambiar":
            res = cambiar_carpeta(self._json().get("carpeta"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/borrar-archivo":
            d = self._json()
            res = borrar_archivo(d.get("rel", ""), d.get("nombre", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/borrar-modelo":
            res = borrar_modelo(self._json().get("rel", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/papelera/restaurar":
            res = restaurar_papelera(self._json().get("id"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/papelera/vaciar":
            return self._send(200, vaciar_papelera())

        if r == "/api/actualizacion/aplicar":
            res = aplicar_actualizacion(self._json().get("zip", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/datos/importar":
            d = self._json()
            res = importar_datos(d.get("datos"), d.get("modo", "fusionar"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/reindexar":
            try:
                subprocess.run([sys.executable, os.path.join(BASE, "indexar.py")],
                               cwd=BASE, check=True, capture_output=True)
                recargar_indice()
                return self._send(200, {"ok": True, "total": len(MODELOS)})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        return self._send(404, {"error": "no encontrado"})


def recargar_parcial(rel):
    """Re-lee los archivos de una carpeta tras subir/restaurar (sin reindexar todo)."""
    m = POR_REL.get(rel)
    if not m or not os.path.isdir(m["ruta"]):
        return
    a = {"corte": [], "imagen": [], "manual": [], "3d": [], "video": [], "otro": []}
    for fn in os.listdir(m["ruta"]):
        p = os.path.join(m["ruta"], fn)
        if os.path.isdir(p) or fn.lower() in ("thumbs.db", "desktop.ini"):
            continue
        e = os.path.splitext(fn)[1].lower()
        if e in EXT_CORTE: a["corte"].append(fn)
        elif e in EXT_IMAGEN: a["imagen"].append(fn)
        elif e in EXT_MANUAL: a["manual"].append(fn)
        elif e in {".stl", ".step", ".stp", ".sldprt", ".skp", ".obj"}: a["3d"].append(fn)
        elif e in {".mp4", ".avi", ".mov", ".mkv"}: a["video"].append(fn)
        elif e in {".zip", ".rar", ".7z"}: a["otro"].append(fn)
    m["archivos"] = a
    m["tiene_imagen"] = bool(a["imagen"]); m["tiene_manual"] = bool(a["manual"])
    m["tiene_3d"] = bool(a["3d"]); m["tiene_video"] = bool(a["video"])
    m["tiene_lightburn"] = any(f.lower().endswith((".lbrn", ".lbrn2")) for f in a["corte"])
    m["n_corte"] = len(a["corte"])
    if a["imagen"] and (not m.get("preview") or m["preview"] not in a["imagen"]):
        m["preview"] = a["imagen"][0]


def main():
    db.cx()
    db.sembrar_costos()
    print("=" * 54)
    print("  BIBLIOTECA LASER")
    print("=" * 54)
    print(f"  Modelos    : {len(MODELOS)}")
    print(f"  Biblioteca : {RAIZ}")
    lb = buscar_lightburn()
    print(f"  LightBurn  : {lb if lb else 'no detectado (usara el programa por defecto)'}")
    print(f"  Direccion  : http://127.0.0.1:{PUERTO}")
    print("=" * 54)
    print("  Deja esta ventana abierta mientras uses la biblioteca.")
    print()
    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PUERTO}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando...")


if __name__ == "__main__":
    main()
