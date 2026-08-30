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
from collections import namedtuple
from datetime import datetime

import fenologia_especies as FEN
from contraste_indices import (analizar_por_contraste, heterogeneidad,
                               separacion_copa_cubierta)
from bitacora import log

try:
    # OPCIONAL: ajusta los umbrales con las validaciones del usuario. Si se borra
    # el fichero se juzga con los valores de la tabla, que es lo de siempre.
    import calibracion_umbrales as _CAL
except Exception:
    _CAL = None

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
    """Devuelve (texto_legible, delta_pts, delta_pct).

    Exactamente UNO de los dos valores trae dato y el otro es None, para que el
    llamador nunca tenga que consultar una bandera y adivinar la unidad:

      - delta_pts: variacion en PUNTOS del indice. Se usa en los indices que
        cruzan el cero (NDMI) y cuando el valor previo es casi cero, donde el
        porcentaje se dispara y deja de significar nada.
      - delta_pct: variacion en PORCENTAJE, para el resto de casos.

    Si no hay dato actual o no hay referencia previa, ambos son None.
    """
    if actual is None:
        return ("sin dato", None, None)
    if previo in (None, 0):
        return ("primer dato", None, None)

    d = actual - previo
    if idx in INDICES_ABSOLUTOS or abs(previo) < 0.08:
        # variacion en puntos del indice
        if abs(d) < 0.02:
            return (f"estable ({d:+.3f} pts)", d, None)
        verbo = "sube" if d > 0 else "baja"
        return (f"{verbo} {abs(d):.3f} pts", d, None)

    p = d / abs(previo) * 100.0
    if abs(p) < 2:
        return (f"estable ({p:+.1f} %)", None, p)
    verbo = "sube" if p > 0 else "baja"
    return (f"{verbo} {abs(p):.1f} %", None, p)


# =====================================================================
# 3. DETECCION DE CUBIERTA VEGETAL EN LENOSOS (indicadores cuantitativos)
# =====================================================================
# Cuantas senales mira `detectar_cubierta`. Es el denominador que sale en el
# texto: hay que cambiarlo a la vez que las senales, y por eso viven juntas.
TOTAL_SENALES_CUBIERTA = 4


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
    marcas = (brecha is not None and brecha > 0.12,
              desacople is not None,
              ventana_cubierta,
              # humedad alta sin dosel denso -> verde a ras de suelo
              ndmi is not None and ndmi > 0.15 and (lai or 0) < 2.0)
    assert len(marcas) == TOTAL_SENALES_CUBIERTA
    señales = sum(1 for m in marcas if m)

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
# Los estados que el usuario puede elegir al corregir un diagnostico. Viven junto
# al motor que los produce: si aqui se anade un estado nuevo, el desplegable de la
# correccion tiene que ofrecerlo, y al reves. Estaban dentro de `FichaParcela`, y
# por eso el dialogo de correccion importaba la ficha entera para leer una lista.
ESTADOS_VALIDABLES = ["OK", "Vigilar", "Revisar", "Segado", "N.A."]

# ESTADO APARTE: el problema no esta en el cultivo, esta en lo que se ha declarado.
# Deliberadamente NO entra en ESTADOS_VALIDABLES: no es un juicio agronomico, asi
# que no se ofrece para validar ni alimenta el aprendizaje por validaciones. Ver
# `_regla_plausibilidad`.
ESTADO_DATOS = "Revisar datos"


def _resolver_fase(tipo, subtipo, spec, fecha, act, parcela):
    """Resuelve (fase, lo, hi, caida_ok, fase_esp, siega_verde) de la pasada.

    Por especie si hay spec (con posible override por grados-dia en extensivos); si
    no, por el calendario de meses. Excepcion: el forraje SEGADO EN VERDE no usa la
    fenologia del cereal de grano, porque el cultivo se corta varias veces.
    Extraido de `evaluar_parcela` SIN cambiar el comportamiento."""
    # Una PRADERA va SIEMPRE por el ciclo de cortes, la marquen como la marquen: es
    # una asociacion de especies perenne que se siega varias veces, y la fenologia
    # por dias desde la siembra de un cereal de grano no le aplica. El alta ya fuerza
    # la siega en verde; esto lo garantiza tambien para registros antiguos o tocados
    # a mano.
    es_pradera = (spec or {}).get("especie") == FEN.PRADERA
    siega_verde = (tipo == "EXTENSIVO" and (subtipo == "SIEGA_VERDE" or es_pradera))
    if es_pradera:
        # ...y el calendario por meses tambien tiene que ser el de la siega: si no,
        # una pradera marcada por error como grano caeria en «espigado» y «llenado
        # de grano», fases que en un forraje que se corta varias veces no existen.
        subtipo = "SIEGA_VERDE"
    fase_esp = None
    fase = lo = hi = caida_ok = None
    if spec and spec.get("especie") and not siega_verde:
        try:
            from fenologia_especies import fase_por_especie
            # El decil peor de la pasada es la CALLE: en lenosos sirve para medir el
            # suelo de esta finca en vez de suponerlo. En extensivos se ignora.
            fase_esp = fase_por_especie(tipo, spec.get("especie"), fecha,
                                        fecha_siembra=spec.get("fecha_siembra"),
                                        marco_calle=spec.get("marco_calle"),
                                        marco_pie=spec.get("marco_pie"),
                                        regimen=spec.get("regimen"),
                                        p10_ndvi=act.get("ndvi_p10"),
                                        p10_msavi=act.get("msavi_p10"),
                                        diametro_copa=spec.get("diametro_copa"))
            fase = fase_esp["fase"]
            lo, hi, caida_ok = fase_esp["lo"], fase_esp["hi"], fase_esp["caida"]
        except Exception:
            fase_esp = None
    # OVERRIDE por GRADOS-DIA (opcional, gated, extraible): con integral definida y
    # clima, en un EXTENSIVO la fase la manda el GDD, no el calendario. Sin el modulo
    # o sin datos, no hace nada y se sigue con el calendario.
    if fase_esp is not None and spec and spec.get("integrales_termicas"):
        try:
            import grados_dia as _GDD
            fo = _GDD.fase_override(tipo, spec.get("especie"), spec, fecha, parcela)
            if fo:
                fase_esp = fo
                fase, lo, hi, caida_ok = fo["fase"], fo["lo"], fo["hi"], fo["caida"]
        except Exception:
            log.debug("no se pudo aplicar el override por grados-dia", exc_info=True)
    if fase_esp is None:
        fase, lo, hi, caida_ok = fase_fenologica(tipo, subtipo, fecha)
    return fase, lo, hi, caida_ok, fase_esp, siega_verde


def _umbrales_calibrados(fase_esp, lo, hi, spec, fase, parcela):
    """(umbrales, lo, hi) de la fase, ya ajustados con las validaciones del usuario
    si hay modulo de calibracion y parcela. Sin modulo o sin parcela, quedan los de
    la tabla. Extraido de `evaluar_parcela` sin cambiar el comportamiento."""
    umbrales = FEN.umbrales_de_fase(fase_esp)
    if _CAL is not None and parcela:
        # La VARIEDAD afina por separado: se rige por las normas generales de su
        # especie (estos mismos umbrales de partida), pero solo cuentan para ella
        # las validaciones hechas con esa variedad. Sin variedad elegida, vacio, que
        # es "la especie a secas".
        umbrales = _CAL.ajustar_umbrales(dict(umbrales, lo=lo, hi=hi),
                                         (spec or {}).get("especie"), fase, parcela,
                                         variedad=(spec or {}).get("variedad", ""))
        lo, hi = umbrales.get("lo", lo), umbrales.get("hi", hi)
    return umbrales, lo, hi


