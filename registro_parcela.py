# -*- coding: utf-8 -*-
"""
registro_parcela.py
====================

Dos funcionalidades que se apoyan en el diagnostico existente:

1. CUADERNO DE CAMPO (eventos)
   Permite anotar intervenciones que el satelite NO detecta con fiabilidad por si
   solo: aplicacion de un producto (fitosanitario, abono, herbicida), siega,
   cosecha, riego, laboreo, siembra... Estos eventos:
     - Retroalimentan el diagnostico: una siega o cosecha REGISTRADA explica una
       caida brusca de NDVI (deja de ser falsa alarma).
     - Permiten medir la RESPUESTA del cultivo tras un producto (correlacion, no
       causa: el clima y la fenologia tambien mueven los indices).

Persistencia en JSON (misma carpeta que el resto de datos).
"""

import math
from datetime import datetime

import almacen as DB     # el almacen (SQLite) guarda ahora los eventos
from campanas import campana_actual   # logica pura de campana agricola


def _dias(f1, f2):
    d1 = datetime.strptime(f1, "%Y-%m-%d")
    d2 = datetime.strptime(f2, "%Y-%m-%d")
    return (d2 - d1).days


# =====================================================================
# 1. CUADERNO DE CAMPO
# =====================================================================
# Tipos de evento y, para PRODUCTO, objetivos posibles.
TIPOS_EVENTO = ["PRODUCTO", "SIEGA", "COSECHA", "RIEGO", "LABOREO", "SIEMBRA", "OTRO"]
OBJETIVOS_PRODUCTO = ["fitosanitario (plaga)", "fungicida (enfermedad)",
                      "herbicida (malas hierbas)", "abono / nutricion", "otro"]

# =====================================================================
# COSECHA: el unico dato OBJETIVO del sistema
# =====================================================================
# Los kg/ha salen de la bascula, no de interpretar una imagen. Es el unico dato
# que este programa no puede deducir y que se pierde para siempre si no se anota
# en su momento. Por eso se captura tal cual, sin calcular ni estimar nada con el.
#
# Todos los campos son OPCIONALES: mas vale un rendimiento a secas que ninguno.
# La humedad solo se pide donde significa algo (grano de extensivo); en el resto
# ni se ensena, porque no hay tal dato.
FUENTES_DATO = ["memoria", "albaran", "bascula", "parte de cosecha"]

CAMPOS_COSECHA = ("rendimiento_kg_ha", "humedad_grano_pct",
                  "superficie_cosechada_ha", "fuente_dato")


def admite_humedad_grano(cultivo):
    """True solo si el cultivo es grano de extensivo, que es donde la humedad del
    grano tiene sentido (y sin ella el rendimiento no se puede comparar entre
    campanas). En lo demas no existe ese dato y no debe pedirse.

    El subtipo vacio cuenta como grano: es la misma convencion que ya aplican el
    panel y demo_sistema al normalizar un extensivo sin finalidad declarada. Asi
    las fichas antiguas (guardadas antes de que se escribiera el subtipo) no
    pierden el campo."""
    if not cultivo:
        return False
    return (cultivo.get("tipo") == "EXTENSIVO"
            and (cultivo.get("subtipo") or "COSECHA_GRANO") == "COSECHA_GRANO")


def admite_humedad_en_campana(cultivo_campana, cultivo_vista):
    """Como `admite_humedad_grano`, pero para una COSECHA que puede caer en una
    campana anterior.

    Al cargar el historico de anos pasados esa campana casi nunca tiene cultivo
    registrado: el agricultor empezo a usar el programa despues. Si se mirase solo
    ahi, la humedad desapareceria JUSTO en el caso para el que se pide. Por eso,
    cuando la campana de destino no dice nada, se hereda el cultivo de la campana
    que se esta viendo, que es el de la parcela."""
    return admite_humedad_grano(cultivo_campana or cultivo_vista)


