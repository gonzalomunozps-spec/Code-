# -*- coding: utf-8 -*-
"""
campanas.py
===========

Logica PURA de "campana" agricola. Una campana va de septiembre a agosto y se
nombra 'AAAA-BBBB' (p. ej. '2025-2026'). Estas funciones no dependen de Tkinter
ni de la base de datos: se importan y se prueban sueltas.

Comportamiento identico al que tenian dentro de panel_gestion_parcelas.
"""

from datetime import datetime
from typing import Any, List, Optional, Tuple


def campana_actual(fecha: Optional[datetime] = None) -> str:
    """Campana agricola de una fecha (o de hoy). Sep-Dic -> 'anio-anio+1'."""
    d = fecha or datetime.now()
    return f"{d.year}-{d.year + 1}" if d.month >= 9 else f"{d.year - 1}-{d.year}"


def rango_campana(campana: str) -> Tuple[str, str]:
    """Devuelve (inicio, fin) ISO de una campana: 1-sep a 31-ago."""
    a0, a1 = [int(x) for x in campana.split("-")]
    return f"{a0}-09-01", f"{a1}-08-31"


def campanas_entre(inicio: Any, fin: str) -> List[str]:
    """Lista de campanas 'A-B' desde `inicio` hasta `fin` (inclusive), mas reciente
    primero. Tolera entradas mal formadas devolviendo al menos `fin`."""
    try:
        a0 = int(str(inicio).split("-")[0])
        a1 = int(str(fin).split("-")[0])
    except (ValueError, TypeError, AttributeError):
        return [fin]
    if a0 > a1:
        a0, a1 = a1, a0
    return [f"{y}-{y + 1}" for y in range(a1, a0 - 1, -1)]