def _calcular_deltas(act, prev):
    """Variacion de cada indice respecto a la pasada anterior. Puro: dos claves
    explicitas por indice (una trae dato, la otra None) para no mirar banderas."""
    deltas = {}
    for K in ("NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"):
        k = K.lower()
        if act.get(k) is not None:
            txt, d_pts, d_pct = delta(K, act.get(k), (prev or {}).get(k))
            deltas[K] = {"valor": act[k], "texto": txt,
                         "delta_pts": d_pts, "delta_pct": d_pct}
    return deltas


def _detectar_segado(siega_verde, ndvi, d_ndvi, prev, fecha):
    """(segado, mes_act) para forraje segado en verde: una caida drastica del NDVI
    en plena primavera (abril-mayo) es un CORTE de forraje, no un problema sanitario;
    el rebrote vuelve a subir los indices. Extraido sin cambiar el comportamiento.

    `prev_ndvi > 0` no es un test de verdad: con 0.0 la regla de la proporcion se
    saltaba entera, y con un NDVI previo NEGATIVO se invertia."""
    segado, mes_act = False, None
    if siega_verde and ndvi is not None:
        try:
            mes_act = datetime.strptime(fecha, "%Y-%m-%d").month
        except (TypeError, ValueError):
            mes_act = None
        prev_ndvi = prev.get("ndvi") if prev else None
        caida_drastica = ((d_ndvi is not None and d_ndvi < -0.15) or
                          (prev_ndvi is not None and prev_ndvi > 0
                           and ndvi < 0.60 * prev_ndvi))
        if mes_act in (4, 5) and caida_drastica:
            segado = True
    return segado, mes_act


# =====================================================================
# 4b. EL DIAGNOSTICO, COMO TUBERIA DE REGLAS
# =====================================================================
# `evaluar_parcela` era una funcion de 346 lineas y 57 nombres locales. Lo dificil
# no era la agronomia: era que once bloques seguidos mutaban las MISMAS tres
# variables (`clave`, `estado`, `motivo`), asi que para saber que hacia el septimo
# habia que haber leido los seis anteriores, y el ORDEN -que es significativo- solo
# existia como posicion de las lineas en el fichero.
#
# Ahora hay tres piezas:
#   1. `_Ctx`   : todo lo CALCULADO antes de juzgar (fase, umbrales, indice de
#                 juicio, deltas...). Es una tupla con nombres: de solo lectura, para
#                 que ninguna regla pueda cambiarle el suelo a la siguiente.
#   2. `_juicio_base` : la cadena de decision principal, que asigna el primer
#                 veredicto. Sigue siendo un if/elif exclusivo, como estaba.
#   3. `REGLAS` : las reglas que MATIZAN ese veredicto, cada una `f(ctx, diag)` que
#                 devuelve un `_Efecto` o None. El orden es una lista con nombre, no
#                 la posicion de las lineas.
#
# Lo que NO ha cambiado: ni un umbral, ni un texto, ni un estado, ni el orden. La
# prueba de eso es `pruebas_oro.py`: 3.493 entradas con su salida completa
# congelada, que pasa identica antes y despues.

_Ctx = namedtuple("_Ctx", [
    "tipo", "subtipo", "serie", "act", "prev", "fecha", "spec", "parcela",
    "eventos_cerca", "heterogeneidad_activa",
    "fase", "fase_esp", "lo", "hi", "caida_ok", "siega_verde", "umbrales",
    "ndvi", "ndmi", "d_ndvi", "deltas",
    "ndvi_juicio", "indice_juicio", "ndvi_limpio",
    "contraste", "copa", "separacion", "cubierta", "hetero",
    "segado", "mes_act",
])

# Que cambia una regla. `estado` a None = deja el veredicto como esta; `texto` se
# ANADE al motivo salvo que `reemplaza` sea True, y entonces lo sustituye entero;
# `esperado` a None = no lo toca.
_Efecto = namedtuple("_Efecto", ["estado", "texto", "esperado", "reemplaza"])
_Efecto.__new__.__defaults__ = (None, "", None, False)

# El veredicto en curso. `clave` y `estado` van juntos SALVO en el corte de forraje,
# que es "OK" de clave y "Segado" de estado; por eso son dos campos y no uno.
_Diag = namedtuple("_Diag", ["clave", "estado", "motivo", "esperado", "evento_explica"])


def _indice_de_juicio_lenoso(serie, act, prev, fase_esp, contraste,
                             ndvi_juicio, lo, hi, d_ndvi):
    """En un leñoso, decide CON QUE INDICE se juzga y CONTRA QUE LISTON.

    Reparto copa/cubierta con UNA sola lectura (ver contraste_indices). Usa los
    percentiles de la pasada cuando los hay: el p90 es mucho mejor proxy de la copa
    que la media, porque la media se come la calle.

    Si la cubierta domina, el NDVI esta inflado por la hierba y deja de servir: se
    juzga con el MSAVI. Pero entonces HAY QUE CAMBIAR TAMBIEN EL LISTON. Se comparaba
    el MSAVI contra el rango de NDVI de la fase, que es otra magnitud: un MSAVI de
    0.11 frente a un "0.16-0.23" de NDVI da "Revisar" por construccion. El rango pasa
    a ser el del MSAVI en la misma escala de parcela (ver fenologia_especies).

    Devuelve (separacion, copa, ndvi_juicio, indice_juicio, lo, hi, d_ndvi) ya
    resueltos; si no hay separacion posible, devuelve lo que entro."""
    separacion = separacion_copa_cubierta(serie, fase_esp, act)
    if not separacion:
        return separacion, contraste, ndvi_juicio, "NDVI", lo, hi, d_ndvi
    copa = dict(contraste or {}, **{"separacion": separacion})
    candidato = act.get("msavi")
    # sin ficha de especie no hay conversion de escala posible, y sin ella
    # no se puede juzgar en MSAVI: se sigue con el NDVI, como siempre
    lo_msavi = (fase_esp or {}).get("msavi_min_parcela")
    if not (separacion["cubierta_domina"] and candidato is not None and lo_msavi is not None):
        return separacion, copa, ndvi_juicio, "NDVI", lo, hi, d_ndvi
    hi_msavi = (fase_esp or {}).get("msavi_max_parcela") or max(lo_msavi, candidato)
    if prev and prev.get("msavi") is not None and act.get("msavi") is not None:
        d_ndvi = act["msavi"] - prev["msavi"]
    return separacion, copa, candidato, "MSAVI", lo_msavi, hi_msavi, d_ndvi