def campana_de_evento(tipo, iso, campana_vista):
    """Campana bajo la que se archiva un evento del cuaderno.

    Todo se anota en la campana que se esta viendo, SALVO la COSECHA: esa cae en
    la campana de su propia fecha, para poder cargar el historico de anos
    anteriores sin cambiar de campana en el panel. Una fecha ilegible no rompe
    nada: se queda en la campana vista."""
    if tipo != "COSECHA" or not iso:
        return campana_vista
    try:
        return campana_actual(datetime.strptime(iso, "%Y-%m-%d"))
    except (TypeError, ValueError):
        return campana_vista


def _num_es(v, dec=0):
    """Numero en castellano: miles con punto, decimales con coma."""
    return f"{v:,.{dec}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def linea_rendimiento(r):
    """Una linea del historico de cosecha, tal como la devuelve `almacen.rendimientos`.

    Volcado literal de lo anotado: no se convierte a humedad comercial, no se
    normaliza por superficie y no se compara con nada."""
    partes = [r.get("campana", "")]
    if r.get("rendimiento_kg_ha") is not None:
        partes.append(f"{_num_es(r['rendimiento_kg_ha'])} kg/ha")
    if r.get("humedad_grano_pct") is not None:
        partes.append(f"humedad {_num_es(r['humedad_grano_pct'], 1)} %")
    if r.get("superficie_cosechada_ha") is not None:
        partes.append(f"{_num_es(r['superficie_cosechada_ha'], 2)} ha")
    if r.get("fuente_dato"):
        partes.append(str(r["fuente_dato"]))
    if r.get("fecha"):
        partes.append(f"({r['fecha']})")
    return "  ·  ".join(p for p in partes if p)


def numero_opcional(texto):
    """Texto -> numero, aceptando la coma decimal ('4,5' y '4.5' valen igual).

    Devuelve None si esta vacio. Lanza ValueError si no es un numero o si es
    negativo (un rendimiento o una superficie negativos no existen).

    'nan' e 'inf' tambien se rechazan aunque float() los acepte: 'nan' burla la
    comprobacion del signo (nan < 0 es False) y los dos acabarian escritos en la
    base como NaN / Infinity, que NO son JSON valido y atragantan a cualquier
    lector que no sea Python."""
    t = (texto or "").strip().replace(",", ".")
    if not t:
        return None
    v = float(t)                      # ValueError si no es un numero
    if not math.isfinite(v):
        raise ValueError("no es un numero valido")
    if v < 0:
        raise ValueError("no puede ser negativo")
    return v


def datos_cosecha(rendimiento=None, humedad=None, superficie=None, fuente=None,
                  admite_humedad=True):
    """Normaliza los campos de una COSECHA para guardarlos en el evento.

    Devuelve un dict SOLO con lo que se haya rellenado (nada de ceros ni huecos
    inventados). Si el cultivo no admite humedad de grano, ese campo se ignora
    aunque venga con valor. Lanza ValueError, con el nombre del campo, si algun
    numero no es valido.
    """
    out = {}
    for clave, valor, etiqueta in (("rendimiento_kg_ha", rendimiento, "rendimiento (kg/ha)"),
                                   ("superficie_cosechada_ha", superficie, "superficie cosechada (ha)")):
        try:
            v = numero_opcional(valor)
        except ValueError:
            raise ValueError(etiqueta)
        if v is not None:
            out[clave] = v
    if admite_humedad:
        try:
            h = numero_opcional(humedad)
        except ValueError:
            raise ValueError("humedad del grano (%)")
        if h is not None:
            if h > 100:
                raise ValueError("humedad del grano (%)")
            out["humedad_grano_pct"] = h
    fuente = (fuente or "").strip()
    if fuente:
        out["fuente_dato"] = fuente
    return out

# Interpretacion (opcional) del herbicida con LAI constante. Vive en un modulo
# aparte; si se borra ese fichero, se vuelve solo al comportamiento base.
try:
    import herbicida_contexto as _HB
except Exception:
    _HB = None

# eventos que, si estan registrados, EXPLICAN una caida brusca del NDVI
EVENTOS_QUE_BAJAN_NDVI = {"SIEGA", "COSECHA"}


