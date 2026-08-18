# -*- coding: utf-8 -*-
"""
fenologia_especies.py
=====================

Modelo fenologico por ESPECIE, mas fino que el calendario por meses:

  CEREALES DE INVIERNO (trigo, cebada, avena)
    La fase se calcula por DIAS DESDE LA SIEMBRA, no por el mes. Cada especie
    tiene un factor de ciclo: la cebada madura antes que el trigo, la avena
    despues. Asi, dos parcelas sembradas el mismo dia estan en fases distintas
    segun la especie.

  LEÑOSOS (olivo, viña, almendro, pistacho)
    La diferencia clave NO es la etiqueta, sino que el OLIVO es perennifolio y
    los otros tres son de hoja CADUCA. En invierno un caduco esta sin hoja: su
    NDVI cae a valores de suelo y eso es NORMAL. Ademas, el MARCO de plantacion
    (calle x pie) da la densidad -> el tipo (tradicional/intensivo/superintensivo)
    -> el techo de NDVI esperado (mas copa cubre mas suelo).

Todas las funciones son puras y no dependen de Tkinter ni de GEE.
"""

import math
from datetime import datetime


def _dias(f1, f2):
    d1 = datetime.strptime(f1, "%Y-%m-%d")
    d2 = datetime.strptime(f2, "%Y-%m-%d")
    return (d2 - d1).days


