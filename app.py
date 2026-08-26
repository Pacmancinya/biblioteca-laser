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
import base64, io          # los usa el conversor (miniaturas de LightBurn)
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import db
import formatos

CONGELADO = getattr(sys, "frozen", False)   # True cuando corre como .exe

APP_VERSION = "2.1"
APP_NOMBRE = "Mas comodo"   # nombre corto de esta versión, para reconocerla
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
VACIO = {"raiz": "", "modelos": [], "categorias": [], "total_modelos": 0}


def cargar_indice():
    """Lee biblioteca.json. Si todavía no existe (instalación recién puesta)
    devuelve una biblioteca vacía en vez de cortar el programa: la ventana
    tiene que abrir igual para poder pedir la carpeta de modelos."""
    if not os.path.exists(INDICE):
        return dict(VACIO)
    try:
        with open(INDICE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(VACIO)

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
    """Se mantiene por compatibilidad; ahora vive dentro de buscar_programa()."""
    return buscar_programa("lightburn") or None


# ---------------------------------------------------------------- programas
# Qué programa abre cada tipo de archivo. El usuario puede cambiarlo en Ajustes.
PROGRAMAS_DEF = {
    "lightburn": {"nombre": "LightBurn", "exts": [".lbrn", ".lbrn2"],
                  "exes": ["LightBurn.exe"],
                  "propias": [".lbrn2", ".lbrn"],
                  "buscar": ["LightBurn/LightBurn.exe"]},
    "corel":     {"nombre": "CorelDRAW", "exts": [".cdr", ".cmx", ".svg", ".ai", ".eps"],
                  "exes": ["CorelDRW.exe", "CorelDraw.exe"],
                  # OJO: solo .cdr y .cmx sirven para BUSCARLO. Con .svg se
                  # encontraba el navegador, porque muchos PCs lo abren ahi.
                  "propias": [".cdr", ".cmx"],
                  "buscar": ["Corel/CorelDRAW Graphics Suite */Programs64/CorelDRW.exe",
                             "Corel/CorelDRAW Graphics Suite */Programs/CorelDRW.exe",
                             "Corel/CorelDRAW*/Programs64/CorelDRW.exe",
                             "Corel/CorelDRAW*/Programs/CorelDRW.exe"]},
    "inkscape":  {"nombre": "Inkscape", "exts": [],
                  "exes": ["inkscape.exe"],
                  "propias": [],
                  "buscar": ["Inkscape/bin/inkscape.exe", "Inkscape/inkscape.exe"]},
}


def _buscar_en_registro(exes):
    """Busca un programa donde Windows anota los instalados.

    Es mucho más confiable que adivinar carpetas: CorelDRAW cambia de ruta
    en cada versión ("Graphics Suite 2021", "X8", "2024"...) y además puede
    estar en otro disco.
    """
    try:
        import winreg
    except ImportError:
        return ""
    ramas = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for raiz, ruta in ramas:
        for exe in exes:
            try:
                with winreg.OpenKey(raiz, ruta + "\\" + exe) as k:
                    valor = winreg.QueryValueEx(k, "")[0]
                    valor = (valor or "").strip('"')
                    if valor and os.path.exists(valor):
                        return valor
            except OSError:
                continue
    return ""


def _buscar_por_extension(ext):
    """Con qué programa abre Windows ese tipo de archivo (ej. .cdr)."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as k:
            tipo = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            tipo + r"\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return ""
    # el comando viene como:  "C:\...\CorelDRW.exe" "%1"
    m = re.match(r'\s*"([^"]+)"', cmd or "")
    ruta = m.group(1) if m else (cmd or "").split()[0].strip('"')
    return ruta if ruta and os.path.exists(ruta) else ""


def buscar_programa(clave):
    """Busca el .exe de un programa: primero lo que eligió el usuario, luego lo típico."""
    guardados = CFG.get("programas") or {}
    # config antigua: la ruta de LightBurn vivía suelta en config.json
    if clave == "lightburn" and not guardados.get(clave) and CFG.get("lightburn"):
        guardados["lightburn"] = CFG["lightburn"]
    p = guardados.get(clave)
    if p and os.path.exists(p):
        return p
    # 1) donde Windows anota los programas instalados (lo mas confiable)
    d = PROGRAMAS_DEF.get(clave, {})
    esperados = [e.lower() for e in d.get("exes", [])]
    hallado = _buscar_en_registro(d.get("exes", []))
    if not hallado:
        for ext in d.get("propias", []):
            candidato = _buscar_por_extension(ext)
            # que de verdad sea el programa que buscamos y no el que el
            # usuario tenga asociado a ese tipo de archivo
            if candidato and os.path.basename(candidato).lower() in esperados:
                hallado = candidato
                break
    if hallado:
        guardados[clave] = hallado
        CFG["programas"] = guardados
        guardar_config(CFG)
        return hallado

    # 2) si no, se buscan las carpetas de siempre
    import glob
    bases = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    for patron in PROGRAMAS_DEF.get(clave, {}).get("buscar", []):
        for b in bases:
            if not b:
                continue
            for hallado in sorted(glob.glob(os.path.join(b, patron.replace("/", os.sep))),
                                  reverse=True):   # la versión más nueva primero
                if os.path.exists(hallado):
                    guardados[clave] = hallado
                    CFG["programas"] = guardados
                    guardar_config(CFG)
                    return hallado
    return ""


def programas_estado():
    out = []
    for clave, d in PROGRAMAS_DEF.items():
        ruta = buscar_programa(clave)
        out.append({"clave": clave, "nombre": d["nombre"], "exts": d["exts"],
                    "ruta": ruta, "instalado": bool(ruta)})
    return out


def programa_para(archivo):
    """Con qué programa se abre este archivo, según su extensión."""
    ext = os.path.splitext(archivo)[1].lower()
    asign = CFG.get("asignaciones") or {}
    if ext in asign:
        clave = asign[ext]
        # "sistema" = que lo abra Windows con lo que tenga por defecto
        if not clave or clave == "sistema" or clave not in PROGRAMAS_DEF:
            return "", ""
        return clave, buscar_programa(clave)
    for clave, d in PROGRAMAS_DEF.items():
        if ext in d["exts"]:
            return clave, buscar_programa(clave)
    return "", ""


def raices():
    """Todas las carpetas de modelos: la principal y las agregadas."""
    r = DATOS.get("raices")
    if r:
        return [x for x in r if x]
    return [RAIZ] if RAIZ else []


def ruta_segura(p):
    """Solo se puede tocar lo que este dentro de alguna carpeta de modelos
    (o de la carpeta del programa, para los archivos convertidos)."""
    try:
        p = os.path.abspath(p)
    except Exception:
        return False
    permitidas = [x for x in raices() if x] + [BASE]
    for base in permitidas:
        try:
            b = os.path.abspath(base)
            if os.path.commonpath([b, p]) == b:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- vista de modelos
_REGLAS = None          # cache de las reglas "esta carpeta es de esta categoria"


def recargar_reglas():
    """Las reglas se guardan por ruta relativa, de la mas larga a la mas corta,
    para que mande siempre la carpeta mas precisa."""
    global _REGLAS
    _REGLAS = [(r["rel"].replace("/", os.sep).strip(os.sep).lower(),
                r["categoria"], r["subcategoria"])
               for r in db.reglas_carpeta()]
    _REGLAS.sort(key=lambda x: -len(x[0]))
    return _REGLAS


def regla_de(rel):
    """Si el modelo esta dentro de una carpeta marcada, devuelve su categoria."""
    if _REGLAS is None:
        recargar_reglas()
    if not _REGLAS:
        return None
    r = rel.replace("/", os.sep).strip(os.sep).lower()
    for carpeta, cat, sub in _REGLAS:
        if r == carpeta or r.startswith(carpeta + os.sep):
            return cat, sub
    return None


_EXT_DIBUJABLES = {".svg", ".dxf", ".eps", ".ai", ".lbrn", ".lbrn2"}


def modelo_vista(m, metas=None):
    """Mezcla el modelo del disco con lo que el usuario editó.

    Quien manda sobre la categoría, de mayor a menor:
      1. lo que el usuario corrigió en ESE modelo
      2. la regla "esta carpeta es de esta categoría" (la más precisa)
      3. lo que adivinó el clasificador al leer el disco
    """
    metas = metas if metas is not None else db.meta_todos()
    mt = metas.get(m["rel"]) or {}
    partes = m["ruta_partes"]

    cat = mt.get("categoria")
    sub = mt.get("subcategoria")
    if not cat:
        r = regla_de(m["rel"])
        if r:
            cat = r[0]
            if sub is None and r[1]:
                sub = r[1]

    return {
        "rel": m["rel"], "id": m["id"],
        "n": mt.get("nombre") or m["nombre"],
        "n_orig": m["nombre"],
        "c": cat or m["categoria"],
        "s": sub if sub is not None else m["subcategoria"],
        "ruta_partes": partes,
        "fmt": m["formatos"], "gr": m["grosores"],
        "img": 1 if m["tiene_imagen"] else 0, "man": 1 if m["tiene_manual"] else 0,
        # hay algo que mostrar: una foto, la miniatura del archivo de LightBurn,
        # o el dibujo del propio modelo
        "prev": 1 if (m["tiene_imagen"] or m["tiene_lightburn"]
                      or any(os.path.splitext(a)[1].lower() in _EXT_DIBUJABLES
                             for a in m["archivos"]["corte"])) else 0,
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
    creadas, ocultas = db.subcats_propias()
    conteo, conteo_sub = {}, {}
    for v in vistas:
        conteo[v["c"]] = conteo.get(v["c"], 0) + 1
        conteo_sub[(v["c"], v["s"])] = conteo_sub.get((v["c"], v["s"]), 0) + 1

    def visible(cat, sub, n):
        if sub in (ocultas.get(cat) or []):
            return False
        # una subcategoría vacía se muestra solo si el usuario la creó
        return n > 0 or sub in (creadas.get(cat) or [])

    salida = []
    hechas = set()
    for grupo in cats.estructura():
        cat = grupo["nombre"]
        hechas.add(cat)
        nombres = list(grupo["subs"])
        for s in (creadas.get(cat) or []):
            if s not in nombres:
                nombres.append(s)
        for (c, s), _ in conteo_sub.items():
            if c == cat and s and s not in nombres:
                nombres.append(s)
        subs = [{"nombre": s, "n": conteo_sub.get((cat, s), 0), "propia": s not in grupo["subs"]}
                for s in nombres]
        salida.append({"nombre": cat, "n": conteo.get(cat, 0),
                       "subs": [s for s in subs if visible(cat, s["nombre"], s["n"])]})
    # categorías inventadas por el usuario
    for c in list(conteo) + list(creadas):
        if c in hechas:
            continue
        hechas.add(c)
        nombres = list(creadas.get(c) or [])
        for (cc, s), _ in conteo_sub.items():
            if cc == c and s and s not in nombres:
                nombres.append(s)
        subs = [{"nombre": s, "n": conteo_sub.get((c, s), 0), "propia": True} for s in nombres]
        salida.append({"nombre": c, "n": conteo.get(c, 0), "propia": True,
                       "subs": [s for s in subs if visible(c, s["nombre"], s["n"])]})
    # categorías que el usuario invento y todavia estan vacias
    orden_usuario, ocultas_cat, propias_cat = db.cats_propias()
    for c in propias_cat:
        if c not in hechas:
            salida.append({"nombre": c, "n": conteo.get(c, 0), "propia": True, "subs": []})
            hechas.add(c)

    # una categoría vacía solo se muestra si el usuario la creó
    salida = [g for g in salida
              if (g["n"] > 0 or g.get("subs") or g["nombre"] in propias_cat)
              and g["nombre"] not in ocultas_cat]

    # y en el orden en que el usuario las dejó
    base = {g["nombre"]: i for i, g in enumerate(cats.estructura())}
    def clave(g):
        n = g["nombre"]
        if n in orden_usuario:
            return (0, orden_usuario[n])
        if n in base:
            return (1, base[n])
        return (2, n.lower())
    salida.sort(key=clave)
    for g in salida:
        g["propia"] = g["nombre"] in propias_cat
    return salida


def crear_categoria(nombre):
    nombre = (nombre or "").strip()
    if not nombre:
        return {"error": "Escribe el nombre de la categoría."}
    if len(nombre) > 40:
        return {"error": "El nombre es muy largo."}
    actuales = [g["nombre"] for g in categorias_con_conteo(vistas_todas())]
    if nombre in actuales:
        return {"error": "Ya existe una categoría con ese nombre."}
    db.guardar_cat(nombre, orden=len(actuales), propia=True, oculta=False)
    return {"ok": True, "nombre": nombre}


def borrar_categoria(nombre, destino=""):
    """Saca una categoría grande. Sus modelos pasan a `destino`, o vuelven a
    donde los pondría el programa solo. Nunca se borra nada del disco."""
    nombre = (nombre or "").strip()
    destino = (destino or "").strip()
    if not nombre:
        return {"error": "falta la categoría"}
    vistas = vistas_todas()
    afectados = [v for v in vistas if v["c"] == nombre]
    if len(afectados) > 20:
        respaldar_base()
    for v in afectados:
        if destino:
            db.guardar_meta(v["rel"], {"categoria": destino, "subcategoria": ""})
        else:
            # volver a lo automatico: se borra la correccion del usuario
            db.guardar_meta(v["rel"], {"categoria": "", "subcategoria": ""})
    # y las reglas de carpeta que apuntaban ahi
    for r in db.reglas_carpeta():
        if r["categoria"] == nombre:
            db.borrar_regla(r["rel"])
    recargar_reglas()
    import categorias as cats
    if nombre in [g["nombre"] for g in cats.estructura()]:
        db.guardar_cat(nombre, oculta=True, propia=False)   # de fabrica: se tapa
    else:
        db.quitar_cat(nombre)
    return {"ok": True, "movidos": len(afectados), "destino": destino}


def renombrar_categoria(viejo, nuevo):
    viejo, nuevo = (viejo or "").strip(), (nuevo or "").strip()
    if not viejo or not nuevo:
        return {"error": "Faltan los nombres."}
    if viejo == nuevo:
        return {"ok": True, "movidos": 0}
    vistas = vistas_todas()
    afectados = [v for v in vistas if v["c"] == viejo]
    if len(afectados) > 20:
        respaldar_base()
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": nuevo})
    for r in db.reglas_carpeta():
        if r["categoria"] == viejo:
            db.guardar_regla(r["rel"], nuevo, r["subcategoria"])
    recargar_reglas()
    orden, _oc, _pr = db.cats_propias()
    db.guardar_cat(nuevo, orden=orden.get(viejo, 999), propia=True)
    import categorias as cats
    if viejo in [g["nombre"] for g in cats.estructura()]:
        db.guardar_cat(viejo, oculta=True)
    else:
        db.quitar_cat(viejo)
    return {"ok": True, "movidos": len(afectados)}


def vistas_todas():
    metas = db.meta_todos()
    return [modelo_vista(m, metas) for m in MODELOS]


def marcar_carpeta(ruta, categoria, subcategoria=""):
    """Deja una carpeta entera dentro de una categoría."""
    categoria = (categoria or "").strip()
    if not categoria:
        return {"error": "Elige la categoría."}
    ruta = (ruta or "").strip().strip('"').strip()
    if not ruta:
        return {"error": "Elige la carpeta."}
    if not os.path.isdir(ruta):
        return {"error": "No encuentro esa carpeta: %s" % ruta}
    if not RAIZ:
        return {"error": "Todavía no hay biblioteca configurada."}
    try:
        rel = os.path.relpath(os.path.abspath(ruta), os.path.abspath(RAIZ))
    except ValueError:
        return {"error": "Esa carpeta está en otro disco que la biblioteca."}
    if rel.startswith(".."):
        return {"error": "Esa carpeta tiene que estar dentro de tu biblioteca: %s" % RAIZ}
    if rel == ".":
        return {"error": "Esa es la carpeta principal: elige una de adentro."}

    db.guardar_regla(rel, categoria, subcategoria)
    recargar_reglas()
    cuantos = sum(1 for m in MODELOS
                  if m["rel"].lower() == rel.lower()
                  or m["rel"].lower().startswith(rel.lower() + os.sep))
    return {"ok": True, "rel": rel, "categoria": categoria, "modelos": cuantos}


# ------------------------------- lo que se edita en CorelDRAW pasa a ser lo bueno
# Cuando el papa abre un modelo en CorelDRAW, guardamos como estaba el archivo.
# Al volver a la ficha, si lo ve cambiado, ofrece dejar esa version como la
# principal del modelo.
_VIGILADOS = {}          # rel -> {"archivo": ruta, "antes": (tam, fecha), "cuando": t}


def vigilar(rel, ruta):
    """Anota como esta un archivo justo antes de abrirlo en un programa."""
    try:
        st = os.stat(ruta)
        _VIGILADOS[rel] = {"archivo": ruta, "antes": (st.st_size, int(st.st_mtime)),
                           "cuando": time.time(),
                           "carpeta": os.path.dirname(ruta),
                           "habia": set(os.listdir(os.path.dirname(ruta)))}
    except OSError:
        pass


def revisar_cambios(rel):
    """¿Cambio algo desde que lo abrimos? Devuelve que encontro."""
    v = _VIGILADOS.get(rel)
    if not v:
        return None
    salida = {"editado": None, "nuevos": []}
    try:
        st = os.stat(v["archivo"])
        if (st.st_size, int(st.st_mtime)) != v["antes"]:
            salida["editado"] = os.path.basename(v["archivo"])
    except OSError:
        pass
    # CorelDRAW a veces guarda un archivo nuevo (.cdr) en vez de pisar el que abrio
    try:
        ahora = set(os.listdir(v["carpeta"]))
        for n in sorted(ahora - v["habia"]):
            ext = os.path.splitext(n)[1].lower()
            if ext in (".cdr", ".svg", ".ai", ".eps", ".dxf", ".pdf", ".lbrn", ".lbrn2"):
                salida["nuevos"].append(n)
    except OSError:
        pass
    if not salida["editado"] and not salida["nuevos"]:
        return None
    return salida


def hacer_principal(rel, nombre):
    """Deja ese archivo como el principal del modelo: es el que se abre y del
    que sale la vista previa. Guarda la version anterior por si se arrepiente."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "no existe ese modelo"}
    origen = os.path.join(m["ruta"], nombre)
    if not ruta_segura(origen) or not os.path.exists(origen):
        return {"error": "no encuentro ese archivo"}

    corte = m["archivos"]["corte"]
    ext = os.path.splitext(nombre)[1].lower()
    if ext not in [e.lower() for e in
                   (".svg", ".dxf", ".eps", ".ai", ".cdr", ".cmx", ".lbrn", ".lbrn2", ".plt", ".dwg")]:
        return {"error": "ese archivo no es un dibujo para cortar"}

    # que quede primero en la lista: asi lo toma todo lo demas
    if nombre in corte:
        corte.remove(nombre)
    corte.insert(0, nombre)
    m["archivos"]["corte"] = corte
    m["n_corte"] = len(corte)
    m["formatos"] = sorted({os.path.splitext(f)[1].lower().lstrip(".") for f in corte})
    m["tiene_lightburn"] = any(f.lower().endswith((".lbrn", ".lbrn2")) for f in corte)
    guardar_indice()

    db.guardar_meta(rel, {"principal": nombre})
    db.registrar_version(rel, "principal", nombre, "")

    # la vista previa vieja ya no vale
    try:
        h = hashlib.md5(rel.encode("utf-8")).hexdigest()
        thumb = os.path.join(CACHE_THUMBS, h + ".jpg")
        if os.path.exists(thumb):
            os.remove(thumb)
    except OSError:
        pass
    _VIGILADOS.pop(rel, None)
    return {"ok": True, "principal": nombre}


def guardar_indice():
    """Graba biblioteca.json despues de un cambio hecho desde la app."""
    try:
        with open(INDICE, "w", encoding="utf-8") as f:
            json.dump(DATOS, f, ensure_ascii=False)
    except Exception:
        pass


def _la_pone_el_programa(cat, sub):
    """¿Esta subcategoría sale sola al leer la carpeta? (porque la arma el
    clasificador o porque existe como carpeta en el disco). Si es así hay que
    taparla, si no volvería a aparecer en el próximo reindexado."""
    return any(m["categoria"] == cat and m["subcategoria"] == sub for m in MODELOS)


def modelos_en(cat, sub):
    """Los modelos que hoy están en esa categoría/subcategoría."""
    metas = db.meta_todos()
    return [v for v in (modelo_vista(m, metas) for m in MODELOS)
            if v["c"] == cat and (v["s"] or "") == (sub or "")]


def renombrar_subcat(cat, vieja, nueva):
    """Le cambia el nombre a una subcategoría y arrastra sus modelos."""
    cat, vieja, nueva = (cat or "").strip(), (vieja or "").strip(), (nueva or "").strip()
    if not cat or not vieja:
        return {"error": "falta la subcategoría"}
    if not nueva:
        return {"error": "Escribe el nombre nuevo."}
    if nueva == vieja:
        return {"ok": True, "movidos": 0}
    afectados = modelos_en(cat, vieja)
    if len(afectados) > 20:
        respaldar_base()      # por si se arrepiente después
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": cat, "subcategoria": nueva})
    db.quitar_subcat(cat, vieja)
    db.crear_subcat(cat, nueva)
    # si el nombre viejo sale solo al leer la carpeta, hay que taparlo
    if _la_pone_el_programa(cat, vieja):
        db.ocultar_subcat(cat, vieja, 1)
    return {"ok": True, "movidos": len(afectados)}


def borrar_subcat(cat, sub, destino=""):
    """Saca una subcategoría. Sus modelos pasan a `destino` (o quedan sin subcategoría);
    nunca se borra nada del disco."""
    cat, sub = (cat or "").strip(), (sub or "").strip()
    if not cat or not sub:
        return {"error": "falta la subcategoría"}
    destino = (destino or "").strip()
    afectados = modelos_en(cat, sub)
    if len(afectados) > 20:
        respaldar_base()      # por si se arrepiente después
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": cat, "subcategoria": destino})
    db.quitar_subcat(cat, sub)
    # Solo hay que taparla si la inventa el programa; si la creó el usuario,
    # con quitarla basta y no dejamos basura guardada.
    if _la_pone_el_programa(cat, sub):
        db.ocultar_subcat(cat, sub, 1)
    return {"ok": True, "movidos": len(afectados), "destino": destino}


def vista_previa_lightburn(m):
    """Los archivos de LightBurn traen una miniatura adentro. Si el modelo no
    tiene ninguna foto, la usamos para que igual se vea algo."""
    for a in (m.get("archivos", {}).get("corte") or []):
        if a.lower().endswith((".lbrn", ".lbrn2")):
            p = os.path.join(m["ruta"], a)
            if os.path.exists(p):
                return p
    return None


def miniatura(rel):
    m = POR_REL.get(rel)
    if not m:
        return None
    origen = os.path.join(m["ruta"], m["preview"]) if m.get("preview") else ""
    lbrn = None
    dibujo = None
    if not origen or not os.path.exists(origen):
        lbrn = vista_previa_lightburn(m)      # no hay foto: probamos con LightBurn
        if lbrn:
            origen = lbrn
        else:
            # tampoco hay: dibujamos el modelo a partir del archivo de corte
            for a in (m["archivos"]["corte"] or []):
                p = os.path.join(m["ruta"], a)
                if (os.path.splitext(a)[1].lower() in formatos.LEIBLES
                        and os.path.exists(p) and os.path.getsize(p) < 12_000_000):
                    dibujo = p
                    break
            if not dibujo:
                return None
            origen = dibujo
    if not HAY_PIL:
        if lbrn or dibujo:
            return None
        with open(origen, "rb") as f:
            return f.read(), mimetypes.guess_type(origen)[0] or "image/jpeg"
    h = hashlib.md5(rel.encode("utf-8")).hexdigest()
    destino = os.path.join(CACHE_THUMBS, h + ".jpg")
    try:
        if not os.path.exists(destino) or os.path.getmtime(destino) < os.path.getmtime(origen):
            if dibujo:
                if not formatos.dibujar_previa(origen, destino):
                    return None
                im = Image.open(destino).convert("RGB")
            elif lbrn:
                res = miniatura_lightburn(origen, destino + ".png")
                if not res.get("ok"):
                    return None
                im = Image.open(destino + ".png").convert("RGB")
                os.remove(destino + ".png")
            else:
                im = Image.open(origen).convert("RGB")
            im.thumbnail((520, 520), Image.LANCZOS)
            im.save(destino, "JPEG", quality=82)
    except Exception:
        return None
    with open(destino, "rb") as f:
        return f.read(), "image/jpeg"



# =========================================================================
#  CONVERSOR DE ARCHIVOS
#  Vive aquí adentro y no en un archivo aparte a propósito: al actualizar,
#  las versiones viejas de la app solo reemplazan los archivos que ya
#  conocen. Un archivo NUEVO no les llega (paso con convertir.py en la 1.4
#  y el papá se quedo sin conversor). Metido en app.py, siempre llega.
# =========================================================================
IMAGENES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VECTORES = {".svg", ".pdf", ".dxf", ".eps", ".ps", ".emf", ".wmf", ".ai"}
LIGHTBURN = {".lbrn", ".lbrn2"}
COREL = {".cdr", ".cmx"}

SALIDA_IMAGEN = ["png", "jpg", "webp", "bmp", "pdf"]
SALIDA_VECTOR = ["svg", "pdf", "dxf", "png", "eps"]

_RX_THUMB = re.compile(rb'<Thumbnail\s+Source="([^"]+)"')


def formatos_destino(archivo):
    """A qué formatos se puede llevar este archivo."""
    ext = os.path.splitext(archivo)[1].lower()
    if ext in LIGHTBURN:
        return ["png"]           # solo la miniatura que trae adentro
    if ext in IMAGENES:
        return [f for f in SALIDA_IMAGEN if f != ext.lstrip(".")]
    if ext in VECTORES:
        return [f for f in SALIDA_VECTOR if f != ext.lstrip(".")]
    return []


def por_que_no(archivo):
    """Si no se puede convertir, explicar por qué en cristiano."""
    ext = os.path.splitext(archivo)[1].lower()
    if ext in COREL:
        return ("Los archivos %s son formato cerrado de CorelDRAW: solo CorelDRAW "
                "puede abrirlos. Ábrelo ahí y usa Archivo → Exportar." % ext)
    if not formatos_destino(archivo):
        return "Todavía no sé convertir archivos %s." % (ext or "sin extensión")
    return ""


# ------------------------------------------------------------------ LightBurn
def miniatura_lightburn(origen, destino):
    """Saca la miniatura PNG que LightBurn guarda dentro del archivo."""
    try:
        with open(origen, "rb") as f:
            # la miniatura va al principio; no hace falta leer archivos de 20 MB enteros
            cabeza = f.read(8_000_000)
    except OSError as e:
        return {"error": "No pude leer el archivo: %s" % e}

    m = _RX_THUMB.search(cabeza)
    if not m:
        return {"error": "Este archivo de LightBurn no trae miniatura adentro."}
    try:
        datos = base64.b64decode(m.group(1))
        from PIL import Image
        img = Image.open(io.BytesIO(datos))
        img.load()
        img.save(destino)
    except Exception as e:
        return {"error": "La miniatura venía dañada: %s" % e}
    return {"ok": True, "archivo": destino, "con": "la miniatura de LightBurn"}


# --------------------------------------------------------------------- fotos
def convertir_imagen(origen, destino):
    try:
        from PIL import Image
        img = Image.open(origen)
        img.load()
        # jpg y pdf no soportan transparencia: la aplanamos sobre blanco
        if destino.lower().endswith((".jpg", ".jpeg", ".pdf")) and img.mode in ("RGBA", "LA", "P"):
            fondo = Image.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            fondo.paste(img, mask=img.split()[-1])
            img = fondo
        img.save(destino)
    except Exception as e:
        return {"error": "No pude convertir la imagen: %s" % e}
    return {"ok": True, "archivo": destino, "con": "Pillow"}


# ------------------------------------------------------------------ vectores
def convertir_vector(origen, destino, inkscape):
    if not inkscape:
        return {"error": "Para convertir dibujos vectoriales hace falta Inkscape "
                         "(es gratis: inkscape.org). Instálalo y vuelve a intentar."}
    ext = os.path.splitext(destino)[1].lower().lstrip(".")
    cmd = [inkscape, origen, "--export-filename=" + destino]
    if ext == "png":
        cmd.append("--export-dpi=300")
    if ext == "svg":
        cmd.append("--export-plain-svg")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"error": "Inkscape se demoró demasiado. Puede que el archivo sea muy pesado."}
    except Exception as e:
        return {"error": "No pude ejecutar Inkscape: %s" % e}

    if not os.path.exists(destino) or os.path.getsize(destino) == 0:
        detalle = (r.stderr or r.stdout or "").strip().splitlines()
        return {"error": "Inkscape no logró convertirlo.",
                "detalle": detalle[-1][:200] if detalle else ""}
    return {"ok": True, "archivo": destino, "con": "Inkscape"}