def registrar_evento(parcela, campana, evento):
    """evento = dict con al menos {fecha, tipo}. Devuelve el evento guardado (con id)."""
    return DB.registrar_evento(parcela, campana, evento)


def eventos_de(parcela, campana):
    return DB.eventos_de(parcela, campana)


def eliminar_evento(parcela, campana, evento_id):
    DB.eliminar_evento(parcela, campana, evento_id)


def eventos_cercanos(parcela, campana, fecha_iso, ventana_dias=20):
    """Eventos ocurridos en los `ventana_dias` anteriores (o el mismo dia) a fecha_iso."""
    out = []
    if not fecha_iso:                 # sin fecha de referencia no hay nada que comparar
        return out
    for e in eventos_de(parcela, campana):
        f = e.get("fecha")
        if not f:
            continue
        try:
            d = _dias(f, fecha_iso)
        except (TypeError, ValueError):   # fecha del evento o de referencia mal formada
            continue
        if 0 <= d <= ventana_dias:
            out.append((d, e))
    return sorted(out, key=lambda x: x[0])


def explicacion_por_eventos(eventos_cerca, dN):
    """
    Dada la lista de (dias, evento) cercanos y la variacion de NDVI (dN),
    devuelve (esperado, texto) si algun evento explica lo observado.
    """
    for d, e in eventos_cerca:
        tipo = e.get("tipo")
        if tipo in EVENTOS_QUE_BAJAN_NDVI and dN is not None and dN < -0.08:
            nombre = "siega/corte" if tipo == "SIEGA" else "cosecha"
            return (True, f"Caida del NDVI coherente con la {nombre} registrada en el cuaderno "
                          f"el {e.get('fecha')} (hace {d} dias): evento previsto, no anomalia.")
        if tipo == "PRODUCTO" and "herbicida" in (e.get("objetivo", "")) and dN is not None and dN < -0.05:
            return (True, f"Descenso del verdor coherente con el herbicida aplicado el "
                          f"{e.get('fecha')} (hace {d} dias) sobre malas hierbas.")
    return (False, None)