def _preparar_contexto(tipo, subtipo, serie, fecha_iso, eventos_cerca, spec, parcela,
                       heterogeneidad_activa, arbolado):
    """Todo lo que hay que CALCULAR antes de juzgar nada.

    Es el mismo bloque de cabecera que tenia `evaluar_parcela`, en el mismo orden y
    con las mismas llamadas; lo unico que cambia es que acaba en una tupla de solo
    lectura en vez de en treinta variables sueltas."""
    act = serie[-1]
    prev = serie[-2] if len(serie) > 1 else None
    fecha = fecha_iso or act.get("fecha")

    # --- FENOLOGIA: por especie (con posible override por GDD) o calendario ---
    # La siega en verde y el override termico se resuelven dentro del helper.
    fase, lo, hi, caida_ok, fase_esp, siega_verde = _resolver_fase(
        tipo, subtipo, spec, fecha, act, parcela)

    # --- UMBRALES DE LA FASE, ya calibrados con lo que haya validado el usuario ---
    # Se hace UNA vez y aqui arriba, para que el NDVI se juzgue con el mismo liston
    # que luego se explica.
    umbrales, lo, hi = _umbrales_calibrados(fase_esp, lo, hi, spec, fase, parcela)

    deltas = _calcular_deltas(act, prev)

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
    separacion = None

    # ENMASCARADO DE ARBOLADO (opcional, gated, extraible): en un EXTENSIVO marcado
    # como de arbolado disperso (dehesa/encinas), la media de NDVI esta inflada por
    # los arboles perennifolios, que estan verdes todo el ano. Se recalcula la media
    # SOLO del cultivo (pixeles no arbolados de la rejilla de esa fecha) y se juzga
    # con ELLA -no con la bruta-. Se toca UNICAMENTE el valor que se juzga; los
    # deltas y el NDMI se dejan igual (el arbol es estable: apenas mueve el delta, y
    # el NDMI no se guarda por pixel). Triple candado: hace falta el flag, el modulo
    # y una rejilla de esa fecha; si falta alguno, se juzga con la media de siempre.
    ndvi_limpio = None
    if arbolado and tipo == "EXTENSIVO" and ndvi is not None and parcela:
        try:
            import heterogeneidad_espacial as _HE
            nl = _HE.ndvi_cultivo_limpio(parcela, fecha)
            if nl is not None and abs(nl - ndvi) > 0.02:
                ndvi_limpio, ndvi_juicio = nl, nl
        except Exception:
            log.debug("no se pudo enmascarar el arbolado para el juicio", exc_info=True)
    if tipo == "LENOSO":
        (separacion, copa, ndvi_juicio, indice_juicio,
         lo, hi, d_ndvi) = _indice_de_juicio_lenoso(
            serie, act, prev, fase_esp, contraste, ndvi_juicio, lo, hi, d_ndvi)

    # --- SIEGA EN VERDE: una caida drastica del NDVI en primavera = SEGADO ---
    # En forraje segado en verde, un desplome en abril-mayo no es un problema: el
    # cultivo se ha CORTADO. Se marca "Segado" para que no salte como anomalia.
    segado, mes_act = _detectar_segado(siega_verde, ndvi, d_ndvi, prev, fecha)

    # Cubierta y heterogeneidad son DATO, no juicio: se calculan siempre (tambien
    # con el analisis de zonas apagado, que apaga el aviso pero no el dato) y las
    # reglas solo los leen.
    cubierta = detectar_cubierta(tipo, subtipo, serie, fecha)
    # UNA sola fuente de verdad sobre la cubierta. `detectar_cubierta` aporta sus
    # indicadores numericos, pero el VEREDICTO que se ensena es el mismo que ha
    # decidido con que indice se juzga: si no, la cabecera podia decir "cubierta
    # probable" mientras el juicio iba por la copa (pasaba en el 21 % de los casos).
    if separacion and cubierta:
        cubierta["hipotesis_preliminar"] = separacion["veredicto"]
        # OJO: `detectar_cubierta` cuenta sobre 4 y `separacion_copa_cubierta`
        # acumula hasta siete evidencias. Machacar la primera con la segunda hacia
        # que el texto dijera «5/4 senales» y que el liston de `>= 2` se aplicara a
        # una escala distinta de aquella para la que se ajusto. Se guardan aparte.
        cubierta["evidencias"] = len(separacion["evidencias_cubierta"])
        cubierta["confianza"] = separacion["confianza"]
        cubierta["copa_msavi"] = separacion["copa_msavi"]
    hetero = heterogeneidad(serie)

    return _Ctx(tipo=tipo, subtipo=subtipo, serie=serie, act=act, prev=prev, fecha=fecha,
                spec=spec, parcela=parcela, eventos_cerca=eventos_cerca,
                heterogeneidad_activa=heterogeneidad_activa,
                fase=fase, fase_esp=fase_esp, lo=lo, hi=hi, caida_ok=caida_ok,
                siega_verde=siega_verde, umbrales=umbrales,
                ndvi=ndvi, ndmi=ndmi, d_ndvi=d_ndvi, deltas=deltas,
                ndvi_juicio=ndvi_juicio, indice_juicio=indice_juicio,
                ndvi_limpio=ndvi_limpio, contraste=contraste, copa=copa,
                separacion=separacion, cubierta=cubierta, hetero=hetero,
                segado=segado, mes_act=mes_act)


def _juicio_base(ctx):
    """El veredicto de partida. Cadena EXCLUSIVA: manda la primera que se cumple.

    El orden es agronomico, no casual: sin NDVI no hay nada que juzgar; un corte de
    forraje o una caida propia de la fase EXPLICAN el desplome antes de que nadie lo
    llame anomalia; y solo despues se mira el nivel del indice y la caida brusca."""
    ndvi, ndvi_juicio, d_ndvi = ctx.ndvi, ctx.ndvi_juicio, ctx.d_ndvi
    lo, hi, fase = ctx.lo, ctx.hi, ctx.fase
    if ndvi is None:
        return _Diag("Sin", "Sin dato", "Sin NDVI valido (nubosidad).", False, False)
    if ctx.segado:
        _mes_txt = {4: "abril", 5: "mayo"}.get(ctx.mes_act, "primavera")
        return _Diag("OK", "Segado",
                     f"Caida drastica del NDVI ({d_ndvi:+.3f}) en {_mes_txt}: el cultivo se ha "
                     "SEGADO en verde (corte de forraje). Es lo esperado en esta modalidad; "
                     "el rebrote volvera a elevar los indices en las proximas pasadas.",
                     True, False)
    if ctx.caida_ok and d_ndvi is not None and d_ndvi < -0.10:
        # caida fuerte PERO propia de la fase: senescencia, siega, cosecha
        evento = ("senescencia y maduracion" if "senescencia" in fase or "madur" in fase else
                  "corte / siega" if "corte" in fase or "rebrote" in fase else
                  "cosecha / rastrojo" if "rastrojo" in fase else "cambio propio de la fase")
        return _Diag("OK", "OK",
                     f"Caida marcada del NDVI ({d_ndvi:+.3f}) coherente con la fase de {fase}: "
                     f"se interpreta como {evento}, no como problema sanitario.",
                     True, False)
    if ndvi_juicio < lo * 0.8:
        return _Diag("Revisar", "Revisar",
                     f"{ctx.indice_juicio} {ndvi_juicio:.3f} muy por debajo del rango esperado "
                     f"para la fase de {fase} ({lo:.2f}-{hi:.2f}).", False, False)
    if ndvi_juicio < lo:
        return _Diag("Vigilar", "Vigilar",
                     f"{ctx.indice_juicio} {ndvi_juicio:.3f} algo por debajo del rango de la fase "
                     f"de {fase} ({lo:.2f}-{hi:.2f}).", False, False)
    if d_ndvi is not None and d_ndvi < -0.10 and not ctx.caida_ok:
        return _Diag("Revisar", "Revisar",
                     f"Caida brusca del NDVI ({d_ndvi:+.3f}) NO esperada en la fase de {fase}: "
                     f"posible estres, plaga o incidencia.", False, False)
    return _Diag("OK", "OK",
                 f"{ctx.indice_juicio} {ndvi_juicio:.3f} dentro del rango esperado para la fase "
                 f"de {fase} ({lo:.2f}-{hi:.2f}).", False, False)


