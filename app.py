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
import base64, io          # miniaturas de LightBurn
import sqlite3, uuid, tempfile
from datetime import datetime
from functools import wraps
from contextlib import closing
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import db
import formatos
import indexar
import agregados
import configuracion

CONGELADO = getattr(sys, "frozen", False)   # True cuando corre como .exe

APP_VERSION = "2.2"
APP_NOMBRE = "Ordenado y tranquilo"
# De dónde se bajan las actualizaciones (ZIP con los archivos de la app).
URL_ACTUALIZACIONES = "https://raw.githubusercontent.com/Pacmancinya/biblioteca-laser/main/version.json"
# A quién le llegan las ideas/cambios que anota el usuario (WhatsApp de Ruperto).
WHATSAPP_SOPORTE = "56954703465"

BASE = os.environ.get("BIBLIOTECA_LASER_BASE") or os.path.dirname(os.path.abspath(__file__))
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
_REVISIONES = {}
_MEDIDAS = {}


def aplicar_preferencias(m):
    mt = db.meta(m["rel"]) or {}
    foto = mt.get("foto_preferida")
    if foto and foto in m["archivos"]["imagen"]:
        m["preview"] = foto
    manual = mt.get("manual_preferido")
    if manual and any(manual in grupo for grupo in m["archivos"].values()) and manual not in m["archivos"]["manual"]:
        m["archivos"]["manual"].insert(0, manual)
        m["tiene_manual"] = True
    principal = mt.get("principal")
    corte = m["archivos"]["corte"]
    if principal and any(principal in grupo for grupo in m["archivos"].values()):
        if principal in corte:
            corte.remove(principal)
        corte.insert(0, principal)
    return m


def recargar_indice():
    global DATOS, RAIZ, MODELOS, POR_REL
    DATOS = cargar_indice()
    RAIZ = DATOS["raiz"]
    MODELOS = DATOS["modelos"]
    POR_REL = {m["rel"]: m for m in MODELOS}
    for m in MODELOS:
        aplicar_preferencias(m)


def cargar_config():
    return configuracion.leer(CONFIG)

def guardar_config(c):
    global CFG
    CFG = configuracion.modificar(CONFIG, c)
    return CFG

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
        guardar_config(lambda c: c.setdefault("programas", {}).update({clave: hallado}))
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
                    guardar_config(lambda c: c.setdefault("programas", {}).update({clave: hallado}))
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
    cfg = cargar_config()
    r = [cfg.get("biblioteca")] + (cfg.get("bibliotecas_extra") or [])
    r = [x for x in r if x]
    return r


def ruta_segura(p, miniaturas=False):
    """Raíces de modelos, enlaces resueltos y miniaturas propias; nunca datos de la app."""
    try:
        if not p or not os.path.isabs(p):
            return False
        p = os.path.normcase(os.path.realpath(p))
    except Exception:
        return False
    # Ni configurar la carpeta de la app como raíz permite descargar sus datos.
    app_base = os.path.normcase(os.path.realpath(BASE))
    thumb_base = os.path.normcase(os.path.realpath(CACHE_THUMBS))
    def dentro(base, ruta):
        try:
            return os.path.commonpath([base, ruta]) == base
        except ValueError:
            return False
    if miniaturas and dentro(thumb_base, p):
        return bool(re.fullmatch(r"[a-f0-9]{32}\.jpg", os.path.basename(p)))
    permitidas = [os.path.normcase(os.path.realpath(x)) for x in raices() if x]
    if dentro(app_base, p):
        primero = os.path.relpath(p, app_base).split(os.sep)[0].lower()
        if primero.startswith(".") or primero in ("_papelera", "_ventana", "respaldos", "_version_anterior", "_exe"):
            return False
        # Agregados puede vivir en BASE, con una raíz específica diferente de BASE.
        if not any(b != app_base and dentro(app_base, b) and dentro(b, p) for b in permitidas):
            return False
    for base in permitidas:
        if dentro(base, p):
            return True
    return False


def error_ruta(p, carpeta=False):
    if not ruta_segura(p):
        return "Ese archivo no está dentro de tus carpetas de modelos."
    for raiz in raices():
        if not os.path.isdir(raiz):
            try:
                if os.path.commonpath([os.path.abspath(raiz), os.path.abspath(p)]) == os.path.abspath(raiz):
                    return "No encuentro la carpeta de modelos %s. ¿Está conectado el disco?" % raiz
            except ValueError:
                pass
    if not os.path.exists(p):
        return "No encuentro %s %s. Puede que se haya movido o cambiado de nombre. ¿Está conectado el disco?" % ("la carpeta" if carpeta else "el archivo", p)
    return ""


@db.atomico
def recordar_rutas():
    for rel, mt in db.meta_todos().items():
        m = POR_REL.get(rel)
        if m and not mt.get("ruta_guardada"):
            db.guardar_meta(rel, {"ruta_guardada": m["ruta"]})


@db.atomico
def detectar_no_encontrados():
    for rel, mt in db.meta_todos().items():
        m = POR_REL.get(rel)
        guardada = mt.get("ruta_guardada")
        falta = not m or bool(guardada and os.path.normcase(os.path.realpath(guardada)) != os.path.normcase(os.path.realpath(m["ruta"])))
        db.guardar_meta(rel, {"no_encontrado": int(falta)})


def no_encontrados():
    salida = []
    for rel, mt in db.meta_todos().items():
        if rel in POR_REL and not mt.get("no_encontrado"):
            continue
        if not tiene_datos(mt):
            continue
        final = rel.replace("\\", "/").split("/")[-1].lower()
        sugeridas = [{"rel": m["rel"], "nombre": m["nombre"], "ruta": m["ruta"]} for m in MODELOS
                     if os.path.basename(m["ruta"]).lower() == final]
        salida.append({"rel": rel, "nombre": mt.get("nombre") or rel, "ruta": mt.get("ruta_guardada") or rel,
                       "sugeridas": sugeridas})
    return salida


def tiene_datos(meta):
    return any(meta.get(k) for k in ("nombre", "notas", "categoria", "subcategoria", "favorito", "stock", "cliente_id", "principal", "oculto", "foto_preferida", "manual_preferido")) or any(meta.get(k) is not None for k in ("precio", "costo"))


@db.exclusivo
def resolver_no_encontrado(rel, destino="", descartar=False):
    # El respaldo precede a la transacción (SQLite.backup no se ejecuta dentro).
    if rel not in {m["rel"] for m in no_encontrados()}:
        return {"error": "Ese modelo ya está asociado a una carpeta."}
    m = POR_REL.get(destino)
    if not descartar and not m:
        return {"error": "Elige una carpeta de modelos que aparezca en la biblioteca."}
    existente = db.meta(destino) if destino != rel else None
    if existente and tiene_datos(existente):
        return {"error": "La carpeta elegida ya tiene datos guardados. Elige otra para no pisarlos."}
    copia = respaldar_base("Antes de recuperar los datos de " + rel)
    if not copia.get("ok"):
        return copia
    with db.transaccion() as c:
        if descartar:
            c.execute("DELETE FROM modelos WHERE rel=?", (rel,))
            c.execute("UPDATE pedidos SET rel=NULL WHERE rel=?", (rel,))
            c.execute("UPDATE ventas SET rel=NULL WHERE rel=?", (rel,))
        else:
            if existente:
                c.execute("DELETE FROM modelos WHERE rel=?", (destino,))
            c.execute("UPDATE modelos SET rel=?,ruta_guardada=?,no_encontrado=0 WHERE rel=?", (destino, m["ruta"], rel))
            for tabla in ("pedidos", "ventas", "versiones"):
                c.execute("UPDATE " + tabla + " SET rel=? WHERE rel=?", (destino, rel))
            c.execute("UPDATE reglas_carpeta SET rel=? WHERE rel=?", (destino, rel))
    recargar_reglas()
    return {"ok": True}


def resolver_categoria(nombre):
    destinos = json.loads(db.ajuste("categoria_destinos", "{}"))
    vistos = set()
    while nombre in destinos and nombre not in vistos:
        vistos.add(nombre)
        nombre = destinos[nombre]
    return nombre


