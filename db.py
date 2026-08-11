# -*- coding: utf-8 -*-
"""
db.py — base de datos de la Biblioteca Láser (SQLite).

Guarda TODO lo que el usuario edita, sin tocar sus archivos:
  modelos   -> nombre/categoría propios, favorito, notas, costo, precio, stock
  clientes  -> datos de contacto
  pedidos   -> encargos por cliente, con cobro y vencimiento
  ventas    -> lo vendido (ferias, precios variables) para las métricas
  versiones -> historial de archivos reemplazados (máx. 3 por archivo)

La llave de cada modelo es su RUTA RELATIVA dentro de la biblioteca, así los
datos sobreviven al re-indexado.
"""
import os, sqlite3, time, json

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "biblioteca.db")

ESQUEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS modelos (
  rel          TEXT PRIMARY KEY,
  nombre       TEXT,
  categoria    TEXT,
  subcategoria TEXT,
  notas        TEXT,
  favorito     INTEGER DEFAULT 0,
  oculto       INTEGER DEFAULT 0,
  costo        REAL,
  precio       REAL,
  stock        INTEGER DEFAULT 0,
  cliente_id   INTEGER,
  actualizado  INTEGER
);

CREATE TABLE IF NOT EXISTS clientes (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre    TEXT NOT NULL,
  telefono  TEXT,
  email     TEXT,
  notas     TEXT,
  creado    INTEGER
);

CREATE TABLE IF NOT EXISTS pedidos (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  cliente_id   INTEGER,
  rel          TEXT,
  descripcion  TEXT,
  cantidad     INTEGER DEFAULT 1,
  precio       REAL,
  abonado      REAL DEFAULT 0,
  estado       TEXT DEFAULT 'pendiente',   -- pendiente | cortado | entregado
  pagado       INTEGER DEFAULT 0,
  fecha_pedido INTEGER,
  fecha_vence  INTEGER,
  fecha_pago   INTEGER,
  notas        TEXT
);

CREATE TABLE IF NOT EXISTS ventas (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha       INTEGER,
  rel         TEXT,
  item        TEXT,
  cantidad    INTEGER DEFAULT 1,
  precio_unit REAL,
  costo_unit  REAL,
  canal       TEXT DEFAULT 'feria',        -- feria | cliente | local | otro
  evento      TEXT,
  cliente_id  INTEGER,
  notas       TEXT
);

CREATE TABLE IF NOT EXISTS versiones (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  rel     TEXT,
  tipo    TEXT,        -- modelo | imagen | manual
  archivo TEXT,        -- nombre del archivo actual
  respaldo TEXT,       -- ruta del archivo guardado
  fecha   INTEGER
);

CREATE TABLE IF NOT EXISTS papelera (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo    TEXT,        -- archivo | modelo
  rel     TEXT,        -- modelo al que pertenecía
  nombre  TEXT,        -- nombre del archivo o del modelo
  origen  TEXT,        -- ruta original (para restaurar)
  destino TEXT,        -- dónde quedó guardado
  fecha   INTEGER
);

-- materiales: planchas con su medida y precio (para el costo por cm2)
CREATE TABLE IF NOT EXISTS materiales (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre    TEXT,
  proveedor TEXT,
  ancho     REAL,     -- cm
  largo     REAL,     -- cm
  espesor   REAL,     -- mm
  precio    REAL,     -- precio de la plancha completa
  activo    INTEGER DEFAULT 1
);

-- costos fijos del taller (para calcular el costo por minuto)
CREATE TABLE IF NOT EXISTS costos_fijos (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT,
  monto  REAL,
  horas  REAL,        -- en cuántas horas se prorratea
  grupo  TEXT
);

-- ajustes sueltos (clave/valor)
CREATE TABLE IF NOT EXISTS ajustes (
  clave TEXT PRIMARY KEY,
  valor TEXT
);

