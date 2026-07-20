# -*- coding: utf-8 -*-
"""
contraste_indices.py
====================

Alternativa (mejor) al desmezclado por fraccion de copa.

IDEA: no hace falta INVENTAR una fraccion de copa (fc) ni un NDVI de fondo.
Cada indice pondera de forma DISTINTA la copa y el suelo/cubierta, asi que el
CONTRASTE ENTRE INDICES ya contiene la informacion. Se deja que los indices se
delaten entre si.

FISICA DE CADA CONTRASTE
------------------------
  NDVI - MSAVI   MSAVI esta disenado para ANULAR el efecto del suelo. Si el NDVI
                 sube y el MSAVI no le acompana, ese verde esta en el FONDO, no
                 en la copa. Es el contraste mas directo suelo/vegetacion.

  NDVI vs LAI    El LAI mide ESTRUCTURA del dosel (area foliar). La hierba rasa
                 aporta verdor pero poca estructura. NDVI arriba + LAI plano =
                 verde sin dosel = cubierta.

  NDVI vs EVI    El EVI corrige suelo y atmosfera y no se satura en biomasa alta.
                 En vegetacion densa y estructurada, EVI acompana al NDVI. Si el
                 NDVI sube mucho mas que el EVI, hay senal de fondo.

  GNDVI / NDVI   El GNDVI (banda verde) responde mas a la CLOROFILA de hoja densa.
                 La razon GNDVI/NDVI difiere entre copa lenosa y herbacea joven.

  NDMI           La copa perenne (raiz profunda) retiene agua en verano; la hierba
                 se agosta. NDMI alto con LAI bajo = agua en el fondo, no en copa.

VENTAJAS sobre el desmezclado por fc:
  - Sin parametros inventados (no hay fc ni fondo que estimar).
  - Funciona igual en LENOSOS y en EXTENSIVOS (ver mas abajo).
  - Es relativo: se compara el indice consigo mismo y con sus hermanos, asi que
    no depende de la finca concreta.

EN EXTENSIVOS el problema es paralelo:
  - Distinguir SENESCENCIA (NDVI baja, NDMI baja, LAI baja: todo cae junto, el
    cultivo se seca de forma ordenada) de ESTRES (NDMI cae PRIMERO y mas rapido
    que el NDVI: la planta pierde agua antes que verdor).
  - Detectar MALAS HIERBAS o rebrote sobre rastrojo (NDVI sube fuera de fase,
    MSAVI acompana poco, LAI bajo).
"""

from datetime import datetime


# =====================================================================
# UTILIDADES
# =====================================================================
def _g(reg, k):
    v = reg.get(k)
    return None if v is None else float(v)


def _delta(serie, k, n=1):
    """Variacion del indice k entre la ultima pasada y n pasadas atras."""
    if len(serie) <= n:
        return None
    a, b = _g(serie[-1], k), _g(serie[-1 - n], k)
    if a is None or b is None:
        return None
    return a - b


# =====================================================================
# 1. CONTRASTES BASICOS (valen para cualquier cultivo)
# =====================================================================
def contrastes(serie):
    """Calcula los contrastes entre indices de la ultima pasada (y su evolucion)."""
    if not serie:
        return None
    a = serie[-1]
    ndvi, msavi = _g(a, "ndvi"), _g(a, "msavi")
    savi, evi = _g(a, "savi"), _g(a, "evi")
    lai, ndmi = _g(a, "lai"), _g(a, "ndmi")
    gndvi = _g(a, "gndvi")

    c = {}

    # --- suelo vs vegetacion ---
    if ndvi is not None and msavi is not None:
        c["brecha_suelo"] = round(ndvi - msavi, 3)          # alto -> senal de fondo
    if ndvi is not None and savi is not None:
        c["brecha_savi"] = round(ndvi - savi, 3)

    # --- verdor vs estructura del dosel ---
    if ndvi is not None and lai is not None and ndvi > 0.05:
        # LAI esperado si todo el verde fuese dosel estructurado (lai ~ 3.6*evi)
        c["lai_por_ndvi"] = round(lai / ndvi, 2)            # bajo -> verde sin estructura
    if ndvi is not None and evi is not None and evi > 0.02:
        c["ndvi_evi"] = round(ndvi / evi, 2)                # alto -> saturacion o fondo

    # --- clorofila de hoja densa ---
    if gndvi is not None and ndvi is not None and ndvi > 0.05:
        c["gndvi_ndvi"] = round(gndvi / ndvi, 2)

    # --- agua ---
    if ndmi is not None and lai is not None:
        c["ndmi"] = round(ndmi, 3)
        c["agua_sin_dosel"] = bool(ndmi > 0.15 and lai < 2.0)

    # --- EVOLUCION: quien se mueve y quien no (lo mas revelador) ---
    d_ndvi = _delta(serie, "ndvi")
    d_msavi = _delta(serie, "msavi")
    d_lai = _delta(serie, "lai")
    d_ndmi = _delta(serie, "ndmi")
    if d_ndvi is not None:
        c["d_ndvi"] = round(d_ndvi, 3)
    if d_ndvi is not None and d_msavi is not None:
        # NDVI se mueve y MSAVI no -> el movimiento es del fondo
        c["divergencia_ndvi_msavi"] = round(d_ndvi - d_msavi, 3)
    if d_ndvi is not None and d_lai is not None:
        # NDVI sube y LAI plano -> verde sin estructura
        c["divergencia_ndvi_lai"] = round(d_ndvi - (d_lai / 3.6), 3)
    if d_ndmi is not None:
        c["d_ndmi"] = round(d_ndmi, 3)
    if d_ndvi is not None and d_ndmi is not None:
        # el agua cae ANTES que el verdor -> estres; caen juntos -> senescencia
        c["agua_cae_antes"] = bool(d_ndmi < -0.05 and d_ndvi > -0.05)

    return c