def es_convertidos(ruta):
    return "_convertidos" in os.path.realpath(ruta).replace("\\", "/").lower().split("/")


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
            if sub is None:
                sub = r[1] or ""

    return {
        "rel": m["rel"], "id": m["id"],
        "n": mt.get("nombre") or m["nombre"],
        "n_orig": m["nombre"],
        "c": resolver_categoria(cat or m["categoria"]),
        "s": sub if sub is not None else m["subcategoria"],
        "ruta_partes": partes, "ruta": m["ruta"],
        "fmt": m["formatos"], "gr": m["grosores"],
        "img": 1 if m["tiene_imagen"] else 0, "man": 1 if m["tiene_manual"] else 0,
        # hay algo que mostrar: una foto, la miniatura del archivo de LightBurn,
        # o el dibujo del propio modelo
        "prev": 1 if (m["tiene_imagen"] or m["tiene_lightburn"]
                      or any(os.path.splitext(a)[1].lower() in _EXT_DIBUJABLES
                             for a in m["archivos"]["corte"])) else 0,
        "lb": 1 if m["tiene_lightburn"] else 0, "d3": 1 if m["tiene_3d"] else 0,
        "fav": 1 if mt.get("favorito") else 0,
        "oculto": 1 if mt.get("oculto") or mt.get("no_encontrado") else 0,
        "revision": str(m.get("mtime", 0)) + "-" + str(mt.get("actualizado", 0)) + "-" + str(_REVISIONES.get(m["rel"], 0)),
        "archivos_busqueda": " ".join(a for grupo in m["archivos"].values() for a in grupo),
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
        if v.get("oculto"):
            continue
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
    orden_sub = {(r["categoria"], r["subcategoria"]): r["orden"] for r in db.filas("SELECT * FROM subcats")}
    for g in salida:
        g["subs"].sort(key=lambda sub: orden_sub.get((g["nombre"], sub["nombre"]), 999))
        g["propia"] = g["nombre"] in propias_cat
    return salida


def cambio_organizacion(descripcion):
    """El respaldo y el cambio se hacen juntos, sin otras solicitudes entremedio."""
    def decorar(funcion):
        @wraps(funcion)
        def protegida(*args, **kwargs):
            with db.LOCK:
                texto = descripcion(*args, **kwargs) if callable(descripcion) else descripcion
                copia = respaldar_base(texto)
                if not copia.get("ok"):
                    return copia
                try:
                    return funcion(*args, **kwargs)
                finally:
                    # También restaura la vista de reglas si una transacción falló.
                    recargar_reglas()
        return protegida
    return decorar


@cambio_organizacion(lambda nombre: "Antes de crear la categoría " + str(nombre))
def crear_categoria(nombre):
    nombre = (nombre or "").strip()
    if not nombre:
        return {"error": "Escribe el nombre de la categoría."}
    if len(nombre) > 40:
        return {"error": "El nombre es muy largo."}
    actuales = [g["nombre"] for g in categorias_con_conteo(vistas_todas())]
    if nombre in actuales:
        return {"error": "Ya existe una categoría con ese nombre."}
    if len(actuales) >= 6:
        return {"error": "Puedes tener hasta 6 categorías grandes. Saca una antes de crear otra."}
    db.guardar_cat(nombre, orden=len(actuales), propia=True, oculta=False)
    return {"ok": True, "nombre": nombre}


@cambio_organizacion(lambda nombre, destino="": "Antes de sacar la categoría " + str(nombre))
@db.atomico
def borrar_categoria(nombre, destino=""):
    """Saca una categoría grande. Sus modelos pasan a `destino`, o vuelven a
    donde los pondría el programa solo. Nunca se borra nada del disco."""
    nombre = (nombre or "").strip()
    destino = (destino or "").strip()
    if not nombre:
        return {"error": "falta la categoría"}
    vistas = vistas_todas()
    afectados = [v for v in vistas if v["c"] == nombre]
    if destino == nombre:
        return {"error": "Elige otra categoría para los modelos."}
    import categorias as cats
    if not destino and (nombre in [g["nombre"] for g in cats.estructura()] or afectados or db.fila("SELECT rel FROM modelos WHERE categoria=? LIMIT 1", (nombre,)) or db.fila("SELECT rel FROM reglas_carpeta WHERE categoria=? LIMIT 1", (nombre,))):
        return {"error": "Elige a qué categoría mandar los modelos antes de borrar esta categoría."}
    destino = destino or "Otros"
    _orden, ocultas, _propias = db.cats_propias()
    posibles = {g["nombre"] for g in categorias_con_conteo(vistas)} | {g["nombre"] for g in cats.estructura() if g["nombre"] not in ocultas}
    if destino not in posibles and destino != "Otros":
        return {"error": "Elige una de las categorías existentes para los modelos."}
    with db.transaccion():
        db.ejecutar("UPDATE modelos SET categoria=?,subcategoria='' WHERE categoria=?", (destino, nombre))
        db.ejecutar("UPDATE reglas_carpeta SET categoria=?,subcategoria='' WHERE categoria=?", (destino, nombre))
        db.ejecutar("DELETE FROM subcats WHERE categoria=?", (nombre,))
        destinos = json.loads(db.ajuste("categoria_destinos", "{}"))
        destinos[nombre] = destino
        db.guardar_ajuste("categoria_destinos", json.dumps(destinos, ensure_ascii=False))
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": destino, "subcategoria": ""})
    # y las reglas de carpeta que apuntaban ahi
    for r in db.reglas_carpeta():
        if r["categoria"] == nombre:
            db.guardar_regla(r["rel"], destino, "")
    recargar_reglas()
    import categorias as cats
    if nombre in [g["nombre"] for g in cats.estructura()]:
        db.guardar_cat(nombre, oculta=True, propia=False)   # de fabrica: se tapa
    else:
        db.quitar_cat(nombre)
    return {"ok": True, "movidos": len(afectados), "destino": destino}


@cambio_organizacion(lambda viejo, nuevo: "Antes de renombrar la categoría " + str(viejo))
@db.atomico
def renombrar_categoria(viejo, nuevo):
    viejo, nuevo = (viejo or "").strip(), (nuevo or "").strip()
    if not viejo or not nuevo:
        return {"error": "Faltan los nombres."}
    if viejo == nuevo:
        return {"ok": True, "movidos": 0}
    if nuevo in [g["nombre"] for g in categorias_con_conteo(vistas_todas())]:
        return {"error": "Ya existe una categoría con ese nombre."}
    vistas = vistas_todas()
    afectados = [v for v in vistas if v["c"] == viejo]
    with db.transaccion():
        db.ejecutar("UPDATE modelos SET categoria=? WHERE categoria=?", (nuevo, viejo))
        db.ejecutar("UPDATE reglas_carpeta SET categoria=? WHERE categoria=?", (nuevo, viejo))
        db.ejecutar("UPDATE subcats SET categoria=? WHERE categoria=?", (nuevo, viejo))
        destinos = json.loads(db.ajuste("categoria_destinos", "{}"))
        destinos.pop(nuevo, None)
        destinos[viejo] = nuevo
        db.guardar_ajuste("categoria_destinos", json.dumps(destinos, ensure_ascii=False))
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": nuevo})
    for r in db.reglas_carpeta():
        if r["categoria"] == viejo:
            db.guardar_regla(r["rel"], nuevo, r["subcategoria"])
    recargar_reglas()
    orden, _oc, _pr = db.cats_propias()
    db.guardar_cat(nuevo, orden=orden.get(viejo, 999), propia=True, oculta=False)
    import categorias as cats
    if viejo in [g["nombre"] for g in cats.estructura()]:
        db.guardar_cat(viejo, oculta=True)
    else:
        db.quitar_cat(viejo)
    return {"ok": True, "movidos": len(afectados)}


def vistas_todas():
    metas = db.meta_todos()
    return [modelo_vista(m, metas) for m in MODELOS]


@cambio_organizacion(lambda ruta, categoria, subcategoria="": "Antes de cambiar la categoría fija de la carpeta " + str(ruta))
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
    if not nombre or os.path.basename(nombre) != nombre or "/" in nombre or "\\" in nombre:
        return {"error": "Elige un archivo de esta carpeta, sin rutas a otras carpetas."}
    recargar_parcial(rel)
    m = POR_REL[rel]
    origen = os.path.join(m["ruta"], nombre)
    if not ruta_segura(origen) or not os.path.exists(origen):
        return {"error": "no encuentro ese archivo"}

    corte = m["archivos"]["corte"]
    ext = os.path.splitext(nombre)[1].lower()
    if ext not in [e.lower() for e in
                   (".svg", ".dxf", ".eps", ".ai", ".cdr", ".cmx", ".lbrn", ".lbrn2", ".plt", ".dwg", ".pdf")]:
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
    """Persistencia atómica: nunca silenciar un error de escritura."""
    DATOS["modelos"] = MODELOS
    DATOS["total_modelos"] = len(MODELOS)
    indexar.guardar_json_atomico(INDICE, DATOS)


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


@cambio_organizacion(lambda cat, vieja, nueva: "Antes de renombrar la subcategoría " + str(vieja))
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
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": cat, "subcategoria": nueva})
    db.quitar_subcat(cat, vieja)
    db.crear_subcat(cat, nueva)
    # si el nombre viejo sale solo al leer la carpeta, hay que taparlo
    if _la_pone_el_programa(cat, vieja):
        db.ocultar_subcat(cat, vieja, 1)
    return {"ok": True, "movidos": len(afectados)}


@cambio_organizacion(lambda cat, sub, destino="": "Antes de sacar la subcategoría " + str(sub))
def borrar_subcat(cat, sub, destino=""):
    """Saca una subcategoría. Sus modelos pasan a `destino` (o quedan sin subcategoría);
    nunca se borra nada del disco."""
    cat, sub = (cat or "").strip(), (sub or "").strip()
    if not cat or not sub:
        return {"error": "falta la subcategoría"}
    destino = (destino or "").strip()
    afectados = modelos_en(cat, sub)
    for v in afectados:
        db.guardar_meta(v["rel"], {"categoria": cat, "subcategoria": destino})
    db.quitar_subcat(cat, sub)
    # Solo hay que taparla si la inventa el programa; si la creó el usuario,
    # con quitarla basta y no dejamos basura guardada.
    if _la_pone_el_programa(cat, sub):
        db.ocultar_subcat(cat, sub, 1)
    return {"ok": True, "movidos": len(afectados), "destino": destino}


@cambio_organizacion("Antes de ordenar las categorías")
def ordenar_categorias(nombres):
    db.ordenar_cats(nombres)
    return {"ok": True}


@cambio_organizacion("Antes de asignar modelos arrastrando")
def asignar_modelos(rels, categoria, subcategoria=""):
    if not isinstance(rels, list) or not rels or any(not isinstance(r, str) or r not in POR_REL for r in rels):
        return {"error": "Selecciona modelos válidos."}
    grupos = categorias_con_conteo(vistas_todas())
    grupo = next((g for g in grupos if g["nombre"] == categoria), None)
    if not grupo or (subcategoria and subcategoria not in [s["nombre"] for s in grupo["subs"]]):
        return {"error": "Elige una categoría o subcategoría existente."}
    for rel in set(rels):
        db.guardar_meta(rel, {"categoria": categoria, "subcategoria": subcategoria})
    return {"ok": True, "aviso": "Listo. Si no te gusta, Respaldo -> Volver a como estaba."}


@cambio_organizacion("Antes de ordenar las subcategorías")
def ordenar_subcategorias(categoria, nombres):
    g = next((g for g in categorias_con_conteo(vistas_todas()) if g["nombre"] == categoria), None)
    if not g or not isinstance(nombres, list) or any(not isinstance(n, str) for n in nombres) or set(nombres) != {s["nombre"] for s in g["subs"]} or len(nombres) != len(set(nombres)):
        return {"error": "Orden no válido."}
    db.ordenar_subcats(categoria, nombres)
    return {"ok": True}


@cambio_organizacion("Antes de trasladar una subcategoría")
def trasladar_subcategoria(categoria, subcategoria, destino):
    grupos = categorias_con_conteo(vistas_todas())
    origen = next((g for g in grupos if g["nombre"] == categoria), None)
    if not origen or subcategoria not in [s["nombre"] for s in origen["subs"]] or destino not in [g["nombre"] for g in grupos]:
        return {"error": "Elige categorías existentes."}
    if categoria == destino:
        return {"ok": True}
    for v in modelos_en(categoria, subcategoria):
        db.guardar_meta(v["rel"], {"categoria": destino, "subcategoria": subcategoria})
    for regla in db.reglas_carpeta():
        if regla["categoria"] == categoria and regla["subcategoria"] == subcategoria:
            db.guardar_regla(regla["rel"], destino, subcategoria)
    db.ocultar_subcat(categoria, subcategoria)
    db.crear_subcat(destino, subcategoria)
    recargar_reglas()
    return {"ok": True}


@cambio_organizacion(lambda cat, nombre: "Antes de crear la subcategoría " + str(nombre))
def crear_subcategoria(cat, nombre):
    db.crear_subcat(cat, nombre)
    return {"ok": True, "categoria": cat, "nombre": nombre}


@cambio_organizacion(lambda rel: "Antes de quitar la categoría fija de la carpeta " + str(rel))
def quitar_regla(rel):
    db.borrar_regla(rel)
    recargar_reglas()
    return {"ok": True}


@cambio_organizacion(lambda rel: "Antes de ocultar o volver a mostrar el modelo " + str(rel))
def alternar_modelo_oculto(rel):
    return {"ok": True, "oculto": db.alternar_oculto(rel)}


@db.exclusivo
def guardar_edicion(rel, campos):
    viejo = db.meta(rel) or {}
    if any(k in campos and campos[k] != viejo.get(k) for k in ("categoria", "subcategoria", "oculto")):
        res = respaldar_base("Antes de cambiar la categoría o visibilidad del modelo " + str(rel))
        if not res.get("ok"):
            return res
    db.guardar_meta(rel, campos)
    return {"ok": True, "meta": db.meta(rel)}


def archivo_para_programa(m, programa, principal=""):
    archivos = [a for grupo in m["archivos"].values() for a in grupo]
    return formatos.elegir_archivo(m["ruta"], archivos, programa, principal)


@db.exclusivo
def finalizar_agregado(destinos, categoria, subcategoria):
    nuevos = []
    for destino in destinos:
        nuevos.extend(releer_arbol(destino))
        if categoria:
            rel = os.path.relpath(destino, RAIZ)
            db.guardar_regla(rel, categoria, subcategoria)
    recargar_reglas()
    return nuevos


@db.exclusivo
def preparar_arrastre(rutas, categoria="", subcategoria=""):
    if categoria:
        grupo = next((g for g in categorias_con_conteo(vistas_todas()) if g["nombre"] == categoria), None)
        if not grupo or (subcategoria and subcategoria not in [s["nombre"] for s in grupo["subs"]]):
            return {"error": "Ese destino ya no existe. Arrastra de nuevo."}
    raiz = RAIZ or cargar_config().get("biblioteca", "")
    return agregados.preparar(rutas, raiz, categoria, subcategoria, finalizar_agregado,
                             lambda: respaldar_base("Antes de agregar modelos a una categoría"))


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
        principal = (db.meta(rel) or {}).get("principal")
        if principal and principal in m["archivos"]["corte"]:
            p = os.path.join(m["ruta"], principal)
            ext = os.path.splitext(principal)[1].lower()
            if os.path.isfile(p) and os.path.getsize(p) < 12_000_000:
                if ext in formatos.LIGHTBURN:
                    lbrn = p
                elif ext in formatos.LEIBLES:
                    dibujo = p
        if not lbrn and not dibujo:
            lbrn = vista_previa_lightburn(m)
        if lbrn:
            origen = lbrn
        else:
            # tampoco hay: dibujamos el modelo a partir del archivo de corte
            for a in (m["archivos"]["corte"] or []):
                if dibujo:
                    break
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





# ------------------------------------------------------------------ LightBurn
_RX_THUMB = re.compile(rb'<Thumbnail\s+Source="([^"]+)"')

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


@db.exclusivo
def guardar_archivo(rel, tipo, nombre, datos):
    """Guarda un archivo en la carpeta del modelo. Si reemplaza a otro,
    respalda el anterior en _versiones_anteriores (máximo 3)."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    carpeta = m["ruta"]
    if es_convertidos(carpeta):
        return {"error": "Los trabajos de _convertidos se conservan tal como están. Guarda el archivo en otra carpeta de modelos."}
    if not ruta_segura(carpeta):
        return {"error": "ruta no permitida"}
    nombre = os.path.basename(nombre).replace("\\", "").replace("/", "")
    if not nombre or nombre in (".", ".."):
        return {"error": "nombre inválido"}
    extension = os.path.splitext(nombre)[1].lower()
    permitidas = {"imagen": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"},
                  "manual": {".pdf", ".jpg", ".png", ".txt", ".doc", ".docx"},
                  "modelo": EXT_CORTE}
    if tipo not in permitidas or extension not in permitidas[tipo] or ":" in nombre:
        return {"error": "Ese tipo de archivo no sirve para esta carga. No se aceptan ejecutables ni accesos directos."}
    mensaje = error_ruta(carpeta, True)
    if mensaje:
        return {"error": mensaje}
    destino = os.path.join(carpeta, nombre)

    temporal = ""
    try:
        if os.path.exists(destino):
            if not os.path.isfile(destino) or os.path.islink(destino):
                return {"error": "Ese nombre corresponde a una carpeta o enlace. Elige otro nombre."}
            respaldo = ruta_respaldo(carpeta, nombre)
            shutil.copy2(destino, respaldo)
            db.registrar_version(rel, tipo, nombre, respaldo)
        fd, temporal = tempfile.mkstemp(prefix=".carga-", dir=carpeta)
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, destino)
        if tipo == "imagen":
            db.guardar_meta(rel, {"foto_preferida": nombre})
        elif tipo == "manual":
            db.guardar_meta(rel, {"manual_preferido": nombre})
    except OSError as e:
        return {"error": "No pude guardar el archivo. La versión anterior se conserva: %s" % e}
    finally:
        if temporal and os.path.exists(temporal):
            os.remove(temporal)
    try:
        recargar_parcial(rel)
    except OSError as e:
        return {"error": "El archivo se guardó, pero no pude guardar el índice de la biblioteca: %s" % e}
    return {"ok": True, "archivo": nombre}


# ---------------------------------------------------------------- papelera
PAPELERA = os.path.join(BASE, "_papelera")

MENSAJE_OCULTO = ("Listo, ya no se muestra. Tus archivos siguen en su carpeta. "
                  "Para que vuelva: Limpieza -> Ver ocultos.")


def borrar_archivo(rel, nombre):
    """Compatibilidad con clientes antiguos: ya no se quitan archivos del disco."""
    return {"error": "Los archivos se conservan. Puedes quitar el modelo de la biblioteca."}


@cambio_organizacion(lambda rel: "Antes de quitar el modelo " + str(rel))
def borrar_modelo(rel):
    """El basurero solo oculta, incluso si lo llama una interfaz anterior."""
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    if es_convertidos(m["ruta"]):
        return {"error": "Los trabajos de _convertidos se conservan."}
    db.guardar_meta(rel, {"oculto": 1})
    return {"ok": True, "oculto": 1, "aviso": MENSAJE_OCULTO}


@db.exclusivo
def restaurar_papelera(pid):
    it = db.item_papelera(pid)
    if not it:
        return {"error": "no está en la papelera"}
    if es_convertidos(it["origen"]) or es_convertidos(it["destino"]):
        return {"error": "Los trabajos de _convertidos se conservan tal como están."}
    try:
        papelera = os.path.normcase(os.path.realpath(PAPELERA))
        origen_guardado = os.path.normcase(os.path.realpath(it["destino"]))
        dentro = os.path.commonpath([papelera, origen_guardado]) == papelera
    except (ValueError, TypeError):
        dentro = False
    if not dentro or not ruta_segura(it["origen"]):
        return {"error": "No encuentro este archivo dentro de la papelera y tus carpetas de modelos. Revisa las carpetas en Ajustes."}
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
        _releer_carpeta(os.path.dirname(it["origen"]))
        guardar_indice()
    else:
        releer_arbol(it["origen"])
    return {"ok": True, "tipo": it["tipo"]}


def vaciar_papelera():
    return {"error": "La papelera se conserva solo para recuperar archivos."}


# ---------------------------------------------------------------- duplicados
SIMILITUD_MINIMA = 0.65   # cuánto se tienen que parecer dos modelos para ser "el mismo"

def buscar_duplicados(avance=None, cancelar=None):
    """Modelos que son el MISMO modelo: comparten casi todos sus archivos.

    Huella por archivo = tamaño + md5 de los primeros 128 KB (se guarda en caché,
    así la segunda búsqueda es casi instantánea). Dos modelos son duplicados si
    la similitud entre sus conjuntos de archivos supera SIMILITUD_MINIMA."""
    cache = db.huellas_todas()
    nuevas = []
    firmas = {}
    metas = db.meta_todos()
    visibles = [m for m in MODELOS if not (metas.get(m["rel"]) or {}).get("oculto") and not (metas.get(m["rel"]) or {}).get("no_encontrado")]
    total = max(1, len(visibles) * 2)

    def progreso(numero):
        if cancelar and cancelar.is_set():
            raise InterruptedError("Búsqueda cancelada. Tus modelos se conservan.")
        if avance:
            avance(numero, total)

    for posicion, m in enumerate(visibles):
        progreso(posicion)
        a = m.get("archivos") or {}
        candidatos = (a.get("corte") or [])[:25]
        if not candidatos:
            continue
        conj = set()
        for fn in candidatos:
            progreso(posicion)
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

    for posicion, m in enumerate(visibles):
        progreso(len(visibles) + posicion)
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
    progreso(total)
    return grupos


_DUP_TRABAJOS = {}
_DUP_LOCK = threading.RLock()


def iniciar_duplicados():
    with _DUP_LOCK:
        for identificador, trabajo in _DUP_TRABAJOS.items():
            if trabajo["estado"] == "buscando":
                return {"ok": True, "id": identificador}
        # Solo la última búsqueda, para no acumular miles de resultados en memoria.
        _DUP_TRABAJOS.clear()
        identificador = uuid.uuid4().hex
        trabajo = {"estado": "buscando", "actual": 0, "total": 1, "cancelar": threading.Event()}
        _DUP_TRABAJOS[identificador] = trabajo

    def avance(actual, total):
        with _DUP_LOCK:
            trabajo.update(actual=actual, total=total)

    def buscar():
        try:
            grupos = buscar_duplicados(avance, trabajo["cancelar"])
            with _DUP_LOCK:
                trabajo.update(estado="listo", grupos=grupos)
        except InterruptedError:
            with _DUP_LOCK:
                trabajo["estado"] = "cancelado"
        except Exception as error:
            with _DUP_LOCK:
                trabajo.update(estado="error", error="No pude revisar los archivos: " + str(error))
    threading.Thread(target=buscar, daemon=True).start()
    return {"ok": True, "id": identificador}


def estado_duplicados(identificador):
    with _DUP_LOCK:
        trabajo = _DUP_TRABAJOS.get(identificador)
        return {k: v for k, v in trabajo.items() if k != "cancelar"} if trabajo else {"error": "No encuentro esa búsqueda."}


# ---------------------------------------------------------------- respaldo de datos
# Archivos que SON la app (se reemplazan al actualizar). Se listan por si
# hiciera falta, pero la actualización toma todo lo que venga en el paquete:
# así nunca se queda afuera un archivo nuevo (paso con convertir.py en la 1.4).
ARCHIVOS_CODIGO = ["app.py", "db.py", "indexar.py", "configuracion.py", "categorias.py",
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
            horas = 9600 if c.get("grupo") == "Equipos" else 800
        valor_hora = monto / horas
        valor_min = valor_hora / 60.0
        parcial += valor_min
        detalle.append({"id": c["id"], "nombre": c["nombre"], "grupo": c["grupo"],
                        "monto": monto, "horas": horas,
                        "valor_hora": round(valor_hora, 4), "valor_minuto": round(valor_min, 5)})
    aj = db.ajustes_todos()
    pct = float(aj.get("ganancia_minuto") or 0)
    ganancia = parcial * pct / 100.0
    return {"detalle": detalle, "aviso": "Hay costos con horas en cero: se repartieron en 9.600 horas para equipos y 800 para gastos mensuales. Corrígelos en Ajustes > Costos." if any(float(c.get("horas") or 0) <= 0 for c in db.costos_fijos()) else "", "parcial": round(parcial, 4),
            "ganancia_pct": pct, "ganancia": round(ganancia, 4),
            "final": round(parcial + ganancia, 4)}


def cotizar(d):
    """Igual que el Excel 'CALCULO_DE_COSTOS': material por cm2 + tiempo de corte
    + luz + mano de obra + depreciación, y al final la utilidad."""
    aj = db.ajustes_todos()
    num = lambda v, x=0.0: db.numero(v, "cotización", x)

    minutos = num(d.get("minutos"), num(aj.get("minutos_defecto"), 30))
    ancho_c, largo_c = num(d.get("ancho")), num(d.get("largo"))
    piezas = db.numero(d.get("piezas"), "cantidad de piezas", 1, entero=True)
    if piezas < 1:
        raise ValueError("La cantidad de piezas debe ser al menos uno.")

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
    guardar_config(lambda c: c.setdefault("programas", {}).update({clave: ruta}))
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
    def cambiar(c):
        asignaciones = c.setdefault("asignaciones", {})
        if clave:
            asignaciones[ext] = clave
        else:
            asignaciones.pop(ext, None)
    guardar_config(cambiar)
    return {"ok": True, "asignaciones": asign}


def indexar_ahora(carpeta=None, avance=None):
    """Lee la carpeta de modelos y genera biblioteca.json.

    Como .exe no se puede lanzar "python indexar.py": sys.executable es el
    propio programa. Por eso aca se importa indexar y se corre adentro.
    """
    for raiz in ([carpeta] if carpeta else raices()):
        if not os.path.isdir(raiz):
            return False, "No encuentro la carpeta de modelos %s. ¿Está conectado el disco?" % raiz
    try:
        recordar_rutas()
        indexar.CONFIG, indexar.SALIDA = CONFIG, INDICE
        indexar.indexar(carpeta, avance=avance)
        recargar_indice()
        detectar_no_encontrados()
        return True, ""
    except Exception as e:
        return False, str(e)


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
        guardar_config({"biblioteca": ruta})
    else:
        extra = list(cfg.get("bibliotecas_extra") or [])
        extra.append(ruta)
        guardar_config({"bibliotecas_extra": extra})

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
    guardar_config({"bibliotecas_extra": extra})
    listo, err = indexar_ahora()
    if not listo:
        return {"error": err or "no pude releer las carpetas"}
    recargar_indice()
    return {"ok": True, "total": len(MODELOS), "carpetas": len(raices())}


def cambiar_carpeta(nueva=None, confirmado=False):
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

    recordar_rutas()
    afectados = [rel for rel, mt in db.meta_todos().items() if rel in POR_REL and
                 os.path.normcase(os.path.realpath(POR_REL[rel]["ruta"])) != os.path.normcase(os.path.realpath(os.path.join(nueva, rel))) and
                 not rel.startswith("[") and tiene_datos(mt)]
    if afectados and not confirmado:
        return {"confirmar": True, "carpeta": nueva, "afectados": len(afectados),
                "aviso": "%s modelos tienen datos guardados en la carpeta anterior. Podrás asociarlos o descartarlos en Limpieza > Modelos que ya no encuentro. ¿Cambiar la carpeta?" % len(afectados)}
    copia = respaldar_base("Antes de cambiar la carpeta principal")
    if not copia.get("ok"):
        return copia
    anterior = cargar_config().get("biblioteca", "")
    guardar_config({"biblioteca": nueva})
    listo, err = indexar_ahora(nueva)
    if not listo:
        guardar_config({"biblioteca": anterior})
        return {"error": err or "no pude leer esa carpeta"}
    recargar_indice()
    return {"ok": True, "carpeta": RAIZ, "total": len(MODELOS)}


@db.exclusivo
def exportar_datos():
    """Todo lo que el usuario editó, en un solo archivo para llevarlo a otro PC."""
    origen = db.ajuste("respaldo_origen", "")
    if not origen:
        origen = uuid.uuid4().hex
        db.guardar_ajuste("respaldo_origen", origen)
    recordar_rutas()
    return {
        "formato_version": 3,
        "origen": origen,
        "base_origen": BASE,
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
        "cats": db.filas("SELECT * FROM cats"),
        "reglas_carpeta": db.reglas_carpeta(),
        "versiones": db.filas("SELECT * FROM versiones"),
        "papelera": db.papelera(),
    }


MARCA_RESPALDO = "biblioteca-laser-respaldo-v22"
AVISO_RESPALDO = ""
_NOMBRE_RESPALDO = re.compile(r"bl-v22-(diario|cambio)-[0-9]{8}-[0-9]{12}-[0-9a-f]{32}\.db$")


def carpeta_respaldos():
    return os.path.join(BASE, "respaldos")


@db.exclusivo
def listar_respaldos(carpeta=None):
    carpeta = carpeta or carpeta_respaldos()
    salida = []
    if not os.path.isdir(carpeta):
        return salida
    for nombre in os.listdir(carpeta):
        match = _NOMBRE_RESPALDO.fullmatch(nombre)
        ruta = os.path.join(carpeta, nombre)
        ficha = ruta + ".json"
        if not match or not os.path.isfile(ruta) or os.path.islink(ruta) or os.path.islink(ficha):
            continue
        try:
            with open(ficha, encoding="utf-8") as f:
                dato = json.load(f)
            if (dato.get("marca") != MARCA_RESPALDO or dato.get("archivo") != nombre
                    or dato.get("tipo") != match.group(1)):
                continue
            datetime.fromisoformat(dato["fecha"])
            salida.append(dato)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(salida, key=lambda x: x["fecha"], reverse=True)


def limitar_respaldos(carpeta=None):
    carpeta = carpeta or carpeta_respaldos()
    lista = listar_respaldos(carpeta)
    for tipo in ("diario", "cambio"):
        propios = [x for x in lista if x["tipo"] == tipo]
        for viejo in propios[30:]:
            ruta = os.path.join(carpeta, viejo["archivo"])
            try:
                os.remove(ruta)
                os.remove(ruta + ".json")
            except OSError:
                pass


@db.exclusivo
def respaldar_base(descripcion="Antes de cambiar el orden de la biblioteca", tipo="cambio"):
    """La API de SQLite incluye lo que aún vive en el WAL, sin copiar la base abierta."""
    if tipo not in ("diario", "cambio"):
        return {"error": "No pude guardar la copia. No se cambió tu biblioteca."}
    ahora = datetime.now()
    nombre = "bl-v22-%s-%s-%s.db" % (tipo, ahora.strftime("%Y%m%d-%H%M%S%f"), uuid.uuid4().hex)
    destino = os.path.join(carpeta_respaldos(), nombre)
    dato = {"marca": MARCA_RESPALDO, "archivo": nombre, "tipo": tipo,
            "fecha": ahora.isoformat(timespec="microseconds"), "descripcion": descripcion}
    try:
        os.makedirs(carpeta_respaldos(), exist_ok=True)
        with closing(sqlite3.connect(destino)) as copia:
            db.cx().backup(copia)
        with open(destino + ".json", "x", encoding="utf-8") as f:
            json.dump(dato, f, ensure_ascii=False, indent=2)
    except Exception:
        for p in (destino, destino + ".json"):
            try:
                os.remove(p)
            except OSError:
                pass
        return {"error": "No pude guardar la copia de seguridad. No se cambió tu biblioteca. Revisa que haya espacio en el disco."}
    limitar_respaldos()
    return {"ok": True, "archivo": destino, "respaldo": dato}


def copiar_diario_externo(dato):
    externa = db.ajuste("carpeta_respaldo_externa", "")
    if not externa:
        return ""
    if not os.path.isdir(externa):
        return "La copia quedó guardada en este computador. Conecta la carpeta externa para guardar también allí."
    if es_convertidos(externa):
        return "La copia quedó guardada en este computador. Elige otra carpeta externa: _convertidos conserva tus trabajos anteriores."
    try:
        origen = os.path.join(carpeta_respaldos(), dato["archivo"])
        destino = os.path.join(externa, dato["archivo"])
        if os.path.normcase(os.path.abspath(origen)) != os.path.normcase(os.path.abspath(destino)):
            # Aquí sí se copia: este archivo es un respaldo ya cerrado, nunca la base en uso.
            shutil.copy2(origen, destino)
            shutil.copy2(origen + ".json", destino + ".json")
            limitar_respaldos(externa)
    except OSError:
        return "La copia quedó en este computador, pero no pude guardarla en la carpeta externa. Revisa que esté conectada y tenga espacio."
    return ""


@db.exclusivo
def respaldo_diario():
    global AVISO_RESPALDO
    hoy = datetime.now().date().isoformat()
    dato = next((x for x in listar_respaldos() if x["tipo"] == "diario" and x["fecha"].startswith(hoy)), None)
    if dato is None:
        res = respaldar_base("Copia del día al abrir la biblioteca", "diario")
        if not res.get("ok"):
            AVISO_RESPALDO = res["error"].replace("No se cambió tu biblioteca. ", "")
            return res
        dato = res["respaldo"]
    AVISO_RESPALDO = copiar_diario_externo(dato)
    return {"ok": True, "aviso": AVISO_RESPALDO}


@db.exclusivo
def volver_respaldo(nombre):
    global AVISO_RESPALDO
    dato = next((x for x in listar_respaldos() if x["archivo"] == nombre), None)
    if not dato:
        return {"error": "No encuentro esa copia. Elige otra de la lista."}
    origen = None
    previo = None
    try:
        from pathlib import Path
        origen = sqlite3.connect(Path(os.path.join(carpeta_respaldos(), nombre)).as_uri() + "?mode=ro", uri=True)
        if origen.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("copia dañada")
        tablas = {x[0] for x in origen.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        necesarias = {x[0] for x in db.cx().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not necesarias.issubset(tablas):
            raise ValueError("copia incompleta")
        # Separar la fuente de su archivo antes de aplicar la retención:
        # así se puede volver también a la más antigua en Windows.
        instantanea = sqlite3.connect(":memory:")
        try:
            origen.backup(instantanea)
        except Exception:
            instantanea.close()
            raise
        origen.close()
        origen = instantanea
        previo = respaldar_base("Antes de volver a la biblioteca del " + dato["fecha"][:16].replace("T", " "))
        if not previo.get("ok"):
            return previo
        db.cerrar()
        try:
            with closing(sqlite3.connect(db.DB_PATH)) as destino:
                origen.backup(destino)
        except Exception:
            # Si una restauración falla, recuperamos la copia previa con la misma API.
            with closing(sqlite3.connect(previo["archivo"])) as segura, closing(sqlite3.connect(db.DB_PATH)) as destino:
                segura.backup(destino)
            raise
        finally:
            db.cx()
        recargar()
        _VIGILADOS.clear()
        AVISO_RESPALDO = ""
        fecha = datetime.fromisoformat(dato["fecha"]).strftime("%d-%m-%Y a las %H:%M")
        return {"ok": True, "aviso": "Listo, la biblioteca quedó como estaba el " + fecha,
                "deshacer": os.path.basename(previo["archivo"])}
    except Exception:
        if previo is None:
            return {"error": "No pude abrir esa copia. Tu biblioteca sigue como estaba. Elige otra de la lista."}
        return {"error": "No pude volver a esa copia. Tus datos actuales siguen guardados en la copia previa."}
    finally:
        if origen is not None:
            origen.close()


@cambio_organizacion("Antes de cargar un respaldo")
def importar_datos(datos, modo="fusionar"):
    """Carga un respaldo. modo=fusionar (respeta lo que ya hay) o reemplazar."""
    if not isinstance(datos, dict) or "modelos" not in datos:
        return {"error": "el archivo no es un respaldo válido"}
    if modo not in ("fusionar", "reemplazar") or datos.get("formato_version", 1) not in (1, 2, 3):
        return {"error": "No conozco ese formato de respaldo."}
    tablas = ("clientes", "modelos", "pedidos", "ventas", "materiales", "costos_fijos",
              "cats", "subcats", "reglas_carpeta", "sugerencias", "versiones", "papelera")
    n = {t: 0 for t in tablas}
    origen = datos.get("origen") or hashlib.sha256(json.dumps(
        {k: v for k, v in datos.items() if k != "fecha"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        with db.transaccion() as c:
            if modo == "reemplazar":
                for tabla in tablas + ("ajustes", "importaciones"):
                    c.execute("DELETE FROM " + tabla)
            mapa_cli = {}
            for tabla in tablas:
                usados = set()
                registros = datos.get(tabla, [])
                if not isinstance(registros, list):
                    raise ValueError("La sección %s del respaldo no es válida." % tabla)
                columnas = {r[1] for r in c.execute("PRAGMA table_info(" + tabla + ")")}
                for registro in registros:
                    if not isinstance(registro, dict):
                        raise ValueError("Hay un registro inválido en " + tabla)
                    d = {k: v for k, v in registro.items() if k in columnas and k != "id"}
                    viejo = registro.get("id")
                    if "cliente_id" in d:
                        d["cliente_id"] = mapa_cli.get(str(d["cliente_id"]))
                    if tabla in ("versiones", "papelera"):
                        for campo in ("origen", "destino", "respaldo"):
                            if d.get(campo):
                                d[campo] = remapear_ruta(d[campo], datos.get("base_origen"), BASE)
                    if tabla == "modelos":
                        if not d.get("rel"):
                            raise ValueError("Un modelo del respaldo no tiene carpeta.")
                        # La carpeta se vuelve a comprobar en esta instalación.
                        m = POR_REL.get(d["rel"])
                        if m:
                            d["ruta_guardada"] = m["ruta"]
                            d["no_encontrado"] = 0
                    clave = str(viejo) if viejo is not None else hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
                    existente = None
                    if "id" in columnas:
                        marca = c.execute("SELECT id_local FROM importaciones WHERE origen=? AND tabla=? AND id_original=?",
                                          (origen, tabla, clave)).fetchone()
                        if marca:
                            existente = c.execute("SELECT id FROM " + tabla + " WHERE id=?", (marca[0],)).fetchone()
                        if not existente and d:
                            # Reconoce registros locales que ya formaban parte del respaldo.
                            condiciones = " AND ".join(k + " IS ?" for k in d)
                            coincidencias = c.execute("SELECT id FROM " + tabla + " WHERE " + condiciones, list(d.values())).fetchall()
                            existente = next((r for r in coincidencias if r[0] not in usados), None)
                        if existente:
                            nuevo = existente[0]
                        else:
                            campos = ",".join(d)
                            nuevo = c.execute("INSERT INTO " + tabla + " (" + campos + ") VALUES (" + ",".join("?" for _ in d) + ")", list(d.values())).lastrowid
                            n[tabla] += 1
                        usados.add(nuevo)
                        c.execute("INSERT OR REPLACE INTO importaciones VALUES (?,?,?,?)", (origen, tabla, clave, nuevo))
                        if tabla == "clientes":
                            mapa_cli[str(viejo)] = nuevo
                    else:
                        keys = {"modelos": ("rel",), "cats": ("nombre",), "subcats": ("categoria", "subcategoria"),
                                "reglas_carpeta": ("rel",)}[tabla]
                        if any(not d.get(k) for k in keys):
                            raise ValueError("Falta un nombre o carpeta en " + tabla)
                        existe = c.execute("SELECT 1 FROM " + tabla + " WHERE " + " AND ".join(k + "=?" for k in keys), [d[k] for k in keys]).fetchone()
                        if existe and modo == "fusionar":
                            continue
                        campos = ",".join(d)
                        c.execute("INSERT OR REPLACE INTO " + tabla + " (" + campos + ") VALUES (" + ",".join("?" for _ in d) + ")", list(d.values()))
                        n[tabla] += 1
            ajustes = datos.get("ajustes", {})
            if not isinstance(ajustes, dict):
                raise ValueError("Los ajustes del respaldo no son válidos.")
            for k, v in ajustes.items():
                if k != "respaldo_origen":
                    db.guardar_ajuste(k, v)
            detectar_no_encontrados()
        recargar_reglas()
    except Exception as e:
        return {"error": "No pude cargar el respaldo. Tus datos se conservaron: " + str(e)}
    return {"ok": True, "importado": n}


def remapear_ruta(ruta, antigua, nueva):
    if not antigua:
        return ruta
    import ntpath
    # Los respaldos de Windows pueden cargarse desde otra plataforma.
    normal = ntpath.normcase(ntpath.normpath(ruta))
    base = ntpath.normcase(ntpath.normpath(antigua)).rstrip("\\")
    if normal == base or normal.startswith(base + "\\"):
        resto = ntpath.relpath(ruta, antigua).replace("\\", os.sep)
        return os.path.join(nueva, resto)
    return ruta


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


@db.exclusivo
def restaurar_version(rel, vid):
    v = db.fila("SELECT * FROM versiones WHERE id=?", (vid,))
    if not v or v["rel"] != rel or not os.path.isfile(v["respaldo"]):
        return {"error": "esa versión ya no está"}
    m = POR_REL.get(rel)
    if not m:
        return {"error": "modelo no encontrado"}
    actual = os.path.join(m["ruta"], v["archivo"])
    if not ruta_segura(v["respaldo"]) or os.path.basename(v["archivo"]) != v["archivo"] or "/" in v["archivo"] or "\\" in v["archivo"]:
        return {"error": "Esa versión no está dentro de tus carpetas de modelos."}
    if es_convertidos(actual) or es_convertidos(v["respaldo"]):
        return {"error": "Los trabajos de _convertidos se conservan tal como están."}
    # Leemos antes de crear otro respaldo: la retención puede retirar esta versión.
    with open(v["respaldo"], "rb") as f:
        contenido = f.read()
    return guardar_archivo(rel, v["tipo"], v["archivo"], contenido)


# ---------------------------------------------------------------- servidor
def respuesta_segura(funcion):
    @wraps(funcion)
    def protegida(self, *args, **kwargs):
        try:
            return funcion(self, *args, **kwargs)
        except Exception as error:
            import traceback
            try:
                with open(os.path.join(BASE, "errores.log"), "a", encoding="utf-8") as registro:
                    registro.write("\n" + time.strftime("%Y-%m-%d %H:%M:%S ") + self.path + "\n" + traceback.format_exc())
            except OSError:
                pass
            mensaje = str(error) if isinstance(error, (ValueError, FileNotFoundError, TimeoutError)) else "No pude completar esta acción. Inténtalo otra vez. El detalle quedó en errores.log."
            return self._send(400 if isinstance(error, ValueError) else 500, {"error": mensaje})
    return protegida


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
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0:
            raise ValueError("El tamaño de la carga no es válido.")
        self.connection.settimeout(15)
        try:
            datos = self.rfile.read(n) if n else b""
        except TimeoutError as error:
            raise ValueError("La carga no terminó. Vuelve a subir el archivo; se conserva el anterior.") from error
        if len(datos) != n:
            raise ValueError("La carga se cortó antes de terminar. El archivo anterior se conserva; vuelve a subirlo.")
        return datos

    def _json(self):
        datos = json.loads(self._cuerpo().decode("utf-8-sig") or "{}")
        if not isinstance(datos, dict):
            raise ValueError("No pude leer los datos de esta acción.")
        return datos

    # ------------------------------------------------------------ GET
    @respuesta_segura
    @db.exclusivo
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        r = u.path
        q = urllib.parse.parse_qs(u.query)
        arg = lambda k, d="": (q.get(k) or [d])[0]

        if r == "/inicio":
            return self._send(200, '<!doctype html><html lang="es"><meta charset="utf-8"><style>body{background:#14120F;color:#F1E9DC;font:22px system-ui;display:grid;place-content:center;height:90vh;text-align:center}progress{width:380px;max-width:80vw;margin:auto}</style><h1>Ordenando tu biblioteca...</h1><progress></progress><p id="arranqueTexto">Abriendo tus datos...</p></html>', "text/html; charset=utf-8")

        if r in ("/", "/index.html"):
            with open(os.path.join(BASE, "ui.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if r == "/api/datos":
            metas = db.meta_todos()
            vistas = [modelo_vista(m, metas) for m in MODELOS]
            return self._send(200, {
                "modelos": vistas,
                "categorias": categorias_con_conteo([v for v in vistas if not v["oculto"]]),
                "total": sum(not v["oculto"] for v in vistas),
                "no_encontrados": len(no_encontrados()),
                "raiz": RAIZ,
                "raices": [{"ruta": x, "principal": (i == 0),
                            "modelos": sum(1 for m in MODELOS if m.get("raiz", RAIZ) == x and not (metas.get(m["rel"]) or {}).get("oculto") and not (metas.get(m["rel"]) or {}).get("no_encontrado"))}
                           for i, x in enumerate(raices())],
                "lightburn": buscar_lightburn() or "",
                "clientes": db.clientes(),
                "aviso_respaldo": AVISO_RESPALDO,
            })

        if r == "/api/modelo":
            rel = arg("rel")
            m = POR_REL.get(rel)
            if not m:
                return self._send(404, {"error": "no existe"})
            aviso = error_ruta(m["ruta"], True)
            if not aviso:
                m = recargar_parcial(rel)
                if not m:
                    return self._send(404, {"error": "Esta carpeta ya no contiene archivos para cortar. Sus datos se conservan en Limpieza."})
            d = dict(m)
            d["aviso_disco"] = aviso
            d["vista"] = modelo_vista(m)
            padre = os.path.normcase(os.path.realpath(m["ruta"])).rstrip(os.sep) + os.sep
            d["submodelos"] = sum(os.path.normcase(os.path.realpath(x["ruta"])).startswith(padre) for x in MODELOS)
            d["medidas_mm"] = None
            if not aviso:
                for archivo in m["archivos"]["corte"]:
                    ruta = os.path.join(m["ruta"], archivo)
                    if os.path.isfile(ruta) and os.path.getsize(ruta) < 12_000_000:
                        clave = (ruta, os.stat(ruta).st_mtime_ns, os.path.getsize(ruta))
                        if clave not in _MEDIDAS:
                            _MEDIDAS[clave] = formatos.medidas_confiables(ruta)
                        if _MEDIDAS[clave]:
                            d["medidas_mm"] = _MEDIDAS[clave]
                            break
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
            # Los botones abren archivos existentes del modelo, incluido PDF.
            d["cambios"] = revisar_cambios(rel)
            d["principal"] = (d["meta"] or {}).get("principal") or ""
            d["abrir_en"] = {}
            for cual in ("corel", "lightburn"):
                nombre = archivo_para_programa(m, cual, d["principal"])
                puede = bool(nombre)
                d["abrir_en"][cual] = {
                    "puede": puede,
                    "archivo": nombre or "",
                    "instalado": bool(buscar_programa(cual)),
                    "motivo": "" if puede else "Este modelo no trae un archivo que pueda abrir " + PROGRAMAS_DEF[cual]["nombre"] + ".",
                }
            return self._send(200, d)

        if r == "/thumb":
            res = miniatura(arg("rel"))
            if not res:
                return self._send(404, b"", "text/plain")
            body, ctype = res
            return self._send(200, body, ctype, {"Cache-Control": "no-cache"})

        if r == "/api/archivo":
            p = arg("p")
            if not ruta_segura(p, miniaturas=True):
                return self._send(403, {"error": "Ese archivo no está dentro de tus carpetas de modelos."})
            if not os.path.isfile(p):
                return self._send(404, {"error": error_ruta(p) or "No encuentro ese archivo."})
            ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
            with open(p, "rb") as f:
                return self._send(200, f.read(), ctype, {"Cache-Control": "no-cache"})

        if r == "/api/abrir":
            p, modo = arg("p"), arg("modo", "auto")
            mensaje = error_ruta(p)
            if mensaje:
                return self._send(404, {"error": mensaje})
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
            # Los dos botones grandes abren un archivo que ya existe.
            rel, cual = arg("rel"), arg("programa")
            m = POR_REL.get(rel)
            if not m:
                return self._send(404, {"error": "no existe ese modelo"})
            if cual not in ("corel", "lightburn"):
                return self._send(400, {"error": "programa no valido"})
            mensaje = error_ruta(m["ruta"], True)
            if mensaje:
                return self._send(404, {"error": mensaje})

            elegido = archivo_para_programa(m, cual, (db.meta(rel) or {}).get("principal", ""))
            if not elegido:
                return self._send(400, {"error": "Este modelo no trae un archivo que pueda abrir " + PROGRAMAS_DEF[cual]["nombre"] + "."})
            ruta = os.path.join(m["ruta"], elegido)
            mensaje = error_ruta(ruta)
            if mensaje:
                return self._send(404, {"error": mensaje})
            if not ruta_segura(ruta):
                return self._send(403, {"error": "No encuentro ese archivo dentro de tus modelos."})

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
                vigilar(rel, ruta)
            except Exception as e:
                return self._send(500, {"error": "No pude abrirlo: %s" % str(e)[:120]})
            return self._send(200, {
                "ok": True, "con": nombre if exe else "Windows",
                "archivo": os.path.basename(ruta),
                "instalado": bool(exe),
            })

        if r == "/api/reglas-carpeta":
            reglas = []
            for x in db.reglas_carpeta():
                rel = x["rel"]
                metas = db.meta_todos()
                n = sum(1 for m in MODELOS if not (metas.get(m["rel"]) or {}).get("oculto") and not (metas.get(m["rel"]) or {}).get("no_encontrado")
                        and (m["rel"].lower() == rel.lower()
                        or m["rel"].lower().startswith(rel.lower() + os.sep)))
                reglas.append({"rel": rel, "categoria": x["categoria"],
                               "subcategoria": x["subcategoria"], "modelos": n})
            return self._send(200, {"reglas": reglas, "raiz": RAIZ})

        if r == "/api/programas":
            return self._send(200, {"programas": programas_estado(),
                                    "asignaciones": CFG.get("asignaciones") or {}})


        if r == "/api/carpeta":
            p = arg("p")
            mensaje = error_ruta(p, True)
            if mensaje:
                return self._send(404, {"error": mensaje})
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

        if r == "/api/agregados/estado":
            res = agregados.estado(arg("id"))
            return self._send(200 if "estado" in res else 400, res)

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
        if r == "/api/duplicados/estado":
            return self._send(200, estado_duplicados(arg("id")))
        if r == "/api/no-encontrados":
            return self._send(200, {"items": no_encontrados(), "destinos": [{"rel": m["rel"], "nombre": m["nombre"], "ruta": m["ruta"]} for m in MODELOS]})

        if r == "/api/version":
            return self._send(200, {"version": APP_VERSION, "nombre": APP_NOMBRE})

        if r == "/api/actualizacion/revisar":
            return self._send(200, revisar_actualizacion())

        if r == "/api/datos/exportar":
            cuerpo = json.dumps(exportar_datos(), ensure_ascii=False, indent=1)
            nombre = "biblioteca-respaldo-" + time.strftime("%Y%m%d") + ".json"
            return self._send(200, cuerpo, "application/json; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{nombre}"'})

        if r == "/api/respaldos":
            return self._send(200, {"items": listar_respaldos(),
                                   "carpeta_externa": db.ajuste("carpeta_respaldo_externa", ""),
                                   "aviso": AVISO_RESPALDO})

        return self._send(404, {"error": "no encontrado"})

    # ------------------------------------------------------------ POST
    @respuesta_segura
    @db.exclusivo
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        r = u.path
        q = urllib.parse.parse_qs(u.query)
        arg = lambda k, d="": (q.get(k) or [d])[0]

        if r == "/api/duplicados/iniciar":
            self._json()
            return self._send(200, iniciar_duplicados())
        if r == "/api/duplicados/cancelar":
            d = self._json()
            with _DUP_LOCK:
                trabajo = _DUP_TRABAJOS.get(d.get("id"))
                if trabajo:
                    trabajo["cancelar"].set()
            return self._send(200, {"ok": True})

        if r == "/api/meta":
            d = self._json()
            rel = d.pop("rel", "")
            if not rel or rel not in POR_REL:
                return self._send(400, {"error": "modelo no válido"})
            res = guardar_edicion(rel, d)
            return self._send(200 if res.get("ok") else 400, res)

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
            return self._send(200, res)

        if r == "/api/restaurar":
            d = self._json()
            res = restaurar_version(d.get("rel", ""), d.get("id"))
            if "error" in res:
                return self._send(400, res)
            return self._send(200, res)

        if r == "/api/agregados/confirmar":
            res = agregados.confirmar(self._json().get("id"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/agregados/cancelar":
            res = agregados.cancelar(self._json().get("id"))
            return self._send(200 if res.get("ok") else 400, res)

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
            guardar_config({"whatsapp": str(self._json().get("numero") or "").strip()})
            return self._send(200, {"ok": True, "whatsapp": CFG["whatsapp"]})

        if r == "/api/ocultar":
            rel = self._json().get("rel", "")
            if not rel or rel not in POR_REL:
                return self._send(400, {"error": "modelo no válido"})
            res = alternar_modelo_oculto(rel)
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/carpeta/cambiar":
            d = self._json()
            res = cambiar_carpeta(d.get("carpeta"), d.get("confirmado", False))
            return self._send(200 if res.get("ok") or res.get("confirmar") else 400, res)
        if r == "/api/no-encontrados/resolver":
            d = self._json()
            res = resolver_no_encontrado(d.get("rel"), d.get("destino", ""), d.get("descartar", False))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/programa":
            d = self._json()
            res = elegir_programa(d.get("clave", ""), d.get("ruta"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/programa/asignar":
            d = self._json()
            res = asignar_extension(d.get("ext", ""), d.get("clave", ""))
            return self._send(200 if res.get("ok") else 400, res)


        if r == "/api/principal":
            d = self._json()
            res = hacer_principal(d.get("rel", ""), d.get("nombre", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/principal/ignorar":
            _VIGILADOS.pop(self._json().get("rel", ""), None)
            return self._send(200, {"ok": True})

        if r == "/api/modelos/asignar":
            d = self._json()
            res = asignar_modelos(d.get("rels"), d.get("categoria"), d.get("subcategoria", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/subcategoria/ordenar":
            d = self._json()
            res = ordenar_subcategorias(d.get("categoria"), d.get("orden"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/subcategoria/trasladar":
            d = self._json()
            res = trasladar_subcategoria(d.get("categoria"), d.get("subcategoria"), d.get("destino"))
            return self._send(200 if res.get("ok") else 400, res)

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
            res = ordenar_categorias([str(n) for n in nombres])
            return self._send(200 if res.get("ok") else 400, res)

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
            res = quitar_regla(self._json().get("rel", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/subcategoria/crear":
            d = self._json()
            cat = (d.get("categoria") or "").strip()
            nom = (d.get("nombre") or "").strip()
            if not cat or not nom:
                return self._send(400, {"error": "Elige la categoría y escribe el nombre."})
            res = crear_subcategoria(cat, nom)
            return self._send(200 if res.get("ok") else 400, res)

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
            return self._send(400, vaciar_papelera())

        if r == "/api/actualizacion/aplicar":
            res = aplicar_actualizacion(self._json().get("zip", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/datos/importar":
            d = self._json()
            res = importar_datos(d.get("datos"), d.get("modo", "fusionar"))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/respaldos/volver":
            res = volver_respaldo(self._json().get("archivo", ""))
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/respaldos/carpeta":
            d = self._json()
            if d.get("quitar"):
                db.guardar_ajuste("carpeta_respaldo_externa", "")
                return self._send(200, {"ok": True})
            if sys.platform == "win32":
                ruta = elegir_carpeta_nativa("Elige la carpeta del pendrive u otro disco donde guardar la copia del día")
            else:
                ruta, err = pedir_carpeta(db.ajuste("carpeta_respaldo_externa", ""))
            if not ruta:
                return self._send(400, {"error": "No elegiste una carpeta. Tu copia de este computador sigue guardada."})
            if not os.path.isdir(ruta):
                return self._send(400, {"error": "No encuentro esa carpeta. Revisa que esté conectada."})
            if es_convertidos(ruta):
                return self._send(400, {"error": "Elige otra carpeta. _convertidos conserva tus trabajos anteriores."})
            db.guardar_ajuste("carpeta_respaldo_externa", ruta)
            res = respaldo_diario()
            return self._send(200 if res.get("ok") else 400, res)

        if r == "/api/reindexar":
            listo, err = indexar_ahora()
            if not listo:
                return self._send(500, {"error": err or "no pude leer la carpeta"})
            recargar_indice()
            return self._send(200, {"ok": True, "total": len(MODELOS)})

        return self._send(404, {"error": "no encontrado"})


def contexto_carpeta(ruta):
    for i, raiz in enumerate(raices()):
        try:
            if os.path.commonpath([os.path.abspath(ruta), os.path.abspath(raiz)]) == os.path.abspath(raiz):
                marca = "" if i == 0 else "[%s]" % os.path.basename(raiz.rstrip(os.sep + "/"))
                return raiz, marca
        except ValueError:
            continue
    raise ValueError("Esa carpeta no pertenece a la biblioteca.")


def invalidar_miniatura(rel):
    _REVISIONES[rel] = time.time_ns()
    thumb = os.path.join(CACHE_THUMBS, hashlib.md5(rel.encode("utf-8")).hexdigest() + ".jpg")
    if os.path.isfile(thumb):
        os.remove(thumb)


def _releer_carpeta(ruta):
    raiz, marca = contexto_carpeta(ruta)
    rel = os.path.relpath(ruta, raiz)
    if marca:
        rel = os.path.join(marca, rel) if rel != "." else marca
    anterior = POR_REL.get(rel)
    nuevo = indexar.leer_modelo(ruta, raiz, marca,
                               anterior["id"] if anterior else max((m["id"] for m in MODELOS), default=-1) + 1,
                               POR_REL)
    if anterior:
        MODELOS.remove(anterior)
        POR_REL.pop(rel, None)
    if nuevo:
        aplicar_preferencias(nuevo)
        MODELOS.append(nuevo)
        POR_REL[rel] = nuevo
    invalidar_miniatura(rel)
    return nuevo


@db.exclusivo
def recargar_parcial(rel):
    """Misma entrada que el indexador completo; persistida antes de responder."""
    m = POR_REL.get(rel)
    if not m:
        return
    posicion = MODELOS.index(m)
    nuevo = _releer_carpeta(m["ruta"])
    if nuevo:
        MODELOS.remove(nuevo)
        MODELOS.insert(posicion, nuevo)
    guardar_indice()
    return nuevo


@db.exclusivo
def releer_arbol(ruta):
    nuevos = []
    for carpeta, dirs, _ in os.walk(ruta):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in indexar.CARPETAS_INTERNAS)
        m = _releer_carpeta(carpeta)
        if m:
            nuevos.append(m["rel"])
    guardar_indice()
    return nuevos


def reordenar_si_hace_falta(avance=None):
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
    listo, _err = indexar_ahora(RAIZ, avance=avance)
    if not listo:
        print("  (no se pudo reordenar ahora; puedes hacerlo en Ajustes)")
        return False
    recargar_indice()
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
    for m in MODELOS:
        aplicar_preferencias(m)
    recargar_reglas()
    return len(MODELOS)


def preparar(avisar=None):
    """Deja todo listo antes de mostrar la biblioteca.
    `avisar` es una funcion opcional para contar en que va (la usa la ventana)."""
    di = avisar or (lambda t: None)
    di("Abriendo tus datos...")
    db.cx()
    db.sembrar_costos()
    if not MODELOS and cargar_config().get("biblioteca"):
        listo, error = indexar_ahora(avance=di)
        if not listo:
            raise OSError(error)
    di("Revisando el orden de las categorias...")
    reordenar_si_hace_falta(di)
    di("Guardando la copia de hoy...")
    respaldo_diario()
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
