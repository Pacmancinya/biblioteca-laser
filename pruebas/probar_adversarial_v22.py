# -*- coding: utf-8 -*-
"""Cuarta parte: cada prueba crea su propia base, raíces y servidor temporales."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import stat
import types
import unittest
from unittest import mock

import probar_v22 as soporte
from probar_v22 import app, db, indexar
import seguridad_archivos
import construir_paquete
import construir_exe


class Adversarial22(unittest.TestCase):
    setUp = soporte.Version22.setUp
    tearDown = soporte.Version22.tearDown
    iniciar_http = soporte.Version22.iniciar_http
    pedir = soporte.Version22.pedir

    def venta(self, cantidad=2, rel="animal"):
        return {"rel": rel, "cantidad": cantidad, "precio_unit": 100, "costo_unit": 10,
                "item": "Animal", "canal": "feria", "fecha": 1000000000}

    def antigua(self):
        db.guardar_meta("animal", {"stock": 10})
        vid = db.guardar_venta(self.venta())
        db.ejecutar("UPDATE ventas SET stock_descontado=NULL WHERE id=?", (vid,))
        return vid

    def otra_raiz(self):
        nueva = self.base / "otra"
        (nueva / "animal").mkdir(parents=True)
        (nueva / "animal" / "otro.cdr").write_bytes(b"otro original")
        with contextlib.redirect_stdout(io.StringIO()):
            res = app.cambiar_carpeta(str(nueva), confirmado=True)
        self.assertTrue(res["ok"], res)
        return nueva

    def enlace(self, destino, original, carpeta=False):
        try:
            os.symlink(original, destino, target_is_directory=carpeta)
        except OSError as e:
            if os.name == "nt" and carpeta:
                res = subprocess.run(["cmd", "/c", "mklink", "/J", str(destino), str(original)], capture_output=True)
                if res.returncode == 0:
                    return
            self.skipTest("El sistema no permite crear enlaces: " + str(e))

    def agotar_historial(self):
        for _ in range(4):
            self.assertTrue(app.guardar_archivo("animal", "modelo", "dibujo.cdr", b"nuevo")["ok"])

    def test_01_importado_nunca_borra_original_ni_archivo_externo(self):
        original = self.modelos / "animal" / "dibujo.cdr"
        ajeno = self.base / "ajeno.cdr"
        ajeno.write_bytes(b"ajeno")
        datos = {"formato_version": 3, "modelos": [], "versiones": [
            {"id": i, "rel": "animal", "tipo": "modelo", "archivo": "dibujo.cdr", "respaldo": str(p),
             "fecha": 1, "permiso_borrado": 1, "carpeta_modelo": str(original.parent)}
            for i, p in enumerate((original, ajeno), 1)]}
        self.assertTrue(app.importar_datos(datos)["ok"])
        self.assertTrue(all(v["permiso_borrado"] == 0 for v in db.versiones("animal")))
        antes = original.read_bytes()
        for i in range(4):
            db.registrar_version("animal", "modelo", "dibujo.cdr", "", str(original.parent))
        self.assertEqual(original.read_bytes(), antes)
        self.assertEqual(ajeno.read_bytes(), b"ajeno")
        self.assertFalse(any(v["fecha"] == 1 for v in db.versiones("animal")))

    def test_01_importado_con_nombre_valido_y_carpeta_interna_no_se_borra(self):
        carpeta = self.modelos / "animal"
        ruta = Path(app.ruta_respaldo(str(carpeta), "dibujo.cdr"))
        ruta.write_bytes(b"importado")
        datos = {"modelos": [], "versiones": [{"rel": "animal", "tipo": "modelo", "archivo": "dibujo.cdr",
                  "respaldo": str(ruta), "fecha": 1, "permiso_borrado": 1, "carpeta_modelo": str(carpeta)}]}
        self.assertTrue(app.importar_datos(datos)["ok"])
        for i in range(4):
            db.registrar_version("animal", "modelo", "dibujo.cdr", "", str(carpeta))
        self.assertEqual(ruta.read_bytes(), b"importado")

    def test_01_retencion_local_solo_retira_versiones_generadas(self):
        self.agotar_historial()
        carpeta = self.modelos / "animal" / app.CARPETA_VERSIONES
        self.assertEqual(len(list(carpeta.iterdir())), 3)
        self.assertEqual(len(db.versiones("animal")), 3)
        self.assertEqual((self.modelos / "animal" / "dibujo.cdr").read_bytes(), b"nuevo")

    def test_01_ruta_nombre_y_modelo_deben_corresponder(self):
        carpeta = self.modelos / "animal"
        interna = carpeta / app.CARPETA_VERSIONES
        interna.mkdir()
        externa = self.base / "dibujo__20000101-000000.cdr"
        externa.write_bytes(b"externo")
        invalida = interna / "original.cdr"
        invalida.write_bytes(b"original interno")
        otro = self.modelos / "otro" / app.CARPETA_VERSIONES
        otro.mkdir(parents=True)
        ajena = otro / "dibujo__20000101-000000.cdr"
        ajena.write_bytes(b"otro modelo")
        for ruta in (externa, invalida, ajena, carpeta / "dibujo.cdr"):
            with self.subTest(ruta=ruta):
                v = {"permiso_borrado": 1, "archivo": "dibujo.cdr", "respaldo": str(ruta), "tipo": "modelo"}
                self.assertFalse(seguridad_archivos.version_propia(v, str(carpeta)))
        for ruta in (externa, invalida, ajena):
            db.ejecutar("INSERT INTO versiones(rel,tipo,archivo,respaldo,fecha,permiso_borrado,carpeta_modelo) VALUES ('animal','modelo','dibujo.cdr',?,1,1,?)", (str(ruta), str(carpeta)))
        for _ in range(4):
            db.registrar_version("animal", "modelo", "dibujo.cdr", "", str(carpeta))
        self.assertTrue(all(p.exists() for p in (externa, invalida, ajena)))

    def test_01_enlace_de_historial_no_borra_ni_escribe_fuera(self):
        carpeta = self.modelos / "animal"
        externa = self.base / "externa"
        externa.mkdir()
        self.enlace(carpeta / app.CARPETA_VERSIONES, externa, True)
        v = {"permiso_borrado": 1, "archivo": "dibujo.cdr", "respaldo": str(carpeta / app.CARPETA_VERSIONES / "dibujo__20000101-000000.cdr")}
        self.assertFalse(seguridad_archivos.version_propia(v, str(carpeta)))
        self.assertIn("error", app.guardar_archivo("animal", "modelo", "dibujo.cdr", b"nuevo"))
        self.assertEqual(list(externa.iterdir()), [])
        self.assertEqual((carpeta / "dibujo.cdr").read_bytes(), b"cdr de prueba")

    def test_01_hardlink_del_original_no_se_borra(self):
        carpeta = self.modelos / "animal"
        ruta = Path(app.ruta_respaldo(str(carpeta), "dibujo.cdr"))
        os.link(carpeta / "dibujo.cdr", ruta)
        v = {"permiso_borrado": 1, "archivo": "dibujo.cdr", "respaldo": str(ruta)}
        self.assertFalse(seguridad_archivos.version_propia(v, str(carpeta)))

    def test_01_papelera_no_mueve_modelos_originales_por_enlace(self):
        papelera = Path(app.PAPELERA)
        self.enlace(papelera, self.modelos, True)
        original = self.modelos / "animal" / "dibujo.cdr"
        pid = db.a_papelera("archivo", "animal", "dibujo.cdr", str(original.parent / "restaurado.cdr"), str(papelera / "animal" / "dibujo.cdr"))
        self.assertIn("error", app.restaurar_papelera(pid))
        self.assertEqual(original.read_bytes(), b"cdr de prueba")

    def test_01_miniatura_enlace_nunca_elimina_original(self):
        carpeta = Path(app.CACHE_THUMBS)
        carpeta.mkdir()
        original = self.modelos / "animal" / "dibujo.cdr"
        ruta = carpeta / ("a" * 32 + ".jpg")
        os.link(original, ruta)
        # Windows no permite symlinks de archivos sin privilegios. Comprobar el
        # reparse point mediante lstat, sobre un hardlink real al original.
        lstat = os.lstat
        def dato(r):
            if os.path.abspath(r) == str(ruta):
                return types.SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
            return lstat(r)
        with mock.patch.object(seguridad_archivos.os, "lstat", side_effect=dato):
            app.retirar_miniatura(str(ruta))
        self.assertEqual(original.read_bytes(), b"cdr de prueba")
        self.assertTrue(ruta.exists())

    def test_01_empaquetar_no_borra_carpeta_ni_zip_preexistentes(self):
        vieja = self.base / "_paquete"
        vieja.mkdir()
        original = vieja / "original.cdr"
        original.write_bytes(b"original")
        zip_viejo = self.modelos / "Biblioteca-Laser.zip"
        zip_viejo.write_bytes(b"archivo del usuario")
        with mock.patch.object(construir_paquete, "BASE", str(self.base)), mock.patch.object(construir_paquete, "INCLUIR", []):
            zip_nuevo = construir_paquete.build(str(self.modelos))
        self.assertNotEqual(zip_nuevo, str(zip_viejo))
        self.assertTrue(Path(zip_nuevo).is_file())
        self.assertEqual(zip_viejo.read_bytes(), b"archivo del usuario")
        self.assertEqual(original.read_bytes(), b"original")
        self.assertEqual(list(self.base.glob(".paquete-*")), [])
        self.assertIn("seguridad_archivos.py", construir_paquete.INCLUIR)
        self.assertIn("seguridad_archivos.py", construir_exe.APP)

    def test_01_respaldos_junction_no_borran_originales(self):
        externa = self.base / "originales"
        externa.mkdir()
        original = externa / "dibujo.cdr"
        original.write_bytes(b"original")
        self.enlace(Path(app.carpeta_respaldos()), externa, True)
        self.assertEqual(app.listar_respaldos(), [])
        self.assertIn("error", app.respaldar_base("rechazar enlace"))
        app.limitar_respaldos()
        self.assertEqual(list(externa.iterdir()), [original])
        self.assertEqual(original.read_bytes(), b"original")

    def test_02_raices_distintas_cancelar_no_cambia_db_config_indice(self):
        copia = app.respaldar_base("original")["respaldo"]["archivo"]
        nueva = self.otra_raiz()
        db.guardar_meta("animal", {"notas": "local después"})
        antes = app.exportar_datos()
        config = Path(app.CONFIG).read_bytes()
        indice = Path(app.INDICE).read_bytes()
        res = app.volver_respaldo(copia)
        self.assertTrue(res["confirmar_raices"])
        self.assertIn(str(self.modelos), res["aviso"])
        self.assertEqual(app.exportar_datos(), antes)
        self.assertEqual(Path(app.CONFIG).read_bytes(), config)
        self.assertEqual(Path(app.INDICE).read_bytes(), indice)
        self.assertEqual(app.raices(), [str(nueva)])

    def test_02_restaurar_raices_reindexa_y_permita_deshacer(self):
        copia = app.respaldar_base("original")["respaldo"]["archivo"]
        nueva = self.otra_raiz()
        with contextlib.redirect_stdout(io.StringIO()):
            res = app.volver_respaldo(copia, restaurar_raices=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(app.raices(), [str(self.modelos)])
        self.assertEqual(app.POR_REL["animal"]["ruta"], str(self.modelos / "animal"))
        self.assertFalse(db.meta("animal")["no_encontrado"])
        self.assertEqual(db.meta("animal")["notas"], "Antes")
        self.assertTrue(app.volver_respaldo(res["deshacer"])["confirmar_raices"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(app.volver_respaldo(res["deshacer"], True)["ok"])
        self.assertEqual(app.raices(), [str(nueva)])

    def test_02_extras_tambien_exigen_confirmacion(self):
        extra = self.base / "extras"
        extra.mkdir()
        app.guardar_config({"bibliotecas_extra": [str(extra)]})
        copia = app.respaldar_base("con extra")["respaldo"]["archivo"]
        app.guardar_config({"bibliotecas_extra": []})
        self.assertTrue(app.volver_respaldo(copia)["confirmar_raices"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(app.volver_respaldo(copia, True)["ok"])
        self.assertEqual(app.raices(), [str(self.modelos), str(extra)])

    def test_02_copia_antigua_sin_raices_no_asocia_rel_de_otra_carpeta(self):
        copia = app.respaldar_base("vieja")["respaldo"]["archivo"]
        ficha = Path(app.carpeta_respaldos()) / (copia + ".json")
        dato = json.loads(ficha.read_text(encoding="utf-8"))
        dato.pop("raices")
        ficha.write_text(json.dumps(dato), encoding="utf-8")
        self.otra_raiz()
        self.assertTrue(app.volver_respaldo(copia)["ok"])
        self.assertTrue(db.meta("animal")["no_encontrado"])
        vista = app.modelo_vista(app.POR_REL["animal"])
        self.assertEqual(vista["notas"], "")
        self.assertEqual(vista["oculto"], 1)
        self.assertEqual(app.meta_asociada("animal"), {})

    def test_02_ruta_no_verificable_permanece_no_encontrada(self):
        copia = app.respaldar_base("sin ruta antigua")["respaldo"]["archivo"]
        with contextlib.closing(sqlite3.connect(Path(app.carpeta_respaldos()) / copia)) as cx:
            cx.execute("UPDATE modelos SET ruta_guardada=NULL")
            cx.commit()
        self.assertTrue(app.volver_respaldo(copia)["ok"])
        self.assertTrue(db.meta("animal")["no_encontrado"])
        app.recargar()
        self.assertTrue(db.meta("animal")["no_encontrado"])
        self.assertIsNone(db.meta("animal")["ruta_guardada"])

    def test_02_raiz_desconectada_conserva_datos_sin_asociar(self):
        copia = app.respaldar_base("desconectada")["respaldo"]["archivo"]
        self.otra_raiz()
        self.modelos.rename(self.base / "desconectados")
        self.assertTrue(app.volver_respaldo(copia, True)["ok"])
        self.assertEqual(app.MODELOS, [])
        self.assertTrue(db.meta("animal")["no_encontrado"])

    def test_02_fallo_reindexando_revierte_raices_indice_y_base(self):
        copia = app.respaldar_base("original")["respaldo"]["archivo"]
        nueva = self.otra_raiz()
        db.guardar_meta("animal", {"notas": "datos actuales"})
        indice = app.cargar_indice()
        with mock.patch.object(indexar, "indexar", side_effect=OSError("disco no disponible")):
            self.assertIn("error", app.volver_respaldo(copia, True))
        self.assertEqual(app.raices(), [str(nueva)])
        self.assertEqual(app.cargar_indice(), indice)
        self.assertEqual(db.meta("animal")["notas"], "datos actuales")

    def test_02_favorito_nuevo_recuerda_ruta_sin_ocultar_modelo(self):
        db.ejecutar("DELETE FROM modelos")
        self.iniciar_http()
        self.assertEqual(self.pedir("/api/favorito", {"rel": "animal"})[0], 200)
        self.assertEqual(db.meta("animal")["ruta_guardada"], str(self.modelos / "animal"))
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["fav"], 1)
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["oculto"], 0)

    def test_02_preferencia_local_nueva_no_se_confunde_con_importada(self):
        db.ejecutar("DELETE FROM modelos")
        self.assertTrue(app.guardar_archivo("animal", "manual", "guia.txt", b"guia")["ok"])
        self.assertEqual(db.meta("animal")["ruta_guardada"], str(self.modelos / "animal"))
        self.assertEqual(app.modelo_vista(app.POR_REL["animal"])["oculto"], 0)
        self.assertTrue(app.importar_datos({"formato_version": 3, "modelos": [{"rel": "ausente", "notas": "importada sin ruta"}]})["ok"])
        app.recargar()
        self.assertTrue(db.meta("ausente")["no_encontrado"])
        self.assertIsNone(db.meta("ausente")["ruta_guardada"])

    def test_03_borrar_antigua_directo_no_devuelve_stock_desconocido(self):
        vid = self.antigua()
        db.borrar_venta(vid)
        self.assertEqual(db.meta("animal")["stock"], 8)

    def test_03_editar_notas_antiguas_conserva_null_y_stock(self):
        vid = self.antigua()
        d = self.venta()
        d["notas"] = "nuevas"
        db.guardar_venta(d, vid)
        self.assertEqual(db.meta("animal")["stock"], 8)
        self.assertIsNone(db.ventas()[0]["stock_descontado"])

    def test_03_editar_antigua_servidor_avisa_antes_de_mutar(self):
        vid = self.antigua()
        self.iniciar_http()
        d = dict(self.venta(3), id=vid)
        codigo, res = self.pedir("/api/venta", d)
        self.assertEqual(codigo, 200)
        self.assertTrue(res["confirmar_stock"])
        self.assertIn("2 unidades", res["aviso"])
        self.assertEqual(db.ventas()[0]["cantidad"], 2)
        self.assertEqual(db.meta("animal")["stock"], 8)
        d["devolver_stock_antiguo"] = False
        self.assertTrue(self.pedir("/api/venta", d)[1]["ok"])
        self.assertEqual(db.meta("animal")["stock"], 5)
        self.assertEqual(db.ventas()[0]["stock_descontado"], 3)

    def test_03_borrar_antigua_si_y_no_explicitos(self):
        for decision in (False, True):
            with self.subTest(decision=decision):
                vid = self.antigua()
                if not self.servidor:
                    self.iniciar_http()
                self.assertTrue(self.pedir("/api/venta/borrar", {"id": vid})[1]["confirmar_stock"])
                self.assertEqual(db.meta("animal")["stock"], 8)
                self.assertTrue(self.pedir("/api/venta/borrar", {"id": vid, "devolver_stock_antiguo": decision})[1]["ok"])
                self.assertEqual(db.meta("animal")["stock"], 10 if decision else 8)

    def test_03_editar_antigua_si_devuelve_cantidad_anterior(self):
        vid = self.antigua()
        db.guardar_venta(dict(self.venta(3), devolver_stock_antiguo=True), vid)
        self.assertEqual(db.meta("animal")["stock"], 7)
        self.assertEqual(db.ventas()[0]["stock_descontado"], 3)

    def test_03_decision_invalida_no_hace_cambios(self):
        vid = self.antigua()
        with self.assertRaises(ValueError):
            db.borrar_venta(vid, "sí")
        self.assertEqual(db.meta("animal")["stock"], 8)
        self.assertEqual(len(db.ventas()), 1)

    def test_04_editar_oculto_servidor_conserva_asociacion_y_stock_repuesto(self):
        db.guardar_meta("animal", {"stock": 1, "oculto": 1})
        vid = db.guardar_venta(self.venta(4))
        db.guardar_meta("animal", {"stock": 20})
        self.iniciar_http()
        d = dict(self.venta(4), id=vid, notas="solo notas", precio_unit=500)
        self.assertTrue(self.pedir("/api/venta", d)[1]["ok"])
        self.assertEqual(db.ventas()[0]["rel"], "animal")
        self.assertEqual(db.ventas()[0]["stock_descontado"], 1)
        self.assertEqual(db.meta("animal")["stock"], 20)
        db.borrar_venta(vid)
        self.assertEqual(db.meta("animal")["stock"], 21)

    def test_04_editar_sin_rel_no_desasocia(self):
        db.guardar_meta("animal", {"stock": 5})
        vid = db.guardar_venta(self.venta())
        d = dict(self.venta(), notas="nota")
        d.pop("rel")
        db.guardar_venta(d, vid)
        self.assertEqual(db.ventas()[0]["rel"], "animal")
        self.assertEqual(db.meta("animal")["stock"], 3)

    def test_04_editar_no_encontrado_servidor_conserva_rel(self):
        db.guardar_meta("ausente", {"stock": 10, "no_encontrado": 1})
        vid = db.guardar_venta(self.venta(rel="ausente"))
        self.iniciar_http()
        d = dict(self.venta(rel="ausente"), id=vid, notas="nota nueva")
        self.assertTrue(self.pedir("/api/venta", d)[1]["ok"])
        self.assertEqual(db.ventas()[0]["rel"], "ausente")
        self.assertEqual(db.meta("ausente")["stock"], 8)

    def test_05_uid_migra_persiste_exporta_y_nuevos_tienen_uid(self):
        cid = db.guardar_cliente({"nombre": "Uno"})
        pid = db.guardar_pedido({"cliente_id": cid, "precio": 10})
        vid = db.guardar_venta(self.venta())
        datos = app.exportar_datos()
        uids = {t: [r["uid"] for r in datos[t]] for t in ("modelos", "clientes", "pedidos", "ventas")}
        self.assertTrue(all(uid for lista in uids.values() for uid in lista))
        db.cerrar()
        self.assertEqual({t: [r["uid"] for r in app.exportar_datos()[t]] for t in uids}, uids)
        self.assertEqual(len({uid for lista in uids.values() for uid in lista}), 4)

    def test_05_fusion_propia_con_ediciones_locales_no_duplica_ni_pisa(self):
        cid = db.guardar_cliente({"nombre": "Antes"})
        pid = db.guardar_pedido({"cliente_id": cid, "precio": 10, "rel": "animal"})
        vid = db.guardar_venta(dict(self.venta(), cliente_id=cid))
        datos = app.exportar_datos()
        db.guardar_cliente({"nombre": "Después", "telefono": "nuevo"}, cid)
        db.guardar_pedido({"cliente_id": cid, "precio": 90, "rel": "animal", "notas": "local"}, pid)
        db.guardar_venta(dict(self.venta(), cliente_id=cid, precio_unit=900), vid)
        db.guardar_meta("animal", {"notas": "cambio local", "stock": 99})
        db.guardar_ajuste("utilidad", 77)
        for _ in range(2):
            self.assertTrue(app.importar_datos(datos)["ok"])
        self.assertEqual(len(db.clientes()), 1)
        self.assertEqual(len(db.pedidos()), 1)
        self.assertEqual(len(db.ventas()), 1)
        self.assertEqual(db.clientes()[0]["nombre"], "Después")
        self.assertEqual(db.pedidos()[0]["precio"], 90)
        self.assertEqual(db.ventas()[0]["precio_unit"], 900)
        self.assertEqual(db.meta("animal")["notas"], "cambio local")
        self.assertEqual(db.meta("animal")["stock"], 99)
        self.assertEqual(db.ajuste("utilidad"), "77")

    def test_05_uid_remapea_cliente_y_modelo_renombrado_de_registros_nuevos(self):
        cid = db.guardar_cliente({"nombre": "Cliente"})
        datos = app.exportar_datos()
        db.guardar_cliente({"nombre": "Cliente cambiado"}, cid)
        db.ejecutar("UPDATE modelos SET rel='renombrado' WHERE rel='animal'")
        datos["ventas"] = [dict(self.venta(), id=999, uid="venta-nueva", cliente_id=cid)]
        self.assertTrue(app.importar_datos(datos)["ok"])
        self.assertEqual(len(db.meta_todos()), 1)
        self.assertEqual(len(db.clientes()), 1)
        self.assertEqual(db.ventas()[0]["rel"], "renombrado")
        self.assertEqual(db.ventas()[0]["cliente_id"], cid)

    def test_05_formato3_sin_uid_compara_campos_y_conserva_dos_ventas_identicas(self):
        cid = db.guardar_cliente({"nombre": "Cliente"})
        for _ in range(2):
            db.guardar_venta(dict(self.venta(), cliente_id=cid))
        datos = app.exportar_datos()
        for t in ("modelos", "clientes", "pedidos", "ventas"):
            for r in datos[t]:
                r.pop("uid")
        for _ in range(2):
            self.assertTrue(app.importar_datos(datos)["ok"])
        self.assertEqual(len(db.clientes()), 1)
        self.assertEqual(len(db.ventas()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
