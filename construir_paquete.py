# -*- coding: utf-8 -*-
"""
construir_paquete.py — arma el ZIP para llevar la Biblioteca a otro PC.

Copia SOLO lo necesario para que funcione allá:
  app.py  db.py  indexar.py  ui.html  los .bat  LEEME.txt

NO incluye (son de este PC):
  config.json      -> la ruta de los modelos se elige allá la primera vez
  biblioteca.json  -> se genera allá al indexar
  biblioteca.db    -> los datos (favoritos, clientes, ventas) parten limpios
  .venv / .miniaturas / archivos de prueba

Uso:   python construir_paquete.py  [carpeta_de_salida]
Salida: <carpeta>/Biblioteca-Laser.zip   (por defecto en el Escritorio)
"""
import os, shutil, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
NOMBRE = "Biblioteca-Laser"

INCLUIR = ["app.py", "db.py", "indexar.py", "categorias.py", "actualizar.py",
           "elegir_carpeta.py", "ui.html", "lanzador.py", "migrar.py",
           "crear_acceso.py", "formatos.py", "dxf.py", "eps.py", "svg.py",
           "lbrn.py", "icono.ico",
           "INSTALAR.bat",
           "INICIAR Biblioteca.bat", "Actualizar modelos.bat",
           "Cambiar carpeta de modelos.bat", "Buscar actualizaciones.bat",
           "SOLUCIONAR-PROBLEMAS.bat", "LEEME.txt", "EMPEZAR AQUI.txt"]


def build(salida):
    stage_padre = os.path.join(BASE, "_paquete")
    stage = os.path.join(stage_padre, NOMBRE)
    if os.path.exists(stage_padre):
        shutil.rmtree(stage_padre)
    os.makedirs(stage)

    # la guia corta va con un nombre bien visible
    guia = os.path.join(BASE, "empezar_aqui.txt")
    if os.path.exists(guia):
        shutil.copy2(guia, os.path.join(BASE, "EMPEZAR AQUI.txt"))

    faltan = []
    for f in INCLUIR:
        origen = os.path.join(BASE, f)
        if os.path.exists(origen):
            shutil.copy2(origen, os.path.join(stage, f))
        else:
            faltan.append(f)
    if faltan:
        print("  aviso: no encontre ->", ", ".join(faltan))

    os.makedirs(salida, exist_ok=True)
    destino_base = os.path.join(salida, NOMBRE)
    zip_final = destino_base + ".zip"
    if os.path.exists(zip_final):
        os.remove(zip_final)
    archivo = shutil.make_archive(destino_base, "zip", root_dir=stage_padre, base_dir=NOMBRE)
    shutil.rmtree(stage_padre)
    return archivo


def main():
    escritorio = os.path.join(os.path.expanduser("~"), "Desktop")
    salida = sys.argv[1] if len(sys.argv) > 1 else (escritorio if os.path.isdir(escritorio) else BASE)
    print("Armando el paquete para llevar a otro PC...")
    a = build(salida)
    mb = round(os.path.getsize(a) / 1048576, 2)
    print(f"LISTO: {a}  ({mb} MB)")
    print()
    print("Como usarlo en el otro PC:")
    print("  1. Copia el ZIP (pendrive, WhatsApp, Drive, lo que sea).")
    print("  2. Descomprimelo, por ejemplo en el Escritorio.")
    print("  3. Doble clic en 'INSTALAR.bat'  (una sola vez).")
    print("  4. Queda un icono 'Biblioteca Laser' en el Escritorio: con ese se abre.")


if __name__ == "__main__":
    main()
