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
        return dict(umbrales_de_fase(), fase="sin especie", lo=0.30, hi=0.80,
                    caida=False, caduco=False, densidad=None, tipo="sin marco")
    try:
        mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    except (TypeError, ValueError):          # fecha ausente o mal formada
        return dict(umbrales_de_fase(), fase="sin fecha", lo=0.30, hi=0.80, caida=False,
                    caduco=info["hoja"] == "caducifolio", densidad=None, tipo="sin marco")
    lo, hi, caida = info["mes"][mes]
    dens = densidad_arboles(marco_calle, marco_pie)
    nombre_tipo, factor = tipo_plantacion(especie, dens)
    lo2 = round(lo * (0.92 + 0.08 * factor), 2)
    hi2 = round(min(0.92, hi * factor), 2)
    caduco = info["hoja"] == "caducifolio"
    brota_tarde = bool(info.get("brota_tarde"))
    invierno_sin_hoja = caduco and (mes == 12 or mes <= 2 or (brota_tarde and mes == 3))
    # sin hoja no hay dosel que medir: el NDMI lee suelo y cubierta, no el arbol
    extra = {"ndmi_min": None} if invierno_sin_hoja else None
    return dict(umbrales_de_fase(extra), fase=_nombre_fase_lenoso(especie, mes),
                lo=lo2, hi=hi2, caida=bool(caida), caduco=caduco, brota_tarde=brota_tarde,
                invierno_sin_hoja=invierno_sin_hoja, densidad=dens,
                tipo=nombre_tipo, factor=factor)


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
        # en barbecho no hay cultivo: el NDMI mide el suelo, no vale como aviso
        return dict(umbrales_de_fase({"ndmi_min": None}), fase="barbecho",
                    lo=0.05, hi=0.30, caida=False, barbecho=True)
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
