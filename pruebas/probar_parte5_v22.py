# -*- coding: utf-8 -*-
"""Regresiones de la quinta parte (prueba en ventana real). Solo datos temporales.

Uso: python -m unittest discover -s pruebas -p "probar_*.py"
"""
import contextlib
import io
import os
from pathlib import Path
import unittest
import urllib.parse
from unittest import mock

from probar_v22 import app, db, indexar, formatos
import probar_v22 as soporte
import agregados
import lanzador
import migrar


class Parte5(unittest.TestCase):
    setUp = soporte.Version22.setUp
    tearDown = soporte.Version22.tearDown
    iniciar_http = soporte.Version22.iniciar_http
    pedir = soporte.Version22.pedir

    def indexar(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ok, error = app.indexar_ahora()
        self.assertTrue(ok, error)

    # 2: con el disco ausente el mensaje habla del disco, no de Ajustes.
    def test_02_agregar_con_disco_ausente_dice_que_no_encuentra_la_carpeta(self):
        ausente = str(self.base / "disco desconectado")
        with self.assertRaises(ValueError) as e:
            agregados.planificar([str(self.base)], ausente)
        self.assertIn("No encuentro la carpeta de modelos " + ausente, str(e.exception))
        self.assertIn("¿Está conectado el disco?", str(e.exception))
        with self.assertRaises(ValueError) as e:
            agregados.planificar([str(self.base)], "")
        self.assertIn("Elige primero tu carpeta principal", str(e.exception))

    # 1 (servidor): el trabajo con error trae su propio mensaje y lo copiado.
    def test_01_el_estado_de_error_trae_mensaje_y_copias_parciales(self):
        origen = self.base / "origen"
        (origen / "Con exe").mkdir(parents=True)
        (origen / "Con exe" / "a.svg").write_text("<svg/>", encoding="utf-8")
        (origen / "Con exe" / "b.bat").write_text("x", encoding="utf-8")
        agregados.TRABAJOS.clear()
        res = app.preparar_arrastre([str(origen / "Con exe")])
        self.assertTrue(res["ok"])
        for _ in range(100):
            estado = agregados.estado(res["id"])
            if estado.get("estado") != "revisando":
                break
            import time
            time.sleep(0.05)
        self.assertEqual(estado["estado"], "error")
        self.assertIn("No se agregan ejecutables", estado["error"])

    # 3: el PDF es el manual, nunca el dibujo.
    def test_03_corel_no_elige_el_manual_pdf(self):
        carpeta = self.modelos / "camioneta"
        carpeta.mkdir()
        for nombre in ("Land Rover Assembly Guide_makecnc.pdf", "camioneta.dxf"):
            (carpeta / nombre).write_bytes(b"x")
        archivos = ["Land Rover Assembly Guide_makecnc.pdf", "camioneta.dxf"]
        self.assertEqual(formatos.elegir_archivo(str(carpeta), archivos, "corel"), "camioneta.dxf")
        # Aunque el PDF esté clasificado como manual y sea el "principal".
        self.assertEqual(formatos.elegir_archivo(str(carpeta), archivos, "corel",
                                                 principal=archivos[0], manuales=[archivos[0]]), "camioneta.dxf")
        self.assertIsNone(formatos.elegir_archivo(str(carpeta), [archivos[0]], "corel", manuales=[archivos[0]]))
        # Sin otro formato y sin clasificar como manual, el PDF queda como último recurso.
        self.assertEqual(formatos.elegir_archivo(str(carpeta), [archivos[0]], "corel"), archivos[0])
        self.assertEqual(formatos.PRIORIDADES["corel"][-1], ".pdf")

    def test_03_el_servidor_usa_la_lista_de_manuales_del_modelo(self):
        carpeta = self.modelos / "camioneta"
        carpeta.mkdir()
        (carpeta / "guia.pdf").write_bytes(b"x")
        (carpeta / "camioneta.dxf").write_bytes(b"x")
        m = {"ruta": str(carpeta), "archivos": {"corte": ["camioneta.dxf"], "manual": ["guia.pdf"]}}
        self.assertEqual(app.archivo_para_programa(m, "corel", "guia.pdf"), "camioneta.dxf")

    # 8: sin disco, los botones lo dicen.
    def test_08_abrir_en_con_disco_ausente_explica_el_disco(self):
        self.iniciar_http()
        self.modelos.rename(self.base / "desconectado")
        codigo, ficha = self.pedir("/api/modelo?rel=animal")
        self.assertEqual(codigo, 200)
        for cual in ("corel", "lightburn"):
            motivo = ficha["abrir_en"][cual]["motivo"]
            self.assertIn("No encuentro la carpeta de modelos", motivo)
            self.assertNotIn("no trae un archivo", motivo)

    def test_08_modelo_sin_archivo_compatible_conserva_su_motivo(self):
        m = {"ruta": str(self.modelos / "animal")}
        self.assertIn("no trae un archivo que pueda abrir CorelDRAW".replace("CorelDRAW", "LightBurn"),
                      app.motivo_sin_archivo(m, "lightburn"))

    # 6: sugerir por archivos aunque cambie el nombre de la carpeta.
    def test_06_sugiere_carpeta_nueva_con_los_mismos_archivos(self):
        db.guardar_meta("animal", {"stock": 5})
        app.recordar_rutas()
        self.assertIn("animal", db.firmas_todas())
        (self.modelos / "nuevo").mkdir()
        (self.modelos / "animal").rename(self.modelos / "nuevo" / "otro nombre distinto")
        self.indexar()
        faltan = app.no_encontrados()
        self.assertEqual(faltan[0]["rel"], "animal")
        esperado = os.path.join("nuevo", "otro nombre distinto")
        self.assertEqual([s["rel"] for s in faltan[0]["sugeridas"]], [esperado])
        self.assertTrue(app.resolver_no_encontrado("animal", esperado)["ok"])
        self.assertEqual(db.meta(esperado)["stock"], 5)

    def test_06_no_sugiere_carpetas_con_otros_archivos(self):
        db.guardar_meta("animal", {"stock": 5})
        app.recordar_rutas()
        (self.modelos / "animal").rename(self.modelos / "movido")
        (self.modelos / "movido" / "dibujo.cdr").unlink()
        (self.modelos / "movido" / "distinto.cdr").write_bytes(b"x")
        self.indexar()
        self.assertEqual(app.no_encontrados()[0]["sugeridas"], [])

    def test_06_copias_antiguas_sin_tabla_de_firmas_siguen_sirviendo(self):
        # La tabla es un dato derivado: no puede impedir volver a una copia anterior.
        origen = db.cx().execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        self.assertIn("firmas", {r[0] for r in origen})
        nombre = app.respaldar_base("Prueba")
        self.assertTrue(nombre.get("ok"))
        import sqlite3
        with contextlib.closing(sqlite3.connect(nombre["archivo"])) as cx:
            cx.execute("DROP TABLE firmas")
            cx.commit()
        ficha = Path(nombre["archivo"] + ".json")
        self.assertTrue(ficha.exists())
        res = app.volver_respaldo(os.path.basename(nombre["archivo"]))
        self.assertTrue(res.get("ok"), res)

    # 9: varios.
    def test_09_migracion_muestra_la_ruta_tal_cual_y_con_tildes_y_singular(self):
        nueva = self.base / "Mi Carpeta Nueva"
        vieja = self.base / "Versión Vieja Con Mayúsculas"
        nueva.mkdir()
        vieja.mkdir()
        capturado = {}
        with mock.patch.object(migrar, "hace_falta", return_value=True), \
                mock.patch.object(migrar, "buscar", return_value=[str(vieja)]), \
                mock.patch.object(migrar, "resumen", return_value={"modelos": 1, "favoritos": 1, "clientes": 1, "ventas": 1}), \
                mock.patch.object(lanzador, "_preguntar", side_effect=lambda t, texto: capturado.update(texto=texto) or False):
            lanzador._traer_datos_viejos()
        texto = capturado["texto"]
        self.assertIn(str(vieja), texto)
        self.assertIn("Encontré una versión anterior", texto)
        self.assertIn("1 modelo con datos tuyos, 1 favorito, 1 cliente, 1 venta", texto)

    def test_09_buscar_no_pasa_la_ruta_en_minusculas(self):
        base = self.base / "Mezcla De MAYUSCULAS"
        base.mkdir()
        pedidos = []

        def lugares(desde=None):
            pedidos.append(desde)
            return [str(base)]
        with mock.patch.object(migrar, "_lugares", side_effect=lugares):
            migrar.buscar(saltar=str(base / "Nueva Instalación"))
        self.assertEqual(pedidos, [os.path.abspath(str(base / "Nueva Instalación"))])
        vieja = base / "Instalación Vieja"
        vieja.mkdir()
        (vieja / "biblioteca.db").write_bytes(b"")
        (vieja / "app.py").write_bytes(b"")
        with mock.patch.object(migrar, "_lugares", return_value=[str(base)]):
            self.assertEqual(migrar.buscar(saltar=str(base / "Nueva Instalación")), [str(vieja)])

    def test_09_categoria_otros_no_cuenta_para_el_maximo(self):
        def grupos(*nombres):
            return [{"nombre": n} for n in nombres]
        seis_y_otros = grupos("A", "B", "C", "D", "E", "F", "Otros")
        with mock.patch.object(app, "categorias_con_conteo", return_value=seis_y_otros):
            self.assertIn("hasta 6", app.crear_categoria("G")["error"])
        cinco_y_otros = grupos("A", "B", "C", "D", "E", "Otros")
        with mock.patch.object(app, "categorias_con_conteo", return_value=cinco_y_otros):
            self.assertTrue(app.crear_categoria("F")["ok"])


if __name__ == "__main__":
    unittest.main()
