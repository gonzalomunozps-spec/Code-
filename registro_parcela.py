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

import os
import json
import tempfile
from datetime import datetime, timedelta

ARCHIVO_EVENTOS = "eventos_parcela.json"

for _f in (ARCHIVO_EVENTOS,):
    if not os.path.exists(_f):
        with open(_f, "w") as fh:
            json.dump({}, fh, indent=4)


def _load(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path, data):
    """Escritura atomica: temporal + os.replace, para no dejar el JSON del
    cuaderno corrupto si el proceso se corta a mitad."""
    carpeta = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=carpeta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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

# eventos que, si estan registrados, EXPLICAN una caida brusca del NDVI
EVENTOS_QUE_BAJAN_NDVI = {"SIEGA", "COSECHA"}


def registrar_evento(parcela, campana, evento):
    """evento = dict con al menos {fecha, tipo}. Devuelve el evento guardado (con id)."""
    data = _load(ARCHIVO_EVENTOS)
    lista = data.setdefault(parcela, {}).setdefault(campana, [])
    evento = dict(evento)
    evento.setdefault("id", f"{parcela}_{campana}_{len(lista)}_{evento.get('fecha','')}")
    evento.setdefault("registrado", datetime.now().strftime("%Y-%m-%d %H:%M"))
    lista.append(evento)
    lista.sort(key=lambda e: e.get("fecha", ""))
    _save(ARCHIVO_EVENTOS, data)
    return evento


def eventos_de(parcela, campana):
    return sorted(_load(ARCHIVO_EVENTOS).get(parcela, {}).get(campana, []),
                  key=lambda e: e.get("fecha", ""))


def eliminar_evento(parcela, campana, evento_id):
    data = _load(ARCHIVO_EVENTOS)
    lista = data.get(parcela, {}).get(campana, [])
    data.setdefault(parcela, {})[campana] = [e for e in lista if e.get("id") != evento_id]
    _save(ARCHIVO_EVENTOS, data)


def eventos_cercanos(parcela, campana, fecha_iso, ventana_dias=20):
    """Eventos ocurridos en los `ventana_dias` anteriores (o el mismo dia) a fecha_iso."""
    out = []
    for e in eventos_de(parcela, campana):
        f = e.get("fecha")
        if not f:
            continue
        d = _dias(f, fecha_iso)
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


def efecto_producto(serie, evento, ventana_dias=30):
    """
    Mide la RESPUESTA de los indices tras aplicar un producto.
    Compara el estado en la fecha de aplicacion (o la pasada valida mas cercana previa)
    con el estado ~`ventana_dias` despues.

    IMPORTANTE: es correlacion, no causa. El clima y la fenologia tambien influyen.
    """
    f_ap = evento.get("fecha")
    if not f_ap or not serie:
        return None
    serie = sorted(serie, key=lambda r: r.get("fecha", ""))

    # baseline: ultima pasada en o antes de la aplicacion
    base = None
    for r in serie:
        if r.get("fecha") and r["fecha"] <= f_ap and r.get("ndvi") is not None:
            base = r
    # respuesta: primera pasada al menos `ventana_dias/2` despues, la mas cercana a la ventana
    resp = None
    for r in serie:
        f = r.get("fecha")
        if not f or r.get("ndvi") is None or f <= f_ap:
            continue
        d = _dias(f_ap, f)
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

    if d_ndvi > 0.05:
        verdicto = "respuesta positiva compatible (el verdor se recupera tras la aplicacion)"
    elif d_ndvi < -0.03:
        verdicto = "sin mejora / deterioro tras la aplicacion"
    else:
        verdicto = "sin cambio claro"

    return {
        "disponible": True,
        "fecha_aplicacion": f_ap,
        "objetivo": evento.get("objetivo", ""),
        "producto": evento.get("producto", ""),
        "ndvi_antes": base["ndvi"], "ndvi_despues": resp["ndvi"], "d_ndvi": d_ndvi,
        "ndmi_antes": base.get("ndmi"), "ndmi_despues": resp.get("ndmi"), "d_ndmi": d_ndmi,
        "dias_despues": _dias(f_ap, resp["fecha"]),
        "verdicto": verdicto,
        "aviso": ("Correlacion, no causa: el clima y la fenologia tambien mueven los indices. "
                  "Interpretar junto al contexto de la parcela."),
    }
