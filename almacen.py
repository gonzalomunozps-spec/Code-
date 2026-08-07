# -*- coding: utf-8 -*-
"""
almacen.py
==========

Capa de datos con SQLite (sustituye a los ficheros JSON). Guarda parcelas,
cultivos por campana, pasadas del satelite (historico de indices) y el cuaderno
de campo (eventos) en un unico fichero `parcelas.db`.

Ventajas frente a los JSON:
  - Consultas por parcela/campana sin cargar todo en memoria (indices).
  - Transacciones atomicas por operacion (no se reescribe el fichero entero).
  - Un solo fichero, seguro entre hilos (cerrojo + WAL).

Las funciones devuelven/aceptan las MISMAS estructuras (dicts/listas) que antes,
para que el resto del programa apenas cambie. La primera vez, si existen los
JSON antiguos, se importan automaticamente y se renombran a *.bak.

Config (config_credenciales.json) y la marca de sync (estado_sync.json) siguen
siendo JSON aparte: son configuracion/estado, no datos.
"""

import os
import json
import uuid
import sqlite3
import threading
from datetime import datetime

RUTA_DB = "parcelas.db"
_CONN = None
_LOCK = threading.RLock()

# JSON antiguos a importar la primera vez
_JSON_PARCELAS = "parcelas.json"
_JSON_HISTORICO = "historico_reportes.json"
_JSON_EVENTOS = "eventos_parcela.json"


# ---------------------------------------------------------------------------
# Conexion / esquema / migracion
# ---------------------------------------------------------------------------
def conectar(ruta=None):
    """Abre (o reutiliza) la conexion. Con `ruta` distinta, reconecta (util en tests)."""
    global _CONN, RUTA_DB
    with _LOCK:
        if ruta and ruta != RUTA_DB:
            cerrar()
            RUTA_DB = ruta
        if _CONN is None:
            _CONN = sqlite3.connect(RUTA_DB, check_same_thread=False)
            _CONN.row_factory = sqlite3.Row
            try:
                _CONN.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            _crear_tablas()
            _migrar_desde_json()
        return _CONN


def cerrar():
    global _CONN
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None


def _c():
    return _CONN or conectar()


def _crear_tablas():
    _CONN.executescript("""
        CREATE TABLE IF NOT EXISTS parcelas(
            nombre TEXT PRIMARY KEY,
            propietario TEXT,
            coordenadas TEXT,          -- JSON: [[lon,lat], ...]
            superficie_ha REAL,
            anio_inicio TEXT);
        CREATE TABLE IF NOT EXISTS cultivos(
            nombre TEXT, campana TEXT,
            datos TEXT,                -- JSON del cultivo (tipo, subtipo, especie, marco...)
            PRIMARY KEY(nombre, campana));
        CREATE TABLE IF NOT EXISTS pasadas(
            nombre TEXT, campana TEXT, fecha TEXT,
            datos TEXT,                -- JSON con los indices y la estadistica espacial
            interpretacion TEXT,
            PRIMARY KEY(nombre, campana, fecha));
        CREATE TABLE IF NOT EXISTS pasadas_radar(
            nombre TEXT, campana TEXT, fecha TEXT,
            datos TEXT,                -- JSON con VV, VH y RVI (Sentinel-1, atraviesa nubes)
            PRIMARY KEY(nombre, campana, fecha));
        CREATE TABLE IF NOT EXISTS eventos(
            id TEXT PRIMARY KEY,
            nombre TEXT, campana TEXT, fecha TEXT,
            datos TEXT);               -- JSON del evento (tipo, producto, notas...)
        CREATE TABLE IF NOT EXISTS validaciones(
            nombre TEXT, campana TEXT, fecha TEXT,
            fase TEXT,                 -- fase fenologica que calculo el sistema
            cultivo TEXT,              -- tipo/subtipo/especie (para aprender por cultivo)
            estado_sistema TEXT,       -- diagnostico automatico (OK/Vigilar/Revisar/Segado)
            veredicto TEXT,            -- 'correcto' | 'incorrecto'
            estado_real TEXT,          -- lo que el usuario dice que era (si incorrecto)
            nota TEXT,                 -- observacion libre del agricultor
            ts TEXT,                   -- momento de la validacion
            PRIMARY KEY(nombre, campana, fecha));
        CREATE INDEX IF NOT EXISTS ix_pasadas_np ON pasadas(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_pasadas_c  ON pasadas(campana);
        CREATE INDEX IF NOT EXISTS ix_radar_np   ON pasadas_radar(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_cultivos_c ON cultivos(campana);
        CREATE INDEX IF NOT EXISTS ix_eventos_np ON eventos(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_valida_ts  ON validaciones(ts);
    """)
    _CONN.commit()


