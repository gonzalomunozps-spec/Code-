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

import rutas
from bitacora import log   # registro de incidencias (no cambia nada visible)
import sqlite3
import threading
from datetime import datetime

RUTA_DB = rutas.ruta("parcelas.db")   # en el directorio de datos del usuario
_CONN = None
_LOCK = threading.RLock()

# =====================================================================
# VERSION DEL ESQUEMA (PRAGMA user_version)
# =====================================================================
# La base guarda su propia version. Al abrirla, `_migrar_esquema` aplica en orden
# las migraciones que le falten, de una en una, hasta ESQUEMA_VERSION.
#
# COMO ANADIR UNA MIGRACION EN EL FUTURO (ejemplo: pasar de la 1 a la 2)
#   1. Sube la constante:            ESQUEMA_VERSION = 2
#   2. Escribe la funcion del paso:
#          def _migracion_2(c):
#              \"\"\"Anade la columna 'riego' a parcelas.\"\"\"
#              c.execute("ALTER TABLE parcelas ADD COLUMN riego TEXT")
#   3. Registrala en el diccionario:  _MIGRACIONES = {2: _migracion_2, ...}
#
# Reglas para que una base de 10 anos siga abriendose sin sustos:
#   - Cada migracion debe ser IDEMPOTENTE en la practica y no destruir datos:
#     anadir columnas o tablas, si; renombrar o borrar, solo con mucho cuidado.
#   - Nunca cambies una migracion ya publicada: escribe la siguiente.
#   - `_crear_tablas` usa CREATE TABLE IF NOT EXISTS, asi que crea el esquema
#     COMPLETO y ACTUAL para una base nueva; las migraciones solo sirven para
#     poner al dia las bases que ya existian.
ESQUEMA_VERSION = 3

# JSON antiguos a importar la primera vez. Se buscan en el DIRECTORIO DE TRABAJO
# a proposito: son ficheros de versiones antiguas, que se ejecutaban ahi.
_JSON_PARCELAS = "parcelas.json"
_JSON_HISTORICO = "historico_reportes.json"
_JSON_EVENTOS = "eventos_parcela.json"


# ---------------------------------------------------------------------------
# Conexion / esquema / migracion
# ---------------------------------------------------------------------------
def _rescatar_bd_del_cwd(destino):
    """Traslada UNA sola vez la base de datos de una version anterior.

    Hasta ahora `parcelas.db` se creaba en el directorio de trabajo. Si el usuario
    tiene ahi su base y todavia no hay ninguna en el directorio de datos, se mueve
    (con sus ficheros -wal y -shm) para que no "pierda" sus parcelas al arrancar
    el programa desde otra carpeta.

    Solo actua si: existe en el cwd, NO existe en el destino y no son el mismo
    fichero. Si el traslado falla, se deja donde estaba y se sigue usando: nunca
    se borra ni se pisa nada.
    """
    origen = os.path.abspath("parcelas.db")
    destino = os.path.abspath(destino)
    if origen == destino or not os.path.exists(origen) or os.path.exists(destino):
        return destino
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        os.replace(origen, destino)
        for suf in ("-wal", "-shm"):        # ficheros auxiliares del modo WAL
            if os.path.exists(origen + suf):
                try:
                    os.replace(origen + suf, destino + suf)
                except OSError:
                    pass                    # silencio deliberado: se regeneran solos
        log.warning("base de datos trasladada de %s a %s (nueva ubicacion de datos)",
                    origen, destino)
        return destino
    except Exception:
        # no se pudo mover: se sigue usando la de siempre, sin perder nada
        log.warning("no se pudo trasladar %s a %s; se seguira usando la del "
                    "directorio de trabajo", origen, destino, exc_info=True)
        return origen


