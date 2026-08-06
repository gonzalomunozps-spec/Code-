# -*- coding: utf-8 -*-
"""
geo.py
======

Geometria PURA de parcelas. Centraliza el calculo de superficie (formula del
area de un poligono, "shoelace", proyectada a metros) que antes estaba
duplicado en el panel, en la demo y en el modulo de informes.

`superficie_ha` conserva EXACTAMENTE el contrato que tenia en el panel:
  - coords vacio o con menos de 3 vertices -> 0.0
  - en caso contrario, hectareas SIN redondear
Los llamadores que quieran redondear o devolver None lo hacen en su capa (asi no
se cambia el comportamiento observable de ninguno).
"""

import math


def superficie_ha(coords):
    """Superficie de la parcela en hectareas (sin redondear). 0.0 si el poligono
    no es valido (vacio o < 3 vertices). coords = [[lon, lat], ...]."""
    if not coords or len(coords) < 3:
        return 0.0
    pts = coords[:-1] if coords[0] == coords[-1] else coords
    lat0 = math.radians(sum(p[1] for p in pts) / len(pts))
    R = 6371000.0
    xy = [(math.radians(p[0]) * R * math.cos(lat0), math.radians(p[1]) * R) for p in pts]
    area = 0.0
    n = len(xy)
    for i in range(n):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0 / 10000.0