def _backup(path):
    try:
        os.replace(path, path + ".bak")
    except OSError:
        pass


def _migrar_desde_json():
    """Importa los JSON antiguos una sola vez (si existen y las tablas estan vacias)."""
    # --- parcelas + cultivos ---
    if os.path.exists(_JSON_PARCELAS) and not _CONN.execute("SELECT 1 FROM parcelas LIMIT 1").fetchone():
        try:
            with open(_JSON_PARCELAS, encoding="utf-8") as f:
                data = json.load(f)
            for nombre, ficha in (data or {}).items():
                guardar_ficha(nombre, ficha)
            _backup(_JSON_PARCELAS)
        except Exception:
            pass
    # --- historico (pasadas) ---
    if os.path.exists(_JSON_HISTORICO) and not _CONN.execute("SELECT 1 FROM pasadas LIMIT 1").fetchone():
        try:
            with open(_JSON_HISTORICO, encoding="utf-8") as f:
                data = json.load(f)
            for nombre, camps in (data or {}).items():
                for campana, lista in (camps or {}).items():
                    anadir_pasadas(nombre, campana, lista)
            _backup(_JSON_HISTORICO)
        except Exception:
            pass
    # --- eventos ---
    if os.path.exists(_JSON_EVENTOS) and not _CONN.execute("SELECT 1 FROM eventos LIMIT 1").fetchone():
        try:
            with open(_JSON_EVENTOS, encoding="utf-8") as f:
                data = json.load(f)
            for parcela, camps in (data or {}).items():
                for campana, lista in (camps or {}).items():
                    for ev in lista:
                        eid = ev.get("id") or f"{parcela}_{campana}_{ev.get('fecha','')}_{uuid.uuid4().hex[:8]}"
                        datos = {k: v for k, v in ev.items() if k != "id"}
                        _CONN.execute("INSERT OR REPLACE INTO eventos(id,nombre,campana,fecha,datos) VALUES(?,?,?,?,?)",
                                      (eid, parcela, campana, ev.get("fecha", ""), json.dumps(datos, ensure_ascii=False)))
            _CONN.commit()
            _backup(_JSON_EVENTOS)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PARCELAS
# ---------------------------------------------------------------------------
def _ficha_from_row(r):
    return {"propietario": r["propietario"] or "",
            "coordenadas": json.loads(r["coordenadas"]) if r["coordenadas"] else [],
            "superficie_ha": r["superficie_ha"] or 0.0,
            "anio_inicio_monitoreo": r["anio_inicio"] or ""}


def parcelas_dict():
    """Devuelve {nombre: ficha} con la misma forma que el antiguo parcelas.json."""
    c = _c()
    with _LOCK:
        out = {}
        for r in c.execute("SELECT * FROM parcelas"):
            out[r["nombre"]] = _ficha_from_row(r)
        for r in c.execute("SELECT nombre, campana, datos FROM cultivos"):
            if r["nombre"] in out:
                out[r["nombre"]].setdefault("cultivos_por_campana", {})[r["campana"]] = json.loads(r["datos"])
        return out


def ficha(nombre):
    """Ficha de una parcela (o None) con su cultivos_por_campana."""
    c = _c()
    with _LOCK:
        r = c.execute("SELECT * FROM parcelas WHERE nombre=?", (nombre,)).fetchone()
        if not r:
            return None
        f = _ficha_from_row(r)
        for cr in c.execute("SELECT campana, datos FROM cultivos WHERE nombre=?", (nombre,)):
            f.setdefault("cultivos_por_campana", {})[cr["campana"]] = json.loads(cr["datos"])
        return f


def existe(nombre):
    c = _c()
    with _LOCK:
        return c.execute("SELECT 1 FROM parcelas WHERE nombre=?", (nombre,)).fetchone() is not None


def nombres():
    c = _c()
    with _LOCK:
        return [r["nombre"] for r in c.execute("SELECT nombre FROM parcelas ORDER BY nombre")]


def guardar_ficha(nombre, ficha):
    """Inserta/actualiza la parcela y sus cultivos por campana."""
    c = _c()
    with _LOCK:
        c.execute("INSERT INTO parcelas(nombre,propietario,coordenadas,superficie_ha,anio_inicio) "
                  "VALUES(?,?,?,?,?) ON CONFLICT(nombre) DO UPDATE SET "
                  "propietario=excluded.propietario, coordenadas=excluded.coordenadas, "
                  "superficie_ha=excluded.superficie_ha, anio_inicio=excluded.anio_inicio",
                  (nombre, ficha.get("propietario", ""),
                   json.dumps(ficha.get("coordenadas", []), ensure_ascii=False),
                   ficha.get("superficie_ha", 0.0), ficha.get("anio_inicio_monitoreo", "")))
        for camp, cult in (ficha.get("cultivos_por_campana") or {}).items():
            c.execute("INSERT INTO cultivos(nombre,campana,datos) VALUES(?,?,?) "
                      "ON CONFLICT(nombre,campana) DO UPDATE SET datos=excluded.datos",
                      (nombre, camp, json.dumps(cult, ensure_ascii=False)))
        c.commit()


