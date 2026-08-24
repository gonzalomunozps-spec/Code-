# -*- coding: utf-8 -*-
"""
grados_dia.py
=============

MODULO OPCIONAL Y EXTRAIBLE. Integral termica (grados-dia, GDD) a partir de la
temperatura de ERA5-Land que ya descarga `clima_era5`.

Si borras este fichero, el programa sigue igual: la fase vuelve a estimarse por
DIAS de calendario (`fenologia_especies.fase_extensivo`), la ficha deja de
mostrar la tarjeta de GDD y el alta deja de ofrecer integrales termicas. Nada mas
que tocar: el motor lo llama por `try/except` (ver `interpretacion_fenologica`) y
la interfaz tambien.

POR QUE
-------
La fenologia la gobierna el TIEMPO TERMICO, no el calendario: dos trigos sembrados
el mismo dia llegan a espigado con semanas de diferencia entre un ano frio y uno
calido. Con dias fijos, en un ano frio el programa cree que el cultivo va mas
adelantado de lo que esta y aplica el rango de indice equivocado. Los grados-dia
lo corrigen usando la temperatura real.

QUE ES UNA INTEGRAL TERMICA
---------------------------
El grado-dia de un dia es cuanto calor UTIL ha hecho por encima de una temperatura
base (`Tbase`) por debajo de la cual el cultivo no crece:

    GDD_dia = max(0, (Tmax + Tmin) / 2 - Tbase)

y la integral es la SUMA de esos grados-dia a lo largo de una ventana. La `Tbase`
depende del cultivo (0 C en cereales de invierno, 10 C en maiz...). Algunos
metodos ademas TOPAN la Tmax (un maiz no crece mas rapido por encima de 30 C).

AVISO IMPORTANTE
----------------
Los hitos de GDD por fase (`GDD_FASES`) son valores de BIBLIOGRAFIA, orientativos
y variables por variedad, region y manejo. Son un punto de partida razonable, NO
una verdad de campo: hay que contrastarlos con lo observado en la parcela. Por eso
la fase por GDD solo PRIMA cuando el usuario define una integral a proposito.
"""

# Solo las tablas de fenologia, que son puras. El clima y la base se leen mas
# arriba (en `fase_override` y en la interfaz), para no atar este nucleo a la BD.
import fenologia_especies as FEN


# =====================================================================
# TIPOS DE INTEGRAL TERMICA
# =====================================================================
# Cada metodo: (clave, etiqueta, Tbase en C, tope de Tmax en C o None).
# La Tbase sale de la bibliografia clasica por cultivo/grupo; el tope (cutoff
# superior) es el metodo "con corte" para cultivos que se paran con el calor.
METODOS = [
    ("base0",      "Base 0 °C — cereales de invierno (trigo, cebada, avena)", 0.0,  None),
    ("base5",      "Base 5 °C — colza, remolacha, guisante", 5.0,  None),
    ("base6",      "Base 6 °C — girasol", 6.0,  None),
    ("base10",     "Base 10 °C — maíz, sorgo (C4)", 10.0, None),
    ("base10cut30", "Base 10 °C con tope 30 °C — maíz, método con corte", 10.0, 30.0),
]
_METODO = {k: (et, tb, tope) for k, et, tb, tope in METODOS}

# Metodo por defecto sugerido por grupo de cultivo (solo para preseleccionar en la
# interfaz; el usuario puede cambiarlo).
METODO_SUGERIDO = {
    "TRIGO": "base0", "CEBADA": "base0", "AVENA": "base0", "CENTENO": "base0",
    "TRITICALE": "base0", "COLZA": "base5", "GUISANTE": "base5", "VEZA": "base5",
    "REMOLACHA": "base5", "GIRASOL": "base6", "MAIZ": "base10cut30", "SORGO": "base10cut30",
}


def metodo(clave):
    """(etiqueta, Tbase, tope) del metodo, o el base0 si no se reconoce."""
    return _METODO.get(clave, _METODO["base0"])


def etiqueta_metodo(clave):
    return _METODO.get(clave, _METODO["base0"])[0]


# =====================================================================
# ACUMULACION (pura: se prueba sin red)
# =====================================================================
def gdd_dia(t_min, t_max, tbase, tope=None):
    """Grados-dia de UN dia. None si falta alguna temperatura.

    Metodo de la media con tope superior opcional (single-average con cutoff):
    se topa la Tmax antes de promediar, y el resultado no baja de cero (un dia frio
    no RESTA calor acumulado)."""
    if t_min is None or t_max is None:
        return None
    tmax = min(t_max, tope) if tope is not None else t_max
    media = (tmax + t_min) / 2.0
    return round(max(0.0, media - tbase), 2)