# =====================================================================
# CULTIVOS EXTENSIVOS
# =====================================================================
# Cada especie tiene su PROPIO calendario fenologico por DIAS DESDE LA SIEMBRA
# (no un unico patron escalado). Cada fase:
#   (das_min, das_max, nombre, ndvi_min, ndvi_max, caida_esperada[, umbrales])
# caida_esperada=True -> una bajada fuerte del NDVI en esa fase es NORMAL
# (senescencia, maduracion, cosecha), no una alarma.
#
# El septimo elemento es OPCIONAL (ver `umbrales_de_fase` mas abajo) y lleva los
# umbrales de los DEMAS indices para esa fase. De donde salen sus valores:
#   - QUE fase es critica y como se ordenan los cultivos entre si: bibliografia
#     (FAO-56, coeficiente de respuesta del rendimiento Ky). El maiz en floracion
#     es el mas sensible del grupo; los cereales de invierno sufren de encanado a
#     llenado; las leguminosas, en floracion y llenado de vaina.
#   - Los NUMEROS de NDMI: escalados a partir de que un dosel cerrado y bien
#     abastecido se mueve en 0.20-0.35 y por debajo de ~0.10 con dosel cerrado hay
#     deficit. SON UN PUNTO DE PARTIDA, no una verdad: el NDMI absoluto se mueve
#     con el sensor, la correccion atmosferica y la zona. Por eso existe
#     `calibracion_umbrales.py`, que los ajusta con las validaciones del usuario
#     SIN tocar estos valores.
#   - `ndmi_min: None` = en esta fase el NDMI no dice nada y no se evalua.
EXTENSIVO_ESPECIES = {
    # ---------------- cereales de invierno (siembra en otono) ----------------
    "TRIGO": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.35, False, {"ndmi_min": None}),
        (30, 95, "ahijado", 0.30, 0.65, False, {"ndmi_min": 0.0, "lai_min": 1.0}),
        (95, 140, "encanado", 0.55, 0.85, False, {"ndmi_min": 0.08, "lai_min": 2.5}),
        (140, 170, "espigado / floracion", 0.60, 0.92, False, {"ndmi_min": 0.12, "lai_min": 3.0, "critica": True}),
        (170, 205, "llenado de grano", 0.50, 0.88, False, {"ndmi_min": 0.08, "lai_min": 2.5, "critica": True}),
        (205, 240, "maduracion / senescencia", 0.20, 0.62, True, {"ndmi_min": None}),
        (240, 400, "rastrojo / cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "CEBADA": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 25, "nascencia", 0.12, 0.35, False, {"ndmi_min": None}),
        (25, 80, "ahijado", 0.30, 0.62, False, {"ndmi_min": 0.0, "lai_min": 1.0}),
        (80, 120, "encanado", 0.52, 0.82, False, {"ndmi_min": 0.08, "lai_min": 2.5}),
        (120, 150, "espigado / floracion", 0.58, 0.90, False, {"ndmi_min": 0.12, "lai_min": 3.0, "critica": True}),
        (150, 182, "llenado de grano", 0.45, 0.85, False, {"ndmi_min": 0.08, "lai_min": 2.5, "critica": True}),
        (182, 212, "maduracion / senescencia", 0.18, 0.58, True, {"ndmi_min": None}),
        (212, 400, "rastrojo / cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "AVENA": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.38, False, {"ndmi_min": None}),
        (30, 100, "ahijado", 0.32, 0.68, False, {"ndmi_min": 0.0, "lai_min": 1.0}),
        (100, 148, "encanado", 0.55, 0.88, False, {"ndmi_min": 0.08, "lai_min": 2.5}),
        (148, 180, "espigado / floracion", 0.60, 0.92, False, {"ndmi_min": 0.12, "lai_min": 3.0, "critica": True}),
        (180, 215, "llenado de grano", 0.50, 0.88, False, {"ndmi_min": 0.08, "lai_min": 2.5, "critica": True}),
        (215, 250, "maduracion / senescencia", 0.20, 0.64, True, {"ndmi_min": None}),
        (250, 400, "rastrojo / cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "CENTENO": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 28, "nascencia", 0.12, 0.35, False, {"ndmi_min": None}),
        (28, 90, "ahijado", 0.30, 0.66, False, {"ndmi_min": 0.0, "lai_min": 1.0}),
        (90, 130, "encanado", 0.55, 0.86, False, {"ndmi_min": 0.08, "lai_min": 2.5}),
        (130, 158, "espigado / floracion", 0.60, 0.90, False, {"ndmi_min": 0.12, "lai_min": 3.0, "critica": True}),
        (158, 195, "llenado de grano", 0.48, 0.86, False, {"ndmi_min": 0.08, "lai_min": 2.5, "critica": True}),
        (195, 228, "maduracion / senescencia", 0.20, 0.60, True, {"ndmi_min": None}),
        (228, 400, "rastrojo / cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "TRITICALE": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.36, False, {"ndmi_min": None}),
        (30, 98, "ahijado", 0.32, 0.66, False, {"ndmi_min": 0.0, "lai_min": 1.0}),
        (98, 145, "encanado", 0.56, 0.87, False, {"ndmi_min": 0.08, "lai_min": 2.5}),
        (145, 175, "espigado / floracion", 0.60, 0.92, False, {"ndmi_min": 0.12, "lai_min": 3.0, "critica": True}),
        (175, 210, "llenado de grano", 0.50, 0.88, False, {"ndmi_min": 0.08, "lai_min": 2.5, "critica": True}),
        (210, 245, "maduracion / senescencia", 0.20, 0.62, True, {"ndmi_min": None}),
        (245, 400, "rastrojo / cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    # ---------------- primavera / verano ----------------
    "MAIZ": {"grupo": "cereal de primavera", "siembra": "primavera", "fases": [
        (0, 15, "nascencia", 0.10, 0.30, False, {"ndmi_min": None}),
        (15, 55, "desarrollo vegetativo", 0.30, 0.78, False, {"ndmi_min": 0.1, "lai_min": 1.5}),
        (55, 80, "floracion (panoja/sedas)", 0.75, 0.92, False, {"ndmi_min": 0.22, "lai_min": 3.5, "critica": True}),
        (80, 120, "llenado de grano", 0.68, 0.90, False, {"ndmi_min": 0.18, "lai_min": 3.0, "critica": True}),
        (120, 150, "maduracion (dentado)", 0.35, 0.75, True, {"ndmi_min": None}),
        (150, 400, "seco / cosecha", 0.15, 0.45, True, {"ndmi_min": None})]},
    "SORGO": {"grupo": "cereal de primavera", "siembra": "primavera", "fases": [
        (0, 15, "nascencia", 0.10, 0.30, False, {"ndmi_min": None}),
        (15, 55, "desarrollo vegetativo", 0.30, 0.75, False, {"ndmi_min": 0.05, "lai_min": 1.5}),
        (55, 80, "floracion", 0.68, 0.90, False, {"ndmi_min": 0.12, "lai_min": 2.5, "critica": True}),
        (80, 115, "llenado de grano", 0.60, 0.88, False, {"ndmi_min": 0.08, "lai_min": 2.0}),
        (115, 145, "maduracion", 0.30, 0.70, True, {"ndmi_min": None}),
        (145, 400, "seco / cosecha", 0.15, 0.45, True, {"ndmi_min": None})]},
    "GIRASOL": {"grupo": "oleaginosa de primavera", "siembra": "primavera", "fases": [
        (0, 15, "emergencia", 0.10, 0.28, False, {"ndmi_min": None}),
        (15, 50, "desarrollo", 0.28, 0.72, False, {"ndmi_min": 0.05, "lai_min": 1.5}),
        (50, 70, "boton floral", 0.62, 0.85, False, {"ndmi_min": 0.1, "lai_min": 2.5}),
        (70, 92, "floracion", 0.68, 0.88, False, {"ndmi_min": 0.15, "lai_min": 3.0, "critica": True}),
        (92, 120, "llenado / madurez", 0.40, 0.80, True, {"ndmi_min": None}),
        (120, 400, "seco / cosecha", 0.12, 0.45, True, {"ndmi_min": None})]},
    "COLZA": {"grupo": "oleaginosa de invierno", "siembra": "otono", "fases": [
        (0, 30, "emergencia", 0.15, 0.40, False, {"ndmi_min": None}),
        (30, 120, "roseta (invierno)", 0.35, 0.70, False, {"ndmi_min": 0.02, "lai_min": 1.0}),
        (120, 160, "encanado", 0.55, 0.82, False, {"ndmi_min": 0.08, "lai_min": 2.0}),
        (160, 188, "floracion (flor amarilla)", 0.45, 0.78, False, {"ndmi_min": 0.12, "lai_min": 2.5, "critica": True}),
        (188, 230, "formacion de silicuas", 0.55, 0.85, False, {"ndmi_min": 0.1, "lai_min": 2.5, "critica": True}),
        (230, 262, "maduracion", 0.25, 0.60, True, {"ndmi_min": None}),
        (262, 400, "cosecha", 0.10, 0.35, True, {"ndmi_min": None})]},
    "GUISANTE": {"grupo": "leguminosa", "siembra": "otono/invierno", "fases": [
        (0, 20, "nascencia", 0.12, 0.35, False, {"ndmi_min": None}),
        (20, 70, "desarrollo", 0.30, 0.72, False, {"ndmi_min": 0.05, "lai_min": 1.5}),
        (70, 98, "floracion", 0.60, 0.85, False, {"ndmi_min": 0.15, "lai_min": 2.5, "critica": True}),
        (98, 132, "llenado de vaina", 0.50, 0.82, False, {"ndmi_min": 0.1, "lai_min": 2.0, "critica": True}),
        (132, 162, "maduracion", 0.20, 0.55, True, {"ndmi_min": None}),
        (162, 400, "cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "VEZA": {"grupo": "leguminosa", "siembra": "otono", "fases": [
        (0, 25, "nascencia", 0.12, 0.35, False, {"ndmi_min": None}),
        (25, 90, "desarrollo", 0.30, 0.75, False, {"ndmi_min": 0.05, "lai_min": 1.5}),
        (90, 125, "floracion", 0.55, 0.85, False, {"ndmi_min": 0.15, "lai_min": 2.5, "critica": True}),
        (125, 160, "llenado de vaina", 0.45, 0.80, False, {"ndmi_min": 0.1, "lai_min": 2.0, "critica": True}),
        (160, 195, "maduracion", 0.20, 0.55, True, {"ndmi_min": None}),
        (195, 400, "cosecha", 0.05, 0.30, True, {"ndmi_min": None})]},
    "REMOLACHA": {"grupo": "raiz de primavera", "siembra": "primavera", "fases": [
        (0, 25, "nascencia", 0.10, 0.35, False, {"ndmi_min": None}),
        (25, 70, "desarrollo foliar", 0.35, 0.78, False, {"ndmi_min": 0.1, "lai_min": 1.5}),
        (70, 110, "cierre de calle", 0.72, 0.92, False, {"ndmi_min": 0.2, "lai_min": 3.5}),
        (110, 185, "engorde de raiz", 0.70, 0.92, False, {"ndmi_min": 0.18, "lai_min": 3.5, "critica": True}),
        (185, 215, "madurez", 0.55, 0.85, False, {"ndmi_min": 0.1, "lai_min": 3.0}),
        (215, 400, "recoleccion", 0.25, 0.70, True, {"ndmi_min": None})]},
}

# alias por compatibilidad (el nombre antiguo apuntaba solo a cereales)
CEREAL_ESPECIES = EXTENSIVO_ESPECIES


# =====================================================================
# UMBRALES POR FASE DE LOS DEMAS INDICES (NDMI, LAI)
# =====================================================================
# El NDVI ya tiene su rango por especie Y fase, arriba. Los demas indices se
# juzgaban con una constante unica para todos los cultivos: `ndmi < 0` avisaba de
# estres hidrico lo mismo en un maiz en floracion que en un trigo en rastrojo.
#
# Cada fila de fase admite un SEPTIMO elemento OPCIONAL: un dict con umbrales
# propios. Las filas que no lo llevan se comportan EXACTAMENTE igual que antes,
# porque los valores por defecto son los que ya estaban escritos a pelo.
#
#   ndmi_min : suelo del NDMI por debajo del cual se avisa de falta de agua.
#              None = en esta fase el NDMI no dice nada y NO se evalua (nascencia,
#              donde manda el suelo; senescencia, donde secarse es lo normal).
#              Ausente = se usa DEFECTO_UMBRALES.
#   lai_min  : LAI que cabe esperar con el dosel de esta fase. Sirve para separar
#              "hay agua pero no hay cultivo" (el verde es cubierta o hierba).
#   critica  : True en la ventana en que la falta de agua se lleva el rendimiento
#              por delante (FAO-56). Hoy solo se usa para redactar; no cambia el
#              semaforo por si solo.
DEFECTO_UMBRALES = {"ndmi_min": 0.0, "lai_min": 2.0, "critica": False}


def umbrales_de_fase(extra=None):
    """Mezcla los umbrales propios de una fase con los valores por defecto.

    `extra` es el septimo elemento de la fila de fase (o None). Devolver siempre
    las tres claves permite a quien consume no tener que comprobar nada."""
    d = dict(DEFECTO_UMBRALES)
    if extra:
        d.update(extra)
    return d


def _fila_fase(fila):
    """Descompone una fila de fase, que puede tener 6 o 7 elementos."""
    return fila[0], fila[1], fila[2], fila[3], fila[4], fila[5], (fila[6] if len(fila) > 6 else None)


def fase_extensivo(especie, fecha_siembra, fecha_iso):
    """Fase, dias desde siembra y rango de NDVI esperado, usando el calendario
    PROPIO de cada cultivo extensivo. Incluye los umbrales de NDMI/LAI de la fase."""
    info = EXTENSIVO_ESPECIES.get(especie) or EXTENSIVO_ESPECIES["TRIGO"]
    fases = info["fases"]
    if not fecha_siembra:
        # sin fecha de siembra no se puede afinar: rango amplio de seguridad
        return dict(umbrales_de_fase(), fase="sin fecha de siembra", das=None,
                    lo=0.15, hi=0.90, caida=False, previo=False)
    try:
        das = _dias(fecha_siembra, fecha_iso)
    except (TypeError, ValueError):          # fecha de siembra o pasada mal formada
        return dict(umbrales_de_fase(), fase="sin fecha de siembra", das=None,
                    lo=0.15, hi=0.90, caida=False, previo=False)
    if das < 0:
        # antes de sembrar no hay cultivo: el NDMI mide el suelo desnudo
        return dict(umbrales_de_fase({"ndmi_min": None}), fase="presiembra", das=das,
                    lo=0.05, hi=0.20, caida=False, previo=True)
    for fila in fases:
        d0, d1, nombre, lo, hi, caida, extra = _fila_fase(fila)
        if d0 <= das < d1:
            return dict(umbrales_de_fase(extra), fase=nombre, das=das, lo=lo, hi=hi,
                        caida=caida, previo=False)
    d0, d1, nombre, lo, hi, caida, extra = _fila_fase(fases[-1])
    return dict(umbrales_de_fase(extra), fase=nombre, das=das, lo=lo, hi=hi,
                caida=caida, previo=False)


# nombre antiguo, se mantiene por compatibilidad
fase_cereal = fase_extensivo


# =====================================================================
# LEÑOSOS
# =====================================================================
# Para cada especie: tipo de hoja y rango de NDVI esperado por MES (a copa
# plena, antes de aplicar la densidad). (ndvi_min, ndvi_max, caida_esperada)
LENOSO_ESPECIES = {
    "OLIVO": {
        "hoja": "perennifolio",
        "mes": {1: (.35, .72, 0), 2: (.35, .72, 0), 3: (.40, .78, 0), 4: (.42, .80, 0),
                5: (.45, .82, 0), 6: (.45, .82, 0), 7: (.40, .78, 0), 8: (.40, .78, 0),
                9: (.40, .78, 0), 10: (.40, .78, 0), 11: (.38, .75, 0), 12: (.35, .72, 0)},
        # (umbral_arboles_ha, nombre_tipo, factor_techo)
        "dens": [(250, "tradicional", 0.82), (700, "intensivo", 1.0),
                 (1e9, "superintensivo (seto)", 1.12)],
    },
    "VIÑA": {
        "hoja": "caducifolio",
        "mes": {1: (.12, .26, 0), 2: (.12, .28, 0), 3: (.15, .35, 0), 4: (.28, .55, 0),
                5: (.38, .68, 0), 6: (.45, .75, 0), 7: (.48, .78, 0), 8: (.45, .75, 0),
                9: (.35, .65, 1), 10: (.25, .55, 1), 11: (.15, .35, 1), 12: (.12, .26, 0)},
        "dens": [(2000, "vaso tradicional", 0.85), (4000, "espaldera", 1.0),
                 (1e9, "alta densidad", 1.1)],
    },
    "ALMENDRO": {
        "hoja": "caducifolio",
        "mes": {1: (.12, .26, 0), 2: (.13, .30, 0), 3: (.28, .55, 0), 4: (.38, .68, 0),
                5: (.45, .78, 0), 6: (.48, .80, 0), 7: (.45, .78, 0), 8: (.42, .75, 0),
                9: (.38, .68, 1), 10: (.22, .48, 1), 11: (.15, .32, 1), 12: (.12, .26, 0)},
        "dens": [(300, "tradicional", 0.82), (650, "intensivo", 1.0),
                 (1e9, "superintensivo (seto)", 1.12)],
    },
    "PISTACHO": {
        "hoja": "caducifolio", "brota_tarde": True,
        "mes": {1: (.12, .25, 0), 2: (.12, .25, 0), 3: (.13, .28, 0), 4: (.18, .40, 0),
                5: (.38, .68, 0), 6: (.45, .76, 0), 7: (.45, .78, 0), 8: (.42, .75, 0),
                9: (.35, .65, 1), 10: (.28, .55, 1), 11: (.18, .38, 1), 12: (.12, .25, 0)},
        "dens": [(280, "tradicional", 0.85), (450, "intensivo", 1.0),
                 (1e9, "alta densidad", 1.1)],
    },
}


# =====================================================================
# LEÑOSOS: FASES FISIOLOGICAS Y UMBRALES POR REGIMEN HIDRICO
# =====================================================================
# El mes por si solo no sirve para colgar umbrales: "verano" no dice si el arbol
# esta engordando fruto o acumulando aceite. `FASES_LENOSO` traduce mes -> ventana
# FISIOLOGICA, que es la que decide.
#
# Y sobre todo: en lenosos el REGIMEN HIDRICO pesa mas que la especie. Un olivar
# de secano en julio esta en deficit POR DISENO -cierra estomas, el NDMI baja- y
# eso es lo normal. El mismo NDMI en un seto regado significa que ha fallado el
# riego. Mismo numero, significado opuesto. Por eso los umbrales van por
# (fase, regimen), no solo por fase.
#
# En SECANO no se ponen suelos absolutos de NDMI en la ventana seca: no funcionan.
# Un olivo de secano en agosto tiene el NDMI bajo y esta perfectamente. Ahi el
# valor es `None` (no se juzga) y lo que queda es la comparacion con la propia
# parcela en anos anteriores, que es otra cosa.
REGIMENES = ["REGADIO", "SECANO"]

FASES_LENOSO = {
    "OLIVO": {1: "parada invernal", 2: "parada invernal", 3: "brotacion",
              4: "brotacion", 5: "floracion / cuajado", 6: "endurecimiento de hueso",
              7: "endurecimiento de hueso", 8: "acumulacion de aceite",
              9: "acumulacion de aceite", 10: "acumulacion de aceite",
              11: "cosecha", 12: "postcosecha"},
    "VIÑA": {1: "parada (sin hoja)", 2: "parada (sin hoja)", 3: "brotacion",
             4: "crecimiento vegetativo", 5: "crecimiento vegetativo",
             6: "floracion / cuajado", 7: "envero", 8: "maduracion",
             9: "vendimia", 10: "postcosecha", 11: "caida de hoja",
             12: "parada (sin hoja)"},
    "ALMENDRO": {1: "parada (sin hoja)", 2: "floracion (sin hoja)", 3: "foliacion",
                 4: "crecimiento de fruto", 5: "crecimiento de fruto",
                 6: "endurecimiento de hueso", 7: "llenado de pepita",
                 8: "maduracion", 9: "cosecha", 10: "postcosecha",
                 11: "caida de hoja", 12: "parada (sin hoja)"},
    "PISTACHO": {1: "parada (sin hoja)", 2: "parada (sin hoja)", 3: "parada (sin hoja)",
                 4: "brotacion / floracion", 5: "crecimiento", 6: "crecimiento",
                 7: "llenado de pepita", 8: "llenado de pepita",
                 9: "maduracion / cosecha", 10: "postcosecha",
                 11: "caida de hoja", 12: "parada (sin hoja)"},
}

# Umbrales por (especie, fase, regimen). Claves:
#   msavi_min  vigor de copa minimo. ES EL PARAMETRO CENTRAL EN LEÑOSOS: el MSAVI
#              corrige el efecto del suelo, asi que mide la copa y no la calle.
#              Se escala con el factor de densidad del marco.
#   ndmi_min   suelo de agua. None = aqui no se juzga.
#   lai_min    estructura de dosel esperada.
#   critica    ventana en que la falta de agua se lleva la cosecha (o la del ano
#              siguiente, en postcosecha de olivo y almendro).
#   deficit_buscado  el deficit AQUI es intencionado (envero y maduracion de viña:
#              riego deficitario controlado para calidad). No se avisa de agua.
#   sin_hoja   el arbol no tiene hoja: ningun indice mide la copa.
_SIN_HOJA = {"msavi_min": None, "ndmi_min": None, "lai_min": None, "sin_hoja": True}
# Perdiendo hoja: el dosel baja A PROPOSITO, asi que no se juzga su vigor, pero el
# arbol todavia tiene hoja y no todo el verde es cubierta.
_CAIDA = {"msavi_min": None, "ndmi_min": None, "lai_min": None}

UMBRALES_LENOSO = {
    "OLIVO": {
        "parada invernal": {"REGADIO": {"msavi_min": 0.28, "ndmi_min": 0.10, "lai_min": 1.2},
                            "SECANO": {"msavi_min": 0.25, "ndmi_min": 0.05, "lai_min": 1.0}},
        "brotacion": {"REGADIO": {"msavi_min": 0.32, "ndmi_min": 0.12, "lai_min": 1.5},
                      "SECANO": {"msavi_min": 0.28, "ndmi_min": 0.06, "lai_min": 1.3}},
        "floracion / cuajado": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.15, "lai_min": 1.8, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": 0.05, "lai_min": 1.5, "critica": True}},
        "endurecimiento de hueso": {
            "REGADIO": {"msavi_min": 0.38, "ndmi_min": 0.18, "lai_min": 2.0, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": None, "lai_min": 1.5,
                       "critica": True, "deficit_buscado": True}},
        "acumulacion de aceite": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.15, "lai_min": 1.9},
            "SECANO": {"msavi_min": 0.28, "ndmi_min": None, "lai_min": 1.4,
                       "deficit_buscado": True}},
        "cosecha": {"REGADIO": {"msavi_min": 0.32, "ndmi_min": 0.12, "lai_min": 1.7},
                    "SECANO": {"msavi_min": 0.26, "ndmi_min": None, "lai_min": 1.3}},
        "postcosecha": {
            "REGADIO": {"msavi_min": 0.32, "ndmi_min": 0.12, "lai_min": 1.6, "critica": True},
            "SECANO": {"msavi_min": 0.26, "ndmi_min": 0.04, "lai_min": 1.2, "critica": True}},
    },
    "VIÑA": {
        "parada (sin hoja)": {"REGADIO": _SIN_HOJA, "SECANO": _SIN_HOJA},
        "caida de hoja": {"REGADIO": _CAIDA, "SECANO": _CAIDA},
        "brotacion": {"REGADIO": {"msavi_min": 0.20, "ndmi_min": 0.10, "lai_min": 0.8},
                      "SECANO": {"msavi_min": 0.18, "ndmi_min": 0.05, "lai_min": 0.7}},
        "crecimiento vegetativo": {
            "REGADIO": {"msavi_min": 0.30, "ndmi_min": 0.14, "lai_min": 1.4},
            "SECANO": {"msavi_min": 0.26, "ndmi_min": 0.06, "lai_min": 1.2}},
        "floracion / cuajado": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.16, "lai_min": 1.8, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": 0.06, "lai_min": 1.5, "critica": True}},
        "envero": {"REGADIO": {"msavi_min": 0.34, "ndmi_min": None, "lai_min": 1.8,
                               "deficit_buscado": True},
                   "SECANO": {"msavi_min": 0.28, "ndmi_min": None, "lai_min": 1.5,
                              "deficit_buscado": True}},
        "maduracion": {"REGADIO": {"msavi_min": 0.32, "ndmi_min": None, "lai_min": 1.7,
                                   "deficit_buscado": True},
                       "SECANO": {"msavi_min": 0.26, "ndmi_min": None, "lai_min": 1.4,
                                  "deficit_buscado": True}},
        "vendimia": {"REGADIO": {"msavi_min": 0.28, "ndmi_min": None, "lai_min": 1.5},
                     "SECANO": {"msavi_min": 0.24, "ndmi_min": None, "lai_min": 1.2}},
        "postcosecha": {"REGADIO": {"msavi_min": 0.24, "ndmi_min": 0.08, "lai_min": 1.2},
                        "SECANO": {"msavi_min": 0.20, "ndmi_min": None, "lai_min": 1.0}},
    },
    "ALMENDRO": {
        "parada (sin hoja)": {"REGADIO": _SIN_HOJA, "SECANO": _SIN_HOJA},
        "floracion (sin hoja)": {"REGADIO": _SIN_HOJA, "SECANO": _SIN_HOJA},
        "caida de hoja": {"REGADIO": _CAIDA, "SECANO": _CAIDA},
        "foliacion": {"REGADIO": {"msavi_min": 0.26, "ndmi_min": 0.12, "lai_min": 1.2},
                      "SECANO": {"msavi_min": 0.22, "ndmi_min": 0.06, "lai_min": 1.0}},
        "crecimiento de fruto": {
            "REGADIO": {"msavi_min": 0.34, "ndmi_min": 0.15, "lai_min": 1.8, "critica": True},
            "SECANO": {"msavi_min": 0.28, "ndmi_min": 0.05, "lai_min": 1.5, "critica": True}},
        "endurecimiento de hueso": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.18, "lai_min": 2.0, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": None, "lai_min": 1.6,
                       "critica": True, "deficit_buscado": True}},
        "llenado de pepita": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.18, "lai_min": 2.0, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": None, "lai_min": 1.6,
                       "critica": True, "deficit_buscado": True}},
        "maduracion": {"REGADIO": {"msavi_min": 0.32, "ndmi_min": 0.14, "lai_min": 1.8},
                       "SECANO": {"msavi_min": 0.26, "ndmi_min": None, "lai_min": 1.4}},
        "cosecha": {"REGADIO": {"msavi_min": 0.28, "ndmi_min": 0.12, "lai_min": 1.6},
                    "SECANO": {"msavi_min": 0.24, "ndmi_min": None, "lai_min": 1.2}},
        "postcosecha": {
            "REGADIO": {"msavi_min": 0.28, "ndmi_min": 0.12, "lai_min": 1.5, "critica": True},
            "SECANO": {"msavi_min": 0.24, "ndmi_min": 0.05, "lai_min": 1.2, "critica": True}},
    },
    "PISTACHO": {
        "parada (sin hoja)": {"REGADIO": _SIN_HOJA, "SECANO": _SIN_HOJA},
        "caida de hoja": {"REGADIO": _CAIDA, "SECANO": _CAIDA},
        "brotacion / floracion": {"REGADIO": {"msavi_min": 0.22, "ndmi_min": 0.10, "lai_min": 1.0},
                                  "SECANO": {"msavi_min": 0.20, "ndmi_min": 0.05, "lai_min": 0.9}},
        "crecimiento": {"REGADIO": {"msavi_min": 0.32, "ndmi_min": 0.14, "lai_min": 1.6},
                        "SECANO": {"msavi_min": 0.28, "ndmi_min": 0.05, "lai_min": 1.4}},
        "llenado de pepita": {
            "REGADIO": {"msavi_min": 0.36, "ndmi_min": 0.18, "lai_min": 2.0, "critica": True},
            "SECANO": {"msavi_min": 0.30, "ndmi_min": None, "lai_min": 1.6,
                       "critica": True, "deficit_buscado": True}},
        "maduracion / cosecha": {"REGADIO": {"msavi_min": 0.30, "ndmi_min": 0.14, "lai_min": 1.7},
                                 "SECANO": {"msavi_min": 0.26, "ndmi_min": None, "lai_min": 1.3}},
        "postcosecha": {
            "REGADIO": {"msavi_min": 0.28, "ndmi_min": 0.12, "lai_min": 1.5, "critica": True},
            "SECANO": {"msavi_min": 0.24, "ndmi_min": 0.05, "lai_min": 1.2, "critica": True}},
    },
}

