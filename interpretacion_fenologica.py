# -*- coding: utf-8 -*-
"""
interpretacion_fenologica.py
============================

Sustituye a las funciones `estado_semaforo` e `interpretar_reglas` del panel,
corrigiendo los cuatro fallos detectados:

  1. No miraba la FECHA -> falsas alarmas en senescencia, siega, cosecha y
     parada invernal. Ahora se estima la FASE FENOLOGICA y los umbrales son
     por fase, no fijos de campana.
  2. Semaforo y frase se contradecian -> ahora hay un unico juicio.
  3. El % del NDMI se disparaba (-300 %) al cruzar el cero -> ahora se usa
     DELTA ABSOLUTO en indices que pueden ser negativos.
  4. El barbecho no estaba blindado -> ahora devuelve N.A. siempre.

Ademas incorpora DETECCION DE CUBIERTA VEGETAL en lenosos:
  el codigo calcula indicadores cuantitativos (senal de suelo vs copa) y la IA
  (ChatGPT) los interpreta con contexto agronomico.

Uso desde panel_gestion_parcelas.py:
    from interpretacion_fenologica import evaluar_parcela, texto_interpretacion
"""

import os
import json
from datetime import datetime

from contraste_indices import analizar_por_contraste, heterogeneidad
from bitacora import log

try:
    from openai import OpenAI
    _OPENAI = True
except Exception:
    _OPENAI = False

# Tiempo maximo de espera de la llamada a ChatGPT, en segundos.
# Sin esto el SDK espera su valor por defecto (600 s) y ademas reintenta, con lo
# que la interpretacion podia tardar decenas de minutos en aparecer. Al agotarse,
# se usa el respaldo por reglas, que es el comportamiento ya previsto cuando la IA
# no esta disponible (el texto que ve el usuario no cambia).
TIMEOUT_IA_S = 30.0


# =====================================================================
# 1. FENOLOGIA: fase estimada por cultivo y fecha
# =====================================================================
# Calendario para el hemisferio norte / clima mediterraneo continental.
# Cada fase: (mes_ini, mes_fin, nombre, ndvi_min, ndvi_max, caida_esperada)
#   caida_esperada=True -> una bajada fuerte del NDVI en esa fase es NORMAL.
FENOLOGIA = {
    "LENOSO": [
        (9, 11, "postcosecha / otono",        0.25, 0.75, False),
        (12, 2, "parada vegetativa invernal", 0.20, 0.70, False),
        (3, 4,  "brotacion",                  0.30, 0.80, False),
        (5, 6,  "floracion / cuajado",        0.35, 0.85, False),
        (7, 8,  "endurecimiento / verano",    0.30, 0.80, False),
    ],
    "EXTENSIVO_COSECHA_GRANO": [
        (9, 10, "presiembra / suelo desnudo", 0.05, 0.30, False),
        (11, 12, "nascencia / ahijado",       0.15, 0.55, False),
        (1, 2,  "ahijado / encanado",         0.30, 0.75, False),
        (3, 4,  "encanado / espigado",        0.50, 0.90, False),
        (5, 5,  "llenado de grano",           0.40, 0.90, False),
        (6, 6,  "maduracion / senescencia",   0.15, 0.70, True),
        (7, 8,  "rastrojo / postcosecha",     0.05, 0.30, True),
    ],
    "EXTENSIVO_SIEGA_VERDE": [
        (9, 10, "presiembra",                 0.05, 0.35, False),
        (11, 1, "implantacion",               0.20, 0.60, False),
        (2, 4,  "crecimiento / corte",        0.30, 0.85, True),   # cortes periodicos
        (5, 7,  "rebrote / cortes",           0.25, 0.85, True),
        (8, 8,  "fin de ciclo",               0.15, 0.60, True),
    ],
}

# Ajuste del rango segun modalidad del leñoso (marco de plantacion -> mas o menos copa)
AJUSTE_LENOSO = {
    "TRADICIONAL":    (-0.05, -0.15),   # menos cobertura: rango mas bajo
    "INTENSIVO":      (0.00, 0.00),
    "SUPERINTENSIVO": (0.10, 0.05),     # mas cobertura: rango mas alto
}


