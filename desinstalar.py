#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desinstalar.py
==============

Deshace lo que hizo `instalar.py`: quita el acceso directo y (opcionalmente) el
entorno virtual. NUNCA borra tus DATOS: `parcelas.db` vive en la carpeta de datos
del usuario y se queda donde está.

  python desinstalar.py                # quita accesos directos y el entorno virtual
  python desinstalar.py --conservar-venv   # quita solo los accesos, deja el entorno
"""

import argparse
import shutil
import sys
from pathlib import Path

import instalador as I


def main(argv=None):
    ap = argparse.ArgumentParser(description="Desinstala el Gestor de Parcelas (los datos NO se tocan).")
    ap.add_argument("--conservar-venv", action="store_true", help="no borrar el entorno virtual")
    args = ap.parse_args(argv)

    reg = I.leer_registro()
    if not reg:
        print("No hay registro de instalación (.instalacion.json). Nada que quitar.")
        print(f"Tus datos, por si acaso, siguen en: {I.carpeta_datos_texto()}")
        return 0

    n = I.quitar_accesos(reg)
    print(f"  · Accesos directos quitados: {n}")

    venv = reg.get("venv")
    if venv and not args.conservar_venv:
        try:
            if Path(venv).is_dir():
                shutil.rmtree(venv)
                print(f"  · Entorno virtual borrado: {venv}")
        except OSError as e:
            print(f"  ! No se pudo borrar el entorno virtual ({venv}): {e}")

    try:
        I.REGISTRO.unlink()
    except OSError:
        pass

    print("\n✔ Desinstalado.")
    print(f"  Tus DATOS se conservan intactos en: {I.carpeta_datos_texto()}")
    print("  (bórralos a mano solo si quieres eliminarlos del todo).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
