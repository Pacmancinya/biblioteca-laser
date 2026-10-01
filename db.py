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
import os, sqlite3, time, json, threading, math
from contextlib import contextmanager
from functools import wraps

BASE = os.environ.get("BIBLIOTECA_LASER_BASE") or os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "biblioteca.db")
LOCK = threading.RLock()
_TRANSACCION = 0


@contextmanager
def transaccion():
    """El lock cubre toda la operación; los helpers no confirman a mitad."""
    global _TRANSACCION
    with LOCK:
        conexion = cx()
        externa = _TRANSACCION == 0
        if externa:
            conexion.execute("BEGIN IMMEDIATE")
        _TRANSACCION += 1
        try:
            yield conexion
            if externa:
                conexion.commit()
        except BaseException:
            if externa:
                conexion.rollback()
            raise
        finally:
            _TRANSACCION -= 1


def atomico(funcion):
    @wraps(funcion)
    def protegida(*args, **kwargs):
        with transaccion():
            return funcion(*args, **kwargs)
    return protegida


def numero(valor, nombre, defecto=0, entero=False):
    try:
        n = float(defecto if valor in (None, "") else valor)
    except (ValueError, TypeError):
        raise ValueError("Escribe un número válido en " + nombre + ".")
    if not math.isfinite(n) or n < 0 or (entero and n != int(n)):
        raise ValueError(nombre + " debe ser un número " + ("entero " if entero else "") + "mayor o igual a cero.")
    return int(n) if entero else n


def validar_cliente(valor):
    if valor in (None, ""):
        return None
    try:
        identificador = int(valor)
    except (TypeError, ValueError):
        raise ValueError("Elige un cliente de la lista.")
    if not fila("SELECT id FROM clientes WHERE id=?", (identificador,)):
        raise ValueError("Ese cliente ya no está. Elige otro o deja la acción sin cliente.")
    return identificador


def exclusivo(funcion):
    @wraps(funcion)
    def protegida(*args, **kwargs):
        with LOCK:
            return funcion(*args, **kwargs)
    return protegida


@exclusivo
def cerrar():
    global _CX
    if _CX is not None:
        _CX.close()
        _CX = None

ESQUEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS modelos (
  rel          TEXT PRIMARY KEY,
  nombre       TEXT,
  categoria    TEXT,
  subcategoria TEXT,
  notas        TEXT,
  favorito     INTEGER DEFAULT 0,
  principal    TEXT,
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

-- Categorías grandes: las que el usuario crea, esconde o reordena.
-- Las "de fábrica" solo aparecen aquí si les cambió algo.
CREATE TABLE IF NOT EXISTS cats (
  nombre TEXT PRIMARY KEY,
  orden  INTEGER DEFAULT 0,
  propia INTEGER DEFAULT 0,     -- 1 = la invento el usuario
  oculta INTEGER DEFAULT 0
);

-- "Esta carpeta es de esta categoría": todo lo que esté dentro pertenece
-- ahí. La ruta se guarda RELATIVA a la biblioteca, para que siga sirviendo
-- si el usuario mueve la carpeta de modelos a otro disco.
CREATE TABLE IF NOT EXISTS reglas_carpeta (
  rel          TEXT PRIMARY KEY,
  categoria    TEXT,
  subcategoria TEXT
);

-- Subcategorías que creó el usuario. Se guardan aparte para que existan
-- aunque todavía no tengan ningún modelo dentro.
CREATE TABLE IF NOT EXISTS subcats (
  categoria    TEXT,
  subcategoria TEXT,
  oculta       INTEGER DEFAULT 0,
  orden        INTEGER DEFAULT 999,
  PRIMARY KEY (categoria, subcategoria)
);

CREATE INDEX IF NOT EXISTS ix_pap_fecha ON papelera(fecha);
CREATE INDEX IF NOT EXISTS ix_ped_cli ON pedidos(cliente_id);
CREATE INDEX IF NOT EXISTS ix_ven_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS ix_ver_rel ON versiones(rel, tipo);
CREATE INDEX IF NOT EXISTS ix_mod_fav ON modelos(favorito);

CREATE TABLE IF NOT EXISTS importaciones (
  origen TEXT, tabla TEXT, id_original TEXT, id_local INTEGER,
  PRIMARY KEY (origen, tabla, id_original)
);
"""


def conectar():
    cx = sqlite3.connect(DB_PATH, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    return cx


def migrar(cx):
    """Agrega columnas nuevas a bases creadas por versiones anteriores."""
    faltantes = {"oculto": "INTEGER DEFAULT 0", "principal": "TEXT",
                 "foto_preferida": "TEXT", "manual_preferido": "TEXT", "ruta_guardada": "TEXT",
                 "no_encontrado": "INTEGER DEFAULT 0"}
    existentes = {r[1] for r in cx.execute("PRAGMA table_info(modelos)").fetchall()}
    for col, tipo in faltantes.items():
        if col not in existentes:
            try:
                cx.execute(f"ALTER TABLE modelos ADD COLUMN {col} {tipo}")
            except sqlite3.OperationalError:
                pass
    if "orden" not in {r[1] for r in cx.execute("PRAGMA table_info(subcats)").fetchall()}:
        cx.execute("ALTER TABLE subcats ADD COLUMN orden INTEGER DEFAULT 999")
    if "stock_descontado" not in {r[1] for r in cx.execute("PRAGMA table_info(ventas)").fetchall()}:
        cx.execute("ALTER TABLE ventas ADD COLUMN stock_descontado INTEGER")
    cx.commit()


_CX = None
@exclusivo
def cx():
    global _CX
    if _CX is None:
        _CX = conectar()
        _CX.executescript(ESQUEMA)
        _CX.commit()
        migrar(_CX)
    return _CX


@exclusivo
def filas(sql, args=()):
    return [dict(r) for r in cx().execute(sql, args).fetchall()]

@exclusivo
def fila(sql, args=()):
    r = cx().execute(sql, args).fetchone()
    return dict(r) if r else None

@exclusivo
def ejecutar(sql, args=()):
    try:
        c = cx().execute(sql, args)
        if not _TRANSACCION:
            cx().commit()
        return c.lastrowid
    except Exception:
        if not _TRANSACCION:
            cx().rollback()
        raise


# ---------------------------------------------------------------- modelos
def meta_todos():
    """Dict {rel: metadatos} para mezclar con el índice de archivos."""
    return {r["rel"]: r for r in filas("SELECT * FROM modelos")}

def meta(rel):
    return fila("SELECT * FROM modelos WHERE rel=?", (rel,))

@atomico
def guardar_meta(rel, campos):
    """Crea o actualiza los metadatos de un modelo."""
    permitidos = {"nombre", "categoria", "subcategoria", "notas", "favorito",
                  "costo", "precio", "stock", "cliente_id", "oculto", "principal",
                  "foto_preferida", "manual_preferido", "ruta_guardada", "no_encontrado"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if "cliente_id" in campos:
        campos["cliente_id"] = validar_cliente(campos["cliente_id"])
    if not campos:
        return
    if not meta(rel):
        ejecutar("INSERT INTO modelos (rel, actualizado) VALUES (?,?)", (rel, int(time.time())))
    sets = ", ".join(f"{k}=?" for k in campos)
    vals = list(campos.values()) + [int(time.time()), rel]
    ejecutar(f"UPDATE modelos SET {sets}, actualizado=? WHERE rel=?", vals)

@atomico
def alternar_oculto(rel):
    m = meta(rel)
    nuevo = 0 if (m and m.get("oculto")) else 1
    guardar_meta(rel, {"oculto": nuevo})
    return nuevo

def ocultos():
    return filas("SELECT rel, nombre FROM modelos WHERE oculto=1")


# ------------------------------------------------ categorías del usuario
def cats_propias():
    """Lo que el usuario cambió de las categorías grandes: orden, cuáles
    escondió y cuáles inventó."""
    orden, ocultas, propias = {}, set(), set()
    for r in filas("SELECT * FROM cats"):
        orden[r["nombre"]] = r["orden"]
        if r["oculta"]:
            ocultas.add(r["nombre"])
        if r["propia"]:
            propias.add(r["nombre"])
    return orden, ocultas, propias


@atomico
def guardar_cat(nombre, orden=None, propia=None, oculta=None):
    """Crea o actualiza una categoría grande, sin pisar lo que no se pasa."""
    r = fila("SELECT * FROM cats WHERE nombre=?", (nombre,))
    if not r:
        ejecutar("INSERT INTO cats (nombre, orden, propia, oculta) VALUES (?,?,?,?)",
                 (nombre, orden if orden is not None else 999,
                  1 if propia else 0, 1 if oculta else 0))
        return
    ejecutar("UPDATE cats SET orden=?, propia=?, oculta=? WHERE nombre=?",
             (r["orden"] if orden is None else orden,
              r["propia"] if propia is None else (1 if propia else 0),
              r["oculta"] if oculta is None else (1 if oculta else 0),
              nombre))


def quitar_cat(nombre):
    ejecutar("DELETE FROM cats WHERE nombre=?", (nombre,))


@atomico
def ordenar_cats(nombres):
    """Guarda el orden en que el usuario dejó las categorías."""
    for i, n in enumerate(nombres):
        guardar_cat(n, orden=i)


# ------------------------------------------- "esta carpeta es de esta categoría"
def reglas_carpeta():
    return filas("SELECT * FROM reglas_carpeta ORDER BY LENGTH(rel) DESC")


def guardar_regla(rel, categoria, subcategoria=""):
    ejecutar("INSERT OR REPLACE INTO reglas_carpeta (rel, categoria, subcategoria) "
             "VALUES (?,?,?)", (rel, categoria, subcategoria or ""))


def borrar_regla(rel):
    ejecutar("DELETE FROM reglas_carpeta WHERE rel=?", (rel,))


# ------------------------------------------------- subcategorías del usuario
def subcats_propias():
    """Las que creó el usuario a mano (aunque estén vacías) y las que escondió."""
    creadas, ocultas = {}, {}
    for r in filas("SELECT * FROM subcats"):
        destino = ocultas if r["oculta"] else creadas
        destino.setdefault(r["categoria"], []).append(r["subcategoria"])
    return creadas, ocultas


def crear_subcat(categoria, subcategoria):
    ejecutar("INSERT INTO subcats (categoria, subcategoria, oculta) VALUES (?,?,0) "
             "ON CONFLICT(categoria,subcategoria) DO UPDATE SET oculta=0",
             (categoria, subcategoria))


@atomico
def ordenar_subcats(categoria, nombres):
    for i, nombre in enumerate(nombres):
        crear_subcat(categoria, nombre)
        ejecutar("UPDATE subcats SET orden=? WHERE categoria=? AND subcategoria=?",
                 (i, categoria, nombre))


def ocultar_subcat(categoria, subcategoria, oculta=1):
    """Esconder una subcategoría del clasificador (no se puede 'borrar' de verdad
    porque la calcula el programa, pero sí dejar de mostrarla)."""
    ejecutar("INSERT INTO subcats (categoria, subcategoria, oculta) VALUES (?,?,?) "
             "ON CONFLICT(categoria,subcategoria) DO UPDATE SET oculta=excluded.oculta",
             (categoria, subcategoria, 1 if oculta else 0))


def quitar_subcat(categoria, subcategoria):
    ejecutar("DELETE FROM subcats WHERE categoria=? AND subcategoria=?",
             (categoria, subcategoria))


@atomico
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
        (SELECT COALESCE(SUM(MAX(0,COALESCE(p.precio,0) - COALESCE(p.abonado,0))),0) FROM pedidos p
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

@atomico
def borrar_cliente(cid):
    if fila("SELECT id FROM pedidos WHERE cliente_id=? AND COALESCE(estado,'pendiente')!='entregado' LIMIT 1", (cid,)):
        raise ValueError("Este cliente tiene encargos pendientes. Entrégalos o asígnalos a otro cliente antes de eliminarlo.")
    ejecutar("UPDATE pedidos SET cliente_id=NULL WHERE cliente_id=?", (cid,))
    ejecutar("UPDATE ventas SET cliente_id=NULL WHERE cliente_id=?", (cid,))
    ejecutar("UPDATE modelos SET cliente_id=NULL WHERE cliente_id=?", (cid,))
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

@atomico
def guardar_pedido(d, pid=None):
    d = dict(d)
    d["cliente_id"] = validar_cliente(d.get("cliente_id"))
    d["precio"] = numero(d.get("precio"), "precio")
    d["abonado"] = numero(d.get("abonado"), "abono")
    if d["abonado"] > d["precio"]:
        raise ValueError("El abono no puede ser mayor que el precio del encargo.")
    d["cantidad"] = numero(d.get("cantidad"), "cantidad", 1, entero=True)
    if d["cantidad"] < 1:
        raise ValueError("La cantidad debe ser al menos uno.")
    d.setdefault("estado", "pendiente")
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

@atomico
def guardar_venta(d, vid=None):
    d = dict(d)
    d["cliente_id"] = validar_cliente(d.get("cliente_id"))
    d["cantidad"] = numero(d.get("cantidad"), "cantidad", 1, entero=True)
    if d["cantidad"] < 1:
        raise ValueError("La cantidad debe ser al menos uno.")
    for campo in ("precio_unit", "costo_unit"):
        d[campo] = numero(d.get(campo), campo)
    campos = ("fecha", "rel", "item", "cantidad", "precio_unit", "costo_unit",
              "canal", "evento", "cliente_id", "notas")
    anterior = fila("SELECT * FROM ventas WHERE id=?", (vid,)) if vid else None
    if vid and not anterior:
        raise ValueError("No encuentro esa venta.")
    if anterior and anterior.get("rel"):
        ejecutar("UPDATE modelos SET stock=COALESCE(stock,0)+? WHERE rel=?",
                 (anterior["stock_descontado"] if anterior["stock_descontado"] is not None else anterior["cantidad"], anterior["rel"]))
    descontado = 0
    if d.get("rel"):
        modelo = meta(d["rel"])
        descontado = min(int((modelo or {}).get("stock") or 0), d["cantidad"])
        # Una sola operación SQL, bajo el mismo lock/transacción que la venta.
        ejecutar("UPDATE modelos SET stock=MAX(0,COALESCE(stock,0)-?) WHERE rel=?",
                 (d["cantidad"], d["rel"]))
    if vid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE ventas SET {sets} WHERE id=?", [d.get(k) for k in campos] + [vid])
        ejecutar("UPDATE ventas SET stock_descontado=? WHERE id=?", (descontado, vid))
        return vid
    d.setdefault("fecha", int(time.time()))
    vid = ejecutar(f"INSERT INTO ventas ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
                   [d.get(k) for k in campos])
    ejecutar("UPDATE ventas SET stock_descontado=? WHERE id=?", (descontado, vid))
    return vid

@atomico
def borrar_venta(vid):
    anterior = fila("SELECT * FROM ventas WHERE id=?", (vid,))
    if anterior and anterior.get("rel"):
        ejecutar("UPDATE modelos SET stock=COALESCE(stock,0)+? WHERE rel=?",
                 (anterior["stock_descontado"] if anterior["stock_descontado"] is not None else anterior["cantidad"], anterior["rel"]))
    ejecutar("DELETE FROM ventas WHERE id=?", (vid,))


@exclusivo
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
    cobrar = fila("""SELECT COALESCE(SUM(MAX(0,COALESCE(precio,0)-COALESCE(abonado,0))),0) t, COUNT(*) n
                     FROM pedidos WHERE pagado=0""") or {}
    vencidos = fila("""SELECT COUNT(*) n FROM pedidos
                       WHERE pagado=0 AND fecha_vence IS NOT NULL AND fecha_vence < ?""",
                    (hoy,)) or {}
    encargos = fila("SELECT COALESCE(SUM(CASE WHEN pagado=1 THEN precio ELSE MIN(COALESCE(abonado,0),COALESCE(precio,0)) END),0) ingreso FROM pedidos")
    encargos_mes = fila("SELECT COALESCE(SUM(CASE WHEN pagado=1 THEN precio ELSE MIN(COALESCE(abonado,0),COALESCE(precio,0)) END),0) ingreso FROM pedidos WHERE COALESCE(fecha_pago,fecha_pedido)>=?", (mes,))
    feria = dict(tot)
    ventas_mes = dict(mes_r)
    tot["venta"] += encargos["ingreso"]
    mes_r["venta"] += encargos_mes["ingreso"]
    return {
        "ventas_feria": feria, "ventas_mes": ventas_mes, "encargos": encargos, "encargos_mes": encargos_mes,
        "total": tot, "mes": mes_r, "top": top, "por_canal": por_canal,
        "por_mes": list(reversed(por_mes)), "por_cobrar": cobrar, "vencidos": vencidos,
        "n_favoritos": (fila("SELECT COUNT(*) n FROM modelos WHERE favorito=1 AND COALESCE(oculto,0)=0 AND COALESCE(no_encontrado,0)=0") or {}).get("n", 0),
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
            protegido = "_convertidos" in os.path.normpath(v["respaldo"] or "").replace("\\", "/").lower().split("/")
            if tipo != "convertido" and not protegido and v["respaldo"] and os.path.exists(v["respaldo"]):
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
    d = dict(d)
    d["monto"] = numero(d.get("monto"), "monto")
    d["horas"] = numero(d.get("horas"), "horas")
    if d["horas"] <= 0:
        raise ValueError("Las horas deben ser mayores que cero para repartir este costo.")
    campos = ("nombre", "monto", "horas", "grupo")
    if cid:
        sets = ", ".join(f"{k}=?" for k in campos)
        ejecutar(f"UPDATE costos_fijos SET {sets} WHERE id=?", [d.get(k) for k in campos] + [cid])
        return cid
    return ejecutar(f"INSERT INTO costos_fijos ({','.join(campos)}) VALUES ({','.join('?'*len(campos))})",
                    [d.get(k) for k in campos])

def borrar_costo_fijo(cid):
    ejecutar("DELETE FROM costos_fijos WHERE id=?", (cid,))


@atomico
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

@atomico
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