def fase_fenologica(tipo, subtipo, fecha_iso):
    """Devuelve (nombre_fase, ndvi_min, ndvi_max, caida_esperada)."""
    if tipo == "BARBECHO":
        return ("barbecho", 0.05, 0.30, False)

    try:
        mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    except (TypeError, ValueError):
        return ("sin fase", 0.30, 0.80, False)   # fecha ausente o mal formada
    clave = "LENOSO" if tipo == "LENOSO" else f"EXTENSIVO_{subtipo}"
    tabla = FENOLOGIA.get(clave, FENOLOGIA["LENOSO"])

    for m0, m1, nombre, lo, hi, caida in tabla:
        dentro = (m0 <= mes <= m1) if m0 <= m1 else (mes >= m0 or mes <= m1)  # tramos que cruzan enero
        if dentro:
            if tipo == "LENOSO":
                a_lo, a_hi = AJUSTE_LENOSO.get(subtipo, (0.0, 0.0))
                lo, hi = round(lo + a_lo, 2), round(hi + a_hi, 2)
            return (nombre, lo, hi, caida)
    return ("sin fase", 0.30, 0.80, False)


# =====================================================================
# 2. DELTAS: % en indices positivos, ABSOLUTO en los que cruzan cero
# =====================================================================
INDICES_ABSOLUTOS = {"NDMI"}     # va de -1 a +1: el % no tiene sentido cerca de 0


def delta(idx, actual, previo):
    """Devuelve (texto_legible, valor_delta, es_porcentaje)."""
    if actual is None:
        return ("sin dato", None, False)
    if previo in (None, 0):
        return ("primer dato", None, False)

    d = actual - previo
    if idx in INDICES_ABSOLUTOS or abs(previo) < 0.08:
        # delta absoluto (en puntos del indice)
        if abs(d) < 0.02:
            return (f"estable ({d:+.3f} pts)", d, False)
        verbo = "sube" if d > 0 else "baja"
        return (f"{verbo} {abs(d):.3f} pts", d, False)

    p = d / abs(previo) * 100.0
    if abs(p) < 2:
        return (f"estable ({p:+.1f} %)", p, True)
    verbo = "sube" if p > 0 else "baja"
    return (f"{verbo} {abs(p):.1f} %", p, True)


# =====================================================================
# 3. DETECCION DE CUBIERTA VEGETAL EN LENOSOS (indicadores cuantitativos)
# =====================================================================
def detectar_cubierta(tipo, subtipo, serie, fecha_iso):
    """
    En lenosos, separa la senal de la CUBIERTA/SUELO de la de la COPA.

    Indicadores usados (todos derivables de lo que ya se descarga):
      - brecha_suelo = NDVI - MSAVI. MSAVI corrige el efecto suelo: si hay hierba
        verde entre calles, el NDVI sube mucho mas que el MSAVI -> brecha alta.
      - desacople LAI: si el NDVI sube pero el LAI apenas se mueve, el verde nuevo
        NO esta en la copa (que es la que aporta area foliar), sino a ras de suelo.
      - estacionalidad: la cubierta espontanea crece de invierno a primavera y se
        agosta en mayo-junio; una subida de NDVI en esa ventana es sospechosa.

    Devuelve dict con los indicadores y una hipotesis preliminar (la IA la matiza).
    """
    if tipo != "LENOSO" or not serie or not fecha_iso:
        return None

    act = serie[-1]
    prev = serie[-2] if len(serie) > 1 else None
    try:
        mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    except (TypeError, ValueError):
        return None

    ndvi = act.get("ndvi")
    msavi = act.get("msavi")
    lai = act.get("lai")
    ndmi = act.get("ndmi")
    if ndvi is None:
        return None

    brecha = None if msavi is None else round(ndvi - msavi, 3)

    # desacople NDVI vs LAI respecto a la pasada anterior
    desacople = None
    if prev and prev.get("ndvi") and prev.get("lai") is not None and lai is not None:
        d_ndvi = ndvi - prev["ndvi"]
        d_lai = lai - prev["lai"]
        # NDVI sube claramente pero LAI casi no -> verde fuera de la copa
        if d_ndvi > 0.05 and d_lai < 0.15:
            desacople = round(d_ndvi - d_lai / 3.6, 3)   # 3.6 = pendiente LAI~EVI

    ventana_cubierta = mes in (12, 1, 2, 3, 4, 5)

    # hipotesis preliminar por reglas (la IA la interpreta y matiza)
    señales = 0
    if brecha is not None and brecha > 0.12:
        señales += 1
    if desacople is not None:
        señales += 1
    if ventana_cubierta:
        señales += 1
    if ndmi is not None and ndmi > 0.15 and (lai or 0) < 2.0:
        señales += 1     # humedad alta sin dosel denso -> verde a ras de suelo

    hipotesis = ("cubierta vegetal probable" if señales >= 3 else
                 "posible cubierta vegetal" if señales == 2 else
                 "sin indicios claros de cubierta")

    return {
        "brecha_suelo_ndvi_msavi": brecha,
        "desacople_ndvi_lai": desacople,
        "ventana_estacional_cubierta": ventana_cubierta,
        "mes": mes,
        "señales": señales,
        "hipotesis_preliminar": hipotesis,
        "nota": ("En lenosos el NDVI medio mezcla copa y suelo. La cubierta entre calles "
                 "eleva el NDVI sin aumentar el area foliar de la copa."),
    }


