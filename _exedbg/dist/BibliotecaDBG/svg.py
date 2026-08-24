# -*- coding: utf-8 -*-
"""Lee un SVG y saca su geometria en milimetros.

Entiende path, rect, circle, ellipse, line, polyline y polygon, con sus
transform y respetando viewBox/width/height para que el tamano salga bien.
Solo stdlib: la PC del papa no tiene nada instalado.
"""
import math
import re
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"
_NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?')
_CMD = re.compile(r'([MmZzLlHhVvCcSsQqTtAa])')

# cuanto mide una unidad en milimetros
UNIDADES = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0,
            "pc": 25.4 / 6.0, "px": 25.4 / 96.0, "": 25.4 / 96.0}


def _largo(txt, por_defecto=None):
    """'210mm' -> (210.0, 'mm')"""
    if not txt:
        return por_defecto
    m = re.match(r'\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*([a-z%]*)', txt.strip())
    if not m:
        return por_defecto
    try:
        return float(m.group(1)), m.group(2)
    except ValueError:
        return por_defecto


def _mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + b1*c2, a1*b2 + b1*d2,
            c1*a2 + d1*c2, c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2)


def _ap(m, x, y):
    a, b, c, d, e, f = m
    return (a*x + c*y + e, b*x + d*y + f)


def _transform(txt):
    """Convierte el atributo transform en una matriz."""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not txt:
        return m
    for nombre, args in re.findall(r'(\w+)\s*\(([^)]*)\)', txt):
        v = [float(x) for x in _NUM.findall(args)]
        if nombre == "matrix" and len(v) >= 6:
            t = tuple(v[:6])
        elif nombre == "translate":
            t = (1, 0, 0, 1, v[0] if v else 0, v[1] if len(v) > 1 else 0)
        elif nombre == "scale":
            sx = v[0] if v else 1
            sy = v[1] if len(v) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif nombre == "rotate" and v:
            a = math.radians(v[0])
            ca, sa = math.cos(a), math.sin(a)
            t = (ca, sa, -sa, ca, 0, 0)
            if len(v) >= 3:
                t = _mul(_mul((1, 0, 0, 1, -v[1], -v[2]), t), (1, 0, 0, 1, v[1], v[2]))
        elif nombre == "skewX" and v:
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif nombre == "skewY" and v:
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(t, m)
    return m


def _bezier3(p0, p1, p2, p3, pasos=14):
    out = []
    for i in range(1, pasos + 1):
        t = i / pasos
        u = 1 - t
        out.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                    u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))
    return out


def _bezier2(p0, p1, p2, pasos=10):
    out = []
    for i in range(1, pasos + 1):
        t = i / pasos
        u = 1 - t
        out.append((u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0],
                    u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1]))
    return out