# ---------------------------------------------------------------------
# Las reglas que MATIZAN el veredicto base. Cada una: (ctx, diag) -> _Efecto | None
# ---------------------------------------------------------------------
def _regla_traza_indice(ctx, diag):
    """Deja dicho CON QUE se ha juzgado. No cambia el veredicto, lo explica.

    Un diagnostico que no dice si miro el NDVI o el MSAVI, ni si aparto las encinas,
    no se puede discutir con el agricultor ni reproducir despues."""
    txt = ""
    if ctx.indice_juicio == "MSAVI":
        txt += (f" [El NDVI observado ({ctx.ndvi:.3f}) esta inflado por la cubierta; se juzga con "
                f"MSAVI, robusto al suelo. Vigor de copa: {ctx.contraste.get('vigor_copa', '-')}.]")
    elif ctx.tipo == "EXTENSIVO" and ctx.contraste and ctx.contraste.get("situacion"):
        txt += f" [Contraste de indices: {ctx.contraste['situacion']}.]"
    if ctx.ndvi_limpio is not None:
        txt += (f" [Arbolado disperso (dehesa/encinas): se juzga con la media del cultivo "
                f"{ctx.ndvi_limpio:.3f}, excluyendo los pixeles de arbol permanente; la media bruta "
                f"de la parcela era {ctx.ndvi:.3f}.]")
    return _Efecto(texto=txt) if txt else None


def _regla_lenoso_sin_hoja(ctx, diag):
    """LEÑOSO CADUCO EN INVIERNO: el arbol esta sin hoja.

    En viña, almendro o pistacho en parada invernal no hay hoja: el NDVI cae a
    valores de suelo y eso es NORMAL. Cualquier verde es cubierta, no el cultivo.
    Es la unica regla que BAJA el nivel de alerta, y por eso va antes que las que lo
    suben: lo que rescata aqui no debe volver a saltar mas abajo."""
    if not (ctx.fase_esp and ctx.fase_esp.get("invierno_sin_hoja")):
        return None
    sufijo = (" [El arbol esta SIN HOJA: cualquier verde que se vea es cubierta o "
              "hierba, no el cultivo. El NDVI no mide el arbol hasta la brotacion.]")
    if diag.clave in ("Revisar", "Vigilar") and ctx.ndvi is not None and ctx.ndvi >= ctx.lo * 0.7:
        nuevo = (f"NDVI {ctx.ndvi:.3f} propio de la parada invernal sin hoja "
                 f"({ctx.lo:.2f}-{ctx.hi:.2f}).")
        return _Efecto(estado="OK", texto=nuevo + sufijo, esperado=True, reemplaza=True)
    return _Efecto(texto=sufijo)


def _regla_vigor_copa(ctx, diag):
    """VIGOR DE COPA (lenosos): el MSAVI, no el NDVI medio.

    El NDVI de la parcela mezcla copa y calle, asi que un olivar puede salir
    "normal" con la copa floja y la hierba alta. El MSAVI corrige el suelo; con
    percentiles y lineas resolubles se usa el p90 trasladado, que es copa casi
    pura. El umbral viene de (especie, fase, regimen) y lleva ya el factor del
    marco: un seto cubre mas suelo que un olivar a 100 arboles/ha.
    UNA SOLA ESCALA. El msavi_min de la tabla es un umbral DE COPA: un dosel de
    olivo sano da MSAVI ~0.43. Lo que mide el satelite es otra cosa: la media de
    un pixel que en un olivar tradicional es copa en un 20 % y calle en el 80 %
    restante, y que sale 0.11 con el arbol perfecto. Comparar lo uno con lo otro
    hacia saltar el aviso SIEMPRE en tradicional.

    Se compara siempre en escala de PARCELA: el umbral se traduce con la
    fraccion de copa (ver fenologia_especies.umbral_en_escala_parcela). El p90
    no se usa como si fuera copa pura, porque no lo es: a 10 m de pixel, ni
    siquiera un marco de 12 m da un pixel limpio de copa -lo dice el "limite
    honesto" de contraste_indices-. El p90 sigue sirviendo para el reparto
    copa/cubierta y para contarlo, que es para lo que vale."""
    msavi_min = ctx.umbrales.get("msavi_min")
    if not (ctx.tipo == "LENOSO" and msavi_min is not None and ctx.separacion
            and not ctx.fase_esp.get("invierno_sin_hoja")):
        return None
    copa_val = ctx.act.get("msavi")
    umbral_val = ctx.fase_esp.get("msavi_min_parcela", msavi_min)
    fc = ctx.fase_esp.get("fraccion_copa")
    de_donde = ("media de la parcela" if fc is None else
                f"media de la parcela; umbral de copa {msavi_min:.2f} traido a "
                f"una copa que tapa el {fc * 100:.0f} % del suelo")
    estado, txt = None, ""
    if copa_val is not None and umbral_val is not None and copa_val < umbral_val:
        # Sin marco no hay conversion, asi que se esta comparando una mezcla
        # contra un umbral de copa: eso NO puede llegar a "Revisar" por si
        # solo. Con marco si, porque las dos cosas estan en la misma escala.
        if diag.clave == "OK":
            estado = "Vigilar"
        elif diag.clave == "Vigilar" and fc is not None:
            estado = "Revisar"
        txt += (f" Vigor de copa por debajo de lo esperado: MSAVI {copa_val:.3f} "
                f"({de_donde}) frente a {umbral_val:.2f} en {ctx.fase} de "
                f"{ctx.umbrales.get('regimen', 'SECANO').lower()}.")
        if ctx.umbrales.get("critica"):
            txt += (" Es además una fase crítica: lo que pase aquí se nota en la "
                    "cosecha" + (" del año que viene." if "postcosecha" in ctx.fase
                                 else "."))
    if ctx.separacion["confianza"] != "alta":
        txt += (" [Copa y calle no se separan bien con este marco: el juicio de "
                "copa va con la media, no con el percentil 90.]")
    return _Efecto(estado=estado, texto=txt) if (estado or txt) else None


def _sequia_comarcal(ctx, ndmi_min):
    """Si TODA la comarca lleva semanas de deficit, un NDMI bajo en secano es
    coherente con la sequia y no debe -por si solo- subir la alerta.

    Devuelve (ndmi_min, nota): con `ndmi_min` a None se salta el escalado, que es el
    mismo escape que usa `deficit_buscado`. La nota se ensena SIEMPRE que exista: si
    suprimio, explica por que no ha subido la alerta; si no (regadio), acompana al
    aviso con el balance de la comarca.

    Modulo OPCIONAL (`balance_hidrico`): si no esta o falla, el NDMI escala
    EXACTAMENTE igual que si esta funcion no existiera."""
    try:
        import balance_hidrico as _BH
        exp = _BH.explicacion_deficit(ctx.parcela, ctx.fecha, ctx.umbrales.get("regimen"))
    except Exception:
        # Rastro en debug para diagnosticar sin cambiar el comportamiento.
        log.debug("no se pudo aplicar el contexto de sequia comarcal", exc_info=True)
        return ndmi_min, None
    if not exp:
        return ndmi_min, None
    suprimir, nota = exp
    return (None if suprimir else ndmi_min), nota