# =====================================================================
# 4. EVALUACION UNIFICADA (semaforo y frase salen del MISMO juicio)
# =====================================================================
def evaluar_parcela(tipo, subtipo, serie, fecha_iso=None, eventos_cerca=None, spec=None):
    """
    Devuelve un dict con el diagnostico completo. Semaforo y explicacion
    coherentes entre si, con fenologia y (en lenosos) cubierta vegetal.

    eventos_cerca: lista opcional [(dias, evento), ...] del cuaderno de campo.
    spec: dict opcional con el modelo por especie:
        {"especie": ..., "fecha_siembra": ..., "marco_calle": ..., "marco_pie": ...}
        Si se aporta, la fenologia se calcula por especie (cereal por dias desde
        siembra; leñoso por mes + marco). Si no, se usa el calendario por meses.
    """
    if tipo == "BARBECHO":
        return {"estado": "N.A.", "clave": "NA", "fase": "barbecho",
                "motivo": "Parcela en barbecho: no se evalua el vigor del cultivo.",
                "deltas": {}, "cubierta": None, "esperado": True}

    if not serie:
        return {"estado": "Sin dato", "clave": "Sin", "fase": "-",
                "motivo": "Sin pasadas validas de satelite.", "deltas": {},
                "cubierta": None, "esperado": False}

    act = serie[-1]
    prev = serie[-2] if len(serie) > 1 else None
    fecha = fecha_iso or act.get("fecha")

    # --- FENOLOGIA: por especie si hay spec; si no, calendario por meses ---
    # Excepcion: en extensivos SEGADOS EN VERDE (forraje) NO se usa la fenologia
    # del cereal de grano (espigado/llenado/senescencia): el cultivo se corta
    # varias veces, asi que se usa el calendario de SIEGA_VERDE, donde las caidas
    # son NORMALES. De lo contrario, un corte saldria como caida anomala.
    siega_verde = (tipo == "EXTENSIVO" and subtipo == "SIEGA_VERDE")
    fase_esp = None
    if spec and spec.get("especie") and not siega_verde:
        try:
            from fenologia_especies import fase_por_especie
            fase_esp = fase_por_especie(tipo, spec.get("especie"), fecha,
                                        fecha_siembra=spec.get("fecha_siembra"),
                                        marco_calle=spec.get("marco_calle"),
                                        marco_pie=spec.get("marco_pie"))
            fase = fase_esp["fase"]
            lo, hi, caida_ok = fase_esp["lo"], fase_esp["hi"], fase_esp["caida"]
        except Exception:
            fase_esp = None
    if fase_esp is None:
        fase, lo, hi, caida_ok = fase_fenologica(tipo, subtipo, fecha)

    # deltas de todos los indices
    deltas = {}
    for K in ("NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"):
        k = K.lower()
        if act.get(k) is not None:
            txt, val, es_pct = delta(K, act.get(k), (prev or {}).get(k))
            deltas[K] = {"valor": act[k], "texto": txt, "delta": val, "pct": es_pct}

    ndvi = act.get("ndvi")
    ndmi = act.get("ndmi")
    d_ndvi = None if not prev or prev.get("ndvi") is None or ndvi is None else ndvi - prev["ndvi"]

    # --- MITIGACION DEL EFECTO CUBIERTA POR CONTRASTE ENTRE INDICES ---
    # No se estima ninguna fraccion de copa. Se deja que los indices se delaten
    # entre si: si la cubierta domina la senal, el NDVI deja de ser fiable y el
    # juicio pasa a apoyarse en el MSAVI, que corrige el efecto suelo.
    contraste = analizar_por_contraste(tipo, subtipo, serie, fecha)
    copa = contraste
    ndvi_juicio = ndvi
    indice_juicio = "NDVI"
    if (tipo == "LENOSO" and contraste and
            "cubierta" in contraste.get("veredicto_cubierta", "")):
        msavi = act.get("msavi")
        if msavi is not None:
            ndvi_juicio = msavi
            indice_juicio = "MSAVI"
            if prev and prev.get("msavi") is not None:
                d_ndvi = msavi - prev["msavi"]

    # --- SIEGA EN VERDE: una caida drastica del NDVI en primavera = SEGADO ---
    # En forraje segado en verde, cuando en abril-mayo (plena primavera) los indices
    # se desploman de golpe, no es un problema sanitario: el cultivo se ha CORTADO.
    # Se marca como "Segado" para que quede claro y no salte como anomalia; el rebrote
    # volvera a subir los indices.
    segado = False
    if siega_verde and ndvi is not None:
        try:
            mes_act = datetime.strptime(fecha, "%Y-%m-%d").month
        except (TypeError, ValueError):
            mes_act = None
        prev_ndvi = prev.get("ndvi") if prev else None
        caida_drastica = ((d_ndvi is not None and d_ndvi < -0.15) or
                          (prev_ndvi and ndvi < 0.60 * prev_ndvi))
        if mes_act in (4, 5) and caida_drastica:
            segado = True

    # --- juicio unico ---
    esperado = False
    if ndvi is None:
        clave, estado, motivo = "Sin", "Sin dato", "Sin NDVI valido (nubosidad)."
    elif segado:
        clave, estado = "OK", "Segado"
        _mes_txt = {4: "abril", 5: "mayo"}.get(mes_act, "primavera")
        motivo = (f"Caida drastica del NDVI ({d_ndvi:+.3f}) en {_mes_txt}: el cultivo se ha "
                  "SEGADO en verde (corte de forraje). Es lo esperado en esta modalidad; "
                  "el rebrote volvera a elevar los indices en las proximas pasadas.")
        esperado = True
    elif caida_ok and d_ndvi is not None and d_ndvi < -0.10:
        # caida fuerte PERO propia de la fase: senescencia, siega, cosecha
        evento = ("senescencia y maduracion" if "senescencia" in fase or "madur" in fase else
                  "corte / siega" if "corte" in fase or "rebrote" in fase else
                  "cosecha / rastrojo" if "rastrojo" in fase else "cambio propio de la fase")
        clave, estado = "OK", "OK"
        motivo = (f"Caida marcada del NDVI ({d_ndvi:+.3f}) coherente con la fase de {fase}: "
                  f"se interpreta como {evento}, no como problema sanitario.")
        esperado = True
    elif ndvi_juicio < lo * 0.8:
        clave, estado = "Revisar", "Revisar"
        motivo = (f"{indice_juicio} {ndvi_juicio:.3f} muy por debajo del rango esperado "
                  f"para la fase de {fase} ({lo:.2f}-{hi:.2f}).")
    elif ndvi_juicio < lo:
        clave, estado = "Vigilar", "Vigilar"
        motivo = (f"{indice_juicio} {ndvi_juicio:.3f} algo por debajo del rango de la fase "
                  f"de {fase} ({lo:.2f}-{hi:.2f}).")
    elif d_ndvi is not None and d_ndvi < -0.10 and not caida_ok:
        clave, estado = "Revisar", "Revisar"
        motivo = (f"Caida brusca del NDVI ({d_ndvi:+.3f}) NO esperada en la fase de {fase}: "
                  f"posible estres, plaga o incidencia.")
    else:
        clave, estado = "OK", "OK"
        motivo = (f"{indice_juicio} {ndvi_juicio:.3f} dentro del rango esperado para la fase "
                  f"de {fase} ({lo:.2f}-{hi:.2f}).")

    # traza de como se ha llegado al juicio
    if indice_juicio == "MSAVI":
        motivo += (f" [El NDVI observado ({ndvi:.3f}) esta inflado por la cubierta; se juzga con "
                   f"MSAVI, robusto al suelo. Vigor de copa: {contraste.get('vigor_copa', '-')}.]")
    elif tipo == "EXTENSIVO" and contraste and contraste.get("situacion"):
        motivo += f" [Contraste de indices: {contraste['situacion']}.]"

    # --- LEÑOSO CADUCO EN INVIERNO: el arbol esta sin hoja ---
    # En viña, almendro o pistacho en parada invernal no hay hoja: el NDVI cae a
    # valores de suelo y eso es NORMAL. Cualquier verde es cubierta, no el cultivo.
    if fase_esp and fase_esp.get("invierno_sin_hoja"):
        if clave in ("Revisar", "Vigilar") and ndvi is not None and ndvi >= lo * 0.7:
            clave, estado, esperado = "OK", "OK", True
            motivo = (f"NDVI {ndvi:.3f} propio de la parada invernal sin hoja "
                      f"({lo:.2f}-{hi:.2f}).")
        motivo += (" [El arbol esta SIN HOJA: cualquier verde que se vea es cubierta o "
                   "hierba, no el cultivo. El NDVI no mide el arbol hasta la brotacion.]")

    # el estres hidrico ELEVA el nivel de alerta (ya no contradice al semaforo)
    if ndmi is not None and ndmi < 0 and not esperado:
        if clave == "OK":
            clave, estado = "Vigilar", "Vigilar"
            motivo += f" Ademas el NDMI es negativo ({ndmi:+.3f}): indicio de estres hidrico."
        elif clave == "Vigilar":
            clave, estado = "Revisar", "Revisar"
            motivo += f" El NDMI negativo ({ndmi:+.3f}) agrava el diagnostico."
        else:
            motivo += f" NDMI negativo ({ndmi:+.3f}): estres hidrico asociado."

    # --- EVENTOS DEL CUADERNO DE CAMPO ---
    # Una siega/cosecha/herbicida REGISTRADO por el usuario explica una caida brusca
    # y prevalece sobre la deteccion automatica: deja de ser alarma.
    evento_explica = False
    if eventos_cerca:
        try:
            from registro_parcela import explicacion_por_eventos
            esp_ev, txt_ev = explicacion_por_eventos(eventos_cerca, d_ndvi)
            if esp_ev:
                clave, estado, esperado = "OK", "OK", True
                motivo = txt_ev
                evento_explica = True
        except Exception:
            # importante: si esto falla, una siega/cosecha REGISTRADA deja de
            # explicar la caida del NDVI y saltaria como falsa alarma.
            log.warning("no se pudo aplicar la explicacion por eventos del cuaderno",
                        exc_info=True)

    cubierta = detectar_cubierta(tipo, subtipo, serie, fecha)
    hetero = heterogeneidad(serie)

    # si hay deterioro LOCALIZADO, se advierte de posible foco (biotico)
    if evento_explica or segado:
        pass   # el evento (o el corte de forraje) ya explica lo observado; no se solapan avisos
    elif hetero and hetero.get("patron") == "deterioro LOCALIZADO":
        motivo += (" [ATENCION: deterioro LOCALIZADO. La dispersion interna crece "
                   f"(std {hetero['d_std']:+.3f}) mientras la media cae: posible FOCO en la "
                   "parcela (hongo, plaga o rodal). Revisar el mapa para localizar la mancha.]")
        if clave == "OK" and not esperado:
            clave, estado = "Vigilar", "Vigilar"
    elif hetero and hetero.get("patron") == "deterioro GENERALIZADO":
        motivo += (" [Deterioro GENERALIZADO y homogeneo: apunta a causa general "
                   "(sequia, helada, senescencia), no a un foco localizado.]")

    return {"estado": estado, "clave": clave, "fase": fase, "rango_fase": (lo, hi),
            "motivo": motivo, "deltas": deltas, "cubierta": cubierta, "copa": copa,
            "heterogeneidad": hetero, "ndvi_juicio": ndvi_juicio,
            "esperado": esperado, "fecha": fecha}


