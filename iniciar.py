#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iniciar.py
==========

Arranca el programa SIN instalar nada. Es lo mismo que
`python panel_gestion_parcelas.py`, pero con un nombre fácil de encontrar (y
doble-clicable donde Python esté asociado a los .py).

Requiere Python y las dependencias (o funcionará en modo reducido). Para un
arranque aislado con todo instalado y un acceso directo, usa `instalar.py`.
"""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    # ejecuta el panel como si fuera el programa principal, sin instalar nada
    sys.argv[0] = str(Path(__file__).with_name("panel_gestion_parcelas.py"))
    runpy.run_path(sys.argv[0], run_name="__main__")
