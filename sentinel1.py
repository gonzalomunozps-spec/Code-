# -*- coding: utf-8 -*-
"""
sentinel1.py
============

Integracion de Sentinel-1 (RADAR / SAR) COMO COMPLEMENTO de Sentinel-2, activada
SOLO bajo demanda (boton "Sentinel-1" en la ficha de cada parcela).

Por que anadir radar:
  - El radar ATRAVIESA LAS NUBES: da lectura de la parcela cuando el optico
    (Sentinel-2) esta tapado.
  - Es sensible a la ESTRUCTURA y a la HUMEDAD (constante dielectrica), no al
    verdor. Asi corrobora o matiza lo que dice el optico.

Valores e indices caracteristicos que se toman (medias sobre la parcela):
  - VV (dB): retrodispersion co-polar (suelo + estructura).
  - VH (dB): retrodispersion cross-polar (volumen de vegetacion).
  - RVI    : Radar Vegetation Index = 4*VH / (VV+VH) en potencia lineal [0..1];
             sube con la biomasa/estructura del dosel.
  - CR (dB): cociente cross-polar VH-VV; sube con el desarrollo del cultivo.

La INTERPRETACION relaciona el radar con Sentinel-2 (concordancia de tendencias,
continuidad con nubes, verdor con o sin estructura...).

Este modulo es PURO: solo calculo e interpretacion, sin Earth Engine ni base de
datos, asi que se prueba entero sin satelite. La DESCARGA de las pasadas de radar
vive en gee_cliente.sincronizar_radar, que reutiliza estas mismas funciones.
"""

import math
from datetime import datetime


# =====================================================================
# 1. INDICES DE RADAR (puros)
# =====================================================================
def db_a_lineal(db):
    """dB -> potencia lineal. Sentinel-1 GRD entrega VV/VH en dB."""
    if db is None:
        return None
    return 10.0 ** (db / 10.0)


def rvi(vv_db, vh_db):
    """Radar Vegetation Index = 4*VH / (VV+VH) en lineal, acotado a [0,1]."""
    vv, vh = db_a_lineal(vv_db), db_a_lineal(vh_db)
    if vv is None or vh is None:
        return None
    denom = vv + vh
    if denom <= 0:
        return None
    return round(min(1.0, max(0.0, 4.0 * vh / denom)), 3)


def cross_ratio_db(vv_db, vh_db):
    """Cociente cross-polar VH-VV en dB (sube con la vegetacion)."""
    if vv_db is None or vh_db is None:
        return None
    return round(vh_db - vv_db, 2)


def _lectura_rvi(v):
    if v is None:
        return "sin RVI"
    if v >= 0.6:
        return "biomasa/estructura alta"
    if v >= 0.4:
        return "biomasa/estructura moderada"
    return "biomasa/estructura escasa (suelo dominante)"


# =====================================================================
# 1b. INCERTIDUMBRE del dato de radar (speckle, nº de looks, dispersion)
# =====================================================================
# El SAR tiene ruido speckle: la media sobre la parcela es tanto mas fiable cuantos
# mas pixeles (looks) se promedian y menos dispersion espacial hay. Ademas, comparar
# pasadas de ORBITAS distintas (ascendente/descendente) introduce variacion por el
# angulo de incidencia, no por el cultivo. Estas metricas permiten discernir la
# veracidad del valor y ponderar su aporte al diagnostico.
def error_estandar(std, n):
    """Error estandar de la media = std / sqrt(n). None si no procede."""
    if std is None or n is None or n <= 0:
        return None
    return round(std / math.sqrt(n), 3)


def rvi_incertidumbre(vv_db, vh_db, vv_err, vh_err):
    """RVI y su rango propagando la incertidumbre de VV y VH. El RVI SUBE con VH y
    BAJA con VV, asi que el minimo esta en (vv+e, vh-e) y el maximo en (vv-e, vh+e).
    Devuelve (rvi, rvi_lo, rvi_hi)."""
    base = rvi(vv_db, vh_db)
    if base is None:
        return (None, None, None)
    ve = vv_err or 0.0
    he = vh_err or 0.0
    lo = rvi(vv_db + ve, vh_db - he)
    hi = rvi(vv_db - ve, vh_db + he)
    vals = [x for x in (lo, hi) if x is not None]
    return (base, min(vals) if vals else None, max(vals) if vals else None)


