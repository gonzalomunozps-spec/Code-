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
#   (das_min, das_max, nombre, ndvi_min, ndvi_max, caida_esperada)
# caida_esperada=True -> una bajada fuerte del NDVI en esa fase es NORMAL
# (senescencia, maduracion, cosecha), no una alarma.
EXTENSIVO_ESPECIES = {
    # ---------------- cereales de invierno (siembra en otono) ----------------
    "TRIGO": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.35, False),
        (30, 95, "ahijado", 0.30, 0.65, False),
        (95, 140, "encanado", 0.55, 0.85, False),
        (140, 170, "espigado / floracion", 0.60, 0.92, False),
        (170, 205, "llenado de grano", 0.50, 0.88, False),
        (205, 240, "maduracion / senescencia", 0.20, 0.62, True),
        (240, 400, "rastrojo / cosecha", 0.05, 0.30, True)]},
    "CEBADA": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 25, "nascencia", 0.12, 0.35, False),
        (25, 80, "ahijado", 0.30, 0.62, False),
        (80, 120, "encanado", 0.52, 0.82, False),
        (120, 150, "espigado / floracion", 0.58, 0.90, False),
        (150, 182, "llenado de grano", 0.45, 0.85, False),
        (182, 212, "maduracion / senescencia", 0.18, 0.58, True),
        (212, 400, "rastrojo / cosecha", 0.05, 0.30, True)]},
    "AVENA": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.38, False),
        (30, 100, "ahijado", 0.32, 0.68, False),
        (100, 148, "encanado", 0.55, 0.88, False),
        (148, 180, "espigado / floracion", 0.60, 0.92, False),
        (180, 215, "llenado de grano", 0.50, 0.88, False),
        (215, 250, "maduracion / senescencia", 0.20, 0.64, True),
        (250, 400, "rastrojo / cosecha", 0.05, 0.30, True)]},
    "CENTENO": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 28, "nascencia", 0.12, 0.35, False),
        (28, 90, "ahijado", 0.30, 0.66, False),
        (90, 130, "encanado", 0.55, 0.86, False),
        (130, 158, "espigado / floracion", 0.60, 0.90, False),
        (158, 195, "llenado de grano", 0.48, 0.86, False),
        (195, 228, "maduracion / senescencia", 0.20, 0.60, True),
        (228, 400, "rastrojo / cosecha", 0.05, 0.30, True)]},
    "TRITICALE": {"grupo": "cereal de invierno", "siembra": "otono", "fases": [
        (0, 30, "nascencia", 0.12, 0.36, False),
        (30, 98, "ahijado", 0.32, 0.66, False),
        (98, 145, "encanado", 0.56, 0.87, False),
        (145, 175, "espigado / floracion", 0.60, 0.92, False),
        (175, 210, "llenado de grano", 0.50, 0.88, False),
        (210, 245, "maduracion / senescencia", 0.20, 0.62, True),
        (245, 400, "rastrojo / cosecha", 0.05, 0.30, True)]},
    # ---------------- primavera / verano ----------------
    "MAIZ": {"grupo": "cereal de primavera", "siembra": "primavera", "fases": [
        (0, 15, "nascencia", 0.10, 0.30, False),
        (15, 55, "desarrollo vegetativo", 0.30, 0.78, False),
        (55, 80, "floracion (panoja/sedas)", 0.75, 0.92, False),
        (80, 120, "llenado de grano", 0.68, 0.90, False),
        (120, 150, "maduracion (dentado)", 0.35, 0.75, True),
        (150, 400, "seco / cosecha", 0.15, 0.45, True)]},
    "SORGO": {"grupo": "cereal de primavera", "siembra": "primavera", "fases": [
        (0, 15, "nascencia", 0.10, 0.30, False),
        (15, 55, "desarrollo vegetativo", 0.30, 0.75, False),
        (55, 80, "floracion", 0.68, 0.90, False),
        (80, 115, "llenado de grano", 0.60, 0.88, False),
        (115, 145, "maduracion", 0.30, 0.70, True),
        (145, 400, "seco / cosecha", 0.15, 0.45, True)]},
    "GIRASOL": {"grupo": "oleaginosa de primavera", "siembra": "primavera", "fases": [
        (0, 15, "emergencia", 0.10, 0.28, False),
        (15, 50, "desarrollo", 0.28, 0.72, False),
        (50, 70, "boton floral", 0.62, 0.85, False),
        (70, 92, "floracion", 0.68, 0.88, False),
        (92, 120, "llenado / madurez", 0.40, 0.80, True),
        (120, 400, "seco / cosecha", 0.12, 0.45, True)]},
    "COLZA": {"grupo": "oleaginosa de invierno", "siembra": "otono", "fases": [
        (0, 30, "emergencia", 0.15, 0.40, False),
        (30, 120, "roseta (invierno)", 0.35, 0.70, False),
        (120, 160, "encanado", 0.55, 0.82, False),
        (160, 188, "floracion (flor amarilla)", 0.45, 0.78, False),
        (188, 230, "formacion de silicuas", 0.55, 0.85, False),
        (230, 262, "maduracion", 0.25, 0.60, True),
        (262, 400, "cosecha", 0.10, 0.35, True)]},
    "GUISANTE": {"grupo": "leguminosa", "siembra": "otono/invierno", "fases": [
        (0, 20, "nascencia", 0.12, 0.35, False),
        (20, 70, "desarrollo", 0.30, 0.72, False),
        (70, 98, "floracion", 0.60, 0.85, False),
        (98, 132, "llenado de vaina", 0.50, 0.82, False),
        (132, 162, "maduracion", 0.20, 0.55, True),
        (162, 400, "cosecha", 0.05, 0.30, True)]},
    "VEZA": {"grupo": "leguminosa", "siembra": "otono", "fases": [
        (0, 25, "nascencia", 0.12, 0.35, False),
        (25, 90, "desarrollo", 0.30, 0.75, False),
        (90, 125, "floracion", 0.55, 0.85, False),
        (125, 160, "llenado de vaina", 0.45, 0.80, False),
        (160, 195, "maduracion", 0.20, 0.55, True),
        (195, 400, "cosecha", 0.05, 0.30, True)]},
    "REMOLACHA": {"grupo": "raiz de primavera", "siembra": "primavera", "fases": [
        (0, 25, "nascencia", 0.10, 0.35, False),
        (25, 70, "desarrollo foliar", 0.35, 0.78, False),
        (70, 110, "cierre de calle", 0.72, 0.92, False),
        (110, 185, "engorde de raiz", 0.70, 0.92, False),
        (185, 215, "madurez", 0.55, 0.85, False),
        (215, 400, "recoleccion", 0.25, 0.70, True)]},
}

