# -*- coding: utf-8 -*-
"""Abre el selector de carpetas de Windows y escribe la ruta elegida.

Imprime la ruta en la salida estándar. Si el usuario cancela, no imprime nada
y devuelve 1. Los mensajes de error van a la salida de errores.
"""
import os, sys


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        sys.stderr.write("tkinter no disponible: %s" % e)
        return 2

    try:
        root = tk.Tk()
        root.withdraw()
        # traer el diálogo al frente (si no, queda detrás del navegador)
        root.attributes("-topmost", True)
        root.update()
        root.lift()
        try:
            root.focus_force()
        except Exception:
            pass

        inicial = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
        ruta = filedialog.askdirectory(
            title="Elige la carpeta donde tienes tus modelos",
            initialdir=inicial, parent=root, mustexist=True)
        root.destroy()
    except Exception as e:
        sys.stderr.write("no se pudo abrir la ventana: %s" % e)
        return 2

    if not ruta:
        sys.stderr.write("cancelado")
        return 1
    sys.stdout.write(os.path.normpath(ruta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
