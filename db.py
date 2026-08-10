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

CREATE TABLE IF NOT EXISTS huellas (
  ruta  TEXT PRIMARY KEY,
  tam   INTEGER,
  mtime INTEGER,
  hash  TEXT
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


_CX = None
def cx():
    global _CX
    if _CX is None:
        _CX = conectar()
        _CX.executescript(ESQUEMA)
        _CX.commit()
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
                  "costo", "precio", "stock", "cliente_id"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    if not meta(rel):
        ejecutar("INSERT INTO modelos (rel, actualizado) VALUES (?,?)", (rel, int(time.time())))
    sets = ", ".join(f"{k}=?" for k in campos)
    vals = list(campos.values()) + [int(time.time()), rel]
    ejecutar(f"UPDATE modelos SET {sets}, actualizado=? WHERE rel=?", vals)

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
