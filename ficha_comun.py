# -*- coding: utf-8 -*-
"""
ficha_comun.py
==============

Constantes de presentacion y ayudantes SUELTOS que comparten `ui_ficha` y los
mixins en que se ha partido la ficha (`ficha_cuaderno`, `ficha_clima_gdd`,
`ficha_validacion`, `ficha_export`).

Viven aqui -y no en `ui_ficha`- para que los mixins puedan importarlos sin crear
un ciclo (`ui_ficha` importa los mixins, los mixins importarian `ui_ficha`). No
hay nada de logica de ficha: solo formato, etiquetas y utilidades de sistema.
"""

import os
import importlib.util

import gee_cliente
from gee_cliente import INDICES_ORDEN
from bitacora import log

_PIL = importlib.util.find_spec("PIL") is not None
_EE = gee_cliente.hay_ee()


def _abrir_archivo(ruta):
    """Abre un fichero con la aplicacion por defecto del sistema (multiplataforma)."""
    import platform
    import subprocess
    try:
        sistema = platform.system()
        if sistema == "Windows":
            os.startfile(ruta)                                   # noqa: solo en Windows
        elif sistema == "Darwin":
            subprocess.Popen(["open", ruta])
        else:
            subprocess.Popen(["xdg-open", ruta])
    except Exception:
        log.warning("no se pudo abrir %s con la aplicacion del sistema", ruta, exc_info=True)


# Constantes de presentacion (se definen UNA vez, no en cada llamada/redibujado).
_FMT_DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
_FMT_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
# color y etiqueta de cada tipo de evento del cuaderno para las lineas de la grafica
# Los eventos del cuaderno se marcan sobre la grafica como lineas verticales de
# apoyo. NO llevan color propio: siete colores mas, encima de hasta ocho series de
# datos, se comen el canal que sirve para saber que curva es cual. Van en tinta
# apagada y se distinguen por su ETIQUETA, que es lo que se lee de todas formas.
_NOMBRE_EVENTO = {"PRODUCTO": "Producto", "SIEGA": "Siega", "COSECHA": "Cosecha",
                  "RIEGO": "Riego", "LABOREO": "Laboreo", "SIEMBRA": "Siembra",
                  "OTRO": "Evento"}


# --- texto emergente de la grafica: valores de los indices y fiabilidad del dia ---
def tooltip_pasada(reg):
    """Texto multilinea con los indices de una pasada y su fiabilidad (cobertura
    valida de pixeles tras enmascarar nubes/sombra)."""
    if not reg:
        return ""
    lineas = [reg.get("fecha", "")]
    for K in INDICES_ORDEN:
        v = reg.get(K.lower())
        if v is not None:
            lineas.append(f"{K}: {v:.3f}")
    cob = reg.get("cobertura_valida")
    if cob is not None:
        pct = cob * 100 if cob <= 1 else cob
        etiqueta = "alta" if pct >= 95 else "media" if pct >= 85 else "baja"
        lineas.append(f"Fiabilidad: {pct:.0f}% ({etiqueta})")
    return "\n".join(lineas)


# (los colores de serie viven en PALETA_DATOS; se piden con `color_serie`)
# indices que se muestran por defecto en la grafica (los demas, a eleccion)
INDICES_GRAFICA_DEF = ["NDVI", "EVI", "SAVI", "NDMI"]

# Resoluciones de descarga del mapa: (etiqueta, metros por pixel)
# 10 m = nativo de Sentinel-2 en B2/B3/B4/B8. NDMI y MSAVI usan B11 (20 m nativos),
# asi que por debajo de 20 m esos dos indices se remuestrean, no ganan detalle real.
RESOLUCIONES = [
    ("5 m (sobremuestreo)", 5),
    ("10 m (nativo S2)", 10),
    ("20 m (rapido)", 20),
    ("60 m (vista rapida)", 60),
]
# MAX_PIXELES y dimensiones_para viven en gee_cliente.
