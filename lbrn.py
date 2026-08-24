# -*- coding: utf-8 -*-
"""Lee archivos de LightBurn (.lbrn / .lbrn2) y saca su geometria.

Sirve para el camino de vuelta: un modelo que solo viene en LightBurn se
puede pasar a SVG para abrirlo en CorelDRAW.

El formato es XML. Cada figura es un <Shape> con:
  <XForm>a b c d e f</XForm>   la matriz que la ubica
  <VertList>V x yc0x..c0y..c1x..c1y..V...</VertList>   los vertices
  <PrimList>LineClosed</PrimList>  o  "L0 1L1 2"  o  "B0 1B1 2"
Los Group traen Children adentro, con su propia XForm que se acumula.
Las medidas ya vienen en milimetros.
"""
import math
import re
import xml.etree.ElementTree as ET

_VERT = re.compile(
    r'V(-?[\d.eE+]+) (-?[\d.eE+]+)'
    r'(?:c0x(-?[\d.eE+]+))?(?:c0y(-?[\d.eE+]+))?'
    r'(?:c1x(-?[\d.eE+]+))?(?:c1y(-?[\d.eE+]+))?')
_PRIM = re.compile(r'([LBL])(\d+) (\d+)')


def _num(s, d=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return d


def _mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + b1*c2, a1*b2 + b1*d2,
            c1*a2 + d1*c2, c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2)


def _ap(m, x, y):
    a, b, c, d, e, f = m
    return (a*x + c*y + e, b*x + d*y + f)


def _xform(el):
    t = (el.findtext("XForm") or "").split()
    if len(t) >= 6:
        try:
            return tuple(float(v) for v in t[:6])
        except ValueError:
            pass
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _bezier(p0, c0, c1, p1, pasos=10):
    out = []
    for i in range(1, pasos + 1):
        t = i / pasos
        u = 1 - t
        out.append((u*u*u*p0[0] + 3*u*u*t*c0[0] + 3*u*t*t*c1[0] + t*t*t*p1[0],
                    u*u*u*p0[1] + 3*u*u*t*c0[1] + 3*u*t*t*c1[1] + t*t*t*p1[1]))
    return out


def _vertices(texto):
    """Devuelve [(punto, control_saliente, control_entrante), ...]."""
    salida = []
    for m in _VERT.finditer(texto or ""):
        x, y = _num(m.group(1)), _num(m.group(2))
        # cuando no hay curva, LightBurn escribe marcadores sin sentido
        # geometrico ("c0x1c1x1"): en ese caso el control es el punto mismo
        c0 = (_num(m.group(3), x), _num(m.group(4), y)) if m.group(4) else (x, y)
        c1 = (_num(m.group(5), x), _num(m.group(6), y)) if m.group(6) else (x, y)
        salida.append(((x, y), c0, c1))
    return salida


def _path(shape, m):
    verts = _vertices(shape.findtext("VertList"))
    if len(verts) < 2:
        return []
    prim = (shape.findtext("PrimList") or "").strip()

    if prim.startswith("LineClosed") or not prim:
        pts = [_ap(m, p[0][0], p[0][1]) for p, _c0, _c1 in
               [(v, v[1], v[2]) for v in verts]]
        return [{"puntos": pts, "cerrado": True}]

    # secuencias tipo L0 1L1 2  /  B0 1B1 2
    trazos = []
    actual = []
    ultimo = None
    for tipo, a, b in _PRIM.findall(prim):
        i, j = int(a), int(b)
        if i >= len(verts) or j >= len(verts):
            continue
        pa, ca0, _ca1 = verts[i]
        pb, _cb0, cb1 = verts[j]
        if ultimo != i:
            if len(actual) >= 2:
                trazos.append({"puntos": actual, "cerrado": False})
            actual = [_ap(m, pa[0], pa[1])]
        if tipo == "B":
            for x, y in _bezier(pa, ca0, cb1, pb):
                actual.append(_ap(m, x, y))
        else:
            actual.append(_ap(m, pb[0], pb[1]))
        ultimo = j
    if len(actual) >= 2:
        # si vuelve al principio, es una figura cerrada
        cerrado = (abs(actual[0][0] - actual[-1][0]) < 1e-6
                   and abs(actual[0][1] - actual[-1][1]) < 1e-6)
        trazos.append({"puntos": actual[:-1] if cerrado else actual,
                       "cerrado": cerrado})
    return trazos


def _figura(shape, m):
    tipo = shape.get("Type", "")
    m = _mul(_xform(shape), m)

    if tipo == "Group":
        out = []
        hijos = shape.find("Children")
        for h in (hijos if hijos is not None else []):
            out += _figura(h, m)
        return out

    if tipo == "Path":
        return _path(shape, m)

    if tipo == "Rect":
        w = _num(shape.findtext("W"), 0.0)
        h = _num(shape.findtext("H"), 0.0)
        if w <= 0 or h <= 0:
            return []
        esq = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
        return [{"puntos": [_ap(m, x, y) for x, y in esq], "cerrado": True}]

    if tipo == "Ellipse":
        rx = _num(shape.findtext("Rx"), 0.0)
        ry = _num(shape.findtext("Ry"), 0.0)
        if rx <= 0 or ry <= 0:
            return []
        n = 48
        pts = [(rx*math.cos(2*math.pi*k/n), ry*math.sin(2*math.pi*k/n)) for k in range(n)]
        return [{"puntos": [_ap(m, x, y) for x, y in pts], "cerrado": True}]

    # Text y Bitmap no se pueden convertir a trazos de forma fiel
    return []


def leer(ruta):
    """Devuelve (trazos_en_mm, aviso)."""
    try:
        raiz = ET.parse(ruta).getroot()
    except Exception as e:
        return [], "No pude leer el archivo de LightBurn: %s" % str(e)[:90]

    base = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    trazos = []
    saltados = 0
    for shape in raiz.findall("Shape"):
        t = shape.get("Type", "")
        if t in ("Text", "Bitmap"):
            saltados += 1
            continue
        trazos += _figura(shape, base)

    aviso = ""
    if saltados:
        aviso = ("Este archivo trae %d texto(s) o imagen(es) que no se pueden "
                 "pasar a otro formato; el resto del dibujo si." % saltados)
    return [t for t in trazos if len(t["puntos"]) >= 2], aviso