# Meses en que la cubierta entre calles suele estar VIVA. Fuera de esa ventana,
# el verde que se vea entre lineas ya no se explica por la cubierta sembrada.
VENTANA_CUBIERTA = (12, 1, 2, 3, 4, 5)


def regimen_valido(regimen):
    """Normaliza el regimen hidrico. Lo que no se reconoce va a SECANO, que es el
    supuesto conservador: no avisa de falta de agua donde el deficit es normal."""
    r = (regimen or "").strip().upper()
    return r if r in REGIMENES else "SECANO"


def umbrales_lenoso(especie, fase, regimen, factor=1.0):
    """Umbrales de esa fase y regimen. Son valores DE COPA, no de parcela.

    El `msavi_min` de la tabla es el vigor minimo de la COPA: un dosel de olivo
    sano da MSAVI ~0.43, y por debajo de 0.30 en cuajado hay algo que mirar. Lo que
    mide el satelite en un olivar tradicional NO es eso: es la media de un pixel
    que es copa en un 20 % y suelo en el 80 % restante. Convertir de una escala a
    la otra es trabajo de `umbral_en_escala_parcela`, con la fraccion de copa.

    El `factor` de densidad ya NO se aplica al msavi_min: era un +-15 % sobre una
    magnitud que cambia por un factor de 2 o 3 entre un tradicional y un seto, y
    ademas de la forma equivocada (lo que cambia con la densidad no es el vigor de
    la copa, es cuanto pixel es copa). Se sigue aplicando al `lai_min`, que es una
    magnitud de dosel, y al techo de NDVI del mes."""
    base = dict(DEFECTO_UMBRALES)
    tabla = UMBRALES_LENOSO.get(especie, {}).get(fase, {})
    propios = tabla.get(regimen_valido(regimen))
    if propios:
        base.update(propios)
    if base.get("lai_min") is not None:
        base["lai_min"] = round(base["lai_min"] * factor, 2)
    base["regimen"] = regimen_valido(regimen)
    return base