# -------------------------------------------------------------------- entrada
def convertir_archivo(origen, formato, inkscape=None, carpeta_salida=None):
    """Convierte `origen` al `formato` pedido. Nunca toca el archivo original."""
    if not os.path.exists(origen):
        return {"error": "No encuentro ese archivo."}
    formato = (formato or "").strip().lower().lstrip(".")
    if not formato.isalnum():
        return {"error": "Formato no válido."}

    ext = os.path.splitext(origen)[1].lower()
    permitidos = formatos_destino(origen)
    if not permitidos:
        return {"error": por_que_no(origen)}
    if formato not in permitidos:
        return {"error": "De %s puedo pasar a: %s." % (ext, ", ".join(permitidos))}

    carpeta = carpeta_salida or os.path.dirname(origen)
    base = os.path.splitext(os.path.basename(origen))[0]
    destino = os.path.join(carpeta, "%s.%s" % (base, formato))
    # si ya existe uno con ese nombre, no lo pisamos
    n = 2
    while os.path.exists(destino):
        destino = os.path.join(carpeta, "%s (%d).%s" % (base, n, formato))
        n += 1

    try:
        if ext in LIGHTBURN:
            return miniatura_lightburn(origen, destino)
        if ext in IMAGENES:
            return convertir_imagen(origen, destino)
        return convertir_vector(origen, destino, inkscape)
    except Exception as e:
        return {"error": str(e)}


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
# Archivos que SON la app (se reemplazan al actualizar). Se listan por si
# hiciera falta, pero la actualización toma todo lo que venga en el paquete:
# así nunca se queda afuera un archivo nuevo (paso con convertir.py en la 1.4).
ARCHIVOS_CODIGO = ["app.py", "db.py", "indexar.py", "categorias.py",
                   "elegir_carpeta.py", "actualizar.py", "ui.html"]

