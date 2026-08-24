# -*- coding: utf-8 -*-
"""Conversion automatica entre formatos de dibujo.

La idea: el papa aprieta "Abrir en CorelDRAW" y se abre un SVG; aprieta
"Abrir en LightBurn" y se abre un .lbrn. Si el modelo no tiene ese formato,
se genera al vuelo desde lo que si tenga.

Todo se hace con codigo propio (dxf.py, eps.py, svg.py) para no depender de
que el usuario instale nada. Cobertura medida sobre la biblioteca real:
    .svg   99%      .dxf   99%      .eps   85%
Los .cdr son formato cerrado de Corel: esos solo los abre CorelDRAW.

Lo convertido NO se mezcla con los archivos del usuario: va a una carpeta
aparte (_convertidos) dentro de la carpeta de la app.
"""
import hashlib
import os
import time

import dxf as lector_dxf
import eps as lector_eps
import svg as lector_svg
import lbrn as lector_lbrn

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "_convertidos")

# De que formatos sabemos sacar geometria, en orden de preferencia:
# primero los mas fieles y rapidos.
LEIBLES = [".svg", ".dxf", ".eps", ".ai", ".lbrn2", ".lbrn"]
# Formato cerrado: sin CorelDRAW no hay nada que hacer.
CERRADOS = {".cdr", ".cmx"}
# Los que ya son de LightBurn.
LIGHTBURN = {".lbrn", ".lbrn2"}


def _huella(ruta):
    """Identifica una version concreta de un archivo (ruta + tamano + fecha)."""
    try:
        st = os.stat(ruta)
        crudo = "%s|%d|%d" % (os.path.abspath(ruta).lower(), st.st_size, int(st.st_mtime))
    except OSError:
        crudo = os.path.abspath(ruta).lower()
    return hashlib.md5(crudo.encode("utf-8")).hexdigest()[:16]


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
        return None, "El archivo no trae dibujo que se pueda convertir."
    # sacar los puntos de mas: el archivo queda liviano y el corte igual
    trazos = lector_dxf.simplificar(trazos, 0.02)
    return trazos, ""


# --------------------------------------------------------------- escribir
def _caja(trazos):
    xs = [x for t in trazos for x, _y in t["puntos"]]
    ys = [y for t in trazos for _x, y in t["puntos"]]
    return min(xs), min(ys), max(xs), max(ys)


def escribir_svg(trazos, destino):
    x0, y0, x1, y1 = _caja(trazos)
    w = max(x1 - x0, 0.001)
    h = max(y1 - y0, 0.001)
    partes = []
    for t in trazos:
        d = []
        for i, (x, y) in enumerate(t["puntos"]):
            # el SVG crece hacia abajo, asi que se da vuelta la Y
            d.append(("M" if i == 0 else "L") + "%.4f %.4f" % (x - x0, h - (y - y0)))
        if t["cerrado"]:
            d.append("Z")
        partes.append('<path d="%s"/>' % "".join(d))
    texto = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"\n'
        '     width="%.4fmm" height="%.4fmm" viewBox="0 0 %.4f %.4f">\n'
        '  <g fill="none" stroke="#000000" stroke-width="0.1">\n'
        '    %s\n'
        '  </g>\n'
        '</svg>\n' % (w, h, w, h, "\n    ".join(partes)))
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    return destino


_LB_CABECERA = '''<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="1.6.03" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="False">
    <VariableText>
        <Start Value="0"/>
        <End Value="999"/>
        <Current Value="0"/>
        <Increment Value="1"/>
        <AutoAdvance Value="0"/>
    </VariableText>
    <CutSetting type="Cut">
        <index Value="0"/>
        <name Value="Corte"/>
        <maxPower Value="20"/>
        <speed Value="20"/>
        <priority Value="0"/>
    </CutSetting>
'''

_LB_PIE = '''    <Notes ShowOnLoad="0" Notes="Convertido por la Biblioteca Laser"/>
</LightBurnProject>
'''


def escribir_lbrn(trazos, destino):
    """Escribe un .lbrn2. LightBurn trabaja en mm con la Y hacia arriba,
    igual que como vienen los trazos, asi que no hay que dar vuelta nada."""
    x0, y0, _x1, _y1 = _caja(trazos)
    cuerpo = []
    n = 0
    for t in trazos:
        pts = t["puntos"]
        # LightBurn no repite el punto final: cierra con LineClosed
        if (t["cerrado"] and len(pts) > 2
                and abs(pts[0][0] - pts[-1][0]) < 1e-9
                and abs(pts[0][1] - pts[-1][1]) < 1e-9):
            pts = pts[:-1]
        if len(pts) < 2:
            continue
        verts = "".join("V%.4f %.4f" % (x - x0, y - y0) for x, y in pts)
        prim = ("LineClosed" if t["cerrado"]
                else "".join("L%d %d" % (k, k + 1) for k in range(len(pts) - 1)))
        cuerpo.append(
            '    <Shape Type="Path" CutIndex="0" VertID="%d">\n'
            '        <XForm>1 0 0 1 0 0</XForm>\n'
            '        <VertList>%s</VertList>\n'
            '        <PrimList>%s</PrimList>\n'
            '    </Shape>\n' % (n, verts, prim))
        n += 1
    if not cuerpo:
        return None
    with open(destino, "w", encoding="utf-8") as f:
        f.write(_LB_CABECERA + "".join(cuerpo) + _LB_PIE)
    return destino


