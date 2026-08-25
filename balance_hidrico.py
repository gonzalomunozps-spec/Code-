# -*- coding: utf-8 -*-
"""
balance_hidrico.py
==================

MODULO OPCIONAL Y EXTRAIBLE. Da CONTEXTO de sequia comarcal a partir del clima de
ERA5-Land (lluvia y ET0 que ya descarga `clima_era5`), para no confundir «seco
porque toca» con «seco porque ha fallado algo».

Idea (hallazgo 2 de la auditoria): hoy un NDMI por debajo de lo esperado en la
fase SUBE el nivel de alerta como «estres hidrico». Pero si TODA la comarca lleva
semanas de deficit (la ET0 supera con mucho a la lluvia), ese NDMI bajo es
coherente con la sequia general y no es, por si solo, una anomalia de ESTA
parcela: avisar en todas las parcelas a la vez no es accionable, es ruido. Este
modulo detecta ese deficit comarcal y deja que el motor lo tenga en cuenta.

QUE HACE Y QUE NO
  - Calcula un balance rodante lluvia - ET0 sobre una ventana (30 dias por
    defecto) hasta la fecha de la pasada.
  - Clasifica la severidad de ese deficit (normal / seco / muy seco).
  - `explicacion_deficit` decide si un NDMI bajo se explica por la sequia: en
    SECANO (y extensivos, que en su mayoria lo son) no debe subir la alerta por si
    solo; en REGADIO NO se suprime, porque el riego deberia haber sostenido el
    NDMI y un valor bajo pese al riego si es un aviso.
  - NO toca ningun umbral del NDMI ni del NDVI. Solo aporta contexto y, como mucho,
    evita que el NDMI bajo ESCALE el semaforo cuando la sequia ya lo explica.

REVERSIBLE: si borras este fichero, el gancho de `interpretacion_fenologica` no
importa nada y el diagnostico vuelve a comportarse EXACTAMENTE como hoy (el NDMI
bajo escala igual que siempre). Como `grados_dia`, el nucleo es puro y se prueba
sin red; el clima se pide de forma perezosa a `clima_era5`/`almacen`.

AVISO sobre los datos (igual que en `clima_era5`): el pixel de ERA5-Land son 11 km
de lado, asi que esto es contexto de COMARCA, no de parcela; y la ET0 es
evaporacion POTENCIAL (demanda atmosferica), no la ET real del cultivo, de modo
que lluvia - ET0 tiende a exagerar el deficit. Por eso los umbrales de abajo son
CONSERVADORES y estan pensados para calibrarse con campo.
"""

from datetime import datetime, timedelta


# Ventana del balance rodante, en dias. Un mes es el horizonte en el que una
# racha seca ya se nota en el NDMI del cultivo sin diluirse en el resto de la
# campana.
VENTANA_DIAS = 30

# Umbrales del deficit acumulado (mm) sobre la ventana. Negativo = la ET0 supera a
# la lluvia. Son CRITERIO provisional (ver el aviso de la cabecera), no
# bibliografia cerrada: deciden solo el CONTEXTO, nunca el umbral del NDMI.
DEFICIT_SECO = -75.0        # por debajo: la comarca lleva un deficit apreciable
DEFICIT_MUY_SECO = -150.0   # por debajo: sequia marcada


# =====================================================================
# Fechas (pequenos ayudantes, para no repetir el formato)
# =====================================================================
def _fecha(iso):
    return datetime.strptime(iso, "%Y-%m-%d")


def _iso(d):
    return d.strftime("%Y-%m-%d")


# =====================================================================
# Balance (puro: se prueba sin red)
# =====================================================================
def balance_ventana(clima_dias, fecha_iso, ventana=VENTANA_DIAS):
    """Suma de (lluvia - ET0) en los `ventana` dias hasta `fecha_iso` (incluida).

    `clima_dias` son los dias de `clima_era5`/`almacen.clima` (cada uno con
    `fecha`, `lluvia`, `et0`). Devuelve el deficit, los dias contados y los totales,
    o None si no hay ningun dia con AMBOS datos (sin lluvia y ET0 no hay balance)."""
    if not fecha_iso:
        return None
    try:
        hasta = _fecha(fecha_iso)
    except (TypeError, ValueError):
        return None
    desde = hasta - timedelta(days=ventana - 1)
    lluvia = et0 = 0.0
    n = 0
    for d in clima_dias or []:
        f = d.get("fecha")
        if not f:
            continue
        try:
            fd = _fecha(f)
        except (TypeError, ValueError):
            continue
        if fd < desde or fd > hasta:
            continue
        lv, ev = d.get("lluvia"), d.get("et0")
        if lv is None or ev is None:
            continue
        lluvia += lv
        et0 += ev
        n += 1
    if n == 0:
        return None
    return {"deficit_mm": round(lluvia - et0, 1), "dias": n,
            "lluvia_mm": round(lluvia, 1), "et0_mm": round(et0, 1)}


