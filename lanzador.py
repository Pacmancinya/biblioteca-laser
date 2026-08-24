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


def _preguntar(titulo, texto):
    """Cartel de Si/No. Devuelve True si dijo que si."""
    try:
        import ctypes
        # 0x24 = iconos de pregunta + botones Si/No ; 6 = respondio Si
        return ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x24) == 6
    except Exception:
        return False


def _traer_datos_viejos():
    """Si es una instalacion nueva y hay una anterior, ofrece traerse los datos.
    Asi el usuario no tiene que copiar archivos a mano."""
    try:
        import migrar
    except Exception:
        return
    if not migrar.hace_falta(BASE):
        return                       # ya tiene datos propios: no se toca nada
    try:
        encontradas = migrar.buscar(saltar=BASE)
    except Exception:
        return
    if not encontradas:
        return

    vieja = encontradas[0]
    info = migrar.resumen(vieja)
    detalle = []
    if info["modelos"]:
        detalle.append("%d modelos con datos tuyos" % info["modelos"])
    if info["favoritos"]:
        detalle.append("%d favoritos" % info["favoritos"])
    if info["clientes"]:
        detalle.append("%d clientes" % info["clientes"])
    if info["ventas"]:
        detalle.append("%d ventas" % info["ventas"])

    texto = ("Encontre una version anterior de la Biblioteca en:\n\n%s\n\n"
             "%s\n\n¿Quieres traer esos datos a esta version?\n\n"
             "(La carpeta vieja no se toca ni se borra.)"
             % (vieja, ("Tiene: " + ", ".join(detalle)) if detalle
                else "Tiene tus ajustes guardados."))
    if not _preguntar(TITULO, texto):
        return
    r = migrar.traer(vieja, BASE)
    if r.get("error"):
        _avisar_error(TITULO, r["error"])
    else:
        _avisar_error(TITULO, "Listo, ya tienes tus datos aqui.\n\n"
                              "Tus favoritos, precios, clientes y ventas estan como los dejaste.")


def _primera_vez(app):
    """Si todavía no hay biblioteca leída, pedir la carpeta de modelos y leerla.

    Antes de esto el programa se moria en silencio cuando faltaba
    biblioteca.json, porque sin consola no se veia el mensaje de error.
    """

    if app.MODELOS:
        return True                      # ya hay biblioteca cargada

    carpeta = (app.CFG.get("biblioteca") or "").strip()
    if not carpeta or not os.path.isdir(carpeta):
        _avisar_error(TITULO,
                      "Bienvenido.\n\nPara empezar, elige la carpeta donde tienes "
                      "tus modelos.\n\nSe va a abrir una ventana para buscarla.")
        carpeta, err = app.pedir_carpeta()
        if err and err != "cancelado":
            _avisar_error(TITULO, "No pude abrir la ventana para elegir la carpeta.\n\n%s" % err)
            return False
        if not carpeta:
            _avisar_error(TITULO, "No elegiste ninguna carpeta.\n\n"
                                  "Vuelve a abrir el programa cuando quieras.")
            return False

    res = app.cambiar_carpeta(carpeta)
    if not res.get("ok"):
        _avisar_error(TITULO, res.get("error", "No pude leer esa carpeta."))
        return False
    return True


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
        _traer_datos_viejos()
        app.recargar()               # por si la migracion trajo datos
        if not _primera_vez(app):
            return 0
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
