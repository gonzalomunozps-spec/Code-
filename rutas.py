# -*- coding: utf-8 -*-
"""
rutas.py
========

UN solo sitio donde se decide DONDE viven los datos del usuario (base de datos,
credenciales, bitacora, estado de sincronizacion y cache de mapas).

Antes cada fichero era una ruta relativa al directorio de trabajo, asi que
arrancar el programa desde otra carpeta creaba una base de datos vacia nueva sin
avisar y el usuario "perdia" sus parcelas. Ahora todo cuelga de un directorio
fijo del perfil del usuario, valga desde donde valga que se arranque.

Como se elige el directorio (por orden de prioridad):

  1. La variable de entorno GESTOR_PARCELAS_DIR, si esta definida. Sirve para
     forzarlo en pruebas o para llevar los datos a un disco concreto.
  2. El directorio estandar del sistema, si esta instalado `platformdirs`
     (Windows: %LOCALAPPDATA%; macOS: ~/Library/Application Support; Linux:
     ~/.local/share). Es una dependencia OPCIONAL.
  3. Si no esta, ~/.gestor_parcelas, que funciona en los tres sistemas.

Uso:
    import rutas
    RUTA_DB = rutas.ruta("parcelas.db")
"""

import os

VAR_ENTORNO = "GESTOR_PARCELAS_DIR"
NOMBRE_APP = "gestor_parcelas"
RESPALDO = "~/." + NOMBRE_APP          # si no hay platformdirs


def _base():
    """Directorio elegido (sin crearlo todavia)."""
    forzado = os.environ.get(VAR_ENTORNO)
    if forzado:
        return os.path.abspath(os.path.expanduser(forzado))
    try:
        from platformdirs import user_data_dir      # dependencia OPCIONAL
        return user_data_dir(NOMBRE_APP, appauthor=False)
    except Exception:
        return os.path.abspath(os.path.expanduser(RESPALDO))


def directorio_datos():
    """Directorio de datos del usuario, creandolo si hace falta.

    Si no se puede crear (disco lleno, permisos), se devuelve igualmente la ruta:
    que falle el fichero concreto, con su propio aviso, y no el arranque entero.
    """
    d = _base()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def ruta(nombre):
    """Ruta completa de un fichero de datos dentro del directorio del usuario."""
    return os.path.join(directorio_datos(), nombre)


def es_forzado():
    """True si el directorio viene impuesto por la variable de entorno."""
    return bool(os.environ.get(VAR_ENTORNO))
