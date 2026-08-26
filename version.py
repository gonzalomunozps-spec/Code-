# -*- coding: utf-8 -*-
"""
version.py
==========

La version del programa, en UN solo sitio. La leen `pyproject.toml` (para el
empaquetado), el arranque (`panel_gestion_parcelas --version`) y quien quiera
mostrarla. Cambiarla aqui la cambia en todas partes.

No confundir con `almacen.ESQUEMA_VERSION`, que versiona el ESQUEMA de la base de
datos y sube cada vez que cambia una tabla; esta versiona el PROGRAMA.

Se sigue SemVer (https://semver.org): MAYOR.MENOR.PARCHE.
  - MAYOR  cambia cuando se rompe la compatibilidad de datos o de uso.
  - MENOR  cuando se anade una funcion sin romper nada.
  - PARCHE cuando solo se corrigen fallos.
"""

__version__ = "1.7.0"
