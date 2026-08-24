# -*- coding: utf-8 -*-
"""Lee un DXF de texto y devuelve la geometria en milimetros.

Se escribio a mano a proposito: la PC del papa no tiene Inkscape ni nada
instalado, y el 35% de sus modelos son DXF. Un lector propio evita
depender de que instale programas.

Devuelve una lista de trazos. Cada trazo es {"puntos": [(x, y), ...],
"cerrado": bool} ya aplanado (los arcos y curvas vienen convertidos en
segmentos), que es lo que necesitan tanto el SVG como LightBurn.
"""
import math


def _pares(texto):
    """El DXF viene como pares: una linea con el codigo, otra con el valor."""
    lineas = texto.splitlines()
    i = 0
    n = len(lineas)
    while i + 1 < n:
        cod = lineas[i].strip()
        val = lineas[i + 1].strip()
        i += 2
        if not cod.lstrip("-").isdigit():
            i -= 1          # desalineado: avanzamos de a uno hasta recuperar
            continue
        yield int(cod), val


def _arco(cx, cy, r, a1, a2, paso=6.0):
    """Un arco convertido en segmentos. `paso` son grados por segmento."""
    if a2 < a1:
        a2 += 360.0
    n = max(2, int(math.ceil(abs(a2 - a1) / paso)))
    return [(cx + r * math.cos(math.radians(a1 + (a2 - a1) * k / n)),
             cy + r * math.sin(math.radians(a1 + (a2 - a1) * k / n)))
            for k in range(n + 1)]


def _bulge(p1, p2, b, paso=6.0):
    """En una polilinea, un 'bulge' convierte un tramo recto en arco."""
    if abs(b) < 1e-9:
        return [p2]
    x1, y1 = p1
    x2, y2 = p2
    cuerda = math.hypot(x2 - x1, y2 - y1)
    if cuerda < 1e-12:
        return [p2]
    theta = 4.0 * math.atan(b)
    seno = math.sin(abs(theta) / 2.0)
    if seno < 1e-12:
        return [p2]
    r = cuerda / (2.0 * seno)
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    d = math.sqrt(max(0.0, r * r - (cuerda / 2.0) ** 2))
    ux, uy = (x2 - x1) / cuerda, (y2 - y1) / cuerda
    signo = 1.0 if theta > 0 else -1.0
    cx, cy = mx - signo * d * uy, my + signo * d * ux
    a1 = math.degrees(math.atan2(y1 - cy, x1 - cx))
    a2 = math.degrees(math.atan2(y2 - cy, x2 - cx))
    if theta > 0:
        if a2 < a1:
            a2 += 360.0
    else:
        if a2 > a1:
            a2 -= 360.0
    n = max(2, int(math.ceil(abs(a2 - a1) / paso)))
    return [(cx + r * math.cos(math.radians(a1 + (a2 - a1) * k / n)),
             cy + r * math.sin(math.radians(a1 + (a2 - a1) * k / n)))
            for k in range(1, n + 1)]


def _bspline(ctrl, grado=3, pasos=None):
    """Aplana una SPLINE con sus puntos de control (De Boor).
    Si algo no calza, devuelve los puntos de control como polilinea:
    para cortar sirve igual y nunca se pierde la forma general."""
    n = len(ctrl)
    if n < 2:
        return list(ctrl)
    grado = max(1, min(int(grado or 3), n - 1))
    m = n + grado + 1
    interiores = m - 2 * (grado + 1)
    if interiores < 0:
        return list(ctrl)
    nudos = ([0.0] * (grado + 1)
             + [float(k + 1) for k in range(interiores)]
             + [float(interiores + 1)] * (grado + 1))
    if len(nudos) != m:
        return list(ctrl)

    def punto(t):
        k = grado
        while k < n - 1 and t >= nudos[k + 1]:
            k += 1
        d = [list(ctrl[j]) for j in range(k - grado, k + 1)]
        for r in range(1, grado + 1):
            for j in range(grado, r - 1, -1):
                i = k - grado + j
                den = nudos[i + grado - r + 1] - nudos[i]
                a = 0.0 if abs(den) < 1e-12 else (t - nudos[i]) / den
                d[j][0] = (1 - a) * d[j - 1][0] + a * d[j][0]
                d[j][1] = (1 - a) * d[j - 1][1] + a * d[j][1]
        return (d[grado][0], d[grado][1])

    total = pasos or max(24, min(400, n * 10))
    t0, t1 = nudos[grado], nudos[n]
    if t1 <= t0:
        return list(ctrl)
    try:
        return [punto(t0 + (t1 - t0) * i / total) for i in range(total + 1)]
    except Exception:
        return list(ctrl)