# Lo que NUNCA se pisa al actualizar: son los datos del usuario.
DATOS_DEL_USUARIO = {"config.json", "biblioteca.json", "biblioteca.db",
                     "biblioteca.db-wal", "biblioteca.db-shm", "version.json"}

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


def elegir_carpeta_nativa(titulo="Elige la carpeta donde tienes tus modelos"):
    """Abre el buscador de carpetas de Windows sin salir del programa.

    Como .exe no se puede lanzar elegir_carpeta.py con Python (sys.executable
    es el propio programa), asi que se llama directo a la API de Windows.
    Devuelve la ruta elegida, o "" si canceló.
    """
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [("hwndOwner", wintypes.HWND),
                        ("pidlRoot", ctypes.c_void_p),
                        ("pszDisplayName", wintypes.LPWSTR),
                        ("lpszTitle", wintypes.LPCWSTR),
                        ("ulFlags", wintypes.UINT),
                        ("lpfn", ctypes.c_void_p),
                        ("lParam", wintypes.LPARAM),
                        ("iImage", ctypes.c_int)]

        buf = ctypes.create_unicode_buffer(1024)
        bi = BROWSEINFO()
        bi.hwndOwner = None
        bi.pidlRoot = None
        bi.pszDisplayName = ctypes.cast(buf, wintypes.LPWSTR)
        bi.lpszTitle = titulo
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return ""
        ruta = ctypes.create_unicode_buffer(1024)
        ok = shell32.SHGetPathFromIDListW(pidl, ruta)
        ctypes.windll.ole32.CoTaskMemFree(pidl)
        return ruta.value if ok else ""
    except Exception:
        return ""
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def pedir_carpeta(inicial=""):
    """Pide una carpeta al usuario, de la forma que funcione en este entorno."""
    if CONGELADO:
        return elegir_carpeta_nativa(), ""
    exe = python_con_ventanas()
    try:
        r = subprocess.run([exe, os.path.join(BASE, "elegir_carpeta.py"), inicial or ""],
                           cwd=BASE, capture_output=True, text=True, timeout=600)
        elegida = (r.stdout or "").strip()
        if elegida:
            return elegida, ""
        err = (r.stderr or "").strip()
        if err == "cancelado" or r.returncode == 1:
            return "", "cancelado"
        return "", err[:200]
    except Exception as e:
        return "", str(e)[:200]


