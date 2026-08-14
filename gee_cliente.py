# -*- coding: utf-8 -*-
"""
gee_cliente.py
==============

Todo el trato con Google Earth Engine: calculo de indices, sincronizacion
incremental de pasadas y descarga de los mapas (opticos y de radar).

Aislado del panel para que la descarga se pueda PROBAR SIN RED: el modulo `ee` es
inyectable. En las pruebas basta con sustituirlo por un doble:

    import gee_cliente as G
    G.ee = MiEeFalso()          # y, si hace falta, G.Image = ...
    G.sincronizar_parcela("Parcela", "2025-2026")

`hay_ee()` dice si Earth Engine esta disponible (o inyectado), y es lo que mira
`sincronizar_parcela` antes de intentar nada.

Aqui viven tambien las tablas de VISUALIZACION (rango y paleta por indice y por
parametro de radar). Estan en este modulo, y no en la interfaz, porque la propia
descarga las necesita para construir el thumbnail; el panel las reutiliza para
pintar la leyenda, de modo que ambos usan la MISMA fuente de verdad.
"""

import io
import math
from datetime import datetime, timedelta

import requests

import almacen as DB
import rejilla
from bitacora import log
from campanas import rango_campana
from sentinel1 import (cross_ratio_db, error_estandar, fiabilidad_radar,
                       rvi_incertidumbre)
from sincronizacion import ULTIMO_SYNC

try:
    import ee                      # inyectable: las pruebas lo sustituyen
except Exception:
    ee = None

try:
    from PIL import Image
    _PIL = True
except Exception:
    _PIL = False


def hay_ee():
    """True si Earth Engine esta disponible (instalado o inyectado en pruebas)."""
    return ee is not None


# =====================================================================
# INDICES: definicion, rangos y paletas
# =====================================================================
PAL_VEG = ['a50026', 'd73027', 'f46d43', 'fdae61', 'fee08b',
           'ffffbf', 'd9ef8b', 'a6d96a', '66bd63', '1a9850', '006837']
PAL_HUM = ['8c510a', 'bf812d', 'dfc27d', 'f6e8c3', 'f7f7f7',
           'c7eae5', '80cdc1', '35978f', '01665e']

