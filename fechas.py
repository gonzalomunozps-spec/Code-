# -*- coding: utf-8 -*-
"""
fechas.py
=========

Utilidades PURAS de fecha para la interfaz: conversion entre el formato interno
ISO (aaaa-mm-dd) y el que ve el usuario (dd-mm-aaaa), enmascarado con guiones
automaticos y validacion al vuelo mientras se teclea.

No dependen de Tkinter ni de ningun estado: se pueden importar y probar sueltas.
El comportamiento es identico al que tenian dentro de panel_gestion_parcelas.
"""

import re
from datetime import datetime


# --- conversion de fechas: el programa usa ISO (aaaa-mm-dd); el usuario ve dd-mm-aaaa ---
def iso_a_ddmmaaaa(iso):
    """'2026-05-04' -> '04-05-2026' (o '' si no es una fecha valida)."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        return ""


def ddmmaaaa_a_iso(texto):
    """'04-05-2026' (o '04052026') -> '2026-05-04'. '' si esta incompleta o no existe."""
    digs = re.sub(r"\D", "", texto or "")[:8]
    if len(digs) != 8:
        return ""
    d, m, y = digs[:2], digs[2:4], digs[4:8]
    try:
        datetime.strptime(f"{y}-{m}-{d}", "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{y}-{m}-{d}"


def enmascarar_fecha(texto):
    """Formatea los digitos tecleados como dd-mm-aaaa (los guiones salen solos)."""
    digs = re.sub(r"\D", "", texto or "")[:8]
    out = digs[:2]
    if len(digs) > 2:
        out += "-" + digs[2:4]
    if len(digs) > 4:
        out += "-" + digs[4:8]
    return out


def filtrar_fecha_digitos(digs):
    """Acepta los digitos mientras formen una fecha posible y descarta el primero
    que la haga imposible (dia 1-31, mes 1-12). Valida al vuelo segun se teclea."""
    digs = re.sub(r"\D", "", digs or "")
    out = ""
    for i, ch in enumerate(digs[:8]):
        if i == 0 and ch > "3":                      # decena del dia: 0-3
            break
        if i == 1 and not (1 <= int(out[0] + ch) <= 31):   # dia completo 01-31
            break
        if i == 2 and ch > "1":                      # decena del mes: 0-1
            break
        if i == 3 and not (1 <= int(out[2] + ch) <= 12):   # mes completo 01-12
            break
        out += ch                                    # anio (i>=4): cualquier digito
    return out