def _regla_falta_de_agua(ctx, diag):
    """FALTA DE AGUA: eleva el nivel de alerta (ya no contradice al semaforo).

    El suelo del NDMI sale de la FASE, no de una constante unica: un maiz en
    floracion sufre mucho antes que un trigo en rastrojo. `ndmi_min = None`
    significa que en esta fase el NDMI no dice nada (presiembra, barbecho,
    senescencia, lenoso sin hoja) y no se evalua. Si la fase no declara nada,
    DEFECTO_UMBRALES deja el 0.0 de siempre.
    En lenosos hay ademas una fase donde el deficit es INTENCIONADO: envero y
    maduracion de viña (riego deficitario controlado para calidad) y el verano
    de secano. Ahi el NDMI bajo no es una anomalia, y avisar seria un error.

    Aqui dentro va tambien el CONTEXTO DE SEQUIA COMARCAL (modulo opcional
    `balance_hidrico`), porque decide sobre el MISMO umbral: si toda la comarca
    lleva semanas de deficit, un NDMI bajo en secano es coherente con la sequia y
    no debe -por si solo- subir la alerta. Separarlo en otra regla obligaria a
    pasarse el `ndmi_min` ya tocado de una a otra, que es justo el acoplamiento
    que este refactor quita."""
    ndmi, ndmi_min = ctx.ndmi, ctx.umbrales["ndmi_min"]
    estado, txt = None, ""
    if ctx.umbrales.get("deficit_buscado") and ndmi is not None:
        txt += (f" [NDMI {ndmi:+.3f}: en esta fase el deficit hidrico es lo esperado"
                + (" en secano" if ctx.umbrales.get("regimen") == "SECANO" else
                   " (riego deficitario controlado)") + ", no se toma como aviso.]")
        ndmi_min = None
    # CONTEXTO DE SEQUIA COMARCAL (opcional, gated, extraible). Se reutiliza el
    # mismo escape que `deficit_buscado`: poner ndmi_min a None salta el escalado.
    # Sin `balance_hidrico.py` no se importa nada y el NDMI bajo escala EXACTAMENTE
    # igual que hoy.
    nota_hidrica = None
    if ndmi_min is not None and ndmi is not None and ndmi < ndmi_min and not diag.esperado:
        ndmi_min, nota_hidrica = _sequia_comarcal(ctx, ndmi_min)
    if ndmi_min is not None and ndmi is not None and ndmi < ndmi_min and not diag.esperado:
        # el listón calibrado por el usuario, si lo hay, manda sobre el de la tabla
        como = (f"negativo ({ndmi:+.3f})" if ndmi_min == 0.0 else
                f"{ndmi:+.3f}, por debajo de {ndmi_min:.2f} esperado en {ctx.fase}")
        if diag.clave == "OK":
            estado = "Vigilar"
            txt += f" Ademas el NDMI es {como}: indicio de estres hidrico."
        elif diag.clave == "Vigilar":
            estado = "Revisar"
            txt += f" El NDMI {como} agrava el diagnostico."
        else:
            txt += f" NDMI {como}: estrés hídrico asociado."
        if ctx.umbrales.get("critica"):
            txt += (" Es además la fase en la que la falta de agua más se lleva "
                    "por delante el rendimiento.")
    # el contexto de sequia comarcal se anade siempre que exista: si suprimio el
    # escalado, EXPLICA por que el NDMI bajo no ha subido la alerta; si no lo
    # suprimio (regadio), acompana al aviso con el balance de la comarca.
    if nota_hidrica:
        txt += " " + nota_hidrica
    return _Efecto(estado=estado, texto=txt) if (estado or txt) else None


def _regla_eventos_cuaderno(ctx, diag):
    """EVENTOS DEL CUADERNO DE CAMPO.

    Una siega/cosecha/herbicida REGISTRADO por el usuario explica una caida brusca
    y prevalece sobre la deteccion automatica: deja de ser alarma. Es la unica regla
    que SUSTITUYE el motivo entero, porque lo que explica el dato ya no es el
    razonamiento del motor, es el apunte del agricultor."""
    if not ctx.eventos_cerca:
        return None
    try:
        from registro_parcela import explicacion_por_eventos
        esp_ev, txt_ev = explicacion_por_eventos(ctx.eventos_cerca, ctx.d_ndvi)
    except Exception:
        # importante: si esto falla, una siega/cosecha REGISTRADA deja de
        # explicar la caida del NDVI y saltaria como falsa alarma.
        log.warning("no se pudo aplicar la explicacion por eventos del cuaderno",
                    exc_info=True)
        return None
    if not esp_ev:
        return None
    return _Efecto(estado="OK", texto=txt_ev, esperado=True, reemplaza=True)


def _regla_zonas(ctx, diag):
    """Si hay deterioro LOCALIZADO, se advierte de posible foco (biotico).

    Cuatro lecturas EXCLUSIVAS de la distribucion interna, de mas grave a menos:
    foco localizado, deterioro general, y el aviso temprano (la parcela se desiguala
    antes de que la media se mueva). No se solapa con un evento del cuaderno ni con
    un corte de forraje: si eso ya explica lo observado, sobra un segundo aviso."""
    hetero = ctx.hetero
    if not ctx.heterogeneidad_activa:
        return None      # el usuario ha apagado el analisis de zonas para esta parcela
    if diag.evento_explica or ctx.segado:
        return None      # el evento (o el corte de forraje) ya explica lo observado
    sube = ("Vigilar" if diag.clave == "OK" and not diag.esperado else None)
    if hetero and hetero.get("patron") == "deterioro LOCALIZADO":
        return _Efecto(estado=sube, texto=(
            " [ATENCION: deterioro LOCALIZADO. La dispersion interna crece "
            f"(std {hetero['d_std']:+.3f}) mientras la media cae: posible FOCO en la "
            "parcela (hongo, plaga o rodal). Revisar el mapa para localizar la mancha.]"))
    if hetero and hetero.get("patron") == "deterioro GENERALIZADO":
        return _Efecto(texto=(
            " [Deterioro GENERALIZADO y homogeneo: apunta a causa general "
            "(sequia, helada, senescencia), no a un foco localizado.]"))
    if hetero and (hetero.get("patron") == "heterogeneidad creciente"
                   or hetero.get("rodal_sospechoso")):
        # AVISO TEMPRANO: el foco AUN NO ha movido la media, pero la parcela ya se
        # esta desigualando (o hay un 10 % claramente hundido). Se avisa antes de
        # que el problema sea visible en el promedio.
        senales = []
        if hetero.get("patron") == "heterogeneidad creciente":
            senales.append(f"la dispersión interna crece (std {hetero['d_std']:+.3f}) "
                           "aunque la media aguanta")
        if hetero.get("rodal_sospechoso"):
            senales.append(f"el 10 % peor está {hetero['hundimiento']:.2f} puntos por debajo "
                           "de la mediana (rodal hundido)")
        return _Efecto(estado=sube, texto=(
            " [AVISO TEMPRANO: " + " y ".join(senales) + ". Puede ser el INICIO de un "
            "foco localizado, antes de que se note en el promedio. Conviene mirar el "
            "mapa y, si al revisarla esta todo bien, validar el diagnostico: se tendra "
            "en cuenta para las proximas pasadas.]"))
    return None