# =====================================================================
# 2. DIAGNOSTICO EN LENOSOS: ¿el verde es de la copa o de la cubierta?
# =====================================================================
def diagnostico_lenoso(serie, fecha_iso, subtipo=""):
    """
    Decide, SOLO por contraste entre indices, si el verdor procede de la copa o
    de la cubierta, y da un vigor de copa CUALITATIVO (alto/medio/bajo) sin
    necesidad de estimar fraccion de copa.
    """
    c = contrastes(serie)
    if not c:
        return None
    mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month
    ventana = mes in (12, 1, 2, 3, 4, 5)      # epoca de cubierta viva

    ev = []      # evidencias a favor de CUBIERTA
    ec = []      # evidencias a favor de COPA

    b = c.get("brecha_suelo")
    if b is not None:
        if b > 0.12:
            ev.append(f"brecha NDVI-MSAVI alta ({b}): hay verde que el MSAVI no ve, "
                      f"o sea que esta en el fondo")
        elif b < 0.05:
            ec.append(f"brecha NDVI-MSAVI baja ({b}): el verde resiste la correccion "
                      f"de suelo, luego es dosel real")

    dvl = c.get("divergencia_ndvi_lai")
    if dvl is not None:
        if dvl > 0.06:
            ev.append(f"el NDVI sube sin que el LAI acompane ({dvl}): verde sin estructura")
        elif dvl < -0.02:
            ec.append(f"el LAI crece junto al NDVI ({dvl}): el verde tiene estructura de copa")

    lpn = c.get("lai_por_ndvi")
    if lpn is not None:
        if lpn < 2.2:
            ev.append(f"poca area foliar para el verdor observado (LAI/NDVI={lpn})")
        elif lpn > 3.2:
            ec.append(f"mucha area foliar por unidad de verdor (LAI/NDVI={lpn}): dosel denso")

    if c.get("agua_sin_dosel"):
        ev.append("NDMI alto con LAI bajo: el agua esta a ras de suelo, no en copa")

    if ventana:
        ev.append("epoca de cubierta viva (invierno-primavera)")
    else:
        ec.append("fuera de la ventana de cubierta (agostada)")

    n_ev, n_ec = len(ev), len(ec)
    if n_ev >= 3 and n_ev > n_ec:
        veredicto = "cubierta vegetal dominando la senal"
    elif n_ev > n_ec:
        veredicto = "posible aporte de cubierta"
    else:
        veredicto = "senal atribuible a la copa"

    # vigor de copa CUALITATIVO: se usan los indices que MENOS ven el suelo
    msavi = _g(serie[-1], "msavi")
    lai = _g(serie[-1], "lai")
    evi = _g(serie[-1], "evi")
    ref = {"TRADICIONAL": (0.22, 0.38), "INTENSIVO": (0.32, 0.50),
           "SUPERINTENSIVO": (0.45, 0.65)}.get(subtipo, (0.30, 0.48))
    vigor = None
    if msavi is not None:
        if msavi < ref[0]:
            vigor = "bajo"
        elif msavi < ref[1]:
            vigor = "medio"
        else:
            vigor = "alto"

    return {
        "veredicto_cubierta": veredicto,
        "evidencias_cubierta": ev,
        "evidencias_copa": ec,
        "vigor_copa": vigor,
        "indices_robustos": {"msavi": msavi, "lai": lai, "evi": evi},
        "razonamiento": ("El vigor de la copa se juzga con MSAVI/LAI/EVI, que son "
                         "mucho menos sensibles al suelo y a la cubierta que el NDVI."),
        "contrastes": c,
    }