# =====================================================================
# 5. TEXTO: IA (ChatGPT) con respaldo por reglas
# =====================================================================
SYSTEM_PROMPT = """Eres un ingeniero agronomo experto en teledeteccion con Sentinel-2.
Recibes el diagnostico de una parcela: fase fenologica estimada, rango de NDVI esperado
para esa fase, valores de indices y su variacion respecto a la pasada anterior, y —en
cultivos lenosos— indicadores de posible cubierta vegetal entre calles.

Reglas que debes respetar:
- No inventes valores que no se te hayan dado.
- Ten SIEMPRE en cuenta la fase fenologica: una caida del NDVI en senescencia, siega o
  cosecha es NORMAL y no debe alarmar; la misma caida fuera de esas fases si es sospechosa.
- En el NDMI razona en puntos absolutos, no en porcentaje (cruza el cero).
- Si hay indicadores de cubierta vegetal, explica que el NDVI medio mezcla la senal de la
  copa con la del suelo/cubierta, y valora si el verdor procede de la cubierta o de la copa,
  y si eso es beneficioso (suelo protegido) o competencia por agua segun la epoca.
- Si el patron es "deterioro LOCALIZADO" (la media cae y la dispersion interna crece),
  advierte de que puede haber un FOCO en la parcela (hongo, plaga o rodal) y recomienda
  inspeccionar el mapa y visitar esa zona. Si es "deterioro GENERALIZADO" (cae todo a la
  vez de forma homogenea), orienta hacia causa general (sequia, helada, senescencia).
  NUNCA afirmes que enfermedad concreta es: los indices no lo pueden saber.
- Escribe 4-7 frases, en castellano claro, y termina con UNA recomendacion practica.
"""


