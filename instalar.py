#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar.py
===========

Instala el «Gestor de Parcelas» en este equipo: prepara un entorno con las
dependencias y crea un ACCESO DIRECTO en el escritorio.

  python instalar.py                 # entorno virtual + dependencias + acceso directo
  python instalar.py --sin-venv      # usa el Python actual (si ya tienes las dependencias)
  python instalar.py --sin-acceso    # solo el entorno, sin acceso directo
  python instalar.py --sin-deps      # crea el entorno pero no instala dependencias

NO hace falta instalar para USAR el programa: ver `iniciar.py` o
`python panel_gestion_parcelas.py`. Desinstalar: `python desinstalar.py`.
"""

import argparse
import sys

import instalador as I


def main(argv=None):
    ap = argparse.ArgumentParser(description="Instala el Gestor de Parcelas y crea un acceso directo.")
    ap.add_argument("--sin-venv", action="store_true", help="usar el Python actual, sin crear entorno virtual")
    ap.add_argument("--sin-deps", action="store_true", help="no instalar dependencias en el entorno")
    ap.add_argument("--sin-acceso", action="store_true", help="no crear el acceso directo")
    args = ap.parse_args(argv)

    print(f"Instalando «{I.NOMBRE_APP}» para {I.sistema()} …")

    venv_dir = None
    if not args.sin_venv:
        venv_dir = I.crear_venv(con_deps=not args.sin_deps)
        if venv_dir:
            print(f"  · Entorno virtual: {venv_dir}")
    py = I.python_lanzador(venv_dir)
    print(f"  · Se arrancará con: {py}")

    registro = {"sistema": I.sistema(), "venv": str(venv_dir) if venv_dir else None,
                "python": str(py), "accesos": []}

    if not args.sin_acceso:
        try:
            creados = I.crear_acceso_directo(py)
            registro["accesos"] = creados
            for c in creados:
                print(f"  · Acceso directo: {c}")
        except Exception as e:
            print(f"  ! No se pudo crear el acceso directo: {e}")
            print("    Puedes arrancar igualmente con «python iniciar.py».")

    I.guardar_registro(registro)
    print("\n✔ Instalación terminada.")
    print(f"  Tus datos viven en: {I.carpeta_datos_texto()}  (no se tocan al desinstalar).")
    print("  Para quitarlo:  python desinstalar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