def _plausibilidad_extensivo(especie, fase, valor):
    """(nivel, techo) de plausibilidad de `valor` para esa especie y fase.

    Dos listones, y NINGUNO lleva un factor inventado: los dos salen de las propias
    tablas de `fenologia_especies`.

      "imposible" -> el valor supera lo que la especie alcanza en su MEJOR momento
          de TODO el ciclo. Sea cual sea la fase, eso no lo da el cultivo declarado.
          No se aplica en la fase de techo (donde `hi` ES el maximo del ciclo):
          alli el cultivo esta legitimamente en su tope y un exceso no se distingue
          del ruido de la medida.

      "otra_fase" -> el valor cae fuera del rango de la fase declarada Y de sus
          fases contiguas. La tolerancia de UNA fase no es un numero elegido: es
          exactamente el desfase que este programa ya da por normal, y por eso
          existe el ajuste por grados-dia (el calendario se corre del orden de una
          fase en un ano calido o frio). Dos fases ya no es adelanto.

    Devuelve (None, None) si no se puede juzgar."""
    info = FEN.EXTENSIVO_ESPECIES.get(especie)
    if not info or valor is None:
        return None, None
    fases = info["fases"]
    maximo = max(x[4] for x in fases)
    idx = next((i for i, x in enumerate(fases) if x[2] == fase), None)
    if idx is None:
        return None, None
    es_techo = abs(fases[idx][4] - maximo) < 1e-9
    if valor > maximo and not es_techo:
        return "imposible", maximo
    vecino_hi = max(fases[j][4] for j in range(max(0, idx - 1), min(len(fases), idx + 2)))
    if valor > vecino_hi:
        return "otra_fase", vecino_hi
    return None, None


def _regla_plausibilidad(ctx, diag):
    """«Esto no se parece a lo que me has dicho que es.»

    El motor sabia detectar «hay menos verde del que deberia», pero no lo contrario:
    medido, un NDVI de 1.00 quince dias despues de sembrar daba OK, porque el techo
    de la fase solo se IMPRIMIA y nunca se juzgaba.

    Dos niveles, por decision explicita:
      - IMPOSIBLE -> estado propio `Revisar datos` y motivo nuevo. El veredicto
        agronomico anterior no vale de nada si el dato no cuadra con lo declarado.
      - OTRA FASE -> solo una NOTA. El semaforo no se toca: un cultivo puede ir
        adelantado, y marcarlo en rojo por eso seria peor que callarse.

    Que revisar, y son cuatro cosas, no una: la fecha de siembra, la especie, la
    geometria de la parcela, o que lo que domina el pixel no sea el cultivo (una
    cubierta de malas hierbas puede estar mas verde que el propio cereal; el motor
    solo trata la cubierta en lenosos). En los cuatro casos lo honesto es lo mismo:
    lo que hay en el suelo no es lo que consta.
    """
    if ctx.tipo != "EXTENSIVO" or ctx.indice_juicio != "NDVI":
        return None
    especie = (ctx.spec or {}).get("especie")
    nivel, techo = _plausibilidad_extensivo(especie, ctx.fase, ctx.ndvi_juicio)
    if nivel is None:
        return None
    if nivel == "imposible":
        return _Efecto(
            estado=ESTADO_DATOS, esperado=False, reemplaza=True,
            texto=(f"NDVI {ctx.ndvi_juicio:.3f} por encima de lo que {especie.lower()} "
                   f"alcanza en su mejor momento de todo el ciclo ({techo:.2f}). El dato "
                   f"no cuadra con el cultivo declarado, asi que el diagnostico "
                   f"agronomico no se puede sostener. Revisa, por este orden: la fecha "
                   f"de siembra, la especie declarada, la geometria de la parcela, y si "
                   f"lo que se ve puede ser una cubierta de malas hierbas mas verde que "
                   f"el cultivo."))
    return _Efecto(texto=(
        f" [El verdor observado ({ctx.ndvi_juicio:.3f}) es propio de una fase distinta "
        f"de la declarada: en {ctx.fase} y sus fases contiguas no pasa de {techo:.2f}. "
        f"El semaforo no se toca -un cultivo puede ir adelantado-, pero conviene "
        f"revisar la fecha de siembra.]"))


# Margen para decir que un veredicto esta "en el filo". Es una heuristica de
# PRESENTACION: no mueve ni un veredicto, solo avisa de cuales se deciden por poco.
# El valor sale de lo medido en la fase 3 (con ruido de +-0.03 oscila el 45 % de las
# combinaciones pegadas a un umbral), pero el ruido REAL depende de la instalacion y
# se mide con `medir_ruido.py`. Por eso es una constante a la vista y no un numero
# escondido en una comparacion.
MARGEN_FILO = 0.03

# Estados donde "estar en el filo" no significa nada: no se han decidido comparando
# un indice contra un umbral.
_SIN_FILO = ("Sin dato", "N.A.", "Segado", ESTADO_DATOS)


def _distancia_al_corte(valor, lo):
    """Lo que le sobra al valor para caer del otro lado del corte mas cercano.

    El juicio del nivel tiene DOS cortes: `lo` (dentro/algo por debajo) y `lo*0.8`
    (algo/muy por debajo). Se mira el mas cercano de los dos, que es el que decide.
    None si no se puede calcular."""
    if valor is None or lo is None:
        return None
    return min(abs(valor - lo), abs(valor - lo * 0.8))