def acumular(clima_dias, clave_metodo, desde=None, hasta=None):
    """Suma de grados-dia sobre una ventana de fechas [desde, hasta] (ISO, ambas
    inclusive; None = sin limite por ese lado).

    `clima_dias` es la lista de dias de `clima_era5.clima_de_parcela` (cada uno con
    `fecha`, `t_min`, `t_max`). Devuelve un dict con el total, los dias contados y
    los que no tenian temperatura (para poder decir si el dato esta completo)."""
    _et, tbase, tope = metodo(clave_metodo)
    total, n, huecos = 0.0, 0, 0
    for d in clima_dias or []:
        f = d.get("fecha")
        if not f or (desde and f < desde) or (hasta and f > hasta):
            continue
        g = gdd_dia(d.get("t_min"), d.get("t_max"), tbase, tope)
        if g is None:
            huecos += 1
            continue
        total += g
        n += 1
    return {"gdd": round(total, 1), "dias": n, "huecos": huecos, "metodo": clave_metodo}


# =====================================================================
# HITOS DE GDD POR FASE  (bibliografia; contrastar con campo)
# =====================================================================
# GDD ACUMULADO DESDE LA SIEMBRA al COMIENZO de cada fase, con el metodo de esa
# especie. Los nombres coinciden EXACTAMENTE con `EXTENSIVO_ESPECIES` para que el
# rango de indice de la fase se reutilice tal cual (solo cambia el reloj: GDD en
# vez de dias). Rangos tipicos de bibliografia (Zadoks/GDD, FAO, extension
# agraria); variables por variedad y region.
GDD_FASES = {
    "TRIGO":  [(0, "nascencia"), (160, "ahijado"), (500, "encanado"),
               (1000, "espigado / floracion"), (1300, "llenado de grano"),
               (1800, "maduracion / senescencia"), (2100, "rastrojo / cosecha")],
    "CEBADA": [(0, "nascencia"), (150, "ahijado"), (450, "encanado"),
               (900, "espigado / floracion"), (1200, "llenado de grano"),
               (1650, "maduracion / senescencia"), (1950, "rastrojo / cosecha")],
    "AVENA":  [(0, "nascencia"), (170, "ahijado"), (520, "encanado"),
               (1050, "espigado / floracion"), (1350, "llenado de grano"),
               (1850, "maduracion / senescencia"), (2150, "rastrojo / cosecha")],
    "MAIZ":   [(0, "nascencia"), (90, "desarrollo vegetativo"),
               (650, "floracion (panoja/sedas)"), (900, "llenado de grano"),
               (1350, "maduracion (dentado)"), (1600, "seco / cosecha")],
    "GIRASOL": [(0, "emergencia"), (90, "desarrollo"), (500, "boton floral"),
                (800, "floracion"), (1100, "llenado / madurez"), (1600, "seco / cosecha")],
}


def hay_referencia_gdd(especie):
    """True si `especie` tiene hitos de GDD por fase (si no, se usa el calendario)."""
    return especie in GDD_FASES


def fase_por_gdd(especie, gdd_acumulado):
    """Nombre de fase segun el GDD acumulado desde la siembra. None si no hay tabla.

    Se elige la ULTIMA fase cuyo umbral de arranque ya se ha superado."""
    tabla = GDD_FASES.get(especie)
    if not tabla or gdd_acumulado is None:
        return None
    nombre = tabla[0][1]
    for umbral, fase in tabla:
        if gdd_acumulado >= umbral:
            nombre = fase
        else:
            break
    return nombre


def gdd_hasta_siguiente(especie, gdd_acumulado):
    """Cuantos grados-dia faltan para la fase siguiente (o None si es la ultima)."""
    tabla = GDD_FASES.get(especie)
    if not tabla or gdd_acumulado is None:
        return None
    for umbral, _fase in tabla:
        if gdd_acumulado < umbral:
            return round(umbral - gdd_acumulado, 1)
    return None


# =====================================================================
# LA FASE, VISTA POR GDD  (reusa los umbrales de la tabla por NOMBRE)
# =====================================================================
def _fila_de_fase(especie, nombre_fase):
    """La fila de `EXTENSIVO_ESPECIES` cuya fase se llama `nombre_fase`."""
    info = FEN.EXTENSIVO_ESPECIES.get(especie)
    if not info:
        return None
    for fila in info["fases"]:
        if fila[2] == nombre_fase:
            return fila
    return None


