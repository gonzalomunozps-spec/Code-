# -*- coding: utf-8 -*-
"""
cultivo.py
==========

Helpers PUROS del modelo de cultivo de una parcela (sin Tkinter ni base de datos):

  - spec_de: extrae el "modelo por especie" (especie, siembra, marco) del registro
    de cultivo, o None si es un registro antiguo sin especie.
  - clave_cultivo: clave estable tipo/subtipo para el cultivo.

Comportamiento identico al que tenian dentro de panel_gestion_parcelas; se
centralizan aqui para no duplicarlos (spec_de estaba repetido en informe_anual).
"""

from typing import Any, Dict, Optional


def spec_de(cultivo: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extrae el modelo por especie del registro de cultivo (o None si es antiguo)."""
    if not cultivo or not cultivo.get("especie"):
        return None
    return {"especie": cultivo.get("especie"),
            "fecha_siembra": cultivo.get("fecha_siembra"),
            "marco_calle": cultivo.get("marco_calle"),
            "marco_pie": cultivo.get("marco_pie"),
            # diametro medio de copa (lenosos, metros). Opcional: sin el, la
            # fraccion de copa se estima del marco. Con el, se sabe. Los registros
            # antiguos no lo traen y se comportan igual que siempre.
            "diametro_copa": cultivo.get("diametro_copa"),
            # regimen hidrico (lenosos). Los registros antiguos no lo traen y
            # `regimen_valido` los deja en SECANO, que es el supuesto que NO avisa
            # de falta de agua donde el deficit es normal.
            "regimen": cultivo.get("regimen"),
            # integrales termicas (grados-dia) definidas por el usuario. Lista o
            # None. Con ellas, la fase de un extensivo la manda el GDD y no el
            # calendario (modulo OPCIONAL grados_dia). Los registros sin ellas se
            # comportan como siempre.
            "integrales_termicas": cultivo.get("integrales_termicas")}


def clave_cultivo(tipo: str, subtipo: str) -> str:
    """Clave estable del cultivo: 'TIPO_SUBTIPO' (o solo 'BARBECHO')."""
    return tipo if tipo == "BARBECHO" else f"{tipo}_{subtipo}"