def leer(ruta):
    """Devuelve (trazos, unidades) leyendo un DXF de texto."""
    with open(ruta, encoding="utf-8", errors="replace") as f:
        texto = f.read()

    trazos = []
    unidades = 4                 # 4 = milimetros
    ent = None
    d = {}
    vertices = []
    ctrl = []
    esperando_insunits = False

    def cerrar():
        if not ent:
            return
        try:
            if ent == "LINE":
                trazos.append({"puntos": [(d.get(10, 0.0), d.get(20, 0.0)),
                                          (d.get(11, 0.0), d.get(21, 0.0))],
                               "cerrado": False})
            elif ent == "CIRCLE":
                trazos.append({"puntos": _arco(d.get(10, 0.0), d.get(20, 0.0),
                                               d.get(40, 0.0), 0.0, 360.0),
                               "cerrado": True})
            elif ent == "ARC":
                trazos.append({"puntos": _arco(d.get(10, 0.0), d.get(20, 0.0), d.get(40, 0.0),
                                               d.get(50, 0.0), d.get(51, 0.0)),
                               "cerrado": False})
            elif ent == "ELLIPSE":
                cx, cy = d.get(10, 0.0), d.get(20, 0.0)
                mx, my = d.get(11, 0.0), d.get(21, 0.0)
                rel = d.get(40, 1.0)
                a_ini, a_fin = d.get(41, 0.0), d.get(42, 2 * math.pi)
                mayor = math.hypot(mx, my)
                menor = mayor * rel
                rot = math.atan2(my, mx)
                n = 72
                pts = []
                for k in range(n + 1):
                    t = a_ini + (a_fin - a_ini) * k / n
                    x, y = mayor * math.cos(t), menor * math.sin(t)
                    pts.append((cx + x * math.cos(rot) - y * math.sin(rot),
                                cy + x * math.sin(rot) + y * math.cos(rot)))
                trazos.append({"puntos": pts,
                               "cerrado": abs(a_fin - a_ini) >= 2 * math.pi - 1e-6})
            elif ent == "LWPOLYLINE":
                pts = d.get("_pts", [])
                bul = d.get("_bulges", {})
                if len(pts) >= 2:
                    cerrado = bool(int(d.get(70, 0)) & 1)
                    salida = [pts[0]]
                    tramos = list(range(len(pts) - 1)) + ([len(pts) - 1] if cerrado else [])
                    for i in tramos:
                        j = (i + 1) % len(pts)
                        salida += _bulge(pts[i], pts[j], bul.get(i, 0.0))
                    trazos.append({"puntos": salida, "cerrado": cerrado})
            elif ent == "POLYLINE":
                if len(vertices) >= 2:
                    cerrado = bool(int(d.get(70, 0)) & 1)
                    salida = [vertices[0][0]]
                    tramos = list(range(len(vertices) - 1)) + ([len(vertices) - 1] if cerrado else [])
                    for i in tramos:
                        j = (i + 1) % len(vertices)
                        salida += _bulge(vertices[i][0], vertices[j][0], vertices[i][1])
                    trazos.append({"puntos": salida, "cerrado": cerrado})
            elif ent == "SPLINE":
                if len(ctrl) >= 2:
                    trazos.append({"puntos": _bspline(ctrl, int(d.get(71, 3) or 3)),
                                   "cerrado": bool(int(d.get(70, 0)) & 1)})
        except Exception:
            pass          # una entidad rara no puede botar el archivo entero

    for cod, val in _pares(texto):
        if cod == 9:
            esperando_insunits = (val == "$INSUNITS")
            continue
        if esperando_insunits and cod == 70:
            try:
                unidades = int(val)
            except ValueError:
                pass
            esperando_insunits = False
            continue

        if cod == 0:
            if val == "VERTEX" and ent == "POLYLINE":
                vertices.append([(0.0, 0.0), 0.0])
                continue
            if val in ("SEQEND", "SECTION"):
                continue
            cerrar()
            ent = val if val not in ("ENDSEC", "EOF") else None
            if val == "POLYLINE":
                vertices = []
            if val == "SPLINE":
                ctrl = []
            d = {}
            continue

        if ent is None:
            continue

        try:
            num = float(val)
        except ValueError:
            num = None

        if ent == "POLYLINE" and vertices:
            if cod == 10 and num is not None:
                vertices[-1][0] = (num, vertices[-1][0][1]); continue
            if cod == 20 and num is not None:
                vertices[-1][0] = (vertices[-1][0][0], num); continue
            if cod == 42 and num is not None:
                vertices[-1][1] = num; continue

        if ent == "LWPOLYLINE":
            if cod == 10 and num is not None:
                d.setdefault("_pts", []).append((num, 0.0)); continue
            if cod == 20 and num is not None and d.get("_pts"):
                x, _y = d["_pts"][-1]
                d["_pts"][-1] = (x, num); continue
            if cod == 42 and num is not None and d.get("_pts"):
                d.setdefault("_bulges", {})[len(d["_pts"]) - 1] = num; continue

        if ent == "SPLINE":
            if cod == 10 and num is not None:
                ctrl.append((num, 0.0)); continue
            if cod == 20 and num is not None and ctrl:
                ctrl[-1] = (ctrl[-1][0], num); continue

        if num is not None and cod < 100:
            d[cod] = num

    cerrar()
    return [t for t in trazos if len(t["puntos"]) >= 2], unidades