def fase_desde_gdd(especie, gdd_acumulado):
    """El MISMO dict que `fenologia_especies.fase_extensivo`, pero con la fase
    elegida por GDD en vez de por dias. Reusa el rango de indice y los umbrales de
    esa fase (no se inventa ninguno). None si no se puede (sin tabla o sin dato).

    `das` se deja como None a proposito: aqui el reloj es el GDD, no los dias; se
    devuelve `gdd` para que quien quiera lo muestre."""
    fase = fase_por_gdd(especie, gdd_acumulado)
    fila = _fila_de_fase(especie, fase) if fase else None
    if not fila:
        return None
    _d0, _d1, nombre, lo, hi, caida, extra = FEN._fila_fase(fila)
    return dict(FEN.umbrales_de_fase(extra), fase=nombre, das=None, lo=lo, hi=hi,
                caida=caida, previo=False, por_gdd=True, gdd=round(gdd_acumulado, 1))


# =====================================================================
# INTEGRACION CON EL CLIMA REAL  (lee de la base; degrada si no hay clima)
# =====================================================================
# `clima_era5` es OPCIONAL: si se ha borrado, no hay temperatura y la fase por GDD
# no se puede calcular -> se cae al calendario. `almacen` (la base) siempre esta.
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


def _metodo_de_integrales(integrales, especie):
    """El metodo a usar para la fase: el de la integral que arranca en la siembra,
    o el de la primera, o el sugerido para la especie."""
    for it in integrales or []:
        if (it.get("desde") or "").lower() in ("siembra", "nascencia", "emergencia"):
            return it.get("metodo") or METODO_SUGERIDO.get(especie, "base0")
    if integrales:
        return integrales[0].get("metodo") or METODO_SUGERIDO.get(especie, "base0")
    return METODO_SUGERIDO.get(especie, "base0")


def gdd_acumulado(especie, spec, fecha_iso, parcela):
    """GDD acumulado desde la siembra hasta `fecha_iso`, con clima real. None si no
    se puede (sin siembra, sin clima, sin metodo)."""
    siembra = (spec or {}).get("fecha_siembra")
    if not siembra or not fecha_iso:
        return None
    met = _metodo_de_integrales((spec or {}).get("integrales_termicas"), especie)
    clima = _clima_de(parcela, siembra, fecha_iso)
    if not clima:
        return None
    r = acumular(clima, met, desde=siembra, hasta=fecha_iso)
    return r if r["dias"] > 0 else None


def fase_override(tipo, especie, spec, fecha_iso, parcela):
    """La fase vista por GDD, con el MISMO formato que `fase_extensivo`, o None.

    Es el gancho que llama el motor. Solo actua si TODO se cumple:
      - es un EXTENSIVO (en lenosos la fenologia va por mes, no por GDD),
      - la parcela tiene integrales termicas definidas (el usuario lo pidio),
      - la especie tiene hitos de GDD (`GDD_FASES`),
      - y hay clima real para acumular.
    Si algo falta, devuelve None y el motor sigue con el calendario."""
    if tipo != "EXTENSIVO":
        return None
    if not (spec or {}).get("integrales_termicas"):
        return None
    if not hay_referencia_gdd(especie):
        return None
    ac = gdd_acumulado(especie, spec, fecha_iso, parcela)
    if ac is None:
        return None
    return fase_desde_gdd(especie, ac["gdd"])


def resumen_parcela(tipo, especie, spec, fecha_iso, parcela):
    """Lo que la ficha ensena de GDD, o None si no aplica. Incluye el GDD
    acumulado, la fase por GDD, la del calendario y cada integral definida con su
    GDD de referencia de bibliografia (para comparar adelanto/retraso)."""
    integrales = (spec or {}).get("integrales_termicas")
    if not integrales:
        return None
    ac = gdd_acumulado(especie, spec, fecha_iso, parcela)
    hitos = dict((f, g) for g, f in GDD_FASES.get(especie, []))
    filas = []
    for it in integrales:
        et = etiqueta_metodo(it.get("metodo"))
        d, h = it.get("desde", "siembra"), it.get("hasta", "cosecha")
        ref = None
        if d in hitos and h in hitos:
            ref = round(hitos[h] - hitos[d], 0)
        filas.append({"metodo": et, "desde": d, "hasta": h, "referencia_gdd": ref})
    return {
        "gdd_acumulado": ac["gdd"] if ac else None,
        "dias": ac["dias"] if ac else 0,
        "huecos": ac["huecos"] if ac else 0,
        "fase_gdd": fase_por_gdd(especie, ac["gdd"]) if ac else None,
        "faltan_siguiente": gdd_hasta_siguiente(especie, ac["gdd"]) if ac else None,
        "hay_referencia": hay_referencia_gdd(especie),
        "integrales": filas,
    }
