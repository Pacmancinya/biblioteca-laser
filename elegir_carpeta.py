# -*- coding: utf-8 -*-
"""Abre el selector de carpetas de Windows y escribe la ruta elegida."""
import os, sys


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return 1
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    ruta = filedialog.askdirectory(title="Elige la carpeta donde tienes tus modelos")
    root.destroy()
    if not ruta:
        return 1
    print(os.path.normpath(ruta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