# =====================================================================
# FRACCION DE COPA: de un umbral de COPA a un umbral de PARCELA
# =====================================================================
# Un pixel de Sentinel-2 son 10 m de lado. En un olivar tradicional a 10x10 ese
# pixel contiene UN arbol y el resto es calle: por mucho que la copa este perfecta,
# la media de la parcela no puede acercarse al MSAVI de una copa. Con reflectancias
# de bibliografia (copa NIR .32 / RED .06, suelo seco NIR .28 / RED .24) la media
# de la parcela sale asi:
#
#   tradicional 10x10 (fc 0.20)   MSAVI 0.11        umbral de copa 0.30
#   intensivo 6x4     (fc 0.30)   MSAVI 0.15
#   seto 4x1.5        (fc 0.40)   MSAVI 0.18
#
# Comparar 0.11 contra 0.30 hace saltar el aviso SIEMPRE en tradicional, este el
# arbol como este. Y lo que subiria ese 0.11 hacia 0.30 no es que el arbol mejore:
# es que haya hierba en la calle. Es decir, el umbral estaba midiendo la cubierta.
#
# La conversion correcta es de mezcla, no un porcentaje:
#     umbral_parcela = fc * umbral_copa + (1 - fc) * MSAVI_SUELO
#
# FRACCION DE COPA. Si la ficha trae el diametro de copa, se usa. Si no, se estima
# como una proporcion del marco, distinta por tipo de plantacion. Las proporciones
# salen de cuadrar los marcos tipicos con las coberturas de suelo publicadas
# (tradicional 15-25 %, intensivo 25-35 %, superintensivo 35-45 %):
#     tradicional 10x10 -> copa 5.0 m sobre marco 10 -> 0.50
#     intensivo   6x4   -> copa 3.0 m sobre marco  4 -> 0.76
#     seto        4x1.5 -> copa 1.75 m sobre marco 1.5 -> 1.17 (la fila se cierra)
# Sobre el marco MENOR de los dos, que es el que limita el crecimiento de la copa.
MSAVI_SUELO = 0.08          # suelo desnudo seco; el rango real es 0.05-0.12
NDVI_SUELO = 0.10           # el mismo suelo, en NDVI (0.08-0.14 segun humedad)
# Tope de lo que puede ser un FONDO medido. NDVI y MSAVI no pasan de 1 en ninguna
# escena real, ni sobre la hierba mas cerrada; un p10 por encima de esto no es una
# calle verde, es un dato corrupto, y se descarta en vez de creerselo.
SUELO_MAX = 1.0
FC_MAXIMA = 0.85            # ni el dosel mas cerrado tapa el 100 % del suelo
PROPORCION_COPA = {"TRADICIONAL": 0.50, "INTENSIVO": 0.76, "SUPERINTENSIVO": 1.17}