# =====================================================================
# 3. DIAGNOSTICO EN EXTENSIVOS: senescencia vs estres vs malas hierbas
# =====================================================================
def diagnostico_extensivo(serie, fecha_iso, subtipo=""):
    """
    Por contraste entre indices distingue tres situaciones que el NDVI solo confunde:
      - SENESCENCIA: todo cae junto y ordenado (NDVI, LAI y NDMI a la vez).
      - ESTRES HIDRICO: el NDMI cae ANTES y mas rapido que el NDVI (pierde agua
        antes que verdor). Es la firma temprana, la que permite reaccionar.
      - MALAS HIERBAS / REBROTE: el NDVI sube fuera de fase con LAI bajo y brecha
        NDVI-MSAVI alta (verde disperso, sin dosel de cultivo).
    """
    c = contrastes(serie)
    if not c:
        return None
    mes = datetime.strptime(fecha_iso, "%Y-%m-%d").month

    d_ndvi = c.get("d_ndvi")
    d_ndmi = c.get("d_ndmi")
    brecha = c.get("brecha_suelo")
    dvl = c.get("divergencia_ndvi_lai")

    señales = []
    situacion = "desarrollo normal"

    # --- estres hidrico temprano: el agua cae antes que el verdor ---
    if c.get("agua_cae_antes"):
        situacion = "estres hidrico incipiente"
        señales.append("el NDMI cae mientras el NDVI aun se mantiene: la planta pierde "
                       "agua ANTES que verdor (firma temprana de estres)")
    # --- senescencia: caen todos a la vez ---
    elif (d_ndvi is not None and d_ndvi < -0.08 and d_ndmi is not None and d_ndmi < -0.03):
        es_epoca = (subtipo == "COSECHA_GRANO" and mes in (6, 7)) or \
                   (subtipo == "SIEGA_VERDE" and mes in (2, 3, 4, 5, 6, 7))
        if es_epoca:
            situacion = "senescencia / corte (normal)"
            señales.append("NDVI, LAI y NDMI descienden de forma conjunta y ordenada, "
                           "en la epoca esperada: maduracion, siega o cosecha")
        else:
            situacion = "caida anomala"
            señales.append("caida conjunta de todos los indices FUERA de la epoca de "
                           "senescencia: revisar (plaga, encharcamiento, dano)")
    # --- malas hierbas / rebrote sobre rastrojo ---
    elif (d_ndvi is not None and d_ndvi > 0.06 and
          brecha is not None and brecha > 0.12 and
          dvl is not None and dvl > 0.05):
        situacion = "verde disperso (malas hierbas o rebrote)"
        señales.append("el NDVI sube con brecha NDVI-MSAVI alta y sin subida de LAI: "
                       "verde disperso sin dosel de cultivo")
    elif d_ndvi is not None and d_ndvi > 0.05:
        situacion = "crecimiento activo"
        señales.append("NDVI al alza acompanado por el resto de indices")

    return {
        "situacion": situacion,
        "señales": señales,
        "contrastes": c,
        "razonamiento": ("El contraste NDMI vs NDVI separa el estres (el agua cae primero) "
                         "de la senescencia (cae todo junto). La brecha NDVI-MSAVI con LAI "
                         "bajo delata verde que no es del cultivo."),
    }


# =====================================================================
# 4. PUNTO DE ENTRADA UNICO
# =====================================================================
def analizar_por_contraste(tipo, subtipo, serie, fecha_iso=None):
    """Devuelve el diagnostico por contraste de indices, sea lenoso o extensivo."""
    if not serie:
        return None
    fecha = fecha_iso or serie[-1].get("fecha")
    if tipo == "LENOSO":
        d = diagnostico_lenoso(serie, fecha, subtipo)
        if d:
            d["ambito"] = "lenoso"
        return d
    if tipo == "EXTENSIVO":
        d = diagnostico_extensivo(serie, fecha, subtipo)
        if d:
            d["ambito"] = "extensivo"
        return d
    return {"ambito": "barbecho", "situacion": "barbecho",
            "contrastes": contrastes(serie), "señales": []}


