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
ESQUEMA_VERSION = 7

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
            sigpac TEXT,               -- JSON con los 7 codigos del recinto
            buffer_m REAL,             -- buffer interior de la rejilla; NULL = por defecto
            heterogeneidad INTEGER);   -- 1/0: incluir el analisis de zonas en la interpretacion
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
        CREATE TABLE IF NOT EXISTS pixeles(
            nombre TEXT, campana TEXT, fecha TEXT,
            datos TEXT,                -- JSON de rejilla.codificar(): NDVI por pixel
            PRIMARY KEY(nombre, campana, fecha));
        CREATE INDEX IF NOT EXISTS ix_pixeles_np ON pixeles(nombre, campana);
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
            regimen TEXT,              -- REGADIO | SECANO (lenosos); vacio = comodin
            densidad TEXT,             -- tradicional | intensivo | seto; vacio = comodin
            ts TEXT);
        CREATE TABLE IF NOT EXISTS clima(
            punto TEXT,                -- punto de la rejilla de ERA5: "lat,lon" a 0.1 grados
            fecha TEXT,
            datos TEXT,                -- JSON del dia ya en unidades de campo (°C, mm, MJ/m2)
            PRIMARY KEY(punto, fecha));
        CREATE INDEX IF NOT EXISTS ix_clima_punto ON clima(punto, fecha);
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


def _migracion_4(c):
    """Separa las validaciones por REGIMEN HIDRICO y por DENSIDAD de plantacion.

    En lenosos, un olivar de secano tradicional y un seto superintensivo de
    regadio no tienen nada que ver: si comparten clave, sus validaciones se
    contaminan y el ajuste sale peor que no ajustar. Con estas dos columnas cada
    sistema aprende de lo suyo.

    Las filas anteriores quedan con el campo vacio, que actua como comodin: lo ya
    validado en herbaceos -donde esto no aplica- sigue contando igual."""
    ya = {r[1] for r in c.execute("PRAGMA table_info(validaciones_indice)")}
    for col in ("regimen", "densidad"):
        if col not in ya:
            c.execute(f"ALTER TABLE validaciones_indice ADD COLUMN {col} TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS ix_vidx_sistema "
              "ON validaciones_indice(indice, especie, fase, regimen, densidad)")