def fraccion_copa(especie, marco_calle, marco_pie, diametro_copa=None):
    """Fraccion del suelo que tapa la copa vista desde arriba (0-1), o None.

    None significa "no se sabe el marco": quien llama debe seguir juzgando en
    escala de copa, sin convertir, que es el comportamiento de siempre."""
    dens = densidad_arboles(marco_calle, marco_pie)
    if not dens:
        return None
    try:
        d = float(diametro_copa) if diametro_copa else 0.0
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0:
        sub = subtipo_canonico(especie, dens) or "TRADICIONAL"
        # `densidad_arboles` ya ha garantizado que los dos marcos son positivos
        d = PROPORCION_COPA.get(sub, 0.50) * min(float(marco_calle), float(marco_pie))
    area_copa = math.pi * (d / 2.0) ** 2
    return round(min(FC_MAXIMA, dens * area_copa / 10000.0), 3)


def texto_marco(especie, marco_calle, marco_pie, diametro_copa=None):
    """Resumen legible del marco: densidad, tipo y CUANTO SUELO TAPA LA COPA.

    Esa fraccion es la que traduce los umbrales de copa a la escala de la parcela,
    asi que conviene que se vea al teclear el marco y no quede escondida en el
    calculo. Se dice ademas si el diametro de copa esta medido o estimado, porque
    la diferencia entre las dos cosas es justo lo que este texto sirve para
    enseñar. Cadena vacia si el marco no da para nada."""
    dens = densidad_arboles(marco_calle, marco_pie)
    if not dens:
        return ""
    tipo, _factor = tipo_plantacion(especie or "OLIVO", dens)
    txt = f"= {dens} arboles/ha  ->  {tipo}"
    fc = fraccion_copa(especie or "OLIVO", marco_calle, marco_pie, diametro_copa)
    if fc is not None:
        origen = "copa medida" if diametro_copa else "copa estimada del marco"
        txt += f"  ·  la copa tapa el {fc * 100:.0f} % del suelo ({origen})"
    return txt


