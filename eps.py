# -*- coding: utf-8 -*-
"""Lee un EPS (PostScript encapsulado) y saca su geometria.

El 80% de los EPS de la biblioteca los hizo Adobe Illustrator 3.2, que
escribe los trazos en texto plano con operadores cortos:
    x y m            empezar un trazo
    x y L  /  l      linea hasta ahi
    x1 y1 x2 y2 x3 y3 C   curva bezier
    x1 y1 x2 y2 v / y     curvas abreviadas
    h / H            cerrar el trazo
    S s f F b B N n  terminar el trazo (pintar o no)
Tambien entiende el estilo mas moderno (cairo, CorelDRAW) con 'm/l/c/re'
y las transformaciones 'cm' dentro de q/Q.

Las medidas de PostScript son puntos (1/72 de pulgada); aca se devuelven
en milimetros para que calcen con el resto de la app.
"""
import math
import re

PT_A_MM = 25.4 / 72.0


def _curva(p0, p1, p2, p3, pasos=12):
    """Una bezier cubica convertida en segmentos."""
    pts = []
    for i in range(1, pasos + 1):
        t = i / pasos
        u = 1 - t
        pts.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                    u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))
    return pts


def _aplicar(m, x, y):
    """Aplica una matriz [a b c d e f] a un punto."""
    a, b, c, d, e, f = m
    return (a*x + c*y + e, b*x + d*y + f)


def _multiplicar(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + b1*c2, a1*b2 + b1*d2,
            c1*a2 + d1*c2, c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2)


def leer(ruta):
    """Devuelve (trazos, escala_a_mm). Los trazos vienen en puntos PostScript."""
    with open(ruta, "rb") as f:
        crudo = f.read()

    # Un EPS puede traer una vista previa binaria pegada adelante (cabecera EPSF
    # de 30 bytes). En ese caso la parte PostScript viene indicada ahi.
    if crudo[:4] == b"\xc5\xd0\xd3\xc6":
        ini = int.from_bytes(crudo[4:8], "little")
        largo = int.from_bytes(crudo[8:12], "little")
        crudo = crudo[ini:ini + largo]

    texto = crudo.decode("latin-1", "replace")

    # cortar la parte binaria de las vistas previas incrustadas
    texto = re.split(r'%%BeginPreview|%AI9_PrivateDataBegin|%%BeginBinary', texto)[0]

    trazos = []
    actual = []
    pos = (0.0, 0.0)
    inicio = (0.0, 0.0)
    matriz = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    pila = []
    nums = []

    def guardar(cerrado):
        if len(actual) >= 2:
            trazos.append({"puntos": list(actual), "cerrado": cerrado})

    # tokenizar: numeros y palabras
    for tok in re.findall(r'-?\d*\.?\d+(?:[eE][-+]?\d+)?|[A-Za-z]{1,3}|[\[\]]', texto):
        c = tok[0]
        if c == "-" or c == "." or c.isdigit():
            try:
                nums.append(float(tok))
            except ValueError:
                pass
            if len(nums) > 8:
                del nums[:-8]
            continue

        op = tok
        try:
            if op == "m" and len(nums) >= 2:
                guardar(False)
                actual = []
                pos = inicio = _aplicar(matriz, nums[-2], nums[-1])
                actual.append(pos)
            elif op in ("L", "l") and len(nums) >= 2:
                pos = _aplicar(matriz, nums[-2], nums[-1])
                actual.append(pos)
            elif op in ("C", "c") and len(nums) >= 6:
                p1 = _aplicar(matriz, nums[-6], nums[-5])
                p2 = _aplicar(matriz, nums[-4], nums[-3])
                p3 = _aplicar(matriz, nums[-2], nums[-1])
                actual += _curva(pos, p1, p2, p3)
                pos = p3
            elif op in ("v", "V") and len(nums) >= 4:
                p2 = _aplicar(matriz, nums[-4], nums[-3])
                p3 = _aplicar(matriz, nums[-2], nums[-1])
                actual += _curva(pos, pos, p2, p3)
                pos = p3
            elif op in ("y", "Y") and len(nums) >= 4:
                p1 = _aplicar(matriz, nums[-4], nums[-3])
                p3 = _aplicar(matriz, nums[-2], nums[-1])
                actual += _curva(pos, p1, p3, p3)
                pos = p3
            elif op == "re" and len(nums) >= 4:
                x, y, w, h = nums[-4], nums[-3], nums[-2], nums[-1]
                esq = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
                guardar(False)
                actual = [_aplicar(matriz, a, b) for a, b in esq]
                guardar(True)
                actual = []
            elif op in ("h", "H"):
                if actual:
                    guardar(True)
                    actual = []
                    pos = inicio
            elif op in ("S", "s", "f", "F", "B", "b", "N", "n"):
                # terminan el trazo. Las minusculas de AI cierran la figura.
                if actual:
                    guardar(op in ("s", "b", "f", "F"))
                    actual = []
            elif op == "cm" and len(nums) >= 6:
                matriz = _multiplicar(tuple(nums[-6:]), matriz)
            elif op == "q":
                pila.append(matriz)
            elif op == "Q":
                if pila:
                    matriz = pila.pop()
        except Exception:
            pass
        nums = []

    guardar(False)

    # el %%BoundingBox dice el tamano en puntos; sirve para revisar
    caja = None
    mb = re.search(r'%%BoundingBox:\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', texto)
    if mb:
        caja = tuple(float(mb.group(i)) for i in range(1, 5))

    trazos = [t for t in trazos if len(t["puntos"]) >= 2]
    return trazos, caja


def escala_mm():
    return PT_A_MM