def _migracion_5(c):
    """Rejilla de NDVI por pasada: el valor de CADA pixel, no solo la media.

    Con la media y los percentiles se sabe QUE parte de la parcela va peor, pero
    no DONDE. La rejilla guarda el NDVI pixel a pixel junto con su
    georreferenciacion, de modo que el (i,j) de dos fechas sea el mismo trozo de
    terreno y se puedan comparar en el tiempo.

    Solo NDVI: guardar los siete indices multiplicaria el tamano por siete sin
    aportar nada a esto. Medido, una parcela de 5-10 ha ocupa 0.9-1.5 KB por
    pasada (ver rejilla.py)."""
    c.execute("""
        CREATE TABLE IF NOT EXISTS pixeles(
            nombre TEXT, campana TEXT, fecha TEXT,
            datos TEXT,                -- JSON de rejilla.codificar()
            PRIMARY KEY(nombre, campana, fecha))""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_pixeles_np ON pixeles(nombre, campana)")


def _migracion_6(c):
    """Buffer interior y aviso de heterogeneidad, por parcela.

    El buffer de 15 m es un buen valor por defecto -un pixel de Sentinel-2 mas
    margen de geolocalizacion- pero no vale para todas: una parcela con un camino
    ancho por un lado quiere mas, y una estrecha y limpia quiere menos. Se guarda
    con la parcela, no en una constante.

    NULL = usar el valor por defecto del programa. Asi las parcelas que ya
    existen se comportan exactamente igual que antes."""
    ya = {r[1] for r in c.execute("PRAGMA table_info(parcelas)")}
    for col, tipo in (("buffer_m", "REAL"), ("heterogeneidad", "INTEGER")):
        if col not in ya:
            c.execute(f"ALTER TABLE parcelas ADD COLUMN {col} {tipo}")


def _migracion_7(c):
    """Tabla `clima`: el contexto climatico de ERA5-Land.

    NO va indexada por parcela, y es deliberado: el pixel de ERA5-Land son 11 km
    de lado (12.392 ha), asi que todas las parcelas de una comarca comparten el
    MISMO dato. Guardarlo por parcela seria escribir veinte copias de una sola
    medida, con veinte oportunidades de que dejaran de cuadrar entre si. Se guarda
    por PUNTO DE REJILLA y las parcelas lo consultan.

    Por eso tampoco entra en el borrado en cascada de `eliminar_parcela` como las
    demas tablas: un punto de rejilla no es de nadie. Lo que si se hace al borrar
    es tirar los puntos que ya no usa ninguna parcela (ver `purgar_clima`), para
    no dejar huerfanos."""
    c.execute("""CREATE TABLE IF NOT EXISTS clima(
                     punto TEXT, fecha TEXT, datos TEXT,
                     PRIMARY KEY(punto, fecha))""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_clima_punto ON clima(punto, fecha)")


# Migraciones por version de destino: {version: funcion(conexion)}.
# La 1 es el esquema inicial, que ya crea `_crear_tablas`, por eso no hay entrada.
_MIGRACIONES = {2: _migracion_2, 3: _migracion_3, 4: _migracion_4,
                5: _migracion_5, 6: _migracion_6, 7: _migracion_7}


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
            "sigpac": json.loads(_col(r, "sigpac")) if _col(r, "sigpac") else {},
            # NULL = "usa el valor por defecto del programa". Se distingue de un 0
            # explicito, que significa "esta parcela sin buffer, a proposito".
            "buffer_m": _col(r, "buffer_m"),
            "heterogeneidad": (True if _col(r, "heterogeneidad") is None
                               else bool(_col(r, "heterogeneidad")))}


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
        # `buffer_m` tiene DOS vacios distintos y hay que separarlos:
        #   - la clave NO viene    -> un guardado que no sabe del margen: no se toca
        #   - la clave viene None  -> «usa el margen por defecto»: hay que poner NULL
        # COALESCE solo ve el valor, no si la clave estaba, asi que con COALESCE
        # siempre se conservaba lo viejo y una parcela puesta a 40 m no podia volver
        # al valor por defecto NUNCA, aunque el dialogo dijera que se habia guardado.
        # La decision se toma aqui, donde si se sabe. (Los dos fragmentos son
        # constantes del propio modulo: no entra nada del usuario en el SQL.)
        set_buffer = ("buffer_m=excluded.buffer_m, " if "buffer_m" in ficha
                      else "buffer_m=COALESCE(excluded.buffer_m, parcelas.buffer_m), ")
        c.execute("INSERT INTO parcelas(nombre,propietario,coordenadas,superficie_ha,"
                  "anio_inicio,provincia,municipio,sigpac,buffer_m,heterogeneidad) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(nombre) DO UPDATE SET "
                  "propietario=excluded.propietario, coordenadas=excluded.coordenadas, "
                  "superficie_ha=excluded.superficie_ha, anio_inicio=excluded.anio_inicio, "
                  "provincia=COALESCE(excluded.provincia, parcelas.provincia), "
                  "municipio=COALESCE(excluded.municipio, parcelas.municipio), "
                  "sigpac=COALESCE(excluded.sigpac, parcelas.sigpac), "
                  + set_buffer +
                  "heterogeneidad=COALESCE(excluded.heterogeneidad, parcelas.heterogeneidad)",
                  (nombre, ficha.get("propietario", ""),
                   json.dumps(ficha.get("coordenadas", []), ensure_ascii=False),
                   ficha.get("superficie_ha", 0.0), ficha.get("anio_inicio_monitoreo", ""),
                   ficha.get("provincia") or None, ficha.get("municipio") or None,
                   json.dumps(sig, ensure_ascii=False) if sig else None,
                   ficha.get("buffer_m"),
                   None if ficha.get("heterogeneidad") is None
                   else int(bool(ficha["heterogeneidad"]))))
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


# Avisos de "se ha borrado una parcela". Quien tenga algo DERIVADO de sus datos
# -una cache, un indice en memoria- se apunta aqui y se entera, sin que `almacen`
# tenga que conocerlo. Hace falta al reves: `calibracion_umbrales` ya importa
# `almacen`, asi que si `almacen` lo importara habria un ciclo. Y no vale con
# avisar desde quien borra: el borrado se llama desde el panel, desde la demo y
# desde las pruebas, y basta con que uno se olvide.
_AL_BORRAR = []


def al_eliminar_parcela(fn):
    """Registra un aviso para cuando se borre una parcela. `fn(nombre)`."""
    if fn not in _AL_BORRAR:
        _AL_BORRAR.append(fn)
    return fn


