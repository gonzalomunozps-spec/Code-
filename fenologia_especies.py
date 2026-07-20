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
# CEREALES DE INVIERNO
# =====================================================================
# Fase por dias desde siembra (referencia: trigo).
# (das_min, das_max, nombre, ndvi_min, ndvi_max, caida_esperada)
CEREAL_FASES = [
    (0,   30,  "nascencia",              0.12, 0.35, False),
    (30,  95,  "ahijado",                0.30, 0.65, False),
    (95,  140, "encanado",               0.55, 0.85, False),
    (140, 170, "espigado / floracion",   0.60, 0.92, False),
    (170, 200, "llenado de grano",       0.50, 0.88, False),
    (200, 235, "maduracion / senescencia", 0.20, 0.62, True),
    (235, 400, "rastrojo / cosecha",     0.05, 0.30, True),
]

# ciclo <1 -> madura antes;  techo -> multiplica el NDVI maximo esperado
CEREAL_ESPECIES = {
    "TRIGO":  {"ciclo": 1.00, "techo": 1.00, "nota": "ciclo de referencia"},
    "CEBADA": {"ciclo": 0.88, "techo": 0.96, "nota": "madura ~2 semanas antes que el trigo"},
    "AVENA":  {"ciclo": 1.08, "techo": 1.04, "nota": "ciclo mas largo y mas biomasa"},
}


def fase_cereal(especie, fecha_siembra, fecha_iso):
    """Devuelve dict con fase, dias desde siembra y rango de NDVI esperado."""
    e = CEREAL_ESPECIES.get(especie, CEREAL_ESPECIES["TRIGO"])
    if not fecha_siembra:
        # sin fecha de siembra no se puede afinar: rango amplio de seguridad
        return {"fase": "sin fecha de siembra", "das": None,
                "lo": 0.15, "hi": 0.85, "caida": False, "previo": False}
    das = _dias(fecha_siembra, fecha_iso)
    if das < 0:
        return {"fase": "presiembra", "das": das, "lo": 0.05, "hi": 0.20,
                "caida": False, "previo": True}
    eff = das / e["ciclo"]
    for d0, d1, nombre, lo, hi, caida in CEREAL_FASES:
        if d0 <= eff < d1:
            return {"fase": nombre, "das": das, "das_equiv": round(eff),
                    "lo": round(lo, 2), "hi": round(min(0.95, hi * e["techo"]), 2),
                    "caida": caida, "previo": False}
    return {"fase": "rastrojo / cosecha", "das": das, "lo": 0.05, "hi": 0.30,
            "caida": True, "previo": False}


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
    mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
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
