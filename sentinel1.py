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
continuidad con nubes, verdor con o sin estructura...). Las funciones de calculo
e interpretacion son PURAS (se prueban sin satelite). La sincronizacion usa Earth
Engine (COPERNICUS/S1_GRD) igual que el modulo optico.
"""

from datetime import datetime, timedelta

import almacen as DB

try:
    import ee
    _EE = True
except Exception:
    _EE = False


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

    partes = [f"Radar Sentinel-1 del {r_act.get('fecha')}: "
              f"VV {r_act.get('vv')} dB, VH {r_act.get('vh')} dB, RVI {rvi_act} "
              f"({_lectura_rvi(rvi_act)})."]

    d_rvi = None
    if r_prev and r_prev.get("rvi") is not None and rvi_act is not None:
        d_rvi = round(rvi_act - r_prev["rvi"], 3)

    ndvi_act = serie_optica[-1].get("ndvi") if serie_optica else None
    ndvi_prev = serie_optica[-2].get("ndvi") if serie_optica and len(serie_optica) > 1 else None
    d_ndvi = None if ndvi_act is None or ndvi_prev is None else round(ndvi_act - ndvi_prev, 3)

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

    if rvi_act is not None and ndvi_act is not None:
        if rvi_act >= 0.5 and ndvi_act >= 0.5:
            partes.append("Alta concordancia (RVI y NDVI altos): el diagnostico de vigor es ROBUSTO.")
        elif rvi_act < 0.35 and ndvi_act < 0.4:
            partes.append("RVI y NDVI bajos: poca vegetacion confirmada por ambos sensores.")

    if diag_optico and diag_optico.get("estado"):
        refuerza = concordancia in ("bajan juntos", "suben juntos", "continuidad")
        partes.append(f"Diagnostico optico actual: [{diag_optico['estado']}] "
                      f"{diag_optico.get('fase', '')}. El radar "
                      f"{'REFUERZA esa lectura' if refuerza else 'aporta un matiz adicional'}.")

    return {"disponible": True, "texto": " ".join(partes), "rvi": rvi_act,
            "d_rvi": d_rvi, "d_ndvi": d_ndvi, "concordancia": concordancia}


# =====================================================================
# 3. SINCRONIZACION CON EARTH ENGINE (COPERNICUS/S1_GRD)
# =====================================================================
def _rango_campana(campana):
    a0, a1 = [int(x) for x in campana.split("-")]
    return f"{a0}-09-01", f"{a1}-08-31"


def sincronizar_radar(nombre, campana, silencioso=True):
    """
    Descarga INCREMENTAL de Sentinel-1 (VV/VH) sobre la parcela y guarda VV, VH,
    RVI y CR por pasada. Devuelve (n_nuevos, mensaje). SOLO se llama desde el boton.
    """
    if not _EE:
        return (0, "earthengine-api no disponible")
    try:
        ficha = DB.ficha(nombre)
        if not ficha or not ficha.get("coordenadas"):
            return (0, "parcela sin geometria")

        geom = ee.Geometry.Polygon(ficha["coordenadas"])
        ini_camp, fin_camp = _rango_campana(campana)
        ultima = DB.ultima_fecha_radar(nombre, campana)
        existentes = {p["fecha"] for p in DB.radar(nombre, campana) if p.get("fecha")}
        try:
            inicio = ((datetime.strptime(ultima, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                      if ultima else ini_camp)
        except ValueError:
            inicio = ini_camp
        hoy = datetime.now().strftime("%Y-%m-%d")
        fin = min(fin_camp, hoy)
        if inicio > fin:
            return (0, "radar ya al dia")

        col = (ee.ImageCollection("COPERNICUS/S1_GRD")
               .filterBounds(geom).filterDate(inicio, fin)
               .filter(ee.Filter.eq("instrumentMode", "IW"))
               .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
               .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
               .select(["VV", "VH"])
               .sort("system:time_start", True))

        def feat(img):
            m = img.reduceRegion(ee.Reducer.mean(), geom, scale=10, bestEffort=True)
            return ee.Feature(None, {"fecha": img.date().format("yyyy-MM-dd"),
                                     "vv": m.get("VV"), "vh": m.get("VH"),
                                     "orbita": img.get("orbitProperties_pass")})

        data = col.map(feat).getInfo()["features"]
        nuevos = []
        for f in data:
            p = f["properties"]
            fecha = p.get("fecha")
            vv, vh = p.get("vv"), p.get("vh")
            if not fecha or fecha in existentes or vv is None or vh is None:
                continue
            existentes.add(fecha)          # evita duplicar si hay dos escenas el mismo dia
            nuevos.append({"fecha": fecha, "vv": round(vv, 2), "vh": round(vh, 2),
                           "rvi": rvi(vv, vh), "cr": cross_ratio_db(vv, vh),
                           "orbita": p.get("orbita")})

        if not nuevos:
            return (0, "sin pasadas de radar nuevas")
        DB.anadir_radar(nombre, campana, nuevos)
        return (len(nuevos), f"anadidas {len(nuevos)} pasadas de radar")
    except Exception as e:
        if not silencioso:
            raise
        return (0, f"error: {e}")