def set_cultivo(nombre, campana, cultivo):
    c = _c()
    with _LOCK:
        c.execute("INSERT INTO cultivos(nombre,campana,datos) VALUES(?,?,?) "
                  "ON CONFLICT(nombre,campana) DO UPDATE SET datos=excluded.datos",
                  (nombre, campana, json.dumps(cultivo, ensure_ascii=False)))
        c.commit()


def eliminar_parcela(nombre):
    c = _c()
    with _LOCK:
        for t in ("pasadas", "cultivos", "eventos", "parcelas"):
            c.execute(f"DELETE FROM {t} WHERE nombre=?", (nombre,))
        c.commit()


# ---------------------------------------------------------------------------
# HISTORICO (pasadas del satelite)
# ---------------------------------------------------------------------------
def _pasada_from_row(r):
    d = json.loads(r["datos"]) if r["datos"] else {}
    d["fecha"] = r["fecha"]
    if r["interpretacion"] is not None:
        d["interpretacion"] = r["interpretacion"]
    return d


def pasadas(nombre, campana):
    """Lista de pasadas de una parcela/campana, ordenadas por fecha."""
    c = _c()
    with _LOCK:
        return [_pasada_from_row(r) for r in c.execute(
            "SELECT fecha,datos,interpretacion FROM pasadas WHERE nombre=? AND campana=? ORDER BY fecha",
            (nombre, campana))]


def pasadas_de_campana(campana):
    """{nombre: [pasadas]} de toda una campana en UNA sola consulta (para la lista)."""
    c = _c()
    with _LOCK:
        out = {}
        for r in c.execute("SELECT nombre,fecha,datos,interpretacion FROM pasadas "
                           "WHERE campana=? ORDER BY fecha", (campana,)):
            out.setdefault(r["nombre"], []).append(_pasada_from_row(r))
        return out


def ultima_fecha(nombre, campana):
    c = _c()
    with _LOCK:
        r = c.execute("SELECT MAX(fecha) AS f FROM pasadas WHERE nombre=? AND campana=? "
                      "AND fecha IS NOT NULL AND fecha<>''", (nombre, campana)).fetchone()
        return r["f"] if r else None


def anadir_pasadas(nombre, campana, nuevas):
    """Inserta las pasadas que no existan (no sobrescribe: conserva la interpretacion)."""
    c = _c()
    with _LOCK:
        for p in nuevas or []:
            fecha = p.get("fecha")
            if not fecha:
                continue
            datos = {k: v for k, v in p.items() if k not in ("fecha", "interpretacion")}
            c.execute("INSERT OR IGNORE INTO pasadas(nombre,campana,fecha,datos,interpretacion) "
                      "VALUES(?,?,?,?,?)",
                      (nombre, campana, fecha, json.dumps(datos, ensure_ascii=False), p.get("interpretacion")))
        c.commit()


def set_interpretacion(nombre, campana, fecha, texto):
    c = _c()
    with _LOCK:
        c.execute("UPDATE pasadas SET interpretacion=? WHERE nombre=? AND campana=? AND fecha=?",
                  (texto, nombre, campana, fecha))
        c.commit()


# ---------------------------------------------------------------------------
# RADAR (Sentinel-1): serie paralela, con sus propias fechas (atraviesa nubes)
# ---------------------------------------------------------------------------
def _radar_from_row(r):
    d = json.loads(r["datos"]) if r["datos"] else {}
    d["fecha"] = r["fecha"]
    return d


def radar(nombre, campana):
    """Lista de pasadas de radar (VV/VH/RVI) de una parcela/campana, por fecha."""
    c = _c()
    with _LOCK:
        return [_radar_from_row(r) for r in c.execute(
            "SELECT fecha,datos FROM pasadas_radar WHERE nombre=? AND campana=? ORDER BY fecha",
            (nombre, campana))]


def ultima_fecha_radar(nombre, campana):
    c = _c()
    with _LOCK:
        r = c.execute("SELECT MAX(fecha) AS f FROM pasadas_radar WHERE nombre=? AND campana=? "
                      "AND fecha IS NOT NULL AND fecha<>''", (nombre, campana)).fetchone()
        return r["f"] if r else None


