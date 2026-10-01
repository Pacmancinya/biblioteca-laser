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
import json


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
    def cuenta(n, uno, varios):
        return "%d %s" % (n, uno if n == 1 else varios)

    detalle = []
    if info["modelos"]:
        detalle.append(cuenta(info["modelos"], "modelo con datos tuyos", "modelos con datos tuyos"))
    if info["favoritos"]:
        detalle.append(cuenta(info["favoritos"], "favorito", "favoritos"))
    if info["clientes"]:
        detalle.append(cuenta(info["clientes"], "cliente", "clientes"))
    if info["ventas"]:
        detalle.append(cuenta(info["ventas"], "venta", "ventas"))

    texto = ("Encontré una versión anterior de la Biblioteca en:\n\n%s\n\n"
             "%s\n\n¿Quieres traer esos datos a esta versión?\n\n"
             "(La carpeta vieja no se toca ni se borra.)"
             % (vieja, ("Tiene: " + ", ".join(detalle)) if detalle
                else "Tiene tus ajustes guardados."))
    if not _preguntar(TITULO, texto):
        return
    r = migrar.traer(vieja, BASE)
    if r.get("error"):
        _avisar_error(TITULO, r["error"])
    else:
        _avisar_error(TITULO, "Listo, ya tienes tus datos aquí.\n\n"
                              "Tus favoritos, precios, clientes y ventas están como los dejaste.")


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

    # La lectura ocurre después de mostrar la pantalla de avance.
    app.guardar_config({"biblioteca": carpeta})
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


def registrar_arrastre(ventana, app):
    """El listener Python habilita pywebviewFullPath en WebView2 (pywebview 5+)."""
    from webview.dom import DOMEventHandler

    def al_soltar(evento):
        archivos = (evento.get("dataTransfer") or {}).get("files") or []
        if not archivos:
            return
        rutas = [f.get("pywebviewFullPath") for f in archivos]
        if not all(rutas):
            ventana.evaluate_js("toast('Para agregar arrastrando, abre la Biblioteca desde su icono.',true)")
            return
        x, y = evento.get("clientX", 0), evento.get("clientY", 0)
        destino = ventana.evaluate_js("destinoEnPunto(%s,%s)" % (json.dumps(x), json.dumps(y))) or {}
        if destino.get("cargar"):
            return
        resultado = app.preparar_arrastre(rutas, destino.get("categoria", ""), destino.get("subcategoria", ""))
        if resultado.get("ok"):
            ventana.evaluate_js("recibirAgregado(%s)" % json.dumps(resultado["id"]))
        else:
            ventana.evaluate_js("toast(%s,true)" % json.dumps(resultado.get("error", "No pude agregarlo.")))

    ventana.dom.document.events.dragover += DOMEventHandler(lambda e: None, prevent_default=True, debounce=500)
    ventana.dom.document.events.drop += DOMEventHandler(al_soltar, prevent_default=True)
    ventana.evaluate_js("window.arrastreNativo=true")


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
        srv, url = app.arrancar_servidor()
    except Exception as e:
        _avisar_error(TITULO, "No pude iniciar la biblioteca.\n\n%s" % e)
        return 1

    icono = os.path.join(BASE, "icono.ico")
    try:
        webview.settings['ALLOW_DOWNLOADS'] = True
        ventana = webview.create_window(
            TITULO, url + "/inicio",
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

        preparado = threading.Event()

        def preparar_ventana():
            def avisar(texto):
                ventana.evaluate_js("document.getElementById('arranqueTexto').textContent=" + json.dumps(texto))
            try:
                app.preparar(avisar)
                ventana.load_url(url)
            except Exception as error:
                avisar("No pude abrir la biblioteca: " + str(error))

        def al_cargar():
            if not preparado.is_set():
                preparado.set()
                threading.Thread(target=preparar_ventana, daemon=True).start()
                return
            try:
                registrar_arrastre(ventana, app)
            except Exception:
                ventana.evaluate_js("window.arrastreNativo=false")

        ventana.events.loaded += al_cargar
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
