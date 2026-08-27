# -*- coding: utf-8 -*-
"""
copias.py
=========

COPIAS DE SEGURIDAD de la base de datos. Toda la informacion de la empresa
-parcelas, pasadas, cuaderno, observaciones- vive en UN fichero SQLite; si se
corrompe o se pierde el equipo, se pierde todo. Este modulo hace copias con fecha,
las rota (guarda solo las N mas nuevas) y sabe restaurarlas.

Es OPCIONAL y AUTONOMO: no importa `almacen` (para no atarse a la conexion viva);
abre su propia conexion de solo lectura y usa el backup ONLINE de SQLite, que da
una instantanea consistente aunque la base este en modo WAL y en uso. Si se borra
este fichero, el programa sigue funcionando: solo desaparece la copia automatica.

La copia automatica del arranque (`crear_copia_si_toca`) esta limitada: no vuelve
a copiar si ya hay una reciente, para no llenar el disco de copias iguales.
"""

import os
import glob
import shutil
import sqlite3
from datetime import datetime

import rutas
from bitacora import log

PREFIJO = "parcelas_"
SUFIJO = ".db"
PREFIJO_RESTAURAR = "antes_de_restaurar_"
MAX_COPIAS = 10           # copias con fecha que se conservan (las mas nuevas)
INTERVALO_HORAS = 12      # no repetir la copia automatica si hay una mas nueva que esto


def dir_copias():
    """Carpeta 'copias' dentro del directorio de datos, creada si hace falta."""
    d = os.path.join(rutas.directorio_datos(), "copias")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _nombre(ahora=None):
    ahora = ahora or datetime.now()
    return f"{PREFIJO}{ahora.strftime('%Y%m%d_%H%M%S')}{SUFIJO}"


def listar():
    """Copias con fecha existentes, de la mas NUEVA a la mas vieja. Cada una es un
    dict {ruta, nombre, mtime, bytes}. No incluye las de seguridad de restaurar."""
    out = []
    for f in glob.glob(os.path.join(dir_copias(), PREFIJO + "*" + SUFIJO)):
        try:
            st = os.stat(f)
            out.append({"ruta": f, "nombre": os.path.basename(f),
                        "mtime": st.st_mtime, "bytes": st.st_size})
        except OSError:
            pass
    out.sort(key=lambda c: c["mtime"], reverse=True)
    return out


def _copiar_db(origen, destino):
    """Copia CONSISTENTE de una base SQLite (aguanta WAL y uso concurrente) con el
    backup online. Deja en `destino` una base de un solo fichero, sin WAL."""
    src = sqlite3.connect(origen)
    try:
        dst = sqlite3.connect(destino)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def rotar(maximo=MAX_COPIAS):
    """Deja solo las `maximo` copias con fecha mas nuevas. Devuelve cuantas borro.
    `maximo <= 0` no borra nada (se conservan todas)."""
    if maximo is None or maximo <= 0:
        return 0
    borradas = 0
    for c in listar()[maximo:]:
        try:
            os.remove(c["ruta"])
            borradas += 1
        except OSError:
            pass
    return borradas


def crear_copia(origen_db, ahora=None, maximo=MAX_COPIAS):
    """Crea una copia con fecha de `origen_db` y rota. Devuelve la ruta creada, o
    None si no se pudo (la base no existe o fallo la copia). Nunca lanza."""
    if not origen_db or not os.path.exists(origen_db):
        return None
    destino = os.path.join(dir_copias(), _nombre(ahora))
    try:
        _copiar_db(origen_db, destino)
    except Exception:
        log.warning("no se pudo crear la copia de seguridad de %s", origen_db, exc_info=True)
        return None
    rotar(maximo)
    return destino


def copia_reciente(intervalo_horas=INTERVALO_HORAS, ahora=None):
    """True si ya existe una copia mas nueva que `intervalo_horas` (para no duplicar)."""
    copias = listar()
    if not copias:
        return False
    import time
    ref = ahora.timestamp() if ahora else time.time()
    return (ref - copias[0]["mtime"]) < intervalo_horas * 3600


def crear_copia_si_toca(origen_db, intervalo_horas=INTERVALO_HORAS, ahora=None, maximo=MAX_COPIAS):
    """Copia automatica del arranque: solo si no hay una reciente. Nunca lanza; un
    fallo de copia jamas debe impedir abrir el programa."""
    try:
        if copia_reciente(intervalo_horas, ahora):
            return None
        return crear_copia(origen_db, ahora=ahora, maximo=maximo)
    except Exception:
        log.warning("copia de seguridad automatica fallida", exc_info=True)
        return None


def exportar(origen_db, destino):
    """Guarda una copia en la ruta que elija el usuario (fuera de la carpeta de
    copias: un pen-drive, una carpeta de red...). Devuelve True si fue bien."""
    if not origen_db or not os.path.exists(origen_db):
        return False
    try:
        _copiar_db(origen_db, destino)
        return True
    except Exception:
        log.warning("no se pudo exportar la copia a %s", destino, exc_info=True)
        return False


def restaurar(ruta_copia, destino_db):
    """Restaura `ruta_copia` SOBRE la base actual. Antes, guarda la base ACTUAL
    como copia de seguridad (por si el usuario se arrepiente) y limpia los ficheros
    WAL/SHM que quedaran. Devuelve True si fue bien.

    IMPORTANTE: la conexion a la base debe estar CERRADA cuando se llama (lo hace
    la interfaz: cierra, restaura y vuelve a conectar). No lo comprueba aqui."""
    if not ruta_copia or not os.path.exists(ruta_copia):
        return False
    try:
        if os.path.exists(destino_db):
            seg = os.path.join(dir_copias(),
                               PREFIJO_RESTAURAR + datetime.now().strftime("%Y%m%d_%H%M%S") + SUFIJO)
            shutil.copy2(destino_db, seg)
        shutil.copy2(ruta_copia, destino_db)
        # una base restaurada por copia no tiene WAL pendiente: si quedaban de la
        # base anterior, hay que quitarlos o SQLite mezclaria datos de las dos.
        for ext in ("-wal", "-shm"):
            p = destino_db + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return True
    except Exception:
        log.warning("no se pudo restaurar la copia %s", ruta_copia, exc_info=True)
        return False


def texto_tamano(n_bytes):
    """Tamano legible (KB/MB) para mostrar en la lista de copias."""
    if n_bytes is None:
        return "?"
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.0f} KB"
    return f"{n_bytes / (1024 * 1024):.1f} MB"