def fiabilidad_radar(n_pixeles, vv_std, vh_std):
    """Fiabilidad cualitativa del valor de radar (heuristica): mas pixeles (looks) y
    menos dispersion espacial (dB) => mas fiable. Devuelve 'alta' | 'media' | 'baja'."""
    if n_pixeles is None:
        return "desconocida"
    ds = [s for s in (vv_std, vh_std) if s is not None]
    disp = sum(ds) / len(ds) if ds else None
    if n_pixeles >= 50 and (disp is None or disp < 1.5):
        return "alta"
    if n_pixeles >= 15 and (disp is None or disp < 3.0):
        return "media"
    return "baja"


# =====================================================================
# 2. INTERPRETACION CRUZADA S1 <-> S2 (pura)
# =====================================================================
def interpretar_radar(serie_optica, serie_radar, diag_optico=None):
    """
    Relaciona la ultima pasada de radar con la del optico (Sentinel-2).

    serie_optica: lista de pasadas opticas (con 'ndvi'...).
    serie_radar : lista de pasadas de radar (con 'vv','vh','rvi','cr').
    diag_optico : dict opcional del motor optico (evaluar_parcela): estado, fase.

    Devuelve {'disponible', 'texto', 'rvi', 'd_rvi', 'd_ndvi', 'concordancia'}.
    """
    if not serie_radar:
        return {"disponible": False,
                "texto": "Aun no hay pasadas de Sentinel-1. Pulsa el boton de radar para descargarlas."}

    r_act = serie_radar[-1]
    r_prev = serie_radar[-2] if len(serie_radar) > 1 else None
    rvi_act = r_act.get("rvi")
    fiab = r_act.get("fiabilidad", "desconocida")
    rango = ""
    if r_act.get("rvi_lo") is not None and r_act.get("rvi_hi") is not None:
        rango = f" [{r_act['rvi_lo']}-{r_act['rvi_hi']}]"

    partes = [f"Radar Sentinel-1 del {r_act.get('fecha')}: "
              f"VV {r_act.get('vv')} dB, VH {r_act.get('vh')} dB, RVI {rvi_act}{rango} "
              f"({_lectura_rvi(rvi_act)}). Fiabilidad del dato: {fiab.upper()} "
              f"({r_act.get('n_pixeles')} pixeles, dispersion VV/VH "
              f"{r_act.get('vv_std')}/{r_act.get('vh_std')} dB)."]

    # --- cautelas de incertidumbre que restan validez a la COMPARACION ---
    cautelas = []
    cambio_orbita = bool(r_prev and r_act.get("orbita") and r_prev.get("orbita")
                         and r_act["orbita"] != r_prev["orbita"])
    if cambio_orbita:
        cautelas.append("las dos ultimas pasadas de radar son de ORBITAS distintas "
                        f"({r_prev.get('orbita')} vs {r_act.get('orbita')}): parte del cambio "
                        "puede deberse al angulo de incidencia, no al cultivo")
    ndvi_act = serie_optica[-1].get("ndvi") if serie_optica else None
    f_opt = serie_optica[-1].get("fecha") if serie_optica else None
    desfase = None
    if f_opt and r_act.get("fecha"):
        try:
            desfase = abs((datetime.strptime(r_act["fecha"], "%Y-%m-%d")
                           - datetime.strptime(f_opt, "%Y-%m-%d")).days)
        except ValueError:
            desfase = None
    if desfase is not None and desfase > 6:
        cautelas.append(f"la pasada de radar y la optica distan {desfase} dias: "
                        "la comparacion directa pierde precision")
    if fiab == "baja":
        cautelas.append("pocos pixeles o mucha dispersion: el valor de radar es POCO fiable")

    d_rvi = None
    if r_prev and r_prev.get("rvi") is not None and rvi_act is not None:
        d_rvi = round(rvi_act - r_prev["rvi"], 3)
    ndvi_prev = serie_optica[-2].get("ndvi") if serie_optica and len(serie_optica) > 1 else None
    d_ndvi = None if ndvi_act is None or ndvi_prev is None else round(ndvi_act - ndvi_prev, 3)

    # una variacion de RVI dentro de su incertidumbre no es fiable como tendencia
    rvi_err = None
    if r_act.get("rvi_lo") is not None and r_act.get("rvi_hi") is not None:
        rvi_err = (r_act["rvi_hi"] - r_act["rvi_lo"]) / 2.0
    tendencia_fiable = (d_rvi is not None and (rvi_err is None or abs(d_rvi) > rvi_err)
                        and not cambio_orbita and fiab != "baja")

    concordancia = "no evaluable"
    if ndvi_act is None:
        concordancia = "continuidad"
        partes.append("El optico (Sentinel-2) no tiene NDVI valido (nubes) en la ultima fecha, "
                      "pero el radar SI ve la parcela: aporta CONTINUIDAD cuando hay nubes.")
    elif d_rvi is not None and d_ndvi is not None:
        if d_rvi < -0.03 and d_ndvi < -0.03:
            concordancia = "bajan juntos"
            partes.append("Radar y optico BAJAN a la vez: el descenso queda CONFIRMADO "
                          "(senescencia, corte, cosecha o estres), no es un artefacto de nube.")
        elif d_rvi > 0.03 and d_ndvi > 0.03:
            concordancia = "suben juntos"
            partes.append("Radar y optico SUBEN a la vez: crecimiento de biomasa y verdor CONFIRMADOS.")
        elif d_ndvi > 0.03 and d_rvi <= 0.0:
            concordancia = "verdor sin estructura"
            partes.append("El NDVI sube pero el radar NO acompana: verdor SIN estructura/biomasa "
                          "(posible cubierta entre calles o malas hierbas), coherente con el optico.")
        elif d_ndvi <= 0.0 and d_rvi > 0.03:
            concordancia = "estructura sin verdor"
            partes.append("El radar sube mientras el NDVI no: la parcela gana ESTRUCTURA/biomasa "
                          "aunque el verdor no cambie (p. ej. encanado o lignificacion).")
        else:
            concordancia = "coherentes"
            partes.append("Radar y optico coherentes, sin cambios marcados entre pasadas.")
        if concordancia in ("bajan juntos", "suben juntos") and not tendencia_fiable:
            partes.append("(La tendencia del radar cae dentro de su incertidumbre o cambia de orbita: "
                          "tomar la concordancia con cautela.)")

    if cautelas:
        partes.append("Incertidumbre: " + "; ".join(cautelas) + ".")

    # --- APORTE al diagnostico, ponderado por la fiabilidad del radar ---
    peso = {"alta": "con ALTA confianza", "media": "con confianza media",
            "baja": "con RESERVAS (baja fiabilidad del radar)"}.get(fiab, "con confianza indeterminada")
    if diag_optico and diag_optico.get("estado"):
        refuerza = tendencia_fiable and concordancia in ("bajan juntos", "suben juntos", "continuidad")
        verbo = "REFUERZA" if refuerza else ("aporta continuidad a" if concordancia == "continuidad"
                                             else "matiza")
        partes.append(f"Aporte al diagnostico optico [{diag_optico['estado']}] "
                      f"{diag_optico.get('fase', '')}: el radar lo {verbo} {peso}.")

    return {"disponible": True, "texto": " ".join(partes), "rvi": rvi_act,
            "rvi_lo": r_act.get("rvi_lo"), "rvi_hi": r_act.get("rvi_hi"),
            "fiabilidad": fiab, "d_rvi": d_rvi, "d_ndvi": d_ndvi,
            "tendencia_fiable": tendencia_fiable, "concordancia": concordancia,
            "cautelas": cautelas}
