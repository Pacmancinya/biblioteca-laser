# -*- coding: utf-8 -*-
"""Elección de archivos existentes y lectores para dibujar vistas previas."""
import os

import dxf as lector_dxf
import eps as lector_eps
import svg as lector_svg
import lbrn as lector_lbrn

# De que formatos sabemos sacar geometria, en orden de preferencia:
# primero los mas fieles y rapidos.
LEIBLES = [".svg", ".dxf", ".eps", ".ai", ".lbrn2", ".lbrn"]
# Formato cerrado: sin CorelDRAW no hay nada que hacer.
CERRADOS = {".cdr", ".cmx"}
# Los que ya son de LightBurn.
LIGHTBURN = {".lbrn", ".lbrn2"}

PRIORIDADES = {
    # El PDF va al final: casi siempre es el manual, no el dibujo.
    "corel": (".cdr", ".ai", ".eps", ".svg", ".dxf", ".pdf"),
    "lightburn": (".lbrn2", ".lbrn", ".svg", ".dxf", ".ai"),
}


def elegir_archivo(carpeta, archivos, programa, principal="", manuales=()):
    """Solo archivos del modelo que existen; el principal compatible manda.

    Un archivo que la biblioteca clasifica como manual nunca se elige como dibujo.
    """
    prioridad = PRIORIDADES.get(programa, ())
    manuales = set(manuales or ())
    existentes = []
    for nombre in archivos:
        if nombre in manuales:
            continue
        # Un nombre de archivo, nunca una ruta fuera de la carpeta del modelo.
        if os.path.basename(nombre) != nombre or "/" in nombre or "\\" in nombre:
            continue
        if os.path.splitext(nombre)[1].lower() in prioridad and os.path.isfile(os.path.join(carpeta, nombre)):
            existentes.append(nombre)
    if principal in existentes:
        return principal
    for ext in prioridad:
        for nombre in existentes:
            if os.path.splitext(nombre)[1].lower() == ext:
                return nombre
    return None


def leer_geometria(ruta):
    """Saca los trazos de cualquier formato que sepamos leer.
    Devuelve (trazos_en_mm, error). Los trazos ya vienen en milimetros."""
    ext = os.path.splitext(ruta)[1].lower()
    if not os.path.exists(ruta):
        return None, "No encuentro el archivo."
    try:
        if ext == ".dxf":
            trazos, unidades = lector_dxf.leer(ruta)
            esc = lector_dxf.escala_mm(unidades)
            if esc != 1.0:
                trazos = [{"puntos": [(x * esc, y * esc) for x, y in t["puntos"]],
                           "cerrado": t["cerrado"]} for t in trazos]
        elif ext in (".eps", ".ai"):
            trazos, _caja = lector_eps.leer(ruta)
            esc = lector_eps.escala_mm()
            trazos = [{"puntos": [(x * esc, y * esc) for x, y in t["puntos"]],
                       "cerrado": t["cerrado"]} for t in trazos]
        elif ext == ".svg":
            trazos, _tam = lector_svg.leer(ruta)
        elif ext in LIGHTBURN:
            trazos, _aviso = lector_lbrn.leer(ruta)
        elif ext in CERRADOS:
            return None, ("Los archivos %s son formato cerrado de CorelDRAW. "
                          "Solo CorelDRAW puede abrirlos." % ext)
        else:
            if ext in (".dwg",):
                return None, ("Los .dwg son de AutoCAD. Abrelo ahi (o en CorelDRAW) "
                              "y guardalo como DXF o SVG para poder usarlo.")
            if ext in (".plt",):
                return None, ("Los .plt son de plotter de corte. Abrelo en CorelDRAW "
                              "y guardalo como SVG para poder usarlo.")
            return None, "No se leer archivos %s." % (ext or "sin extension")
    except Exception as e:
        return None, "No pude leer el dibujo: %s" % str(e)[:120]

    if not trazos:
        return None, "El archivo no trae un dibujo para mostrar."
    # Menos puntos para dibujar la miniatura con rapidez.
    trazos = lector_dxf.simplificar(trazos, 0.02)
    return trazos, ""


# --------------------------------------------------------------- medidas
def medidas_confiables(ruta):
    """Dimensiones del dibujo en mm, solo con unidades físicas conocidas."""
    import math
    import xml.etree.ElementTree as ET
    ext = os.path.splitext(ruta)[1].lower()
    try:
        if ext == ".svg":
            raiz = ET.parse(ruta).getroot()
            for campo in ("width", "height"):
                largo = lector_svg._largo(raiz.get(campo))
                if not largo or largo[1] not in ("mm", "cm", "in", "pt", "pc"):
                    return None
        elif ext == ".dxf":
            _trazos, unidades = lector_dxf.leer(ruta)
            if not unidades:
                return None
        elif ext not in LIGHTBURN:
            return None
        trazos, error = leer_geometria(ruta)
        if error:
            return None
        x0, y0, x1, y1 = _caja(trazos)
        ancho, alto = x1 - x0, y1 - y0
        if not all(math.isfinite(n) and 0 < n <= 100000 for n in (ancho, alto)):
            return None
        return {"ancho": round(ancho, 2), "alto": round(alto, 2)}
    except (OSError, ValueError, ET.ParseError):
        return None


def _caja(trazos):
    xs = [x for t in trazos for x, _y in t["puntos"]]
    ys = [y for t in trazos for _x, y in t["puntos"]]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------- vista previa dibujada
def dibujar_previa(ruta, destino, lado=520):
    """Dibuja el modelo para usarlo como vista previa cuando no hay foto.

    Sirve para los miles de modelos que vienen sin imagen: al menos se ve
    la forma de las piezas en vez de un cuadro vacio.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    trazos, err = leer_geometria(ruta)
    if err or not trazos:
        return None
    x0, y0, x1, y1 = _caja(trazos)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    esc = (lado - 24) / max(w, h)
    W, H = int(w * esc) + 24, int(h * esc) + 24
    if W < 8 or H < 8 or W > 4000 or H > 4000:
        return None
    img = Image.new("RGB", (W, H), "white")
    dib = ImageDraw.Draw(img)
    for t in trazos:
        pts = [(12 + (x - x0) * esc, H - 12 - (y - y0) * esc) for x, y in t["puntos"]]
        if t["cerrado"] and len(pts) > 2:
            pts = pts + [pts[0]]
        if len(pts) >= 2:
            dib.line(pts, fill=(20, 20, 20), width=1)
    img.save(destino, "JPEG", quality=86)
    return destino