def anadir_radar(nombre, campana, nuevas):
    """Inserta las pasadas de radar que no existan (no sobrescribe)."""
    c = _c()
    with _LOCK:
        for p in nuevas or []:
            fecha = p.get("fecha")
            if not fecha:
                continue
            datos = {k: v for k, v in p.items() if k != "fecha"}
            c.execute("INSERT OR IGNORE INTO pasadas_radar(nombre,campana,fecha,datos) VALUES(?,?,?,?)",
                      (nombre, campana, fecha, json.dumps(datos, ensure_ascii=False)))
        c.commit()


def campanas():
    """Conjunto de campanas presentes (en cultivos o en pasadas)."""
    c = _c()
    with _LOCK:
        s = set()
        for r in c.execute("SELECT DISTINCT campana FROM pasadas"):
            s.add(r["campana"])
        for r in c.execute("SELECT DISTINCT campana FROM cultivos"):
            s.add(r["campana"])
        return s


def campanas_con_datos():
    """Solo las campanas que tienen datos de satelite (pasadas). Las que carecen de
    datos de Copernicus no se muestran en el desplegable del panel."""
    c = _c()
    with _LOCK:
        return {r["campana"] for r in c.execute("SELECT DISTINCT campana FROM pasadas")}


# ---------------------------------------------------------------------------
# EVENTOS (cuaderno de campo)
# ---------------------------------------------------------------------------
def registrar_evento(parcela, campana, evento):
    c = _c()
    ev = dict(evento)
    ev.setdefault("id", f"{parcela}_{campana}_{ev.get('fecha','')}_{uuid.uuid4().hex[:8]}")
    ev.setdefault("registrado", datetime.now().strftime("%Y-%m-%d %H:%M"))
    datos = {k: v for k, v in ev.items() if k != "id"}
    with _LOCK:
        c.execute("INSERT OR REPLACE INTO eventos(id,nombre,campana,fecha,datos) VALUES(?,?,?,?,?)",
                  (ev["id"], parcela, campana, ev.get("fecha", ""), json.dumps(datos, ensure_ascii=False)))
        c.commit()
    return ev


def eventos_de(parcela, campana):
    c = _c()
    with _LOCK:
        out = []
        for r in c.execute("SELECT id,datos FROM eventos WHERE nombre=? AND campana=? ORDER BY fecha",
                           (parcela, campana)):
            d = json.loads(r["datos"]) if r["datos"] else {}
            d["id"] = r["id"]
            out.append(d)
        return out


def eliminar_evento(parcela, campana, evento_id):
    c = _c()
    with _LOCK:
        c.execute("DELETE FROM eventos WHERE id=?", (evento_id,))
        c.commit()


# ---------------------------------------------------------------------------
# VALIDACIONES DEL DIAGNOSTICO (aprendizaje supervisado por el agricultor)
# ---------------------------------------------------------------------------
# El usuario confirma o corrige el diagnostico de una pasada. Esas validaciones
# se reinyectan como ejemplos al pedir la interpretacion a ChatGPT, para que
# acierte mejor en pasadas futuras del mismo tipo de cultivo.
def guardar_validacion(nombre, campana, fecha, fase, cultivo,
                       estado_sistema, veredicto, estado_real=None, nota=""):
    """Guarda (o actualiza) la validacion del diagnostico de una pasada."""
    c = _c()
    with _LOCK:
        c.execute(
            "INSERT INTO validaciones(nombre,campana,fecha,fase,cultivo,estado_sistema,"
            "veredicto,estado_real,nota,ts) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(nombre,campana,fecha) DO UPDATE SET "
            "fase=excluded.fase, cultivo=excluded.cultivo, estado_sistema=excluded.estado_sistema, "
            "veredicto=excluded.veredicto, estado_real=excluded.estado_real, nota=excluded.nota, "
            "ts=excluded.ts",
            (nombre, campana, fecha, fase or "", cultivo or "", estado_sistema or "",
             veredicto or "", estado_real, nota or "", datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()


def validacion_de(nombre, campana, fecha):
    """Devuelve la validacion de una pasada concreta (o None)."""
    c = _c()
    with _LOCK:
        r = c.execute("SELECT * FROM validaciones WHERE nombre=? AND campana=? AND fecha=?",
                      (nombre, campana, fecha)).fetchone()
        return dict(r) if r else None


def validaciones_recientes(limite=8, cultivo=None):
    """Ultimas validaciones (para reinyectar como aprendizaje). Si se pasa `cultivo`,
    prioriza las del mismo tipo de cultivo."""
    c = _c()
    with _LOCK:
        if cultivo:
            filas = c.execute(
                "SELECT * FROM validaciones ORDER BY (cultivo=?) DESC, ts DESC LIMIT ?",
                (cultivo, limite)).fetchall()
        else:
            filas = c.execute("SELECT * FROM validaciones ORDER BY ts DESC LIMIT ?",
                              (limite,)).fetchall()
        return [dict(r) for r in filas]