def umbral_en_escala_parcela(umbral_copa, fc, suelo=MSAVI_SUELO):
    """Pasa un umbral de COPA a la escala de la MEDIA de la parcela.

    Es la mezcla de un pixel: una parte de copa y el resto de suelo. Sin `fc` no
    hay conversion posible y se devuelve el umbral tal cual."""
    if umbral_copa is None:
        return None
    if fc is None:
        return umbral_copa
    return round(fc * umbral_copa + (1.0 - fc) * suelo, 3)


# El suelo no es una constante: un calizo seco y un suelo humedo o con costra
# biologica se llevan facilmente 0.03 de indice entre ellos, y eso entra ENTERO en
# la parte del pixel que no es copa. En un olivar tradicional eso son 4/5 partes
# del pixel, asi que el margen de error del umbral convertido es mayor cuanto
# menos copa hay. Se resta ese margen antes de avisar: por debajo del umbral pero
# dentro de lo que el desconocimiento del suelo explica, no hay nada que decir.
INCERTIDUMBRE_SUELO = 0.03
# ...pero si el suelo se MIDE en vez de suponerlo, ese error se reduce a la mitad:
# lo que queda es el ruido del propio percentil, no el desconocimiento.
INCERTIDUMBRE_SUELO_MEDIDO = 0.015
# MSAVI de un dosel de olivo sano y cerrado. Solo se usa para poder decir el rango
# ("0.10-0.19") cuando el juicio se hace en MSAVI; ningun estado depende de el.
MSAVI_COPA_PLENA = 0.45


