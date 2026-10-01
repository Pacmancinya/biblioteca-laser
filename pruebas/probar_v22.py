# -*- coding: utf-8 -*-
"""Pruebas de 2.2, solo stdlib. Nunca abre datos ni modelos reales.

Uso desde el repositorio: python pruebas/probar_v22.py
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# Aislar incluso las lecturas y mkdir que ocurren durante import app.
IMPORTACION = tempfile.TemporaryDirectory(prefix="laser-v22-import-")
os.environ["BIBLIOTECA_LASER_BASE"] = IMPORTACION.name
import app
import db
import formatos
import indexar


class Version22(unittest.TestCase):
    def setUp(self):
        db.cerrar()
        self.temporal = tempfile.TemporaryDirectory(prefix="laser-v22-")
        self.base = Path(self.temporal.name)
        app.BASE = db.BASE = indexar.BASE = str(self.base)
        app.INDICE = indexar.SALIDA = str(self.base / "biblioteca.json")
        app.CONFIG = indexar.CONFIG = str(self.base / "config.json")
        app.CACHE_THUMBS = str(self.base / ".miniaturas")
        app.PAPELERA = str(self.base / "_papelera")
        db.DB_PATH = str(self.base / "biblioteca.db")
        # Crear semilla y usar COPIA SQLite temporal, nunca la base del repo.
        semilla = self.base / "semilla.db"
        with contextlib.closing(sqlite3.connect(semilla)) as origen:
            origen.executescript(db.ESQUEMA)
            origen.execute("INSERT INTO modelos(rel,categoria,subcategoria,notas) VALUES ('animal','Animales','Aves','Antes')")
            origen.execute("INSERT INTO cats(nombre,orden,propia) VALUES ('Animales',0,1)")
            origen.execute("INSERT INTO subcats(categoria,subcategoria) VALUES ('Animales','Aves')")
            origen.commit()
            with contextlib.closing(sqlite3.connect(db.DB_PATH)) as copia:
                origen.backup(copia)
        self.modelos = self.base / "modelos"
        self.modelos.mkdir()
        carpeta = self.modelos / "animal"
        carpeta.mkdir()
        (carpeta / "dibujo.cdr").write_bytes(b"cdr de prueba")
        m = {"id": 0, "nombre": "Animal", "rel": "animal", "ruta": str(carpeta),
             "ruta_partes": ["animal"], "categoria": "Animales", "subcategoria": "Aves",
             "archivos": {"corte": ["dibujo.cdr"], "manual": [], "imagen": []},
             "formatos": ["cdr"], "grosores": [], "n_corte": 1, "mb": 0,
             "tiene_imagen": False, "tiene_manual": False, "tiene_lightburn": False,
             "tiene_3d": False, "preview": ""}
        dato = {"raiz": str(self.modelos), "modelos": [m], "categorias": [], "total_modelos": 1}
        Path(app.INDICE).write_text(json.dumps(dato), encoding="utf-8")
        Path(app.CONFIG).write_text(json.dumps({"biblioteca": str(self.modelos)}), encoding="utf-8")
        app._REGLAS = None
        app.AVISO_RESPALDO = ""
        app.recargar()
        self.servidor = None

    def tearDown(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
            self.hilo.join(timeout=3)
        db.cerrar()
        self.temporal.cleanup()

    def leer_copia(self, nombre, consulta, args=()):
        ruta = Path(app.carpeta_respaldos()) / nombre
        with contextlib.closing(sqlite3.connect(ruta)) as cx:
            return cx.execute(consulta, args).fetchall()

    def iniciar_http(self):
        self.servidor = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.url = "http://127.0.0.1:%s" % self.servidor.server_port

    def pedir(self, ruta, datos=None):
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        req = urllib.request.Request(self.url + ruta, cuerpo, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as respuesta:
                return respuesta.status, json.load(respuesta)
        except urllib.error.HTTPError as respuesta:
            return respuesta.code, json.load(respuesta)

    def test_respaldo_antes_de_renombrar_incluye_wal(self):
        db.guardar_meta("animal", {"notas": "Cambio reciente en WAL"})
        self.assertTrue(app.renombrar_categoria("Animales", "Naturaleza")["ok"])
        copias = app.listar_respaldos()
        self.assertEqual(len(copias), 1)
        self.assertIn("renombrar la categoría Animales", copias[0]["descripcion"])
        filas = self.leer_copia(copias[0]["archivo"], "SELECT categoria,notas FROM modelos WHERE rel='animal'")
        self.assertEqual(filas, [("Animales", "Cambio reciente en WAL")])
        self.assertEqual(db.meta("animal")["categoria"], "Naturaleza")

    def test_sin_respaldo_no_se_cambia_el_orden(self):
        with mock.patch.object(app, "respaldar_base", return_value={"error": "Sin espacio"}):
            self.assertIn("error", app.renombrar_categoria("Animales", "Naturaleza"))
            self.assertIn("error", app.guardar_edicion("animal", {"categoria": "Hogar"}))
            self.assertIn("error", app.alternar_modelo_oculto("animal"))
        self.assertEqual(db.meta("animal")["categoria"], "Animales")
        self.assertFalse(db.meta("animal")["oculto"])

    def test_cambios_de_organizacion_tienen_copia_previa(self):
        acciones = [lambda: app.crear_categoria("Nueva"),
                    lambda: app.crear_subcategoria("Animales", "Peces"),
                    lambda: app.ordenar_categorias(["Nueva", "Animales"]),
                    lambda: app.marcar_carpeta(str(self.modelos / "animal"), "Animales", "Aves"),
                    lambda: app.quitar_regla("animal"),
                    lambda: app.renombrar_subcat("Animales", "Peces", "Marinos"),
                    lambda: app.borrar_subcat("Animales", "Marinos"),
                    lambda: app.borrar_categoria("Nueva"),
                    lambda: app.guardar_edicion("animal", {"categoria": "Otra"}),
                    lambda: app.alternar_modelo_oculto("animal"),
                    lambda: app.importar_datos({"modelos": []}),
                    lambda: app.borrar_modelo("animal")]
        for i, accion in enumerate(acciones, 1):
            with self.subTest(cambio=i):
                self.assertTrue(accion().get("ok"))
                self.assertEqual(len(app.listar_respaldos()), i)

    def test_editar_notas_no_crea_copia_de_organizacion(self):
        app.guardar_edicion("animal", {"notas": "Una nota"})
        self.assertEqual(app.listar_respaldos(), [])

    def test_fallo_al_escribir_copia_no_deja_archivo_ni_cambia_base(self):
        with mock.patch.object(app.sqlite3, "connect", side_effect=OSError("Sin espacio")):
            res = app.renombrar_categoria("Animales", "Nueva")
        self.assertIn("error", res)
        self.assertEqual(db.meta("animal")["categoria"], "Animales")
        self.assertEqual(list(Path(app.carpeta_respaldos()).iterdir()), [])

    def test_limite_30_diarios_y_30_cambios_solo_propios(self):
        carpeta = Path(app.carpeta_respaldos())
        carpeta.mkdir()
        antiguos = [carpeta / "biblioteca-19990101.db", carpeta / "ajeno.db"]
        for ruta in antiguos:
            ruta.write_bytes(b"No borrar")
        falsas = carpeta / ("bl-v22-cambio-19990101-000000000000-" + "a" * 32 + ".db")
        falsas.write_bytes(b"Otra persona")
        Path(str(falsas) + ".json").write_text('{"marca":"otra app"}', encoding="utf-8")
        with mock.patch.object(app, "datetime", wraps=datetime) as reloj:
            for i in range(35):
                reloj.now.return_value = datetime(2025, 1, 1) + timedelta(days=i)
                for tipo in ("diario", "cambio"):
                    self.assertTrue(app.respaldar_base("Prueba %s" % i, tipo)["ok"])
        lista = app.listar_respaldos()
        self.assertEqual(sum(x["tipo"] == "diario" for x in lista), 30)
        self.assertEqual(sum(x["tipo"] == "cambio" for x in lista), 30)
        self.assertFalse(any(x["descripcion"] == "Prueba 0" for x in lista))
        self.assertTrue(all(p.read_bytes() == b"No borrar" for p in antiguos))
        self.assertEqual(falsas.read_bytes(), b"Otra persona")

    def test_diario_una_vez_por_dia_y_copia_externa(self):
        externa = self.base / "pendrive"
        externa.mkdir()
        db.guardar_ajuste("carpeta_respaldo_externa", str(externa))
        with mock.patch.object(app, "datetime", wraps=datetime) as reloj:
            reloj.now.return_value = datetime(2026, 9, 1, 10)
            self.assertTrue(app.respaldo_diario()["ok"])
            self.assertTrue(app.respaldo_diario()["ok"])
            self.assertEqual(len(app.listar_respaldos()), 1)
            self.assertEqual(len(list(externa.glob("*.db"))), 1)
            reloj.now.return_value = datetime(2026, 9, 2, 10)
            self.assertTrue(app.respaldo_diario()["ok"])
            self.assertEqual(len(app.listar_respaldos()), 2)
        db.guardar_ajuste("carpeta_respaldo_externa", str(self.base / "desconectado"))
        res = app.respaldo_diario()
        self.assertTrue(res["ok"])
        self.assertIn("Conecta", res["aviso"])
        self.assertFalse((self.base / "desconectado").exists())

    def test_volver_y_deshacer_el_volver(self):
        original = app.respaldar_base("Estado original")["respaldo"]["archivo"]
        db.guardar_meta("animal", {"categoria": "Nueva", "favorito": 1, "notas": "Después"})
        db.guardar_regla("animal", "Nueva", "Nueva sub")
        conexion_vieja = db.cx()
        res = app.volver_respaldo(original)
        self.assertTrue(res["ok"], res)
        self.assertIn("Listo, la biblioteca quedó como estaba el", res["aviso"])
        self.assertIsNot(db.cx(), conexion_vieja)
        with self.assertRaises(sqlite3.ProgrammingError):
            conexion_vieja.execute("SELECT 1")
        self.assertEqual(db.meta("animal")["categoria"], "Animales")
        self.assertEqual(db.reglas_carpeta(), [])
        self.assertTrue(app.volver_respaldo(res["deshacer"])["ok"])
        self.assertEqual(db.meta("animal")["categoria"], "Nueva")
        self.assertEqual(db.meta("animal")["notas"], "Después")
        self.assertEqual(app.regla_de("animal"), ("Nueva", "Nueva sub"))

    def test_volver_a_la_mas_antigua_con_retencion_llena(self):
        for i in range(30):
            self.assertTrue(app.respaldar_base("Copia %s" % i)["ok"])
        vieja = app.listar_respaldos()[-1]["archivo"]
        db.guardar_meta("animal", {"notas": "Último estado"})
        self.assertTrue(app.volver_respaldo(vieja)["ok"])
        self.assertEqual(db.meta("animal")["notas"], "Antes")
        self.assertEqual(len(app.listar_respaldos()), 30)

    def test_copia_danada_y_ruta_fuera_no_restauran(self):
        nombre = app.respaldar_base("Corrupta")["respaldo"]["archivo"]
        (Path(app.carpeta_respaldos()) / nombre).write_bytes(b"no es sqlite")
        self.assertIn("error", app.volver_respaldo(nombre))
        self.assertIn("error", app.volver_respaldo("../semilla.db"))
        self.assertEqual(db.meta("animal")["notas"], "Antes")

    def test_solicitudes_concurrentes_durante_restauracion(self):
        self.iniciar_http()
        nombre = app.respaldar_base("Original")["respaldo"]["archivo"]
        db.guardar_meta("animal", {"notas": "Después"})
        errores = []
        def leer():
            try:
                for i in range(10):
                    codigo, dato = self.pedir("/api/modelo?rel=animal")
                    if codigo != 200 or dato["meta"]["notas"] not in ("Antes", "Después"):
                        errores.append((codigo, dato))
            except Exception as e:
                errores.append(str(e))
        with mock.patch.object(app, "buscar_programa", return_value=""):
            lectores = [threading.Thread(target=leer) for i in range(2)]
            for hilo in lectores:
                hilo.start()
            res = app.volver_respaldo(nombre)
            self.assertTrue(res["ok"], res)
            self.assertTrue(app.volver_respaldo(res["deshacer"])["ok"])
            for hilo in lectores:
                hilo.join(timeout=10)
                self.assertFalse(hilo.is_alive())
        self.assertEqual(errores, [])

    def test_archivos_cdr_principal_prioridades_y_faltantes(self):
        carpeta = self.modelos / "animal"
        def elegir(archivos, programa, principal=""):
            return formatos.elegir_archivo(str(carpeta), archivos, programa, principal)
        self.assertEqual(elegir(["dibujo.cdr"], "corel"), "dibujo.cdr")
        self.assertIsNone(elegir(["dibujo.cdr"], "lightburn"))
        for programa, prioridad in formatos.PRIORIDADES.items():
            archivos = ["modelo" + ext.upper() for ext in reversed(prioridad)]
            for archivo in archivos:
                (carpeta / archivo).touch()
            for ext in prioridad:
                esperado = "modelo" + ext.upper()
                self.assertEqual(elegir(archivos, programa), esperado)
                archivos.remove(esperado)
        for nombre in ("editable.svg", "archivo.ai", "proyecto.lbrn2", "manual.pdf"):
            (carpeta / nombre).touch()
        archivos = ["dibujo.cdr", "editable.svg", "archivo.ai", "proyecto.lbrn2", "manual.pdf", "noexiste.cdr"]
        self.assertEqual(elegir(archivos, "corel", "editable.svg"), "editable.svg")
        self.assertEqual(elegir(archivos, "lightburn", "archivo.ai"), "archivo.ai")
        self.assertEqual(elegir(archivos, "lightburn", "dibujo.cdr"), "proyecto.lbrn2")
        self.assertEqual(elegir(["manual.pdf"], "corel", "manual.pdf"), "manual.pdf")
        self.assertIsNone(elegir(["noexiste.cdr", "../semilla.db"], "corel"))

    def test_indexador_ignora_internos_en_cualquier_nivel(self):
        for nombre in indexar.CARPETAS_INTERNAS:
            for padre in (self.modelos, self.modelos / "normal"):
                oculto = padre / nombre.upper() / "subcarpeta"
                oculto.mkdir(parents=True)
                (oculto / "no-indexar.svg").write_text("<svg/>", encoding="utf-8")
        with mock.patch.object(sys, "argv", ["indexar.py"]), contextlib.redirect_stdout(io.StringIO()):
            indexar.indexar()
        dato = json.loads(Path(indexar.SALIDA).read_text(encoding="utf-8"))
        self.assertEqual([m["rel"] for m in dato["modelos"]], ["animal"])

    def test_limpieza_versiones_no_borra_trabajos_convertidos(self):
        convertido = self.base / "_convertidos" / "trabajo.svg"
        convertido.parent.mkdir()
        convertido.write_bytes(b"Trabajo editado")
        for i in range(6):
            db.registrar_version("animal", "modelo", "trabajo.svg", str(convertido))
        self.assertEqual(convertido.read_bytes(), b"Trabajo editado")
        for i in range(6):
            db.registrar_version("animal", "convertido", "trabajo.svg", str(convertido))
        self.assertEqual(convertido.read_bytes(), b"Trabajo editado")

    def test_no_se_escribe_ni_quita_un_modelo_antiguo_de_convertidos(self):
        carpeta = self.base / "_convertidos"
        carpeta.mkdir()
        trabajo = carpeta / "trabajo.svg"
        trabajo.write_bytes(b"Trabajo del papa")
        app.POR_REL["antiguo"] = {"ruta": str(carpeta)}
        self.assertIn("error", app.guardar_archivo("antiguo", "modelo", "trabajo.svg", b"nuevo"))
        self.assertIn("error", app.borrar_archivo("antiguo", "trabajo.svg"))
        self.assertIn("error", app.borrar_modelo("antiguo"))
        self.assertEqual(trabajo.read_bytes(), b"Trabajo del papa")

    def test_http_botones_y_conversion_eliminada(self):
        self.iniciar_http()
        with mock.patch.object(app, "buscar_programa", return_value="CorelDRW.exe"), mock.patch.object(app.subprocess, "Popen") as abrir:
            codigo, ficha = self.pedir("/api/modelo?rel=animal")
            self.assertEqual(codigo, 200)
            self.assertEqual(ficha["abrir_en"]["corel"]["archivo"], "dibujo.cdr")
            self.assertFalse(ficha["abrir_en"]["lightburn"]["puede"])
            self.assertTrue(ficha["abrir_en"]["lightburn"]["motivo"])
            codigo, res = self.pedir("/api/abrir-en?rel=animal&programa=corel")
            self.assertEqual(codigo, 200)
            self.assertTrue(res["ok"])
            self.assertEqual(Path(abrir.call_args.args[0][1]).name, "dibujo.cdr")
        self.assertEqual(self.pedir("/api/convertir", {})[0], 404)
        self.assertEqual(self.pedir("/api/convertir/opciones?f=dibujo.cdr")[0], 404)
        self.assertFalse((self.base / "_convertidos").exists())

    def test_http_copia_antes_de_meta_ocultar_y_ordenar(self):
        self.iniciar_http()
        for i, (ruta, datos) in enumerate([
                ("/api/meta", {"rel": "animal", "categoria": "Nueva"}),
                ("/api/ocultar", {"rel": "animal"}),
                ("/api/categoria/ordenar", {"orden": ["Animales"]})], 1):
            codigo, res = self.pedir(ruta, datos)
            self.assertEqual(codigo, 200)
            self.assertTrue(res["ok"])
            self.assertEqual(len(app.listar_respaldos()), i)

    def test_json_descargado_incluye_orden_y_reglas(self):
        db.guardar_regla("animal", "Animales", "Aves")
        datos = app.exportar_datos()
        self.assertEqual(datos["cats"][0]["nombre"], "Animales")
        self.assertEqual(datos["reglas_carpeta"][0]["rel"], "animal")
        db.ejecutar("DELETE FROM cats")
        db.ejecutar("DELETE FROM reglas_carpeta")
        self.assertTrue(app.importar_datos(datos)["ok"])
        self.assertEqual(db.cats_propias()[2], {"Animales"})
        self.assertEqual(app.regla_de("animal"), ("Animales", "Aves"))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        db.cerrar()
        IMPORTACION.cleanup()