# =====================================================================
# 5. HETEROGENEIDAD INTRAPARCELA (usa desviacion y percentiles del NDVI)
# =====================================================================
"""
La MEDIA oculta la heterogeneidad. Dos parcelas con NDVI medio 0.60:
  - una uniforme (std=0.04): todo el cultivo va igual de bien.
  - otra con un rodal malo (std=0.18, p10=0.28): hay una zona hundida que la
    media enmascara, porque el resto de la parcela la compensa.

Con la desviacion estandar y los percentiles que ahora guarda el sincronizador
se puede detectar ese rodal SIN necesidad de analisis espacial completo:

  amplitud   = p90 - p10   -> cuanto se separan los mejores de los peores
  hundimiento= p50 - p10   -> cuanto peor esta el 10 % peor respecto a la mediana
  cv         = std / media -> heterogeneidad relativa

Y lo mas util: la EVOLUCION de estas metricas.
  - Si la media baja Y la desviacion SUBE  -> el problema es LOCALIZADO (una zona
    se hunde mientras el resto aguanta). Firma tipica de foco: hongo, plaga, rodal.
  - Si la media baja Y la desviacion se mantiene o BAJA -> el problema es UNIFORME
    (toda la parcela cae a la vez). Firma tipica de sequia, helada, senescencia.

Esta distincion NO identifica la enfermedad, pero separa lo LOCALIZADO de lo
GENERALIZADO, que es la pista mas util para decidir si merece la pena ir a campo
a buscar un foco.
"""

def heterogeneidad(serie):
    """Analiza la distribucion del NDVI dentro de la parcela y su evolucion."""
    if not serie:
        return None
    a = serie[-1]
    media = _g(a, "ndvi")
    std = _g(a, "ndvi_std")
    p10, p50, p90 = _g(a, "ndvi_p10"), _g(a, "ndvi_p50"), _g(a, "ndvi_p90")
    n = a.get("n_pixeles")
    cob = a.get("cobertura_valida")

    if media is None or std is None:
        return {"disponible": False,
                "nota": "Sin estadistica espacial (pasada anterior al enmascarado SCL)."}

    r = {"disponible": True, "media": round(media, 3), "std": round(std, 3),
         "p10": p10, "p50": p50, "p90": p90, "n_pixeles": n, "cobertura_valida": cob}

    if p10 is not None and p90 is not None:
        r["amplitud"] = round(p90 - p10, 3)
    if p10 is not None and p50 is not None:
        r["hundimiento"] = round(p50 - p10, 3)
    if media > 0.05:
        r["cv"] = round(std / media, 3)

    # --- uniformidad ---
    cv = r.get("cv")
    if cv is None:
        r["uniformidad"] = "desconocida"
    elif cv < 0.12:
        r["uniformidad"] = "parcela uniforme"
    elif cv < 0.25:
        r["uniformidad"] = "heterogeneidad moderada"
    else:
        r["uniformidad"] = "parcela muy heterogenea"

    # --- zona hundida: el 10 % peor esta MUY por debajo de la mediana ---
    hund = r.get("hundimiento")
    r["rodal_sospechoso"] = bool(hund is not None and hund > 0.15)

    # --- EVOLUCION: la clave para separar LOCALIZADO de GENERALIZADO ---
    prev = serie[-2] if len(serie) > 1 else None
    if prev and _g(prev, "ndvi") is not None and _g(prev, "ndvi_std") is not None:
        d_media = media - _g(prev, "ndvi")
        d_std = std - _g(prev, "ndvi_std")
        d_p10 = None if p10 is None or _g(prev, "ndvi_p10") is None else p10 - _g(prev, "ndvi_p10")
        r["d_media"] = round(d_media, 3)
        r["d_std"] = round(d_std, 3)
        if d_p10 is not None:
            r["d_p10"] = round(d_p10, 3)

        if d_media < -0.05 and d_std > 0.02:
            r["patron"] = "deterioro LOCALIZADO"
            r["lectura"] = ("La media cae mientras la dispersion AUMENTA: una zona concreta "
                            "se esta hundiendo mientras el resto aguanta. Firma compatible con "
                            "un FOCO (hongo, plaga, rodal). Conviene inspeccionar el mapa y "
                            "localizar la mancha.")
        elif d_media < -0.05 and d_std <= 0.02:
            r["patron"] = "deterioro GENERALIZADO"
            r["lectura"] = ("La media cae y la dispersion no aumenta: TODA la parcela decae a la "
                            "vez de forma homogenea. Firma compatible con causa general (sequia, "
                            "helada, senescencia), no con un foco localizado.")
        elif d_std > 0.04:
            r["patron"] = "heterogeneidad creciente"
            r["lectura"] = ("La parcela se esta volviendo mas desigual aunque la media aguante: "
                            "vigilar, puede ser el inicio de un problema localizado.")
        else:
            r["patron"] = "estable"
            r["lectura"] = "La distribucion interna de la parcela se mantiene estable."

    return r