INDICES = {
    "NDVI":  {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "EVI":   {"rango": (0.0, 1.0),  "paleta": PAL_VEG},
    "SAVI":  {"rango": (0.0, 1.0),  "paleta": PAL_VEG},
    "GNDVI": {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "LAI":   {"rango": (0.0, 6.0),  "paleta": PAL_VEG},
    "MSAVI": {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "NDMI":  {"rango": (-0.5, 0.5), "paleta": PAL_HUM},
}

INDICES_ORDEN = ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]

# --- visualizacion del radar (Sentinel-1) ---
RADAR_VIS = {
    "VV":  {"rango": (-25, 0),  "paleta": ["000000", "8a8a8a", "ffffff"]},
    "VH":  {"rango": (-30, -5), "paleta": ["000000", "8a8a8a", "ffffff"]},
    "RVI": {"rango": (0, 1),    "paleta": ["9c6b30", "d9d59b", "3a9d23", "0b6623"]},
}

MAX_PIXELES = 2048          # tope por lado, para no pedir imagenes gigantes a GEE

# Sesion HTTP compartida para las descargas de mapas. Reutiliza la conexion
# TCP/TLS con el servidor de Google en vez de renegociarla en cada peticion (cada
# mapa hace dos: fondo + capa del indice), asi el mapa aparece antes.
# CONTRATO: se configura aqui una sola vez y despues SOLO se llama a .get(); no se
# muta desde ningun sitio, que es lo que permite usarla desde varios hilos.
_HTTP = requests.Session()
_HTTP.headers.update({"User-Agent": "GestorParcelas/1.0"})


def dimensiones_para(coords, metros_px):
    """Tamano en pixeles del lado mayor para servir la parcela a `metros_px` m/pixel."""
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    lat0 = math.radians(sum(lats) / len(lats))
    ancho_m = (max(lons) - min(lons)) * 111320.0 * math.cos(lat0)
    alto_m = (max(lats) - min(lats)) * 110540.0
    lado_m = max(ancho_m, alto_m, 1.0)
    return int(max(64, min(MAX_PIXELES, round(lado_m / max(1, metros_px)))))


def construir_indice(img, indice):
    nir, red, green, blue = img.select("B8"), img.select("B4"), img.select("B3"), img.select("B2")
    if indice == "NDVI":
        return img.normalizedDifference(["B8", "B4"]).rename("IDX")
    if indice == "GNDVI":
        return img.normalizedDifference(["B8", "B3"]).rename("IDX")
    if indice == "NDMI":
        return img.normalizedDifference(["B8", "B11"]).rename("IDX")
    if indice == "SAVI":
        return img.expression("((NIR-RED)/(NIR+RED+0.5))*1.5", {"NIR": nir, "RED": red}).rename("IDX")
    if indice == "EVI":
        return img.expression("2.5*((NIR-RED)/(NIR+6.0*RED-7.5*BLUE+1.0))",
                              {"NIR": nir, "RED": red, "BLUE": blue}).rename("IDX")
    if indice == "MSAVI":
        return img.expression("(2*NIR+1-sqrt((2*NIR+1)**2-8*(NIR-RED)))/2",
                              {"NIR": nir, "RED": red}).rename("IDX")
    if indice == "LAI":
        evi = img.expression("2.5*((NIR-RED)/(NIR+6.0*RED-7.5*BLUE+1.0))",
                             {"NIR": nir, "RED": red, "BLUE": blue})
        return evi.expression("3.618*EVI-0.118", {"EVI": evi}).rename("IDX")
    return img.normalizedDifference(["B8", "B4"]).rename("IDX")


def descargar_mapa_indice(coords, iso, idx, metros, png_destino):
    """Descarga de GEE el mapa de un indice para un dia y lo guarda como PNG
    (fondo RGB natural + capa de color del indice). Devuelve el lado en pixeles.
    Reutilizable por la ficha y por la ventana de comparacion."""
    geom = ee.Geometry.Polygon(coords)
    region = geom.bounds()
    dim = dimensiones_para(coords, metros)
    d1 = (datetime.strptime(iso, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    img = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(geom).filterDate(iso, d1).first())
    fondo = img.visualize(bands=["B4", "B3", "B2"], min=0, max=3000).getThumbURL(
        {"region": region, "dimensions": dim, "format": "png"})
    fondo = Image.open(io.BytesIO(_HTTP.get(fondo, timeout=90).content)).convert("RGBA")
    rng = INDICES[idx]["rango"]
    ov = construir_indice(img, idx).clip(geom).visualize(
        min=rng[0], max=rng[1], palette=INDICES[idx]["paleta"]).getThumbURL(
        {"region": region, "dimensions": dim, "format": "png"})
    ov = Image.open(io.BytesIO(_HTTP.get(ov, timeout=90).content)).convert("RGBA")
    Image.alpha_composite(fondo, ov).save(png_destino)
    return dim


def imagen_param_radar(img, param):
    """Banda del parametro de radar pedido (VV, VH en dB, o RVI en lineal)."""
    vv, vh = img.select("VV"), img.select("VH")
    if param == "VH":
        return vh
    if param == "RVI":
        vvl = ee.Image(10).pow(vv.divide(10))
        vhl = ee.Image(10).pow(vh.divide(10))
        return vhl.multiply(4).divide(vvl.add(vhl)).rename("RVI")
    return vv


def descargar_mapa_radar(coords, iso, param, metros, png_destino):
    """Descarga de GEE el mapa de un parametro de Sentinel-1 para un dia y lo guarda
    como PNG. Devuelve el lado en pixeles."""
    geom = ee.Geometry.Polygon(coords)
    region = geom.bounds()
    dim = dimensiones_para(coords, metros)
    d1 = (datetime.strptime(iso, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    img = (ee.ImageCollection("COPERNICUS/S1_GRD")
           .filterBounds(geom).filterDate(iso, d1)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .first())
    vis = RADAR_VIS.get(param, RADAR_VIS["RVI"])
    ov = imagen_param_radar(img, param).clip(geom).visualize(
        min=vis["rango"][0], max=vis["rango"][1], palette=vis["paleta"]).getThumbURL(
        {"region": region, "dimensions": dim, "format": "png"})
    Image.open(io.BytesIO(_HTTP.get(ov, timeout=90).content)).convert("RGBA").save(png_destino)
    return dim


# =====================================================================
# REJILLA DE NDVI: el valor de CADA pixel, comparable entre fechas
# =====================================================================
# La media y los percentiles dicen QUE parte de la parcela va peor, pero no
# DONDE. La rejilla guarda el NDVI pixel a pixel. Para que sirva de algo, el
# pixel (i,j) tiene que ser el mismo trozo de terreno en todas las fechas:
#
#   - Se usa la RETICULA NATIVA de Sentinel-2, sin reproyectar ni remuestrear.
#     El rectangulo se encaja sobre bordes de pixel a partir del `transform` de
#     la propia imagen (ver rejilla.encajar).
#   - Se guarda la georreferenciacion (crs, escala, i0, j0, filas, columnas) con
#     los datos, y al leer se exige que coincida. Una parcela a caballo entre dos
#     husos UTM puede llegar en husos distintos segun la pasada; en ese caso la
#     comparacion se DESCARTA en vez de hacerse mal.
#   - Se guarda tambien la mascara de pixeles validos: un pixel tapado por nube
#     no es un pixel anomalo, y sin la mascara se confundirian.
#
# Buffer interior de 15 m para no meter pixeles de borde, mezclados con lindero o
# camino. Si el buffer deja la parcela por debajo de MIN_PIXELES_BUFFER, se
# guarda sin buffer y se marca, que es mejor que quedarse sin rejilla.
BUFFER_INTERIOR_M = 15
MIN_PIXELES_BUFFER = 20
# Tope de seguridad. Medido: una parcela de 5-10 ha ocupa 0.9-1.5 KB por pasada,
# y el tamano crece con la superficie. 60.000 pixeles son 600 ha, muy por encima
# de cualquier parcela real; sirve para que una geometria disparatada no llene la
# base ni reviente el limite de `sampleRectangle`.
MAX_PIXELES_REJILLA = 60000


def _dia_siguiente(iso):
    return (datetime.strptime(iso, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _info_rejilla(geom, col):
    """Proyeccion nativa y geometria de trabajo. Dos viajes a Earth Engine.

    Devuelve (crs, transform, esquinas, sin_buffer) o None si no se puede."""
    proj = ee.Image(col.first()).select("B4").projection().getInfo()
    crs, transform = proj.get("crs"), proj.get("transform")
    if not crs or not transform:
        return None
    geom_buf = geom.buffer(-BUFFER_INTERIOR_M)
    areas = ee.Dictionary({"buf": geom_buf.area(1), "todo": geom.area(1)}).getInfo()
    lado = abs(float(transform[0])) or 10.0
    # el buffer puede dejar la parcela en nada (parcelas estrechas o pequenas)
    sin_buffer = (areas.get("buf") or 0) / (lado * lado) < MIN_PIXELES_BUFFER
    usada = geom if sin_buffer else geom_buf
    esquinas = usada.transform(crs, 1).bounds().coordinates().getInfo()[0]
    return crs, transform, esquinas, sin_buffer, usada


def _descargar_rejillas(nombre, campana, geom, fechas):
    """Descarga y guarda la rejilla de NDVI de esas fechas. Devuelve cuantas.

    Se llama DESPUES de guardar las pasadas y va en su propio try: la rejilla es
    un extra, y si Earth Engine la niega no puede costarnos los datos buenos.
    """
    if not fechas:
        return 0
    # Ventana justa que cubre las fechas pedidas. Puede colarse alguna imagen de
    # por medio que no se queria: se descarta abajo, al comprobar la fecha. Es mas
    # simple y mucho mas robusto que componer un filtro por cada dia.
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(geom)
           .filterDate(min(fechas), _dia_siguiente(max(fechas)))
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
           .sort("system:time_start", True))
    info = _info_rejilla(geom, col)
    if not info:
        log.warning("rejilla: sin proyeccion utilizable en %s %s", nombre, campana)
        return 0
    crs, transform, esquinas, sin_buffer, geom_uso = info
    i0, j0, filas, columnas, rect = rejilla.encajar(esquinas, transform)
    if filas * columnas > MAX_PIXELES_REJILLA:
        log.warning("rejilla: %s ocupa %sx%s pixeles, por encima del tope; se omite",
                    nombre, filas, columnas)
        return 0

    lado = abs(float(transform[0]))
    region = ee.Geometry.Rectangle(rect, crs, False, False)

    def con_rejilla(img):
        # MISMO enmascarado SCL que usa la sincronizacion: si aqui se filtrara
        # distinto, la rejilla y la estadistica hablarian de pixeles distintos.
        scl = img.select("SCL")
        ok = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
        ndvi = img.updateMask(ok).normalizedDifference(["B8", "B4"]).clip(geom_uso)
        valido = ndvi.mask().rename("valido")
        par = ndvi.unmask(0).rename("ndvi").addBands(valido.unmask(0))
        muestra = par.sampleRectangle(region=region, defaultValue=0)
        return ee.Feature(None, {"fecha": img.date().format("yyyy-MM-dd"),
                                 "crs": img.select("B4").projection().crs(),
                                 "ndvi": muestra.get("ndvi"),
                                 "valido": muestra.get("valido")})

    datos = col.map(con_rejilla).getInfo()["features"]
    geo = {"crs": crs, "escala": lado, "i0": i0, "j0": j0,
           "filas": filas, "columnas": columnas}
    guardadas = 0
    for f in datos:
        p = f.get("properties") or {}
        fecha = p.get("fecha")
        if not fecha or fecha not in fechas:
            continue
        # una pasada que llega en OTRO huso no comparte reticula: no se guarda
        # georreferenciada con la de las demas, que seria mentir sobre donde esta
        if p.get("crs") and p["crs"] != crs:
            log.warning("rejilla: %s %s llega en %s y no en %s; se omite esa fecha",
                        nombre, fecha, p["crs"], crs)
            continue
        plano = rejilla.desde_arrays(p.get("ndvi"), p.get("valido"), filas, columnas)
        if not plano:
            log.warning("rejilla: %s %s devuelve una matriz de otra forma; se omite",
                        nombre, fecha)
            continue
        valores, validos = plano
        DB.guardar_rejilla(nombre, campana, fecha,
                           rejilla.codificar(valores, validos, geo, sin_buffer=sin_buffer,
                                             buffer_m=0 if sin_buffer else BUFFER_INTERIOR_M))
        guardadas += 1
    return guardadas


def sincronizar_parcela(nombre, campana, silencioso=True):
    """
    Sincronizacion INCREMENTAL: mira hasta que fecha hay datos guardados y solo
    descarga las pasadas nuevas del satelite con nubosidad < 20 %, sin sobrescribir.
    Devuelve (n_nuevos, mensaje).
    """
    if not hay_ee():
        ULTIMO_SYNC.update(estado="fallo", msg="earthengine-api no disponible")
        return (0, "earthengine-api no disponible")
    try:
        ficha = DB.ficha(nombre)
        if not ficha or not ficha.get("coordenadas"):
            return (0, "parcela sin geometria")

        geom = ee.Geometry.Polygon(ficha["coordenadas"])
        ini_camp, fin_camp = rango_campana(campana)

        ultima = DB.ultima_fecha(nombre, campana)      # MAX(fecha) via SQLite (indexado)
        fechas_existentes = {p["fecha"] for p in DB.pasadas(nombre, campana) if p.get("fecha")}

        # ventana incremental: desde el dia siguiente a la ultima fecha guardada
        try:
            inicio = ((datetime.strptime(ultima, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                      if ultima else ini_camp)
        except ValueError:                    # fecha guardada mal formada: re-escanea la campana
            inicio = ini_camp
        hoy = datetime.now().strftime("%Y-%m-%d")
        fin = min(fin_camp, hoy)
        if inicio > fin:
            return (0, "ya esta al dia")

        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
               .filterBounds(geom).filterDate(inicio, fin)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))   # prefiltro amplio;
               .sort("system:time_start", True))                       # el SCL decide de verdad

        def feat(img):
            # --- 1. ENMASCARADO DE NUBES CON SCL (por pixel, no por escena) ---
            # La banda SCL clasifica cada pixel. Nos quedamos solo con lo utilizable:
            #   4 = vegetacion, 5 = suelo desnudo, 6 = agua, 7 = nube baja probabilidad,
            #   11 = nieve/hielo.  Se DESCARTAN:
            #   0 = sin dato, 1 = saturado/defectuoso, 2 = sombra oscura, 3 = sombra de nube,
            #   8 = nube media prob., 9 = nube alta prob., 10 = cirros.
            scl = img.select("SCL")
            valido = (scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7)))
            img_m = img.updateMask(valido)

            comp = img_m
            for k in INDICES_ORDEN:
                comp = comp.addBands(construir_indice(img_m, k).rename(k))

            # --- 2. COBERTURA VALIDA DENTRO DE LA PARCELA ---
            # Fraccion de pixeles de la parcela que sobreviven al enmascarado.
            # Es la nubosidad REAL sobre la finca, no la de la escena entera.
            cobertura = (valido.rename("OK").unmask(0)
                         .reduceRegion(ee.Reducer.mean(), geom, scale=10, bestEffort=True)
                         .get("OK"))

            # --- 3. ESTADISTICA INTRAPARCELA: media + desviacion + percentiles ---
            # La media sola oculta la heterogeneidad. Con la desviacion y los percentiles
            # se detecta si una PARTE de la parcela va mucho peor que el resto.
            reductor = (ee.Reducer.mean()
                        .combine(ee.Reducer.stdDev(), sharedInputs=True)
                        .combine(ee.Reducer.percentile([10, 25, 50, 75, 90]), sharedInputs=True)
                        .combine(ee.Reducer.count(), sharedInputs=True))
            m = comp.reduceRegion(reductor, geom, scale=10, bestEffort=True)

            props = {"fecha": img.date().format("yyyy-MM-dd"),
                     "cobertura_valida": cobertura}
            for k in INDICES_ORDEN:
                props[k.lower()] = m.get(k + "_mean")
            # estadistica espacial completa solo del NDVI (es el indice de referencia)
            props["ndvi_std"] = m.get("NDVI_stdDev")
            props["ndvi_p10"] = m.get("NDVI_p10")
            props["ndvi_p25"] = m.get("NDVI_p25")
            props["ndvi_p50"] = m.get("NDVI_p50")
            props["ndvi_p75"] = m.get("NDVI_p75")
            props["ndvi_p90"] = m.get("NDVI_p90")
            props["n_pixeles"] = m.get("NDVI_count")
            return ee.Feature(None, props)

        data = col.map(feat).getInfo()["features"]
        # el getInfo ha ido bien -> la conexion con GEE funciona
        ULTIMO_SYNC.update(estado="ok", msg="conexion con GEE correcta")

        # --- 4. FILTRO DE VALIDEZ POR PARCELA (no por escena) ---
        # Se acepta la pasada solo si al menos el 80 % de los pixeles de la parcela
        # son validos tras el SCL (es decir, <20 % de nube/sombra SOBRE LA FINCA).
        nuevos, descartadas = [], 0
        for f in data:
            p = f["properties"]
            fecha = p.get("fecha")
            cob = p.get("cobertura_valida")
            if not fecha or fecha in fechas_existentes:
                continue
            if cob is None or cob < 0.80 or not p.get("ndvi"):
                descartadas += 1
                continue
            p["cobertura_valida"] = round(cob, 3)
            nuevos.append(p)

        if not nuevos:
            msg = "sin pasadas nuevas fiables"
            if descartadas:
                msg += f" ({descartadas} descartadas por nube/sombra sobre la parcela)"
            return (0, msg)

        # INSERT OR IGNORE: anade solo las fechas nuevas y conserva las existentes
        # (con su interpretacion). Es atomico y no pisa lo que otro hilo guardara.
        DB.anadir_pasadas(nombre, campana, nuevos)

        # La rejilla va DESPUES y en su propio try: es un extra, y si Earth Engine
        # la niega no puede costarnos las pasadas, que son el dato de verdad. El
        # mensaje que ve el usuario no cambia; lo que pase aqui va a la bitacora.
        try:
            n_rej = _descargar_rejillas(nombre, campana, geom,
                                        sorted(p["fecha"] for p in nuevos))
            if n_rej:
                log.info("rejilla: %s %s, %s fecha(s) guardadas", nombre, campana, n_rej)
        except Exception:
            log.warning("rejilla: no se pudo descargar en %s %s (las pasadas si estan)",
                        nombre, campana, exc_info=True)

        return (len(nuevos), f"anadidas {len(nuevos)} fechas nuevas")
    except Exception as e:
        ULTIMO_SYNC.update(estado="fallo", msg=f"{e}")
        if not silencioso:
            raise
        return (0, f"error: {e}")


# =====================================================================
# SENTINEL-1 (RADAR): descarga incremental de pasadas
# =====================================================================
# El calculo y la interpretacion del radar viven en sentinel1 (modulo puro);
# aqui solo esta la parte que habla con Earth Engine.
# =====================================================================
def sincronizar_radar(nombre, campana, silencioso=True):
    """
    Descarga INCREMENTAL de Sentinel-1 (VV/VH) sobre la parcela y guarda VV, VH,
    RVI y CR por pasada. Devuelve (n_nuevos, mensaje). SOLO se llama desde el boton.
    """
    if not hay_ee():
        return (0, "earthengine-api no disponible")
    try:
        ficha = DB.ficha(nombre)
        if not ficha or not ficha.get("coordenadas"):
            return (0, "parcela sin geometria")

        geom = ee.Geometry.Polygon(ficha["coordenadas"])
        ini_camp, fin_camp = rango_campana(campana)
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

        # media + desviacion espacial + nº de pixeles (para la incertidumbre)
        reductor = (ee.Reducer.mean()
                    .combine(ee.Reducer.stdDev(), sharedInputs=True)
                    .combine(ee.Reducer.count(), sharedInputs=True))

        def feat(img):
            m = img.reduceRegion(reductor, geom, scale=10, bestEffort=True)
            return ee.Feature(None, {"fecha": img.date().format("yyyy-MM-dd"),
                                     "vv": m.get("VV_mean"), "vh": m.get("VH_mean"),
                                     "vv_std": m.get("VV_stdDev"), "vh_std": m.get("VH_stdDev"),
                                     "n": m.get("VV_count"),
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
            vv_std, vh_std = p.get("vv_std"), p.get("vh_std")
            n = int(p["n"]) if p.get("n") is not None else None
            vv_e = error_estandar(vv_std, n)
            vh_e = error_estandar(vh_std, n)
            rv, rlo, rhi = rvi_incertidumbre(vv, vh, vv_e, vh_e)
            nuevos.append({"fecha": fecha, "vv": round(vv, 2), "vh": round(vh, 2),
                           "vv_std": round(vv_std, 2) if vv_std is not None else None,
                           "vh_std": round(vh_std, 2) if vh_std is not None else None,
                           "n_pixeles": n, "rvi": rv, "rvi_lo": rlo, "rvi_hi": rhi,
                           "cr": cross_ratio_db(vv, vh),
                           "fiabilidad": fiabilidad_radar(n, vv_std, vh_std),
                           "orbita": p.get("orbita")})

        if not nuevos:
            return (0, "sin pasadas de radar nuevas")
        DB.anadir_radar(nombre, campana, nuevos)
        return (len(nuevos), f"anadidas {len(nuevos)} pasadas de radar")
    except Exception as e:
        if not silencioso:
            raise
        return (0, f"error: {e}")
