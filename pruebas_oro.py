# -*- coding: utf-8 -*-
"""
pruebas_oro.py
==============

FICHERO DE ORO de `interpretacion_fenologica.evaluar_parcela`.

Para que sirve
--------------
`pruebas.py` comprueba VEREDICTOS: que tal entrada da «Vigilar». Eso no basta para
refactorizar el motor, porque dos caminos distintos que acaben los dos en
«Vigilar» son indistinguibles para esa suite. Aqui se congela la salida COMPLETA
-incluido el `motivo`, que es el texto que lee el agricultor- de un barrido de
entradas, y se compara byte a byte contra `oro_evaluar_parcela.json`.

Asi, al reordenar el motor, cualquier cambio de comportamiento salta con nombre y
apellidos: que caso, que entrada, que decia antes y que dice ahora.

Que congela
-----------
De cada caso se guarda:
  - lo que manda el semaforo: `clave`, `estado`, `esperado`;
  - lo que explica la decision: `fase`, `rango_fase`, `ndvi_juicio`, `umbrales`;
  - lo que LEE el usuario: `motivo`, los textos de `deltas`, el veredicto de
    cubierta/copa en lenosos y la lectura de heterogeneidad.

NO se guardan `fecha` (es un eco de la entrada) ni los numeros internos de
`copa["contrastes"]` (aritmetica derivada de la entrada, que ya queda cubierta por
el veredicto que produce). Si un refactor cambiase esa aritmetica sin cambiar el
veredicto ni el texto, este fichero no lo veria: es una limitacion consciente, a
cambio de un fichero que se puede leer en un diff.

Reglas de la casa
-----------------
- DETERMINISTA: sin red, sin base de datos, sin azar y **sin depender de la fecha
  de hoy**. Todas las fechas son absolutas y `parcela=None` en todas las llamadas
  (asi tampoco entra `calibracion_umbrales`, que aprende de la base).
- Las fronteras de fase NO se escriben a mano: se calculan de las tablas de
  `fenologia_especies`. Si manana se ajusta una fase, el barrido la sigue sola.
- El fichero de oro **no se regenera solo, nunca**. Si la suite falla, es que el
  comportamiento ha cambiado: o el cambio es un error, o es deliberado y entonces
  se regenera A MANO y se revisa el diff:

      python pruebas_oro.py --regenerar

  El diff de ese fichero es la lista exacta de veredictos que cambian, y tiene que
  entrar en la revision del cambio como el codigo.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import fenologia_especies as FEN
from interpretacion_fenologica import evaluar_parcela

RUTA_ORO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "oro_evaluar_parcela.json")

# Fechas de siembra FIJAS. Un cultivo de otono y otro de primavera, para que los
# dias desde siembra caigan en meses distintos y se ejerciten los dos calendarios.
SIEMBRA_OTONO = "2025-10-15"
SIEMBRA_PRIMAVERA = "2026-04-01"

# Ano de referencia para los lenosos, que van por MES y no por dias desde siembra.
ANO_LENOSO = 2026


# =====================================================================
# Ayudantes
# =====================================================================
def _iso(siembra, das):
    """Fecha ISO a `das` dias de la siembra. Las fronteras de fase se expresan en
    dias desde siembra, asi que asi se cae exactamente donde se quiere."""
    return (datetime.strptime(siembra, "%Y-%m-%d") + timedelta(days=das)).strftime("%Y-%m-%d")


def _siembra_de(info):
    return SIEMBRA_OTONO if info.get("siembra") == "otono" else SIEMBRA_PRIMAVERA


def _niveles_ndvi(lo, hi):
    """Los cuatro niveles que importan de un rango de fase, en este orden:
    muy por debajo del suelo del rango, en la zona de aviso, dentro, y por encima
    del techo. Redondeados a tres decimales para que el caso tenga nombre estable.
    """
    return [("bajo", round(lo * 0.8 - 0.02, 3)),
            ("aviso", round((lo * 0.8 + lo) / 2, 3)),
            ("dentro", round((lo + hi) / 2, 3)),
            ("alto", round(hi + 0.05, 3))]


def _pasada(fecha, ndvi, ndmi=0.20, lai=2.5, msavi=None, extra=None):
    """Una pasada con los indices que mira el motor. `msavi` solo hace falta en
    lenosos, donde es el indice que juzga la copa."""
    r = {"fecha": fecha, "ndvi": ndvi, "ndmi": ndmi, "lai": lai}
    if msavi is not None:
        r["msavi"] = msavi
    if extra:
        r.update(extra)
    return r


# =====================================================================
# Generacion de casos
# =====================================================================
def _casos_extensivo():
    """Rejilla por especie x fase x fecha x nivel de NDVI x NDMI.

    Las fases y sus rangos salen de `EXTENSIVO_ESPECIES`; los dias de cada fase,
    de sus propios limites. Nada escrito a mano."""
    for especie in sorted(FEN.EXTENSIVO_ESPECIES):
        info = FEN.EXTENSIVO_ESPECIES[especie]
        siembra = _siembra_de(info)
        for (d0, d1, nombre, lo, hi, _caida, extra) in info["fases"]:
            ndmi_min = (extra or {}).get("ndmi_min")
            # dos fechas por fase: su primer dia (frontera) y su mitad
            for et_dia, das in (("ini", d0), ("med", (d0 + d1) // 2)):
                for et_ndvi, ndvi in _niveles_ndvi(lo, hi):
                    # NDMI por encima y por debajo del minimo de la fase; donde la
                    # fase no exige NDMI, se prueba con dato y sin dato
                    if ndmi_min is None:
                        ndmis = [("nd_dato", 0.20), ("nd_none", None)]
                    else:
                        ndmis = [("nd_alto", round(ndmi_min + 0.10, 3)),
                                 ("nd_bajo", round(ndmi_min - 0.05, 3))]
                    for et_ndmi, ndmi in ndmis:
                        cid = (f"EXT|COSECHA_GRANO|{especie}|{nombre}|{et_dia}"
                               f"|{et_ndvi}|{et_ndmi}")
                        yield cid, dict(
                            tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                            serie=[_pasada(_iso(siembra, das), ndvi, ndmi)],
                            spec={"especie": especie, "fecha_siembra": siembra})


def _casos_fronteras_extensivo():
    """El dia ANTES, el dia EXACTO y el dia DESPUES de cada cambio de fase.

    Es donde un refactor se equivoca de `<` por `<=` sin que la rejilla de arriba
    lo note. El NDVI se deja dentro del rango a proposito: aqui se mira la fase
    resuelta, no el juicio del indice."""
    for especie in sorted(FEN.EXTENSIVO_ESPECIES):
        info = FEN.EXTENSIVO_ESPECIES[especie]
        siembra = _siembra_de(info)
        for (d0, d1, nombre, lo, hi, _caida, _extra) in info["fases"]:
            for et, das in (("d0-1", d0 - 1), ("d0", d0), ("d0+1", d0 + 1),
                            ("d1-1", d1 - 1), ("d1", d1)):
                if das < 0:
                    continue
                cid = f"FRONT|{especie}|{nombre}|{et}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                    serie=[_pasada(_iso(siembra, das), round((lo + hi) / 2, 3))],
                    spec={"especie": especie, "fecha_siembra": siembra})


def _casos_umbrales_extensivo():
    """NDVI pegado a los cortes: `lo*0.8`, `lo` y `hi`, un pelo por debajo, justo
    encima y justo encima+.

    Sin este bloque la red tiene un agujero grande. Comprobado: mover el factor de
    aviso de 0.8 a 0.85 solo movia 10 casos de la rejilla ancha, porque sus niveles
    caen lejos del corte. Con estos, un cambio de umbral se ve entero.

    Se fija una sola fecha (la mitad de la fase) y un solo NDMI: aqui se mira el
    JUICIO del indice, no la fase ni el agua."""
    EPS = 0.005
    for especie in sorted(FEN.EXTENSIVO_ESPECIES):
        info = FEN.EXTENSIVO_ESPECIES[especie]
        siembra = _siembra_de(info)
        for (d0, d1, nombre, lo, hi, _caida, _extra) in info["fases"]:
            fecha = _iso(siembra, (d0 + d1) // 2)
            cortes = (("aviso", lo * 0.8), ("lo", lo), ("hi", hi))
            for et_corte, corte in cortes:
                for et_lado, v in (("-eps", corte - EPS), ("=", corte),
                                   ("+eps", corte + EPS)):
                    cid = f"UMBRAL|{especie}|{nombre}|{et_corte}{et_lado}"
                    yield cid, dict(
                        tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                        serie=[_pasada(fecha, round(v, 4))],
                        spec={"especie": especie, "fecha_siembra": siembra})


def _casos_umbrales_lenoso():
    """Lo mismo en lenosos, donde el que juzga es el MSAVI y no el NDVI.

    El MSAVI se mueve pegado al corte y el NDVI se deja fijo, para que quede claro
    cual de los dos manda: si un refactor cambiase el indice de juicio, estos casos
    lo cantan."""
    EPS = 0.005
    for especie in sorted(FEN.LENOSO_ESPECIES):
        for mes in (3, 6, 10):
            lo, hi, _c = FEN.LENOSO_ESPECIES[especie]["mes"][mes]
            for et_corte, corte in (("aviso", lo * 0.8), ("lo", lo), ("hi", hi)):
                for et_lado, v in (("-eps", corte - EPS), ("=", corte),
                                   ("+eps", corte + EPS)):
                    cid = f"UMBRALLEN|{especie}|m{mes:02d}|{et_corte}{et_lado}"
                    yield cid, dict(
                        tipo="LENOSO", subtipo="TRADICIONAL",
                        serie=[_pasada(f"{ANO_LENOSO}-{mes:02d}-15", 0.55,
                                       msavi=round(v, 4))],
                        spec={"especie": especie, "marco_calle": 10, "marco_pie": 10})


def _casos_umbrales_ndmi():
    """NDMI pegado a su minimo de fase, que es el otro corte del motor.

    Solo en las fases que declaran `ndmi_min`: donde no lo hay, no hay corte que
    rozar."""
    EPS = 0.005
    for especie in sorted(FEN.EXTENSIVO_ESPECIES):
        info = FEN.EXTENSIVO_ESPECIES[especie]
        siembra = _siembra_de(info)
        for (d0, d1, nombre, lo, hi, _caida, extra) in info["fases"]:
            ndmi_min = (extra or {}).get("ndmi_min")
            if ndmi_min is None:
                continue
            fecha = _iso(siembra, (d0 + d1) // 2)
            for et_lado, v in (("-eps", ndmi_min - EPS), ("=", ndmi_min),
                               ("+eps", ndmi_min + EPS)):
                cid = f"UMBRALNDMI|{especie}|{nombre}|{et_lado}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                    serie=[_pasada(fecha, round((lo + hi) / 2, 3), ndmi=round(v, 4))],
                    spec={"especie": especie, "fecha_siembra": siembra})


def _casos_siega_verde():
    """Forraje segado en verde y PRADERA: no siguen la fenologia del grano, van por
    ciclo de cortes. Se recorre el ano por meses."""
    especies = ["VEZA", "MAIZ", FEN.PRADERA]
    for especie in especies:
        for mes in (1, 4, 6, 9, 11):
            fecha = f"{ANO_LENOSO}-{mes:02d}-15"
            for et_ndvi, ndvi in (("bajo", 0.15), ("medio", 0.45), ("alto", 0.85)):
                cid = f"EXT|SIEGA_VERDE|{especie}|m{mes:02d}|{et_ndvi}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="SIEGA_VERDE",
                    serie=[_pasada(fecha, ndvi)],
                    spec={"especie": especie, "fecha_siembra": SIEMBRA_OTONO})


def _casos_segado():
    """Corte de forraje: caida drastica del NDVI en abril-mayo.

    Es un estado propio («Segado») y una de las pocas reglas que MADRUGA sobre todo
    lo demas, asi que hay que congelarla con sus dos fronteras: el mes en el que
    aplica y el tamano de la caida. Los meses de fuera del corte (marzo, junio) van
    a proposito, para que quede grabado que ahi la misma caida NO es un corte."""
    especies = ["VEZA", "MAIZ", FEN.PRADERA]
    caidas = {"corta_mucho": (0.75, 0.25), "corta_justo": (0.75, 0.59),
              "baja_poco": (0.75, 0.70), "sube": (0.40, 0.60)}
    for especie in especies:
        for mes in (3, 4, 5, 6):
            for et, (antes, ahora) in sorted(caidas.items()):
                serie = [_pasada(f"{ANO_LENOSO}-{mes:02d}-01", antes),
                         _pasada(f"{ANO_LENOSO}-{mes:02d}-15", ahora)]
                cid = f"SEGADO|{especie}|m{mes:02d}|{et}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="SIEGA_VERDE", serie=serie,
                    spec={"especie": especie, "fecha_siembra": SIEMBRA_OTONO})
    # el mismo corte declarado como grano: NO debe leerse como siega
    yield "SEGADO|comoGrano|m04|corta_mucho", dict(
        tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
        serie=[_pasada(f"{ANO_LENOSO}-04-01", 0.75),
               _pasada(f"{ANO_LENOSO}-04-15", 0.25)],
        spec={"especie": "VEZA", "fecha_siembra": SIEMBRA_OTONO})


def _casos_lenoso_series():
    """Lenosos con dos pasadas: los deltas y la caida propia de la fase.

    En un caducifolio, que el NDVI se desplome en otono es lo normal; en un
    perennifolio, no. Ese contraste tiene que quedar congelado."""
    for especie in sorted(FEN.LENOSO_ESPECIES):
        for m0, m1 in ((9, 10), (10, 11), (5, 6)):
            for et, (a, b) in (("cae", (0.60, 0.25)), ("plana", (0.50, 0.50)),
                               ("sube", (0.30, 0.55))):
                serie = [_pasada(f"{ANO_LENOSO}-{m0:02d}-15", a, msavi=round(a * 0.85, 3)),
                         _pasada(f"{ANO_LENOSO}-{m1:02d}-15", b, msavi=round(b * 0.85, 3))]
                cid = f"LENSERIE|{especie}|m{m0:02d}-{m1:02d}|{et}"
                yield cid, dict(
                    tipo="LENOSO", subtipo="TRADICIONAL", serie=serie,
                    spec={"especie": especie, "marco_calle": 10, "marco_pie": 10})


def _casos_lenoso():
    """Lenosos: especie x fase (un mes por fase) x densidad x regimen x NDVI.

    Los meses salen de `FASES_LENOSO`, uno por fase distinta. Las densidades se
    eligen para caer en cada tramo de la tabla `dens` de la especie, calculando el
    marco que las produce en vez de escribirlo a mano."""
    marcos = {"TRADICIONAL": (10, 10), "INTENSIVO": (6, 4), "SUPERINTENSIVO": (4, 1.5)}
    for especie in sorted(FEN.LENOSO_ESPECIES):
        tabla = FEN.FASES_LENOSO.get(especie, {})
        vistas, meses = set(), []
        for m in range(1, 13):                 # un mes por fase distinta, en orden
            f = tabla.get(m)
            if f and f not in vistas:
                vistas.add(f)
                meses.append((m, f))
        for mes, fase in meses:
            lo, hi, _caduco = FEN.LENOSO_ESPECIES[especie]["mes"][mes]
            for sub, (calle, pie) in sorted(marcos.items()):
                for regimen in ("REGADIO", "SECANO", None):
                    for et_ndvi, ndvi in (("bajo", round(lo * 0.7, 3)),
                                          ("dentro", round((lo + hi) / 2, 3))):
                        spec = {"especie": especie, "marco_calle": calle,
                                "marco_pie": pie}
                        if regimen:
                            spec["regimen"] = regimen
                        cid = (f"LEN|{sub}|{especie}|{fase}|m{mes:02d}"
                               f"|{et_ndvi}|reg{regimen or 'NC'}")
                        yield cid, dict(
                            tipo="LENOSO", subtipo=sub,
                            serie=[_pasada(f"{ANO_LENOSO}-{mes:02d}-15", ndvi,
                                           msavi=round(ndvi * 0.85, 3))],
                            spec=spec)


def _casos_lenoso_marco():
    """Marco y diametro de copa: declarados, a medias y sin declarar.

    Sin marco, el motor no puede repartir copa y calle; con diametro de copa lo
    sabe en vez de estimarlo. Son los tres caminos que hay que congelar."""
    variantes = [
        ("sin_marco", {}),
        ("solo_calle", {"marco_calle": 7}),
        ("marco", {"marco_calle": 7, "marco_pie": 5}),
        ("marco_diam", {"marco_calle": 7, "marco_pie": 5, "diametro_copa": 3.5}),
        ("marco_diam_grande", {"marco_calle": 7, "marco_pie": 5, "diametro_copa": 6.0}),
    ]
    for especie in sorted(FEN.LENOSO_ESPECIES):
        for mes in (3, 6, 11):
            for et, campos in variantes:
                for et_ndvi, ndvi in (("bajo", 0.20), ("dentro", 0.55)):
                    spec = {"especie": especie}
                    spec.update(campos)
                    cid = f"LENMARCO|{especie}|m{mes:02d}|{et}|{et_ndvi}"
                    yield cid, dict(
                        tipo="LENOSO", subtipo="",
                        serie=[_pasada(f"{ANO_LENOSO}-{mes:02d}-15", ndvi,
                                       msavi=round(ndvi * 0.85, 3))],
                        spec=spec)


def _casos_series():
    """Series de 1, 2 y 4 pasadas, con la ultima subiendo, plana o cayendo.

    Ejercita los deltas y la deteccion de caida: con una sola pasada no hay delta
    que calcular, y ese camino tambien tiene que quedar congelado."""
    base = [("TRIGO", SIEMBRA_OTONO, 140), ("MAIZ", SIEMBRA_PRIMAVERA, 70)]
    formas = {"sube": (0.35, 0.45, 0.55, 0.70), "plana": (0.55, 0.55, 0.55, 0.55),
              "cae_poco": (0.70, 0.68, 0.65, 0.60), "cae_mucho": (0.75, 0.72, 0.70, 0.35)}
    for especie, siembra, das in base:
        for forma, valores in sorted(formas.items()):
            for n in (1, 2, 4):
                serie = []
                for k in range(n):
                    # las pasadas van hacia atras desde `das`, cada 12 dias
                    dias = das - 12 * (n - 1 - k)
                    serie.append(_pasada(_iso(siembra, dias), valores[4 - n + k]))
                cid = f"SERIE|{especie}|{forma}|n{n}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=serie,
                    spec={"especie": especie, "fecha_siembra": siembra})


def _casos_eventos():
    """Eventos del cuaderno cerca de una caida: siega, cosecha y herbicida.

    Un evento registrado EXPLICA una caida que si no seria una alarma. Se prueban
    varias distancias en dias, incluida una fuera de la ventana."""
    serie_cae = [_pasada(_iso(SIEMBRA_OTONO, 128), 0.75),
                 _pasada(_iso(SIEMBRA_OTONO, 140), 0.30)]
    for tipo_ev, objetivo in (("SIEGA", None), ("COSECHA", None),
                              ("PRODUCTO", "herbicida (malas hierbas)"),
                              ("PRODUCTO", "abono / fertilizante"),
                              ("RIEGO", None)):
        for dias in (0, 3, 15, 25):
            ev = {"tipo": tipo_ev, "fecha": _iso(SIEMBRA_OTONO, 140 - dias)}
            if objetivo:
                ev["objetivo"] = objetivo
            et = f"{tipo_ev}{'-' + objetivo.split()[0] if objetivo else ''}"
            cid = f"EVENTO|{et}|d{dias:02d}"
            yield cid, dict(
                tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=serie_cae,
                spec={"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO},
                eventos_cerca=[(dias, ev)])
    # sin eventos: la misma caida, para poder comparar
    yield "EVENTO|ninguno|-", dict(
        tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=serie_cae,
        spec={"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO})


def _casos_heterogeneidad():
    """Con y sin estadistica espacial, y con el juicio de zonas apagado.

    `heterogeneidad_activa=False` no quita el dato: quita el JUICIO. Las dos ramas
    tienen que quedar congeladas."""
    espacial = {"ndvi_std": 0.14, "ndvi_p10": 0.30, "ndvi_p50": 0.55, "ndvi_p90": 0.70,
                "n_pixeles": 900}
    espacial_uniforme = {"ndvi_std": 0.02, "ndvi_p10": 0.54, "ndvi_p50": 0.55,
                         "ndvi_p90": 0.57, "n_pixeles": 900}
    for et_esp, extra in (("sin_espacial", None), ("dispersa", espacial),
                          ("uniforme", espacial_uniforme)):
        for activa in (True, False):
            for et_ndvi, ndvi in (("dentro", 0.60), ("bajo", 0.40)):
                serie = [_pasada(_iso(SIEMBRA_OTONO, 128), 0.62,
                                 extra=dict(extra or {}, ndvi_std=0.05) if extra else None),
                         _pasada(_iso(SIEMBRA_OTONO, 140), ndvi, extra=extra)]
                cid = f"HETERO|{et_esp}|{'on' if activa else 'off'}|{et_ndvi}"
                yield cid, dict(
                    tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=serie,
                    spec={"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO},
                    heterogeneidad_activa=activa)
    # CRUCE evento + zonas: el aviso de foco NO debe solaparse con un evento del
    # cuaderno que ya explica la caida. Sin este bloque, el barrido no cubria ese
    # cruce -lo detecte mutando la regla: solo lo cazaban las pruebas unitarias-.
    ev_siega = [(2, {"tipo": "SIEGA", "fecha": _iso(SIEMBRA_OTONO, 138)})]
    for et_ev, evs in (("con_evento", ev_siega), ("sin_evento", None)):
        for et_esp, extra in (("dispersa", espacial), ("uniforme", espacial_uniforme)):
            serie = [_pasada(_iso(SIEMBRA_OTONO, 128), 0.72,
                             extra={"ndvi_std": 0.04, "ndvi_p10": 0.68,
                                    "ndvi_p50": 0.72, "ndvi_p90": 0.76,
                                    "n_pixeles": 900}),
                     _pasada(_iso(SIEMBRA_OTONO, 140), 0.32, extra=extra)]
            cid = f"HETERO|evento|{et_ev}|{et_esp}"
            kw = dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=serie,
                      spec={"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO})
            if evs:
                kw["eventos_cerca"] = evs
            yield cid, kw
    # y el mismo cruce con un CORTE de forraje, que tambien silencia el aviso
    for et_esp, extra in (("dispersa", espacial), ("uniforme", espacial_uniforme)):
        serie = [_pasada(f"{ANO_LENOSO}-04-01", 0.75,
                         extra={"ndvi_std": 0.04, "ndvi_p10": 0.71, "ndvi_p50": 0.75,
                                "ndvi_p90": 0.79, "n_pixeles": 900}),
                 _pasada(f"{ANO_LENOSO}-04-15", 0.25, extra=extra)]
        yield f"HETERO|segado|{et_esp}", dict(
            tipo="EXTENSIVO", subtipo="SIEGA_VERDE", serie=serie,
            spec={"especie": "VEZA", "fecha_siembra": SIEMBRA_OTONO})

    # arbolado disperso: el juicio se hace sobre el NDVI del cultivo, no la media
    for arbolado in (True, False):
        cid = f"HETERO|arbolado{'ON' if arbolado else 'OFF'}|-"
        yield cid, dict(
            tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
            serie=[_pasada(_iso(SIEMBRA_OTONO, 140), 0.60, extra=espacial)],
            spec={"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO},
            arbolado=arbolado)


def _casos_degenerados():
    """Entradas que no deberian llegar nunca, y que llegan.

    Serie vacia, NDVI nulo, NDVI 0.0 exacto (que NO es lo mismo que nulo), fechas
    ilegibles, indices ausentes, spec a medias y barbecho. Si algo de esto revienta
    despues de un refactor, el usuario ve una traza en vez de una ficha."""
    esp = {"especie": "TRIGO", "fecha_siembra": SIEMBRA_OTONO}
    f = _iso(SIEMBRA_OTONO, 140)
    casos = [
        ("serie_vacia", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=[], spec=esp)),
        ("barbecho", dict(tipo="BARBECHO", subtipo="", serie=[_pasada(f, 0.5)], spec=None)),
        ("barbecho_sin_serie", dict(tipo="BARBECHO", subtipo="", serie=[], spec=None)),
        ("ndvi_none", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                           serie=[{"fecha": f, "ndvi": None, "ndmi": 0.2}], spec=esp)),
        ("ndvi_cero", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                           serie=[{"fecha": f, "ndvi": 0.0, "ndmi": 0.2}], spec=esp)),
        ("ndvi_uno", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                          serie=[{"fecha": f, "ndvi": 1.0, "ndmi": 0.2}], spec=esp)),
        ("ndvi_negativo", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                               serie=[{"fecha": f, "ndvi": -0.15, "ndmi": 0.2}], spec=esp)),
        ("sin_indices", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                             serie=[{"fecha": f}], spec=esp)),
        ("sin_fecha", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                           serie=[{"ndvi": 0.6}], spec=esp)),
        ("fecha_basura", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                              serie=[{"fecha": "no-es-fecha", "ndvi": 0.6}], spec=esp)),
        ("fecha_vacia", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                             serie=[{"fecha": "", "ndvi": 0.6}], spec=esp)),
        ("spec_none", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                           serie=[_pasada(f, 0.6)], spec=None)),
        ("spec_sin_especie", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                                  serie=[_pasada(f, 0.6)],
                                  spec={"fecha_siembra": SIEMBRA_OTONO})),
        ("spec_sin_siembra", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                                  serie=[_pasada(f, 0.6)], spec={"especie": "TRIGO"})),
        ("siembra_basura", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                                serie=[_pasada(f, 0.6)],
                                spec={"especie": "TRIGO", "fecha_siembra": "xx"})),
        ("especie_desconocida", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                                     serie=[_pasada(f, 0.6)],
                                     spec={"especie": "QUINOA",
                                           "fecha_siembra": SIEMBRA_OTONO})),
        ("tipo_desconocido", dict(tipo="OTRA_COSA", subtipo="", serie=[_pasada(f, 0.6)],
                                  spec=esp)),
        ("subtipo_vacio", dict(tipo="EXTENSIVO", subtipo="", serie=[_pasada(f, 0.6)],
                               spec=esp)),
        ("lenoso_sin_spec", dict(tipo="LENOSO", subtipo="", serie=[_pasada(f, 0.5)],
                                 spec=None)),
        ("lenoso_especie_rara", dict(tipo="LENOSO", subtipo="TRADICIONAL",
                                     serie=[_pasada(f, 0.5)],
                                     spec={"especie": "MANGO"})),
        ("das_negativo", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                              serie=[_pasada(_iso(SIEMBRA_OTONO, -30), 0.6)], spec=esp)),
        ("das_enorme", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                            serie=[_pasada(_iso(SIEMBRA_OTONO, 900), 0.6)], spec=esp)),
        ("ndmi_none", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                           serie=[{"fecha": f, "ndvi": 0.6, "ndmi": None}], spec=esp)),
        ("pasada_vacia", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO", serie=[{}],
                              spec=esp)),
        ("fecha_iso_explicita", dict(tipo="EXTENSIVO", subtipo="COSECHA_GRANO",
                                     serie=[_pasada(f, 0.6)], spec=esp,
                                     fecha_iso=_iso(SIEMBRA_OTONO, 200))),
    ]
    for nombre, kw in casos:
        yield f"DEGEN|{nombre}", kw


GENERADORES = [_casos_extensivo, _casos_fronteras_extensivo,
               _casos_umbrales_extensivo, _casos_umbrales_lenoso,
               _casos_umbrales_ndmi, _casos_siega_verde,
               _casos_segado, _casos_lenoso, _casos_lenoso_series,
               _casos_lenoso_marco, _casos_series, _casos_eventos,
               _casos_heterogeneidad, _casos_degenerados]


def casos():
    """Todos los casos, con su identificador. Falla si hay dos con el mismo nombre:
    un id repetido esconderia un caso entero al pisarlo en el diccionario."""
    out = {}
    for gen in GENERADORES:
        for cid, kw in gen():
            if cid in out:
                raise RuntimeError(f"identificador de caso repetido: {cid}")
            out[cid] = kw
    return out


# =====================================================================
# Ejecucion y proyeccion de la salida
# =====================================================================
def _proyectar(d):
    """La parte de la salida que se congela. Ver la cabecera del modulo."""
    out = {
        "clave": d.get("clave"),
        "estado": d.get("estado"),
        "esperado": d.get("esperado"),
        "fase": d.get("fase"),
        "rango_fase": list(d["rango_fase"]) if d.get("rango_fase") else None,
        "ndvi_juicio": d.get("ndvi_juicio"),
        "motivo": d.get("motivo"),
        "umbrales": d.get("umbrales"),
    }
    # los textos de los deltas se ven en la ficha, pasada a pasada
    deltas = d.get("deltas") or {}
    out["deltas_texto"] = {k: v.get("texto") for k, v in sorted(deltas.items())}
    # cubierta vegetal (lenosos): lo que decide, no la aritmetica que lo sostiene
    cub = d.get("cubierta")
    out["cubierta"] = None if not cub else {
        "señales": cub.get("señales"),
        "hipotesis_preliminar": cub.get("hipotesis_preliminar"),
        "confianza": cub.get("confianza"),
        "copa_msavi": cub.get("copa_msavi"),
    }
    copa = d.get("copa")
    out["copa"] = None if not copa else {
        "veredicto_cubierta": copa.get("veredicto_cubierta"),
        "vigor_copa": copa.get("vigor_copa"),
        "ambito": copa.get("ambito"),
        "razonamiento": copa.get("razonamiento"),
    }
    het = d.get("heterogeneidad")
    out["heterogeneidad"] = None if not het else {
        "disponible": het.get("disponible"),
        "patron": het.get("patron"),
        "uniformidad": het.get("uniformidad"),
        "rodal_sospechoso": het.get("rodal_sospechoso"),
    }
    return out


def ejecutar():
    """Corre el barrido entero y devuelve {id: salida_proyectada}.

    Si una llamada revienta, se guarda la excepcion como resultado en vez de tumbar
    el barrido: que el motor pete con una entrada degenerada TAMBIEN es un
    comportamiento que hay que congelar, y asi el diff lo ensena."""
    salida = {}
    for cid, kw in casos().items():
        try:
            d = evaluar_parcela(parcela=None, **kw)
            salida[cid] = _proyectar(d)
        except Exception as e:                      # noqa: BLE001 - se congela el fallo
            salida[cid] = {"EXCEPCION": f"{type(e).__name__}: {e}"}
    return salida


# =====================================================================
# Fichero de oro: leer, escribir, comparar
# =====================================================================
def _volcar(datos):
    """Un caso por LINEA, con las claves ordenadas.

    Con `json.dump(indent=…)` cada caso ocupa veinte lineas y un cambio de estado
    se pierde en el diff. Asi, cambiar un veredicto es cambiar UNA linea, y
    `git diff` se lee de un vistazo."""
    lineas = ["{"]
    claves = sorted(datos)
    for i, k in enumerate(claves):
        coma = "," if i < len(claves) - 1 else ""
        val = json.dumps(datos[k], sort_keys=True, ensure_ascii=False)
        lineas.append(f" {json.dumps(k, ensure_ascii=False)}: {val}{coma}")
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def guardar(datos, ruta=RUTA_ORO):
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(_volcar(datos))


def cargar(ruta=RUTA_ORO):
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def _legible(v):
    """Un valor del informe, con las claves ordenadas si es un dict."""
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return v


def comparar(ruta=RUTA_ORO):
    """Compara la salida de ahora con el oro. Devuelve (ok, informe, resumen).

    `resumen` trae los numeros para quien quiera contarlos sin leer el texto."""
    oro = cargar(ruta)
    ahora = ejecutar()
    if oro is None:
        return (False,
                f"No existe el fichero de oro ({os.path.basename(ruta)}). "
                f"Generalo a mano con:  python pruebas_oro.py --regenerar",
                {"casos": len(ahora), "diferencias": None})

    faltan = sorted(set(oro) - set(ahora))
    sobran = sorted(set(ahora) - set(oro))
    cambian = [k for k in sorted(set(oro) & set(ahora)) if oro[k] != ahora[k]]

    resumen = {"casos": len(ahora), "en_oro": len(oro), "diferencias": len(cambian),
               "solo_en_oro": len(faltan), "solo_ahora": len(sobran)}
    if not (faltan or sobran or cambian):
        return True, f"{len(ahora)} casos, ninguna diferencia.", resumen

    # --- recuento por transicion de estado, que es lo primero que se mira ---
    transiciones = {}
    for k in cambian:
        a, b = oro[k].get("estado"), ahora[k].get("estado")
        if a != b:
            transiciones[f"{a} -> {b}"] = transiciones.get(f"{a} -> {b}", 0) + 1
    solo_texto = sum(1 for k in cambian if oro[k].get("estado") == ahora[k].get("estado"))
    resumen["transiciones"] = transiciones
    resumen["solo_texto"] = solo_texto

    L = ["EL COMPORTAMIENTO DEL MOTOR HA CAMBIADO.", ""]
    L.append(f"  casos del barrido : {len(ahora)}")
    L.append(f"  con diferencias   : {len(cambian)}")
    if faltan:
        L.append(f"  en el oro y ya no se generan : {len(faltan)}  (p.ej. {faltan[:3]})")
    if sobran:
        L.append(f"  nuevos, no estan en el oro   : {len(sobran)}  (p.ej. {sobran[:3]})")
    L.append("")
    if transiciones:
        L.append("  CAMBIOS DE ESTADO:")
        for t, n in sorted(transiciones.items(), key=lambda x: -x[1]):
            L.append(f"    {t:<28} {n:>5} caso(s)")
    if solo_texto:
        L.append(f"  Mismo estado, cambia otra cosa (motivo, fase, umbrales…): {solo_texto}")
    L.append("")
    L.append(f"  PRIMEROS {min(20, len(cambian))} CASOS QUE CAMBIAN:")
    entradas = casos()
    for k in cambian[:20]:
        L.append("")
        L.append(f"  · {k}")
        kw = entradas.get(k, {})
        L.append(f"      entrada: tipo={kw.get('tipo')} subtipo={kw.get('subtipo')!r} "
                 f"spec={kw.get('spec')}")
        L.append(f"               serie={kw.get('serie')}")
        extra = {c: kw[c] for c in ("eventos_cerca", "heterogeneidad_activa",
                                    "arbolado", "fecha_iso") if c in kw}
        if extra:
            L.append(f"               {extra}")
        for campo in sorted(set(oro[k]) | set(ahora[k])):
            va, vb = oro[k].get(campo), ahora[k].get(campo)
            if va != vb:
                L.append(f"      {campo}:")
                # con las claves ordenadas en los dos lados: el oro se lee del
                # JSON (ya ordenado) y lo de ahora viene en orden de insercion,
                # asi que sin esto los dos dicts se ven distintos aunque solo
                # cambie un valor
                L.append(f"          antes:   {_legible(va)}")
                L.append(f"          ahora:   {_legible(vb)}")
    if len(cambian) > 20:
        L.append("")
        L.append(f"  … y {len(cambian) - 20} caso(s) mas.")
    L.append("")
    L.append("  Si el cambio es DELIBERADO: revisa el diff y regenera a mano con")
    L.append("      python pruebas_oro.py --regenerar")
    L.append("  Si no lo es, es una regresion: NO regeneres el fichero.")
    return False, "\n".join(L), resumen


def main(argv):
    regenerar = "--regenerar" in argv
    if regenerar:
        datos = ejecutar()
        guardar(datos)
        print(f"Fichero de oro regenerado: {len(datos)} casos en "
              f"{os.path.basename(RUTA_ORO)}")
        print("Revisa el diff ANTES de hacer commit: es la lista exacta de "
              "veredictos que cambian.")
        return 0
    ok, informe, _resumen = comparar()
    print(informe)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