def python_con_ventanas():
    """pythonw no siempre puede abrir diálogos: preferimos python.exe."""
    exe = sys.executable
    alt = os.path.join(os.path.dirname(exe), "python.exe")
    if os.path.basename(exe).lower().startswith("pythonw") and os.path.exists(alt):
        return alt
    return exe


def elegir_programa(clave, ruta=None):
    """Deja fija la ruta del .exe de un programa. Si no se pasa, abre el buscador."""
    if clave not in PROGRAMAS_DEF:
        return {"error": "programa desconocido"}
    nombre = PROGRAMAS_DEF[clave]["nombre"]
    if not ruta:
        try:
            r = subprocess.run([python_con_ventanas(),
                                os.path.join(BASE, "elegir_carpeta.py"), "--exe", nombre],
                               cwd=BASE, capture_output=True, text=True, timeout=300)
            ruta = (r.stdout or "").strip()
            if not ruta:
                return {"error": "No elegiste ningún programa. Si no viste la ventana, "
                                 "búscala en la barra de tareas o pega la ruta del .exe abajo."}
        except Exception as e:
            return {"error": "No pude abrir la ventana. Pega la ruta del .exe abajo.",
                    "detalle": str(e)[:200]}

    ruta = ruta.strip().strip('"').strip()
    if not os.path.exists(ruta):
        return {"error": "No encuentro ese archivo: %s" % ruta}
    if not ruta.lower().endswith(".exe"):
        return {"error": "Tiene que ser un programa (archivo .exe)."}

    progs = CFG.get("programas") or {}
    progs[clave] = ruta
    CFG["programas"] = progs
    guardar_config(CFG)
    return {"ok": True, "nombre": nombre, "ruta": ruta}


