# -*- coding: utf-8 -*-
"""Pruebas de 2.3: rapidez y fallas que iban y venían (miniaturas, ficha, candado general).

Uso desde el repositorio: python pruebas/probar_v23.py
Nunca abre datos ni modelos reales: usa carpetas temporales.
"""
import hashlib
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probar_v22 as base22  # prepara el entorno aislado igual que las pruebas de 2.2
import app
import db


class Version23(unittest.TestCase):
    def setUp(self):
        base22.Version22.setUp(self)
        app._SIN_MINIATURA.clear()
        app._REVISIONES.clear()

    tearDown = base22.Version22.tearDown
    iniciar_http = base22.Version22.iniciar_http
    pedir = base22.Version22.pedir

    def con_foto(self):
        """Le pone al modelo de prueba una foto de verdad para que tenga miniatura."""
        from PIL import Image
        carpeta = self.modelos / "animal"
        buffer = io.BytesIO()
        Image.new("RGB", (900, 600), (200, 80, 40)).save(buffer, "PNG")
        (carpeta / "foto.png").write_bytes(buffer.getvalue())
        m = app.POR_REL["animal"]
        m["archivos"]["imagen"] = ["foto.png"]
        m["tiene_imagen"] = True
        m["preview"] = "foto.png"
        os.makedirs(app.CACHE_THUMBS, exist_ok=True)
        return m

    def cache(self):
        return Path(app.CACHE_THUMBS) / (hashlib.md5(b"animal").hexdigest() + ".jpg")

    def pedir_cabeceras(self, ruta):
        with urllib.request.urlopen(self.url + ruta, timeout=10) as r:
            return r.status, r.read(), r.headers

    # ---------------------------------------------------------------- candado
    def test_miniaturas_no_esperan_el_candado_general(self):
        self.con_foto()
        self.iniciar_http()
        soltar = threading.Event()
        tomado = threading.Event()

        def retener():
            with db.LOCK:
                tomado.set()
                soltar.wait(10)
        hilo = threading.Thread(target=retener)
        hilo.start()
        try:
            self.assertTrue(tomado.wait(3))
            inicio = time.time()
            codigo, cuerpo, _ = self.pedir_cabeceras("/thumb?rel=animal&v=1")
            self.assertEqual(codigo, 200)
            self.assertLess(time.time() - inicio, 3)
            self.assertTrue(cuerpo.startswith(b"\xff\xd8"))
            # lo que cambia o consulta datos sí espera su turno
            resultado = {}
            consulta = threading.Thread(target=lambda: resultado.setdefault("r", self.pedir("/api/datos")))
            consulta.start()
            time.sleep(0.5)
            self.assertNotIn("r", resultado)
        finally:
            soltar.set()
            hilo.join()
        consulta.join(5)
        self.assertEqual(resultado["r"][0], 200)

    def test_cola_de_espera_del_servidor_es_amplia(self):
        self.assertGreaterEqual(app.Servidor.request_queue_size, 64)

    def test_muchas_miniaturas_a_la_vez_llegan_todas_y_completas(self):
        self.con_foto()
        self.iniciar_http()
        resultados, errores = [], []

        def pedir_una():
            try:
                resultados.append(self.pedir_cabeceras("/thumb?rel=animal&v=1")[1])
            except Exception as error:  # pragma: no cover
                errores.append(repr(error))
        hilos = [threading.Thread(target=pedir_una) for _ in range(24)]
        [h.start() for h in hilos]
        [h.join(20) for h in hilos]
        self.assertEqual(errores, [])
        self.assertEqual(len(resultados), 24)
        self.assertEqual(len(set(resultados)), 1)
        self.assertEqual(list(Path(app.CACHE_THUMBS).glob("*.tmp")), [])

    # ---------------------------------------------------------------- cache
    def test_miniatura_con_revision_se_guarda_y_sin_revision_se_revisa(self):
        self.con_foto()
        self.iniciar_http()
        con_v = self.pedir_cabeceras("/thumb?rel=animal&v=abc")[2]["Cache-Control"]
        sin_v = self.pedir_cabeceras("/thumb?rel=animal")[2]["Cache-Control"]
        self.assertIn("max-age", con_v)
        self.assertEqual(sin_v, "no-cache")

    # ---------------------------------------------------------------- ficha
    def test_abrir_ficha_sin_cambios_no_reescribe_el_indice_ni_borra_la_miniatura(self):
        self.con_foto()
        app.recargar_parcial("animal")  # deja el modelo como lo lee el indexador
        app.miniatura("animal")
        self.assertTrue(self.cache().exists())
        revision = app._REVISIONES.get("animal")
        with mock.patch.object(app, "guardar_indice") as guardar:
            app.recargar_parcial("animal")
            app.recargar_parcial("animal")
        guardar.assert_not_called()
        self.assertTrue(self.cache().exists())
        self.assertEqual(app._REVISIONES.get("animal"), revision)

    def test_abrir_ficha_con_cambios_si_actualiza_indice_y_miniatura(self):
        self.con_foto()
        app.recargar_parcial("animal")
        app.miniatura("animal")
        self.assertTrue(self.cache().exists())
        (self.modelos / "animal" / "manual.pdf").write_bytes(b"%PDF-1.4 prueba")
        with mock.patch.object(app, "guardar_indice") as guardar:
            nuevo = app.recargar_parcial("animal")
        guardar.assert_called_once()
        self.assertIn("manual.pdf", nuevo["archivos"]["manual"])
        self.assertFalse(self.cache().exists())

    def test_ficha_no_consulta_el_disco_por_cada_modelo(self):
        self.con_foto()
        carpeta = self.modelos / "animal"
        for i in range(300):
            otro = dict(app.POR_REL["animal"], rel="extra%d" % i, id=i + 10,
                        ruta=str(self.modelos / ("extra%d" % i)))
            app.MODELOS.append(otro)
        self.iniciar_http()
        real = os.path.realpath
        llamadas = []

        def contar(ruta, *a, **k):
            llamadas.append(ruta)
            return real(ruta, *a, **k)
        with mock.patch("os.path.realpath", contar):
            codigo, ficha = self.pedir("/api/modelo?rel=animal")
        self.assertEqual(codigo, 200)
        self.assertEqual(ficha["submodelos"], 0)
        self.assertLess(len(llamadas), 100, "la ficha volvió a resolver la ruta de cada modelo en el disco")

    def test_ficha_cuenta_los_modelos_de_adentro(self):
        self.con_foto()
        hijo = dict(app.POR_REL["animal"], rel="animal\\ala", id=50,
                    ruta=str(self.modelos / "animal" / "ala"))
        app.MODELOS.append(hijo)
        self.iniciar_http()
        self.assertEqual(self.pedir("/api/modelo?rel=animal")[1]["submodelos"], 1)

    def test_miniatura_que_no_se_puede_dibujar_no_se_reintenta_en_cada_vuelta(self):
        self.con_foto()
        with mock.patch.object(app, "_miniatura_calcular", return_value=None) as calcular:
            self.assertIsNone(app.miniatura("animal"))
            self.assertIsNone(app.miniatura("animal"))
            self.assertEqual(calcular.call_count, 1)
            app.invalidar_miniatura("animal")  # el modelo cambió: se vuelve a intentar
            self.assertIsNone(app.miniatura("animal"))
            self.assertEqual(calcular.call_count, 2)
        app.invalidar_miniatura("animal")
        self.assertIsNotNone(app.miniatura("animal"))  # y si luego se puede, se puede

    def test_subcategorias_sin_orden_manual_salen_de_la_a_a_la_z(self):
        def v(sub):
            return {"c": "Animales", "s": sub, "oculto": 0}
        sin_orden = ["Zorro", "Ñandú", "Árbol", "Oso", "Caja 10", "Caja 2", "nube"]
        vistas = [v("Aves")] + [v(s) for s in sin_orden]
        subs = [s["nombre"] for g in app.categorias_con_conteo(vistas) if g["nombre"] == "Animales" for s in g["subs"]]
        propias = [s for s in subs if s in sin_orden]
        self.assertEqual(propias, ["Árbol", "Caja 2", "Caja 10", "nube", "Ñandú", "Oso", "Zorro"])
        # las de fábrica siguen primero y en su orden de siempre
        self.assertEqual(subs[0], "Aves")
        self.assertLess(subs.index("Aves"), subs.index("Árbol"))

    def test_el_orden_manual_de_subcategorias_no_cambia(self):
        def v(sub):
            return {"c": "Animales", "s": sub, "oculto": 0}
        vistas = [v(s) for s in ["Zorro", "Árbol", "Oso", "Aves"]]
        subs = [s["nombre"] for g in app.categorias_con_conteo(vistas) if g["nombre"] == "Animales" for s in g["subs"]]
        manual = ["Zorro", "Oso", "Aves", "Árbol"]
        self.assertEqual(set(manual), set(subs))
        for i, nombre in enumerate(manual):
            db.ejecutar("INSERT OR REPLACE INTO subcats(categoria,subcategoria,orden) VALUES (?,?,?)", ("Animales", nombre, i))
        with mock.patch.object(app, "respaldar_base", return_value={"ok": True}):
            subs = [s["nombre"] for g in app.categorias_con_conteo(vistas) if g["nombre"] == "Animales" for s in g["subs"]]
        self.assertEqual(subs, manual)

    def test_borrar_miniatura_en_uso_no_rompe(self):
        self.con_foto()
        app.miniatura("animal")
        with mock.patch("os.remove", side_effect=PermissionError("en uso")):
            app.retirar_miniatura(str(self.cache()))  # no lanza
            app.invalidar_miniatura("animal")  # tampoco


if __name__ == "__main__":
    unittest.main(verbosity=2)