def severidad(deficit_mm):
    """Etiqueta de la sequia segun el deficit acumulado (mm)."""
    if deficit_mm is None:
        return "sin dato"
    if deficit_mm <= DEFICIT_MUY_SECO:
        return "muy seco"
    if deficit_mm <= DEFICIT_SECO:
        return "seco"
    return "normal"


def contexto(clima_dias, fecha_iso, ventana=VENTANA_DIAS):
    """El balance de la ventana + su severidad, o None si no se puede calcular."""
    b = balance_ventana(clima_dias, fecha_iso, ventana)
    if not b:
        return None
    sev = severidad(b["deficit_mm"])
    return dict(b, severidad=sev, sequia=(sev != "normal"), ventana=ventana)


def texto_contexto(ctx):
    """Una linea para ensenar el contexto hidrico (o vacia si no hay)."""
    if not ctx:
        return ""
    return (f"Balance de la comarca: {ctx['deficit_mm']:+.0f} mm (lluvia {ctx['lluvia_mm']:.0f} "
            f"− ET0 {ctx['et0_mm']:.0f}) en {ctx['dias']} días → {ctx['severidad']}.")


# =====================================================================
# INTEGRACION CON EL CLIMA REAL (lee de la base; degrada si no hay clima)
# =====================================================================
# `clima_era5` es OPCIONAL: si se ha borrado, no hay temperatura ni lluvia y el
# contexto no se puede calcular -> se devuelve None y el motor sigue como hoy.
try:
    import clima_era5 as _CLIMA
except Exception:
    _CLIMA = None


def _clima_de(parcela, desde, hasta):
    """Los dias de clima de la parcela entre dos fechas, o [] si no se puede."""
    if _CLIMA is None:
        return []
    try:
        import almacen as DB
        punto = _CLIMA.punto_de((DB.ficha(parcela) or {}).get("coordenadas"))
        if not punto:
            return []
        return DB.clima(punto, desde, hasta)
    except Exception:
        return []


def contexto_de_parcela(parcela, fecha_iso, ventana=VENTANA_DIAS):
    """Contexto hidrico de la comarca de `parcela` hasta `fecha_iso`, o None."""
    if not fecha_iso:
        return None
    try:
        hasta = _fecha(fecha_iso)
    except (TypeError, ValueError):
        return None
    desde = hasta - timedelta(days=ventana - 1)
    dias = _clima_de(parcela, _iso(desde), fecha_iso)
    return contexto(dias, fecha_iso, ventana)


def explicacion_deficit(parcela, fecha_iso, regimen=None, ventana=VENTANA_DIAS):
    """Si la comarca esta en sequia real, (suprimir_escalado, nota); si no, None.

    - suprimir_escalado: True si el NDMI bajo se explica por la sequia comarcal y
      NO debe, por si solo, subir el nivel de alerta. Es True en secano/extensivo y
      False en REGADIO (donde el riego deberia haber sostenido el NDMI, asi que un
      valor bajo pese al riego sigue siendo un aviso).
    - nota: texto para anadir al diagnostico, con el balance y su lectura.

    None cuando no hay clima o la comarca NO esta en sequia: entonces el motor
    escala el NDMI bajo como hasta ahora."""
    ctx = contexto_de_parcela(parcela, fecha_iso, ventana)
    if not ctx or not ctx["sequia"]:
        return None
    regadio = (regimen == "REGADIO")
    nota = (f"[Contexto hídrico: la comarca acumula {ctx['deficit_mm']:+.0f} mm de balance "
            f"(lluvia−ET0) en {ctx['dias']} días ({ctx['severidad']}). ")
    if regadio:
        nota += ("Aun en regadío el NDMI ha bajado: la sequía comarcal lo explica en parte, "
                 "pero conviene revisar el riego.]")
    else:
        nota += ("El NDMI bajo es coherente con la sequía general y no se toma, por sí solo, "
                 "como anomalía de esta parcela.]")
    return (not regadio, nota)
