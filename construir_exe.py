# -*- coding: utf-8 -*-
"""Arma el programa listo para la PC del papa: un .exe de doble clic.

Deja una carpeta asi:

    Biblioteca Laser/
        Biblioteca Laser.exe     <- doble clic aca
        app.py  db.py  ui.html   <- el codigo, ACTUALIZABLE
        _internal/               <- Python y las librerias (no tocar)

El codigo de la app queda AFUERA del .exe a proposito: asi las
actualizaciones por internet siguen funcionando reemplazando los .py,
sin tener que bajar el programa entero de nuevo.

Uso:   python construir_exe.py  [carpeta_de_salida]
"""
import os
import shutil
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
NOMBRE = "Biblioteca Laser"

# lo que va SUELTO al lado del exe (se puede actualizar)
APP = ["app.py", "db.py", "indexar.py", "categorias.py", "formatos.py",
       "dxf.py", "eps.py", "svg.py", "lbrn.py", "actualizar.py",
       "elegir_carpeta.py", "ui.html", "LEEME.txt", "icono.ico"]


def revisar():
    faltan = [f for f in APP if not os.path.exists(os.path.join(BASE, f))]
    if faltan:
        print("  FALTAN archivos:", ", ".join(faltan))
        return False
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  Falta PyInstaller.  Instalalo con:  pip install pyinstaller")
        return False
    try:
        import webview  # noqa: F401
    except ImportError:
        print("  Falta pywebview.  Instalalo con:  pip install pywebview")
        return False
    return True


def build(salida):
    if not revisar():
        return 1

    trabajo = os.path.join(BASE, "_exe")
    if os.path.exists(trabajo):
        shutil.rmtree(trabajo)

    print("Compilando el programa (esto demora un par de minutos)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--noconsole",                       # sin ventana negra
        "--onedir",
        "--name", NOMBRE,
        "--icon", os.path.join(BASE, "icono.ico"),
        "--distpath", os.path.join(trabajo, "dist"),
        "--workpath", os.path.join(trabajo, "build"),
        "--specpath", trabajo,
        # cosas que no usamos y solo abultan
        "--exclude-module", "matplotlib", "--exclude-module", "numpy",
        "--exclude-module", "scipy", "--exclude-module", "pandas",
        "--exclude-module", "pytest", "--exclude-module", "PyInstaller",
        os.path.join(BASE, "lanzador.py"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("  ERROR al compilar:")
        print("\n".join((r.stdout or "").splitlines()[-15:]))
        print("\n".join((r.stderr or "").splitlines()[-15:]))
        return 1

    destino = os.path.join(trabajo, "dist", NOMBRE)
    if not os.path.isdir(destino):
        print("  ERROR: no se genero la carpeta del programa")
        return 1

    # el codigo de la app va suelto, para poder actualizarlo
    print("Copiando el codigo de la app (queda actualizable)...")
    for f in APP:
        shutil.copy2(os.path.join(BASE, f), os.path.join(destino, f))

    # un acceso directo con nombre claro para el escritorio
    with open(os.path.join(destino, "COMO USARLO.txt"), "w", encoding="utf-8") as f:
        f.write(
            "BIBLIOTECA LASER\r\n"
            "================\r\n\r\n"
            "Doble clic en:   Biblioteca Laser.exe\r\n\r\n"
            "La primera vez te va a pedir la carpeta donde tienes tus modelos.\r\n"
            "Despues abre solo.\r\n\r\n"
            "Ya no necesitas Python ni el navegador: es un programa normal.\r\n\r\n"
            "Si quieres tenerlo a mano: boton derecho sobre 'Biblioteca Laser.exe'\r\n"
            "-> Enviar a -> Escritorio (crear acceso directo)\r\n\r\n"
            "Lo demas de esta carpeta lo necesita el programa. No lo borres.\r\n")

    os.makedirs(salida, exist_ok=True)
    zip_final = os.path.join(salida, "Biblioteca-Laser-programa.zip")
    if os.path.exists(zip_final):
        os.remove(zip_final)

    print("Armando el ZIP...")
    total = 0
    with zipfile.ZipFile(zip_final, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for raiz, _dirs, archivos in os.walk(destino):
            for a in archivos:
                p = os.path.join(raiz, a)
                rel = os.path.relpath(p, os.path.dirname(destino))
                z.write(p, rel)
                total += os.path.getsize(p)

    mb = os.path.getsize(zip_final) / (1024 * 1024)
    print()
    print("LISTO: %s  (%.1f MB comprimido, %.1f MB al descomprimir)"
          % (zip_final, mb, total / (1024 * 1024)))
    print()
    print("Para instalarlo en el PC de tu papa:")
    print("  1. Copiale el ZIP.")
    print("  2. Que lo descomprima donde quiera (por ejemplo el Escritorio).")
    print("  3. Doble clic en 'Biblioteca Laser.exe'.")
    print()
    print("Si ya tenia la version vieja, que copie de la carpeta antigua estos")
    print("dos archivos a la nueva, para no perder sus datos:")
    print("     biblioteca.db      (favoritos, clientes, ventas, precios)")
    print("     config.json        (la carpeta de sus modelos)")
    return 0


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"), "Desktop")
    sys.exit(build(destino))