def margen_mezcla(fc, medido=False):
    """Cuanto puede errar el umbral convertido por no saber como es el suelo."""
    if fc is None:
        return 0.0
    inc = INCERTIDUMBRE_SUELO_MEDIDO if medido else INCERTIDUMBRE_SUELO
    return round((1.0 - fc) * inc, 3)


def suelo_de_la_parcela(p10, por_defecto, umbral_copa=None):
    """El termino de suelo de la mezcla, MEDIDO en la propia parcela si se puede.

    En un lenoso el decil peor de la parcela (`p10`) es la calle: es el suelo de
    ESA finca en ESE dia, con su humedad, su costra y su cubierta, en vez de una
    constante de bibliografia. Si la calle esta verde, el p10 sube y el umbral de
    parcela sube con el, que es justo lo que debe pasar: con hierba entre lineas,
    un mismo MSAVI medio es menos prueba de que la copa este bien.

    Que el p10 salga MAS ALTO que el umbral de copa no es un error: es una calle
    con hierba alta, y entonces el umbral de parcela debe subir por encima del de
    copa. Es lo que hace que la cuenta salga bien sola: la media de la parcela y el
    umbral suben los dos con el fondo, y lo que queda comparandose es la copa
    contra el umbral de copa, sea cual sea el fondo.

    Lo que SI se descarta es un p10 que no puede ser un fondo: uno negativo (agua o
    sombra), uno fuera del rango fisico del indice, o algo que no es un numero. Un
    valor imposible -un 5.0 en una base con un registro corrupto- subiria el umbral
    por las nubes y la parcela avisaria siempre, que es tan inutil como no avisar
    nunca.

    Devuelve (valor, medido)."""
    if p10 is None:
        return por_defecto, False
    try:
        v = float(p10)
    except (TypeError, ValueError):
        return por_defecto, False
    if not (0.0 <= v <= SUELO_MAX):
        return por_defecto, False
    return round(v, 3), True


def _umbral_parcela_con_margen(umbral_copa, fc, suelo=MSAVI_SUELO, medido=False):
    """Umbral de parcela ya descontado el margen de la mezcla. Nunca negativo."""
    u = umbral_en_escala_parcela(umbral_copa, fc, suelo)
    if u is None or fc is None:
        return u
    return round(max(0.0, u - margen_mezcla(fc, medido)), 3)


def densidad_arboles(marco_calle, marco_pie):
    """arboles/ha a partir del marco (distancia entre calles x distancia entre pies).

    Un marco que no sea un numero POSITIVO devuelve None, es decir "no se sabe el
    marco", y todo lo que dependa de el se comporta como en una parcela sin marco
    declarado. No es una comprobacion de adorno: un marco negativo -un guion de mas
    al teclear- daba una fraccion de copa NEGATIVA, y con ella un umbral de
    practicamente cero. La parcela dejaba de avisar sin decir nada, que es la peor
    forma de fallar que tiene este programa."""
    try:
        calle, pie = float(marco_calle), float(marco_pie)
    except (TypeError, ValueError):
        return None
    if calle <= 0 or pie <= 0:
        return None
    return round(10000.0 / (calle * pie))


def tipo_plantacion(especie, densidad):
    """Devuelve (nombre_tipo, factor_techo) segun la densidad y la especie."""
    tabla = LENOSO_ESPECIES.get(especie, LENOSO_ESPECIES["OLIVO"])["dens"]
    if densidad is None:
        return ("sin marco", 1.0)
    for umbral, nombre, factor in tabla:
        if densidad < umbral:
            return (nombre, factor)
    return tabla[-1][1], tabla[-1][2]


# Nivel canonico de intensificacion, homogeneo entre especies. Sirve para casar
# con las claves de UMBRALES / AJUSTE_LENOSO del panel (que son TRADICIONAL /
# INTENSIVO / SUPERINTENSIVO), independientemente del nombre especifico que
# reciba cada especie ("espaldera", "seto", "alta densidad", ...).
_SUBTIPOS_CANON = ["TRADICIONAL", "INTENSIVO", "SUPERINTENSIVO"]


def subtipo_canonico(especie, densidad):
    """Devuelve TRADICIONAL / INTENSIVO / SUPERINTENSIVO segun la densidad."""
    tabla = LENOSO_ESPECIES.get(especie, LENOSO_ESPECIES["OLIVO"])["dens"]
    if densidad is None:
        return ""
    for i, (umbral, _nombre, _factor) in enumerate(tabla):
        if densidad < umbral:
            return _SUBTIPOS_CANON[min(i, len(_SUBTIPOS_CANON) - 1)]
    return _SUBTIPOS_CANON[-1]


def _nombre_fase_lenoso(esp, mes):
    """Ventana FISIOLOGICA de esa especie en ese mes.

    Antes era una cadena de if/elif con nombres genericos ("verano", "pleno
    desarrollo") que no servian para colgar umbrales: no distinguen engorde de
    fruto de acumulacion de aceite. Ahora cada especie declara su calendario en
    FASES_LENOSO, que es donde se ve y se corrige."""
    tabla = FASES_LENOSO.get(esp)
    if tabla:
        return tabla.get(mes, "sin fase")
    # especie sin calendario declarado: se cae al reparto generico de antes
    info = LENOSO_ESPECIES.get(esp, {})
    if info.get("hoja") == "perennifolio":
        return [None, "parada invernal", "parada invernal", "brotacion", "brotacion",
                "floracion / cuajado", "floracion / cuajado", "verano", "verano",
                "postcosecha", "postcosecha", "postcosecha", "parada invernal"][mes]
    brota = 4 if info.get("brota_tarde") else 3
    if mes == 12 or mes <= 2 or (info.get("brota_tarde") and mes == 3):
        return "parada (sin hoja)"
    if mes == brota:
        return "brotacion"
    if brota < mes <= 5:
        return "foliacion"
    if 6 <= mes <= 8:
        return "crecimiento"
    if mes in (9, 10):
        return "maduracion / cosecha"
    return "caida de hoja"


