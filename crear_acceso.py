# -*- coding: utf-8 -*-
"""Crea el acceso directo "Biblioteca Laser" con su icono.

Lo deja en el Escritorio y tambien al lado del programa. El acceso apunta
a pythonw.exe (que no abre ventana negra) con lanzador.py.

Se hace asi, y no con un .exe propio, por una razon concreta: Windows 11
trae "Control inteligente de aplicaciones", que BLOQUEA los programas sin
firma digital. Un .exe hecho en casa no arranca. En cambio pythonw.exe
viene firmado por la Python Software Foundation, asi que Windows lo deja
correr sin problemas.
"""
import os
import sys


def carpeta_programa():
    return os.path.dirname(os.path.abspath(__file__))


def pythonw():
    """El Python sin consola. Se prefiere el del entorno de la app."""
    base = carpeta_programa()
    candidatos = [
        os.path.join(base, ".venv", "Scripts", "pythonw.exe"),
        os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
        sys.executable,
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    return sys.executable


def escritorio():
    """Donde esta el Escritorio de verdad (puede estar en OneDrive)."""
    try:
        import ctypes
        from ctypes import wintypes
        CSIDL_DESKTOP = 0
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOP, None, 0, buf)
        if buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception:
        pass
    for n in ("Desktop", "Escritorio"):
        p = os.path.join(os.path.expanduser("~"), n)
        if os.path.isdir(p):
            return p
    return None


def crear(destino):
    """Escribe un .lnk usando COM (lo trae Windows, no hace falta instalar nada)."""
    base = carpeta_programa()
    try:
        import ctypes
        from ctypes import wintypes, POINTER, byref, c_void_p
        import comtypes.client  # noqa: F401
        usar_comtypes = True
    except Exception:
        usar_comtypes = False

    # la via mas simple y confiable: WScript.Shell por PowerShell
    import subprocess
    icono = os.path.join(base, "icono.ico")
    guion = (
        "$s = New-Object -ComObject WScript.Shell; "
        "$a = $s.CreateShortcut(%s); "
        "$a.TargetPath = %s; "
        "$a.Arguments = %s; "
        "$a.WorkingDirectory = %s; "
        "$a.Description = 'Biblioteca Laser - tus modelos para la cortadora'; "
        % (_ps(destino), _ps(pythonw()),
           _ps('"%s"' % os.path.join(base, "lanzador.py")), _ps(base))
    )
    if os.path.exists(icono):
        guion += "$a.IconLocation = %s; " % _ps(icono + ",0")
    guion += "$a.Save()"

    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", guion],
                       capture_output=True, text=True, timeout=120)
    return os.path.exists(destino), (r.stderr or "").strip()


def _ps(texto):
    """Comilla un texto para PowerShell."""
    return "'" + str(texto).replace("'", "''") + "'"


def main():
    base = carpeta_programa()
    hechos = []
    fallos = []

    destinos = [os.path.join(base, "Biblioteca Laser.lnk")]
    esc = escritorio()
    if esc:
        destinos.append(os.path.join(esc, "Biblioteca Laser.lnk"))

    for d in destinos:
        try:
            ok, err = crear(d)
        except Exception as e:
            ok, err = False, str(e)[:120]
        if ok:
            hechos.append(d)
        else:
            fallos.append("%s (%s)" % (d, err[:80]))

    for h in hechos:
        print("   acceso directo creado:", h)
    for f in fallos:
        print("   no pude crear:", f)
    return 0 if hechos else 1


if __name__ == "__main__":
    sys.exit(main())
