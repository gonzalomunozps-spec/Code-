# -*- coding: utf-8 -*-
"""
herbicida_contexto.py
=====================

Pieza OPCIONAL y DESACOPLADA del cuaderno de campo.

Cuando un herbicida deja el LAI/NDVI CONSTANTE, el resultado es ambiguo. Este
modulo intenta desambiguarlo usando el contexto de la propia serie (dispersion
intraparcela y tendencia previa del LAI), sin datos externos.

COMO QUITAR ESTA PARTE:
  Basta con BORRAR este fichero. `registro_parcela.efecto_producto` lo importa de
  forma tolerante (try/except): si no existe, el veredicto de un herbicida con LAI
  constante vuelve al comportamiento base ("sin cambio claro"). No hay interruptor
  ni configuracion que tocar; el resto del programa sigue funcionando igual.
"""


def verdicto_lai_constante(d_std, lai_subia_antes):
    """Interpretacion de un herbicida con LAI/NDVI plano, a partir del contexto:

      - d_std: variacion de la dispersion intraparcela del NDVI (resp - base).
               Si BAJA de forma clara, la parcela se homogeneiza -> compatible con
               limpieza de rodales de mala hierba conservando la cobertura.
      - lai_subia_antes: True si el LAI venia subiendo justo antes de la aplicacion
               y despues se estanca -> el tratamiento pudo frenar la vegetacion.

    Devuelve un veredicto (str) o None si no hay contexto util (en cuyo caso el
    llamador usa su texto base 'sin cambio claro').
    """
    if d_std is not None and d_std < -0.02:
        return (f"efecto probable: el area foliar se mantiene pero la parcela se HOMOGENEIZA "
                f"(dispersion {d_std:+.3f}); compatible con limpieza de rodales de mala hierba "
                "conservando la cobertura del cultivo")
    if lai_subia_antes:
        return ("efecto probable: el LAI venia SUBIENDO y se estanca tras el herbicida; el "
                "tratamiento pudo frenar vegetacion (maleza controlada o fitotoxicidad)")
    return None
