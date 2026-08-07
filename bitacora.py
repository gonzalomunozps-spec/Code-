# -*- coding: utf-8 -*-
"""
bitacora.py
===========

Registro de incidencias del programa, para poder DIAGNOSTICAR lo que hasta ahora
fallaba en silencio (migracion de datos, credenciales...).

Principios:
  - NO cambia nada de lo que ve el usuario: el registro va a un fichero
    (`parcelas.log`), nunca a la consola (propagate = False).
  - NO puede tumbar el programa: si el fichero no se puede escribir (carpeta de
    solo lectura, permisos), se usa un manejador nulo y todo sigue igual que
    antes, en silencio.
  - Nivel WARNING: solo se anota lo que de verdad es un problema.

Uso:
    from bitacora import log
    ...
    except Exception:
        log.warning("no se pudo importar el JSON de parcelas", exc_info=True)
"""

import logging

RUTA_LOG = "parcelas.log"

log = logging.getLogger("parcelas")


def _configurar():
    """Prepara el logger una sola vez, sin poder lanzar excepciones al importar."""
    if log.handlers:                       # ya configurado (import repetido)
        return
    log.setLevel(logging.WARNING)
    log.propagate = False                  # nunca escribe en la consola del usuario
    try:
        # Se comprueba que la carpeta admite escritura ANTES de instalar el
        # manejador; asi un entorno de solo lectura no provoca errores luego.
        with open(RUTA_LOG, "a", encoding="utf-8"):
            pass
        h = logging.FileHandler(RUTA_LOG, encoding="utf-8", delay=True)
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                                         datefmt="%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
    except Exception:
        log.addHandler(logging.NullHandler())   # sin registro, como hasta ahora


_configurar()
