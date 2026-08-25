# -*- coding: utf-8 -*-
"""
clima_era5.py
=============

MODULO OPCIONAL Y EXTRAIBLE. Trae el contexto climatico de ERA5-Land (ECMWF, via
Earth Engine) y lo deja en una tabla, junto a los indices del satelite.

Si borras este fichero, el programa sigue funcionando: desaparece la tarjeta de
clima de la ficha y no hay que tocar nada mas. La tabla `clima` se queda en la
base con lo ya descargado, por si lo vuelves a poner.

ESTE MODULO SOLO ENSENA DATOS: descarga el clima y lo pinta, no mueve ningun
diagnostico por si mismo. Quien SI usa estos numeros para el diagnostico es otro
modulo opcional aparte -`balance_hidrico` (contexto de sequia) y `grados_dia`
(fase por integral termica)-, para que ese salto se pueda quitar sin tocar la
descarga. Aqui la regla sigue siendo: bajar el dato y mostrarlo.

======================================================================
LO QUE HAY QUE SABER ANTES DE FIARSE DE ESTOS DATOS
======================================================================

1. EL PIXEL SON 11.132 m DE LADO, o sea 12.392 ha. Una parcela de 10 ha es el
   0,08 % de un solo pixel. Consecuencia: TODAS las parcelas en un radio de
   ~11 km reciben EXACTAMENTE el mismo dato. Esto no sirve para explicar por que
   una finca va peor que su vecina; sirve como contexto de comarca. Por eso los
   datos se guardan por PUNTO DE REJILLA y no por parcela: veinte parcelas del
   mismo pixel comparten una sola serie, que ademas es la verdad -no son veinte
   medidas, es una-.

2. VA CON UNOS DIAS DE RETRASO. Medido contra el catalogo: unos 8 dias. No puede
   explicar la pasada de esta semana; si la del mes pasado.

3. LAS UNIDADES NO SON LAS QUE UNO ESPERA, y aqui ya nos mordio una vez con las
   bandas de Sentinel-2. Verificadas en el STAC oficial de Earth Engine
   (ECMWF/ERA5_LAND/DAILY_AGGR):

       temperature_2m / _min / _max ........ K       -> °C   (restar 273.15)
       total_precipitation_sum ............. m       -> mm   (x 1000)
       potential_evaporation_sum ........... m       -> mm   (x 1000)
       surface_solar_radiation_downwards_sum J/m^2   -> MJ/m² (/ 1e6)
       volumetric_soil_water_layer_1 ....... fraccion-> %    (x 100)
       u/v_component_of_wind_10m ........... m/s     -> m/s  (modulo del vector)

   Una lluvia de 0.012 son DOCE MILIMETROS, no doce milesimas. Todas las
   conversiones viven en `CONVERSION`, en un solo sitio y con prueba de valores
   de oro, exactamente igual que `gee_cliente.ESCALA_SR`.

4. EL PROPIO CATALOGO AVISA de que las bandas acumuladas «pueden traer
   ocasionalmente valores negativos, que no tienen sentido fisico». Lluvia
   negativa, vamos. Se acota a cero al leer (ver `_positivo`).

5. LA EVAPORACION POTENCIAL DE ECMWF ES NEGATIVA por convenio de signo (el flujo
   se cuenta hacia abajo). Se guarda su valor ABSOLUTO, que es lo que un
   agricultor entiende por «se han ido 5 mm». Si algun dia se lee un pev positivo
   y grande, el signo no era el que creiamos: ver `_mm_evaporacion`.
"""

import math
from datetime import datetime, timedelta

import almacen as DB
from bitacora import log
from campanas import rango_campana

try:
    import ee                      # inyectable: las pruebas lo sustituyen
except Exception:
    ee = None


def hay_ee():
    return ee is not None


