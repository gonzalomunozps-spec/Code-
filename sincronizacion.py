# -*- coding: utf-8 -*-
"""
sincronizacion.py
=================

Estado y ritmo de la sincronizacion con el satelite. Sin interfaz y sin Earth
Engine: aqui solo se decide CUANDO toca sincronizar y se recuerda COMO fue la
ultima vez. Quien descarga es `gee_cliente`.

Contiene:
  - la escritura/lectura ATOMICA y tolerante de los JSON de estado,
  - la marca de tiempo del ultimo sync (persistente entre arranques),
  - `toca_sincronizar`, funcion pura que decide si hay que mirar otra vez,
  - `ULTIMO_SYNC`, el resultado del ultimo intento, para poder mostrarlo.
"""

import json
import os
import tempfile
import threading
from datetime import datetime

import rutas
from bitacora import log

# Marca del ultimo sync (estado, no datos), en el directorio de datos del usuario
ARCHIVO_ESTADO = rutas.ruta("estado_sync.json")

# Cerrojo de entrada/salida: el auto-sync, la sincronizacion manual y el worker de
# interpretacion corren en hilos aparte y tocan los mismos ficheros; sin esto
# podrian pisarse y perder datos.
_IO_LOCK = threading.RLock()


def _load(path):
    """Lectura tolerante: si el fichero falta o esta corrupto, devuelve {} en vez
    de reventar (p. ej. un JSON a medio escribir por un corte anterior)."""
    with _IO_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}


def _save(path, data):
    """Escritura ATOMICA: se vuelca a un temporal y se reemplaza de golpe con
    os.replace. Asi un corte a mitad nunca deja el JSON corrupto (o esta el
    fichero viejo intacto, o el nuevo completo)."""
    with _IO_LOCK:
        carpeta = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=carpeta)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                log.warning("no se pudo borrar el temporal %s", tmp, exc_info=True)
            raise


def _actualizar(path, mutador):
    """Read-modify-write serializado: relee el fichero MAS RECIENTE bajo cerrojo,
    aplica el cambio y lo guarda. Evita que dos hilos que cargaron el JSON en
    momentos distintos se pisen al guardar (auto-sync vs. worker de IA)."""
    with _IO_LOCK:
        data = _load(path)
        mutador(data)
        _save(path, data)


# --- marca de tiempo del ultimo sync (persistente, para decidir en el arranque) ---
def marca_leer():
    """Devuelve el ISO del ultimo sync realizado, o None si no hay."""
    return _load(ARCHIVO_ESTADO).get("ultima_comprobacion")


def marca_guardar():
    _save(ARCHIVO_ESTADO, {"ultima_comprobacion": datetime.now().isoformat(timespec="seconds")})


def toca_sincronizar(ultima_iso, intervalo_ms, ahora=None):
    """True si nunca se sincronizo o si ya ha pasado el intervalo desde entonces.
    Funcion pura (sin ficheros): asi el arranque solo sincroniza cuando toca."""
    if not ultima_iso:
        return True
    try:
        ult = datetime.fromisoformat(ultima_iso)
    except (TypeError, ValueError):
        return True
    ahora = ahora or datetime.now()
    return (ahora - ult).total_seconds() * 1000.0 >= intervalo_ms


# Cada cuanto se comprueba AUTOMATICAMENTE si hay pasadas nuevas del satelite.
# Sentinel-2 repite orbita cada ~5 dias (menos aun con nubes), asi que no hace
# falta mirar a menudo. Ademas se sincroniza al abrir la app y se puede forzar a
# mano en cualquier momento (boton "Sincronizar ahora" o desde cada ficha).
DIAS_AUTOSYNC = 1                            # pon 2 para comprobar cada dos dias
INTERVALO_AUTOSYNC_MS = DIAS_AUTOSYNC * 24 * 60 * 60 * 1000

# Resultado de la ultima sincronizacion (la automatica es silenciosa; esto deja
# constancia de si fallo, para poder mostrarlo en la pestana de Credenciales).
ULTIMO_SYNC = {"estado": None, "msg": "aun no se ha sincronizado"}
