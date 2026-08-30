# -*- coding: utf-8 -*-
"""
empaquetar.py
=============

Crea un EJECUTABLE del programa con PyInstaller, para repartirlo a gente que no
tiene Python instalado: doble clic y se abre, sin instalar nada.

    python empaquetar.py

Deja el ejecutable en `dist/`. En Windows sale un `.exe`; en macOS un `.app`; en
Linux un binario. Es un paso de EMPAQUETADO, aparte del programa: no lo importa
nadie y borrarlo no afecta a nada.

Requisitos: `pip install pyinstaller` (mas las dependencias del programa que
quieras que lleve el ejecutable: tkintermapview, earthengine-api, matplotlib...).
Este script NO instala nada: solo comprueba que PyInstaller esta y lanza la
construccion con las opciones correctas (datos, icono, imports que el analisis
estatico de PyInstaller no ve por si solo).
"""

import os
import sys
import subprocess

DIR = os.path.dirname(os.path.abspath(__file__))
NOMBRE = "GestorParcelas"
ENTRADA = os.path.join(DIR, "panel_gestion_parcelas.py")   # tiene el if __name__ == "__main__"

# Ficheros de DATOS que deben viajar dentro del ejecutable (no son codigo).
DATOS = ["icono.png", "icono.ico", "MANUAL.md"]

# Modulos OPCIONALES (se importan con try/except) y librerias que PyInstaller a
# veces no detecta por el analisis estatico. Se declaran a mano para que no
# falten en el ejecutable.
IMPORTS_OCULTOS = [
    # modulos opcionales del propio programa
    "clima_era5", "calibracion_umbrales", "informe_anual", "herbicida_contexto",
    "grados_dia", "balance_hidrico", "heterogeneidad_espacial", "validacion",
    "copias",
    # librerias de terceros (opcionales) que se cargan de forma perezosa
    "tkintermapview", "PIL", "PIL.Image", "PIL.ImageTk",
    "matplotlib", "matplotlib.backends.backend_tkagg",
    "ee", "openpyxl", "reportlab", "keyring", "platformdirs",
]


def _sep():
    """Separador de --add-data: ';' en Windows, ':' en el resto (regla PyInstaller)."""
    return ";" if os.name == "nt" else ":"


def _datos_existentes():
    """Los ficheros de DATOS que de verdad existen (los que falten se omiten)."""
    return [d for d in DATOS if os.path.exists(os.path.join(DIR, d))]


# --- Ficheros de VERSION para Windows -------------------------------------
# Un .exe sin datos de version ni fabricante es, para un antivirus, un binario
# anonimo: puntua peor en los analisis heuristicos. Rellenarlos no firma nada
# -eso solo lo hace un certificado- pero quita uno de los motivos de sospecha.
def _version_info():
    from version import __version__
    n = [int(x) for x in (__version__.split(".") + ["0", "0", "0", "0"])[:4]]
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({n[0]}, {n[1]}, {n[2]}, {n[3]}),
                    prodvers=({n[0]}, {n[1]}, {n[2]}, {n[3]}),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[StringFileInfo([StringTable('040a04b0', [
            StringStruct('CompanyName', 'Gestor de Parcelas'),
            StringStruct('FileDescription', 'Seguimiento de parcelas agricolas por satelite'),
            StringStruct('FileVersion', '{__version__}'),
            StringStruct('InternalName', '{NOMBRE}'),
            StringStruct('OriginalFilename', '{NOMBRE}.exe'),
            StringStruct('ProductName', 'Gestor de Parcelas'),
            StringStruct('ProductVersion', '{__version__}')])]),
        VarFileInfo([VarStruct('Translation', [0x040a, 1200])])]
)
"""


def _escribir_version_info():
    """Deja el fichero de version junto al script y devuelve su ruta (o None si no
    se pudo). Solo tiene efecto en Windows; en el resto PyInstaller lo ignora."""
    ruta = os.path.join(DIR, "version_info.txt")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(_version_info())
        return ruta
    except OSError:
        return None


def _argumentos():
    """La lista de argumentos para PyInstaller (sin el ejecutable de python)."""
    # `--noupx`: UPX comprime el ejecutable, y los binarios comprimidos con UPX son
    # de lo que MAS dispara los antivirus (es la tecnica que usa medio malware para
    # ofuscarse). Renunciar a el hace el ejecutable mas grande pero mucho menos
    # sospechoso, que es justo lo que interesa aqui.
    args = ["--name", NOMBRE, "--windowed", "--noconfirm", "--clean", "--noupx"]
    if os.name == "nt":
        vi = _escribir_version_info()
        if vi:
            args += ["--version-file", vi]
    # icono: .ico en Windows; en el resto se intenta el .png (PyInstaller lo acepta
    # en Linux; en macOS querria .icns, y si no puede, sigue sin icono).
    ico = os.path.join(DIR, "icono.ico")
    png = os.path.join(DIR, "icono.png")
    if os.name == "nt" and os.path.exists(ico):
        args += ["--icon", ico]
    elif os.path.exists(png):
        args += ["--icon", png]
    for d in _datos_existentes():
        args += ["--add-data", f"{os.path.join(DIR, d)}{_sep()}."]
    for m in IMPORTS_OCULTOS:
        args += ["--hidden-import", m]
    args.append(ENTRADA)
    return args


def main():
    # `find_spec` en vez de `import PyInstaller`: aqui solo interesa SI esta, y el
    # import a secas deja una variable sin usar que el linter marca con razon
    # (pyflakes no atiende a `# noqa`). Ademas no carga el paquete, que no hace
    # falta: quien construye de verdad es el subproceso de mas abajo.
    import importlib.util
    if importlib.util.find_spec("PyInstaller") is None:
        print("Falta PyInstaller. Instalalo con:\n\n    pip install pyinstaller\n")
        return 1
    if not os.path.exists(ENTRADA):
        print(f"No encuentro el punto de entrada: {ENTRADA}")
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", *_argumentos()]
    print("Construyendo el ejecutable...\n  " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, cwd=DIR)
    if r.returncode == 0:
        print(f"\nListo. El ejecutable esta en: {os.path.join(DIR, 'dist', NOMBRE)}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