def eliminar_parcela(nombre):
    c = _c()
    with _LOCK:
        # TODAS las tablas que referencian la parcela. Si se olvida alguna, sus filas
        # quedan huerfanas y una parcela nueva con el mismo nombre heredaria los datos
        # de la anterior (le pasaba a pasadas_radar y a validaciones).
        for t in ("pasadas", "pasadas_radar", "pixeles", "cultivos", "eventos",
                  "validaciones", "validaciones_indice", "parcelas"):
            c.execute(f"DELETE FROM {t} WHERE nombre=?", (nombre,))
        c.commit()
    # ...y fuera del lock, porque quien escuche no tiene por que ser rapido y no
    # debe poder bloquear la base. Un oyente que falle no impide avisar al resto:
    # la parcela YA esta borrada, y tragarse el aviso dejaria a los demas rancios.
    for fn in list(_AL_BORRAR):
        try:
            fn(nombre)
        except Exception:
            log.warning("aviso de borrado fallido en %r", fn, exc_info=True)


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
# CLIMA (ERA5-Land): por PUNTO DE REJILLA, no por parcela
# ---------------------------------------------------------------------------
# El pixel de ERA5-Land son 11 km de lado, asi que todas las parcelas de una
# comarca comparten el MISMO dato. Se guarda una vez y lo consultan todas: no son
# veinte medidas, es una. Aqui solo se guarda y se lee; que significan esos
# numeros vive en `clima_era5.py`, que es opcional y extraible.
def anadir_clima(punto, dias):
    """Guarda los dias que falten de ese punto. No pisa lo que ya hubiera."""
    c = _c()
    with _LOCK:
        for d in dias or []:
            fecha = d.get("fecha")
            if not punto or not fecha:
                continue
            datos = {k: v for k, v in d.items() if k != "fecha"}
            c.execute("INSERT OR IGNORE INTO clima(punto,fecha,datos) VALUES(?,?,?)",
                      (punto, fecha, json.dumps(datos, ensure_ascii=False)))
        c.commit()


def clima(punto, desde=None, hasta=None):
    """Los dias de ese punto, en orden. Con `desde`/`hasta`, solo ese tramo."""
    if not punto:
        return []
    sql = "SELECT fecha,datos FROM clima WHERE punto=?"
    args = [punto]
    if desde:
        sql += " AND fecha>=?"
        args.append(desde)
    if hasta:
        sql += " AND fecha<=?"
        args.append(hasta)
    c = _c()
    with _LOCK:
        out = []
        for r in c.execute(sql + " ORDER BY fecha", args):
            d = json.loads(r["datos"]) if r["datos"] else {}
            d["fecha"] = r["fecha"]
            out.append(d)
        return out


def ultima_fecha_clima(punto):
    """MAX(fecha) de ese punto, para pedir solo lo que falte."""
    if not punto:
        return None
    c = _c()
    with _LOCK:
        r = c.execute("SELECT MAX(fecha) AS f FROM clima WHERE punto=? AND fecha<>''",
                      (punto,)).fetchone()
        return r["f"] if r else None


def puntos_clima():
    """Los puntos de rejilla que hay guardados."""
    c = _c()
    with _LOCK:
        return {r["punto"] for r in c.execute("SELECT DISTINCT punto FROM clima")}


def purgar_clima(en_uso):
    """Borra los puntos de rejilla que ya no usa ninguna parcela.

    El clima no es de nadie, asi que no entra en el borrado en cascada de una
    parcela como las demas tablas; pero si se borra la ultima parcela de una
    comarca, su serie se queda ahi para siempre. `en_uso` es el conjunto de puntos
    que siguen haciendo falta. Devuelve cuantos puntos se han tirado."""
    c = _c()
    with _LOCK:
        sobran = puntos_clima() - set(en_uso or ())
        for p in sobran:
            c.execute("DELETE FROM clima WHERE punto=?", (p,))
        c.commit()
        return len(sobran)


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


def campanas_de(nombre):
    """Campanas de UNA parcela que tienen pasadas guardadas, de la mas antigua a
    la mas reciente. Lo usa el relleno de rejillas para saber que hay que rellenar."""
    c = _c()
    with _LOCK:
        return [r["campana"] for r in c.execute(
            "SELECT DISTINCT campana FROM pasadas WHERE nombre=? ORDER BY campana",
            (nombre,))]


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
# REJILLA DE PIXELES (NDVI pixel a pixel, para comparar en el tiempo)
# ---------------------------------------------------------------------------
def guardar_rejilla(nombre, campana, fecha, datos):
    """Guarda la rejilla de una pasada. INSERT OR REPLACE: volver a descargarla
    -por ejemplo al rellenar el historico- la actualiza sin duplicar."""
    c = _c()
    with _LOCK:
        c.execute("INSERT OR REPLACE INTO pixeles(nombre,campana,fecha,datos) VALUES(?,?,?,?)",
                  (nombre, campana, fecha, json.dumps(datos, ensure_ascii=False)))
        c.commit()


