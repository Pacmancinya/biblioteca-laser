# -*- coding: utf-8 -*-
"""Prueba visual aislada: python pruebas/ventana_v22.py [--navegador].

Usa modelos ficticios y publica la carpeta «Arrastrar desde aquí» para probar
desde el Explorador. No carga ni modifica datos de la instalación real.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--navegador", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix=".prueba-v22-", dir=REPO) as temporal:
        base = Path(temporal)
        os.environ["BIBLIOTECA_LASER_BASE"] = str(base)
        import app
        import db
        import indexar
        import lanzador
        modelos = base / "Biblioteca ficticia"
        modelos.mkdir()
        for i in range(125):
            carpeta = modelos / ("Modelo %03d" % i)
            carpeta.mkdir()
            (carpeta / "dibujo.cdr").write_bytes(b"Archivo ficticio para probar la interfaz")
        arrastrar = base / "Arrastrar desde aqui"
        carpeta = arrastrar / "Casita nueva"
        carpeta.mkdir(parents=True)
        (carpeta / "casa.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20"/></svg>', encoding="utf-8")
        (arrastrar / "suelto.cdr").write_bytes(b"Archivo ficticio")
        shutil.copy2(REPO / "ui.html", base / "ui.html")
        shutil.copy2(REPO / "version.json", base / "version.json")
        (base / "config.json").write_text(json.dumps({"biblioteca": str(modelos)}), encoding="utf-8")
        sys.argv = [str(REPO / "indexar.py")]
        indexar.indexar()
        app.recargar()
        for cat in ("Animales", "Hogar", "Casas"):
            db.guardar_cat(cat, propia=True)
            for sub in ("Primera", "Segunda"):
                db.crear_subcat(cat, sub)
        for i, m in enumerate(app.MODELOS):
            db.guardar_meta(m["rel"], {"categoria": ["Animales", "Hogar", "Casas"][i % 3], "subcategoria": "Primera"})
        servidor = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%s" % servidor.server_port
        print("URL de prueba:", url, flush=True)
        print("Origenes ficticios:", arrastrar, flush=True)
        try:
            if args.navegador:
                threading.Event().wait()
            else:
                import webview
                ventana = webview.create_window("Biblioteca - prueba v2.2", url, width=1100, height=800)
                ventana.events.loaded += lambda: lanzador.registrar_arrastre(ventana, app)
                webview.start(gui="edgechromium", debug=False, storage_path=str(base / "webview"))
        finally:
            servidor.shutdown()
            db.cerrar()


if __name__ == "__main__":
    main()
