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


# =====================================================================
# HASTA DONDE LLEGA COPERNICUS, Y QUE HACER CON LO QUE HAY MAS ATRAS
# =====================================================================
# El limite no lo pone el programa, lo pone el satelite: la coleccion
# COPERNICUS/S2_SR_HARMONIZED empieza el 28-3-2017, asi que la primera campana
# con imagenes es la 2017-2018. Y el propio catalogo de Earth Engine avisa de que
# "2017-2018 L2 coverage in the EE collection is not yet global": en esa campana
# puede no haber nada segun la zona. Se ofrece igualmente, marcada, porque donde
# si hay cobertura es un ano mas de historico; la primera campana con cobertura
# completa es la 2018-2019.
#
# Una parcela puede tener guardadas campanas MAS ANTIGUAS que eso (importadas de
# otro sistema, o de una version anterior del programa). Esas no se pueden
# sincronizar -no hay de donde-, pero los datos estan y hay que poder verlos. Por
# eso `campanas_de_parcela` no filtra: devuelve la union, y marca cada una con lo
# que se puede hacer con ella.
PRIMERA_CAMPANA_S2 = "2017-2018"          # primera con imagenes (cobertura parcial)
PRIMERA_CAMPANA_S2_GLOBAL = "2018-2019"   # primera con cobertura completa


def campanas_sincronizables(fecha: Optional[datetime] = None,
                            desde: str = PRIMERA_CAMPANA_S2) -> List[str]:
    """Campanas que Copernicus puede servir hoy, de la mas reciente a la mas vieja."""
    return campanas_entre(desde, campana_actual(fecha))


def _anio(campana: Any, por_defecto: int = 0) -> int:
    try:
        return int(str(campana).split("-")[0])
    except (ValueError, TypeError, AttributeError):
        return por_defecto


def campanas_de_parcela(con_datos: Any = (), fecha: Optional[datetime] = None,
                        desde: str = PRIMERA_CAMPANA_S2) -> List[dict]:
    """Todas las campanas que ofrecer para una parcela, mas reciente primero.

    `con_datos` son las campanas que ya tienen pasadas guardadas. El resultado es
    la UNION de esas y las sincronizables, para que en la ficha aparezcan tanto
    las que se pueden descargar como las que ya se tienen aunque el satelite no
    llegue tan atras. Cada entrada es un dict:

        campana         'AAAA-BBBB'
        tiene_datos     ya hay pasadas guardadas de esa campana
        sincronizable   Copernicus la cubre: se puede descargar o completar
        parcial         cubierta a medias segun la zona (la 2017-2018)
        actual          es la campana en curso
        solo_archivo    hay datos pero no se puede sincronizar: solo consultarla

    `solo_archivo` es el caso que importa: dato que el programa tiene y no puede
    volver a pedir. Nunca se oculta -es lo unico que queda de esos anos-, pero se
    marca para que nadie espere poder actualizarlo."""
    actual = campana_actual(fecha)
    sincro = set(campanas_sincronizables(fecha, desde))
    datos = {c for c in (con_datos or ()) if c}
    a_global = _anio(PRIMERA_CAMPANA_S2_GLOBAL)
    salida = []
    for camp in sorted(sincro | datos, key=_anio, reverse=True):
        tiene = camp in datos
        puede = camp in sincro
        salida.append({"campana": camp,
                       "tiene_datos": tiene,
                       "sincronizable": puede,
                       "parcial": puede and _anio(camp) < a_global,
                       "actual": camp == actual,
                       "solo_archivo": tiene and not puede})
    return salida


def etiqueta_campana(c, n_pasadas=None):
    """Una linea que dice de un vistazo que se puede hacer con esa campana.

    Vive aqui, junto a `campanas_de_parcela`, que es quien decide `actual`,
    `solo_archivo`, `tiene_datos` y `parcial`: la frase que los describe y las
    banderas que describe se cambian a la vez o dejan de cuadrar. Estaba dentro de
    la ficha, y por eso los dialogos tenian que importar la ficha entera solo para
    formatear un texto."""
    marca = c["campana"]
    if c["actual"]:
        marca += "  ·  en curso"
    if c["solo_archivo"]:
        return marca + "  ·  solo archivo"
    if c["tiene_datos"]:
        return marca + (f"  ✓ {n_pasadas} pasadas" if n_pasadas else "  ✓ con datos")
    return marca + ("  ·  sin descargar (parcial)" if c["parcial"]
                    else "  ·  sin descargar")