def efecto_producto(serie, evento, ventana_dias=30, fecha_objetivo=None):
    """
    Mide la RESPUESTA de los indices tras aplicar un producto.
    Compara el estado en la fecha de aplicacion (o la pasada valida mas cercana previa)
    con el estado en el dia del informe.

    El dia del informe se elige, por orden de prioridad:
      1. `fecha_objetivo` (pasado por el usuario al pedir el informe), o
      2. `evento["fecha_informe"]` (guardado al registrar la intervencion), o
      3. automatico: la primera pasada a partir de ~`ventana_dias/2` dias despues.
    En 1 y 2 se toma la pasada valida MAS CERCANA a esa fecha (posterior a la
    aplicacion).

    IMPORTANTE: es correlacion, no causa. El clima y la fenologia tambien influyen.
    """
    f_ap = evento.get("fecha")
    if not f_ap or not serie:
        return None
    serie = sorted(serie, key=lambda r: r.get("fecha", ""))

    # baseline: ultima pasada en o antes de la aplicacion (y la anterior, para la tendencia)
    base = None
    base_idx = -1
    for i, r in enumerate(serie):
        if r.get("fecha") and r["fecha"] <= f_ap and r.get("ndvi") is not None:
            base = r
            base_idx = i
    base_prev = serie[base_idx - 1] if base_idx > 0 else None

    # pasadas validas posteriores a la aplicacion (candidatas a "dia del informe")
    posteriores = [r for r in serie
                   if r.get("fecha") and r["fecha"] > f_ap and r.get("ndvi") is not None]

    objetivo = fecha_objetivo or evento.get("fecha_informe")
    resp = None
    if objetivo and posteriores:
        # la pasada mas cercana a la fecha pedida (aunque no llegue a la ventana)
        try:
            resp = min(posteriores, key=lambda r: abs(_dias(objetivo, r["fecha"])))
        except (TypeError, ValueError):
            resp = None
    if resp is None:
        # automatico: primera pasada al menos `ventana_dias/2` despues, la mas cercana a la ventana
        for r in posteriores:
            d = _dias(f_ap, r["fecha"])
            if d >= max(7, ventana_dias // 2):
                resp = r
                if d >= ventana_dias:
                    break
    if not base or not resp:
        return {"disponible": False,
                "nota": "Aun no hay pasadas suficientes despues de la aplicacion para medir el efecto."}

    d_ndvi = round(resp["ndvi"] - base["ndvi"], 3)
    d_ndmi = None
    if base.get("ndmi") is not None and resp.get("ndmi") is not None:
        d_ndmi = round(resp["ndmi"] - base["ndmi"], 3)
    # LAI (area foliar): clave para HERBICIDAS, donde el efecto se ve como caida de
    # biomasa/cobertura, no como recuperacion del verdor.
    d_lai = None
    if base.get("lai") is not None and resp.get("lai") is not None:
        d_lai = round(resp["lai"] - base["lai"], 3)

    # dispersion intraparcela y tendencia previa del LAI (para desambiguar el LAI plano)
    d_std = None
    if base.get("ndvi_std") is not None and resp.get("ndvi_std") is not None:
        d_std = round(resp["ndvi_std"] - base["ndvi_std"], 3)
    lai_subia_antes = bool(base.get("lai") is not None and base_prev
                           and base_prev.get("lai") is not None
                           and base["lai"] - base_prev["lai"] > 0.1)

    es_herbicida = "herbicida" in (evento.get("objetivo", "") or "").lower()
    if es_herbicida:
        # el herbicida ACTUA si baja el area foliar (LAI) y/o el verdor (NDVI)
        baja_lai = d_lai is not None and d_lai < -0.3
        baja_ndvi = d_ndvi < -0.05
        if baja_lai or baja_ndvi:
            detalle = f"LAI {d_lai:+.2f}" if d_lai is not None else f"NDVI {d_ndvi:+.3f}"
            verdicto = (f"efecto compatible: baja el area foliar/cobertura ({detalle}) tras el "
                        "herbicida (reduccion de vegetacion)")
        elif (d_lai is not None and d_lai > 0.15) or d_ndvi > 0.05:
            verdicto = "sin efecto herbicida visible: el area foliar y el verdor siguen al alza"
        else:
            # LAI/NDVI plano: se delega en el modulo opcional herbicida_contexto.
            # Si ese modulo se ha borrado (_HB is None), se usa el texto base.
            verdicto = None
            if _HB is not None:
                verdicto = _HB.verdicto_lai_constante(d_std, lai_subia_antes)
            if not verdicto:
                verdicto = "sin cambio claro tras el herbicida (LAI estable)"
    else:
        if d_ndvi > 0.05:
            verdicto = "respuesta positiva compatible (el verdor se recupera tras la aplicacion)"
        elif d_ndvi < -0.03:
            verdicto = "sin mejora / deterioro tras la aplicacion"
        else:
            verdicto = "sin cambio claro"

    return {
        "disponible": True,
        "fecha_aplicacion": f_ap,
        "dia_informe": resp["fecha"],
        "objetivo": evento.get("objetivo", ""),
        "producto": evento.get("producto", ""),
        "es_herbicida": es_herbicida,
        "ndvi_antes": base["ndvi"], "ndvi_despues": resp["ndvi"], "d_ndvi": d_ndvi,
        "ndmi_antes": base.get("ndmi"), "ndmi_despues": resp.get("ndmi"), "d_ndmi": d_ndmi,
        "lai_antes": base.get("lai"), "lai_despues": resp.get("lai"), "d_lai": d_lai,
        "d_std": d_std,
        "dias_despues": _dias(f_ap, resp["fecha"]),
        "verdicto": verdicto,
        "aviso": ("Correlacion, no causa: el clima y la fenologia tambien mueven los indices. "
                  "Interpretar junto al contexto de la parcela."),
    }