# =====================================================================
# La coleccion y sus bandas
# =====================================================================
COLECCION = "ECMWF/ERA5_LAND/DAILY_AGGR"
LADO_PIXEL_M = 11132                  # 0.1 grados; 12.392 ha por pixel
GRADOS_REJILLA = 0.1                  # el paso de la rejilla de ERA5-Land
DESFASE_TIPICO_DIAS = 8               # medido contra el catalogo

# (banda de ERA5, clave con la que se guarda, factor, sumando, decimales)
# El orden es el de la tabla que se ensena.
CONVERSION = [
    ("temperature_2m",                      "t_media",  1.0,   -273.15, 1),
    ("temperature_2m_min",                  "t_min",    1.0,   -273.15, 1),
    ("temperature_2m_max",                  "t_max",    1.0,   -273.15, 1),
    ("total_precipitation_sum",             "lluvia",   1000.0,   0.0,  1),
    ("potential_evaporation_sum",           "et0",      1000.0,   0.0,  1),
    ("surface_solar_radiation_downwards_sum", "rad",    1e-6,     0.0,  1),
    ("volumetric_soil_water_layer_1",       "hum_suelo", 100.0,   0.0,  1),
    ("dewpoint_temperature_2m",             "rocio",    1.0,   -273.15, 1),
]
# El viento no es una banda directa: son dos componentes y hay que componerlas.
BANDAS_VIENTO = ("u_component_of_wind_10m", "v_component_of_wind_10m")

BANDAS = [b for b, _c, _f, _s, _d in CONVERSION] + list(BANDAS_VIENTO)

# Columnas de la tabla que se pinta: (clave, titulo, ancho, decimales)
COLUMNAS = [("fecha", "FECHA", 88, None),
            ("t_media", "T MED °C", 70, 1), ("t_min", "T MIN °C", 70, 1),
            ("t_max", "T MAX °C", 70, 1),
            ("lluvia", "LLUVIA mm", 78, 1), ("et0", "ET0 mm", 68, 1),
            ("rad", "RAD MJ/m²", 78, 1), ("hum_suelo", "SUELO %", 68, 1),
            ("rocio", "ROCIO °C", 70, 1), ("viento", "VIENTO m/s", 78, 1)]

# Los que NO pueden ser negativos por fisica (ver el aviso del catalogo).
NO_NEGATIVOS = ("lluvia", "et0", "rad", "hum_suelo", "viento")


# =====================================================================
# Conversion de unidades (pura: se prueba sin red)
# =====================================================================
def _positivo(clave, valor):
    """Acota a cero lo que no puede ser negativo.

    El catalogo avisa de que las bandas acumuladas traen a veces valores
    negativos sin sentido fisico. Se corrigen en vez de ensenarlos: una lluvia de
    -0.3 mm no es un dato, es ruido del modelo."""
    if valor is None or clave not in NO_NEGATIVOS:
        return valor
    return max(0.0, valor)


def _mm_evaporacion(valor_m):
    """ET0 en mm a partir de los metros de ERA5.

    ECMWF cuenta la evaporacion potencial con signo NEGATIVO (flujo hacia abajo).
    Se devuelve el valor absoluto, que es lo que se entiende por «se han ido 5
    mm». Tomar el absoluto tambien deja bien el caso de que algun dia cambien el
    convenio."""
    if valor_m is None:
        return None
    return abs(valor_m) * 1000.0


def convertir(crudo):
    """De las bandas de ERA5 (K, m, J/m²) a unidades de campo (°C, mm, MJ/m²).

    `crudo` es {banda: valor} tal como lo devuelve Earth Engine. Devuelve el dict
    con las claves del programa. Lo que falte queda a None: un hueco es algo que
    el resto del programa sabe tratar, un cero inventado no."""
    fuera = {}
    for banda, clave, factor, sumando, dec in CONVERSION:
        v = (crudo or {}).get(banda)
        if v is None:
            fuera[clave] = None
            continue
        v = _mm_evaporacion(v) if clave == "et0" else v * factor + sumando
        fuera[clave] = round(_positivo(clave, v), dec)
    u, w = (crudo or {}).get(BANDAS_VIENTO[0]), (crudo or {}).get(BANDAS_VIENTO[1])
    # el viento es un VECTOR: su intensidad es el modulo, no la suma
    fuera["viento"] = None if u is None or w is None else round(math.hypot(u, w), 1)
    return fuera


