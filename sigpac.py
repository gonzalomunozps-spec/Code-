# -*- coding: utf-8 -*-
"""
sigpac.py
=========

Consulta de recintos SIGPAC y parseo de su geometria. Aislado del panel para
poder probarlo sin red (el parseo es puro; la peticion HTTP se inyecta como un
`get(url)`), y para no mezclar este dominio con la interfaz.

Comportamiento identico al que tenia dentro de panel_gestion_parcelas:
  - se prueban varios endpoints en orden hasta que uno da un recinto valido,
  - la geometria se normaliza a un anillo exterior de [lon, lat],
  - si viene en UTM (EPSG:25830) se intenta convertir con pyproj,
  - los fallos se traducen a un mensaje ya redactado para el usuario.
"""

from typing import Any, Callable, Dict, List, Optional

import requests


def sigpac_geometria(data: Any) -> Optional[Dict[str, Any]]:
    """Extrae la geometria de una respuesta SIGPAC sea Feature, FeatureCollection
    o geometria suelta. Devuelve el dict de geometria o None."""
    if not isinstance(data, dict):
        return None
    t = data.get("type")
    if t == "FeatureCollection":
        feats = data.get("features") or []
        return feats[0].get("geometry") if feats else None
    if t == "Feature":
        return data.get("geometry")
    if t in ("Polygon", "MultiPolygon"):
        return data
    return data.get("geometry")


def sigpac_anillo(geom: Optional[Dict[str, Any]]) -> Optional[List[Any]]:
    """Anillo exterior [[x,y],...] de un Polygon o MultiPolygon."""
    if not geom:
        return None
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon" and c:
        return c[0]
    if t == "MultiPolygon" and c and c[0]:
        return c[0][0]
    return None


def sigpac_a_lonlat(coords: Optional[List[Any]]) -> Optional[List[List[float]]]:
    """Devuelve las coordenadas como [lon,lat]. Si vienen en UTM (EPSG:25830,
    valores grandes) intenta convertirlas; si no puede, lanza un error claro en
    vez de colocar la parcela en un sitio equivocado en silencio."""
    if not coords:
        return coords
    x0, y0 = coords[0][0], coords[0][1]
    if abs(x0) <= 180 and abs(y0) <= 90:
        return [[float(p[0]), float(p[1])] for p in coords]      # ya es lon/lat
    try:
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        return [list(tr.transform(float(p[0]), float(p[1]))) for p in coords]
    except ImportError:
        raise ValueError("El recinto viene en coordenadas UTM y falta 'pyproj' para "
                         "convertirlas (pip install pyproj).")


class SigpacError(Exception):
    """Error de consulta SIGPAC con un mensaje ya listo para mostrar al usuario."""


# Endpoints de consulta de recintos. Se prueban en orden hasta que uno responda
# con una geometria valida; asi la app resiste que uno de los servicios cambie o
# se caiga. {prov}/{mun}/{agr}/{zona}/{pol}/{par}/{rec}.
SIGPAC_ENDPOINTS = [
    "https://sigpac-hubcloud.es/servicioconsultassigpac/query/recinfo/"
    "{prov}/{mun}/{agr}/{zona}/{pol}/{par}/{rec}.geojson",
    "https://sigpac.mapa.gob.es/fega/serviciosrest/v1/recintos/geojson/"
    "{prov}/{mun}/{agr}/{zona}/{pol}/{par}/{rec}",
]


def sigpac_urls(v: Dict[str, Any]) -> List[str]:
    """Lista de URLs candidatas para los codigos dados (Agr/Zona -> 0 si faltan)."""
    d = {"prov": v["Prov"], "mun": v["Mun"], "agr": v.get("Agr") or "0",
         "zona": v.get("Zona") or "0", "pol": v["Pol"], "par": v["Par"], "rec": v["Rec"]}
    return [u.format(**d) for u in SIGPAC_ENDPOINTS]


def _sigpac_mensaje(ultimo: Optional[tuple]) -> str:
    """Traduce el ultimo fallo (clase, url, detalle) a un mensaje claro."""
    if not ultimo:
        return "No se pudo consultar SIGPAC."
    clase, _url, det = ultimo
    if clase == "http":
        if det == 404:
            return ("SIGPAC no encontro ningun recinto con esos codigos (404).\n\n"
                    "Revisa los 7 codigos (provincia / municipio / agregado / zona / "
                    "poligono / parcela / recinto). Recuerda que SIGPAC solo cubre suelo "
                    "rustico o agricola: en suelo urbano no hay recintos.")
        if det in (429, 500, 502, 503, 504):
            return (f"El servicio SIGPAC no esta disponible ahora mismo (HTTP {det}). "
                    "Vuelve a intentarlo en unos minutos.")
        return (f"SIGPAC respondio con el codigo HTTP {det}. Revisa los codigos o si el "
                "servicio esta disponible.")
    if clase == "con":
        return f"No se pudo conectar con SIGPAC: {det}"
    if clase == "json":
        return ("SIGPAC no devolvio datos de un recinto (respuesta vacia o no valida). "
                "Revisa los codigos.")
    if clase == "vacio":
        return ("SIGPAC no devolvio un recinto valido. Revisa los codigos "
                "(provincia / municipio / agregado / zona / poligono / parcela / recinto).")
    return "No se pudo consultar SIGPAC."


def sigpac_consultar(v: Dict[str, Any], get: Callable[[str], Any]) -> List[List[float]]:
    """Consulta SIGPAC probando los endpoints conocidos.

    `get(url)` debe devolver un objeto tipo respuesta (con `.status_code`,
    `.json()` y `.text`). Devuelve la lista de coordenadas [lon,lat] del anillo
    exterior. Si ninguno responde con un recinto valido, lanza `SigpacError` con
    un mensaje ya redactado para el usuario.
    """
    ultimo: Optional[tuple] = None     # (clase, url, detalle); el detalle varia de tipo
    for url in sigpac_urls(v):
        try:
            r = get(url)
        except Exception as e:                       # fallo de red / DNS / timeout
            ultimo = ("con", url, str(e)); continue
        code = getattr(r, "status_code", None)
        if code is not None and code >= 400:
            ultimo = ("http", url, code); continue
        try:
            data = r.json()
        except Exception:
            ultimo = ("json", url, None); continue
        anillo = sigpac_anillo(sigpac_geometria(data))
        if not anillo or len(anillo) < 3:
            ultimo = ("vacio", url, None); continue
        coords = sigpac_a_lonlat(anillo)             # puede lanzar ValueError (UTM sin pyproj)
        if coords and len(coords) >= 3:
            return coords
        ultimo = ("vacio", url, None)
    raise SigpacError(_sigpac_mensaje(ultimo))


def _sigpac_get(url: str):
    """Getter real basado en requests (separado para poder testear sin red)."""
    return requests.get(url, timeout=15, headers={"User-Agent": "GestorParcelas/1.0"})
