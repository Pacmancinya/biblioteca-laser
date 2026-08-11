# -*- coding: utf-8 -*-
"""Conversor de archivos de la Biblioteca Láser.

Qué se puede convertir y con qué:

  Fotos (jpg, png, webp, bmp, gif, tif)
      Se convierten solas, sin instalar nada. Usa Pillow, que ya viene.

  Dibujos vectoriales (svg, pdf, dxf, eps, ps, emf, wmf)
      Necesitan Inkscape (es gratis: inkscape.org). Es el único que hace
      bien estas conversiones. Sin Inkscape la app avisa y no inventa nada.

  LightBurn (lbrn, lbrn2)
      Adentro traen una miniatura PNG: esa sí se saca sin instalar nada.
      El dibujo en sí es formato propio de LightBurn; para pasarlo a otro
      formato hay que abrirlo en LightBurn y exportar desde ahí.

  CorelDRAW (cdr, cmx)
      Formato cerrado de Corel. Solo CorelDRAW puede abrirlo y exportarlo;
      no existe forma confiable de convertirlo sin él.

Ojo con el revés: para llevar un dibujo A LightBurn no hace falta convertir
nada, porque LightBurn importa svg, dxf, ai, pdf y png directamente.
"""
import base64
import io
import os
import re
import subprocess

# Lo que sabemos hacer, agrupado por cómo lo hacemos
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
def convertir(origen, formato, inkscape=None, carpeta_salida=None):
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