def asignar_extension(ext, clave):
    """Elige con qué programa se abre una extensión (ej. .svg -> corel)."""
    ext = (ext or "").strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    if len(ext) < 2:
        return {"error": "Escribe la extensión, por ejemplo .svg"}
    if clave and clave not in PROGRAMAS_DEF and clave != "sistema":
        return {"error": "programa desconocido"}
    asign = CFG.get("asignaciones") or {}
    if clave:
        asign[ext] = clave
    else:
        asign.pop(ext, None)
    CFG["asignaciones"] = asign
    guardar_config(CFG)
    return {"ok": True, "asignaciones": asign}


def indexar_ahora(carpeta=None):
    """Lee la carpeta de modelos y genera biblioteca.json.

    Como .exe no se puede lanzar "python indexar.py": sys.executable es el
    propio programa. Por eso aca se importa indexar y se corre adentro.
    """
    if CONGELADO:
        try:
            import importlib
            import indexar
            importlib.reload(indexar)
            indexar.indexar(carpeta) if carpeta else indexar.indexar()
            return True, ""
        except SystemExit:
            return True, ""            # indexar.py termina con sys.exit(0)
        except Exception as e:
            return False, str(e)[:150]
    args = [sys.executable, os.path.join(BASE, "indexar.py")]
    if carpeta:
        args.append(carpeta)
    try:
        r = subprocess.run(args, cwd=BASE, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return False, ((r.stderr or r.stdout or "").strip()[-200:] or "no pude leer esa carpeta")
        return True, ""
    except Exception as e:
        return False, str(e)[:150]


def agregar_carpeta(ruta=None):
    """Suma otra carpeta de modelos, sin perder la que ya estaba."""
    if not ruta:
        ruta, err = pedir_carpeta()
        if not ruta:
            return {"error": "No elegiste ninguna carpeta."
                    if err in ("", "cancelado") else err}
    ruta = ruta.strip().strip('"').strip()
    if not os.path.isdir(ruta):
        return {"error": "No encuentro esa carpeta: %s" % ruta}

    actuales = raices()
    igual = [x for x in actuales if os.path.abspath(x).lower() == os.path.abspath(ruta).lower()]
    if igual:
        return {"error": "Esa carpeta ya está en la biblioteca."}
    # que no sea una carpeta que ya esta adentro de otra
    for x in actuales:
        try:
            if os.path.commonpath([os.path.abspath(x), os.path.abspath(ruta)]) == os.path.abspath(x):
                return {"error": "Esa carpeta ya está adentro de «%s», así que sus "
                                 "modelos ya aparecen." % os.path.basename(x)}
        except Exception:
            pass

    cfg = cargar_config()
    if not cfg.get("biblioteca"):
        cfg["biblioteca"] = ruta
    else:
        extra = list(cfg.get("bibliotecas_extra") or [])
        extra.append(ruta)
        cfg["bibliotecas_extra"] = extra
    guardar_config(cfg)

    listo, err = indexar_ahora()
    if not listo:
        return {"error": err or "no pude leer esa carpeta"}
    recargar_indice()
    return {"ok": True, "carpeta": ruta, "total": len(MODELOS), "carpetas": len(raices())}


def quitar_carpeta(ruta):
    """Saca una carpeta de la biblioteca. No borra nada del disco."""
    ruta = (ruta or "").strip()
    if not ruta:
        return {"error": "falta la carpeta"}
    cfg = cargar_config()
    principal = cfg.get("biblioteca") or ""
    if os.path.abspath(ruta).lower() == os.path.abspath(principal).lower():
        return {"error": "Esa es la carpeta principal. Para cambiarla usa "
                         "«Elegir otra carpeta»."}
    extra = [x for x in (cfg.get("bibliotecas_extra") or [])
             if os.path.abspath(x).lower() != os.path.abspath(ruta).lower()]
    cfg["bibliotecas_extra"] = extra
    guardar_config(cfg)
    listo, err = indexar_ahora()
    if not listo:
        return {"error": err or "no pude releer las carpetas"}
    recargar_indice()
    return {"ok": True, "total": len(MODELOS), "carpetas": len(raices())}


def cambiar_carpeta(nueva=None):
    """Cambia la carpeta de modelos y vuelve a indexar.
    Si no se pasa ruta, abre el selector de carpetas de Windows."""
    if not nueva:
        nueva, err = pedir_carpeta(RAIZ or "")
        if not nueva:
            if err == "cancelado" or not err:
                return {"error": "No elegiste ninguna carpeta. "
                                 "Si no viste la ventana, búscala en la barra de tareas "
                                 "o escribe la ruta abajo."}
            return {"error": "No pude abrir la ventana para elegir la carpeta. "
                             "Escribe o pega la ruta abajo.", "detalle": err}

    nueva = nueva.strip().strip('"').strip()
    if not nueva:
        return {"error": "Escribe la ruta de la carpeta."}
    if not os.path.isdir(nueva):
        return {"error": f"No encuentro esa carpeta: {nueva}"}

    cfg = cargar_config()
    cfg["biblioteca"] = nueva
    guardar_config(cfg)
    listo, err = indexar_ahora(nueva)
    if not listo:
        return {"error": err or "no pude leer esa carpeta"}
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
        # los costos y materiales que el usuario ajustó, y sus subcategorías
        "materiales": db.filas("SELECT * FROM materiales"),
        "costos_fijos": db.filas("SELECT * FROM costos_fijos"),
        "ajustes": db.ajustes_todos(),
        "subcats": db.filas("SELECT * FROM subcats"),
    }