def fechas_de(nombre, campana, radar=False):
    """Las fechas guardadas de esa parcela y campana, y NADA mas.

    La sincronizacion solo necesita saber que dias tiene ya para no volver a
    pedirlos. Pidiendo `pasadas()` se traia cada fila entera y se deserializaba su
    JSON -todos los indices, los percentiles, la interpretacion cacheada- para
    quedarse con un campo y tirar el resto: en una parcela con varias campanas de
    historico son miles de blobs parseados por sincronizacion. Igual que
    `fechas_con_rejilla`, que ya lo hacia bien."""
    tabla = "pasadas_radar" if radar else "pasadas"
    c = _c()
    with _LOCK:
        return {r["fecha"] for r in c.execute(
            f"SELECT fecha FROM {tabla} WHERE nombre=? AND campana=?", (nombre, campana))
            if r["fecha"]}


def fechas_con_rejilla(nombre, campana):
    """Fechas de esa campana que YA tienen rejilla. Lo usa la descarga para no
    volver a pedir lo que ya esta."""
    c = _c()
    with _LOCK:
        return {r["fecha"] for r in c.execute(
            "SELECT fecha FROM pixeles WHERE nombre=? AND campana=?", (nombre, campana))}


def rejillas(nombre, campana=None):
    """Rejillas guardadas, ordenadas por fecha. Sin `campana`, todas las campanas
    (es lo que hace falta para comparar un ano con otro).

    Devuelve la lista TAL CUAL esta guardada. Quien compare debe pasar por
    `rejilla.comparables` para no mezclar reticulas distintas."""
    c = _c()
    sql = "SELECT campana,fecha,datos FROM pixeles WHERE nombre=?"
    args = [nombre]
    if campana:
        sql += " AND campana=?"
        args.append(campana)
    with _LOCK:
        filas = list(c.execute(sql + " ORDER BY campana,fecha", args))
    out = []
    for r in filas:
        try:
            d = json.loads(r["datos"]) if r["datos"] else None
        except ValueError:
            log.warning("rejilla ilegible en %s %s %s", nombre, r["campana"], r["fecha"])
            continue
        if d:
            d["campana"], d["fecha"] = r["campana"], r["fecha"]
            out.append(d)
    return out


def tamano_rejillas(nombre=None):
    """(n_rejillas, bytes) de lo que ocupan. Sirve para vigilar el gasto de disco."""
    c = _c()
    sql = "SELECT COUNT(*), COALESCE(SUM(LENGTH(datos)),0) FROM pixeles"
    args = []
    if nombre:
        sql += " WHERE nombre=?"
        args.append(nombre)
    with _LOCK:
        n, b = c.execute(sql, args).fetchone()
    return int(n), int(b)


# ---------------------------------------------------------------------------
# VALIDACIONES POR INDICE (las consume el modulo extraible calibracion_umbrales)
# ---------------------------------------------------------------------------
# Aqui solo se guarda y se lee. QUE se hace con estos datos -como se mueve un
# umbral- vive en calibracion_umbrales.py, para poder borrarlo sin tocar nada.
def guardar_validacion_indice(nombre, campana, fecha, indice, valor, especie, fase,
                              dijo_sistema, dijo_usuario, ambito, clave_ambito,
                              regimen="", densidad=""):
    """Anota lo que el usuario dice de UN indice en UNA pasada.

    La clave incluye el ambito: la misma pasada puede corregirse a nivel de
    parcela y, mas adelante, a nivel de municipio, y son dos hechos distintos.
    Repetir la misma correccion la sustituye, no la duplica."""
    c = _c()
    clave = f"{nombre}|{campana}|{fecha}|{indice}|{ambito}|{clave_ambito or ''}"
    with _LOCK:
        c.execute("INSERT OR REPLACE INTO validaciones_indice(id,nombre,campana,fecha,indice,"
                  "valor,especie,fase,dijo_sistema,dijo_usuario,ambito,clave_ambito,"
                  "regimen,densidad,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (clave, nombre, campana, fecha, indice,
                   None if valor is None else float(valor), especie or "", fase or "",
                   dijo_sistema or "", dijo_usuario or "", ambito or "parcela",
                   clave_ambito or "", regimen or "", densidad or "",
                   datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
    return clave


def validaciones_indice(indice=None, especie=None, fase=None, ambitos=None,
                        regimen=None, densidad=None):
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
    # regimen y densidad: el vacio es COMODIN, no un valor. Las filas anteriores a
    # la migracion 4 -y todos los herbaceos- lo tienen vacio y siguen contando.
    for col, val in (("regimen", regimen), ("densidad", densidad)):
        if val:
            sql += f" AND ({col}=? OR {col}='' OR {col} IS NULL)"
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