def contexto_aprendizaje(aprendizaje):
    """Resume las validaciones del agricultor como texto para guiar a ChatGPT.

    `aprendizaje` es una lista de dicts (de almacen.validaciones_recientes):
    fase, cultivo, estado_sistema, veredicto, estado_real, nota. Devuelve None si
    no hay nada aprovechable."""
    if not aprendizaje:
        return None
    lineas = []
    for v in aprendizaje:
        if not isinstance(v, dict):
            continue
        if v.get("veredicto") == "incorrecto" and v.get("estado_real"):
            linea = (f"- En fase '{v.get('fase','?')}' ({v.get('cultivo','')}) el sistema dijo "
                     f"'{v.get('estado_sistema','?')}' pero lo correcto era "
                     f"'{v.get('estado_real')}'.")
        elif v.get("veredicto") == "correcto":
            linea = (f"- En fase '{v.get('fase','?')}' ({v.get('cultivo','')}) el diagnostico "
                     f"'{v.get('estado_sistema','?')}' fue CONFIRMADO correcto.")
        else:
            continue
        if v.get("nota"):
            linea += f" Observacion del agricultor: {v['nota']}"
        lineas.append(linea)
    if not lineas:
        return None
    return ("Historial de validaciones del agricultor en esta explotacion (aprende de estas "
            "correcciones para afinar el diagnostico actual, sin contradecir los datos):\n"
            + "\n".join(lineas[:8]))