# alias por compatibilidad (el nombre antiguo apuntaba solo a cereales)
CEREAL_ESPECIES = EXTENSIVO_ESPECIES


def fase_extensivo(especie, fecha_siembra, fecha_iso):
    """Fase, dias desde siembra y rango de NDVI esperado, usando el calendario
    PROPIO de cada cultivo extensivo."""
    info = EXTENSIVO_ESPECIES.get(especie) or EXTENSIVO_ESPECIES["TRIGO"]
    fases = info["fases"]
    if not fecha_siembra:
        # sin fecha de siembra no se puede afinar: rango amplio de seguridad
        return {"fase": "sin fecha de siembra", "das": None,
                "lo": 0.15, "hi": 0.90, "caida": False, "previo": False}
    try:
        das = _dias(fecha_siembra, fecha_iso)
    except (TypeError, ValueError):          # fecha de siembra o pasada mal formada
        return {"fase": "sin fecha de siembra", "das": None,
                "lo": 0.15, "hi": 0.90, "caida": False, "previo": False}
    if das < 0:
        return {"fase": "presiembra", "das": das, "lo": 0.05, "hi": 0.20,
                "caida": False, "previo": True}
    for d0, d1, nombre, lo, hi, caida in fases:
        if d0 <= das < d1:
            return {"fase": nombre, "das": das, "lo": lo, "hi": hi,
                    "caida": caida, "previo": False}
    ult = fases[-1]
    return {"fase": ult[2], "das": das, "lo": ult[3], "hi": ult[4],
            "caida": ult[5], "previo": False}


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


