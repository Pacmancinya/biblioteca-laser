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
import time
import hashlib
import base64
import types
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
import agregados
import lanzador


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
        agregados.TRABAJOS.clear()
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

    def esperar_agregado(self, identificador, estados):
        limite = time.monotonic() + 8
        while time.monotonic() < limite:
            dato = agregados.estado(identificador)
            if dato.get("estado") in estados:
                return dato
            time.sleep(.01)
        self.fail("El agregado no terminó: %r" % dato)

    def preparar_copia(self, rutas, categoria="", subcategoria=""):
        res = app.preparar_arrastre([str(r) for r in rutas], categoria, subcategoria)
        self.assertTrue(res.get("ok"), res)
        estado = self.esperar_agregado(res["id"], {"confirmar", "error"})
        self.assertEqual(estado["estado"], "confirmar", estado)
        return res["id"]

    def copiar(self, rutas, categoria="", subcategoria=""):
        identificador = self.preparar_copia(rutas, categoria, subcategoria)
        self.assertTrue(agregados.confirmar(identificador)["ok"])
        res = self.esperar_agregado(identificador, {"listo", "error"})
        self.assertEqual(res["estado"], "listo", res)
        self.assertEqual(res["copiados"], res["total"])
        return res

    def foto(self):
        return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=")

    def test_basurero_oculta_sin_tocar_archivos_ni_papelera(self):
        carpeta = self.modelos / "animal"
        sub = carpeta / "subcarpeta"
        sub.mkdir()
        (sub / "foto.png").write_bytes(self.foto())
        antes = {str(p.relative_to(carpeta)): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in carpeta.rglob("*") if p.is_file()}
        papelera = Path(app.PAPELERA)
        papelera.mkdir()
        anterior = papelera / "antiguo.cdr"
        anterior.write_bytes(b"No vaciar")
        db.a_papelera("archivo", "animal", "antiguo.cdr", str(carpeta / "antiguo.cdr"), str(anterior))
        self.iniciar_http()
        codigo, dato = self.pedir("/api/borrar-modelo", {"rel": "animal"})
        self.assertEqual(codigo, 200)
        self.assertEqual(dato["aviso"], app.MENSAJE_OCULTO)
        self.assertTrue(db.meta("animal")["oculto"])
        self.assertIn("animal", app.POR_REL)
        self.assertEqual(len(app.listar_respaldos()), 1)
        self.assertEqual(self.pedir("/api/borrar-archivo", {"rel": "animal", "nombre": "dibujo.cdr"})[0], 400)
        self.assertEqual(self.pedir("/api/papelera/vaciar", {})[0], 400)
        despues = {str(p.relative_to(carpeta)): (p.read_bytes(), p.stat().st_mtime_ns)
                   for p in carpeta.rglob("*") if p.is_file()}
        self.assertEqual(antes, despues)
        self.assertEqual(anterior.read_bytes(), b"No vaciar")
        self.assertEqual(len(db.papelera()), 1)
        db.cerrar()
        app.recargar()
        self.assertTrue(app.modelo_vista(app.POR_REL["animal"])["oculto"])

    def test_asignacion_por_arrastre_persiste_con_respaldo_y_sin_mover(self):
        db.guardar_cat("Nueva", propia=True)
        db.crear_subcat("Nueva", "Sub")
        original = self.modelos / "animal" / "dibujo.cdr"
        antes = (original.read_bytes(), original.stat().st_mtime_ns)
        self.iniciar_http()
        codigo, dato = self.pedir("/api/modelos/asignar", {"rels": ["animal"], "categoria": "Nueva", "subcategoria": "Sub"})
        self.assertEqual(codigo, 200)
        self.assertTrue(dato["ok"])
        copia = app.listar_respaldos()[0]["archivo"]
        self.assertEqual(self.leer_copia(copia, "SELECT categoria,subcategoria FROM modelos WHERE rel='animal'"), [("Animales", "Aves")])
        db.cerrar()
        app.recargar()
        vista = app.modelo_vista(app.POR_REL["animal"])
        self.assertEqual((vista["c"], vista["s"]), ("Nueva", "Sub"))
        self.assertEqual(antes, (original.read_bytes(), original.stat().st_mtime_ns))

    def test_arrastre_no_cambia_nada_sin_respaldo(self):
        with mock.patch.object(app, "respaldar_base", return_value={"error": "Sin espacio"}):
            self.assertIn("error", app.asignar_modelos(["animal"], "Animales", "Aves"))
            self.assertIn("error", app.ordenar_subcategorias("Animales", ["Aves"]))
            self.assertIn("error", app.trasladar_subcategoria("Animales", "Aves", "Otra"))
        self.assertEqual(db.meta("animal")["categoria"], "Animales")

    def test_orden_y_traslado_subcategorias_incluye_reglas_y_ocultos(self):
        db.crear_subcat("Animales", "Peces")
        db.guardar_cat("Destino", propia=True)
        db.guardar_regla("animal", "Animales", "Aves")
        db.guardar_meta("animal", {"oculto": 1})
        self.assertTrue(app.ordenar_subcategorias("Animales", ["Peces", "Aves"])["ok"])
        db.cerrar()
        app.recargar()
        g = next(g for g in app.categorias_con_conteo(app.vistas_todas()) if g["nombre"] == "Animales")
        self.assertEqual([s["nombre"] for s in g["subs"]], ["Peces", "Aves"])
        self.assertTrue(app.trasladar_subcategoria("Animales", "Aves", "Destino")["ok"])
        self.assertEqual(app.regla_de("animal"), ("Destino", "Aves"))
        vista = app.modelo_vista(app.POR_REL["animal"])
        self.assertEqual((vista["c"], vista["s"], vista["oculto"]), ("Destino", "Aves", 1))
        self.assertEqual(len(app.listar_respaldos()), 2)

    def test_copia_carpetas_contenedor_sin_pisar_ni_tocar_original(self):
        origen = self.base / "original" / "Coleccion"
        for nombre in ("uno", "dos"):
            modelo = origen / nombre
            modelo.mkdir(parents=True)
            (modelo / "modelo.cdr").write_bytes(b"original " + nombre.encode())
            (modelo / "foto.png").write_bytes(self.foto())
        antes = {str(p.relative_to(origen)): (p.read_bytes(), p.stat().st_mtime_ns) for p in origen.rglob("*") if p.is_file()}
        ocupado = self.modelos / "Agregados" / "Coleccion"
        ocupado.mkdir(parents=True)
        (ocupado / "intacto.txt").write_bytes(b"No pisar")
        identificador = self.preparar_copia([origen], "Animales", "Aves")
        self.assertFalse((ocupado.parent / "Coleccion (2)").exists())
        self.assertEqual(agregados.estado(identificador)["total"], 4)
        self.assertEqual(app.listar_respaldos(), [])
        self.assertTrue(agregados.confirmar(identificador)["ok"])
        res = self.esperar_agregado(identificador, {"listo", "error"})
        self.assertEqual(res["estado"], "listo", res)
        self.assertEqual(len(res["nuevos"]), 2)
        self.assertEqual(res["copiados"], 4)
        destino = ocupado.parent / "Coleccion (2)"
        for nombre, (contenido, _) in antes.items():
            self.assertEqual((destino / nombre).read_bytes(), contenido)
        self.assertEqual(antes, {str(p.relative_to(origen)): (p.read_bytes(), p.stat().st_mtime_ns) for p in origen.rglob("*") if p.is_file()})
        self.assertEqual((ocupado / "intacto.txt").read_bytes(), b"No pisar")
        self.assertEqual(len(app.listar_respaldos()), 1)
        copia = app.listar_respaldos()[0]["archivo"]
        self.assertEqual(self.leer_copia(copia, "SELECT * FROM reglas_carpeta"), [])
        db.cerrar()
        app.recargar()
        for rel in res["nuevos"]:
            self.assertEqual((app.modelo_vista(app.POR_REL[rel])["c"], app.modelo_vista(app.POR_REL[rel])["s"]), ("Animales", "Aves"))

    def test_archivos_sueltos_carpetas_unicas_y_cancelacion(self):
        origen = self.base / "nuevo.cdr"
        origen.write_bytes(b"original")
        identificador = self.preparar_copia([origen])
        self.assertTrue(agregados.cancelar(identificador)["ok"])
        self.assertFalse((self.modelos / "Agregados").exists())
        self.assertIn("error", agregados.confirmar(identificador))
        uno = self.copiar([origen])
        dos = self.copiar([origen])
        self.assertEqual(len(uno["nuevos"]), 1)
        self.assertEqual(len(dos["nuevos"]), 1)
        self.assertEqual((self.modelos / "Agregados" / "nuevo" / "nuevo.cdr").read_bytes(), b"original")
        self.assertEqual((self.modelos / "Agregados" / "nuevo (2)" / "nuevo.cdr").read_bytes(), b"original")
        self.assertEqual(origen.read_bytes(), b"original")

    def test_rechaza_todos_los_ejecutables_incluso_anidados_antes_de_copiar(self):
        for extension in agregados.PROHIBIDAS:
            with self.subTest(extension=extension):
                malo = self.base / ("malo" + extension.upper())
                malo.write_bytes(b"no ejecutar")
                with self.assertRaises(ValueError):
                    agregados.planificar([str(malo)], str(self.modelos))
                carpeta = self.base / ("carpeta" + extension)
                carpeta.mkdir()
                (carpeta / malo.name).write_bytes(b"no ejecutar")
                with self.assertRaises(ValueError):
                    agregados.planificar([str(carpeta)], str(self.modelos))
                self.assertIn("error", app.guardar_archivo("animal", "modelo", malo.name, b"no ejecutar"))
        self.assertFalse((self.modelos / "Agregados").exists())

    def test_rechaza_enlaces_y_copiar_la_biblioteca_sobre_si_misma(self):
        with self.assertRaises(ValueError):
            agregados.planificar([str(self.modelos)], str(self.modelos))
        with mock.patch.object(agregados.os, "lstat") as st:
            st.return_value.st_mode = 0
            st.return_value.st_file_attributes = 0x400
            with self.assertRaises(ValueError):
                agregados.planificar([str(self.modelos / "animal")], str(self.modelos))
        self.assertFalse((self.modelos / "Agregados").exists())

    def test_falta_espacio_o_respaldo_no_inicia_copia(self):
        origen = self.base / "nuevo.cdr"
        origen.write_bytes(b"original")
        with mock.patch.object(agregados.shutil, "disk_usage") as disco:
            disco.return_value.free = 0
            with self.assertRaisesRegex(ValueError, "espacio"):
                agregados.planificar([str(origen)], str(self.modelos))
        identificador = self.preparar_copia([origen], "Animales", "Aves")
        with mock.patch.object(app, "respaldar_base", return_value={"error": "No se pudo respaldar"}):
            self.assertTrue(agregados.confirmar(identificador)["ok"])
            res = self.esperar_agregado(identificador, {"error"})
            self.assertIn("respaldar", res["error"])
        self.assertFalse((self.modelos / "Agregados").exists())

    def test_confirmacion_http_no_acepta_rutas_arbitrarias(self):
        self.iniciar_http()
        codigo, _ = self.pedir("/api/agregados/confirmar", {"id": "inventado", "rutas": [str(self.modelos)]})
        self.assertEqual(codigo, 400)
        self.assertEqual(self.pedir("/api/agregados/preparar", {"rutas": [str(self.modelos)]})[0], 404)
        self.assertFalse((self.modelos / "Agregados").exists())

    def test_subir_foto_http_persiste_sin_reindexar_y_sirve_archivo(self):
        self.iniciar_http()
        thumb = Path(app.CACHE_THUMBS)
        thumb.mkdir()
        cache = thumb / (hashlib.md5(b"animal").hexdigest() + ".jpg")
        cache.write_bytes(b"vista vieja")
        req = urllib.request.Request(self.url + "/api/subir?rel=animal&tipo=imagen&nombre=animal.png", self.foto(), method="POST")
        with urllib.request.urlopen(req) as respuesta:
            self.assertTrue(json.load(respuesta)["ok"])
        self.assertFalse(cache.exists())
        codigo, dato = self.pedir("/api/datos")
        self.assertEqual(dato["modelos"][0]["img"], 1)
        ficha = self.pedir("/api/modelo?rel=animal")[1]
        self.assertEqual(ficha["preview"], "animal.png")
        path = urllib.parse.quote(str(self.modelos / "animal" / "animal.png"))
        with urllib.request.urlopen(self.url + "/api/archivo?p=" + path) as respuesta:
            self.assertEqual(respuesta.read(), self.foto())
            self.assertEqual(respuesta.headers["Cache-Control"], "no-cache")
        db.cerrar()
        app.recargar()
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["img"], 1)
        self.assertEqual(app.POR_REL["animal"]["preview"], "animal.png")
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=3)
        self.iniciar_http()
        self.assertEqual(self.pedir("/api/datos")[1]["modelos"][0]["img"], 1)

    def test_drop_python_usa_ruta_real_y_destino_no_nombre_del_navegador(self):
        class Evento:
            def __init__(self):
                self.handlers = []
            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self
        eventos = types.SimpleNamespace(dragover=Evento(), drop=Evento())
        ventana = mock.Mock()
        ventana.dom.document.events = eventos
        ventana.evaluate_js.return_value = {"categoria": "Animales", "subcategoria": "Aves"}
        api = mock.Mock()
        api.preparar_arrastre.return_value = {"ok": True, "id": "identificador"}
        modulo = types.SimpleNamespace(DOMEventHandler=lambda callback, **kwargs: callback)
        with mock.patch.dict(sys.modules, {"webview.dom": modulo}):
            lanzador.registrar_arrastre(ventana, api)
        self.assertEqual(len(eventos.drop.handlers), 1)
        real = str(self.base / "origen real")
        eventos.drop.handlers[0]({"clientX": 20, "clientY": 30,
                                 "dataTransfer": {"files": [{"name": "no usar esto", "pywebviewFullPath": real}]}})
        api.preparar_arrastre.assert_called_once_with([real], "Animales", "Aves")
        api.preparar_arrastre.reset_mock()
        eventos.drop.handlers[0]({"dataTransfer": {"files": [{"name": "sin ruta"}]}})
        api.preparar_arrastre.assert_not_called()
        self.assertIn("abre la Biblioteca desde su icono", ventana.evaluate_js.call_args.args[0])

    def test_lectura_parcial_identica_a_completa_formatos_grosores_3dm(self):
        for nombre, tipo, contenido in [("modelo_3mm.lbrn2", "modelo", b"lb"), ("objeto.3dm", "modelo", b"3d"),
                                       ("manual.pdf", "manual", b"pdf"), ("animal.png", "imagen", self.foto())]:
            self.assertTrue(app.guardar_archivo("animal", tipo, nombre, contenido)["ok"])
        parcial = dict(app.POR_REL["animal"])
        with mock.patch.object(sys, "argv", ["indexar.py"]), contextlib.redirect_stdout(io.StringIO()):
            indexar.indexar()
        completo = json.loads(Path(app.INDICE).read_text(encoding="utf-8"))["modelos"][0]
        self.assertEqual(parcial, completo)
        self.assertTrue(parcial["tiene_3d"])
        self.assertTrue(parcial["tiene_manual"])
        self.assertTrue(parcial["tiene_lightburn"])
        self.assertEqual(parcial["grosores"], ["3mm"])
        self.assertEqual(parcial["formatos"], ["cdr", "lbrn2"])

    def test_reemplazar_y_restaurar_foto_actualiza_indice_y_miniatura(self):
        uno, dos = self.foto(), self.foto() + b"version dos"
        self.assertTrue(app.guardar_archivo("animal", "imagen", "foto.png", uno)["ok"])
        self.assertTrue(app.guardar_archivo("animal", "imagen", "foto.png", dos)["ok"])
        version = db.versiones("animal")[0]
        self.assertTrue(app.restaurar_version("animal", version["id"])["ok"])
        self.assertEqual((self.modelos / "animal" / "foto.png").read_bytes(), uno)
        app.recargar()
        self.assertEqual(app.POR_REL["animal"]["preview"], "foto.png")
        self.assertTrue(app.POR_REL["animal"]["tiene_imagen"])

    def test_recuperar_modelo_y_archivo_relee_sin_reindexar(self):
        carpeta = Path(app.PAPELERA) / "rescatado"
        carpeta.mkdir(parents=True)
        (carpeta / "modelo.cdr").write_bytes(b"recuperar")
        (carpeta / "foto.png").write_bytes(self.foto())
        origen = self.modelos / "rescatado"
        db.a_papelera("modelo", "rescatado", "Rescatado", str(origen), str(carpeta))
        pid = db.papelera()[0]["id"]
        self.assertTrue(app.restaurar_papelera(pid)["ok"])
        app.recargar()
        self.assertEqual(app.modelo_vista(app.POR_REL["rescatado"])["img"], 1)
        manual = Path(app.PAPELERA) / "manual.pdf"
        manual.write_bytes(b"manual")
        db.a_papelera("archivo", "rescatado", "manual.pdf", str(origen / "manual.pdf"), str(manual))
        self.assertTrue(app.restaurar_papelera(db.papelera()[0]["id"])["ok"])
        app.recargar()
        self.assertTrue(app.POR_REL["rescatado"]["tiene_manual"])

    def test_indice_atomico_fallo_conserva_anterior(self):
        anterior = Path(app.INDICE).read_bytes()
        with mock.patch.object(indexar.os, "replace", side_effect=OSError("Sin espacio")):
            with self.assertRaises(OSError):
                app.recargar_parcial("animal")
        self.assertEqual(Path(app.INDICE).read_bytes(), anterior)
        self.assertEqual(list(self.base.glob(".indice-*")), [])

    def test_copia_por_http_no_bloquea_consultas_y_no_repite_confirmacion(self):
        origen = self.base / "suelto.cdr"
        origen.write_bytes(b"original")
        identificador = self.preparar_copia([origen])
        copiando, liberar = threading.Event(), threading.Event()
        def pausar(*args):
            copiando.set()
            self.assertTrue(liberar.wait(5))
        self.iniciar_http()
        with mock.patch.object(agregados.shutil, "copystat", side_effect=pausar):
            try:
                self.assertEqual(self.pedir("/api/agregados/confirmar", {"id": identificador})[0], 200)
                self.assertTrue(copiando.wait(3))
                self.assertEqual(self.pedir("/api/datos")[0], 200)
                estado = self.pedir("/api/agregados/estado?id=" + identificador)[1]
                self.assertEqual(estado["estado"], "copiando")
                self.assertEqual(estado["bytes_copiados"], len(b"original"))
                self.assertEqual(self.pedir("/api/agregados/confirmar", {"id": identificador})[0], 400)
            finally:
                liberar.set()
            self.assertEqual(self.esperar_agregado(identificador, {"listo", "error"})["estado"], "listo")

    def test_cambio_del_original_tras_confirmacion_no_se_pisa(self):
        origen = self.base / "cambiado.cdr"
        origen.write_bytes(b"antes")
        identificador = self.preparar_copia([origen])
        origen.write_bytes(b"ahora editado por el papa")
        self.assertTrue(agregados.confirmar(identificador)["ok"])
        res = self.esperar_agregado(identificador, {"error"})
        self.assertIn("cambió", res["error"])
        self.assertEqual(origen.read_bytes(), b"ahora editado por el papa")

    def test_ocultos_no_aparecen_en_duplicados(self):
        corte = self.modelos / "animal" / "dibujo.cdr"
        corte.write_bytes(b"modelo repetido" * 50)
        app.recargar_parcial("animal")
        otro = self.modelos / "otro"
        otro.mkdir()
        (otro / "dibujo.cdr").write_bytes(corte.read_bytes())
        app.releer_arbol(str(otro))
        self.assertEqual(len(app.buscar_duplicados()), 1)
        self.assertTrue(app.borrar_modelo("otro")["ok"])
        self.assertEqual(app.buscar_duplicados(), [])
        self.assertEqual((otro / "dibujo.cdr").read_bytes(), corte.read_bytes())

    def test_regla_nombre_y_categoria_cambian_al_tiro_sin_releer(self):
        db.guardar_cat("Nueva", propia=True)
        self.assertTrue(app.marcar_carpeta(str(self.modelos / "animal"), "Nueva")["ok"])
        # Una regla sin subcategoría no arrastra una subcategoría automática anterior.
        db.guardar_meta("animal", {"categoria": "", "subcategoria": None})
        self.assertEqual((app.modelo_vista(app.POR_REL["animal"])["c"], app.modelo_vista(app.POR_REL["animal"])["s"]), ("Nueva", ""))
        self.assertTrue(app.guardar_edicion("animal", {"nombre": "Nombre nuevo", "categoria": "Animales", "subcategoria": "Aves"})["ok"])
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["n"], "Nombre nuevo")
        db.cerrar()
        app.recargar()
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["n"], "Nombre nuevo")

    def test_foto_en_biblioteca_extra_conserva_ruta_y_marca(self):
        extra = self.base / "Extra"
        modelo = extra / "modelo"
        modelo.mkdir(parents=True)
        (modelo / "modelo.cdr").write_bytes(b"extra")
        Path(app.CONFIG).write_text(json.dumps({"biblioteca": str(self.modelos), "bibliotecas_extra": [str(extra)]}), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["indexar.py"]), contextlib.redirect_stdout(io.StringIO()):
            indexar.indexar()
        app.recargar()
        rel = os.path.join("[Extra]", "modelo")
        self.assertTrue(app.guardar_archivo(rel, "imagen", "foto.png", self.foto())["ok"])
        app.recargar()
        self.assertEqual(app.POR_REL[rel]["raiz"], str(extra))
        self.assertEqual(app.POR_REL[rel]["preview"], "foto.png")
        self.assertEqual(app.modelo_vista(app.POR_REL[rel])["img"], 1)

    def test_agregar_usa_la_principal_actual_no_config_en_memoria_antigua(self):
        origen = self.base / "suelto.cdr"
        origen.write_bytes(b"original")
        app.CFG["biblioteca"] = str(self.base / "principal vieja")
        identificador = self.preparar_copia([origen])
        self.assertEqual(agregados.TRABAJOS[identificador]["_raiz"], app.RAIZ)
        self.assertTrue(agregados.cancelar(identificador)["ok"])

    def test_subir_sin_espacio_conserva_archivo_actual(self):
        actual = self.modelos / "animal" / "dibujo.cdr"
        original = actual.read_bytes()
        with mock.patch.object(app.os, "replace", side_effect=OSError("Sin espacio")):
            self.assertIn("error", app.guardar_archivo("animal", "modelo", "dibujo.cdr", b"nuevo"))
        self.assertEqual(actual.read_bytes(), original)
        self.assertEqual(list(actual.parent.glob(".carga-*")), [])

    def test_paquete_incluye_importador_y_novedades(self):
        import construir_paquete
        self.assertIn("agregados.py", construir_paquete.INCLUIR)
        self.assertIn("version.json", construir_paquete.INCLUIR)

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