# ----------------------------------------------------------------- elegir
def mejor_origen(archivos, carpeta, destino):
    """De todos los archivos del modelo, cual conviene usar para llegar a
    `destino` ('svg' o 'lbrn'). Devuelve (nombre, ya_sirve)."""
    hay = {}
    for a in archivos:
        hay.setdefault(os.path.splitext(a)[1].lower(), []).append(a)

    if destino == "lbrn":
        for ext in (".lbrn2", ".lbrn"):
            if hay.get(ext):
                return hay[ext][0], True
    if destino == "svg" and hay.get(".svg"):
        return hay[".svg"][0], True

    for ext in LEIBLES:
        if hay.get(ext):
            return hay[ext][0], False
    for ext in CERRADOS:
        if hay.get(ext):
            return hay[ext][0], False
    return (archivos[0] if archivos else None), False


def preparar(carpeta, archivos, destino):
    """Deja listo un archivo del formato `destino` y devuelve su ruta.

    Si el modelo ya lo tiene, se usa ese. Si no, se convierte y se guarda en
    la carpeta de convertidos (nunca dentro de las carpetas del usuario).
    Devuelve (ruta, mensaje_de_error, se_convirtio).
    """
    if destino not in ("svg", "lbrn"):
        return None, "formato no valido", False
    nombre, ya_sirve = mejor_origen(archivos, carpeta, destino)
    if not nombre:
        return None, "Este modelo no tiene archivos para abrir.", False

    origen = os.path.join(carpeta, nombre)
    if ya_sirve:
        return origen, "", False

    ext = os.path.splitext(nombre)[1].lower()
    if ext in CERRADOS:
        return None, ("Este modelo solo viene en %s, que es formato cerrado de "
                      "CorelDRAW. Abrelo en CorelDRAW y guardalo como SVG para "
                      "poder usarlo en LightBurn." % ext), False

    os.makedirs(CACHE, exist_ok=True)
    ext_final = ".lbrn2" if destino == "lbrn" else ".svg"
    base = os.path.splitext(os.path.basename(nombre))[0]
    salida = os.path.join(CACHE, "%s_%s%s" % (_huella(origen), base, ext_final))

    # si ya lo habiamos convertido antes, se reusa
    if os.path.exists(salida) and os.path.getsize(salida) > 0:
        return salida, "", False

    trazos, err = leer_geometria(origen)
    if err:
        return None, err, False
    try:
        if destino == "lbrn":
            r = escribir_lbrn(trazos, salida)
        else:
            r = escribir_svg(trazos, salida)
    except Exception as e:
        return None, "No pude escribir el archivo: %s" % str(e)[:100], False
    if not r:
        return None, "El dibujo quedo vacio al convertirlo.", False
    return salida, "", True


def limpiar_cache(dias=30, max_mb=500):
    """Borra convertidos viejos. Son archivos que se pueden rehacer solos."""
    if not os.path.isdir(CACHE):
        return 0
    ahora = time.time()
    archivos = []
    for n in os.listdir(CACHE):
        p = os.path.join(CACHE, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        archivos.append((st.st_atime, st.st_size, p))
    borrados = 0
    # primero los muy viejos
    for atime, _tam, p in archivos:
        if ahora - atime > dias * 86400:
            try:
                os.remove(p); borrados += 1
            except OSError:
                pass
    # y si aun pesa mucho, los menos usados
    archivos = [(a, t, p) for a, t, p in archivos if os.path.exists(p)]
    total = sum(t for _a, t, _p in archivos)
    archivos.sort()
    while total > max_mb * 1024 * 1024 and archivos:
        _a, tam, p = archivos.pop(0)
        try:
            os.remove(p); total -= tam; borrados += 1
        except OSError:
            pass
    return borrados


def tamano_cache():
    if not os.path.isdir(CACHE):
        return 0, 0
    n = tam = 0
    for f in os.listdir(CACHE):
        try:
            tam += os.path.getsize(os.path.join(CACHE, f)); n += 1
        except OSError:
            pass
    return n, tam


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
