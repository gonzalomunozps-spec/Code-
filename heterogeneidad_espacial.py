# -*- coding: utf-8 -*-
"""
heterogeneidad_espacial.py
==========================

MODULO OPCIONAL Y EXTRAIBLE. Analisis ESPACIAL y TEMPORAL de la rejilla de NDVI
pixel a pixel, para lo que la heterogeneidad "clasica" (media, std, percentiles)
no puede ver por ser ciega al sitio de cada pixel.

Aporta dos cosas que necesitan la rejilla georreferenciada -donde el pixel (i,j)
es el MISMO trozo de terreno entre fechas (ver rejilla.py)-:

  1. AGRUPAMIENTO de los pixeles "bajos": ¿estan pegados entre si (FOCO real:
     hongo, plaga, rodal) o dispersos (ruido / senescencia general)? Y de estar
     agrupados, el TAMANO de la mancha mayor (en pixeles y en ha) y si PERSISTE
     respecto a la pasada anterior (los mismos pixeles cayendo = foco que crece).

  2. MASCARA DE ARBOLADO PERMANENTE (encinas y demas perennifolios): un pixel que
     se queda verde TODO el ano (minimo alto) y oscila poco (amplitud baja) es un
     arbol, no el cultivo herbaceo. En una dehesa o con encinas de lindero esos
     pixeles inflan el verdor y la heterogeneidad sin ser un problema. Se detectan
     por su firma TEMPORAL y se excluyen del juicio del cultivo.

Si borras este fichero, el diagnostico vuelve a la heterogeneidad clasica y no
pasa nada mas. El nucleo es PURO (se prueba sin red); solo `analizar_parcela` lee
las rejillas de la base.

AVISO: todos los umbrales de abajo son CRITERIO provisional, a calibrar con campo
(una dehesa real, un foco conocido). A 10 m de pixel, muchos pixeles son MIXTOS
(parte arbol, parte pasto): enmascarar quita tambien alguno mixto -se pierde algo
de superficie a cambio de un dato limpio-.
"""

import rejilla as _REJ     # capa 0, siempre presente


# --- arbolado permanente (perennifolio: encina, alcornoque, pino disperso) ---
NDVI_ARBOL_MIN = 0.35      # un pixel que NUNCA baja de aqui es candidato a arbol
AMPLITUD_ARBOL_MAX = 0.18  # ...y que ademas oscila poco a lo largo del ano
MIN_FECHAS_ARBOL = 4       # sin varias fechas no se puede ver "todo el ano"

# --- pixeles "bajos" y focos ---
K_BAJO = 1.0               # bajo = por debajo de media - K*std de la parcela
MIN_PIXELES_JUICIO = 12    # con menos pixeles utiles no se juzga la distribucion
MIN_MANCHA = 3             # una mancha de menos pixeles que esto es ruido, no foco


# =====================================================================
# NUCLEO PURO (opera sobre rejillas ya decodificadas y COMPARABLES)
# =====================================================================
def mascara_arbolado(grids, ndvi_min=NDVI_ARBOL_MIN, amplitud_max=AMPLITUD_ARBOL_MAX,
                     min_fechas=MIN_FECHAS_ARBOL):
    """Lista de bool por pixel: True si parece ARBOLADO PERMANENTE.

    `grids` son rejillas decodificadas (dict con 'valores') y COMPARABLES entre si
    (misma geometria, luego misma longitud). Un pixel es arbol si a lo largo del ano
    su NDVI se mantiene alto (minimo >= ndvi_min) y oscila poco (amplitud <=
    amplitud_max). None si no hay fechas suficientes para verlo."""
    grids = [g for g in (grids or []) if g and g.get("valores")]
    if len(grids) < min_fechas:
        return None
    n = len(grids[0]["valores"])
    mask = [False] * n
    for j in range(n):
        vals = [g["valores"][j] for g in grids
                if j < len(g["valores"]) and g["valores"][j] is not None]
        if len(vals) < min_fechas:
            continue
        mn, mx = min(vals), max(vals)
        if mn >= ndvi_min and (mx - mn) <= amplitud_max:
            mask[j] = True
    return mask


def pixeles_bajos(valores, validos, arbolado=None, k=K_BAJO):
    """(set de indices bajos, media, std, n_util). "Bajo" = por debajo de
    media - k*std, entre los pixeles VALIDOS y NO arbolados."""
    util = [i for i, (v, ok) in enumerate(zip(valores, validos))
            if ok and v is not None and not (arbolado and i < len(arbolado) and arbolado[i])]
    xs = [valores[i] for i in util]
    if len(xs) < MIN_PIXELES_JUICIO:
        return set(), None, None, len(xs)
    media = sum(xs) / len(xs)
    std = (sum((x - media) ** 2 for x in xs) / len(xs)) ** 0.5
    umbral = media - k * std
    bajos = {i for i in util if valores[i] < umbral}
    return bajos, round(media, 3), round(std, 3), len(xs)