def punto_de(coordenadas):
    """El punto de la rejilla de ERA5 al que cae una parcela: "lat,lon".

    Se redondea al paso de la rejilla (0.1°) a proposito: es la resolucion real
    del dato. Asi dos parcelas del mismo pixel comparten serie en vez de guardar
    dos copias de lo mismo, que ademas podrian no cuadrar entre si.

    OJO al mirar los resultados: justo en el borde entre dos celdas manda la
    representacion en coma flotante (41.65 / 0.1 vale 416.49999... y cae a 41.6,
    no a 41.7). No es un problema -esto es una CLAVE, no una medida, y para una
    misma coordenada siempre da lo mismo-, pero sorprende si se comprueba a mano.
    El texto sale siempre con un decimal limpio gracias al formato."""
    pts = [p for p in (coordenadas or []) if p and len(p) >= 2]
    if not pts:
        return None
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    r = GRADOS_REJILLA
    return f"{round(lat / r) * r:.1f},{round(lon / r) * r:.1f}"


# =====================================================================
# Resumen (puro)
# =====================================================================
def resumen(filas):
    """Totales de la serie: lo que un agricultor mira primero.

    La lluvia y la ET0 se SUMAN (son acumulados diarios); las temperaturas se
    promedian, y de las extremas interesa la mas extrema, no su media."""
    if not filas:
        return None
    def _vals(k):
        return [f[k] for f in filas if f.get(k) is not None]
    lluvia, et0 = _vals("lluvia"), _vals("et0")
    tmin, tmax, tmed = _vals("t_min"), _vals("t_max"), _vals("t_media")
    return {"dias": len(filas),
            "lluvia": round(sum(lluvia), 1) if lluvia else None,
            "et0": round(sum(et0), 1) if et0 else None,
            "balance": round(sum(lluvia) - sum(et0), 1) if lluvia and et0 else None,
            "t_media": round(sum(tmed) / len(tmed), 1) if tmed else None,
            "t_min": min(tmin) if tmin else None,
            "t_max": max(tmax) if tmax else None,
            "dias_helada": sum(1 for v in tmin if v <= 0.0)}


def texto_resumen(r):
    """Una linea con el contexto de la campana. Vacia si no hay datos."""
    if not r:
        return ""
    trozos = [f"{r['dias']} dias"]
    if r.get("lluvia") is not None:
        trozos.append(f"lluvia {r['lluvia']:.0f} mm")
    if r.get("et0") is not None:
        trozos.append(f"ET0 {r['et0']:.0f} mm")
    if r.get("balance") is not None:
        trozos.append(f"balance {r['balance']:+.0f} mm")
    if r.get("t_media") is not None:
        trozos.append(f"T media {r['t_media']:.1f} °C")
    if r.get("t_min") is not None and r.get("t_max") is not None:
        trozos.append(f"extremas {r['t_min']:.1f} / {r['t_max']:.1f} °C")
    if r.get("dias_helada"):
        trozos.append(f"{r['dias_helada']} dia(s) de helada")
    return "  ·  ".join(trozos)


def celda(valor, decimales):
    """Un numero de la tabla, con su formato. Sin dato, un guion."""
    if valor is None:
        return "-"
    if decimales is None:
        return str(valor)
    return f"{valor:.{decimales}f}"


def filas_tabla(registros):
    """La tabla de clima ya formateada, una fila por dia."""
    return [[celda(r.get(c), dec) for c, _t, _a, dec in COLUMNAS]
            for r in registros or []]