CREATE TABLE IF NOT EXISTS sugerencias (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  texto  TEXT,
  fecha  INTEGER,
  enviada INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS huellas (
  ruta  TEXT PRIMARY KEY,
  tam   INTEGER,
  mtime INTEGER,
  hash  TEXT
);

-- Subcategorías que creó el usuario. Se guardan aparte para que existan
-- aunque todavía no tengan ningún modelo dentro.
CREATE TABLE IF NOT EXISTS subcats (
  categoria    TEXT,
  subcategoria TEXT,
  oculta       INTEGER DEFAULT 0,
  PRIMARY KEY (categoria, subcategoria)
);

CREATE INDEX IF NOT EXISTS ix_pap_fecha ON papelera(fecha);
CREATE INDEX IF NOT EXISTS ix_ped_cli ON pedidos(cliente_id);
CREATE INDEX IF NOT EXISTS ix_ven_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS ix_ver_rel ON versiones(rel, tipo);
CREATE INDEX IF NOT EXISTS ix_mod_fav ON modelos(favorito);
"""


def conectar():
    cx = sqlite3.connect(DB_PATH, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    return cx


def migrar(cx):
    """Agrega columnas nuevas a bases creadas por versiones anteriores."""
    faltantes = {"oculto": "INTEGER DEFAULT 0"}
    existentes = {r[1] for r in cx.execute("PRAGMA table_info(modelos)").fetchall()}
    for col, tipo in faltantes.items():
        if col not in existentes:
            try:
                cx.execute(f"ALTER TABLE modelos ADD COLUMN {col} {tipo}")
            except sqlite3.OperationalError:
                pass
    cx.commit()


_CX = None
def cx():
    global _CX
    if _CX is None:
        _CX = conectar()
        _CX.executescript(ESQUEMA)
        _CX.commit()
        migrar(_CX)
    return _CX


def filas(sql, args=()):
    return [dict(r) for r in cx().execute(sql, args).fetchall()]

def fila(sql, args=()):
    r = cx().execute(sql, args).fetchone()
    return dict(r) if r else None

def ejecutar(sql, args=()):
    c = cx().execute(sql, args)
    cx().commit()
    return c.lastrowid


# ---------------------------------------------------------------- modelos
def meta_todos():
    """Dict {rel: metadatos} para mezclar con el índice de archivos."""
    return {r["rel"]: r for r in filas("SELECT * FROM modelos")}

def meta(rel):
    return fila("SELECT * FROM modelos WHERE rel=?", (rel,))

def guardar_meta(rel, campos):
    """Crea o actualiza los metadatos de un modelo."""
    permitidos = {"nombre", "categoria", "subcategoria", "notas", "favorito",
                  "costo", "precio", "stock", "cliente_id", "oculto"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    if not meta(rel):
        ejecutar("INSERT INTO modelos (rel, actualizado) VALUES (?,?)", (rel, int(time.time())))
    sets = ", ".join(f"{k}=?" for k in campos)
    vals = list(campos.values()) + [int(time.time()), rel]
    ejecutar(f"UPDATE modelos SET {sets}, actualizado=? WHERE rel=?", vals)

def alternar_oculto(rel):
    m = meta(rel)
    nuevo = 0 if (m and m.get("oculto")) else 1
    guardar_meta(rel, {"oculto": nuevo})
    return nuevo

def ocultos():
    return filas("SELECT rel, nombre FROM modelos WHERE oculto=1")


# ------------------------------------------------- subcategorías del usuario
def subcats_propias():
    """Las que creó el usuario a mano (aunque estén vacías) y las que escondió."""
    creadas, ocultas = {}, {}
    for r in filas("SELECT * FROM subcats"):
        destino = ocultas if r["oculta"] else creadas
        destino.setdefault(r["categoria"], []).append(r["subcategoria"])
    return creadas, ocultas


def crear_subcat(categoria, subcategoria):
    ejecutar("INSERT OR REPLACE INTO subcats (categoria, subcategoria, oculta) VALUES (?,?,0)",
             (categoria, subcategoria))


def ocultar_subcat(categoria, subcategoria, oculta=1):
    """Esconder una subcategoría del clasificador (no se puede 'borrar' de verdad
    porque la calcula el programa, pero sí dejar de mostrarla)."""
    ejecutar("INSERT OR REPLACE INTO subcats (categoria, subcategoria, oculta) VALUES (?,?,?)",
             (categoria, subcategoria, 1 if oculta else 0))


def quitar_subcat(categoria, subcategoria):
    ejecutar("DELETE FROM subcats WHERE categoria=? AND subcategoria=?",
             (categoria, subcategoria))


def alternar_favorito(rel):
    m = meta(rel)
    nuevo = 0 if (m and m.get("favorito")) else 1
    guardar_meta(rel, {"favorito": nuevo})
    return nuevo


# ---------------------------------------------------------------- clientes
def clientes():
    return filas("""
      SELECT c.*,
        (SELECT COUNT(*) FROM pedidos p WHERE p.cliente_id=c.id) AS n_pedidos,
        (SELECT COALESCE(SUM(p.precio - p.abonado),0) FROM pedidos p
           WHERE p.cliente_id=c.id AND p.pagado=0) AS por_cobrar
      FROM clientes c ORDER BY c.nombre COLLATE NOCASE
    """)

def guardar_cliente(datos, cid=None):
    if cid:
        ejecutar("UPDATE clientes SET nombre=?, telefono=?, email=?, notas=? WHERE id=?",
                 (datos.get("nombre", ""), datos.get("telefono", ""),
                  datos.get("email", ""), datos.get("notas", ""), cid))
        return cid
    return ejecutar("INSERT INTO clientes (nombre,telefono,email,notas,creado) VALUES (?,?,?,?,?)",
                    (datos.get("nombre", ""), datos.get("telefono", ""),
                     datos.get("email", ""), datos.get("notas", ""), int(time.time())))

def borrar_cliente(cid):
    ejecutar("UPDATE pedidos SET cliente_id=NULL WHERE cliente_id=?", (cid,))
    ejecutar("DELETE FROM clientes WHERE id=?", (cid,))


# ---------------------------------------------------------------- pedidos
def pedidos(cliente_id=None, solo_pendientes=False):
    sql = """SELECT p.*, c.nombre AS cliente FROM pedidos p
             LEFT JOIN clientes c ON c.id=p.cliente_id WHERE 1=1"""
    args = []
    if cliente_id:
        sql += " AND p.cliente_id=?"; args.append(cliente_id)
    if solo_pendientes:
        sql += " AND p.estado!='entregado'"
    sql += " ORDER BY COALESCE(p.fecha_vence, p.fecha_pedido) ASC"
    return filas(sql, args)

def guardar_pedido(d, pid=None):
    campos = ("cliente_id", "rel", "descripcion", "cantidad", "precio", "abonado",
              "estado", "pagado", "fecha_pedido", "fecha_vence", "fecha_pago", "notas")
    if pid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE pedidos SET {sets} WHERE id=?",
                 [d.get(k) for k in campos] + [pid])
        return pid
    d.setdefault("fecha_pedido", int(time.time()))
    return ejecutar(
        f"INSERT INTO pedidos ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
        [d.get(k) for k in campos])

def borrar_pedido(pid):
    ejecutar("DELETE FROM pedidos WHERE id=?", (pid,))


# ---------------------------------------------------------------- ventas
def ventas(desde=None, hasta=None):
    sql = """SELECT v.*, c.nombre AS cliente FROM ventas v
             LEFT JOIN clientes c ON c.id=v.cliente_id WHERE 1=1"""
    args = []
    if desde: sql += " AND v.fecha>=?"; args.append(desde)
    if hasta: sql += " AND v.fecha<=?"; args.append(hasta)
    sql += " ORDER BY v.fecha DESC"
    return filas(sql, args)

def guardar_venta(d, vid=None):
    campos = ("fecha", "rel", "item", "cantidad", "precio_unit", "costo_unit",
              "canal", "evento", "cliente_id", "notas")
    if vid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE ventas SET {sets} WHERE id=?", [d.get(k) for k in campos] + [vid])
        return vid
    d.setdefault("fecha", int(time.time()))
    vid = ejecutar(f"INSERT INTO ventas ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
                   [d.get(k) for k in campos])
    # descuenta del inventario si el modelo lleva stock
    if d.get("rel"):
        m = meta(d["rel"])
        if m and m.get("stock"):
            nuevo = max(0, int(m["stock"]) - int(d.get("cantidad") or 1))
            guardar_meta(d["rel"], {"stock": nuevo})
    return vid

def borrar_venta(vid):
    ejecutar("DELETE FROM ventas WHERE id=?", (vid,))


def metricas():
    """Resumen para el panel."""
    hoy = time.time()
    mes = hoy - 30 * 86400
    tot = fila("""SELECT COUNT(*) n, COALESCE(SUM(precio_unit*cantidad),0) venta,
                         COALESCE(SUM(costo_unit*cantidad),0) costo FROM ventas""") or {}
    mes_r = fila("""SELECT COUNT(*) n, COALESCE(SUM(precio_unit*cantidad),0) venta,
                           COALESCE(SUM(costo_unit*cantidad),0) costo
                    FROM ventas WHERE fecha>=?""", (mes,)) or {}
    top = filas("""SELECT COALESCE(item, rel) AS item, SUM(cantidad) uds,
                          SUM(precio_unit*cantidad) total
                   FROM ventas GROUP BY COALESCE(item, rel)
                   ORDER BY total DESC LIMIT 10""")
    por_canal = filas("""SELECT canal, COUNT(*) n, SUM(precio_unit*cantidad) total
                         FROM ventas GROUP BY canal ORDER BY total DESC""")
    por_mes = filas("""SELECT strftime('%Y-%m', fecha, 'unixepoch') AS mes,
                              SUM(precio_unit*cantidad) total,
                              SUM(costo_unit*cantidad) costo, COUNT(*) n
                       FROM ventas GROUP BY mes ORDER BY mes DESC LIMIT 12""")
    cobrar = fila("""SELECT COALESCE(SUM(precio-abonado),0) t, COUNT(*) n
                     FROM pedidos WHERE pagado=0""") or {}
    vencidos = fila("""SELECT COUNT(*) n FROM pedidos
                       WHERE pagado=0 AND fecha_vence IS NOT NULL AND fecha_vence < ?""",
                    (hoy,)) or {}
    return {
        "total": tot, "mes": mes_r, "top": top, "por_canal": por_canal,
        "por_mes": list(reversed(por_mes)), "por_cobrar": cobrar, "vencidos": vencidos,
        "n_favoritos": (fila("SELECT COUNT(*) n FROM modelos WHERE favorito=1") or {}).get("n", 0),
        "n_clientes": (fila("SELECT COUNT(*) n FROM clientes") or {}).get("n", 0),
    }


# ---------------------------------------------------------------- versiones
MAX_VERSIONES = 3

def registrar_version(rel, tipo, archivo, respaldo):
    ejecutar("INSERT INTO versiones (rel,tipo,archivo,respaldo,fecha) VALUES (?,?,?,?,?)",
             (rel, tipo, archivo, respaldo, int(time.time())))
    # deja solo las últimas MAX_VERSIONES; borra del disco las que sobran
    viejas = filas("""SELECT * FROM versiones WHERE rel=? AND tipo=?
                      ORDER BY fecha DESC LIMIT -1 OFFSET ?""", (rel, tipo, MAX_VERSIONES))
    for v in viejas:
        try:
            if v["respaldo"] and os.path.exists(v["respaldo"]):
                os.remove(v["respaldo"])
        except OSError:
            pass
        ejecutar("DELETE FROM versiones WHERE id=?", (v["id"],))

# ---------------------------------------------------------------- papelera
def papelera():
    return filas("SELECT * FROM papelera ORDER BY fecha DESC")

def a_papelera(tipo, rel, nombre, origen, destino):
    return ejecutar("""INSERT INTO papelera (tipo,rel,nombre,origen,destino,fecha)
                       VALUES (?,?,?,?,?,?)""",
                    (tipo, rel, nombre, origen, destino, int(time.time())))

def item_papelera(pid):
    return fila("SELECT * FROM papelera WHERE id=?", (pid,))

def quitar_de_papelera(pid):
    ejecutar("DELETE FROM papelera WHERE id=?", (pid,))


# ---------------------------------------------------------------- ajustes
AJUSTES_POR_DEFECTO = {
    "ganancia_minuto": "100",     # % que se le suma al costo por minuto
    "luz_pieza": "300",           # costo luz por pieza
    "manoobra_pieza": "1000",     # mano de obra por pieza
    "depreciacion_minuto": "0.2", # depreciación del equipo por minuto
    "utilidad": "100",            # % de utilidad sobre el costo total
    "minutos_defecto": "30",
}

def ajuste(clave, por_defecto=None):
    r = fila("SELECT valor FROM ajustes WHERE clave=?", (clave,))
    if r:
        return r["valor"]
    return AJUSTES_POR_DEFECTO.get(clave, por_defecto)

def ajustes_todos():
    d = dict(AJUSTES_POR_DEFECTO)
    for r in filas("SELECT * FROM ajustes"):
        d[r["clave"]] = r["valor"]
    return d

def guardar_ajuste(clave, valor):
    ejecutar("INSERT OR REPLACE INTO ajustes (clave,valor) VALUES (?,?)", (clave, str(valor)))


# ---------------------------------------------------------------- materiales
def materiales():
    return filas("SELECT * FROM materiales WHERE activo=1 ORDER BY nombre COLLATE NOCASE")

def guardar_material(d, mid=None):
    campos = ("nombre", "proveedor", "ancho", "largo", "espesor", "precio")
    if mid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE materiales SET {sets} WHERE id=?", [d.get(k) for k in campos] + [mid])
        return mid
    return ejecutar(f"INSERT INTO materiales ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
                    [d.get(k) for k in campos])

def borrar_material(mid):
    ejecutar("UPDATE materiales SET activo=0 WHERE id=?", (mid,))


# ---------------------------------------------------------------- costos fijos
def costos_fijos():
    return filas("SELECT * FROM costos_fijos ORDER BY id")

def guardar_costo_fijo(d, cid=None):
    campos = ("nombre", "monto", "horas", "grupo")
    if cid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE costos_fijos SET {sets} WHERE id=?", [d.get(k) for k in campos] + [cid])
        return cid
    return ejecutar(f"INSERT INTO costos_fijos ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
                    [d.get(k) for k in campos])

def borrar_costo_fijo(cid):
    ejecutar("DELETE FROM costos_fijos WHERE id=?", (cid,))


def sembrar_costos():
    """Carga por primera vez los datos de los Excel del papá."""
    if not costos_fijos():
        equipos = [("Laser diodo 10w", 400000, 9600), ("Computador", 950000, 9600),
                   ("Extractor", 14000, 9600), ("Bomba Aire", 92000, 9600),
                   ("Capital inicial", 500000, 9600)]
        mensuales = [("Luz", 12000, 800), ("Tel", 7500, 800), ("Combustible auto", 30000, 800),
                     ("Mantenimiento auto", 30000, 800), ("Otros (limpieza cama)", 10000, 800),
                     ("Sueldo", 500000, 800), ("Varios", 20000, 800)]
        for n, m, h in equipos:
            guardar_costo_fijo({"nombre": n, "monto": m, "horas": h, "grupo": "Equipos"})
        for n, m, h in mensuales:
            guardar_costo_fijo({"nombre": n, "monto": m, "horas": h, "grupo": "Mensuales"})

    if not materiales():
        mats = [
            ("MDF 3mm", "Placacentro", 3, 185), ("MDF 6mm", "Placacentro", 6, 223),
            ("MDF 15mm", "Placacentro", 15, 548), ("MDF 19mm", "Placacentro", 19, 745),
            ("Triplay 3mm", "Placacentro", 3, 178), ("Triplay 6mm", "Placacentro", 6, 343),
            ("Triplay 9mm", "Placacentro", 9, 487), ("Triplay 12.7mm", "Placacentro", 12.7, 571),
            ("Triplay 19mm", "Placacentro", 19, 761),
            ("MDF 3mm", "Cabinet And Chalet", 3, 143), ("MDF 6mm", "Cabinet And Chalet", 6, 233),
            ("MDF 9mm", "Cabinet And Chalet", 9, 351), ("MDF 12mm", "Cabinet And Chalet", 12, 462),
            ("MDF 15mm", "Cabinet And Chalet", 15, 468), ("MDF 19mm", "Cabinet And Chalet", 19, 559),
            ("Triplay 3mm", "Cabinet And Chalet", 3, 188), ("Triplay 6mm", "Cabinet And Chalet", 6, 280),
            ("Triplay 9mm", "Cabinet And Chalet", 9, 435), ("Triplay 12mm", "Cabinet And Chalet", 12, 579),
            ("Triplay 15mm", "Cabinet And Chalet", 15, 690), ("Triplay 19mm", "Cabinet And Chalet", 19, 825),
            ("Acrílico transparente 1.5mm", "Acrílico", 1.5, 933),
            ("Acrílico transparente 2mm", "Acrílico", 2, 1128),
            ("Acrílico transparente 3mm", "Acrílico", 3, 1388),
            ("Acrílico transparente 4.5mm", "Acrílico", 4.5, 2061),
            ("Acrílico transparente 6mm", "Acrílico", 6, 2689),
            ("Acrílico color 3mm", "Acrílico", 3, 1649),
        ]
        for n, prov, esp, precio in mats:
            guardar_material({"nombre": n, "proveedor": prov, "ancho": 122, "largo": 244,
                              "espesor": esp, "precio": precio})
        # la plancha del Excel de ejemplo
        guardar_material({"nombre": "MDF 3.19mm (plancha grande)", "proveedor": "",
                          "ancho": 122, "largo": 244, "espesor": 3.19, "precio": 12000})


# ---------------------------------------------------------------- sugerencias
def sugerencias():
    return filas("SELECT * FROM sugerencias ORDER BY fecha DESC")

def agregar_sugerencia(texto):
    return ejecutar("INSERT INTO sugerencias (texto,fecha,enviada) VALUES (?,?,0)",
                    (texto, int(time.time())))

def borrar_sugerencia(sid):
    ejecutar("DELETE FROM sugerencias WHERE id=?", (sid,))

def marcar_enviadas():
    ejecutar("UPDATE sugerencias SET enviada=1")


# ---------------------------------------------------------------- huellas (caché)
def huellas_todas():
    return {r["ruta"]: r for r in filas("SELECT * FROM huellas")}

def guardar_huellas(lista):
    """lista de (ruta, tam, mtime, hash)"""
    if not lista:
        return
    cx().executemany("INSERT OR REPLACE INTO huellas (ruta,tam,mtime,hash) VALUES (?,?,?,?)", lista)
    cx().commit()


def versiones(rel, tipo=None):
    if tipo:
        return filas("SELECT * FROM versiones WHERE rel=? AND tipo=? ORDER BY fecha DESC", (rel, tipo))
    return filas("SELECT * FROM versiones WHERE rel=? ORDER BY fecha DESC", (rel,))