def _vecinos4(idx, filas, cols):
    """Indices de los 4 vecinos ortogonales del pixel `idx` en la rejilla."""
    f, c = divmod(idx, cols)
    out = []
    if f > 0:
        out.append(idx - cols)
    if f < filas - 1:
        out.append(idx + cols)
    if c > 0:
        out.append(idx - 1)
    if c < cols - 1:
        out.append(idx + 1)
    return out


def componentes_conexas(indices, filas, cols):
    """Agrupa un conjunto de indices en componentes conexas por 4-vecindad.
    Devuelve la lista de componentes (cada una, un set de indices), de mayor a menor."""
    restantes = set(indices)
    comps = []
    while restantes:
        semilla = restantes.pop()
        pila, grupo = [semilla], {semilla}
        while pila:
            x = pila.pop()
            for v in _vecinos4(x, filas, cols):
                if v in restantes:
                    restantes.discard(v)
                    grupo.add(v)
                    pila.append(v)
        comps.append(grupo)
    comps.sort(key=len, reverse=True)
    return comps


def indice_agrupamiento(bajos, utiles, filas, cols):
    """Fraccion de pixeles bajos cuyo vecino (entre los UTILES) tambien es bajo.

    ~1 -> agrupados (foco compacto); cercano a la fraccion de bajos sobre el total
    -> dispersos (ruido, no foco). None si no se puede medir."""
    bajos = set(bajos)
    utiles = set(utiles)
    if not bajos:
        return None
    tot = enlaces = 0
    for i in bajos:
        vecinos_utiles = [v for v in _vecinos4(i, filas, cols) if v in utiles]
        if not vecinos_utiles:
            continue
        tot += len(vecinos_utiles)
        enlaces += sum(1 for v in vecinos_utiles if v in bajos)
    return round(enlaces / tot, 3) if tot else None