def ambito_parcela(cultivo, parcela):
    """Clave de aprendizaje acotada a UNA parcela: 'CULTIVO@Parcela'.

    Las validaciones guardadas con esta clave solo afectan a esa parcela (util
    cuando la finca es especial: suelo pobre, microclima...). Las guardadas con la
    clave del cultivo a secas siguen valiendo para todas sus parcelas, que es el
    comportamiento de siempre (y el de los registros antiguos, sin '@')."""
    return f"{cultivo}@{parcela}" if parcela else cultivo


def _ajuste_en_ambito(cultivo, fase, estado_sistema, validaciones):
    """
    APRENDE de campanas anteriores usando las validaciones del usuario.

    Si en el MISMO cultivo y la MISMA fase el sistema dijo `estado_sistema` y el
    usuario lo corrigio antes hacia otro estado, ajusta (>=2 correcciones coherentes)
    o al menos anota la prediccion. Asi las predicciones se afinan con el uso.

    Devuelve {} si no hay historial util; si no, un dict con:
      - 'corregido': estado al que ajustar (o None si solo se anota)
      - 'nota'     : explicacion para mostrar al usuario
      - 'votos'    : nº de correcciones coherentes
    """
    if not validaciones or not cultivo:
        return {}
    fase_l = (fase or "").lower()
    correcciones = {}      # estado_real -> conteo
    confirmaciones = 0
    for v in validaciones:
        if not isinstance(v, dict):
            continue
        if v.get("cultivo") != cultivo or (v.get("fase") or "").lower() != fase_l:
            continue
        if v.get("estado_sistema") != estado_sistema:
            continue
        if v.get("veredicto") == "incorrecto" and v.get("estado_real"):
            correcciones[v["estado_real"]] = correcciones.get(v["estado_real"], 0) + 1
        elif v.get("veredicto") == "correcto":
            confirmaciones += 1

    if not correcciones:
        if confirmaciones:
            return {"corregido": None, "votos": confirmaciones,
                    "nota": f"Validaste este diagnostico como correcto en {confirmaciones} "
                            f"pasada(s) similar(es) de campanas anteriores."}
        return {}

    real, n = max(correcciones.items(), key=lambda kv: kv[1])
    if n >= 2 and real != estado_sistema:
        return {"corregido": real, "votos": n,
                "nota": (f"Aprendizaje: en {n} pasadas similares de este cultivo y fase corregiste "
                         f"'{estado_sistema}' a '{real}'. Se ajusta la prediccion a '{real}'.")}
    return {"corregido": None, "votos": n,
            "nota": (f"En una pasada similar corregiste '{estado_sistema}' a '{real}'. Se tiene en "
                     "cuenta (aun sin suficiente historial para ajustar automaticamente).")}