# =====================================================================
# Descarga
# =====================================================================
def sincronizar_clima(nombre, campana, silencioso=True):
    """Descarga los dias de esa campana que falten para el punto de la parcela.

    Devuelve (n_nuevos, mensaje). Es INCREMENTAL como la del satelite: mira hasta
    que dia hay guardado y pide desde el siguiente. Y es por PUNTO, asi que la
    segunda parcela de la misma comarca no descarga nada."""
    if not hay_ee():
        return (0, "earthengine-api no disponible")
    ficha = DB.ficha(nombre) or {}
    punto = punto_de(ficha.get("coordenadas"))
    if not punto:
        return (0, "parcela sin geometria")
    try:
        ini, fin = rango_campana(campana)
        hoy = datetime.now().strftime("%Y-%m-%d")
        # el dato va con retraso: pedir hasta hoy es pedir dias que no existen
        tope = (datetime.now() - timedelta(days=DESFASE_TIPICO_DIAS)).strftime("%Y-%m-%d")
        fin = min(fin, tope, hoy)
        ultima = DB.ultima_fecha_clima(punto)
        if ultima and ultima >= ini:
            ini = (datetime.strptime(ultima, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if ini > fin:
            return (0, "el clima ya esta al dia")

        lat, lon = (float(x) for x in punto.split(","))
        geom = ee.Geometry.Point([lon, lat])
        col = (ee.ImageCollection(COLECCION).filterDate(ini, fin).select(BANDAS)
               .sort("system:time_start", True))

        def feat(img):
            v = img.reduceRegion(ee.Reducer.first(), geom, scale=LADO_PIXEL_M)
            return ee.Feature(None, v.set("fecha", img.date().format("yyyy-MM-dd")))

        data = col.map(feat).getInfo()["features"]
        nuevos = []
        for f in data:
            p = f["properties"]
            fecha = p.get("fecha")
            if not fecha:
                continue
            fila = convertir(p)
            fila["fecha"] = fecha
            nuevos.append(fila)
        if not nuevos:
            return (0, "sin dias nuevos de clima")
        DB.anadir_clima(punto, nuevos)
        log.info("clima: %s dia(s) para el punto %s", len(nuevos), punto)
        return (len(nuevos), f"anadidos {len(nuevos)} dias de clima")
    except Exception as e:
        log.warning("clima: no se pudo descargar %s %s", nombre, campana, exc_info=True)
        if not silencioso:
            raise
        return (0, f"error: {e}")


def clima_de_parcela(nombre, campana):
    """Los dias de clima de esa parcela y campana, en orden. Lista vacia si no hay."""
    ficha = DB.ficha(nombre) or {}
    punto = punto_de(ficha.get("coordenadas"))
    if not punto:
        return []
    ini, fin = rango_campana(campana)
    return DB.clima(punto, ini, fin)


# =====================================================================
# Limpieza: un punto que ya no usa nadie no tiene por que quedarse
# =====================================================================
# El clima no es de una parcela, asi que no entra en el borrado en cascada de
# `eliminar_parcela` como las demas tablas. Pero si se borra la ultima parcela de
# una comarca, su serie se quedaria ahi para siempre. Este modulo se apunta al
# aviso de borrado de `almacen` y tira lo que sobra. Como todo lo de aqui, si se
# borra el fichero deja de pasar y no se rompe nada.
def _puntos_en_uso():
    """Los puntos de rejilla que siguen haciendo falta a alguna parcela."""
    return {p for p in (punto_de((DB.ficha(n) or {}).get("coordenadas"))
                        for n in DB.nombres()) if p}


def _al_borrar_parcela(_nombre=None):
    try:
        sobran = DB.purgar_clima(_puntos_en_uso())
        if sobran:
            log.info("clima: %s punto(s) de rejilla sin parcelas, retirados", sobran)
    except Exception:
        log.warning("clima: no se pudo purgar tras un borrado", exc_info=True)


DB.al_eliminar_parcela(_al_borrar_parcela)