def _arco(p0, rx, ry, giro, grande, barrido, p1, pasos=24):
    """El comando A de SVG: arco de elipse entre dos puntos."""
    if rx == 0 or ry == 0 or (abs(p0[0]-p1[0]) < 1e-12 and abs(p0[1]-p1[1]) < 1e-12):
        return [p1]
    rx, ry = abs(rx), abs(ry)
    fi = math.radians(giro)
    cf, sf = math.cos(fi), math.sin(fi)
    dx2, dy2 = (p0[0]-p1[0])/2.0, (p0[1]-p1[1])/2.0
    x1 = cf*dx2 + sf*dy2
    y1 = -sf*dx2 + cf*dy2
    # agrandar los radios si no alcanzan
    lam = (x1*x1)/(rx*rx) + (y1*y1)/(ry*ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx*s, ry*s
    num = rx*rx*ry*ry - rx*rx*y1*y1 - ry*ry*x1*x1
    den = rx*rx*y1*y1 + ry*ry*x1*x1
    if den < 1e-12:
        return [p1]
    co = math.sqrt(max(0.0, num/den))
    if grande == barrido:
        co = -co
    cx1 = co * rx * y1 / ry
    cy1 = -co * ry * x1 / rx
    cx = cf*cx1 - sf*cy1 + (p0[0]+p1[0])/2.0
    cy = sf*cx1 + cf*cy1 + (p0[1]+p1[1])/2.0

    def ang(ux, uy, vx, vy):
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        if n < 1e-12:
            return 0.0
        c = max(-1.0, min(1.0, (ux*vx + uy*vy)/n))
        a = math.acos(c)
        return -a if (ux*vy - uy*vx) < 0 else a

    t1 = ang(1, 0, (x1-cx1)/rx, (y1-cy1)/ry)
    dt = ang((x1-cx1)/rx, (y1-cy1)/ry, (-x1-cx1)/rx, (-y1-cy1)/ry)
    if not barrido and dt > 0:
        dt -= 2*math.pi
    elif barrido and dt < 0:
        dt += 2*math.pi

    n = max(2, int(pasos * abs(dt) / (2*math.pi)) + 2)
    out = []
    for i in range(1, n+1):
        t = t1 + dt*i/n
        x = rx*math.cos(t)
        y = ry*math.sin(t)
        out.append((cf*x - sf*y + cx, sf*x + cf*y + cy))
    return out


def _path(d):
    """Convierte el atributo d en una lista de trazos (sin transformar)."""
    trozos = _CMD.split(d)
    trazos = []
    pts = []
    pos = (0.0, 0.0)
    ini = (0.0, 0.0)
    ctrl_prev = None
    cmd = None
    i = 1
    while i < len(trozos):
        cmd = trozos[i]
        args = [float(x) for x in _NUM.findall(trozos[i+1])] if i+1 < len(trozos) else []
        i += 2
        rel = cmd.islower()
        C = cmd.upper()

        if C == "M":
            for k in range(0, len(args) - 1, 2):
                x, y = args[k], args[k+1]
                if rel:
                    x, y = pos[0]+x, pos[1]+y
                if k == 0:
                    if len(pts) >= 2:
                        trazos.append({"puntos": pts, "cerrado": False})
                    pts = [(x, y)]
                    ini = (x, y)
                else:
                    pts.append((x, y))
                pos = (x, y)
            ctrl_prev = None
        elif C == "Z":
            if len(pts) >= 2:
                trazos.append({"puntos": pts, "cerrado": True})
            pts = [ini]
            pos = ini
            ctrl_prev = None
        elif C == "L":
            for k in range(0, len(args) - 1, 2):
                x, y = args[k], args[k+1]
                if rel:
                    x, y = pos[0]+x, pos[1]+y
                pts.append((x, y)); pos = (x, y)
            ctrl_prev = None
        elif C == "H":
            for x in args:
                if rel:
                    x = pos[0]+x
                pts.append((x, pos[1])); pos = (x, pos[1])
            ctrl_prev = None
        elif C == "V":
            for y in args:
                if rel:
                    y = pos[1]+y
                pts.append((pos[0], y)); pos = (pos[0], y)
            ctrl_prev = None
        elif C == "C":
            for k in range(0, len(args) - 5, 6):
                a = args[k:k+6]
                if rel:
                    a = [a[0]+pos[0], a[1]+pos[1], a[2]+pos[0], a[3]+pos[1],
                         a[4]+pos[0], a[5]+pos[1]]
                p1, p2, p3 = (a[0], a[1]), (a[2], a[3]), (a[4], a[5])
                pts += _bezier3(pos, p1, p2, p3)
                ctrl_prev = p2
                pos = p3
        elif C == "S":
            for k in range(0, len(args) - 3, 4):
                a = args[k:k+4]
                if rel:
                    a = [a[0]+pos[0], a[1]+pos[1], a[2]+pos[0], a[3]+pos[1]]
                p1 = (2*pos[0]-ctrl_prev[0], 2*pos[1]-ctrl_prev[1]) if ctrl_prev else pos
                p2, p3 = (a[0], a[1]), (a[2], a[3])
                pts += _bezier3(pos, p1, p2, p3)
                ctrl_prev = p2
                pos = p3
        elif C == "Q":
            for k in range(0, len(args) - 3, 4):
                a = args[k:k+4]
                if rel:
                    a = [a[0]+pos[0], a[1]+pos[1], a[2]+pos[0], a[3]+pos[1]]
                p1, p2 = (a[0], a[1]), (a[2], a[3])
                pts += _bezier2(pos, p1, p2)
                ctrl_prev = p1
                pos = p2
        elif C == "T":
            for k in range(0, len(args) - 1, 2):
                x, y = args[k], args[k+1]
                if rel:
                    x, y = pos[0]+x, pos[1]+y
                p1 = (2*pos[0]-ctrl_prev[0], 2*pos[1]-ctrl_prev[1]) if ctrl_prev else pos
                pts += _bezier2(pos, p1, (x, y))
                ctrl_prev = p1
                pos = (x, y)
        elif C == "A":
            for k in range(0, len(args) - 6, 7):
                a = args[k:k+7]
                x, y = (a[5], a[6])
                if rel:
                    x, y = pos[0]+x, pos[1]+y
                pts += _arco(pos, a[0], a[1], a[2], int(a[3]), int(a[4]), (x, y))
                pos = (x, y)
            ctrl_prev = None

    if len(pts) >= 2:
        trazos.append({"puntos": pts, "cerrado": False})
    return trazos


def _forma(el):
    """Convierte rect/circle/ellipse/line/polyline/polygon en trazos."""
    tag = el.tag.replace(NS, "")
    g = lambda k, d=0.0: float(el.get(k, d) or d)
    try:
        if tag == "rect":
            x, y, w, h = g("x"), g("y"), g("width"), g("height")
            if w <= 0 or h <= 0:
                return []
            return [{"puntos": [(x, y), (x+w, y), (x+w, y+h), (x, y+h)], "cerrado": True}]
        if tag in ("circle", "ellipse"):
            cx, cy = g("cx"), g("cy")
            if tag == "circle":
                rx = ry = g("r")
            else:
                rx, ry = g("rx"), g("ry")
            if rx <= 0 or ry <= 0:
                return []
            n = 48
            return [{"puntos": [(cx + rx*math.cos(2*math.pi*k/n),
                                 cy + ry*math.sin(2*math.pi*k/n)) for k in range(n)],
                     "cerrado": True}]
        if tag == "line":
            return [{"puntos": [(g("x1"), g("y1")), (g("x2"), g("y2"))], "cerrado": False}]
        if tag in ("polyline", "polygon"):
            v = [float(x) for x in _NUM.findall(el.get("points", ""))]
            pts = [(v[k], v[k+1]) for k in range(0, len(v)-1, 2)]
            if len(pts) < 2:
                return []
            return [{"puntos": pts, "cerrado": tag == "polygon"}]
        if tag == "path":
            return _path(el.get("d", ""))
    except Exception:
        pass
    return []


def leer(ruta):
    """Devuelve (trazos_en_mm, (ancho_mm, alto_mm))."""
    arbol = ET.parse(ruta)
    raiz = arbol.getroot()

    # tamano y viewBox para saber a cuanto equivale una unidad
    vb = raiz.get("viewBox")
    caja = [float(x) for x in _NUM.findall(vb)] if vb else None
    w_attr = _largo(raiz.get("width"))
    h_attr = _largo(raiz.get("height"))

    if caja and len(caja) == 4 and w_attr and w_attr[1] != "%":
        # el ancho real dividido por el ancho del viewBox
        esc = (w_attr[0] * UNIDADES.get(w_attr[1], UNIDADES[""])) / max(caja[2], 1e-9)
    elif w_attr and w_attr[1] != "%":
        esc = UNIDADES.get(w_attr[1], UNIDADES[""])
    else:
        esc = UNIDADES[""]          # sin datos: se asume px a 96 dpi

    trazos = []

    def recorrer(el, m):
        m = _mul(_transform(el.get("transform")), m)
        tag = el.tag.replace(NS, "")
        if tag not in ("g", "svg", "defs", "symbol", "use", "clipPath", "mask"):
            for t in _forma(el):
                t["puntos"] = [_ap(m, x, y) for x, y in t["puntos"]]
                trazos.append(t)
        if tag in ("defs", "clipPath", "mask", "symbol"):
            return                   # eso no se dibuja
        for hijo in el:
            recorrer(hijo, m)

    base = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if caja and len(caja) == 4:
        base = (1.0, 0.0, 0.0, 1.0, -caja[0], -caja[1])
    recorrer(raiz, base)

    # a milimetros, y con el eje Y dado vuelta (el SVG crece hacia abajo)
    alto_vb = (caja[3] if caja and len(caja) == 4 else
               (h_attr[0] / esc if h_attr else 0.0))
    salida = []
    for t in trazos:
        pts = [(x * esc, (alto_vb - y) * esc) for x, y in t["puntos"]]
        if len(pts) >= 2:
            salida.append({"puntos": pts, "cerrado": t["cerrado"]})

    if salida:
        xs = [x for t in salida for x, y in t["puntos"]]
        ys = [y for t in salida for x, y in t["puntos"]]
        tam = (max(xs) - min(xs), max(ys) - min(ys))
    else:
        tam = (0.0, 0.0)
    return salida, tam
