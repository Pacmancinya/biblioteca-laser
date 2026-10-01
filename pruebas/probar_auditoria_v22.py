# -*- coding: utf-8 -*-
"""Regresiones de la tercera parte. Solo bases, modelos y servidores temporales.

Uso: python pruebas/probar_auditoria_v22.py
"""
import concurrent.futures
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from probar_v22 import app, db, indexar, formatos
import probar_v22 as soporte
import configuracion
import migrar


class Auditoria22(unittest.TestCase):
    setUp = soporte.Version22.setUp
    tearDown = soporte.Version22.tearDown
    iniciar_http = soporte.Version22.iniciar_http
    pedir = soporte.Version22.pedir
    foto = soporte.Version22.foto

    def indexar(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ok, error = app.indexar_ahora()
        self.assertTrue(ok, error)

    def modelo_nuevo(self, rel):
        carpeta = self.modelos / rel
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "modelo.cdr").write_bytes(b"modelo temporal")
        app.releer_arbol(str(carpeta))
        return carpeta

    def venta(self, cantidad=1, rel="animal"):
        return {"rel": rel, "cantidad": cantidad, "precio_unit": 1000,
                "costo_unit": 100, "item": "Animal", "canal": "feria"}

    def subir_http(self, tipo, nombre, datos=b"contenido de prueba"):
        ruta = "/api/subir?rel=animal&tipo=" + tipo + "&nombre=" + nombre
        req = urllib.request.Request(self.url + ruta, datos, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as respuesta:
                return respuesta.status, json.load(respuesta)
        except urllib.error.HTTPError as respuesta:
            return respuesta.code, json.load(respuesta)

    def test_01_padre_oculta_solo_padre_y_avisa_submodelos(self):
        carpeta = self.modelo_nuevo("animal/hijo")
        contenido = (carpeta / "modelo.cdr").read_bytes()
        self.iniciar_http()
        codigo, ficha = self.pedir("/api/modelo?rel=animal")
        self.assertEqual(codigo, 200)
        self.assertEqual(ficha["submodelos"], 1)
        self.assertTrue(app.borrar_modelo("animal")["ok"])
        self.assertFalse((db.meta(os.path.join("animal", "hijo")) or {}).get("oculto"))
        self.assertEqual((carpeta / "modelo.cdr").read_bytes(), contenido)

    def test_02_subidas_validan_tipo_en_servidor(self):
        self.iniciar_http()
        for tipo in ("imagen", "manual", "modelo", "inventado"):
            for ext in ("exe", "bat", "lnk", "cmd", "ps1", "com", "vbs", "scr"):
                with self.subTest(tipo=tipo, ext=ext):
                    codigo, res = self.subir_http(tipo, "peligro." + ext)
                    self.assertEqual(codigo, 400)
                    self.assertIn("error", res)
                    self.assertFalse((self.modelos / "animal" / ("peligro." + ext)).exists())
        for tipo, nombre in (("imagen", "foto.gif"), ("manual", "guia.docx"), ("modelo", "pieza.svg")):
            self.assertEqual(self.subir_http(tipo, nombre)[0], 200)
        self.assertEqual(self.subir_http("imagen", "guia.pdf")[0], 400)
        self.assertEqual(self.subir_http("modelo", "foto.jpg")[0], 400)

    def test_03_config_actual_no_se_pisa_con_cfg_viejo(self):
        otra = self.base / "otra"
        otra.mkdir()
        app.guardar_config({"biblioteca": str(otra), "bibliotecas_extra": [str(self.modelos)]})
        app.CFG = {"biblioteca": "carpeta vieja"}
        exe = self.base / "CorelDRW.exe"
        exe.write_bytes(b"programa ficticio")
        self.assertTrue(app.elegir_programa("corel", str(exe))["ok"])
        self.iniciar_http()
        self.assertEqual(self.pedir("/api/config/whatsapp", {"numero": "56912345678"})[0], 200)
        guardada = configuracion.leer(app.CONFIG)
        self.assertEqual(guardada["biblioteca"], str(otra))
        self.assertEqual(guardada["bibliotecas_extra"], [str(self.modelos)])
        self.assertEqual(guardada, app.CFG)
        self.assertFalse(Path(app.CONFIG).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_03_config_atomica_si_falla_replace(self):
        antes = Path(app.CONFIG).read_bytes()
        with mock.patch.object(configuracion.os, "replace", side_effect=OSError("sin espacio")):
            with self.assertRaises(OSError):
                app.guardar_config({"whatsapp": "nuevo"})
        self.assertEqual(Path(app.CONFIG).read_bytes(), antes)
        self.assertEqual(list(self.base.glob(".config-*")), [])

    def test_03_agregar_primera_carpeta_sin_configuracion(self):
        Path(app.CONFIG).unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            resultado = app.agregar_carpeta(str(self.modelos))
        self.assertTrue(resultado.get("ok"), resultado)
        self.assertEqual(configuracion.leer(app.CONFIG)["biblioteca"], str(self.modelos))
        self.assertEqual(app.CFG["biblioteca"], str(self.modelos))
        self.assertIn("animal", app.POR_REL)

    def respaldo(self):
        cliente = db.guardar_cliente({"nombre": "Cliente del respaldo", "telefono": "123"})
        db.guardar_meta("animal", {"cliente_id": cliente, "stock": 20, "precio": 2000,
                                   "oculto": 1, "principal": "dibujo.cdr"})
        db.guardar_pedido({"cliente_id": cliente, "rel": "animal", "precio": 5000, "abonado": 1000})
        venta = self.venta(2)
        venta["cliente_id"] = cliente
        db.guardar_venta(venta)
        db.guardar_cat("Propia", orden=4, propia=True, oculta=True)
        db.crear_subcat("Propia", "Sub propia")
        db.guardar_regla("animal", "Propia", "Sub propia")
        db.agregar_sugerencia("Una idea guardada")
        db.guardar_material({"nombre": "Material", "ancho": 100, "largo": 100, "precio": 2000})
        db.guardar_costo_fijo({"nombre": "Máquina", "monto": 10000, "horas": 100, "grupo": "Equipos"})
        db.guardar_ajuste("utilidad", 55)
        return app.exportar_datos()

    def vaciar_datos(self):
        with db.transaccion() as cx:
            for tabla in ("modelos", "clientes", "pedidos", "ventas", "sugerencias", "cats", "subcats", "reglas_carpeta", "materiales", "costos_fijos", "ajustes", "importaciones"):
                cx.execute("DELETE FROM " + tabla)

    def test_04_respaldo_completo_remapea_no_descontar_no_duplicar(self):
        respaldo = self.respaldo()
        self.assertEqual(respaldo["formato_version"], 3)
        self.vaciar_datos()
        db.guardar_cliente({"nombre": "Otro cliente, id distinto"})
        self.assertTrue(app.importar_datos(respaldo)["ok"])
        nuevo = next(c for c in db.clientes() if c["nombre"] == "Cliente del respaldo")["id"]
        self.assertNotEqual(nuevo, respaldo["clientes"][0]["id"])
        self.assertEqual(db.meta("animal")["cliente_id"], nuevo)
        self.assertEqual(db.pedidos()[0]["cliente_id"], nuevo)
        self.assertEqual(db.ventas()[0]["cliente_id"], nuevo)
        self.assertEqual(db.meta("animal")["stock"], 18)
        self.assertEqual(db.meta("animal")["oculto"], 1)
        self.assertEqual(db.meta("animal")["principal"], "dibujo.cdr")
        self.assertEqual(db.reglas_carpeta()[0]["categoria"], "Propia")
        self.assertEqual(db.sugerencias()[0]["texto"], "Una idea guardada")
        self.assertEqual(db.fila("SELECT * FROM cats WHERE nombre='Propia'")["oculta"], 1)
        self.assertEqual(db.ajuste("utilidad"), "55")
        cantidades = {t: db.fila("SELECT COUNT(*) n FROM " + t)["n"] for t in ("clientes", "pedidos", "ventas", "sugerencias", "materiales", "costos_fijos")}
        self.assertTrue(app.importar_datos(respaldo)["ok"])
        self.assertEqual(cantidades, {t: db.fila("SELECT COUNT(*) n FROM " + t)["n"] for t in cantidades})
        self.assertEqual(db.meta("animal")["stock"], 18)

    def test_04_fallo_tardio_revierte_todas_las_tablas_y_hay_copia(self):
        antes = db.meta_todos()
        datos = {"modelos": [{"rel": "nuevo", "stock": 50}], "clientes": [{"id": 20, "nombre": "Nuevo"}],
                 "ventas": [{"rel": "nuevo", "cantidad": 2}], "reglas_carpeta": [{"categoria": "Sin carpeta"}]}
        res = app.importar_datos(datos, "reemplazar")
        self.assertIn("error", res)
        self.assertEqual(db.meta_todos(), antes)
        self.assertEqual(db.clientes(), [])
        self.assertEqual(db.ventas(), [])
        self.assertEqual(len(app.listar_respaldos()), 1)

    def test_04_dos_ventas_identicas_se_conservan_y_no_se_duplican(self):
        dato = self.venta()
        dato["fecha"] = 1234567890
        db.guardar_venta(dato)
        db.guardar_venta(dato)
        respaldo = app.exportar_datos()
        self.vaciar_datos()
        self.assertTrue(app.importar_datos(respaldo)["ok"])
        self.assertEqual(len(db.ventas()), 2)
        self.assertTrue(app.importar_datos(respaldo)["ok"])
        self.assertEqual(len(db.ventas()), 2)

    def test_04_fallo_al_final_detectando_revierte_importacion(self):
        antes = db.meta_todos()
        with mock.patch.object(app, "detectar_no_encontrados", side_effect=ValueError("fallo final")):
            self.assertIn("error", app.importar_datos({"modelos": [{"rel": "nuevo", "precio": 1000}]}, "reemplazar"))
        self.assertEqual(db.meta_todos(), antes)

    def test_05_disco_ausente_no_dialogo_no_vaciar_indice(self):
        antes = Path(app.INDICE).read_bytes()
        ruta = self.base / "disco desconectado"
        app.guardar_config({"biblioteca": str(ruta)})
        with mock.patch.object(indexar, "elegir_carpeta", side_effect=AssertionError("No abrir diálogos")):
            inicio = time.monotonic()
            ok, error = app.indexar_ahora()
        self.assertFalse(ok)
        self.assertIn(str(ruta), error)
        self.assertIn("disco", error)
        self.assertLess(time.monotonic() - inicio, 2)
        self.assertEqual(Path(app.INDICE).read_bytes(), antes)
        self.assertIn("animal", app.POR_REL)

    def test_05_sin_config_no_usa_ruta_del_autor(self):
        Path(app.CONFIG).write_text("{}", encoding="utf-8")
        antes = Path(app.INDICE).read_bytes()
        with mock.patch.object(indexar, "elegir_carpeta", side_effect=AssertionError()):
            self.assertEqual(indexar.obtener_raiz(), "")
            self.assertFalse(app.indexar_ahora()[0])
        self.assertEqual(Path(app.INDICE).read_bytes(), antes)
        self.assertEqual(indexar.RAIZ_POR_DEFECTO, "")

    def test_06_archivo_bloquea_app_fuera_y_traversal(self):
        self.iniciar_http()
        for ruta in (app.CONFIG, db.DB_PATH, str(self.base / "secreto.txt"), str(self.modelos / ".." / "config.json")):
            codigo, res = self.pedir("/api/archivo?p=" + urllib.parse.quote(ruta))
            self.assertEqual(codigo, 403)
            self.assertIn("error", res)
        ruta = self.modelos / "animal" / "dibujo.cdr"
        with urllib.request.urlopen(self.url + "/api/archivo?p=" + urllib.parse.quote(str(ruta))) as respuesta:
            self.assertEqual(respuesta.read(), b"cdr de prueba")
        app.guardar_config({"biblioteca": str(self.base)})
        self.assertFalse(app.ruta_segura(app.CONFIG))
        self.assertFalse(app.ruta_segura(db.DB_PATH))

    def test_06_enlace_a_config_fuera_de_modelos_no_se_sirve(self):
        enlace = self.modelos / "animal" / "enlace.txt"
        try:
            enlace.symlink_to(Path(app.CONFIG))
        except OSError:
            # Windows sin permiso de enlaces: simular la resolución del sistema,
            # conservando la validación real de límites y raíces.
            resolver = app.os.path.realpath
            with mock.patch.object(app.os.path, "realpath", side_effect=lambda p: resolver(app.CONFIG) if os.fspath(p) == str(enlace) else resolver(p)):
                self.assertFalse(app.ruta_segura(str(enlace)))
            return
        self.assertFalse(app.ruta_segura(str(enlace)))

    def test_08_foto_nueva_gana_preview_y_revision_sobrevive_releer(self):
        app.guardar_archivo("animal", "imagen", "animal.png", self.foto())
        anterior = app.modelo_vista(app.POR_REL["animal"])["revision"]
        app.guardar_archivo("animal", "imagen", "otra.png", self.foto())
        self.assertEqual(app.POR_REL["animal"]["preview"], "otra.png")
        self.assertNotEqual(app.modelo_vista(app.POR_REL["animal"])["revision"], anterior)
        self.indexar()
        self.assertEqual(app.POR_REL["animal"]["preview"], "otra.png")

    def test_09_subida_interrumpida_conserva_original_sin_historial(self):
        destino = self.modelos / "animal" / "dibujo.cdr"
        antes = destino.read_bytes()
        self.iniciar_http()
        with socket.create_connection(("127.0.0.1", self.servidor.server_port), timeout=5) as sock:
            sock.sendall(b"POST /api/subir?rel=animal&tipo=modelo&nombre=dibujo.cdr HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\nConnection: close\r\n\r\ncortado")
            sock.shutdown(socket.SHUT_WR)
            recibido = b""
            while True:
                bloque = sock.recv(8192)
                if not bloque:
                    break
                recibido += bloque
        self.assertIn(b"400", recibido.split(b"\r\n")[0])
        self.assertIn("carga se cortó", recibido.decode("utf-8"))
        self.assertEqual(destino.read_bytes(), antes)
        self.assertEqual(db.versiones("animal"), [])
        self.assertEqual(list(destino.parent.glob(".carga-*")), [])

    def test_10_mensajes_disco_y_archivo_perdido(self):
        self.iniciar_http()
        ruta = self.modelos / "animal" / "dibujo.cdr"
        ruta.unlink()
        res = self.pedir("/api/abrir?p=" + urllib.parse.quote(str(ruta)))[1]
        self.assertIn("No encuentro el archivo", res["error"])
        self.assertNotIn("ruta no permitida", res["error"])
        self.modelos.rename(self.base / "desconectado")
        res = self.pedir("/api/carpeta?p=" + urllib.parse.quote(str(self.modelos / "animal")))[1]
        self.assertIn("¿Está conectado el disco?", res["error"])

    def test_11_mover_carpeta_detecta_sugiere_asocia_y_preserva_ventas(self):
        db.guardar_meta("animal", {"stock": 20, "precio": 3000, "favorito": 1})
        db.guardar_venta(self.venta(2))
        (self.modelos / "nuevo").mkdir()
        (self.modelos / "animal").rename(self.modelos / "nuevo" / "animal")
        self.indexar()
        faltan = app.no_encontrados()
        self.assertEqual(faltan[0]["rel"], "animal")
        nuevo = os.path.join("nuevo", "animal")
        self.assertEqual(faltan[0]["sugeridas"][0]["rel"], nuevo)
        self.assertEqual(db.meta("animal")["stock"], 18)
        self.assertTrue(app.resolver_no_encontrado("animal", nuevo)["ok"])
        self.assertIsNone(db.meta("animal"))
        self.assertEqual(db.meta(nuevo)["stock"], 18)
        self.assertEqual(db.meta(nuevo)["precio"], 3000)
        self.assertEqual(db.ventas()[0]["rel"], nuevo)
        self.assertEqual(app.no_encontrados(), [])

    def test_11_descartar_conserva_venta_encargo_y_archivos(self):
        db.guardar_venta(self.venta())
        db.guardar_pedido({"rel": "animal", "precio": 100})
        (self.modelos / "animal").rename(self.modelos / "movido")
        self.indexar()
        self.assertTrue(app.resolver_no_encontrado("animal", descartar=True)["ok"])
        self.assertEqual(len(db.ventas()), 1)
        self.assertEqual(len(db.pedidos()), 1)
        self.assertIsNone(db.ventas()[0]["rel"])
        self.assertTrue((self.modelos / "movido" / "dibujo.cdr").exists())

    def test_12_cambiar_raiz_avisa_antes_y_no_asocia_rel_igual_solo(self):
        otra = self.base / "biblioteca nueva"
        (otra / "animal").mkdir(parents=True)
        (otra / "animal" / "dibujo.cdr").write_bytes(b"otro modelo")
        antes = Path(app.CONFIG).read_bytes()
        res = app.cambiar_carpeta(str(otra))
        self.assertTrue(res["confirmar"])
        self.assertEqual(res["afectados"], 1)
        self.assertEqual(Path(app.CONFIG).read_bytes(), antes)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(app.cambiar_carpeta(str(otra), True)["ok"])
        self.assertEqual(app.no_encontrados()[0]["rel"], "animal")
        self.assertTrue(app.modelo_vista(app.POR_REL["animal"])["oculto"])
        self.assertTrue(app.resolver_no_encontrado("animal", "animal")["ok"])
        self.assertFalse(app.modelo_vista(app.POR_REL["animal"])["oculto"])

    def test_13_editar_borrar_venta_ajusta_diferencia(self):
        db.guardar_meta("animal", {"stock": 100})
        vid = db.guardar_venta(self.venta(4))
        self.assertEqual(db.meta("animal")["stock"], 96)
        db.guardar_venta(self.venta(6), vid)
        self.assertEqual(db.meta("animal")["stock"], 94)
        db.guardar_venta(self.venta(2), vid)
        self.assertEqual(db.meta("animal")["stock"], 98)
        db.borrar_venta(vid)
        self.assertEqual(db.meta("animal")["stock"], 100)

    def test_13_cambiar_modelo_y_stock_cero_no_inventa_existencias(self):
        self.modelo_nuevo("otro")
        db.guardar_meta("animal", {"stock": 2})
        db.guardar_meta("otro", {"stock": 10})
        vid = db.guardar_venta(self.venta(5))
        self.assertEqual(db.meta("animal")["stock"], 0)
        db.guardar_venta(self.venta(3, "otro"), vid)
        self.assertEqual(db.meta("animal")["stock"], 2)
        self.assertEqual(db.meta("otro")["stock"], 7)
        db.borrar_venta(vid)
        self.assertEqual(db.meta("otro")["stock"], 10)

    def test_13_cuarenta_ventas_http_simultaneas_stock_exacto(self):
        db.guardar_meta("animal", {"stock": 100})
        self.iniciar_http()
        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as grupo:
            respuestas = list(grupo.map(lambda _: self.pedir("/api/venta", self.venta()), range(40)))
        self.assertTrue(all(codigo == 200 for codigo, _ in respuestas))
        self.assertEqual(len(db.ventas()), 40)
        self.assertEqual(db.meta("animal")["stock"], 60)

    def test_13_fallo_insertar_no_descontar_stock(self):
        db.guardar_meta("animal", {"stock": 100})
        ejecutar = db.ejecutar
        def fallo(sql, args=()):
            if sql.startswith("INSERT INTO ventas"):
                raise sqlite3.OperationalError("fallo de prueba")
            return ejecutar(sql, args)
        with mock.patch.object(db, "ejecutar", side_effect=fallo):
            with self.assertRaises(sqlite3.OperationalError):
                db.guardar_venta(self.venta(4))
        self.assertEqual(db.meta("animal")["stock"], 100)
        self.assertEqual(db.ventas(), [])

    def test_15_excepcion_http_json_log_y_sigue_atendiendo(self):
        self.iniciar_http()
        with mock.patch.object(db, "metricas", side_effect=RuntimeError("detalle técnico de prueba")):
            codigo, res = self.pedir("/api/metricas")
        self.assertEqual(codigo, 500)
        self.assertIn("error", res)
        self.assertIn("detalle técnico de prueba", (self.base / "errores.log").read_text(encoding="utf-8"))
        self.assertEqual(self.pedir("/api/datos")[0], 200)

    def test_16_abrir_ficha_refresca_archivos_y_nombre_actual(self):
        self.iniciar_http()
        (self.modelos / "animal" / "nuevo_6mm.svg").write_text('<svg/>', encoding="utf-8")
        db.guardar_meta("animal", {"nombre": "Nombre nuevo"})
        ficha = self.pedir("/api/modelo?rel=animal")[1]
        self.assertIn("nuevo_6mm.svg", ficha["archivos"]["corte"])
        self.assertIn("6mm", ficha["grosores"])
        self.assertEqual(ficha["vista"]["n"], "Nombre nuevo")

    def test_18_principal_persiste_tras_indexar_completo(self):
        (self.modelos / "animal" / "z.svg").write_text('<svg/>', encoding="utf-8")
        self.assertTrue(app.hacer_principal("animal", "z.svg")["ok"])
        self.indexar()
        self.assertEqual(db.meta("animal")["principal"], "z.svg")
        self.assertEqual(app.POR_REL["animal"]["archivos"]["corte"][0], "z.svg")

    def test_19_medidas_solo_con_unidades_confiables(self):
        ruta = self.modelos / "animal" / "fisico.svg"
        ruta.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="30mm" viewBox="0 0 20 30"><rect width="20" height="30"/></svg>', encoding="utf-8")
        self.assertEqual(formatos.medidas_confiables(str(ruta)), {"ancho": 20, "alto": 30})
        ruta.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 30"><rect width="20" height="30"/></svg>', encoding="utf-8")
        self.assertIsNone(formatos.medidas_confiables(str(ruta)))

    def test_20_renombrar_mueve_huerfanos_subcats_reglas_y_futuros(self):
        db.guardar_meta("desaparecido", {"categoria": "Animales", "notas": "conservar"})
        db.guardar_regla("carpeta futura", "Animales", "Aves")
        self.assertTrue(app.renombrar_categoria("Animales", "Naturaleza")["ok"])
        self.assertEqual(db.meta("desaparecido")["categoria"], "Naturaleza")
        self.assertEqual(db.reglas_carpeta()[0]["categoria"], "Naturaleza")
        self.assertTrue(db.fila("SELECT * FROM subcats WHERE categoria='Naturaleza' AND subcategoria='Aves'"))
        nuevo = copy.deepcopy(app.POR_REL["animal"])
        nuevo.update(rel="futuro", categoria="Animales")
        self.assertEqual(app.modelo_vista(nuevo)["c"], "Naturaleza")
        self.assertIn("error", app.borrar_categoria("Naturaleza"))
        self.assertTrue(app.borrar_categoria("Naturaleza", "Hogar y muebles")["ok"])
        self.assertEqual(db.meta("desaparecido")["categoria"], "Hogar y muebles")
        self.assertEqual(app.modelo_vista(nuevo)["c"], "Hogar y muebles")

    def test_21_abonos_pagados_sumados_sin_duplicar_venta_feria(self):
        db.guardar_venta(self.venta(2))
        db.guardar_pedido({"precio": 5000, "abonado": 1000, "pagado": 0})
        db.guardar_pedido({"precio": 6000, "abonado": 6000, "pagado": 1})
        datos = db.metricas()
        self.assertEqual(datos["ventas_feria"]["venta"], 2000)
        self.assertEqual(datos["encargos"]["ingreso"], 7000)
        self.assertEqual(datos["total"]["venta"], 9000)
        self.assertEqual(datos["mes"]["venta"], 9000)

    def test_22_migracion_remapea_papelera_y_historial(self):
        desde, hacia = self.base / "vieja", self.base / "nueva"
        desde.mkdir()
        hacia.mkdir()
        ruta = desde / "_papelera" / "archivo.cdr"
        with contextlib.closing(sqlite3.connect(desde / "biblioteca.db")) as cx, cx:
            cx.executescript(db.ESQUEMA)
            cx.execute("INSERT INTO papelera(origen,destino) VALUES (?,?)", (str(desde / "Agregados" / "a.cdr"), str(ruta)))
            cx.execute("INSERT INTO versiones(respaldo) VALUES (?)", (str(desde / "Agregados" / "_versiones_anteriores" / "a.cdr"),))
        self.assertTrue(migrar.traer(str(desde), str(hacia))["ok"])
        with contextlib.closing(sqlite3.connect(hacia / "biblioteca.db")) as cx:
            origen, destino = cx.execute("SELECT origen,destino FROM papelera").fetchone()
            self.assertEqual(origen, str(hacia / "Agregados" / "a.cdr"))
            self.assertEqual(destino, str(hacia / "_papelera" / "archivo.cdr"))

    def test_23_indexacion_informa_avance(self):
        mensajes = []
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(app.indexar_ahora(avance=mensajes.append)[0])
        self.assertTrue(any("Ordenando tu biblioteca" in m for m in mensajes))

    def test_24_busqueda_cancelable_no_toca_modelos(self):
        cancelar = threading.Event()
        cancelar.set()
        antes = Path(app.INDICE).read_bytes()
        with self.assertRaises(InterruptedError):
            app.buscar_duplicados(cancelar=cancelar)
        self.assertEqual(Path(app.INDICE).read_bytes(), antes)
        self.assertFalse(db.meta("animal")["oculto"])

    def test_25_cliente_pendiente_impide_borrar_y_entregado_desvincula_todo(self):
        cid = db.guardar_cliente({"nombre": "Antes"})
        db.guardar_meta("animal", {"cliente_id": cid})
        venta = self.venta()
        venta["cliente_id"] = cid
        db.guardar_venta(venta)
        pedido = {"cliente_id": cid, "precio": 100, "estado": "pendiente"}
        pid = db.guardar_pedido(pedido)
        with self.assertRaisesRegex(ValueError, "pendientes"):
            db.borrar_cliente(cid)
        self.assertEqual(db.meta("animal")["cliente_id"], cid)
        db.guardar_cliente({"nombre": "Después"}, cid)
        self.assertEqual(db.pedidos()[0]["cliente"], "Después")
        pedido["estado"] = "entregado"
        db.guardar_pedido(pedido, pid)
        db.borrar_cliente(cid)
        self.assertEqual(db.clientes(), [])
        self.assertEqual(len(db.pedidos()), 1)
        self.assertEqual(len(db.ventas()), 1)
        self.assertIsNone(db.meta("animal")["cliente_id"])
        self.assertIsNone(db.ventas()[0]["cliente_id"])
        self.assertIsNone(db.pedidos()[0]["cliente_id"])

    def test_25_fallo_al_desvincular_rollback_conserva_cliente_y_referencias(self):
        cid = db.guardar_cliente({"nombre": "Conservar"})
        db.guardar_meta("animal", {"cliente_id": cid})
        ejecutar = db.ejecutar
        def fallo(sql, args=()):
            if sql.startswith("DELETE FROM clientes"):
                raise sqlite3.OperationalError("fallo después de desvincular")
            return ejecutar(sql, args)
        with mock.patch.object(db, "ejecutar", side_effect=fallo):
            with self.assertRaises(sqlite3.OperationalError):
                db.borrar_cliente(cid)
        self.assertEqual(db.clientes()[0]["id"], cid)
        self.assertEqual(db.meta("animal")["cliente_id"], cid)

    def test_29_contadores_excluyen_ocultos(self):
        db.guardar_meta("animal", {"favorito": 1, "oculto": 1})
        self.iniciar_http()
        self.assertEqual(self.pedir("/api/datos")[1]["total"], 0)
        self.assertEqual(db.metricas()["n_favoritos"], 0)

    def test_31_cotizar_rechaza_negativos_texto_no_finitos_cantidad_cero(self):
        for dato in ({"ancho": -2}, {"minutos": "hola"}, {"largo": float("nan")}, {"piezas": 0}, {"piezas": 1.5}):
            with self.subTest(dato=dato), self.assertRaises(ValueError):
                app.cotizar(dato)

    def test_32_costo_horas_cero_no_se_ignora_y_nuevos_rechazan(self):
        db.ejecutar("INSERT INTO costos_fijos(nombre,monto,horas,grupo) VALUES ('Antiguo',48000,0,'Mensuales')")
        costo = app.costo_por_minuto()
        self.assertEqual(costo["parcial"], 1)
        self.assertIn("horas en cero", costo["aviso"])
        with self.assertRaises(ValueError):
            db.guardar_costo_fijo({"nombre": "Nuevo", "monto": 1000, "horas": 0})

    def test_33_abono_superior_no_se_guarda(self):
        with self.assertRaisesRegex(ValueError, "abono"):
            db.guardar_pedido({"precio": 100, "abonado": 101})
        self.assertEqual(db.pedidos(), [])

    def test_34_config_bom_leida_y_guardada_sin_bom(self):
        Path(app.CONFIG).write_text(json.dumps({"biblioteca": str(self.modelos), "whatsapp": "123"}), encoding="utf-8-sig")
        self.assertEqual(app.cargar_config()["whatsapp"], "123")
        self.assertEqual(indexar.obtener_raiz(), str(self.modelos))
        app.guardar_config({"whatsapp": "456"})
        self.assertEqual(app.CFG["biblioteca"], str(self.modelos))
        self.assertFalse(Path(app.CONFIG).read_bytes().startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