# cuanto mide 1 unidad del dibujo, en milimetros
MM_POR_UNIDAD = {0: 1.0, 1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0,
                 6: 1000.0, 8: 2.54e-5, 9: 0.0254, 10: 914.4, 11: 1e-7,
                 12: 1e-6, 13: 1e-3, 14: 100.0, 15: 10000.0}


def escala_mm(unidades):
    return MM_POR_UNIDAD.get(unidades, 1.0)


def simplificar(trazos, tolerancia=0.02):
    """Saca puntos que no cambian la forma (Douglas-Peucker).

    La tolerancia va en unidades del dibujo. 0.02 mm es cinco veces mas fino
    que el ancho del haz del laser, asi que el corte sale igual pero el
    archivo queda mucho mas liviano y LightBurn lo abre rapido.
    """
    def dp(pts, tol):
        if len(pts) < 3:
            return pts
        # el punto mas lejos de la recta entre el primero y el ultimo
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        dx, dy = x1 - x0, y1 - y0
        largo = math.hypot(dx, dy)
        peor, idx = -1.0, 0
        for i in range(1, len(pts) - 1):
            x, y = pts[i]
            if largo < 1e-12:
                d = math.hypot(x - x0, y - y0)
            else:
                d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / largo
            if d > peor:
                peor, idx = d, i
        if peor <= tol:
            return [pts[0], pts[-1]]
        return dp(pts[:idx + 1], tol)[:-1] + dp(pts[idx:], tol)

    import sys as _sys
    limite = _sys.getrecursionlimit()
    _sys.setrecursionlimit(max(limite, 20000))
    try:
        salida = []
        for t in trazos:
            pts = t["puntos"]
            if len(pts) > 2:
                try:
                    pts = dp(pts, tolerancia)
                except RecursionError:
                    pass          # si es gigante, se deja tal cual
            if len(pts) >= 2:
                salida.append({"puntos": pts, "cerrado": t["cerrado"]})
        return salida
    finally:
        _sys.setrecursionlimit(limite)