def ajuste_por_validaciones(cultivo, fase, estado_sistema, validaciones, parcela=None):
    """APRENDE de las validaciones del usuario, con DOS ambitos:

      1. lo corregido SOLO para esta parcela ('CULTIVO@Parcela'), que MANDA, y
      2. lo corregido para todo el cultivo, que se usa como respaldo.

    Asi una finca especial (suelo pobre, microclima) puede tener su propio criterio
    sin arrastrar al resto, y si no tiene historial propio hereda el del cultivo.
    Sin `parcela` se comporta exactamente como antes."""
    if parcela:
        propio = _ajuste_en_ambito(ambito_parcela(cultivo, parcela), fase,
                                   estado_sistema, validaciones)
        if propio:
            propio["ambito"] = "parcela"
            propio["nota"] = "(solo esta parcela) " + propio.get("nota", "")
            return propio
    general = _ajuste_en_ambito(cultivo, fase, estado_sistema, validaciones)
    if general:
        general["ambito"] = "cultivo"
    return general


def observaciones_del_agricultor(cultivo, fase, validaciones, limite=3, parcela=None):
    """Devuelve lo que la PERSONA escribio al validar, para el MISMO cultivo y fase.

    El programa aprende de lo que se le dice: estas notas de texto se muestran tal
    cual en la interpretacion (funcione o no ChatGPT), y se reutilizan cuando vuelve
    a darse la misma situacion. Lista de dicts {fecha, veredicto, estado, nota},
    de la mas reciente a la mas antigua, sin repetir texto."""
    if not validaciones or not cultivo:
        return []
    fase_l = (fase or "").lower()
    # se aceptan las notas del cultivo y, si se indica parcela, tambien las suyas
    ambitos = {cultivo}
    if parcela:
        ambitos.add(ambito_parcela(cultivo, parcela))
    out, vistos = [], set()
    for v in validaciones:
        if not isinstance(v, dict):
            continue
        if v.get("cultivo") not in ambitos or (v.get("fase") or "").lower() != fase_l:
            continue
        nota = (v.get("nota") or "").strip()
        if not nota or nota in vistos:
            continue
        vistos.add(nota)
        estado = v.get("estado_real") if v.get("veredicto") == "incorrecto" else v.get("estado_sistema")
        out.append({"fecha": v.get("fecha"), "veredicto": v.get("veredicto"),
                    "estado": estado, "nota": nota})
        if len(out) >= limite:
            break
    return out