def densidad_arboles(marco_calle, marco_pie):
    """arboles/ha a partir del marco (distancia entre calles x distancia entre pies)."""
    if not marco_calle or not marco_pie:
        return None
    return round(10000.0 / (marco_calle * marco_pie))


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
    info = LENOSO_ESPECIES[esp]
    if info["hoja"] == "perennifolio":
        return [None, "parada invernal", "parada invernal", "brotacion", "brotacion",
                "floracion", "floracion", "verano", "verano", "postcosecha",
                "postcosecha", "postcosecha", "parada invernal"][mes]
    brota = 4 if info.get("brota_tarde") else 3
    if mes == 12 or mes <= 2 or (info.get("brota_tarde") and mes == 3):
        return "parada (sin hoja)"
    if mes == brota:
        return "brotacion"
    if brota < mes <= 5:
        return "foliacion / desarrollo"
    if 6 <= mes <= 8:
        return "pleno desarrollo"
    if mes in (9, 10):
        return "maduracion / cosecha"
    return "caida de hoja"


def fase_lenoso(especie, fecha_iso, marco_calle=None, marco_pie=None):
    """Devuelve dict con fase, rango de NDVI, densidad y tipo de plantacion."""
    info = LENOSO_ESPECIES.get(especie)
    if not info:
        return {"fase": "sin especie", "lo": 0.30, "hi": 0.80, "caida": False,
                "caduco": False, "densidad": None, "tipo": "sin marco"}
    try:
        mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    except (TypeError, ValueError):          # fecha ausente o mal formada
        return {"fase": "sin fecha", "lo": 0.30, "hi": 0.80, "caida": False,
                "caduco": info["hoja"] == "caducifolio", "densidad": None, "tipo": "sin marco"}
    lo, hi, caida = info["mes"][mes]
    dens = densidad_arboles(marco_calle, marco_pie)
    nombre_tipo, factor = tipo_plantacion(especie, dens)
    lo2 = round(lo * (0.92 + 0.08 * factor), 2)
    hi2 = round(min(0.92, hi * factor), 2)
    caduco = info["hoja"] == "caducifolio"
    brota_tarde = bool(info.get("brota_tarde"))
    invierno_sin_hoja = caduco and (mes == 12 or mes <= 2 or (brota_tarde and mes == 3))
    return {"fase": _nombre_fase_lenoso(especie, mes), "lo": lo2, "hi": hi2,
            "caida": bool(caida), "caduco": caduco, "brota_tarde": brota_tarde,
            "invierno_sin_hoja": invierno_sin_hoja, "densidad": dens,
            "tipo": nombre_tipo, "factor": factor}


# =====================================================================
# ENTRADA UNIFICADA
# =====================================================================
def fase_por_especie(grupo, especie, fecha_iso, fecha_siembra=None,
                     marco_calle=None, marco_pie=None):
    """
    Punto de entrada unico. `grupo` in {EXTENSIVO, LENOSO, BARBECHO}.
    Devuelve un dict homogeneo con al menos: fase, lo, hi, caida.
    """
    if grupo == "BARBECHO":
        return {"fase": "barbecho", "lo": 0.05, "hi": 0.30, "caida": False,
                "barbecho": True}
    if grupo == "EXTENSIVO":
        d = fase_cereal(especie, fecha_siembra, fecha_iso)
        d["grupo"] = "EXTENSIVO"
        return d
    if grupo == "LENOSO":
        d = fase_lenoso(especie, fecha_iso, marco_calle, marco_pie)
        d["grupo"] = "LENOSO"
        return d
    return {"fase": "desconocido", "lo": 0.30, "hi": 0.80, "caida": False}


ESPECIES = {
    "EXTENSIVO": list(CEREAL_ESPECIES.keys()),
    "LENOSO": list(LENOSO_ESPECIES.keys()),
    "BARBECHO": [],
}