def conectar(ruta=None):
    """Abre (o reutiliza) la conexion. Con `ruta` distinta, reconecta (util en tests)."""
    global _CONN, RUTA_DB
    with _LOCK:
        if ruta and ruta != RUTA_DB:
            cerrar()
            RUTA_DB = ruta
        elif _CONN is None and not ruta:
            # solo en el arranque normal (sin ruta explicita, como en las pruebas)
            RUTA_DB = _rescatar_bd_del_cwd(RUTA_DB)
        if _CONN is None:
            _CONN = sqlite3.connect(RUTA_DB, check_same_thread=False)
            _CONN.row_factory = sqlite3.Row
            try:
                _CONN.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                log.warning("no se pudo activar WAL en SQLite", exc_info=True)
            _crear_tablas()
            _migrar_esquema()      # pone al dia el esquema si la base es antigua
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
            anio_inicio TEXT,
            provincia TEXT,            -- codigo SIGPAC de provincia
            municipio TEXT,            -- codigo SIGPAC de municipio
            sigpac TEXT);              -- JSON con los 7 codigos del recinto
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
        CREATE TABLE IF NOT EXISTS validaciones_indice(
            id TEXT PRIMARY KEY,
            nombre TEXT, campana TEXT, fecha TEXT,
            indice TEXT,               -- NDVI, NDMI, LAI...
            valor REAL,                -- lo que midio el satelite ese dia
            especie TEXT, fase TEXT,
            dijo_sistema TEXT,         -- bajo | normal | alto
            dijo_usuario TEXT,         -- bajo | normal | alto
            ambito TEXT,               -- parcela | municipio | provincia | global
            clave_ambito TEXT,
            ts TEXT);
        CREATE INDEX IF NOT EXISTS ix_vidx_busca
            ON validaciones_indice(indice, especie, fase, ambito, clave_ambito);
        CREATE INDEX IF NOT EXISTS ix_vidx_parcela ON validaciones_indice(nombre);
        CREATE INDEX IF NOT EXISTS ix_pasadas_np ON pasadas(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_pasadas_c  ON pasadas(campana);
        CREATE INDEX IF NOT EXISTS ix_radar_np   ON pasadas_radar(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_cultivos_c ON cultivos(campana);
        CREATE INDEX IF NOT EXISTS ix_eventos_np ON eventos(nombre, campana);
        CREATE INDEX IF NOT EXISTS ix_valida_ts  ON validaciones(ts);
    """)
    _CONN.commit()


def _migracion_2(c):
    """Guarda DONDE esta la parcela: provincia, municipio y los codigos SIGPAC.

    Hasta ahora los 7 codigos SIGPAC se tecleaban para capturar el recinto y se
    tiraban en cuanto llegaba el poligono. Sin provincia y municipio no se puede
    corregir un umbral "para todo el municipio", que es la unidad en la que un
    agricultor piensa. Se anaden vacios: las parcelas existentes no se tocan y se
    rellenan cuando se editen.

    Idempotente: en una base NUEVA las columnas ya vienen de `_crear_tablas`, asi
    que se comprueba antes de anadirlas."""
    ya = {r[1] for r in c.execute("PRAGMA table_info(parcelas)")}
    for col, tipo in (("provincia", "TEXT"), ("municipio", "TEXT"), ("sigpac", "TEXT")):
        if col not in ya:
            c.execute(f"ALTER TABLE parcelas ADD COLUMN {col} {tipo}")


def _migracion_3(c):
    """Validaciones POR INDICE (las usa el modulo extraible calibracion_umbrales).

    La tabla `validaciones` guarda el veredicto sobre el diagnostico entero. Esta
    guarda, ademas, que dijo el usuario de CADA indice por separado, que es lo que
    permite mover el umbral de ese indice y no los demas. Vive aqui, y no en el
    modulo, porque el esquema es responsabilidad del almacen: si se borra el
    modulo la tabla se queda quieta, sin estorbar."""
    c.execute("""
        CREATE TABLE IF NOT EXISTS validaciones_indice(
            id TEXT PRIMARY KEY,
            nombre TEXT,               -- parcela
            campana TEXT,
            fecha TEXT,                -- dia de la pasada
            indice TEXT,               -- NDVI, NDMI, LAI...
            valor REAL,                -- lo que medio el satelite ese dia
            especie TEXT,
            fase TEXT,
            dijo_sistema TEXT,         -- bajo | normal | alto
            dijo_usuario TEXT,         -- bajo | normal | alto
            ambito TEXT,               -- parcela | municipio | provincia | global
            clave_ambito TEXT,         -- valor del ambito (nombre, municipio, provincia o '')
            ts TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_vidx_busca "
              "ON validaciones_indice(indice, especie, fase, ambito, clave_ambito)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_vidx_parcela ON validaciones_indice(nombre)")


# Migraciones por version de destino: {version: funcion(conexion)}.
# La 1 es el esquema inicial, que ya crea `_crear_tablas`, por eso no hay entrada.
_MIGRACIONES = {2: _migracion_2, 3: _migracion_3}


def _migrar_esquema():
    """Pone la base al dia aplicando en orden las migraciones que le falten.

    La version vive en la propia base (PRAGMA user_version), asi que el programa
    sabe con que esquema se creo aunque el fichero venga de otro equipo.
    """
    actual = _CONN.execute("PRAGMA user_version").fetchone()[0]
    if actual == ESQUEMA_VERSION:
        return actual
    if actual > ESQUEMA_VERSION:
        # base creada por una version MAS NUEVA del programa: no se toca
        log.warning("la base es de un esquema mas nuevo (v%s) que este programa (v%s); "
                    "se abre tal cual, pero conviene actualizar el programa",
                    actual, ESQUEMA_VERSION)
        return actual
    for version in range(actual + 1, ESQUEMA_VERSION + 1):
        paso = _MIGRACIONES.get(version)
        if paso is not None:
            paso(_CONN)                      # cada paso, en su propia transaccion
            log.warning("esquema migrado a la version %s", version)
        _CONN.execute(f"PRAGMA user_version = {version}")
        _CONN.commit()
    return ESQUEMA_VERSION


def _backup(path):
    try:
        os.replace(path, path + ".bak")
    except OSError:
        log.warning("no se pudo renombrar %s a .bak tras migrarlo", path, exc_info=True)


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
            log.warning("fallo al importar %s: las parcelas no se han migrado",
                        _JSON_PARCELAS, exc_info=True)
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
            log.warning("fallo al importar %s: el historico no se ha migrado",
                        _JSON_HISTORICO, exc_info=True)
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
            log.warning("fallo al importar %s: los eventos no se han migrado",
                        _JSON_EVENTOS, exc_info=True)


# ---------------------------------------------------------------------------
# PARCELAS
# ---------------------------------------------------------------------------
def _col(r, nombre):
    """Columna que puede no existir todavia (bases anteriores a su migracion)."""
    try:
        return r[nombre]
    except (IndexError, KeyError):
        return None


def _ficha_from_row(r):
    return {"propietario": r["propietario"] or "",
            "coordenadas": json.loads(r["coordenadas"]) if r["coordenadas"] else [],
            "superficie_ha": r["superficie_ha"] or 0.0,
            "anio_inicio_monitoreo": r["anio_inicio"] or "",
            "provincia": _col(r, "provincia") or "",
            "municipio": _col(r, "municipio") or "",
            "sigpac": json.loads(_col(r, "sigpac")) if _col(r, "sigpac") else {}}


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
        # provincia/municipio/sigpac: si la ficha no los trae NO se pisan los que
        # ya hubiera (COALESCE). Asi un guardado que no sabe de ellos -por ejemplo
        # una version antigua del dialogo- no borra la ubicacion.
        sig = ficha.get("sigpac") or None
        c.execute("INSERT INTO parcelas(nombre,propietario,coordenadas,superficie_ha,"
                  "anio_inicio,provincia,municipio,sigpac) VALUES(?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(nombre) DO UPDATE SET "
                  "propietario=excluded.propietario, coordenadas=excluded.coordenadas, "
                  "superficie_ha=excluded.superficie_ha, anio_inicio=excluded.anio_inicio, "
                  "provincia=COALESCE(excluded.provincia, parcelas.provincia), "
                  "municipio=COALESCE(excluded.municipio, parcelas.municipio), "
                  "sigpac=COALESCE(excluded.sigpac, parcelas.sigpac)",
                  (nombre, ficha.get("propietario", ""),
                   json.dumps(ficha.get("coordenadas", []), ensure_ascii=False),
                   ficha.get("superficie_ha", 0.0), ficha.get("anio_inicio_monitoreo", ""),
                   ficha.get("provincia") or None, ficha.get("municipio") or None,
                   json.dumps(sig, ensure_ascii=False) if sig else None))
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
        # TODAS las tablas que referencian la parcela. Si se olvida alguna, sus filas
        # quedan huerfanas y una parcela nueva con el mismo nombre heredaria los datos
        # de la anterior (le pasaba a pasadas_radar y a validaciones).
        for t in ("pasadas", "pasadas_radar", "cultivos", "eventos",
                  "validaciones", "validaciones_indice", "parcelas"):
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


def rendimientos(nombre):
    """Historico de cosecha de una parcela, campana a campana.

    Devuelve la lista de eventos COSECHA de TODAS las campanas (no solo la
    activa) que llevan algun dato de rendimiento, ordenados por campana y
    fecha. Es un volcado literal de lo que se anoto en el cuaderno: aqui no se
    calcula, ni se promedia, ni se corrige nada. Kg/ha sale de la bascula, no
    de una estimacion del programa.

    Cada elemento: {campana, fecha, rendimiento_kg_ha, humedad_grano_pct,
    superficie_cosechada_ha, fuente_dato}. Las claves que no se anotaron
    sencillamente no estan."""
    c = _c()
    with _LOCK:
        filas = list(c.execute(
            "SELECT campana,fecha,datos FROM eventos WHERE nombre=? ORDER BY campana,fecha",
            (nombre,)))
    out = []
    for r in filas:
        d = json.loads(r["datos"]) if r["datos"] else {}
        if d.get("tipo") != "COSECHA":
            continue
        reg = {"campana": r["campana"], "fecha": r["fecha"]}
        for k in ("rendimiento_kg_ha", "humedad_grano_pct",
                  "superficie_cosechada_ha", "fuente_dato"):
            if d.get(k) not in (None, ""):
                reg[k] = d[k]
        if len(reg) > 2:            # solo si trae algun dato de cosecha
            out.append(reg)
    return out


def eliminar_evento(parcela, campana, evento_id):
    # Se acota por parcela y campana ademas de por id: el id deberia bastar, pero
    # sin acotar un id repetido o mal formado podria borrar el evento de OTRA
    # parcela. Los tres criterios juntos hacen imposible ese borrado cruzado.
    c = _c()
    with _LOCK:
        c.execute("DELETE FROM eventos WHERE id=? AND nombre=? AND campana=?",
                  (evento_id, parcela, campana))
        c.commit()


# ---------------------------------------------------------------------------
# VALIDACIONES POR INDICE (las consume el modulo extraible calibracion_umbrales)
# ---------------------------------------------------------------------------
# Aqui solo se guarda y se lee. QUE se hace con estos datos -como se mueve un
# umbral- vive en calibracion_umbrales.py, para poder borrarlo sin tocar nada.
def guardar_validacion_indice(nombre, campana, fecha, indice, valor, especie, fase,
                              dijo_sistema, dijo_usuario, ambito, clave_ambito):
    """Anota lo que el usuario dice de UN indice en UNA pasada.

    La clave incluye el ambito: la misma pasada puede corregirse a nivel de
    parcela y, mas adelante, a nivel de municipio, y son dos hechos distintos.
    Repetir la misma correccion la sustituye, no la duplica."""
    c = _c()
    clave = f"{nombre}|{campana}|{fecha}|{indice}|{ambito}|{clave_ambito or ''}"
    with _LOCK:
        c.execute("INSERT OR REPLACE INTO validaciones_indice(id,nombre,campana,fecha,indice,"
                  "valor,especie,fase,dijo_sistema,dijo_usuario,ambito,clave_ambito,ts) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (clave, nombre, campana, fecha, indice,
                   None if valor is None else float(valor), especie or "", fase or "",
                   dijo_sistema or "", dijo_usuario or "", ambito or "parcela",
                   clave_ambito or "", datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
    return clave


def validaciones_indice(indice=None, especie=None, fase=None, ambitos=None):
    """Validaciones por indice, filtrando por lo que se necesite.

    `ambitos` es una lista de pares (ambito, clave) -por ejemplo
    [("parcela","La Vega"), ("municipio","47/186"), ("global","")]-. Devolver
    todas juntas permite a quien llama decidir la precedencia."""
    sql = "SELECT * FROM validaciones_indice WHERE 1=1"
    args = []
    for col, val in (("indice", indice), ("especie", especie), ("fase", fase)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    if ambitos:
        sql += " AND (" + " OR ".join(["(ambito=? AND clave_ambito=?)"] * len(ambitos)) + ")"
        for a, k in ambitos:
            args += [a, k or ""]
    c = _c()
    with _LOCK:
        return [dict(r) for r in c.execute(sql + " ORDER BY ts", args)]


def validaciones_indice_de_pasada(nombre, campana, fecha):
    """Lo que el usuario dijo de cada indice en una pasada concreta."""
    c = _c()
    with _LOCK:
        return {r["indice"]: dict(r) for r in c.execute(
            "SELECT * FROM validaciones_indice WHERE nombre=? AND campana=? AND fecha=? "
            "ORDER BY ts", (nombre, campana, fecha))}


def pasadas_validadas(nombre, campana):
    """Fechas de esa campana que tienen ALGUNA validacion (del diagnostico o de
    un indice). Sirve para marcar en la lista cuales ya se han revisado."""
    c = _c()
    with _LOCK:
        f = {r["fecha"] for r in c.execute(
            "SELECT fecha FROM validaciones WHERE nombre=? AND campana=?", (nombre, campana))}
        f |= {r["fecha"] for r in c.execute(
            "SELECT DISTINCT fecha FROM validaciones_indice WHERE nombre=? AND campana=?",
            (nombre, campana))}
        return f


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