def _fase_en_duda(ctx):
    """True si la fase pudo cambiar ENTRE esta pasada y la anterior.

    Sin numeros inventados: la ventana es la que hay entre las dos pasadas. Si el
    limite de la fase cae dentro de ese hueco, no se sabe de que lado estaba el
    cultivo cuando se tomo el dato, y el liston con el que se le juzga es discutible.
    """
    fe = ctx.fase_esp or {}
    das = fe.get("das")
    if das is None or not ctx.prev:
        return False
    try:
        hueco = (datetime.strptime(ctx.act.get("fecha"), "%Y-%m-%d")
                 - datetime.strptime(ctx.prev.get("fecha"), "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return False
    if hueco <= 0:
        return False
    especie = (ctx.spec or {}).get("especie")
    info = FEN.EXTENSIVO_ESPECIES.get(especie)
    if not info:
        return False
    limites = [f[0] for f in info["fases"]] + [info["fases"][-1][1]]
    return any(das - hueco < L <= das for L in limites)


def _regla_fiabilidad(ctx, diag):
    """Dice CUANDO un veredicto se ha decidido por poco, y por que.

    Medido sobre el barrido: uno de cada cuatro diagnosticos cambia si el NDVI se
    mueve +-0.03, y hasta ahora todos se presentaban con la misma rotundidad. Esto
    no cambia el veredicto -de eso se encarga la persistencia, que ya retiene los
    fragiles-: lo que hace es DECIRLO.

    Deliberadamente NO repite lo que ya se dice en otro sitio (que copa y calle no
    se separan, o que el umbral viene de tus validaciones): eso ya sale en el motivo
    por sus propias reglas, y duplicarlo seria ruido.
    """
    if diag.estado in _SIN_FILO:
        return None
    razones = []
    d = _distancia_al_corte(ctx.ndvi_juicio, ctx.lo)
    if d is not None and d < MARGEN_FILO:
        razones.append(f"el {ctx.indice_juicio} esta a {d:.3f} del corte que decide "
                       f"este veredicto")
    # el NDMI tiene su propio corte, y tambien sube el nivel de alerta al cruzarlo.
    # Sin esto se escapaba el 3 % de los veredictos que cambiarian (medido).
    nm = ctx.umbrales.get("ndmi_min")
    if (ctx.ndmi is not None and nm is not None
            and abs(ctx.ndmi - nm) < MARGEN_FILO):
        razones.append(f"el NDMI esta a {abs(ctx.ndmi - nm):.3f} de su minimo de fase")
    if _fase_en_duda(ctx):
        razones.append("la fase pudo cambiar entre esta pasada y la anterior, asi que "
                       "el liston con el que se juzga es discutible")
    if not razones:
        return None
    return _Efecto(texto=" [Veredicto AJUSTADO: " + "; ".join(razones) +
                   ". Conviene esperar a la siguiente pasada antes de actuar.]")


def _regla_nota_calibracion(ctx, diag):
    """Si algun umbral viene de TUS validaciones y no de la tabla, se dice.

    Va la ultima a proposito: es una nota sobre COMO se ha juzgado, no una razon
    mas del juicio, y tiene que leerse al final del motivo."""
    if _CAL is None or not ctx.umbrales.get("calibrado"):
        return None
    return _Efecto(texto=" " + _CAL.texto_calibracion(ctx.umbrales))


# EL ORDEN IMPORTA, y por eso es una lista con nombre y no la posicion de las
# lineas en el fichero. De arriba abajo:
#   1. se dice con que indice se ha juzgado;
#   2. el leñoso sin hoja RESCATA (unica regla que baja el nivel), asi que va antes
#      que todas las que suben;
#   3. vigor de copa y falta de agua suben el nivel, en ese orden: primero el
#      cultivo, luego el agua, que es como se lee el motivo;
#   4. un evento del cuaderno PISA todo lo anterior: lo apuntado por el agricultor
#      manda sobre lo deducido;
#   5. el aviso de zonas, que se calla si el evento ya lo explico;
#   6. la plausibilidad del dato, que va casi al final porque si lo declarado no
#      cuadra con lo observado, el veredicto agronomico anterior ya no sostiene;
#   7. si el veredicto se ha decidido por poco, se dice (no lo cambia: lo matiza);
#   8. y la nota de calibracion, que cierra.
REGLAS = [
    ("traza_indice", _regla_traza_indice),
    ("lenoso_sin_hoja", _regla_lenoso_sin_hoja),
    ("vigor_copa", _regla_vigor_copa),
    ("falta_de_agua", _regla_falta_de_agua),
    ("eventos_cuaderno", _regla_eventos_cuaderno),
    ("zonas", _regla_zonas),
    ("plausibilidad", _regla_plausibilidad),
    ("fiabilidad", _regla_fiabilidad),
    ("nota_calibracion", _regla_nota_calibracion),
]


def _aplicar(diag, efecto, nombre):
    """El veredicto despues de una regla. Devuelve un `_Diag` nuevo: nadie muta."""
    if efecto is None:
        return diag
    motivo = efecto.texto if efecto.reemplaza else diag.motivo + efecto.texto
    clave = estado = efecto.estado
    if efecto.estado is None:
        clave, estado = diag.clave, diag.estado
    return _Diag(clave=clave, estado=estado, motivo=motivo,
                 esperado=diag.esperado if efecto.esperado is None else efecto.esperado,
                 evento_explica=diag.evento_explica or nombre == "eventos_cuaderno")


def _diagnostico_crudo(tipo, subtipo, serie, fecha_iso=None, eventos_cerca=None, spec=None,
                       parcela=None, heterogeneidad_activa=True, arbolado=False):
    """
    El diagnostico SIN filtro de persistencia: lo que dicen los indices de esta
    pasada, tal cual. Es el juicio agronomico, y es lo que aprende la calibracion.

    Se resuelve en tres pasos, que es como conviene leerlo: se PREPARA el contexto
    (`_preparar_contexto`), se emite un veredicto base (`_juicio_base`) y se pasa por
    las `REGLAS`, en ese orden, que lo matizan.

    parcela: nombre, solo para poder aplicar los umbrales que el usuario haya
        calibrado con sus validaciones (modulo OPCIONAL calibracion_umbrales).
        Sin este argumento -o sin ese modulo- se juzga con la tabla de siempre.

    heterogeneidad_activa: si es False, NO se analizan zonas dentro de la parcela
        ni se avisa de focos. Hay parcelas donde ese aviso solo estorba (muy
        pequenas, muy uniformes, o donde ya se sabe de donde viene la mancha).
        Los estadisticos se siguen calculando y mostrando: lo que se apaga es el
        JUICIO sobre ellos, no el dato.

    eventos_cerca: lista opcional [(dias, evento), ...] del cuaderno de campo.
    spec: dict opcional con el modelo por especie:
        {"especie": ..., "fecha_siembra": ..., "marco_calle": ..., "marco_pie": ...}
        Si se aporta, la fenologia se calcula por especie (cereal por dias desde
        siembra; leñoso por mes + marco). Si no, se usa el calendario por meses.
    """
    if tipo == "BARBECHO":
        return {"estado": "N.A.", "clave": "NA", "fase": "barbecho",
                "motivo": "Parcela en barbecho: no se evalua el vigor del cultivo.",
                "deltas": {}, "cubierta": None, "esperado": True,
                "estado_crudo": "N.A.", "clave_cruda": "NA", "confirmando": False,
                "ajustado": False}

    if not serie:
        return {"estado": "Sin dato", "clave": "Sin", "fase": "-",
                "motivo": "Sin pasadas validas de satelite.", "deltas": {},
                "cubierta": None, "esperado": False,
                "estado_crudo": "Sin dato", "clave_cruda": "Sin", "confirmando": False,
                "ajustado": False}

    ctx = _preparar_contexto(tipo, subtipo, serie, fecha_iso, eventos_cerca, spec,
                             parcela, heterogeneidad_activa, arbolado)
    diag = _juicio_base(ctx)
    disparadas = []
    for nombre, regla in REGLAS:
        efecto = regla(ctx, diag)
        if efecto is not None:
            disparadas.append(nombre)
        diag = _aplicar(diag, efecto, nombre)

    return {"estado": diag.estado, "clave": diag.clave, "fase": ctx.fase,
            "rango_fase": (ctx.lo, ctx.hi), "motivo": diag.motivo, "deltas": ctx.deltas,
            "cubierta": ctx.cubierta, "copa": ctx.copa, "heterogeneidad": ctx.hetero,
            "ndvi_juicio": ctx.ndvi_juicio, "esperado": diag.esperado,
            "fecha": ctx.fecha, "umbrales": ctx.umbrales,
            # sin filtrar: `evaluar_parcela` puede retener el estado una pasada,
            # pero el juicio agronomico es este y es el que aprende la calibracion
            "estado_crudo": diag.estado, "clave_cruda": diag.clave,
            "confirmando": False,
            # el veredicto se ha decidido por poco. Es para que la LISTA lo pueda
            # marcar: en la ficha ya se explica por que, dentro del motivo.
            "ajustado": "fiabilidad" in disparadas}


# =====================================================================
# 4c. PERSISTENCIA: el semaforo no cambia con una sola pasada
# =====================================================================
# MEDIDO en 6.880 combinaciones (especie x fase x distancia al umbral x ruido):
# dentro de una fase, con el umbral quieto y ruido CERO, el semaforo no cambia
# nunca. Con ruido realista de +-0.03 oscila en el 45 % de las combinaciones, y la
# franja donde ocurre es exactamente del ancho del ruido: a +-0.03 por encima del
# umbral, cero oscilacion. Es decir: el problema es real, es ruido, y esta pegado
# a los cortes.
#
# De las tres alternativas medidas (banda muerta, persistencia y marcar sin
# suprimir) se eligio PERSISTENCIA DE DOS PASADAS. Con ruido realista quita el
# 74 % de las oscilaciones y retrasa un aviso de verdad UNA pasada. (k=3 quitaba
# el 92 %, pero en la prueba de deterioro real no llegaba a avisar nunca en ocho
# pasadas: por eso no.)
#
# La regla, entera:
#     el estado que se ENSENA cambia solo cuando el estado CRUDO se repite en dos
#     pasadas seguidas.
#
# Lo que NO se retiene, y por que. La persistencia esta para filtrar RUIDO; estas
# cuatro cosas no son ruido, son hechos, y retenerlas seria enseñar algo falso:
#   - "Sin dato": esa pasada no tiene NDVI. Mantener el veredicto anterior seria
#     presentar como actual un juicio que no se ha hecho.
#   - "Segado": el corte de forraje es un evento discreto, no una fluctuacion.
#   - "N.A." (barbecho): ni siquiera llega aqui, sale antes.
#   - cualquier pasada con `esperado=True`: una caida propia de la fase o explicada
#     por el cuaderno YA esta explicada. Retener una alarma que el motor sabe que
#     no lo es seria justo lo contrario de lo que se busca.
# Esto es una interpretacion de la decision, no la decision: si se prefiere que
# retenga tambien esos casos, se quita de `_SIN_RETENER` y se regenera el oro.
PERSISTENCIA_PASADAS = 2
_SIN_RETENER = ("Sin dato", "Segado", "N.A.")

_NOTA_CONFIRMANDO = (" [El semaforo espera una segunda pasada para confirmar el cambio: "
                     "un solo dato pegado a un umbral suele ser ruido de la medida. "
                     "Lo que se ve arriba es lo observado en esta pasada.]")


def _retiene(estado, esperado):
    """Si este veredicto puede quedarse esperando confirmacion. Ver el bloque de
    arriba: solo se retiene lo que puede ser ruido."""
    return estado not in _SIN_RETENER and not esperado


def evaluar_parcela(tipo, subtipo, serie, fecha_iso=None, eventos_cerca=None, spec=None,
                    parcela=None, heterogeneidad_activa=True, arbolado=False):
    """El diagnostico que se ENSENA: el del motor, con la persistencia aplicada.

    Devuelve el mismo dict que `_diagnostico_crudo` mas tres claves:
      - `estado_crudo` / `clave_cruda`: el juicio sin filtrar. Es lo que aprende la
        calibracion, porque retener un estado es una decision de PRESENTACION y no
        un juicio agronomico: si el aprendizaje mirase el estado retenido, estaria
        aprendiendo del filtro y no del cultivo.
      - `confirmando`: True cuando el estado crudo y el ensenado no coinciden, es
        decir, cuando hay un cambio esperando su segunda pasada.

    El `motivo` es SIEMPRE el de la pasada actual -lo que se ha visto de verdad-;
    cuando se retiene, se le anade una nota que explica por que el semaforo aun no
    se ha movido. Asi el texto nunca contradice al dato.

    Coste: para saber si el estado crudo se repite hace falta el de la pasada
    anterior, asi que se recorre la serie de principio a fin. Son unas decimas de
    milisegundo por pasada; con 30 pasadas, milisegundos.
    """
    if tipo == "BARBECHO" or not serie:
        return _diagnostico_crudo(tipo, subtipo, serie, fecha_iso, eventos_cerca, spec,
                                  parcela, heterogeneidad_activa, arbolado)

    # OJO: `eventos_cerca` y `fecha_iso` son de la ULTIMA pasada, asi que para las
    # anteriores se recalcula SIN ellos. Un evento del cuaderno marca `esperado`, y
    # lo esperado no se retiene, asi que el efecto se limita a la pasada siguiente
    # a una explicada por un evento. Es un limite consciente y esta probado.
    mostrado = None
    crudo_prev = None
    for i in range(len(serie)):
        ultima = (i == len(serie) - 1)
        d = _diagnostico_crudo(tipo, subtipo, serie[:i + 1],
                               fecha_iso if ultima else None,
                               eventos_cerca if ultima else None,
                               spec, parcela, heterogeneidad_activa, arbolado)
        crudo = (d["clave"], d["estado"])
        if mostrado is None:                      # la primera pasada se ensena tal cual
            mostrado = crudo
        elif not _retiene(d["estado"], d.get("esperado")):
            mostrado = crudo                      # hechos, no ruido: pasan sin esperar
        elif crudo == mostrado:
            pass                                  # nada que confirmar
        elif crudo == crudo_prev:
            mostrado = crudo                      # segunda pasada seguida: se confirma
        # si no, se queda el anterior y el crudo sigue esperando
        crudo_prev = crudo
        if ultima:
            d["estado_crudo"], d["clave_cruda"] = d["estado"], d["clave"]
            d["confirmando"] = (mostrado != crudo)
            if d["confirmando"]:
                d["clave"], d["estado"] = mostrado
                d["motivo"] += _NOTA_CONFIRMANDO
            return d
    return d


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
                    "nota": f"Validaste este diagnóstico como correcto en {confirmaciones} "
                            f"pasada(s) similar(es) de campañas anteriores."}
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
                         eventos_cerca=None, spec=None, aprendizaje=None,
                         parcela=None, heterogeneidad_activa=True, arbolado=False):
    """Genera el texto. Usa ChatGPT si hay OPENAI_API_KEY; si no, respaldo por reglas.

    `aprendizaje`: validaciones pasadas del agricultor (almacen.validaciones_recientes)
    que se reinyectan como contexto para que la IA acierte mejor en el futuro.

    `parcela` y `heterogeneidad_activa` van tal cual a `evaluar_parcela` y hay que
    pasarlos: esta funcion vuelve a evaluar por su cuenta, y si evalua con otros
    argumentos que quien pinto la cabecera, el semaforo y el texto que hay debajo
    salen de DOS diagnosticos distintos. Sin `parcela` se pierden los umbrales
    calibrados de esa finca (cabecera «OK», texto «Vigilar»); con la
    heterogeneidad forzada a True, una parcela con el analisis de zonas APAGADO
    recibia igualmente el aviso de «foco localizado» -y se guardaba en la base-."""
    diag = evaluar_parcela(tipo, subtipo, serie, fecha_iso, eventos_cerca=eventos_cerca,
                           spec=spec, parcela=parcela,
                           heterogeneidad_activa=heterogeneidad_activa, arbolado=arbolado)

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
                f"{c['señales']}/{TOTAL_SENALES_CUBIERTA} señales).")
    return txt
