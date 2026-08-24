# -*- coding: utf-8 -*-
"""Abre la Biblioteca Laser en su propia ventana.

Sin navegador y sin ventana negra: se ve como cualquier programa de Windows.
Por dentro sigue siendo la misma app, solo que la pagina se muestra dentro
de una ventana propia (usa WebView2, que ya viene con Windows).

El codigo de la app (app.py, ui.html, etc.) se lee de la carpeta donde esta
este programa, NO de adentro del .exe. Gracias a eso las actualizaciones
siguen funcionando: basta con reemplazar los .py.
"""
import os
import sys
import threading


def carpeta():
    """Donde vive el programa (sirve igual como .exe que como .py)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = carpeta()
sys.path.insert(0, BASE)
os.chdir(BASE)

TITULO = "Biblioteca Laser"


def _avisar_error(titulo, texto):
    """Muestra un cartel de Windows. Sin consola, es la unica forma de avisar."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x10)
    except Exception:
        print(titulo, texto)


def _sin_ventana():
    """Si la ventana no se puede abrir, al menos que funcione en el navegador."""
    import webbrowser
    import app
    app.preparar()
    srv, url = app.arrancar_servidor()
    webbrowser.open(url)
    _avisar_error(TITULO,
                  "No pude abrir la ventana del programa, asi que abri la "
                  "biblioteca en el navegador.\n\nDireccion: " + url +
                  "\n\nNo cierres esta ventana mientras la uses.")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        srv.shutdown()


def main():
    try:
        import app
    except Exception as e:
        _avisar_error(TITULO, "No pude cargar la biblioteca.\n\n%s\n\n"
                              "Puede que falte algun archivo de la carpeta." % e)
        return 1

    try:
        import webview
    except ImportError:
        _sin_ventana()
        return 0

    try:
        app.preparar()
        srv, url = app.arrancar_servidor()
    except Exception as e:
        _avisar_error(TITULO, "No pude iniciar la biblioteca.\n\n%s" % e)
        return 1

    icono = os.path.join(BASE, "icono.ico")
    try:
        ventana = webview.create_window(
            TITULO, url,
            width=1280, height=820, min_size=(900, 600),
            background_color="#14120F",
            text_select=True,
        )

        def al_cerrar():
            try:
                srv.shutdown()
            except Exception:
                pass

        ventana.events.closed += al_cerrar
        webview.start(
            debug=False,
            private_mode=False,          # que recuerde el tema y los filtros
            storage_path=os.path.join(BASE, "_ventana"),
            icon=icono if os.path.exists(icono) else None,
        )
    except Exception as e:
        # si WebView2 no esta o algo falla, no dejamos al usuario a oscuras
        try:
            srv.shutdown()
        except Exception:
            pass
        _avisar_error(TITULO, "La ventana no se pudo abrir (%s).\n\n"
                              "Voy a abrir la biblioteca en el navegador." % str(e)[:120])
        _sin_ventana()
        return 0

    # al cerrar la ventana se cierra todo
    try:
        srv.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
