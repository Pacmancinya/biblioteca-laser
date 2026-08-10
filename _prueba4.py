# -*- coding: utf-8 -*-
"""Prueba de respaldo (exportar/importar) y de actualizacion. Limpia al final."""
import json, os, urllib.request, urllib.parse, shutil

B = "http://127.0.0.1:8777"
BASE = os.path.dirname(os.path.abspath(__file__))
ok = lambda c, m: print(("  OK  " if c else " FALLA") + " | " + m)

def get(r):
    with urllib.request.urlopen(B + r) as x: return json.loads(x.read().decode())
def post(r, d):
    req = urllib.request.Request(B + r, data=json.dumps(d).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as x: return json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read().decode())}

d = get("/api/datos")
rel = d["modelos"][80]["rel"]
print("=" * 58)

# --- crear datos de prueba
post("/api/meta", {"rel": rel, "nombre": "PRUEBA Respaldo", "categoria": "Vehículos",
                   "subcategoria": "Autos", "favorito": 1, "precio": 9900, "stock": 5})
cid = post("/api/cliente", {"nombre": "PRUEBA Cliente Respaldo", "telefono": "+56900000000"})["id"]
post("/api/venta", {"item": "PRUEBA Item", "cantidad": 2, "precio_unit": 5000,
                    "costo_unit": 1500, "canal": "feria"})
post("/api/pedido", {"cliente_id": cid, "descripcion": "PRUEBA Encargo", "precio": 20000})

# --- exportar
with urllib.request.urlopen(B + "/api/datos/exportar") as x:
    respaldo = json.loads(x.read().decode())
ok(len(respaldo["modelos"]) >= 1 and len(respaldo["clientes"]) >= 1
   and len(respaldo["ventas"]) >= 1 and len(respaldo["pedidos"]) >= 1, "el respaldo incluye todo")

mi = next((m for m in respaldo["modelos"] if m["rel"] == rel), None)
ok(mi and mi["nombre"] == "PRUEBA Respaldo" and mi["favorito"] == 1 and mi["precio"] == 9900,
   "guarda nombre, favorito y precio corregidos")

# --- simular "otro computador": borrar todo y volver a cargar el respaldo
import db
for t in ("modelos", "clientes", "pedidos", "ventas"):
    db.ejecutar(f"DELETE FROM {t}")
vacio = get("/api/datos")
mv = next(x for x in vacio["modelos"] if x["rel"] == rel)
ok(mv["n"] != "PRUEBA Respaldo" and not mv["fav"], "tras borrar, los datos ya no estan")

r = post("/api/datos/importar", {"datos": respaldo, "modo": "fusionar"})
ok(r.get("ok"), "importar el respaldo funciona")

vuelto = get("/api/datos")
mr = next(x for x in vuelto["modelos"] if x["rel"] == rel)
ok(mr["n"] == "PRUEBA Respaldo" and mr["fav"] == 1 and mr["precio"] == 9900 and mr["stock"] == 5,
   "el modelo recupero nombre, favorito, precio y stock")
cl = get("/api/clientes")["clientes"]
ok(any(c["nombre"] == "PRUEBA Cliente Respaldo" for c in cl), "los clientes volvieron")
ok(len(get("/api/ventas")["ventas"]) >= 1, "las ventas volvieron")
k = get("/api/metricas")
ok(k["total"]["venta"] == 10000, "las metricas cuadran tras importar")

# --- no duplica al importar dos veces
n_antes = len(get("/api/clientes")["clientes"])
post("/api/datos/importar", {"datos": respaldo, "modo": "fusionar"})
mr2 = next(x for x in get("/api/datos")["modelos"] if x["rel"] == rel)
ok(mr2["n"] == "PRUEBA Respaldo", "reimportar no rompe los datos del modelo")

# --- actualizacion
a = get("/api/actualizacion/revisar")
ok(a.get("ok") and a.get("actual"), "revisar actualizaciones responde (actual %s)" % a.get("actual"))
ok(a.get("hay_nueva") is False, "detecta que esta al dia")

# archivos que NUNCA debe tocar una actualizacion
ok(os.path.exists(os.path.join(BASE, "biblioteca.db")), "biblioteca.db (tus datos) sigue ahi")
ok(os.path.exists(os.path.join(BASE, "config.json")), "config.json (tu carpeta) sigue ahi")

print("-" * 58)
for t in ("modelos", "clientes", "pedidos", "ventas"):
    db.ejecutar(f"DELETE FROM {t}")
print("limpieza: datos de prueba borrados")
print("=" * 58)