def respaldar_base():
    """Copia segura de la base, aunque la app esté funcionando.
    Copiar el archivo a mano NO sirve: SQLite deja cambios en biblioteca.db-wal
    y la copia queda a medias."""
    destino = os.path.join(BASE, "respaldos",
                           "biblioteca-%s.db" % time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    try:
        db.cx().execute("VACUUM INTO ?", (destino,))
    except Exception as e:
        return {"error": str(e)}
    # dejamos solo los 10 respaldos más nuevos
    carpeta = os.path.dirname(destino)
    viejos = sorted(f for f in os.listdir(carpeta) if f.endswith(".db"))
    for f in viejos[:-10]:
        try:
            os.remove(os.path.join(carpeta, f))
        except OSError:
            pass
    return {"ok": True, "archivo": destino}


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

        # costos, materiales y ajustes: reemplazan a los actuales, porque son
        # los valores con que el usuario cotiza (si no, quedarían duplicados)
        if datos.get("materiales"):
            c.execute("DELETE FROM materiales")
        if datos.get("costos_fijos"):
            c.execute("DELETE FROM costos_fijos")
        for m in datos.get("materiales", []):
            m = dict(m); m.pop("id", None)
            db.guardar_material(m)
            n["materiales"] = n.get("materiales", 0) + 1
        for cf in datos.get("costos_fijos", []):
            cf = dict(cf); cf.pop("id", None)
            db.guardar_costo_fijo(cf)
            n["costos"] = n.get("costos", 0) + 1
        for k, v in (datos.get("ajustes") or {}).items():
            db.guardar_ajuste(k, v)
        for s in datos.get("subcats", []):
            db.ocultar_subcat(s.get("categoria"), s.get("subcategoria"), s.get("oculta"))
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
        "actual": APP_VERSION, "actual_nombre": APP_NOMBRE,
        "disponible": nueva, "disponible_nombre": info.get("nombre", ""),
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
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                partes = n.split("/")
                # solo la raíz del paquete: nada de subcarpetas
                if len(partes) > 2:
                    continue
                archivo = partes[-1]
                if archivo in DATOS_DEL_USUARIO or archivo.startswith("."):
                    continue
                if not archivo.lower().endswith((".py", ".html", ".bat", ".txt", ".md")):
                    continue
                datos = z.read(n)
                destino = os.path.join(BASE, archivo)
                if os.path.exists(destino):
                    if open(destino, "rb").read() == datos:
                        continue            # ya está igual, no lo tocamos
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
                "raices": [{"ruta": x, "principal": (i == 0),
                            "modelos": sum(1 for m in MODELOS if m.get("raiz", RAIZ) == x)}
                           for i, x in enumerate(raices())],
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
            # con qué programa se abre cada archivo (por su extensión)
            progs = {}
            for grupo in (m.get("archivos") or {}).values():
                for a in grupo:
                    clave, exe = programa_para(a)
                    if clave:
                        progs[a] = {"clave": clave,
                                    "nombre": PROGRAMAS_DEF[clave]["nombre"],
                                    "instalado": bool(exe)}
            d["programas"] = progs
            # que pasaria al apretar cada boton grande: ya lo tiene, hay que
            # convertir, o de plano no se puede
            corte = m["archivos"]["corte"]
            d["cambios"] = revisar_cambios(rel)
            d["principal"] = (d["meta"] or {}).get("principal") or ""
            d["abrir_en"] = {}
            for cual, fmt in (("corel", "svg"), ("lightburn", "lbrn")):
                nombre, ya = formatos.mejor_origen(corte, m["ruta"], fmt)
                ext = os.path.splitext(nombre or "")[1].lower()
                puede = bool(nombre) and (ya or ext not in formatos.CERRADOS)
                d["abrir_en"][cual] = {
                    "puede": puede,
                    "convierte": bool(nombre) and not ya and puede,
                    "desde": ext.lstrip(".") if nombre else "",
                    "instalado": bool(buscar_programa(cual)),
                    "motivo": ("" if puede else
                               ("Este modelo solo viene en %s, que solo abre CorelDRAW."
                                % ext if ext in formatos.CERRADOS
                                else "Este modelo no trae archivos para cortar.")),
                }
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
                # "auto" = con el programa que corresponde a ese tipo de archivo
                if modo == "auto":
                    modo = programa_para(p)[0]
                # Cualquier otra cosa (abrir, sistema, o algo que no conocemos)
                # significa "que lo abra Windows con lo que tenga". Antes esto
                # caía en el aviso de "no encuentro tal programa", que es lo que
                # pasaba al tocar "Ver imagen" o "Ver manual".
                if modo in PROGRAMAS_DEF:
                    exe = buscar_programa(modo)
                    if exe:
                        subprocess.Popen([exe, p])
                        return self._send(200, {"ok": True, "con": PROGRAMAS_DEF[modo]["nombre"]})
                    nom = PROGRAMAS_DEF.get(modo, {}).get("nombre", modo)
                    return self._send(404, {"error": "No encuentro %s en este computador. "
                                            "Puedes indicar dónde está en ⚙️ Ajustes > Programas." % nom})
                os.startfile(p)
                return self._send(200, {"ok": True, "con": "Windows"})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        if r == "/api/abrir-en":
            # Los dos botones grandes: cada programa recibe el formato que le
            # sirve. Si el modelo no lo tiene, se convierte en el momento.
            rel, cual = arg("rel"), arg("programa")
            m = POR_REL.get(rel)
            if not m:
                return self._send(404, {"error": "no existe ese modelo"})
            if cual not in ("corel", "lightburn"):
                return self._send(400, {"error": "programa no valido"})

            destino = "svg" if cual == "corel" else "lbrn"
            ruta, err, convertido = formatos.preparar(
                m["ruta"], m["archivos"]["corte"], destino)
            if err:
                return self._send(400, {"error": err})

            exe = buscar_programa(cual)
            nombre = PROGRAMAS_DEF[cual]["nombre"]
            if not exe:
                # Sin el programa, Windows abre el cartel "Elegir una aplicacion",
                # que confunde. Mejor decirlo claro.
                return self._send(404, {
                    "error": "No encuentro %s en este computador. Si lo tienes "
                             "instalado, indicale a la app donde esta en "
                             "Ajustes > Programas." % nombre,
                    "falta_programa": cual})
            try:
                subprocess.Popen([exe, ruta])
                # anotamos como estaba, para avisar despues si lo edito
                origen_real = os.path.join(m["ruta"], os.path.basename(ruta))
                vigilar(rel, origen_real if os.path.exists(origen_real) else ruta)
            except Exception as e:
                return self._send(500, {"error": "No pude abrirlo: %s" % str(e)[:120]})
            return self._send(200, {
                "ok": True, "con": nombre if exe else "Windows",
                "archivo": os.path.basename(ruta),
                "convertido": convertido,
                "instalado": bool(exe),
            })

        if r == "/api/reglas-carpeta":
            reglas = []
            for x in db.reglas_carpeta():
                rel = x["rel"]
                n = sum(1 for m in MODELOS
                        if m["rel"].lower() == rel.lower()
                        or m["rel"].lower().startswith(rel.lower() + os.sep))
                reglas.append({"rel": rel, "categoria": x["categoria"],
                               "subcategoria": x["subcategoria"], "modelos": n})
            return self._send(200, {"reglas": reglas, "raiz": RAIZ})

        if r == "/api/programas":
            return self._send(200, {"programas": programas_estado(),
                                    "asignaciones": CFG.get("asignaciones") or {}})

        if r == "/api/convertir/opciones":
            a = arg("f")
            return self._send(200, {
                "formatos": formatos_destino(a),
                "motivo": por_que_no(a),
                "inkscape": bool(buscar_programa("inkscape")),
            })

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
            return self._send(200, {"version": APP_VERSION, "nombre": APP_NOMBRE})

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

        if r == "/api/programa":
            d = self._json()
            res = elegir_programa(d.get("clave", ""), d.get("ruta"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/programa/asignar":
            d = self._json()
            res = asignar_extension(d.get("ext", ""), d.get("clave", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/convertir":
            d = self._json()
            p = d.get("p", "")
            if not ruta_segura(p) or not os.path.exists(p):
                return self._send(403, {"error": "ruta no permitida"})
            res = convertir_archivo(p, d.get("formato", ""),
                                    inkscape=buscar_programa("inkscape"))
            if res.get("ok"):
                db.registrar_version(d.get("rel", ""), "convertido",
                                     os.path.basename(res["archivo"]), "")
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/principal":
            d = self._json()
            res = hacer_principal(d.get("rel", ""), d.get("nombre", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/principal/ignorar":
            _VIGILADOS.pop(self._json().get("rel", ""), None)
            return self._send(200, {"ok": True})

        if r == "/api/categoria/crear":
            res = crear_categoria(self._json().get("nombre", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/categoria/borrar":
            d = self._json()
            res = borrar_categoria(d.get("nombre"), d.get("destino", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/categoria/renombrar":
            d = self._json()
            res = renombrar_categoria(d.get("vieja"), d.get("nueva"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/categoria/ordenar":
            nombres = self._json().get("orden") or []
            if not isinstance(nombres, list) or not nombres:
                return self._send(400, {"error": "orden no valido"})
            db.ordenar_cats([str(n) for n in nombres])
            return self._send(200, {"ok": True})

        if r == "/api/carpeta/agregar":
            res = agregar_carpeta(self._json().get("carpeta"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/carpeta/quitar":
            res = quitar_carpeta(self._json().get("carpeta"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/carpeta/marcar":
            d = self._json()
            ruta = d.get("carpeta")
            if not ruta:
                # sin ruta escrita, se abre el buscador de carpetas de Windows
                ruta, err = pedir_carpeta(RAIZ or "")
                if not ruta:
                    return self._send(400, {"error": "No elegiste ninguna carpeta."
                                            if err in ("", "cancelado")
                                            else "No pude abrir la ventana: %s" % err[:90]})
            res = marcar_carpeta(ruta, d.get("categoria"), d.get("subcategoria", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/carpeta/desmarcar":
            db.borrar_regla(self._json().get("rel", ""))
            recargar_reglas()
            return self._send(200, {"ok": True})

        if r == "/api/subcategoria/crear":
            d = self._json()
            cat = (d.get("categoria") or "").strip()
            nom = (d.get("nombre") or "").strip()
            if not cat or not nom:
                return self._send(400, {"error": "Elige la categoría y escribe el nombre."})
            db.crear_subcat(cat, nom)
            return self._send(200, {"ok": True, "categoria": cat, "nombre": nom})

        if r == "/api/subcategoria/renombrar":
            d = self._json()
            res = renombrar_subcat(d.get("categoria"), d.get("vieja"), d.get("nueva"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/subcategoria/borrar":
            d = self._json()
            res = borrar_subcat(d.get("categoria"), d.get("nombre"), d.get("destino", ""))
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
            listo, err = indexar_ahora()
            if not listo:
                return self._send(500, {"error": err or "no pude leer la carpeta"})
            recargar_indice()
            return self._send(200, {"ok": True, "total": len(MODELOS)})

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


def reordenar_si_hace_falta():
    """Si la app trae una forma nueva de ordenar los modelos, vuelve a leer la
    carpeta sola. Sin esto, mejorar las categorías no cambiaría nada hasta que
    el usuario apretara 'Buscar modelos nuevos' a mano."""
    global DATOS, MODELOS, POR_REL
    import categorias
    nueva = getattr(categorias, "VERSION_CLASIFICADOR", 1)
    guardada = DATOS.get("clasificador", 0)
    if guardada >= nueva or not RAIZ or not os.path.isdir(RAIZ):
        return False
    print("  Ordenando tus modelos con las categorías nuevas...")
    listo, _err = indexar_ahora(RAIZ)
    if not listo:
        print("  (no se pudo reordenar ahora; puedes hacerlo en Ajustes)")
        return False
    DATOS = cargar_indice()
    MODELOS = DATOS["modelos"]
    POR_REL = {m["rel"]: m for m in MODELOS}
    print("  Listo: tus modelos quedaron ordenados de nuevo.")
    return True


def recargar():
    """Vuelve a leer el indice y la configuracion desde el disco.
    Se usa cuando algo cambio por fuera (por ejemplo al traer los datos de
    una instalacion anterior)."""
    global DATOS, RAIZ, MODELOS, POR_REL, CFG
    CFG = cargar_config()
    DATOS = cargar_indice()
    RAIZ = DATOS.get("raiz", "")
    MODELOS = DATOS.get("modelos", [])
    POR_REL = {m["rel"]: m for m in MODELOS}
    recargar_reglas()
    return len(MODELOS)


def preparar(avisar=None):
    """Deja todo listo antes de mostrar la biblioteca.
    `avisar` es una funcion opcional para contar en que va (la usa la ventana)."""
    di = avisar or (lambda t: None)
    di("Abriendo tus datos...")
    db.cx()
    db.sembrar_costos()
    di("Revisando el orden de las categorias...")
    reordenar_si_hace_falta()
    try:
        formatos.limpiar_cache()
    except Exception:
        pass
    di("Listo")


def arrancar_servidor():
    """Levanta el servidor en segundo plano y devuelve (servidor, direccion).
    Si el puerto esta ocupado, busca otro: asi no falla si quedo algo abierto."""
    global PUERTO
    ultimo = None
    for intento in range(12):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
            break
        except OSError as e:
            ultimo = e
            PUERTO += 1
    else:
        raise ultimo
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % PUERTO


def main():
    """Modo consola: se usa como respaldo si la ventana no abre."""
    preparar()
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