def centro_de(grupo, cols):
    """(fila, columna) medias de un grupo de pixeles: donde cae su centro."""
    if not grupo:
        return None
    fs = [i // cols for i in grupo]
    cs = [i % cols for i in grupo]
    return (round(sum(fs) / len(fs), 1), round(sum(cs) / len(cs), 1))


def analizar(grids, arbolado=False, k=K_BAJO):
    """Analisis espacial/temporal sobre rejillas decodificadas y COMPARABLES.

    Mira la ULTIMA rejilla: agrupamiento de los pixeles bajos, mancha mayor (px y
    ha) y si PERSISTE respecto a la anterior. Con `arbolado=True` enmascara antes
    los pixeles de arbol permanente (encinas). Devuelve un dict, o None si no hay
    datos suficientes."""
    grids = [g for g in (grids or []) if g and g.get("valores") and g.get("geo")]
    if not grids:
        return None
    geo = grids[-1]["geo"]
    filas, cols = int(geo.get("filas", 0)), int(geo.get("columnas", 0))
    if filas * cols != len(grids[-1]["valores"]):
        return None
    escala = float(geo.get("escala") or 10.0)

    mask = mascara_arbolado(grids) if arbolado else None
    n_arbol = sum(mask) if mask else 0

    act = grids[-1]
    bajos, media, std, n_util = pixeles_bajos(act["valores"], act["validos"], mask, k)
    utiles = {i for i, (v, ok) in enumerate(zip(act["valores"], act["validos"]))
              if ok and v is not None and not (mask and i < len(mask) and mask[i])}
    if media is None:
        return {"disponible": False, "n_arbolado": n_arbol,
                "nota": "Pocos pixeles utiles para el analisis espacial."}

    comps = componentes_conexas(bajos, filas, cols)
    mancha = comps[0] if comps else set()
    mancha_px = len(mancha)
    mancha_ha = round(mancha_px * escala * escala / 10000.0, 3)
    agr = indice_agrupamiento(bajos, utiles, filas, cols)

    # persistencia: de los pixeles bajos de HOY, cuantos ya estaban bajos ayer
    persistencia = None
    if len(grids) >= 2:
        prev = grids[-2]
        bajos_prev, _, _, _ = pixeles_bajos(prev["valores"], prev["validos"], mask, k)
        if bajos:
            persistencia = round(len(bajos & bajos_prev) / len(bajos), 3)

    # veredicto: foco (agrupado y con mancha real) vs disperso (ruido)
    hay_foco = mancha_px >= MIN_MANCHA and (agr is not None and agr >= 0.45)
    if not bajos:
        patron = "uniforme"
    elif hay_foco:
        patron = "foco localizado"
    else:
        patron = "disperso"

    return {
        "disponible": True,
        "patron": patron,
        "agrupamiento": agr,
        "mancha_px": mancha_px,
        "mancha_ha": mancha_ha,
        "centro": centro_de(mancha, cols) if hay_foco else None,
        "persistencia": persistencia,
        "n_bajos": len(bajos),
        "n_util": n_util,
        "media": media,
        "std": std,
        "n_arbolado": n_arbol,
        "pct_arbolado": round(100.0 * n_arbol / (filas * cols), 1) if filas * cols else 0.0,
        "escala_m": escala,
    }


def texto(res):
    """Interpretacion legible del analisis espacial, para el cuadro de la ficha.
    Cadena vacia si no hay analisis."""
    if not res or not res.get("disponible"):
        return ""
    p = []
    if res.get("n_arbolado"):
        p.append(f"Arbolado permanente detectado: {res['n_arbolado']} píxel(es) "
                 f"({res['pct_arbolado']:.0f} % de la parcela) se mantienen verdes todo el año "
                 "(posible encina/dehesa); se excluyen del juicio del cultivo.")
    patron = res.get("patron")
    if patron == "uniforme":
        p.append("Distribución interna homogénea: no hay zonas hundidas que destaquen.")
    elif patron == "foco localizado":
        ha = res.get("mancha_ha") or 0
        txt = (f"FOCO localizado: los píxeles bajos están agrupados "
               f"(agrupamiento {res.get('agrupamiento')}), la mancha mayor son "
               f"{res.get('mancha_px')} píxel(es) (~{ha:.2f} ha).")
        if res.get("persistencia") is not None and res["persistencia"] >= 0.5:
            txt += (f" Y PERSISTE: el {res['persistencia']*100:.0f} % ya estaba bajo en la pasada "
                    "anterior (un foco que se mantiene o crece). Conviene visitar esa zona.")
        else:
            txt += " Conviene mirar el mapa y localizar la mancha."
        p.append(txt)
    elif patron == "disperso":
        p.append(f"Píxeles bajos DISPERSOS (agrupamiento {res.get('agrupamiento')}), sin formar "
                 "una mancha compacta: apunta a ruido o a un cambio general, no a un foco.")
    return " ".join(p)


# =====================================================================
# INTEGRACION CON LA BASE (lee las rejillas; degrada si no hay)
# =====================================================================
def analizar_parcela(nombre, campana, arbolado=False, k=K_BAJO):
    """Analisis espacial de la parcela para una campana, leyendo sus rejillas de la
    base y quedandose solo con las COMPARABLES. None si no hay rejillas util(es)."""
    try:
        import almacen as DB
        crudas = DB.rejillas(nombre, campana)
    except Exception:
        return None
    buenas, _ = _REJ.comparables(crudas)
    decod = []
    for d in buenas:
        try:
            g = _REJ.decodificar(d)
        except Exception:
            g = None
        if g:
            decod.append(g)
    if len(decod) < 1:
        return None
    return analizar(decod, arbolado=arbolado, k=k)


def ndvi_cultivo_limpio(nombre, fecha):
    """Media de NDVI del CULTIVO en la rejilla de `fecha`: solo los pixeles VALIDOS
    y NO arbolados. Sirve para juzgar el vigor del herbaceo sin el verdor permanente
    de las encinas, que infla la media bruta.

    None (y el motor sigue con la media de siempre) si no se puede: sin rejillas,
    sin fechas suficientes para ver el arbolado, sin la rejilla de esa fecha, o si
    quedan muy pocos pixeles de cultivo tras enmascarar."""
    try:
        import almacen as DB
        crudas = DB.rejillas(nombre)          # todas las campanas: el arbol es plurianual
    except Exception:
        return None
    buenas, _ = _REJ.comparables(crudas)
    decod = []
    for d in buenas:
        try:
            g = _REJ.decodificar(d)
        except Exception:
            g = None
        if g:
            g["fecha"] = d.get("fecha")
            decod.append(g)
    if len(decod) < MIN_FECHAS_ARBOL:
        return None
    mask = mascara_arbolado(decod)
    if not mask or not any(mask):
        return None                    # no se ve arbolado: no hay nada que limpiar
    obj = next((g for g in decod if g.get("fecha") == fecha), None)
    if obj is None:
        return None
    xs = [v for i, (v, ok) in enumerate(zip(obj["valores"], obj["validos"]))
          if ok and v is not None and i < len(mask) and not mask[i]]
    if len(xs) < MIN_PIXELES_JUICIO:
        return None                    # quedan pocos pixeles de cultivo: no fiable
    return round(sum(xs) / len(xs), 3)
