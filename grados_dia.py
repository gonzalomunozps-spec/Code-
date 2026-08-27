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
Dos conceptos que NO hay que confundir (Tema 5, Fitotecnia General):

  - CERO VEGETATIVO (Tbase, To): la Tª por debajo de la cual el cultivo no crece.
    Es propio de CADA ESPECIE (0 C en cereales de invierno, 6 en girasol, 10 en
    maiz...). En la interfaz se autorrellena al elegir el cultivo, y es editable.

  - METODO de calculo: la FORMULA con la que se cuenta el calor. El temario da
    cuatro (ver `METODOS_CALCULO`):
        directo (Reaumur)   Σ Tm             con Tm ≥ 0
        tiempo termico      Σ (Tm − To)      con Tm ≥ To   (el grado-dia clasico)
        exponencial         Σ 2^((Tm−4,5)/10)
        heliotermico        Σ (Tm × horas de luz)

La integral es la SUMA de esos aportes a lo largo de una ventana. El tiempo termico
puede ademas TOPAR la Tmax (un maiz no crece mas rapido por encima de 30 C). Los
hitos de fase por GDD (`GDD_FASES`) estan en °C·dia de TIEMPO TERMICO: con otro
metodo las unidades no casan y la fase por GDD es solo orientativa.

AVISO IMPORTANTE
----------------
Los hitos de GDD por fase (`GDD_FASES`) son valores de BIBLIOGRAFIA, orientativos
y variables por variedad, region y manejo. Son un punto de partida razonable, NO
una verdad de campo: hay que contrastarlos con lo observado en la parcela. Por eso
la fase por GDD solo PRIMA cuando el usuario define una integral a proposito.
"""

# Solo las tablas de fenologia, que son puras. El clima y la base se leen mas
# arriba (en `fase_override` y en la interfaz), para no atar este nucleo a la BD.
import math
import datetime as _dt

import fenologia_especies as FEN


# =====================================================================
# DOS CONCEPTOS DISTINTOS: EL METODO (la formula) Y EL CERO VEGETATIVO (la Tbase)
# =====================================================================
# Un error frecuente es meter la Tbase dentro del "metodo". Son cosas distintas
# (Tema 5, Fitotecnia General): el CERO VEGETATIVO (Tbase, To) es propio de CADA
# ESPECIE -la Tª por debajo de la cual cesa el crecimiento-, y el METODO es la
# FORMULA con la que se cuenta el calor. Aqui van separados: la especie decide el
# cero vegetativo (se autorrellena, editable); el usuario elige el metodo.
#
# TIPOS DE INTEGRAL TERMICA (metodos de calculo del temario):
#   directo (Reaumur)      IT = Σ Tm            (Tm ≥ 0)  -relacion lineal-
#   tiempo_termico/residual IT = Σ (Tm − To)    (Tm ≥ To) -el clasico grado-dia-
#   exponencial            IT = Σ 2^((Tm−4,5)/10) (Tm ≥ 4,5) -reacciones biologicas-
#   heliotermico           I.HT = Σ (Tm × I)    con I = horas de luz del dia
METODOS_CALCULO = [
    ("tiempo_termico", "Tiempo térmico / residual — Σ (Tm − cero vegetativo)"),
    ("directo",        "Directo (Reaumur) — Σ Tm, con Tm ≥ 0"),
    ("exponencial",    "Exponencial — Σ 2^((Tm − 4,5)/10)"),
    ("heliotermico",   "Constante heliotérmica — Σ (Tm × horas de luz)"),
]
_METODO_CALC = dict(METODOS_CALCULO)
METODO_CALC_DEF = "tiempo_termico"

# CERO VEGETATIVO (Tbase, To) por especie, en C. Valores calibrados con los que
# cuadran los hitos de fase por GDD (`GDD_FASES`). Se autorrellena al elegir el
# cultivo, pero es EDITABLE: quien quiera puede teclear el de su temario
# (p. ej. girasol 7, sorgo 15). Fallback 0 C para lo no listado.
CERO_VEGETATIVO = {
    "TRIGO": 0.0, "CEBADA": 0.0, "AVENA": 0.0, "CENTENO": 0.0, "TRITICALE": 0.0,
    "COLZA": 5.0, "GUISANTE": 5.0, "VEZA": 5.0, "REMOLACHA": 5.0,
    "GIRASOL": 6.0, "MAIZ": 10.0, "SORGO": 10.0,
}
# Tope superior de Tmax sugerido (cutoff): un C4 no crece mas rapido por mucho
# calor. Se ofrece como valor por defecto, editable y opcional.
TOPE_SUGERIDO = {"MAIZ": 30.0, "SORGO": 30.0}

# Compatibilidad con integrales guardadas con el esquema anterior, donde el
# "metodo" era en realidad (Tbase, tope): se traducen a tiempo termico.
_LEGACY_METODO = {"base0": (0.0, None), "base5": (5.0, None), "base6": (6.0, None),
                  "base10": (10.0, None), "base10cut30": (10.0, 30.0)}


def cero_vegetativo(especie):
    """Cero vegetativo (Tbase) sugerido para la especie. 0 C si no esta en la tabla."""
    return CERO_VEGETATIVO.get((especie or "").upper(), 0.0)


def tope_sugerido(especie):
    """Tope de Tmax sugerido para la especie (o None si no lo tiene)."""
    return TOPE_SUGERIDO.get((especie or "").upper())


def etiqueta_calculo(clave):
    """Etiqueta larga del metodo de calculo (o la del tiempo termico si no se
    reconoce)."""
    return _METODO_CALC.get(clave, _METODO_CALC[METODO_CALC_DEF])


def params_integral(it):
    """(metodo, cero_vegetativo, tope) de una integral, aceptando el formato NUEVO
    ({metodo:'tiempo_termico', cero_vegetativo, tope}) y el ANTIGUO ({metodo:'base6'}).

    El formato antiguo se traduce a tiempo termico con su Tbase y su tope, para que
    las integrales ya guardadas sigan calculando exactamente igual que antes."""
    it = it or {}
    m = it.get("metodo") or METODO_CALC_DEF
    if m in _LEGACY_METODO:
        to, tope = _LEGACY_METODO[m]
        return "tiempo_termico", to, tope
    if m not in _METODO_CALC:
        m = METODO_CALC_DEF
    to = it.get("cero_vegetativo")
    to = 0.0 if to in (None, "") else float(to)
    tope = it.get("tope")
    tope = float(tope) if tope not in (None, "") else None
    return m, to, tope


def etiqueta_integral(it):
    """Etiqueta corta y legible de una integral para listas y desplegables:
    metodo + cero vegetativo (+ tope, si lo hay)."""
    m, to, tope = params_integral(it)
    nombre = {"tiempo_termico": "Tiempo térmico", "directo": "Directo (Reaumur)",
              "exponencial": "Exponencial", "heliotermico": "Heliotérmica"}.get(m, m)
    if m == "directo":
        return nombre                               # base 0 implicita
    if m == "exponencial":
        return f"{nombre} (ref. 4,5 °C)"
    if m == "heliotermico":
        return f"{nombre} (Tm × horas de luz)"
    extra = f", tope {tope:.0f} °C" if tope is not None else ""
    return f"{nombre} (cero veg. {to:.0f} °C{extra})"


# Compatibilidad hacia atras: codigo viejo podia llamar a estas. `etiqueta_metodo`
# ahora entiende tanto claves nuevas como las antiguas.
def etiqueta_metodo(clave):
    if clave in _LEGACY_METODO:
        to, tope = _LEGACY_METODO[clave]
        extra = f", tope {tope:.0f} °C" if tope is not None else ""
        return f"Tiempo térmico (cero veg. {to:.0f} °C{extra})"
    return etiqueta_calculo(clave)


# =====================================================================
# ACUMULACION (pura: se prueba sin red)
# =====================================================================
def _media(t_min, t_max, tope=None):
    """Tª media del dia, topando la Tmax antes de promediar si hay tope."""
    tmax = min(t_max, tope) if tope is not None else t_max
    return (tmax + t_min) / 2.0


def gdd_dia(t_min, t_max, tbase, tope=None):
    """Grados-dia de UN dia por TIEMPO TERMICO (residual). None si falta una Tª.

    Metodo de la media con tope superior opcional (single-average con cutoff):
    se topa la Tmax antes de promediar, y el resultado no baja de cero (un dia frio
    no RESTA calor acumulado)."""
    if t_min is None or t_max is None:
        return None
    return round(max(0.0, _media(t_min, t_max, tope) - tbase), 2)


def horas_luz(lat, fecha_iso):
    """Duracion del dia en HORAS de sol (modelo CBM, Forsythe et al. 1995), a partir
    de la latitud y el dia del ano. Pura; la usa el metodo heliotermico. None si no
    hay latitud o la fecha no se entiende."""
    if lat is None:
        return None
    try:
        doy = _dt.date.fromisoformat(fecha_iso).timetuple().tm_yday
    except (ValueError, TypeError):
        return None
    lat_r = math.radians(lat)
    P = math.asin(0.39795 * math.cos(0.2163108 + 2 * math.atan(
        0.9671396 * math.tan(0.00860 * (doy - 186)))))
    arg = ((math.sin(math.radians(0.8333)) + math.sin(lat_r) * math.sin(P)) /
           (math.cos(lat_r) * math.cos(P)))
    arg = max(-1.0, min(1.0, arg))                 # polos/dia polar: se satura, no rompe
    return round(24.0 - (24.0 / math.pi) * math.acos(arg), 3)


def aporte_dia(t_min, t_max, metodo=METODO_CALC_DEF, cero_veg=0.0, tope=None, horas=None):
    """Aporte termico de UN dia segun el TIPO de integral. None si faltan datos.

      tiempo_termico  max(0, media − cero_veg)     -grado-dia clasico-
      directo         max(0, media)                -Reaumur, Tm ≥ 0-
      exponencial     2^((media − 4,5)/10)         -0 si media < 4,5-
      heliotermico    max(0, media) × horas de luz -None si no hay horas-
    """
    if t_min is None or t_max is None:
        return None
    if metodo == "directo":
        return round(max(0.0, _media(t_min, t_max)), 2)
    if metodo == "exponencial":
        m = _media(t_min, t_max)
        return round(2.0 ** ((m - 4.5) / 10.0), 4) if m >= 4.5 else 0.0
    if metodo == "heliotermico":
        if horas is None:
            return None
        return round(max(0.0, _media(t_min, t_max)) * horas, 2)
    return gdd_dia(t_min, t_max, cero_veg, tope)   # tiempo termico (por defecto)


def acumular(clima_dias, integral=None, desde=None, hasta=None, lat=None):
    """Suma del aporte termico sobre [desde, hasta] (ISO, inclusive; None = sin
    limite por ese lado), con el metodo de `integral`.

    `integral` es un dict {metodo, cero_vegetativo, tope} y acepta el formato viejo
    ({metodo:'base6'}). `clima_dias` son los dias de `clima_era5` (fecha, t_min,
    t_max). Para el metodo heliotermico hace falta `lat` (para las horas de luz);
    sin ella, esos dias cuentan como hueco. Devuelve total, dias contados y huecos."""
    metodo, cero_veg, tope = params_integral(integral or {})
    total, n, huecos = 0.0, 0, 0
    for d in clima_dias or []:
        f = d.get("fecha")
        if not f or (desde and f < desde) or (hasta and f > hasta):
            continue
        horas = horas_luz(lat, f) if metodo == "heliotermico" else None
        g = aporte_dia(d.get("t_min"), d.get("t_max"), metodo, cero_veg, tope, horas)
        if g is None:
            huecos += 1
            continue
        total += g
        n += 1
    return {"gdd": round(total, 1), "dias": n, "huecos": huecos,
            "metodo": metodo, "cero_vegetativo": cero_veg, "tope": tope}


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


def _integral_para_fase(integrales, especie):
    """La integral cuyo GDD gobierna la fase: la que arranca en la siembra, o la
    primera; si no hay ninguna, una de tiempo termico con la base de la especie."""
    for it in integrales or []:
        if (it.get("desde") or "").lower() in ("siembra", "nascencia", "emergencia"):
            return it
    if integrales:
        return integrales[0]
    return {"metodo": METODO_CALC_DEF, "cero_vegetativo": cero_vegetativo(especie)}


def _lat_de(parcela):
    """Latitud (centro de la parcela) para las horas de luz del metodo heliotermico.
    None si no hay coordenadas. `coordenadas` es [[lon,lat], ...]."""
    try:
        import almacen as DB
        coords = (DB.ficha(parcela) or {}).get("coordenadas") or []
        lats = [c[1] for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
        return sum(lats) / len(lats) if lats else None
    except Exception:
        return None


def gdd_acumulado(especie, spec, fecha_iso, parcela):
    """GDD acumulado desde la siembra hasta `fecha_iso`, con clima real. None si no
    se puede (sin siembra, sin clima). El metodo y el cero vegetativo salen de la
    integral que gobierna la fase."""
    siembra = (spec or {}).get("fecha_siembra")
    if not siembra or not fecha_iso:
        return None
    it = _integral_para_fase((spec or {}).get("integrales_termicas"), especie)
    clima = _clima_de(parcela, siembra, fecha_iso)
    if not clima:
        return None
    lat = _lat_de(parcela) if params_integral(it)[0] == "heliotermico" else None
    r = acumular(clima, it, desde=siembra, hasta=fecha_iso, lat=lat)
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
        met, cv, tope = params_integral(it)
        d, h = it.get("desde", "siembra"), it.get("hasta", "cosecha")
        ref = None
        if d in hitos and h in hitos:
            ref = round(hitos[h] - hitos[d], 0)
        filas.append({"metodo": etiqueta_integral(it), "metodo_clave": met,
                      "cero_vegetativo": cv, "tope": tope,
                      "desde": d, "hasta": h, "referencia_gdd": ref})
    met_fase = params_integral(_integral_para_fase(integrales, especie))[0]
    return {
        "gdd_acumulado": ac["gdd"] if ac else None,
        "dias": ac["dias"] if ac else 0,
        "huecos": ac["huecos"] if ac else 0,
        "metodo_fase": met_fase,
        # los hitos de fase estan en °día de tiempo termico: con otro metodo las
        # unidades no casan y la fase por GDD es orientativa (el usuario lo eligio).
        "aviso_metodo": met_fase != "tiempo_termico",
        "fase_gdd": fase_por_gdd(especie, ac["gdd"]) if ac else None,
        "faltan_siguiente": gdd_hasta_siguiente(especie, ac["gdd"]) if ac else None,
        "hay_referencia": hay_referencia_gdd(especie),
        "integrales": filas,
    }