def fase_lenoso(especie, fecha_iso, marco_calle=None, marco_pie=None, regimen=None,
                p10_ndvi=None, p10_msavi=None, diametro_copa=None):
    """Devuelve dict con fase, rango de NDVI, densidad, tipo de plantacion y los
    umbrales de MSAVI/NDMI/LAI de esa fase y regimen hidrico.

    `p10_ndvi` y `p10_msavi` son el decil peor de la pasada, o sea la CALLE. Si se
    pasan, el termino de suelo de la conversion a escala de parcela se mide en la
    propia finca en vez de suponerse (ver `suelo_de_la_parcela`).

    `diametro_copa` es el diametro medio de copa en metros, si se conoce. Es el
    dato que de verdad fija cuanto suelo tapa el arbol; sin el se estima a partir
    del marco (ver `PROPORCION_COPA`), que es una aproximacion por tipo de
    plantacion y no distingue un olivar viejo de uno joven al mismo marco."""
    info = LENOSO_ESPECIES.get(especie)
    if not info:
        return dict(umbrales_de_fase(), fase="sin especie", lo=0.30, hi=0.80,
                    caida=False, caduco=False, densidad=None, tipo="sin marco",
                    regimen=regimen_valido(regimen))
    try:
        mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    except (TypeError, ValueError):          # fecha ausente o mal formada
        return dict(umbrales_de_fase(), fase="sin fecha", lo=0.30, hi=0.80, caida=False,
                    caduco=info["hoja"] == "caducifolio", densidad=None, tipo="sin marco",
                    regimen=regimen_valido(regimen))
    lo, hi, caida = info["mes"][mes]
    dens = densidad_arboles(marco_calle, marco_pie)
    nombre_tipo, factor = tipo_plantacion(especie, dens)
    fc = fraccion_copa(especie, marco_calle, marco_pie, diametro_copa)
    # EL RANGO DE NDVI TAMBIEN ES DE COPA, no de parcela. `LENOSO_ESPECIES[...]["mes"]`
    # dice "un olivo en julio esta entre 0.40 y 0.78", y eso es el DOSEL. Un olivar
    # tradicional a 12x12 mide 0.17 de media aunque el arbol este perfecto, porque
    # cuatro quintas partes del pixel son calle. Ese era el aviso falso: el rango se
    # escalaba por el factor de densidad (un +-15 %) cuando la diferencia real entre
    # un tradicional y un seto es de mas del doble. Se convierte con la misma mezcla
    # que el MSAVI, y con el mismo criterio: si no hay marco, no se convierte nada.
    suelo_ndvi, ndvi_medido = suelo_de_la_parcela(p10_ndvi, NDVI_SUELO, lo)
    lo2 = round(umbral_en_escala_parcela(lo, fc, suelo_ndvi), 2)
    hi2 = round(min(0.92, umbral_en_escala_parcela(hi, fc, suelo_ndvi)), 2)
    caduco = info["hoja"] == "caducifolio"
    brota_tarde = bool(info.get("brota_tarde"))
    invierno_sin_hoja = caduco and (mes == 12 or mes <= 2 or (brota_tarde and mes == 3))
    fase = _nombre_fase_lenoso(especie, mes)
    # umbrales de la fase Y del regimen, con la densidad del marco ya aplicada
    umb = umbrales_lenoso(especie, fase, regimen, factor)
    if invierno_sin_hoja:
        # sin hoja no hay dosel que medir: ningun indice habla del arbol
        umb.update({"ndmi_min": None, "msavi_min": None, "lai_min": None, "sin_hoja": True})
    suelo_msavi, msavi_medido = suelo_de_la_parcela(p10_msavi, MSAVI_SUELO,
                                                    umb.get("msavi_min"))
    return dict(umb, fase=fase, lo=lo2, hi=hi2, caida=bool(caida), caduco=caduco,
                brota_tarde=brota_tarde, invierno_sin_hoja=invierno_sin_hoja,
                densidad=dens, tipo=nombre_tipo, factor=factor,
                marco_calle=marco_calle, marco_pie=marco_pie,
                fraccion_copa=fc, copa_medida=bool(diametro_copa),
                suelo_ndvi=suelo_ndvi, suelo_msavi=suelo_msavi,
                suelo_medido=bool(ndvi_medido or msavi_medido),
                msavi_min_parcela=_umbral_parcela_con_margen(
                    umb.get("msavi_min"), fc, suelo_msavi, msavi_medido),
                msavi_max_parcela=umbral_en_escala_parcela(
                    MSAVI_COPA_PLENA, fc, suelo_msavi),
                ventana_cubierta=mes in VENTANA_CUBIERTA)


# =====================================================================
# ENTRADA UNIFICADA
# =====================================================================
def fase_por_especie(grupo, especie, fecha_iso, fecha_siembra=None,
                     marco_calle=None, marco_pie=None, regimen=None,
                     p10_ndvi=None, p10_msavi=None, diametro_copa=None):
    """
    Punto de entrada unico. `grupo` in {EXTENSIVO, LENOSO, BARBECHO}.
    Devuelve un dict homogeneo con al menos: fase, lo, hi, caida.
    """
    if grupo == "BARBECHO":
        # en barbecho no hay cultivo: el NDMI mide el suelo, no vale como aviso
        return dict(umbrales_de_fase({"ndmi_min": None}), fase="barbecho",
                    lo=0.05, hi=0.30, caida=False, barbecho=True)
    if grupo == "EXTENSIVO":
        d = fase_cereal(especie, fecha_siembra, fecha_iso)
        d["grupo"] = "EXTENSIVO"
        return d
    if grupo == "LENOSO":
        # los percentiles solo se usan aqui: en extensivos no hay calle que medir
        d = fase_lenoso(especie, fecha_iso, marco_calle, marco_pie, regimen,
                        p10_ndvi=p10_ndvi, p10_msavi=p10_msavi,
                        diametro_copa=diametro_copa)
        d["grupo"] = "LENOSO"
        return d
    return {"fase": "desconocido", "lo": 0.30, "hi": 0.80, "caida": False}


ESPECIES = {
    "EXTENSIVO": list(CEREAL_ESPECIES.keys()),
    "LENOSO": list(LENOSO_ESPECIES.keys()),
    "BARBECHO": [],
}