def texto_interpretacion(tipo, subtipo, serie, fecha_iso=None, modelo="gpt-4o-mini",
                         eventos_cerca=None, spec=None, aprendizaje=None):
    """Genera el texto. Usa ChatGPT si hay OPENAI_API_KEY; si no, respaldo por reglas.

    `aprendizaje`: validaciones pasadas del agricultor (almacen.validaciones_recientes)
    que se reinyectan como contexto para que la IA acierte mejor en el futuro."""
    diag = evaluar_parcela(tipo, subtipo, serie, fecha_iso, eventos_cerca=eventos_cerca, spec=spec)

    if diag["clave"] in ("NA", "Sin"):
        return diag["motivo"], diag

    if _OPENAI and os.environ.get("OPENAI_API_KEY"):
        try:
            payload = {
                "cultivo": {"tipo": tipo, "modalidad": subtipo},
                "fecha": diag["fecha"],
                "fase_fenologica": diag["fase"],
                "rango_ndvi_esperado_en_esta_fase": diag["rango_fase"],
                "estado_calculado": diag["estado"],
                "motivo_calculado": diag["motivo"],
                "indices": {k: {"valor": v["valor"], "variacion": v["texto"]}
                            for k, v in diag["deltas"].items()},
                "cubierta_vegetal": diag["cubierta"],
                "desmezclado_copa": diag.get("copa"),
                "heterogeneidad_intraparcela": diag.get("heterogeneidad"),
            }
            mensajes = [{"role": "system", "content": SYSTEM_PROMPT}]
            ctx = contexto_aprendizaje(aprendizaje)
            if ctx:
                mensajes.append({"role": "system", "content": ctx})
            mensajes.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
            client = OpenAI()
            r = client.chat.completions.create(
                model=modelo, messages=mensajes, temperature=0.3, max_tokens=420,
                timeout=TIMEOUT_IA_S)
            return r.choices[0].message.content.strip(), diag
        except Exception as e:
            return _texto_reglas(diag) + f"  (IA no disponible: {e})", diag

    return _texto_reglas(diag), diag


def _texto_reglas(diag):
    """Respaldo determinista, coherente con el semaforo."""
    idx = "; ".join(f"{k} {v['valor']:.3f} ({v['texto']})" for k, v in diag["deltas"].items())
    txt = f"[Fase: {diag['fase']}] {idx}. {diag['motivo']} Estado: {diag['estado']}."
    c = diag.get("cubierta")
    if c and c["señales"] >= 2:
        txt += (f" Cubierta vegetal: {c['hipotesis_preliminar']} "
                f"(brecha NDVI-MSAVI={c['brecha_suelo_ndvi_msavi']}, "
                f"{c['señales']}/4 senales).")
    return txt
