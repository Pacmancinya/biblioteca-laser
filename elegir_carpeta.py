# -*- coding: utf-8 -*-
"""Abre el selector de Windows y escribe la ruta elegida.

Uso:
    elegir_carpeta.py [carpeta_inicial]          -> elegir una carpeta
    elegir_carpeta.py --exe "Nombre" [inicial]   -> elegir un programa (.exe)

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

        args = sys.argv[1:]
        if args and args[0] == "--exe":
            nombre = args[1] if len(args) > 1 else "el programa"
            inicial = args[2] if len(args) > 2 and os.path.isdir(args[2]) \
                else os.environ.get("ProgramFiles", r"C:\Program Files")
            ruta = filedialog.askopenfilename(
                title="Busca el programa %s (archivo .exe)" % nombre,
                initialdir=inicial, parent=root,
                filetypes=[("Programas", "*.exe"), ("Todos los archivos", "*.*")])
        else:
            inicial = args[0] if args and os.path.isdir(args[0]) else None
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
