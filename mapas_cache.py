# -*- coding: utf-8 -*-
"""
mapas_cache.py
==============

Cache en disco de los PNG de mapas (indices opticos y radar).

Solo decide COMO SE LLAMA y DONDE VA cada imagen, y limpia las viejas. No sabe
descargar (de eso se encarga `gee_cliente`) ni pintar (de eso, el panel), asi que
no depende ni de Earth Engine ni de Tkinter y se puede probar suelto.

La clave de cache incluye parcela, indice/parametro, dia y resolucion: cada
combinacion es un fichero distinto, de modo que cambiar de resolucion o de dia no
pisa la imagen anterior.
"""

import os
import re

import rutas

# Carpeta de la cache, dentro del directorio de datos del usuario (ver rutas.py)
DIR_MAPAS = rutas.ruta("cache_mapas")

os.makedirs(DIR_MAPAS, exist_ok=True)

# Dias que se conservan los PNG. Se purgan al arrancar, en segundo plano. Son
# imagenes RECUPERABLES: se vuelven a descargar al pedirlas. 0 = no purgar nunca.
DIAS_CACHE = 30


def nombre_seguro(nombre):
    """Nombre de parcela seguro para usar como clave y en rutas de fichero:
    espacios a '_' y se descartan caracteres problematicos (/, \\, :, etc.)."""
    n = (nombre or "").strip().replace(" ", "_")
    n = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_\-]", "", n)
    return n or "parcela"


def ruta_cache_mapa(nombre, idx, iso, metros):
    """Ruta del PNG cacheado para (parcela, indice, dia, resolucion)."""
    return os.path.join(DIR_MAPAS, f"{nombre_seguro(nombre)}_{idx}_{iso}_{metros}m.png")


def ruta_cache_radar(nombre, param, iso, metros):
    """Ruta del PNG cacheado del mapa de radar (parcela, parametro, dia, resolucion)."""
    return os.path.join(DIR_MAPAS, f"{nombre_seguro(nombre)}_S1_{param}_{iso}_{metros}m.png")


def purgar(dias=None, ahora=None):
    """Borra los PNG de la cache con mas de `dias` dias. Devuelve cuantos borro.

    Solo toca ficheros .png (ver rutas.purgar_png_antiguos): nunca datos.
    """
    return rutas.purgar_png_antiguos(DIR_MAPAS,
                                     DIAS_CACHE if dias is None else dias,
                                     ahora)
